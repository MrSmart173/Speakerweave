"""Lets other programs on this PC trigger actions through a web link, for example
the Website action of a Stream Deck, Touch Portal, or a SimHub button:

    http://127.0.0.1:47800/<code>/volume_up

Only programs on this PC can reach it, and only with the secret code that is
part of every link.

Two more links are used by the SpeakerWeave plugin for SimHub:
    /<code>/status          SpeakerWeave's state as JSON (volume, mute, mode ...)
    /<code>/game?name=...   which game SimHub sees running ("" when none)
"""
from __future__ import annotations

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

ACTION_RE = re.compile(r"^[a-z0-9_]+(:[0-9a-f]+)?$")


class RemoteServer:
    def __init__(self, port: int, token: str, on_action, on_game=None):
        self.port, self.token, self.on_action = int(port), token, on_action
        self.on_game = on_game          # called with (game, car, track), from the server thread
        self.status: dict = {}          # filled in by the app, sent as is to /status
        self.last_simhub = 0.0          # time.monotonic() of the last call from the SimHub plugin
        self._server = None
        self._thread = None
        self.error = ""

    def simhub_connected(self, within: float = 6.0) -> bool:
        return self.running and self.last_simhub > 0 and time.monotonic() - self.last_simhub < within

    @property
    def running(self) -> bool:
        return self._server is not None

    def url(self, action: str) -> str:
        return f"http://127.0.0.1:{self.port}/{self.token}/{action}"

    def start(self) -> bool:
        self.stop()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self):
                path, _, query = self.path.partition("?")
                parts = [p for p in path.split("/") if p]
                if len(parts) != 2 or parts[0] != owner.token:
                    self._reply(403, "wrong link\n")
                    return
                action = parts[1]
                params = parse_qs(query, keep_blank_values=True)
                if action in ("status", "game"):
                    simhub = action == "game" or params.get("client", [""])[0] == "simhub"
                    if simhub:
                        owner.last_simhub = time.monotonic()
                    if simhub and "name" in params and owner.on_game is not None:
                        owner.on_game(*(params.get(k, [""])[0][:120] for k in ("name", "car", "track")))
                    if action == "status":
                        self._reply(200, json.dumps(owner.status), "application/json")
                    else:
                        self._reply(200, "ok\n")
                    return
                if not ACTION_RE.match(action):
                    self._reply(404, "unknown action\n")
                    return
                owner.on_action(action)
                self._reply(200, "ok\n")

            def _reply(self, code, text, kind="text/plain"):
                body = text.encode()
                self.send_response(code)
                self.send_header("Content-Type", f"{kind}; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = _answer
            do_POST = _answer

            def log_message(self, *_args):
                pass

        try:
            self._server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        except OSError as exc:
            self._server = None
            self.error = f"Port {self.port} is already in use by another program ({exc.strerror})."
            return False
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self.error = ""
        return True

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
