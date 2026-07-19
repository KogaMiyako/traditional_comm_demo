from __future__ import annotations

import argparse
import json
from pathlib import Path
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from .web_adapter import WebRunManager


WEB_ROOT = Path(__file__).resolve().parent.parent / "web"


class DashboardHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(self, address, manager: WebRunManager):
        super().__init__(address, DashboardHandler)
        self.manager = manager


class DashboardHandler(BaseHTTPRequestHandler):
    server: DashboardHTTPServer

    def _send_json(self, value, status: int = 200) -> None:
        body = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, status: int, message: str) -> None:
        self._send_json({"error": message, "status": status}, status)

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if length > 1024 * 1024:
            raise ValueError("request body is too large")
        body = self.rfile.read(length)
        if not body:
            return {}
        value = json.loads(body.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("request body must be a JSON object")
        return value

    def _route_parts(self) -> list[str]:
        path = unquote(urlparse(self.path).path)
        return [part for part in path.split("/") if part]

    def _api_get(self, parts: list[str]) -> None:
        manager = self.server.manager
        if parts == ["api", "health"]:
            self._send_json(
                {
                    "online": True,
                    "service": "traditional-communication-web",
                    "samples_dir": str(manager.samples_dir),
                    "runs_dir": str(manager.runs_dir),
                }
            )
            return
        if parts == ["api", "samples"]:
            self._send_json({"samples": manager.list_samples()})
            return
        if parts == ["api", "runs"]:
            self._send_json({"runs": manager.list_runs()})
            return
        if len(parts) >= 3 and parts[0:2] == ["api", "runs"]:
            run_id = parts[2]
            if len(parts) == 4 and parts[3] == "status":
                self._send_json(manager.get_status(run_id))
                return
            if len(parts) == 4 and parts[3] == "metrics":
                self._send_json({"metrics": manager.get_metrics(run_id)})
                return
            if len(parts) == 4 and parts[3] == "result":
                self._send_json({"result": manager.get_result(run_id)})
                return
            if len(parts) == 4 and parts[3] == "error":
                self._send_json(manager.get_error(run_id))
                return
            if len(parts) == 4 and parts[3] == "events":
                self._send_json({"events": manager.get_events(run_id)})
                return
            if len(parts) == 5 and parts[3] == "files":
                self._send_file(manager.get_file(run_id, parts[4]))
                return
        self._send_error_json(404, "API endpoint not found")

    def _api_post(self, parts: list[str]) -> None:
        manager = self.server.manager
        body = self._read_json()
        if parts == ["api", "runs", "start"]:
            self._send_json(manager.start_run(body), 202)
            return
        if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "cancel":
            self._send_json(manager.cancel_run(parts[2]))
            return
        self._send_error_json(404, "API endpoint not found")

    def _send_file(self, path: Path) -> None:
        body = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix.lower() == ".mp4":
            content_type = "video/mp4"
        elif path.suffix.lower() in {".jpg", ".jpeg"}:
            content_type = "image/jpeg"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, path: str) -> None:
        relative = "index.html" if path in {"", "/"} else path.lstrip("/")
        candidate = (WEB_ROOT / relative).resolve()
        if WEB_ROOT.resolve() not in candidate.parents and candidate != WEB_ROOT.resolve():
            self._send_error_json(404, "static file not found")
            return
        if not candidate.is_file():
            self._send_error_json(404, "static file not found")
            return
        self._send_file(candidate)

    def do_GET(self) -> None:
        try:
            parts = self._route_parts()
            if parts and parts[0] == "api":
                self._api_get(parts)
            else:
                self._send_static(urlparse(self.path).path)
        except KeyError:
            self._send_error_json(404, "run_id not found")
        except FileNotFoundError as exc:
            self._send_error_json(404, str(exc))
        except ValueError as exc:
            self._send_error_json(400, str(exc))
        except Exception as exc:
            self._send_error_json(500, str(exc))

    def do_POST(self) -> None:
        try:
            parts = self._route_parts()
            self._api_post(parts)
        except KeyError:
            self._send_error_json(404, "run_id not found")
        except FileNotFoundError as exc:
            self._send_error_json(404, str(exc))
        except ValueError as exc:
            self._send_error_json(400, str(exc))
        except Exception as exc:
            self._send_error_json(500, str(exc))

    def log_message(self, format: str, *args) -> None:
        print(f"[web] {self.address_string()} - {format % args}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Traditional communication Web dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--samples", type=Path, default=Path(__file__).resolve().parents[1] / "samples")
    parser.add_argument("--runs", type=Path, default=Path(__file__).resolve().parents[1] / "runs")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    manager = WebRunManager(args.samples, args.runs)
    server = DashboardHTTPServer((args.host, args.port), manager)
    print(f"Traditional communication Web dashboard: http://{args.host}:{args.port}/")
    print(f"Samples: {manager.samples_dir}")
    print(f"Runs: {manager.runs_dir}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Web dashboard stopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
