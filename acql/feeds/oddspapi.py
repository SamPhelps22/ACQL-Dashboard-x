"""A second source of betting lines: OddsPapi (oddspapi.io), Pinnacle's prices.

The Odds API (odds.py) is where the lines come from. This is the backup for
when it can't answer - out of requests for the month, down, or no key - so a
card is never priced from Tuesday's lines because one service had a bad day.

Pinnacle is the sharpest book there is, so its line is a good stand-in for the
median of the US books the main feed gives.

OddsPapi's documentation leaves two things open, and neither is taken on trust:

  * which team is home. The answer comes in both ways round (see `fetch`), and
    `odds.update` keeps only the one on the week's own schedule.
  * which way round a spread's handicap is written. Each fetch checks the
    spreads against the moneylines (the favourite on one must be the favourite
    on the other) and turns them round if most disagree.

And the backup is only used once a side-by-side check with the main feed has
agreed (`confirm`): every game in both within `AGREE` points. Until then a
failed main fetch fails as it always did.

Costs: finding the NFL's ids is four requests, once (kept in the database);
each fetch after that is one. The account check is free. Every margin is from
the HOME team's side, like odds.py.
"""

from __future__ import annotations

import json
import os
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request

from .odds import OddsError, Quote

API = "https://api.oddspapi.io/v4/"
SIGNUP_PAGE = "https://oddspapi.io/"
KIND = "oddspapi"
TIMEOUT = 20
BOOKMAKER = "pinnacle"
#: Points the two sources may differ by on any one game and still agree.
AGREE = 1.5
#: Fewest games both sources must quote for a side-by-side check to count.
CHECK_GAMES = 5
#: OddsPapi asks for a second between calls.
COOLDOWN = 1.1
_pause = time.sleep        # tests swap this out


# ---- where it lives ---------------------------------------------------------
def _read() -> dict:
    from .. import store
    return json.loads(json.dumps(store.items(KIND)))


def _write(mapping: dict) -> None:
    from .. import store
    try:
        store.replace(KIND, mapping)
    except store.StoreError:
        pass


def api_key() -> str:
    from ..site import mailer
    env_key = os.environ.get("ACQL_ODDSPAPI_KEY", "").strip()
    if env_key:
        return env_key
    sealed = _read().get("key", "")
    try:
        return mailer.unseal(sealed) if sealed else ""
    except Exception:  # noqa: BLE001 - a key sealed on another machine
        return ""


def set_api_key(key: str) -> None:
    from ..site import mailer
    kept = _read()
    key = "".join(key.split())
    kept["key"] = mailer.seal(key) if key else ""
    if not key:
        kept.pop("confirmed", None)
    _write(kept)


def confirmed() -> bool:
    return bool(_read().get("confirmed"))


def ready() -> bool:
    """A key, and a side-by-side check that agreed: the backup may be used."""
    return bool(api_key()) and confirmed()


def remaining() -> int | None:
    value = _read().get("remaining")
    return int(value) if isinstance(value, (int, float)) else None


def last_check() -> dict | None:
    return _read().get("check")


# ---- talking to it ----------------------------------------------------------
def _get(path: str, params: dict, key: str, opener=None):
    query = urllib.parse.urlencode({**params, "apiKey": key})
    request = urllib.request.Request(f"{API}{path}?{query}", headers={"User-Agent": "ACQL-Dashboard"})
    open_url = opener or (lambda r: urllib.request.urlopen(r, timeout=TIMEOUT))
    from .. import sourcehealth
    started = time.perf_counter()
    try:
        with open_url(request) as reply:
            body = reply.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        sourcehealth.record("oddspapi", False, time.perf_counter() - started, f"HTTP {exc.code}")
        if exc.code in (401, 403):
            raise OddsError("OddsPapi didn't accept the key. Check it under the ⚙ button.") from exc
        if exc.code == 429:
            raise OddsError("OddsPapi is out of requests for this month, or asked to slow down.") from exc
        raise OddsError(f"OddsPapi said no ({exc.code}).") from exc
    except (urllib.error.URLError, OSError) as exc:
        sourcehealth.record("oddspapi", False, time.perf_counter() - started, str(exc))
        raise OddsError(f"Couldn't reach OddsPapi ({getattr(exc, 'reason', exc)}).") from exc
    sourcehealth.record("oddspapi", True, time.perf_counter() - started)
    if path.startswith("odds"):
        from .. import rawarchive
        rawarchive.keep("oddspapi", body)
    try:
        return json.loads(body)
    except ValueError as exc:
        raise OddsError("OddsPapi sent back something that wasn't odds.") from exc


def _records(found) -> list[dict]:
    """A reply as a list of records, whether it came as a list or as {id: record}."""
    if isinstance(found, list):
        return [r for r in found if isinstance(r, dict)]
    if isinstance(found, dict):
        return [r for r in found.values() if isinstance(r, dict)]
    return []


def _id(record: dict, *names: str):
    for name in names:
        if record.get(name) is not None:
            return record[name]
    return None


def _name(record: dict) -> str:
    return " ".join(str(v) for k, v in record.items() if "name" in k.casefold() and isinstance(v, str)).casefold()


# ---- finding the NFL, once --------------------------------------------------
_NOT_FULL_GAME = ("half", "quarter", "1st", "2nd", "3rd", "4th", "period", "team total", "alternative", "corner")


def classify_markets(markets, sport_id) -> dict:
    """{"ml": [ids], "spread": {id: [handicap, outcome ids]}, "total": {id: [line, outcome ids]}}
    for the whole game (overtime included where both kinds are offered)."""
    found = {"ml": {}, "spread": {}, "total": {}}
    for m in _records(markets):
        if m.get("sportId") not in (None, sport_id) or m.get("playerProp"):
            continue
        outcomes = [o.get("outcomeId") for o in m.get("outcomes") or [] if isinstance(o, dict)]
        if len(outcomes) != 2 or m.get("marketId") is None:
            continue
        words = f"{m.get('marketType', '')} {m.get('marketName', '')} {m.get('period', '')}".casefold()
        if any(w in words for w in _NOT_FULL_GAME):
            continue
        overtime = any(w in words for w in ("incl", "overtime", " ot"))
        handicap = m.get("handicap") or 0
        entry = [float(handicap), outcomes, overtime]
        if "handicap" in words or "spread" in words:
            found["spread"][str(m["marketId"])] = entry
        elif "total" in words or "over under" in words:
            found["total"][str(m["marketId"])] = entry
        elif (str(m.get("marketType", "")).strip().casefold() in ("moneyline", "winner", "12", "h2h", "1x2")
              or "moneyline" in words or "winner" in words):
            found["ml"][str(m["marketId"])] = entry
    for kind in found:      # where some include overtime, only those
        if any(e[2] for e in found[kind].values()):
            found[kind] = {k: e for k, e in found[kind].items() if e[2]}
    return {k: {i: e[:2] for i, e in v.items()} for k, v in found.items()}


def discover(key: str, opener=None) -> dict:
    """The NFL's ids, its 32 teams and its markets - asked for once and kept."""
    from ..model.predictions import team_code
    kept = _read()
    ids = kept.get("ids")
    if ids and ids.get("teams") and ids.get("markets", {}).get("spread"):
        return ids
    sports = _records(_get("sports", {}, key, opener))
    sport = next((_id(s, "sportId", "id") for s in sports if "american football" in _name(s)), None)
    if sport is None:
        raise OddsError("OddsPapi doesn't list American football.")
    _pause(COOLDOWN)
    tournaments = _records(_get("tournaments", {"sportId": sport}, key, opener))
    nfl = next((_id(t, "tournamentId", "id") for t in tournaments
                if any(str(v).strip().casefold() == "nfl" for k, v in t.items() if "name" in k.casefold())), None)
    if nfl is None:
        raise OddsError("OddsPapi doesn't list the NFL.")
    _pause(COOLDOWN)
    people = _get("participants", {"sportId": sport}, key, opener)
    teams = {str(pid): team_code(name) for pid, name in (people.items() if isinstance(people, dict) else [])}
    teams = {pid: code for pid, code in teams.items() if code}
    _pause(COOLDOWN)
    markets = classify_markets(_get("markets", {}, key, opener), sport)
    if not markets["spread"] and not markets["ml"]:
        raise OddsError("OddsPapi lists no full-game spread or moneyline for the NFL.")
    ids = {"sport": sport, "tournament": nfl, "teams": teams, "markets": markets}
    kept = _read()
    kept["ids"] = ids
    _write(kept)
    return ids


# ---- reading prices ---------------------------------------------------------
def _chance(price) -> float | None:
    """The chance a price implies - decimal (1.91) or American (-110)."""
    from .odds import _implied
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return None
    if 1.0 < price < 50:
        return 1.0 / price
    return _implied(price)


def _prices(market: dict, outcome_ids: list) -> tuple[float, float] | None:
    """The two sides' chances, the book's margin left in."""
    outcomes = (market or {}).get("outcomes") or {}
    got = []
    for oid in outcome_ids:
        players = (outcomes.get(str(oid)) or {}).get("players") or {}
        live = [p for p in players.values() if isinstance(p, dict) and p.get("active", True) is not False]
        chance = _chance(live[0].get("price")) if live else None
        if chance is None:
            return None
        got.append(chance)
    return got[0], got[1]


def _main(markets: dict, wanted: dict) -> tuple[float, float, float] | None:
    """(line, first side's chance, second side's) for the line nearest even money."""
    best = None
    for mid, (line, outcome_ids) in wanted.items():
        pair = _prices(markets.get(mid), outcome_ids)
        if pair is None:
            continue
        a, b = pair
        gap = abs(a / (a + b) - 0.5)
        if best is None or gap < best[0]:
            best = (gap, line, a, b)
    return None if best is None else best[1:]


def parse(fixtures, ids: dict, book: str = BOOKMAKER) -> list[Quote]:
    """One Quote per game, given both ways round: OddsPapi doesn't say which team is
    home, so `odds.update` keeps whichever matches the week's schedule."""
    rows = []      # (first team, second, kickoff, first's margin or None, first's chance or None, total)
    for f in _records(fixtures):
        first, second = ids["teams"].get(str(f.get("participant1Id"))), ids["teams"].get(str(f.get("participant2Id")))
        markets = (((f.get("bookmakerOdds") or {}).get(book) or {}).get("markets")) or {}
        if not first or not second or not markets:
            continue
        ml = _main(markets, ids["markets"]["ml"])
        win = ml[1] / (ml[1] + ml[2]) if ml else None
        spread = _main(markets, ids["markets"]["spread"])
        total = _main(markets, ids["markets"]["total"])
        margin = -spread[0] if spread else None          # a -3.5 handicap: favoured by 3.5
        if margin is None and win is None:
            continue
        rows.append([first, second, str(f.get("startTime", "")), margin, win, total[0] if total else None])
    # the handicap's sign isn't documented: the favourite on the moneyline must be the favourite here
    clear = [(m, w) for _, _, _, m, w, _ in rows if m and w is not None and abs(w - 0.5) > 0.08]
    if clear and sum((m > 0) != (w > 0.5) for m, w in clear) > len(clear) / 2:
        for row in rows:
            row[3] = -row[3] if row[3] is not None else None
    out = []
    for first, second, kickoff, margin, win, total in rows:
        if margin is None:
            margin = _margin_from_chance(win)
        for home, away, m, w in ((first, second, margin, win), (second, first, -margin, None if win is None else 1 - win)):
            out.append(Quote(away=away, home=home, kickoff=kickoff, home_margin=round(m + 0.0, 2), books=1,
                             home_win=None if w is None else round(w, 4), total=total))
    return out


def _margin_from_chance(win: float) -> float:
    """A spread from a moneyline alone (no spread offered): the curve read backwards."""
    from .. import analytics
    lo, hi = -30.0, 30.0
    for _ in range(50):
        mid = (lo + hi) / 2
        if analytics.win_chance(mid) < win:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2 * 2) / 2


def fetch(key: str, *, opener=None) -> tuple[list[Quote], int | None]:
    """(every NFL game on Pinnacle's board, both ways round; OddsPapi requests left)."""
    if not key:
        raise OddsError("No OddsPapi key.")
    ids = discover(key, opener)
    fixtures = _get("odds-by-tournaments", {"tournamentIds": ids["tournament"], "bookmakers": BOOKMAKER},
                    key, opener)
    quotes = parse(fixtures, ids)
    left = None
    try:
        account = _get("account", {}, key, opener)     # free
        limit, used = account.get("request_limit"), account.get("request_count")
        if isinstance(limit, (int, float)) and isinstance(used, (int, float)):
            left = int(limit - used)
            kept = _read()
            kept["remaining"] = left
            _write(kept)
    except (OddsError, AttributeError):
        pass
    return quotes, left


# ---- trusting it --------------------------------------------------------------
def compare(main: list[Quote], second: list[Quote], now: float | None = None) -> dict:
    """The two sources side by side: games both quote, and those more than AGREE apart."""
    from ..model.predictions import display_matchup
    theirs = {q.key: q.home_margin for q in second}
    both, apart = 0, []
    for q in main:
        other = theirs.get(q.key)
        if other is None:
            continue
        both += 1
        if abs(other - q.home_margin) > AGREE:
            apart.append(f"{display_matchup(q.away, q.home)}: {q.home_margin:+g} vs {other:+g}")
    return {"at": time.time() if now is None else now, "games": both, "apart": apart,
            "agree": both >= CHECK_GAMES and not apart}


def confirm(main: list[Quote], key: str | None = None, opener=None) -> dict | None:
    """Fetch once and check against the main feed's quotes; the backup is trusted only
    after this agrees. Does nothing once confirmed, or with no key."""
    key = api_key() if key is None else key
    if not key or confirmed() or not main:
        return None
    second, _ = fetch(key, opener=opener)
    found = compare(main, second)
    kept = _read()
    kept["check"] = found
    if found["agree"]:
        kept["confirmed"] = found["at"]
    _write(kept)
    return found


def describe(found: dict) -> str:
    """A side-by-side check in a sentence, for the log."""
    if found["agree"]:
        return f"OddsPapi checked against The Odds API on {found['games']} games and agreed - the backup is on."
    if found["games"] < CHECK_GAMES:
        return f"OddsPapi check: only {found['games']} games in both - not enough to trust it yet."
    return (f"OddsPapi check: {len(found['apart'])} of {found['games']} games more than {AGREE:g} points apart "
            f"({'; '.join(found['apart'][:3])}) - the backup stays off.")
