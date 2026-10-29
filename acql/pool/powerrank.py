"""ACQL Power Rankings: an unofficial ranking, apart from the official table.

The official standings rank total wins. These rank how well a coach has been
picking lately, on a scale that doesn't punish a missed week twice or reward
an easy slate:

    rel(w)       a coach's week score minus that week's pool average
                 (only coaches with a card that week count in the average)
    recent       mean rel over the pool's last RECENT weeks (to the cutoff)
    earlier      mean rel over the pool's weeks before those
    steadiness   the pool's median spread of rel minus the coach's own
                 (spread = population standard deviation; positive = steadier)

    rating = 0.55 x recent + 0.30 x earlier + 0.15 x steadiness

all in wins per week against the average coach. Recent and earlier don't
overlap, so no week is counted twice; when a coach has no earlier weeks (or
no recent ones) the weights are shared out over what there is. Steadiness
needs three weeks; with fewer it is left out the same way. Season wins are
not an input - that is the official table's job.

Only weeks up to the cutoff are read, so a past week's ranking is exactly
what could have been worked out that week. A coach with no card in any week
to the cutoff isn't ranked. Equal ratings (to two decimals) share a place.

It has not been tested as a forecast and says nothing about next week.
Nothing here touches the official places, scores or money: it only reads
the weekly scores the site already shows.
"""

from __future__ import annotations

import statistics

RECENT = 3
WEIGHTS = {"recent": 0.55, "earlier": 0.30, "steadiness": 0.15}
STEADY_MIN = 3          # weeks needed before steadiness counts
SMALL_SAMPLE = 3        # fewer weeks than this is flagged


def _weeks(weekly: dict[str, dict], cutoff: int) -> list[int]:
    found = {int(w) for scores in weekly.values() for w in scores if int(w) <= cutoff}
    return sorted(found)


def rankings(weekly: dict[str, dict], cutoff: int) -> list[dict]:
    """Every coach with a card by `cutoff`, best first. `weekly` is
    {coach: {week: total}} (week as int or str), the site's own numbers."""
    weeks = _weeks(weekly, cutoff)
    if not weeks:
        return []
    scores = {c: {int(w): float(v) for w, v in s.items() if int(w) <= cutoff and v is not None}
              for c, s in weekly.items()}
    average = {}
    for w in weeks:
        got = [s[w] for s in scores.values() if w in s]
        average[w] = sum(got) / len(got)
    recent_weeks = weeks[-RECENT:]
    earlier_weeks = weeks[:-RECENT]
    rel = {c: {w: s[w] - average[w] for w in s} for c, s in scores.items() if s}
    spreads = {c: statistics.pstdev(r.values()) for c, r in rel.items() if len(r) >= STEADY_MIN}
    median_spread = statistics.median(spreads.values()) if spreads else None

    rows = []
    for coach, r in rel.items():
        parts = {}
        rec = [r[w] for w in recent_weeks if w in r]
        ear = [r[w] for w in earlier_weeks if w in r]
        if rec:
            parts["recent"] = sum(rec) / len(rec)
        if ear:
            parts["earlier"] = sum(ear) / len(ear)
        if coach in spreads and median_spread is not None:
            parts["steadiness"] = median_spread - spreads[coach]
        total_weight = sum(WEIGHTS[k] for k in parts)
        rating = sum(WEIGHTS[k] * v for k, v in parts.items()) / total_weight
        rows.append({
            "name": coach,
            "rating": round(rating, 2),
            "recent": None if "recent" not in parts else round(parts["recent"], 2),
            "earlier": None if "earlier" not in parts else round(parts["earlier"], 2),
            "spread": None if coach not in spreads else round(spreads[coach], 2),
            "steadiness": None if "steadiness" not in parts else round(parts["steadiness"], 2),
            "weeks": len(r),
            "recent_weeks": len(rec),
            "small": len(r) < SMALL_SAMPLE,
            "last3": [None if w not in scores[coach] else int(scores[coach][w]) for w in recent_weeks],
        })
    rows.sort(key=lambda x: (-x["rating"], x["name"].casefold()))
    for row in rows:
        row["rank"] = 1 + sum(1 for o in rows if o["rating"] > row["rating"])
    return rows


def history(weekly: dict[str, dict], official: dict[str, int | None] | None = None,
            recorded: dict | None = None) -> dict:
    """Every finished week's ranking, each worked out from the weeks up to it
    only, with movement against the week before. `recorded` is
    {week: {"at": ..., "ranks": {coach: rank}}} saved at publish time; a week
    whose saved ranks match is marked recorded, otherwise reconstructed."""
    weeks = _weeks(weekly, 10 ** 6)
    recorded = recorded or {}
    snaps = []
    before: dict[str, int] = {}
    for w in weeks:
        rows = rankings(weekly, w)
        for row in rows:
            prev = before.get(row["name"])
            row["move"] = None if prev is None else prev - row["rank"]
        before = {row["name"]: row["rank"] for row in rows}
        saved = recorded.get(str(w)) or recorded.get(w)
        kind = "reconstructed"
        if isinstance(saved, dict) and saved.get("ranks") == before:
            kind = "recorded"
        snaps.append({"week": w, "kind": kind, "recorded_at": saved.get("at") if kind == "recorded" else None,
                      "rows": rows})
    if snaps and official:
        for row in snaps[-1]["rows"]:
            row["official"] = official.get(row["name"])
    return {
        "method": {
            "weights": WEIGHTS, "recent": RECENT, "steady_min": STEADY_MIN, "small_sample": SMALL_SAMPLE,
            "formula": "rating = 0.55 x recent + 0.30 x earlier + 0.15 x steadiness (wins a week against the pool average)",
        },
        "weeks": snaps,
    }


def record(weekly: dict[str, dict], cutoff: int, now: float) -> bool:
    """Keep this week's ranking as published, once (store kind
    "power_rankings"). True if it was written. Never changes an older one."""
    from .. import store
    key = str(int(cutoff))
    if not cutoff or store.get("power_rankings", key, None):
        return False
    ranks = {row["name"]: row["rank"] for row in rankings(weekly, cutoff)}
    if not ranks:
        return False
    store.put("power_rankings", key, {"at": now, "ranks": ranks})
    return True


def recorded() -> dict:
    from .. import store
    try:
        return store.items("power_rankings") or {}
    except Exception:  # noqa: BLE001 - no store: everything is reconstructed
        return {}
