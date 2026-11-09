"""Token-authenticated HTTP transport restricted to the IPv4 loopback device."""

import hmac
import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .service import GameService

MAX_REQUEST_BYTES = 32 * 1024


def create_server(service=None, token=None):
    bearer = token or secrets.token_urlsafe(32)
    if not isinstance(bearer, str) or len(bearer) < 24:
        raise ValueError("bridge bearer token must have at least 24 characters")
    game = service if service is not None else GameService()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format, *args):
            pass  # Do not log headers, tokens, questions or provider payloads.

        def _reply(self, status, payload):
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True

        def do_POST(self):
            self.connection.settimeout(10)
            # Reject browser origins even if a token is accidentally exposed.
            if self.headers.get("Origin") is not None:
                self._reply(403, {"error": "browser origins are not allowed"})
                return
            supplied = self.headers.get("Authorization", "")
            if not hmac.compare_digest(supplied.encode("utf-8"), ("Bearer " + bearer).encode("utf-8")):
                self._reply(401, {"error": "unauthorized"})
                return
            if self.path != "/command":
                self._reply(404, {"error": "not found"})
                return
            try:
                if self.headers.get("Transfer-Encoding"):
                    raise ValueError()
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_REQUEST_BYTES:
                    self._reply(413, {"error": "invalid request size"})
                    return
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ValueError()
                request = json.loads(raw.decode("utf-8"), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            except (ValueError, UnicodeError, OSError):
                self._reply(400, {"error": "invalid JSON request"})
                return
            self._reply(200, game.handle(request))

        def do_GET(self):
            self._reply(405, {"error": "use POST /command"})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    server.token = bearer
    server.service = game
    return server
