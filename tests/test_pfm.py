#!/usr/bin/env python3
"""Tests for the PFM ratings feed (acql/feeds/pfm.py), the PFM study
(acql/training/pfm.py) and the Model Lab's reader (acql/model/pfmcheck.py).

Run from the project root:

    python tests/test_pfm.py

Every page here is made up: the same markup PFM uses, invented numbers (no
real PFM rating is in this repository - it is public and they are not ours).
Nothing goes online, nothing reads the app's database. No Qt is imported.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from acql.feeds import pfm
from acql.model import pfmcheck, predictions
from acql.training import pfm as study

NAMES = {
    "ari": "Arizona Cardinals", "atl": "Atlanta Falcons", "bal": "Baltimore Ravens", "buf": "Buffalo Bills",
    "car": "Carolina Panthers", "chi": "Chicago Bears", "cin": "Cincinnati Bengals", "cle": "Cleveland Browns",
    "dal": "Dallas Cowboys", "den": "Denver Broncos", "det": "Detroit Lions", "gb": "Green Bay Packers",
    "hou": "Houston Texans", "ind": "Indianapolis Colts", "jax": "Jacksonville Jaguars", "kc": "Kansas City Chiefs",
    "lac": "Los Angeles Chargers", "lar": "Los Angeles Rams", "lv": "Las Vegas Raiders", "mia": "Miami Dolphins",
    "min": "Minnesota Vikings", "ne": "New England Patriots", "no": "New Orleans Saints", "nyg": "New York Giants",
    "nyj": "New York Jets", "phi": "Philadelphia Eagles", "pit": "Pittsburgh Steelers", "sea": "Seattle Seahawks",
    "sf": "San Francisco 49ers", "tb": "Tampa Bay Buccaneers", "ten": "Tennessee Titans", "was": "Washington Commanders",
}
CODES = sorted(NAMES)


def grades_for(i: int) -> dict:
    """Invented grades for the i-th team, and the score the published formula gives them."""
    base = 70.0 + (i * 7) % 20
    g = {key: round(base + ((i + k) % 5) - 2, 2) for k, key in enumerate(pfm.GRADES)}
    g["explosiveness"] = round(base + 1.5, 2)
    g["score"] = round(pfm.public_score(g), 2)
    return g


def slug(code: str) -> str:
    return NAMES[code].lower().replace(" ", "-")


def rankings_page(codes=CODES, stated="2026-10-13", bad: dict | None = None, extra_rows: str = "") -> str:
    rows = []
    for i, code in enumerate(codes):
        g = {**grades_for(i), **((bad or {}).get(code, {}))}
        cells = [f'<td data-label="Rank" data-sort-value="{i + 1}"><span>{i + 1}</span></td>',
                 f'<td data-sort-value="{NAMES[code]}" data-label="Team"><a class="x" '
                 f'href="https://profootballmania.com/nfl-team-dashboards/{slug(code)}/">{NAMES[code]} &#9660; '
                 f'{code.upper()}</a></td>',
                 '<td data-label="Record" data-sort-value="1">3-2</td>',
                 f'<td data-label="PFM Score" data-sort-value="{g["score"]}"><span>{g["score"]:.1f}</span></td>']
        for key, (heading, _) in pfm.GRADES.items():
            cells.append(f'<td data-label="{heading}" data-sort-value="{g[key]}"><span>x</span></td>')
        rows.append(f'<tr data-pfm-original-order="{i + 1}">' + "".join(cells) + "</tr>")
    return (f'<html><body><p>Ratings updated <time datetime="{stated}">Oct 13</time></p><table><thead><tr><th>Rank'
            f'</th></tr></thead><tbody>{"".join(rows)}{extra_rows}</tbody></table></body></html>')


def explosive_page(codes=CODES) -> str:
    rows = "".join(f'<tr><td data-label="Rank" data-sort-value="{i}">{i}</td><td data-label="Team" '
                   f'data-sort-value="{NAMES[c]}">{NAMES[c]}</td><td data-label="Explosiveness" '
                   f'data-sort-value="{grades_for(i)["explosiveness"]}">x</td></tr>' for i, c in enumerate(codes))
    return f'<table><tbody>{rows}</tbody></table><time datetime="2026-10-13">x</time>'


def history_svg(values: list[float]) -> str:
    labels = ["BASELINE"] + [f"W{n}" for n in range(1, len(values))]
    points = "".join(f'<g class="pfm-chart-point"> <circle cx="1" cy="2" r="5"/> <text class="pfm-chart-value" '
                     f'x="1" y="1">{v}</text> <text class="pfm-chart-x-label" x="1" y="2">{l}</text> </g>'
                     for v, l in zip(values, labels))
    return (f'<svg class="pfm-line-chart" aria-label="Some Team PFM score history line chart">{points}</svg>'
            '<svg aria-label="another chart"><g class="pfm-chart-point"><text class="pfm-chart-value">1</text>'
            '<text class="pfm-chart-x-label">W9</text></g></svg>')


def team_history(i: int) -> list[float]:
    """Six weekly scores ending on the table's (rounded) score."""
    last = round(grades_for(i)["score"], 1)
    return [round(last - 0.3 * (5 - k), 1) for k in range(6)]


def changes_page(codes=CODES, date="2026-10-13") -> str:
    events = []
    for i, code in enumerate(codes[:5]):
        h = team_history(i)
        events.append({"date": date, "abbr": {"was": "WSH"}.get(code, code.upper()), "name": NAMES[code],
                       "previous_score": h[-2], "current_score": h[-1], "previous_rank": 3, "current_rank": 2,
                       "change_type": "Weekly Performance", "components": ["QB Stability"]})
    blob = json.dumps({"groups": [{"date": date, "events": events}]})
    return f"<html><script type='application/json'>{blob}</script></html>"


METHOD_PAGE = ("<p>25% QB Stability The quality... 20% Roster Strength x 15% Coaching Direction x 15% Recent "
               "Performance x 10% Offense Strength x 10% Defense Strength x 5% Franchise Direction x</p>"
               "<p>Methodology History June 25, 2026: introduced. August 29, 2026: calibration added.</p>")


class Reply(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def site(fail: set[str] | None = None, table: str | None = None, flaky: dict | None = None):
    """A fake opener serving the made-up pages; `fail` urls raise, `flaky` urls fail n times first."""
    pages = {pfm.RANKINGS_URL: table or rankings_page(), pfm.EXPLOSIVE_URL: explosive_page(),
             pfm.CHANGES_URL: changes_page(), pfm.METHOD_URL: METHOD_PAGE}
    for i, code in enumerate(CODES):
        pages[pfm.TEAM_URL.format(slug=slug(code))] = "<html>" + history_svg(team_history(i)) + "</html>"
    asked: list[str] = []
    flaky = dict(flaky or {})

    def opener(request):
        url = request.full_url
        asked.append(url)
        if url in (fail or set()):
            raise urllib.error.URLError("down")
        if flaky.get(url, 0) > 0:
            flaky[url] -= 1
            raise urllib.error.URLError("blip")
        return Reply(pages[url].encode("utf-8"))
    opener.asked = asked
    return opener


def no_sleep(_):
    pass


class Folder:
    """data_dir pointed at a scratch folder for one test."""

    def __enter__(self):
        import acql.store as store
        self.temp = tempfile.TemporaryDirectory()
        self.store, self.old = store, store.data_dir
        store.data_dir = lambda: Path(self.temp.name)
        return Path(self.temp.name)

    def __exit__(self, *exc):
        self.store.data_dir = self.old
        self.temp.cleanup()


# ---- names ------------------------------------------------------------------------------------------
class Names(unittest.TestCase):
    def test_every_full_name_lands_on_one_known_code(self):
        found = {pfm.team_code(name) for name in NAMES.values()}
        self.assertEqual(found, set(pfm.KNOWN_CODES))
        for code, name in NAMES.items():
            self.assertEqual(pfm.team_code(name), code, name)

    def test_pfm_abbreviations_that_differ(self):
        self.assertEqual(pfm.ABBR["wsh"], "was")
        self.assertEqual(predictions.team_code("Washington Commanders"), "was")


# ---- reading pages --------------------------------------------------------------------------------
class Reading(unittest.TestCase):
    def test_rankings_table_values_and_date(self):
        page = rankings_page()
        teams = pfm.parse_rankings(page)
        self.assertEqual(len(teams), 32)
        self.assertEqual(pfm.effective_date(page), "2026-10-13")
        kc = teams["kc"]
        g = grades_for(CODES.index("kc"))
        self.assertEqual(kc["slug"], "kansas-city-chiefs")
        self.assertAlmostEqual(kc["score"], g["score"])
        for key in pfm.GRADES:
            self.assertAlmostEqual(kc[key], g[key])
        self.assertEqual(kc["name"], "Kansas City Chiefs")     # the sort value, not the cell text with arrows

    def test_duplicate_and_unknown_rows_are_kept_visible(self):
        dup = rankings_page().split("<tbody>")[1].split("</tr>")[0] + "</tr>"
        teams = pfm.parse_rankings(rankings_page(extra_rows=dup))
        self.assertEqual(teams[CODES[0]].get("duplicates"), 1)
        odd = ('<tr><td data-label="Team" data-sort-value="Springfield Atoms">x</td>'
               '<td data-label="PFM Score" data-sort-value="80">80</td></tr>')
        teams = pfm.parse_rankings(rankings_page(extra_rows=odd))
        self.assertIn("Springfield Atoms", teams)

    def test_history_reads_only_the_score_chart(self):
        self.assertEqual(pfm.parse_history(history_svg([80.0, 81.5, 82.0])),
                         [("BASELINE", 80.0), ("W1", 81.5), ("W2", 82.0)])
        self.assertEqual(pfm.parse_history("<svg>no chart</svg>"), [])

    def test_changes_and_methodology(self):
        events = pfm.parse_changes(changes_page())
        self.assertEqual(len(events), 5)
        self.assertEqual(events[0]["date"], "2026-10-13")
        self.assertEqual(pfm.parse_changes("<html>nothing</html>"), [])
        self.assertEqual(pfm.parse_changes("<script>{\"groups\": broken</script>"), [])
        m = pfm.parse_methodology(METHOD_PAGE)
        self.assertEqual(m["version"], "2026-08-29")
        self.assertAlmostEqual(m["weights"]["QB Stability"], 0.25)
        self.assertAlmostEqual(sum(m["weights"].values()), 1.0)

    def test_published_formula(self):
        # the methodology page's own calibration points: raw 82 -> 83.3, 86 -> 89.8, 90 -> 95.0 (capped)
        for raw, public in ((82.0, 83.3), (86.0, 89.8), (90.0, 95.0), (70.0, 69.28)):
            self.assertAlmostEqual(pfm.public_score({k: raw for k in pfm.GRADES}), public, places=1)
        self.assertIsNone(pfm.public_score({"qb_stability": 80}))
        self.assertAlmostEqual(sum(w for _, w in pfm.GRADES.values()), 1.0)


# ---- checking ----------------------------------------------------------------------------------
def built(table=None, history=True, changes=True, explosive=True) -> dict:
    teams = pfm.parse_rankings(table or rankings_page())
    found = pfm.parse_explosiveness(explosive_page()) if explosive else {}
    for i, (code, entry) in enumerate(sorted(teams.items())):
        entry["explosiveness"] = found.get(code)
        entry["history"] = list(map(tuple, zip(["BASELINE", "W1", "W2", "W3", "W4", "W5"],
                                               team_history(CODES.index(code))))) if history else None
    return pfm.build(teams, pfm.effective_date(table or rankings_page()),
                     pfm.parse_changes(changes_page()) if changes else [], pfm.parse_methodology(METHOD_PAGE),
                     [], now=1792360000.0)


class Checking(unittest.TestCase):
    def test_clean_snapshot_has_no_issues(self):
        snap = built()
        self.assertEqual(snap["quality"]["issues"], [])
        self.assertEqual(pfm.status_of(snap["quality"]["issues"], 36, 36), "ok")
        self.assertIn("derived", snap)
        self.assertNotIn("formula_gap", snap["teams"]["kc"])          # derived values never sit with source values

    def test_missing_team_fails(self):
        snap = built(rankings_page(CODES[:31]))
        self.assertEqual(pfm.status_of(snap["quality"]["issues"], 36, 36), "failed")

    def test_out_of_range_fails_and_contradiction_warns(self):
        snap = built(rankings_page(bad={"kc": {"qb_stability": 130.0}}))
        self.assertTrue(any(i["code"] == "range" for i in snap["quality"]["issues"]))
        snap = built(rankings_page(bad={"kc": {"score": 70.0}}))
        codes = {i["code"] for i in snap["quality"]["issues"]}
        self.assertIn("contradiction", codes)                        # the grades say otherwise

    def test_missing_pages_are_partial_not_ok(self):
        snap = built(history=False)
        self.assertEqual(pfm.status_of(snap["quality"]["issues"], 36, 4), "partial")
        snap = built(explosive=False)
        self.assertEqual(pfm.status_of(snap["quality"]["issues"], 36, 36), "partial")

    def test_no_date_fails(self):
        snap = built(rankings_page(stated="never").replace('datetime="never"', ""))
        self.assertEqual(pfm.status_of(snap["quality"]["issues"], 36, 36), "failed")


# ---- fetching and keeping ----------------------------------------------------------------------
class Keeping(unittest.TestCase):
    def test_collect_reads_every_page_with_a_pause(self):
        waits = []
        opener = site()
        snap = pfm.collect(opener=opener, sleep=waits.append, now=1792360000.0)
        self.assertEqual(snap["quality"]["status"], "ok", snap["quality"]["issues"][:3])
        self.assertEqual(len(opener.asked), 36)
        self.assertEqual(len(snap["pages"]), 36)
        self.assertTrue(all(len(p["sha256"]) == 64 for p in snap["pages"]))
        self.assertEqual(waits.count(pfm.PAUSE), 35)

    def test_retries_then_gives_up(self):
        flaky = site(flaky={pfm.EXPLOSIVE_URL: 2})
        snap = pfm.collect(opener=flaky, sleep=no_sleep, now=1.0)
        self.assertEqual(snap["quality"]["status"], "ok")
        down = site(fail={pfm.EXPLOSIVE_URL})
        snap = pfm.collect(opener=down, sleep=no_sleep, now=1.0)
        self.assertEqual(snap["quality"]["status"], "partial")
        self.assertEqual(down.asked.count(pfm.EXPLOSIVE_URL), pfm.TRIES)
        with self.assertRaises(pfm.PfmError):
            pfm.collect(opener=site(fail={pfm.RANKINGS_URL}), sleep=no_sleep, now=1.0)

    def test_save_is_idempotent_and_never_overwrites(self):
        with Folder():
            first = pfm.collect(opener=site(), sleep=no_sleep, now=1792360000.0)
            path, what = pfm.save(first)
            self.assertEqual(what, "saved")
            again = pfm.collect(opener=site(), sleep=no_sleep, now=1792370000.0)
            self.assertEqual(pfm.save(again)[1], "unchanged")
            self.assertEqual(len(pfm.snapshots()), 1)
            moved = pfm.collect(opener=site(table=rankings_page(bad={"kc": {"roster_strength": 71.0}})),
                                sleep=no_sleep, now=1792380000.0)
            pfm.save(moved)
            kept = pfm.snapshots()
            self.assertEqual(len(kept), 2)
            self.assertEqual(kept[0]["content_key"], first["content_key"])   # the old one is still there
            self.assertEqual([e["what"] for e in pfm.imports()], ["saved", "unchanged", "saved"])
            self.assertTrue((pfm.folder() / ".gitignore").read_text().strip().endswith("*"))

    def test_a_failed_pull_keeps_the_last_good_one_and_says_how_old(self):
        with Folder():
            pfm.save(pfm.collect(opener=site(), sleep=no_sleep, now=1792360000.0))
            got = pfm.refresh(opener=site(fail={pfm.RANKINGS_URL}), sleep=no_sleep, now=1792360000.0 + 12 * 86400)
            self.assertEqual(got["what"], "failed")
            self.assertEqual(got["freshness"]["state"], "stale")
            self.assertEqual(len(pfm.snapshots()), 1)
            bad = pfm.collect(opener=site(table=rankings_page(CODES[:30])), sleep=no_sleep, now=1792400000.0)
            self.assertEqual(pfm.save(bad)[1], "refused")
            self.assertEqual(len(pfm.snapshots()), 1)
            self.assertEqual(pfm.imports()[-1]["what"], "refused")

    def test_team_pages_only_when_the_update_moved(self):
        with Folder():
            pfm.save(pfm.collect(opener=site(), sleep=no_sleep, now=1792360000.0))
            opener = site()
            got = pfm.refresh(opener=opener, sleep=no_sleep, now=1792370000.0)
            self.assertEqual(len(opener.asked), 4)                  # same update date: the history is carried
            self.assertEqual(got["what"], "unchanged")
            opener = site(table=rankings_page(stated="2026-10-20"))
            pfm.refresh(opener=opener, sleep=no_sleep, now=1792900000.0)
            self.assertEqual(len(opener.asked), 36)

    def test_freshness_never_calls_stale_current(self):
        snap = built()
        day = 1792360000.0
        self.assertEqual(pfm.freshness(None)["state"], "none")
        self.assertNotEqual(pfm.freshness(snap, now=day)["state"], "stale")
        self.assertEqual(pfm.freshness(snap, now=day + 20 * 86400)["state"], "stale")
        self.assertIn("stale", pfm.freshness(snap, now=day + 20 * 86400)["words"])

    def test_as_of_sees_only_what_was_on_disk(self):
        snap = dict(built(), collected_at=1792360000.0, effective_date="2026-10-13")
        snap["quality"] = {"status": "ok"}
        self.assertIsNone(pfm.as_of(1792360000.0 - 1, [snap]))      # read after the moment asked about
        self.assertIs(pfm.as_of(1792360000.0 + 1, [snap]), snap)
        later = dict(snap, effective_date="2026-12-01")
        self.assertIsNone(pfm.as_of(1792360000.0 + 1, [later]))     # states an update from the future
        broken = dict(snap, quality={"status": "failed"})
        self.assertIsNone(pfm.as_of(1792360000.0 + 1, [broken]))

    def test_revisions_are_found(self):
        a, b = built(), built()
        b["teams"]["kc"]["history"] = [(l, v + (1.0 if l == "W2" else 0.0)) for l, v in a["teams"]["kc"]["history"]]
        found = pfm.revisions([a, b])
        self.assertEqual([(r["code"], r["label"]) for r in found], [("kc", "W2")])


# ---- the study ----------------------------------------------------------------------------------
LOCK = {w: 1789000000.0 + (w - 1) * 7 * 86400 for w in range(1, 30)}   # Wednesday-ish deadlines, a week apart


def snapshot_with(history: dict[str, list[float]], collected: float, stated: str, grades: dict | None = None) -> dict:
    teams = {}
    for code, values in history.items():
        labels = ["BASELINE"] + [f"W{n}" for n in range(1, len(values))]
        teams[code] = {"score": values[-1], "history": list(zip(labels, values)),
                       **{g: (grades or {}).get(code, {}).get(g) for g in study.GRADES}}
    return {"schema": pfm.SCHEMA, "collected_at": collected, "effective_date": stated, "teams": teams,
            "changes": [], "quality": {"status": "ok"}, "file": f"s{collected:.0f}.json"}


def books(weeks: int, games: int, seed: int, pfm_matters: float, scores: dict[str, list[float]]) -> pd.DataFrame:
    """Invented books: a line, Deadeye's chance near the line's, and results in
    which the PFM gap (from `scores`, week by week) counts `pfm_matters`."""
    from acql.training import probability
    curve = probability.InUse()
    draw = np.random.default_rng(seed)
    rows = []
    for week in range(1, weeks + 1):
        order = draw.permutation(len(CODES))
        for g in range(games):
            home, away = CODES[order[2 * g]], CODES[order[2 * g + 1]]
            gap = scores[home][week - 1] - scores[away][week - 1]
            line = float(round(draw.normal(0, 5) * 2) / 2)
            actual = float(round(line + pfm_matters * gap + draw.normal(0, 13)))
            margin = line + draw.normal(0, 0.5)
            rows.append({"season": 2026, "week": week, "home": home, "away": away,
                         "game": f"2026-{week:02d}-{away}@{home}", "locked_at": LOCK[week], "actual": actual,
                         "credited_home": 1.0 if actual > 0 else 0.0 if actual < 0 else np.nan,
                         "pool_line": np.nan, "pool_favourite": "", "deadeye_live": margin,
                         "deadeye_chance": probability.home_chance(curve, margin, np.nan, ""),
                         "line_used": line, "used_at": LOCK[week] - 3600, "taken_at": np.nan,
                         "line_deadline": line})
    return pd.DataFrame(rows)


def scores_for(weeks: int, seed: int) -> dict[str, list[float]]:
    draw = np.random.default_rng(seed)
    return {c: list(np.round(80 + draw.normal(0, 5) + np.cumsum(draw.normal(0, 0.5, weeks)), 1)) for c in CODES}


def history_only(scores: dict[str, list[float]], weeks: int, collected: float) -> dict:
    """One snapshot read late, carrying BASELINE..W(weeks-1) as history."""
    return snapshot_with({c: v[:weeks] for c, v in scores.items()}, collected, "2026-12-30")


class AsOf(unittest.TestCase):
    def test_week_uses_the_score_from_after_the_week_before(self):
        scores = scores_for(6, 3)
        snap = history_only(scores, 6, collected=LOCK[11])
        points = study.history_points(snap)
        self.assertEqual(sorted(set(points["after_week"])), [0, 1, 2, 3, 4, 5])
        known = study.pfm_for_week(4, LOCK[4], [], points)
        self.assertEqual(known["from"], "history")
        self.assertTrue(known["inferred"])
        self.assertAlmostEqual(known["teams"]["kc"]["score"], scores["kc"][3])     # W3, after week 3

    def test_history_published_on_or_after_the_deadline_is_refused(self):
        scores = scores_for(4, 3)
        snap = history_only(scores, 4, collected=LOCK[11])
        points = study.history_points(snap)
        from datetime import datetime, timezone
        lock_day = datetime.fromtimestamp(LOCK[3], timezone.utc).date().isoformat()
        points.loc[points["after_week"] == 2, "published"] = lock_day
        self.assertEqual(study.pfm_for_week(3, LOCK[3], [], points)["teams"], {})

    def test_a_snapshot_read_after_the_deadline_is_never_used_for_it(self):
        scores = scores_for(4, 3)
        late = snapshot_with({c: v[:2] for c, v in scores.items()}, LOCK[3] + 60, "2026-09-01",
                             grades={c: {"qb_stability": 80.0} for c in CODES})
        points = study.history_points({})
        self.assertEqual(study.pfm_for_week(3, LOCK[3], [late], points)["from"], "")
        self.assertEqual(study.pfm_for_week(4, LOCK[4], [late], points)["from"], "snapshot")

    def test_orientation_is_home_less_road(self):
        scores = scores_for(4, 5)
        frame = books(4, 8, 1, 0.0, scores)
        snap = history_only(scores, 4, collected=LOCK[11])
        table = study.table(frame, [snap])
        flipped = frame.rename(columns={"home": "away", "away": "home"})
        table2 = study.table(flipped, [snap])
        here = table["score_diff"].notna()
        self.assertTrue(here.any())
        np.testing.assert_allclose(table.loc[here, "score_diff"], -table2.loc[here, "score_diff"])
        row = table[here].iloc[0]
        w = int(row["week"])
        self.assertAlmostEqual(row["score_diff"], scores[row["home"]][w - 1] - scores[row["away"]][w - 1])


class Teaching(unittest.TestCase):
    def setUp(self):
        self.scores = scores_for(14, 11)
        self.snap = history_only(self.scores, 14, collected=LOCK[11] + 90 * 86400)

    def frame(self, matters: float, seed: int = 2, weeks: int = 14, games: int = 16) -> pd.DataFrame:
        return study.table(books(weeks, games, seed, matters, self.scores), [self.snap])

    def test_production_column_is_untouched(self):
        frame = self.frame(0.0)
        found = study.variants(frame)
        np.testing.assert_array_equal(found["A Deadeye (production)"].chance, frame["deadeye_chance"].to_numpy(float))

    def test_untaught_and_missing_keep_the_base_chance(self):
        frame = self.frame(0.0)
        frame.loc[frame.index[::5], "score_diff"] = np.nan
        found = study.walk(frame, "deadeye_chance", ["score_diff"])
        base = frame["deadeye_chance"].to_numpy(float)
        np.testing.assert_array_equal(found.chance[~found.taught], base[~found.taught])
        self.assertFalse(found.taught[frame["score_diff"].isna().to_numpy()].any())
        self.assertFalse(found.taught[frame["week"].to_numpy() <= 3].any())   # 48 games but < MIN_TRAIN before wk 4

    def test_heavy_shrinkage_gives_back_the_base(self):
        frame = self.frame(0.5)
        found = study.walk(frame, "deadeye_chance", ["score_diff"], ridge=1e12)
        np.testing.assert_allclose(found.chance, frame["deadeye_chance"].to_numpy(float), atol=1e-9)

    def test_reproducible_and_bounded(self):
        frame = self.frame(0.5)
        a = study.walk(frame, "deadeye_chance", ["score_diff"]).chance
        b = study.walk(frame.copy(), "deadeye_chance", ["score_diff"]).chance
        np.testing.assert_array_equal(a, b)
        self.assertTrue(((a > 0) & (a < 1)).all())

    def test_sealed(self):
        frame = self.frame(0.5)
        for week in (5, 9, 14):
            ok, what = study.sealed(frame, week)
            self.assertTrue(ok, what)

    def test_finds_a_planted_signal_and_not_an_absent_one(self):
        planted = self.frame(0.8, weeks=14, games=16)
        marks, keep = study.mark(planted, study.variants(planted))
        c = next(m for m in marks if m.name.startswith("C Deadeye"))
        self.assertLess(c.vs_a, 0)
        self.assertLess(c.high, 0, "a strong planted PFM signal should be found")
        none = self.frame(0.0, seed=4, weeks=14, games=16)
        marks, _ = study.mark(none, study.variants(none))
        call, _ = study.verdict(marks)
        self.assertNotEqual(call, "improvement")

    def test_too_few_games_is_inconclusive(self):
        frame = self.frame(0.8, weeks=6, games=8)
        marks, _ = study.mark(frame, study.variants(frame))
        self.assertEqual(study.verdict(marks)[0], "inconclusive")

    def test_earned_rule_only_looks_back(self):
        frame = self.frame(0.8)
        early = study.earned(frame, 5)
        self.assertEqual(early, [])                                  # too few earlier games to earn anything
        shaken = frame.copy()
        shaken.loc[shaken["week"] >= 9, "credited_home"] = 1.0
        self.assertEqual(study.earned(frame, 9), study.earned(shaken, 9))


class Ledger(unittest.TestCase):
    def test_shadow_written_once_and_only_before_the_deadline(self):
        with tempfile.TemporaryDirectory() as where:
            where = Path(where)
            result = {"upcoming": [{"game": "g1", "week": 7, "home": "kc", "away": "den", "locked_at": 1000.0,
                                    "shadow": 0.6, "deadeye": 0.58, "line_used": 3.0, "pfm_from": "snapshot",
                                    "pfm_effective": "2026-10-13", "pfm_home": 90.0, "pfm_away": 82.0}]}
            frame = pd.DataFrame([{"game": "g1", "used_at": 900.0, "taken_at": np.nan}])
            self.assertEqual(study.record_shadow(result, frame, now=500.0, where=where), 1)
            self.assertEqual(study.record_shadow(result, frame, now=600.0, where=where), 0)
            self.assertEqual(study.record_shadow(result, frame, now=1500.0, where=where), 0)
            line = json.loads((where / "shadow.jsonl").read_text().splitlines()[0])
            self.assertFalse(line["official"])
            for key in ("model_version", "feature_version", "market", "pfm", "deadeye_chance", "shadow_chance",
                        "made_at"):
                self.assertIn(key, line)


# ---- production stays as it was -------------------------------------------------------------------
class Production(unittest.TestCase):
    def test_pricing_never_reads_pfm(self):
        for name in ("acql/model/pricing.py", "acql/model/predictions.py", "acql/analytics.py",
                     "acql/model/ledger.py", "acql/pool/cards.py"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("pfm", text.lower(), name)

    def test_the_dashboard_reads_the_study_only_through_its_file(self):
        import re
        importing = re.compile(r"^\s*(?:from|import)\s+(?:acql\.training|\.+training)", re.M)
        for path in (ROOT / "acql").rglob("*.py"):
            if "training" in path.parts:
                continue
            found = importing.search(path.read_text(encoding="utf-8"))
            self.assertIsNone(found, f"{path} imports the training package")

    def test_share_is_unchanged(self):
        self.assertEqual(predictions.CONSENSUS_WEIGHT, 0.25)

    def test_study_writes_nothing_the_card_reads(self):
        text = (ROOT / "acql/training/pfm.py").read_text(encoding="utf-8")
        self.assertNotIn("store.put", text)
        self.assertNotIn("forecastlog", text)


# ---- the Model Lab's reader ----------------------------------------------------------------------
class Reader(unittest.TestCase):
    def test_reads_a_result_and_marks_shadow_as_such(self):
        with tempfile.TemporaryDirectory() as where:
            path = Path(where) / "latest.json"
            path.write_text(json.dumps({
                "call": "inconclusive", "why": "too few", "made": 1792360000.0, "games": 41,
                "freshness": {"state": "stale", "words": "PFM update of 2026-10-01 - stale"},
                "seals": [{"week": 2, "ok": True}],
                "marks": [{"name": "A Deadeye (production)", "games": 41, "taught": 0, "logloss": 0.68, "brier": 0.24,
                           "vs_a": 0.0, "low": 0.0, "high": 0.0},
                          {"name": "C Deadeye + PFM score", "games": 41, "taught": 41, "logloss": 0.67, "brier": 0.24,
                           "vs_a": -0.004, "low": -0.02, "high": 0.02},
                          {"name": "D Deadeye + qb stability", "games": 41, "taught": 0, "logloss": 0.68,
                           "brier": 0.24, "vs_a": 0.0, "low": 0.0, "high": 0.0}],
                "upcoming": [{"week": 7, "home": "kc", "away": "den", "pfm_home": 90.0, "pfm_away": 82.0,
                              "score_diff": 8.0, "deadeye": 0.7, "market": 0.69, "shadow": 0.72}]}))
            found = pfmcheck.read(path)
            self.assertEqual(found.call, "inconclusive")
            self.assertEqual([r[0] for r in found.rows], ["A Deadeye (production)", "C Deadeye + PFM score"])
            self.assertEqual(found.rows[1][6], "can't tell from luck yet")
            self.assertEqual(found.week, 7)
            self.assertEqual(found.week_rows[0][-1], "+2.0 pts")
            self.assertEqual(found.fresh_state, "stale")
            self.assertTrue(found.sealed)

    def test_damaged_or_missing_is_no_answer(self):
        with tempfile.TemporaryDirectory() as where:
            path = Path(where) / "latest.json"
            self.assertIsNone(pfmcheck.read(path))
            path.write_text("{half")
            self.assertIsNone(pfmcheck.read(path))


if __name__ == "__main__":
    unittest.main(verbosity=1)
