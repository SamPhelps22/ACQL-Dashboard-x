"""A local preview of the website with the league modes turned on.

    python -m acql.site.modespreview [--live] [--out FOLDER]

The modes (League Broadcast, League Time Machine, the Numbers Room) are in the
published page while `poolpage.MODES` is on. This builds the site with them on
whatever the switch says - from the real season, the same way a
publish builds it - into a git-ignored folder (data/site-preview/modes by
default) to open in a browser. Nothing is uploaded, nothing is marked
published, and poolpage.MODES is put back as it was.

--live puts a made-up ESPN scoreboard in front of the page (a third of the
week's games final, a third under way, a third still to play) so the live
Broadcast can be seen on a day with no games. Those scores are fake and the
page says nothing else; they exist only in the preview file.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_OUT = ROOT / "data" / "site-preview" / "modes"

#: A made-up scoreboard for --live: answers the page's ESPN request locally.
FAKE_SCORES = r"""<script>
(function () {
  var real = window.fetch;
  window.fetch = function (url, opts) {
    if (String(url).indexOf("scoreboard") < 0) return real ? real(url, opts) : Promise.reject(new Error("offline"));
    var L = (window.__LIVE_GAMES__ || []), now = Date.now();
    var events = L.map(function (g, i) {
      var k = i % 3, when = new Date(now + (k === 2 ? 26 : -2) * 3600 * 1000).toISOString();
      var st = k === 0 ? { period: 4, clock: 0, type: { state: "post", completed: true, shortDetail: "Final" } }
             : k === 1 ? { period: 3, clock: 412, displayClock: "6:52", type: { state: "in", completed: false, shortDetail: "6:52 - 3rd" } }
             : { period: 0, clock: 0, type: { state: "pre", completed: false, shortDetail: "Sun 1:00 PM" } };
      var hs = k === 2 ? "0" : String(10 + (i * 7) % 21), as = k === 2 ? "0" : String(6 + (i * 5) % 24);
      return { date: when, competitions: [{ date: when, status: st,
        competitors: [{ homeAway: "home", score: hs, team: { abbreviation: g.hc.toUpperCase() } },
                      { homeAway: "away", score: as, team: { abbreviation: g.ac.toUpperCase() } }] }] };
    });
    return Promise.resolve({ ok: true, json: function () { return Promise.resolve({ events: events }); } });
  };
})();
</script>"""


def build(out: Path = DEFAULT_OUT, *, live: bool = False, season=None) -> Path:
    """Build the preview into `out`; returns the page's path."""
    from ..ui import poolpage
    from ..ui.pages import base
    # a preview never writes into the real log
    base.log_path = lambda: Path(out) / "preview-log.txt"
    if season is None:
        from ..config import Settings
        from ..names import AliasTable
        from ..repository import load_season
        season = load_season(Settings.load(), AliasTable.load(), online=False)
    was = poolpage.MODES
    poolpage.MODES = True
    try:
        page, files, data = poolpage.site(season)
    finally:
        poolpage.MODES = was
    if live:
        games = json.dumps((data.get("live") or {}).get("games") or [])
        page = page.replace("<script", f"<script>window.__LIVE_GAMES__ = {games};</script>{FAKE_SCORES}<script", 1)
    page = page.replace(poolpage.SITE, "")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(page, encoding="utf-8")
    for name, blob in files.items():
        if name == poolpage.SERVICE_WORKER:
            continue                     # a preview mustn't install the site's offline cache
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
    return out / "index.html"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--live", action="store_true", help="put made-up live scores in front of the page")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    path = build(args.out, live=args.live)
    print(f"Preview built: {path}\nOpen it in a browser and add #broadcast, #timemachine or #numbers to the address.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
