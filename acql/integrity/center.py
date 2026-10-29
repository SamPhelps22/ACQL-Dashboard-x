"""The Integrity Center: `python -m acql.integrity center [--port 8766]`.

Localhost only, like the Lab: binds to 127.0.0.1, refuses a Host that isn't
this computer, and every POST needs a custom header a cross-site form can't
send. One page and a fixed list of routes; no path is read from the request.

    GET  /                the page
    GET  /api/report      the last run, run history, issue log, decisions, gate
    POST /api/run         load the season and validate now
    POST /api/recover     reload from the files and validate again (after a failure)
    POST /api/decide      record a decision (history.decide) - needs a name and a note
"""

from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import engine, history

PAGE = Path(__file__).with_name("page.html")
MAX_BODY = 8_000
HEADER = "X-Integrity"


def load_season():
    from ..config import Settings
    from ..names import AliasTable
    from ..repository import load_season as load
    return load(Settings.load(), AliasTable.load(), online=False)


class Center:
    def __init__(self, loader=load_season, make_context=None):
        self.loader = loader
        self.make_context = make_context
        self.lock = threading.Lock()
        self.season = None

    def _season(self):
        if self.season is None:
            self.season = self.loader()
        return self.season

    def report(self) -> dict:
        last = history.last()
        return {"last": last, "trusted": history.last_good(), "runs": history.runs()[-30:],
                "issues": history.issues(), "decisions": history.decisions()[-50:],
                "baseline": {y: sorted(w, key=int) for y, w in history.baseline().items()},
                "gate": engine.publish_gate(last) if last else ["the integrity checks haven't run"]}

    def run(self) -> dict:
        with self.lock:
            self.season = self.loader()
            return history.ensure(self.season, force=True, make_context=self.make_context)

    def recover(self) -> dict:
        with self.lock:
            out = history.recover(self.loader, make_context=self.make_context)
            self.season = None
            return out

    def decide(self, body: dict) -> dict:
        with self.lock:
            kind = str(body.get("kind") or "")
            week = int(body["week"]) if str(body.get("week") or "").isdigit() else None
            year = int(body["year"]) if str(body.get("year") or "").isdigit() else None
            return history.decide(kind, by=body.get("by", ""), note=body.get("note", ""),
                                  finding=str(body.get("finding") or ""), week=week, year=year,
                                  choice=str(body.get("choice") or ""), value=body.get("value"),
                                  season=self._season() if kind == "accept_change" else None)


def handler_for(center: Center):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # quiet
            pass

        def _local(self) -> bool:
            host = (self.headers.get("Host") or "").split(":")[0]
            return host in ("127.0.0.1", "localhost")

        def _send(self, status: int, body: bytes, kind: str = "application/json") -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data) -> None:
            self._send(status, json.dumps(data, default=str).encode("utf-8"))

        def do_GET(self):
            if not self._local():
                return self._json(403, {"error": "local only"})
            path = self.path.split("?")[0]
            if path == "/":
                return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            if path == "/api/report":
                return self._json(200, center.report())
            return self._json(404, {"error": "not found"})

        def do_POST(self):
            if not self._local() or self.headers.get(HEADER) != "1":
                return self._json(403, {"error": "local only"})
            size = int(self.headers.get("Content-Length") or 0)
            if size > MAX_BODY:
                return self._json(413, {"error": "too large"})
            try:
                body = json.loads(self.rfile.read(size) or b"{}")
            except ValueError:
                return self._json(400, {"error": "not JSON"})
            path = self.path.split("?")[0]
            try:
                if path == "/api/run":
                    return self._json(200, center.run())
                if path == "/api/recover":
                    return self._json(200, center.recover())
                if path == "/api/decide":
                    return self._json(200, center.decide(body if isinstance(body, dict) else {}))
            except ValueError as exc:
                return self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001 - said on the page
                return self._json(500, {"error": f"{type(exc).__name__}: {exc}"})
            return self._json(404, {"error": "not found"})

    return Handler


def serve(port: int = 8766, center: Center | None = None) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), handler_for(center or Center()))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m acql.integrity center")
    ap.add_argument("--port", type=int, default=8766)
    args = ap.parse_args(argv)
    server = serve(args.port)
    print(f"Integrity Center on http://127.0.0.1:{args.port}/  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0
