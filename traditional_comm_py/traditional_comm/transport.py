from __future__ import annotations

from abc import ABC, abstractmethod
import hashlib
import json
from pathlib import Path
import re
import socket
import struct
import time
import uuid


PROTOCOL_NAME = "semcom-traditional-tcp-v1"
HEADER_LENGTH = struct.Struct("!I")
MAX_HEADER_BYTES = 1024 * 1024
DEFAULT_MAX_PAYLOAD_BYTES = 512 * 1024 * 1024
SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_name(value: object, fallback: str) -> str:
    text = str(value or fallback)
    if not SAFE_NAME.fullmatch(text):
        return fallback
    return text


def _send_message(sock: socket.socket, header: dict, payload: bytes = b"") -> int:
    header = dict(header)
    header["payload_size"] = len(payload)
    encoded_header = json.dumps(header, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if not encoded_header or len(encoded_header) > MAX_HEADER_BYTES:
        raise ValueError("message header is empty or too large")
    frame = HEADER_LENGTH.pack(len(encoded_header)) + encoded_header + payload
    sock.sendall(frame)
    return len(frame)


def _receive_exact(sock: socket.socket, size: int) -> bytes:
    if size < 0:
        raise ValueError("receive size must not be negative")
    result = bytearray()
    while len(result) < size:
        block = sock.recv(min(1024 * 1024, size - len(result)))
        if not block:
            raise ConnectionError(
                f"connection closed before receiving the complete frame "
                f"({len(result)}/{size} bytes)"
            )
        result.extend(block)
    return bytes(result)


def _receive_message(sock: socket.socket, max_payload_bytes: int) -> tuple[dict, bytes, int]:
    prefix = _receive_exact(sock, HEADER_LENGTH.size)
    header_size = HEADER_LENGTH.unpack(prefix)[0]
    if header_size <= 0 or header_size > MAX_HEADER_BYTES:
        raise ValueError(f"invalid message header size: {header_size}")
    encoded_header = _receive_exact(sock, header_size)
    try:
        header = json.loads(encoded_header.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid JSON message header") from exc
    if not isinstance(header, dict):
        raise ValueError("message header must be a JSON object")
    try:
        payload_size = int(header.get("payload_size", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("payload_size must be an integer") from exc
    if payload_size < 0 or payload_size > max_payload_bytes:
        raise ValueError(f"payload_size is outside the allowed range: {payload_size}")
    payload = _receive_exact(sock, payload_size)
    return header, payload, HEADER_LENGTH.size + header_size + payload_size


def _throughput_mbps(byte_count: int, elapsed_ms: float) -> float:
    seconds = max(elapsed_ms / 1000, 1e-9)
    return round(byte_count * 8 / seconds / 1_000_000, 3)


class TransportAdapter(ABC):
    def health_check(self) -> dict:
        return {"online": True, "transport": type(self).__name__}

    def configure_link(self, link_config: dict | None = None) -> dict:
        return {"configured": True, "link_config": link_config or {}}

    @abstractmethod
    def send_payload(self, payload: bytes, metadata: dict | None = None) -> tuple[bytes, dict]:
        raise NotImplementedError

    def receive_payload(self, run_context: dict | None = None) -> tuple[bytes, dict]:
        raise NotImplementedError(f"{type(self).__name__} does not provide a pull receiver")

    def close_link(self, run_id: str | None = None) -> dict:
        return {"closed": True, "run_id": run_id}

    def get_link_status(self, run_id: str | None = None) -> dict:
        return {"online": True, "transport": type(self).__name__, "run_id": run_id}

    def get_transport_stats(self, run_id: str | None = None) -> dict:
        return {"run_id": run_id, "transport": type(self).__name__}


class LoopbackTransport(TransportAdapter):
    def __init__(self, chunk_size: int = 16 * 1024, delay_ms: float = 0, loss_rate: float = 0):
        if chunk_size <= 0 or int(chunk_size) != chunk_size:
            raise ValueError("chunk_size must be a positive integer")
        if delay_ms < 0 or not 0 <= loss_rate < 1:
            raise ValueError("delay_ms must be >= 0 and loss_rate must be in [0, 1)")
        self.chunk_size = int(chunk_size)
        self.delay_ms = float(delay_ms)
        self.loss_rate = float(loss_rate)
        self._last_stats: dict = {}

    def send_payload(self, payload: bytes, metadata: dict | None = None) -> tuple[bytes, dict]:
        metadata = metadata or {}
        start = time.perf_counter()
        chunks: list[bytes] = []
        lost_chunks = 0
        chunk_count = (len(payload) + self.chunk_size - 1) // self.chunk_size
        for offset in range(0, len(payload), self.chunk_size):
            chunk = payload[offset : offset + self.chunk_size]
            if self.delay_ms:
                time.sleep(self.delay_ms / 1000)
            import random

            if self.loss_rate and random.random() < self.loss_rate:
                lost_chunks += 1
                continue
            chunks.append(bytes(chunk))
        received = b"".join(chunks)
        elapsed_ms = (time.perf_counter() - start) * 1000
        average_mbps = _throughput_mbps(len(received), elapsed_ms)
        stats = {
            "transport": "loopback",
            "run_id": metadata.get("run_id"),
            "sent_bytes": len(payload),
            "received_bytes": len(received),
            "wire_sent_bytes": len(payload),
            "wire_received_bytes": len(received),
            "actual_link_total_bytes": len(payload),
            "chunk_size": self.chunk_size,
            "chunk_count": chunk_count,
            "lost_chunks": lost_chunks,
            "loss_rate": self.loss_rate,
            "elapsed_ms": round(elapsed_ms, 3),
            "average_throughput_mbps": average_mbps,
            "peak_throughput_mbps": average_mbps,
            "receiver_decode_valid": True,
        }
        self._last_stats = stats
        return received, stats

    def get_transport_stats(self, run_id: str | None = None) -> dict:
        stats = dict(self._last_stats)
        if run_id is not None:
            stats["run_id"] = run_id
        return stats


class LanTcpTransport(TransportAdapter):
    """TCP sender adapter for a separate LAN receiver process.

    The receiver acknowledges the payload instead of echoing it back. The
    returned payload is the locally encoded payload so the existing runner can
    keep its validation flow; receiver-side decode status is included in stats.
    """

    def __init__(
        self,
        remote_host: str,
        remote_port: int,
        connect_timeout_ms: int = 5000,
        receive_timeout_ms: int = 30000,
        max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
    ):
        if not remote_host:
            raise ValueError("remote_host must not be empty")
        if not 1 <= int(remote_port) <= 65535:
            raise ValueError("remote_port must be between 1 and 65535")
        if connect_timeout_ms <= 0 or receive_timeout_ms <= 0:
            raise ValueError("timeouts must be positive")
        if max_payload_bytes <= 0:
            raise ValueError("max_payload_bytes must be positive")
        self.remote_host = str(remote_host)
        self.remote_port = int(remote_port)
        self.connect_timeout_ms = int(connect_timeout_ms)
        self.receive_timeout_ms = int(receive_timeout_ms)
        self.max_payload_bytes = int(max_payload_bytes)
        self._last_stats: dict = {}

    def _connection(self) -> socket.socket:
        sock = socket.create_connection(
            (self.remote_host, self.remote_port),
            timeout=self.connect_timeout_ms / 1000,
        )
        sock.settimeout(self.receive_timeout_ms / 1000)
        return sock

    def health_check(self) -> dict:
        started = time.perf_counter()
        try:
            with self._connection() as sock:
                _send_message(
                    sock,
                    {
                        "protocol": PROTOCOL_NAME,
                        "message_type": "health_check",
                        "run_id": f"health-{uuid.uuid4().hex[:8]}",
                    },
                )
                ack, payload, _ = _receive_message(sock, self.max_payload_bytes)
                if payload or ack.get("message_type") != "ack" or not ack.get("accepted"):
                    raise ConnectionError("invalid health-check acknowledgement")
        except OSError as exc:
            return {
                "online": False,
                "transport": "lan-tcp",
                "remote_host": self.remote_host,
                "remote_port": self.remote_port,
                "error": str(exc),
            }
        return {
            "online": True,
            "transport": "lan-tcp",
            "remote_host": self.remote_host,
            "remote_port": self.remote_port,
            "check_time_ms": round((time.perf_counter() - started) * 1000, 3),
        }

    def configure_link(self, link_config: dict | None = None) -> dict:
        link_config = link_config or {}
        return {
            "configured": True,
            "transport": "lan-tcp",
            "remote_host": self.remote_host,
            "remote_port": self.remote_port,
            "link_config": link_config,
        }

    def send_payload(self, payload: bytes, metadata: dict | None = None) -> tuple[bytes, dict]:
        if not isinstance(payload, bytes):
            raise TypeError("payload must be bytes")
        if len(payload) > self.max_payload_bytes:
            raise ValueError("payload exceeds max_payload_bytes")
        metadata = dict(metadata or {})
        run_id = _safe_name(metadata.get("run_id"), f"anonymous-{uuid.uuid4().hex[:8]}")
        message = {
            "protocol": PROTOCOL_NAME,
            "message_type": "payload",
            "run_id": run_id,
            "mode": metadata.get("mode", "traditional"),
            "media_type": metadata.get("media_type"),
            "sample_id": metadata.get("sample_id"),
            "task_id": metadata.get("task_id"),
            "codec": metadata.get("codec"),
            "container": metadata.get("container"),
            "codec_metadata": metadata.get("codec_metadata", {}),
            "payload_size": len(payload),
            "expected_total_bytes": metadata.get("expected_total_bytes", len(payload)),
            "sequence_id": metadata.get("sequence_id", 0),
            "sha256": _sha256(payload),
        }
        started = time.perf_counter()
        with self._connection() as sock:
            wire_sent_bytes = _send_message(sock, message, payload)
            ack, ack_payload, wire_received_bytes = _receive_message(
                sock, self.max_payload_bytes
            )
        elapsed_ms = (time.perf_counter() - started) * 1000
        if ack.get("protocol") != PROTOCOL_NAME or ack.get("message_type") != "ack":
            raise ConnectionError("invalid TCP receiver acknowledgement")
        if ack.get("run_id") != run_id:
            raise ConnectionError("TCP receiver acknowledgement has the wrong run_id")
        if ack_payload:
            raise ConnectionError("TCP receiver acknowledgement must not contain a payload")
        if not ack.get("accepted"):
            raise ConnectionError(str(ack.get("error") or "TCP receiver rejected payload"))
        if ack.get("sha256") != message["sha256"]:
            raise ConnectionError("TCP receiver checksum does not match sender checksum")
        receiver_decode_valid = ack.get("receiver_decode_valid")
        stats = {
            "transport": "lan-tcp",
            "protocol": PROTOCOL_NAME,
            "run_id": run_id,
            "remote_host": self.remote_host,
            "remote_port": self.remote_port,
            "sent_bytes": len(payload),
            "received_bytes": int(ack.get("received_bytes", len(payload))),
            "wire_sent_bytes": wire_sent_bytes,
            "wire_received_bytes": wire_received_bytes,
            "actual_link_total_bytes": wire_sent_bytes + wire_received_bytes,
            "chunk_count": 1,
            "lost_chunks": 0,
            "loss_rate": 0.0,
            "elapsed_ms": round(elapsed_ms, 3),
            "average_throughput_mbps": _throughput_mbps(len(payload), elapsed_ms),
            "peak_throughput_mbps": _throughput_mbps(len(payload), elapsed_ms),
            "acknowledged": True,
            "receiver_decode_valid": receiver_decode_valid,
            "receiver_decode_time_ms": ack.get("receiver_decode_time_ms"),
            "receiver_result_path": ack.get("receiver_result_path"),
            "receiver_error": ack.get("receiver_error"),
        }
        self._last_stats = stats
        return payload, stats

    def get_link_status(self, run_id: str | None = None) -> dict:
        status = self.health_check()
        status["run_id"] = run_id
        return status

    def get_transport_stats(self, run_id: str | None = None) -> dict:
        stats = dict(self._last_stats)
        if run_id is not None:
            stats["run_id"] = run_id
        return stats


class LanTcpReceiver:
    """Receiver service for LanTcpTransport."""

    def __init__(
        self,
        bind_host: str = "0.0.0.0",
        port: int = 5000,
        output_dir: Path | None = None,
        backlog: int = 8,
        max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
    ):
        if not 0 <= int(port) <= 65535:
            raise ValueError("port must be between 0 and 65535")
        if backlog <= 0:
            raise ValueError("backlog must be positive")
        if max_payload_bytes <= 0:
            raise ValueError("max_payload_bytes must be positive")
        self.bind_host = str(bind_host)
        self.port = int(port)
        self.output_dir = Path(output_dir or "runs_receiver").resolve()
        self.backlog = int(backlog)
        self.max_payload_bytes = int(max_payload_bytes)
        self._server_socket: socket.socket | None = None
        self._last_stats: dict = {}

    @property
    def address(self) -> tuple[str, int]:
        if self._server_socket is None:
            return self.bind_host, self.port
        host, port = self._server_socket.getsockname()[:2]
        return str(host), int(port)

    def start(self) -> dict:
        if self._server_socket is not None:
            return {"online": True, "transport": "lan-tcp-receiver", "address": self.address}
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self.bind_host, self.port))
        server.listen(self.backlog)
        server.settimeout(0.5)
        self._server_socket = server
        return {"online": True, "transport": "lan-tcp-receiver", "address": self.address}

    def health_check(self) -> dict:
        return {
            "online": self._server_socket is not None,
            "transport": "lan-tcp-receiver",
            "address": self.address,
        }

    def close(self) -> dict:
        if self._server_socket is not None:
            self._server_socket.close()
            self._server_socket = None
        return {"closed": True, "transport": "lan-tcp-receiver"}

    def _store_payload(self, header: dict, payload: bytes, peer: tuple) -> dict:
        run_id = _safe_name(header.get("run_id"), f"received-{uuid.uuid4().hex[:8]}")
        container = _safe_name(header.get("container"), "bin")
        media_type = header.get("media_type")
        run_dir = self.output_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        received_path = run_dir / f"received_payload.{container}"
        output_path = run_dir / f"output.{container}"
        received_path.write_bytes(payload)
        output_path.write_bytes(payload)

        receiver_decode_valid: bool | None = None
        receiver_decode_time_ms: float | None = None
        receiver_error: str | None = None
        decoded_path: Path | None = None
        decode_start = time.perf_counter()
        try:
            if media_type not in {"text", "image", "video"}:
                raise ValueError(f"unsupported media_type: {media_type}")
            from .codecs import decode_payload

            decoded = decode_payload(media_type, payload, header.get("codec_metadata", {}))
            decoded_extension = {"text": "txt", "image": "ppm", "video": "tvid"}[media_type]
            decoded_path = run_dir / f"decoded.{decoded_extension}"
            decoded_path.write_bytes(decoded)
            receiver_decode_valid = True
        except Exception as exc:
            receiver_decode_valid = False
            receiver_error = str(exc)
        receiver_decode_time_ms = round((time.perf_counter() - decode_start) * 1000, 3)
        result = {
            "run_id": run_id,
            "peer": {"host": peer[0], "port": peer[1]},
            "media_type": media_type,
            "codec": header.get("codec"),
            "container": container,
            "received_bytes": len(payload),
            "sha256": _sha256(payload),
            "received_path": str(received_path),
            "output_path": str(output_path),
            "decoded_path": str(decoded_path) if decoded_path else None,
            "receiver_decode_valid": receiver_decode_valid,
            "receiver_decode_time_ms": receiver_decode_time_ms,
            "receiver_error": receiver_error,
        }
        (run_dir / "receiver_result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        result["receiver_result_path"] = str(run_dir / "receiver_result.json")
        return result

    def _handle_connection(self, connection: socket.socket, peer: tuple) -> dict:
        started = time.perf_counter()
        try:
            header, payload, _wire_received = _receive_message(
                connection, self.max_payload_bytes
            )
            if header.get("protocol") != PROTOCOL_NAME:
                raise ValueError("unsupported TCP protocol")
            if header.get("message_type") == "health_check":
                ack = {
                    "protocol": PROTOCOL_NAME,
                    "message_type": "ack",
                    "run_id": _safe_name(header.get("run_id"), "health"),
                    "accepted": True,
                    "complete": True,
                    "received_bytes": 0,
                    "sha256": None,
                    "receiver_decode_valid": True,
                }
                self._last_stats = {
                    "transport": "lan-tcp-receiver",
                    "protocol": PROTOCOL_NAME,
                    "message_type": "health_check",
                    "accepted": True,
                    "run_id": ack["run_id"],
                    "received_bytes": 0,
                    "receiver_decode_valid": True,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                }
                _send_message(connection, ack)
                return self._last_stats
            if header.get("message_type") != "payload":
                raise ValueError("expected payload or health_check message")
            expected_size = int(header.get("expected_total_bytes", len(payload)))
            if expected_size != len(payload):
                raise ValueError(
                    f"payload size mismatch: expected {expected_size}, got {len(payload)}"
                )
            if header.get("sha256") != _sha256(payload):
                raise ValueError("payload checksum mismatch")
            result = self._store_payload(header, payload, peer)
            ack = {
                "protocol": PROTOCOL_NAME,
                "message_type": "ack",
                "run_id": _safe_name(header.get("run_id"), "unknown"),
                "accepted": True,
                "complete": True,
                "received_bytes": len(payload),
                "sha256": result["sha256"],
                "receiver_decode_valid": result["receiver_decode_valid"],
                "receiver_decode_time_ms": result["receiver_decode_time_ms"],
                "receiver_result_path": result["receiver_result_path"],
                "receiver_error": result["receiver_error"],
            }
        except Exception as exc:
            ack = {
                "protocol": PROTOCOL_NAME,
                "message_type": "ack",
                "run_id": _safe_name(locals().get("header", {}).get("run_id"), "unknown"),
                "accepted": False,
                "complete": False,
                "received_bytes": 0,
                "sha256": None,
                "receiver_decode_valid": False,
                "error": str(exc),
            }
        _send_message(connection, ack)
        stats = {
            "transport": "lan-tcp-receiver",
            "protocol": PROTOCOL_NAME,
            "message_type": "payload",
            "peer_host": peer[0],
            "peer_port": peer[1],
            "accepted": ack["accepted"],
            "run_id": ack.get("run_id"),
            "received_bytes": ack.get("received_bytes", 0),
            "receiver_decode_valid": ack.get("receiver_decode_valid"),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        }
        self._last_stats = stats
        return stats

    def serve_once(self) -> dict:
        if self._server_socket is None:
            self.start()
        assert self._server_socket is not None
        while True:
            try:
                connection, peer = self._server_socket.accept()
                break
            except TimeoutError:
                continue
        with connection:
            connection.settimeout(30)
            return self._handle_connection(connection, peer)

    def serve_forever(self, max_connections: int | None = None, stop_event=None) -> list[dict]:
        if max_connections is not None and max_connections < 0:
            raise ValueError("max_connections must be non-negative or None")
        if self._server_socket is None:
            self.start()
        results: list[dict] = []
        while max_connections is None or len(results) < max_connections:
            if stop_event is not None and stop_event.is_set():
                break
            try:
                result = self.serve_once()
            except OSError:
                if self._server_socket is None:
                    break
                raise
            if result.get("message_type") == "payload":
                results.append(result)
        return results

    def get_transport_stats(self, run_id: str | None = None) -> dict:
        stats = dict(self._last_stats)
        if run_id is not None:
            stats["run_id"] = run_id
        return stats


class Task3Transport(TransportAdapter):
    """Adapter seam for the future task-3 communication link."""

    def __init__(self, implementation):
        if implementation is None or not hasattr(implementation, "send_payload"):
            raise ValueError("Task3Transport requires an implementation with send_payload()")
        self.implementation = implementation

    def health_check(self) -> dict:
        if hasattr(self.implementation, "health_check"):
            return self.implementation.health_check()
        return {"online": True, "transport": "task3-adapter"}

    def configure_link(self, link_config: dict | None = None) -> dict:
        if hasattr(self.implementation, "configure_link"):
            return self.implementation.configure_link(link_config or {})
        return {"configured": True, "transport": "task3-adapter"}

    def send_payload(self, payload: bytes, metadata: dict | None = None) -> tuple[bytes, dict]:
        return self.implementation.send_payload(payload, metadata or {})

    def close_link(self, run_id: str | None = None) -> dict:
        if hasattr(self.implementation, "close_link"):
            return self.implementation.close_link(run_id)
        return {"closed": True, "transport": "task3-adapter", "run_id": run_id}

    def get_link_status(self, run_id: str | None = None) -> dict:
        if hasattr(self.implementation, "get_link_status"):
            return self.implementation.get_link_status(run_id)
        return {"online": True, "transport": "task3-adapter", "run_id": run_id}

    def get_transport_stats(self, run_id: str | None = None) -> dict:
        if hasattr(self.implementation, "get_transport_stats"):
            return self.implementation.get_transport_stats(run_id)
        return {"transport": "task3-adapter", "run_id": run_id}
