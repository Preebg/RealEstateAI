#!/usr/bin/env python3
"""Always-on lightweight proxy: wake Docker on demand, then forward to FastAPI."""

from __future__ import annotations

import http.client
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

UPSTREAM_HOST = os.getenv("WAKE_PROXY_UPSTREAM_HOST", "127.0.0.1")
UPSTREAM_PORT = int(os.getenv("WAKE_PROXY_UPSTREAM_PORT", "8000"))
LISTEN_HOST = os.getenv("WAKE_PROXY_HOST", "127.0.0.1")
LISTEN_PORT = int(os.getenv("WAKE_PROXY_PORT", "8088"))
HEALTH_URL = f"http://{UPSTREAM_HOST}:{UPSTREAM_PORT}/api/health"
ROOT = Path(__file__).resolve().parents[1]
WAKE_SCRIPT = ROOT / "scripts" / "wake_stack.cmd"


def _upstream_healthy() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=2) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False


def _wake_stack() -> bool:
    if not WAKE_SCRIPT.is_file():
        return False
    subprocess.run(
        ["cmd.exe", "/c", str(WAKE_SCRIPT)],
        cwd=str(ROOT),
        check=False,
    )
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if _upstream_healthy():
            return True
        time.sleep(2)
    return False


def _ensure_stack() -> bool:
    if _upstream_healthy():
        return True
    return _wake_stack()


class WakeProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        return

    def _forward(self) -> None:
        if not _ensure_stack():
            self.send_error(503, "API stack is starting; retry shortly")
            return

        content_length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(content_length) if content_length > 0 else None
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in {"host", "content-length", "connection"}
        }

        try:
            conn = http.client.HTTPConnection(
                UPSTREAM_HOST,
                UPSTREAM_PORT,
                timeout=120,
            )
            conn.request(self.command, self.path, body=body, headers=headers)
            upstream = conn.getresponse()
            self.send_response(upstream.status, upstream.reason)
            for key, value in upstream.getheaders():
                if key.lower() not in {"transfer-encoding", "connection"}:
                    self.send_header(key, value)
            self.end_headers()
            while True:
                chunk = upstream.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
        except OSError:
            self.send_error(502, "Upstream API unavailable")

    def do_GET(self) -> None:
        self._forward()

    def do_HEAD(self) -> None:
        self._forward()

    def do_POST(self) -> None:
        self._forward()

    def do_PUT(self) -> None:
        self._forward()

    def do_PATCH(self) -> None:
        self._forward()

    def do_DELETE(self) -> None:
        self._forward()

    def do_OPTIONS(self) -> None:
        self._forward()


def main() -> int:
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), WakeProxyHandler)
    print(
        f"wake_proxy listening on http://{LISTEN_HOST}:{LISTEN_PORT} "
        f"-> {UPSTREAM_HOST}:{UPSTREAM_PORT}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
