from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(__file__).resolve().parent
DATA = json.loads((BASE_DIR / "data.json").read_text(encoding="utf-8"))


class _Handler(BaseHTTPRequestHandler):

    def log_message(self, *args: Any) -> None:
        return

    def _send_json(self, obj: Any, code: int = 200) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        body = path.read_bytes()
        ctype = "text/html; charset=utf-8"
        if path.suffix == ".json":
            ctype = "application/json; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/state":
            self._send_json(self.server.owner.flags)
            return
        if path == "/api/hana/txns":
            qs = parse_qs(parsed.query)
            start = qs.get("from", ["00000000"])[0]
            end = qs.get("to", ["99991231"])[0]
            page = int(qs.get("page", ["1"])[0])
            rows = [
                r
                for r in DATA["txns"]
                if start <= r["date"] <= end
            ] if not self.server.owner.flags.get("hana_empty") else []
            per = 10
            pages = max(1, -(-len(rows) // per)) if rows else 1
            page = max(1, min(page, pages))
            chunk = rows[(page - 1) * per : page * per]
            self._send_json({"rows": chunk, "page": page, "pages": pages, "total": len(rows)})
            return
        if path == "/api/deel/expenses":
            self._send_json(self.server.owner.deel_submissions)
            return
        if path.startswith("/api/"):
            self._send_json({"error": "not found"}, 404)
            return
        if path in ("", "/"):
            path = "/hana/login.html"
        fpath = (BASE_DIR / path.lstrip("/")).resolve()
        if not str(fpath).startswith(str(BASE_DIR)) or not fpath.is_file():
            self.send_response(404)
            self.end_headers()
            return
        self._send_file(fpath)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/deel/expenses":
            self._send_json({"error": "not found"}, 404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        if self.server.owner.flags.get("deel_slow"):
            time.sleep(3)
        self.server.owner.deel_counter += 1
        ref = f"EXP-{self.server.owner.deel_counter}"
        self.server.owner.deel_submissions.append({**payload, "ref": ref})
        self._send_json({"ref": ref})


class MockServer:
    def __init__(self) -> None:
        self.flags: dict[str, Any] = {
            "hana_session_expired": False,
            "hana_captcha": False,
            "hana_selector_drift": False,
            "hana_empty": False,
            "deel_session_expired": False,
            "deel_form_error": False,
            "deel_slow": False,
        }
        self.deel_submissions: list[dict[str, Any]] = []
        self.deel_counter = 0
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._httpd.daemon_threads = True
        self._httpd.owner = self
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    def set_flag(self, name: str, value: Any = True) -> None:
        self.flags[name] = value

    def reset(self) -> None:
        for k in self.flags:
            self.flags[k] = False
        self.deel_submissions.clear()
        self.deel_counter = 0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread:
            self._thread.join(timeout=5)
        self._thread = None

    def __enter__(self) -> "MockServer":
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()
