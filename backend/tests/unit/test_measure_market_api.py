"""measure_market_api must read response headers whatever their case (HTTP/2 lowercases them)."""

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from scripts.clickhouse.measure_market_api import get


class _Lowercase(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        for name, value in (
            ("x-export-truncated", "true"),
            ("x-export-rows", "500000"),
            ("x-export-matching-rows", "1200000"),
        ):
            self.send_header(name, value)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


def test_get_headers_are_case_insensitive():
    server = HTTPServer(("127.0.0.1", 0), _Lowercase)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        status, _, size, headers = get(f"http://127.0.0.1:{server.server_port}", "t", "/x")
    finally:
        server.shutdown()
    assert (status, size) == (200, 2)
    assert headers.get("X-Export-Truncated") == "true"
    assert headers.get("X-Export-Rows") == "500000"
    assert headers.get("x-export-matching-rows") == "1200000"
