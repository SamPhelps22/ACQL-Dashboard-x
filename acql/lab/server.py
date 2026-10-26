"""The Lab's server: `python -m acql.lab [--port 8765] [--offline]`.

Binds to 127.0.0.1 only, so nothing outside this computer can reach it.
Requests whose Host isn't this computer are refused (so a web page elsewhere
can't reach it through a renamed address), and the two POST routes need a
custom header that a cross-site form cannot send. It serves one page and a
fixed list of JSON routes - no path is ever read from the request.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import assistant, data, live

PAGE = Path(__file__).with_name("page.html")
CACHE_S = 60
MAX_BODY = 16_000


OPEN_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>RedZone</title>
<style>body{margin:0;background:#07080a;color:#f2f3f5;font:16px/1.5 "Segoe UI",system-ui,sans-serif;
display:grid;place-items:center;min-height:100vh;text-align:center}b{color:#d4a93c;letter-spacing:.14em}
p{color:#8b919c;max-width:36ch}</style></head><body><div><b>REDZONE</b><p id="m">Asking the dashboard...</p></div>
<script>
fetch("/api/open", {method: "POST", headers: {"Content-Type": "application/json", "X-Lab": "1"},
  body: JSON.stringify({what: "redzone"})}).then(function (r) { return r.json(); }).then(function (j) {
  document.getElementById("m").textContent = j.ok ? "RedZone is open on your dashboard. You can close this tab."
    : (j.error || "The dashboard didn't answer.");
}).catch(function () { document.getElementById("m").textContent = "The dashboard didn't answer."; });
</script></body></html>"""


class Lab:
    """What the routes share: one read-only database link, one live hub, a small cache."""

    def __init__(self, *, hub: live.LiveHub | None = None, conn=None, client=None, actions=None):
        #: what the Lab may ask the dashboard to do, by name (only when started from the dashboard)
        self.actions: dict = dict(actions or {})
        self.conn = conn or data.connect()
        self.db_lock = threading.Lock()
        self.hub = hub
        self.client = client
        self._cache: dict[str, tuple[float, object]] = {}

    def cached(self, key: str, make):
        hit = self._cache.get(key)
        if hit and time.time() - hit[0] < CACHE_S:
            return hit[1]
        with self.db_lock:
            made = make()
        self._cache[key] = (time.time(), made)
        return made

    def route(self, path: str, q: dict) -> object:
        one = lambda k, cast=str: (cast(q[k][0]) if q.get(k) and q[k][0] != "" else None)  # noqa: E731
        c = self.conn
        if path == "/api/models":
            return self.cached("models", lambda: data.model_list(c))
        if path == "/api/calibration":
            args = dict(model=one("model") or data.DEADEYE, season=one("season", int), team=one("team"),
                        version=one("version"), horizon=one("horizon"), width=one("width", float) or 0.1)
            if args["width"] not in (0.05, 0.1):
                args["width"] = 0.1
            return self.cached("cal" + json.dumps(args, sort_keys=True), lambda: data.calibration(
                c, args.pop("model"), **args))
        if path == "/api/distribution":
            args = dict(model=one("model") or data.DEADEYE, week=one("week", int), team=one("team"))
            return self.cached("dist" + json.dumps(args, sort_keys=True),
                               lambda: data.distribution(c, args.pop("model"), **args))
        if path == "/api/teams":
            return self.cached("teams", lambda: {"teams": data.teams(c), "records": {
                t: data.team_record(c, t) for t in data.TEAMS}})
        if path == "/api/strength":
            return self.cached("strength", data.strength)
        if path == "/api/books":
            at = one("at", float)
            return self.cached(f"books{at}", lambda: data.books(at))
        if path == "/api/stats":
            season = one("season", int)
            return self.cached(f"stats{season}", lambda: data.stats(season))
        if path == "/api/postmortems":
            return self.cached("pm", lambda: data.postmortems(c))
        if path == "/api/experiments":
            return self.cached("exp", lambda: data.experiments(c))
        if path == "/api/live":
            return self.hub.snapshot() if self.hub else {"error": "Live scores are off (--offline)."}
        if path == "/api/assistant":
            ok, why = (True, "") if self.client else assistant.available()
            return {"available": ok, "reason": why, "model": assistant.MODEL,
                    "tools": [t["name"] for t in assistant.TOOLS]}
        return None


def handler_for(lab: Lab, port: int):
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        server_version = "OperationSundayLab"

        def log_message(self, *args):  # quiet: nothing is written to the app's log
            pass

        def _send(self, code: int, body: bytes, kind: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                             "img-src 'self' data:; connect-src 'self'")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj: object) -> None:
            self._send(code, json.dumps(obj, default=str).encode("utf-8"))

        def _host_ok(self) -> bool:
            return self.headers.get("Host", "") in hosts

        def do_GET(self):  # noqa: N802
            if not self._host_ok():
                return self._json(403, {"error": "This server only answers this computer."})
            url = urlparse(self.path)
            if url.path == "/redzone":
                return self._send(200, OPEN_PAGE.encode("utf-8"), "text/html; charset=utf-8")
            if url.path in ("/", "/index.html"):
                return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            if url.path == "/events":
                return self._events(parse_qs(url.query))
            try:
                out = lab.route(url.path, parse_qs(url.query))
            except (ValueError, TypeError) as exc:
                return self._json(400, {"error": f"Bad request: {exc}"})
            except Exception as exc:  # noqa: BLE001 - said on the page
                return self._json(500, {"error": f"{exc.__class__.__name__}: {exc}"})
            if out is None:
                return self._json(404, {"error": "No such page."})
            return self._json(200, out)

        def do_POST(self):  # noqa: N802
            if not self._host_ok() or self.headers.get("X-Lab") != "1":
                return self._json(403, {"error": "Refused."})
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self._json(413, {"error": "Too long."})
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self._json(400, {"error": "Not JSON."})
            path = urlparse(self.path).path
            if path == "/api/tool":
                name = str(body.get("name", ""))
                if name not in {t["name"] for t in assistant.TOOLS}:
                    return self._json(400, {"error": "Unknown tool."})
                with lab.db_lock:
                    return self._json(200, {"result": assistant.run_tool(name, body.get("args") or {}, lab.conn)})
            if path == "/api/open":
                act = lab.actions.get(str(body.get("what", "")))
                if not act:
                    return self._json(200, {"ok": False, "error": "Open the dashboard first: RedZone opens there, "
                                                                     "and this Lab wasn't started by it."})
                act()
                return self._json(200, {"ok": True})
            if path == "/api/ask":
                with lab.db_lock:
                    out = assistant.ask(body.get("question", ""), lab.conn, client=lab.client,
                                        context=body.get("context"))
                return self._json(200, out)
            return self._json(404, {"error": "No such page."})

        def _events(self, q: dict) -> None:
            if not lab.hub:
                return self._json(404, {"error": "Live scores are off (--offline)."})
            since = int((q.get("since") or ["0"])[0] or 0)
            last = self.headers.get("Last-Event-ID")
            if last and last.isdigit():
                since = int(last)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(b"retry: 5000\n\n")
                while True:
                    for e in lab.hub.since(since):
                        self.wfile.write(f"id: {e['version']}\ndata: {json.dumps(e, default=str)}\n\n".encode())
                        since = e["version"]
                    self.wfile.flush()
                    if not lab.hub.wait(since, 25):
                        self.wfile.write(b": keep-alive\n\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                return

    return Handler


_RUNNING: dict[int, Lab] = {}


def _answering(port: int) -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/models", timeout=2) as r:
            return r.status == 200
    except OSError:
        return False


def start_background(port: int = 8765, *, actions=None) -> str:
    """The Lab's address, starting it on a background thread if nothing answers there yet
    (the dashboard's LAB button). Raises OSError when the port is taken by something else."""
    url = f"http://127.0.0.1:{port}/"
    if port in _RUNNING:
        _RUNNING[port].actions.update(actions or {})
        return url
    if _answering(port):
        return url
    from ..feeds import results
    year = results.season_year()
    hub = live.LiveHub(year, live.current_week(year))
    hub.start()
    lab = Lab(hub=hub, actions=actions)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler_for(lab, port))
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, name="lab-server", daemon=True).start()
    _RUNNING[port] = lab
    return url


def serve(port: int = 8765, *, offline: bool = False) -> None:
    from ..feeds import results
    year = results.season_year()
    hub = None
    if not offline:
        hub = live.LiveHub(year, live.current_week(year))
        hub.start()
    lab = Lab(hub=hub)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler_for(lab, port))
    httpd.daemon_threads = True
    print(f"Operation Sunday Lab: http://127.0.0.1:{port}  (this computer only; Ctrl+C stops it)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if hub:
            hub.stop()
        httpd.server_close()


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="python -m acql.lab", description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--offline", action="store_true", help="don't ask ESPN for live scores")
    args = parser.parse_args(argv)
    serve(args.port, offline=args.offline)
