from __future__ import annotations

from abc import ABC, abstractmethod
import time


class TransportAdapter(ABC):
    def health_check(self) -> dict:
        return {"online": True, "transport": type(self).__name__}

    @abstractmethod
    def send_payload(self, payload: bytes, metadata: dict | None = None) -> tuple[bytes, dict]:
        raise NotImplementedError


class LoopbackTransport(TransportAdapter):
    def __init__(self, chunk_size: int = 16 * 1024, delay_ms: float = 0, loss_rate: float = 0):
        if chunk_size <= 0 or int(chunk_size) != chunk_size:
            raise ValueError("chunk_size must be a positive integer")
        if delay_ms < 0 or not 0 <= loss_rate < 1:
            raise ValueError("delay_ms must be >= 0 and loss_rate must be in [0, 1)")
        self.chunk_size = int(chunk_size)
        self.delay_ms = float(delay_ms)
        self.loss_rate = float(loss_rate)

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
            # A zero loss rate is deterministic; nonzero loss is intentionally a smoke-test simulation.
            import random
            if self.loss_rate and random.random() < self.loss_rate:
                lost_chunks += 1
                continue
            chunks.append(bytes(chunk))
        received = b"".join(chunks)
        elapsed_ms = (time.perf_counter() - start) * 1000
        seconds = max(elapsed_ms / 1000, 1e-9)
        average_mbps = len(received) * 8 / seconds / 1_000_000
        stats = {
            "transport": "loopback",
            "run_id": metadata.get("run_id"),
            "sent_bytes": len(payload),
            "received_bytes": len(received),
            "chunk_size": self.chunk_size,
            "chunk_count": chunk_count,
            "lost_chunks": lost_chunks,
            "loss_rate": self.loss_rate,
            "delay_ms_per_chunk": self.delay_ms,
            "elapsed_ms": round(elapsed_ms, 3),
            "average_throughput_mbps": round(average_mbps, 3),
            "peak_throughput_mbps": round(average_mbps, 3),
        }
        return received, stats


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

    def send_payload(self, payload: bytes, metadata: dict | None = None) -> tuple[bytes, dict]:
        return self.implementation.send_payload(payload, metadata or {})
