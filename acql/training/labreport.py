"""The strategy lab's report: what each strategy added, what was redundant, where the data runs out.

Written from a run's results (strategylab.run) into its folder and into
data/training/lab/latest/report.md. Plain markdown; nothing here computes a
number the results do not already hold.

No Qt here.
"""

from __future__ import annotations

import math
from pathlib import Path

from . import strategylab as lab


def _f(x, places=4, sign=True) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "-"
    return f"{x:+.{places}f}" if sign else f"{x:.{places}f}"


def _p(x) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "-"
    return "<0.001" if x < 0.001 else f"{x:.3f}"


def _range(d: dict | None, places=4) -> str:
    if not d:
        return "-"
    return f"{_f(d.get('edge'), places)} ({_f(d.get('low'), places)} to {_f(d.get('high'), places)})"


def _pool(d: dict | None) -> str:
    if not d or not d.get("weeks"):
        return "-"
    return f"{_f(d.get('diff_per_week'), 2)} ({_f(d.get('low'), 2)} to {_f(d.get('high'), 2)})"


def _beyond(d: dict | None) -> str:
    if not d:
        return "-"
    return f"{d['weight']:+.2f} (z {d['z']:+.1f})"


def _rows(specs: dict, which: str) -> list[str]:
    head = ("| Strategy | Family | Log loss | Brier | Calib. error | Sharpness | vs Deadeye, log loss a game (95%) | p | "
            "Holm p | vs market | ACQL picks a week vs Deadeye (95%) | View corr. w/ Deadeye | Weight beyond market (z) | "
            "Status |")
    out = [head, "|" + "---|" * (head.count("|") - 1)]
    order = sorted(specs.values(), key=lambda s: (s[which] or {}).get("logloss", 9))
    for s in order:
        d = s[which]
        if not d:
            continue
        name = s["spec"]["name"] + (" *(round 2)*" if s["spec"]["round"] == 2 else "") + \
            (" *(tried before)*" if s.get("tried_before") else "")
        out.append(f"| {name} | {s['spec']['family']} | {d['logloss']:.4f} | {d['brier']:.4f} | {d['calibration']:.3f} | "
                   f"{d['sharpness']:.3f} | {_range(d['vs_deadeye'])} | {_p(d['vs_deadeye']['p'])} | "
                   f"{_p(d.get('holm_vs_deadeye'))} | {_f(d['vs_market']['edge'])} | {_pool(d['pool_vs_deadeye'])} | "
                   f"{_f(d.get('view_corr_deadeye'), 2, False)} | {_beyond(d.get('beyond_market'))} | {s['status']} |")
    return out


def _sufficiency(res: dict) -> list[str]:
    out = ["| Timing | Games | Development seasons | Dev games | Test seasons | Test games | "
           "Smallest edge vs Deadeye the dev games could detect* |", "|---|---|---|---|---|---|---|"]
    for timing, t in res["timings"].items():
        dead = t["specs"].get(lab.MARKET_SPEC.id, {}).get("dev") or {}
        se = (dead.get("vs_deadeye") or {}).get("se")
        mde = f"{2.8 * se:.4f}" if se else "-"
        ds, ts = t["dev_seasons"], t["test_seasons"]
        out.append(f"| {timing} | {t['games']:,} | {ds[0]}-{ds[-1]} | {t['dev_games']:,} | "
                   f"{ts[0]}-{ts[-1]} | {t['test_games']:,} | {mde} |" if ds and ts else
                   f"| {timing} | {t['games']:,} | - | {t['dev_games']} | - | {t['test_games']} | {mde} |")
    out.append("")
    out.append("*Roughly 2.8 standard errors (5% one-sided test, 80% power) of the market-vs-Deadeye difference on "
               "development. The Model Lab's own bar for a switch is 0.010 a game.")
    return out


def _contexts(spec: dict) -> list[str]:
    ctx = (spec.get("dev") or {}).get("contexts") or {}
    if not ctx:
        return []
    out = [f"**{spec['spec']['name']}** against Deadeye, development games, by situation:", "",
           "| Situation | Games | Log loss a game vs Deadeye (95%) |", "|---|---|---|"]
    for label, c in ctx.items():
        out.append(f"| {label} | {c['games']} | {_range(c)} |")
    return out + [""]


def _weights(spec: dict) -> list[str]:
    states = spec.get("states") or {}
    if not states:
        return []
    last = states[max(states)]
    w = last.get("weights") or {}
    if not w:
        return []
    shown = ", ".join(f"{k} {v:+.3f}" for k, v in w.items())
    return [f"- **{spec['spec']['name']}**, as taught for {max(states)} (penalty {last.get('penalty')}): {shown}"]


def write(res: dict, where: Path) -> str:
    prim = res["protocol"]["primary_timing"]
    t = res["timings"][prim]
    specs = t["specs"]
    names = {i: s["spec"]["name"] for i, s in specs.items()}
    nominee = res.get("nominee")
    lines = [f"# Strategy lab report - run {res['run']}", "",
             f"Protocol `{res['protocol']['id']}` (fingerprint {res['protocol_mark']}, registered "
             f"{res['protocol']['registered']}), lab {res['lab']}, code {res['code'] or 'unknown'}. "
             f"Took {res['took']:.0f}s. Nothing in this report changes a pick.", ""]

    # the short of it
    lines += ["## The short of it", ""]
    if nominee:
        lines.append(f"- **Nominated for the owner's review:** {names[nominee]} passed every gate. This is a "
                     "nomination only - Deadeye stays the champion until it is switched by hand.")
    else:
        lines.append("- **Nothing nominated.** No strategy passed the predefined gates. Deadeye stays the champion "
                     "and nothing changes.")
    dead_dev = specs[lab.DEADEYE_SPEC.id]["dev"]
    mkt_dev = specs[lab.MARKET_SPEC.id]["dev"]
    lines.append(f"- **Deadeye against the market** at the {prim} line (development): log loss "
                 f"{dead_dev['logloss']:.4f} vs {mkt_dev['logloss']:.4f}; the market's lead "
                 f"{_range(mkt_dev['vs_deadeye'])}.")
    dead_test = specs[lab.DEADEYE_SPEC.id].get("test") or {}
    mkt_test = specs[lab.MARKET_SPEC.id].get("test") or {}
    if dead_test and mkt_test:
        lines.append(f"- **Same on the untouched test seasons:** Deadeye {dead_test['logloss']:.4f}, market "
                     f"{mkt_test['logloss']:.4f}; the market's lead {_range(mkt_test['vs_deadeye'])}.")
    ahead = [s for s in specs.values() if s["dev"] and not s["spec"]["baseline"]
             and s["dev"]["vs_deadeye"]["low"] > 0]
    lines.append(f"- **Clear of Deadeye on development before correction:** {len(ahead)} of "
                 f"{res['tried']} candidates; after Holm over {res['holm_family']} hypotheses: "
                 f"{sum(1 for s in specs.values() if (s['dev'] or {}).get('holm_vs_deadeye', 1) < res['protocol']['alpha'] and not s['spec']['baseline'])}.")
    redundant = [s["spec"]["name"] for s in specs.values() if s["status"].startswith("redundant")]
    worse = [s["spec"]["name"] for s in specs.values() if s["status"].startswith("failed: clearly")]
    if redundant:
        lines.append(f"- **Redundant with Deadeye** (same view of the game, no measurable difference): "
                     + "; ".join(redundant) + ".")
    if worse:
        lines.append(f"- **Clearly worse than Deadeye** on development: " + "; ".join(worse) + ".")
    leak = res.get("leak")
    lines.append(f"- **Leak check:** {'passed' if leak and leak[0] else 'FAILED' if leak else 'not run'}"
                 + (f" - {leak[1]}" if leak else "") + ".")
    lines.append(f"- **The test seasons** have been opened {res['test_openings']} time(s) under this protocol "
                 "(each run that scores them counts).")
    lines.append("")

    lines += ["## 1. Does the data support this design?", ""] + _sufficiency(res) + [""]
    lines += ["What that means:", "",
              "- The Thursday deadline line itself exists only for this season's own records (about 60 games). "
              "The archive's midweek line (2013 on) is the nearest stand-in and is the headline; the opening and "
              "last-updated lines are diagnostics.",
              "- Learned strategies need three seasons to learn from and the meta-learner two more seasons of "
              "out-of-sample predictions, so at the midweek line the development window is short.",
              "- The computer models' numbers in the archive carry no time stamp; at the midweek line some may "
              "have been posted later than a Thursday card could have seen. Treat any model-based edge as an "
              "upper bound.",
              "- Team ratings (Elo, the scoring model) are built only from results of earlier weeks, from nflverse "
              "and the archive. Totals and moneylines exist only at the close, so they are not used at the deadline.",
              ""]

    lines += ["## 2. Every candidate, development seasons", "",
              "Positive edges mean better than Deadeye (log loss a game; lower log loss is better). p is one-sided, "
              "weeks treated as independent clusters; Holm p corrects for every candidate tried under this protocol. "
              "'View corr.' is how alike the strategy's disagreement with the market is to Deadeye's. 'Weight beyond "
              "market' is the weight a logistic fit gives the strategy's view on top of the market (z near 0: it adds "
              "nothing the line lacks).", ""] + _rows(specs, "dev") + [""]

    lines += ["## 3. Finalists on the untouched test seasons", "",
              f"Frozen before scoring (freeze.json): " + ", ".join(names.get(i, i) for i in res["finalists"]) + ".", ""]
    lines += _rows({i: s for i, s in specs.items() if s.get("test")}, "test") + [""]
    lines += ["Gates (every one must hold for a nomination):", ""]
    for i in res["finalists"]:
        g = specs[i].get("gates") or {}
        failed = [k for k, ok in g.items() if not ok]
        lines.append(f"- **{names[i]}**: " + ("passes every gate" if not failed else "fails: " + "; ".join(failed)))
    lines.append("")

    lines += ["## 4. The meta-learner: what it learned, and when strategies help", ""]
    for s in specs.values():
        if s["spec"]["family"] == "stack":
            lines += _weights(s)
    lines.append("")
    best_stack = min((s for s in specs.values() if s["spec"]["family"] == "stack" and s["dev"]),
                     key=lambda s: s["dev"]["logloss"], default=None)
    if best_stack:
        lines += _contexts(best_stack)

    lines += ["## 5. The market at each timing, and the close", "",
              "On the games every timing shares (the same games for every row):", "",
              "| Line | Games | Log loss | Brier | Picks right |", "|---|---|---|---|---|"]
    ref = res.get("closing_reference") or {}
    for k, v in ref.items():
        if isinstance(v, dict):
            lines.append(f"| {k} | {v['games']} | {v['logloss']:.4f} | {v['brier']:.4f} | {v['right']} |")
    lines.append("")
    for timing, tt in res["timings"].items():
        if timing == prim:
            continue
        sp = tt["specs"]
        top = sorted((s for s in sp.values() if s["dev"]), key=lambda s: s["dev"]["logloss"])[:5]
        lines.append(f"**Diagnostic: the {timing} line** - best five on development:")
        lines.append("")
        for s in top:
            x = s.get("test") or {}
            lines.append(f"- {s['spec']['name']}: log loss {s['dev']['logloss']:.4f}, vs Deadeye "
                         f"{_range(s['dev']['vs_deadeye'])}" + (f"; test {_range(x['vs_deadeye'])}" if x else ""))
        lines.append("")

    lines += ["## 6. ACQL scoring", "",
              "ACQL gives one point for each pick credited under the commissioner's line (plus Big Losers); picks "
              "are not ranked by confidence. So the only allocation decision a probability drives is the side, and "
              "the pool card counts picks credited a week by taking each strategy's more likely side. It is scored "
              "apart from probability quality: a strategy can have better chances and the same picks.", ""]

    lines += ["## 7. Where everything is", "",
              f"- Every strategy's chance for every game, with the result: `{', '.join(a['file'] for a in res['archive'].values())}` "
              "in this run's folder (sha256 in results.json).",
              "- Every candidate ever tried, with its status: `data/training/lab/registry.jsonl` (append-only).",
              "- Locked weekly forecasts: `data/training/lab/locked/` (`python -m acql.training lab verify`).",
              "- The nomination (if any): `data/training/lab/nominee.json`. Nothing reads it to make picks.", ""]
    text = "\n".join(lines)
    (Path(where) / "report.md").write_text(text, encoding="utf-8")
    return text


# ---- strategy-lab-2: two tracks, two champions ------------------------------------------------------
def _picks(d: dict | None) -> str:
    if not d or d.get("weeks", 0) < 2:
        return "-"
    return f"{_f(d.get('edge'), 2)} ({_f(d.get('low'), 2)} to {_f(d.get('high'), 2)})"


def _track_rows(specs: dict, which: str, track: str) -> list[str]:
    acql = track == "acql"
    head = ("| Strategy | Family | Log loss | Brier | Calib. error | Sharpness | vs Deadeye, log loss a game (95%) | "
            "vs market | " + ("ACQL picks a week vs Deadeye (95%) | p | Holm p | Games on another side | "
                              if acql else "p | Holm p | View corr. w/ Deadeye | Weight beyond market (z) | ")
            + "Status |")
    out = [head, "|" + "---|" * (head.count("|") - 1)]

    def order_key(s):
        d = s[which]
        first = -((d.get("picks_vs_deadeye") or {}).get("edge") or 0.0) if acql else 0.0
        return (first, d["logloss"])

    for s in sorted((s for s in specs.values() if s.get(which)), key=order_key):
        d = s[which]
        name = s["spec"]["name"] + (" *(round 2)*" if s["spec"]["round"] == 2 else "") + \
            (" *(tried before)*" if s.get("tried_before") else "")
        row = (f"| {name} | {s['spec']['family']} | {d['logloss']:.4f} | {d['brier']:.4f} | {d['calibration']:.3f} | "
               f"{d['sharpness']:.3f} | {_range(d['vs_deadeye'])} | {_f(d['vs_market']['edge'])} | ")
        if acql:
            pk = d.get("picks_vs_deadeye") or {}
            row += f"{_picks(pk)} | {_p(pk.get('p'))} | {_p(d.get('holm_vs_deadeye'))} | {pk.get('flips', '-')} | "
        else:
            row += (f"{_p(d['vs_deadeye']['p'])} | {_p(d.get('holm_vs_deadeye'))} | "
                    f"{_f(d.get('view_corr_deadeye'), 2, False)} | {_beyond(d.get('beyond_market'))} | ")
        out.append(row + f"{s.get('status', '-')} |")
    return out


def _baseline_line(specs: dict, which: str, track: str) -> str:
    dead = specs.get(lab.DEADEYE_SPEC.id, {}).get(which) or {}
    mkt = specs.get(lab.MARKET_SPEC.id, {}).get(which) or {}
    if not dead or not mkt:
        return "-"
    text = (f"Deadeye {dead['logloss']:.4f}, market {mkt['logloss']:.4f} log loss over {dead['games']:,} games; "
            f"the market's lead over Deadeye {_range(mkt['vs_deadeye'])}")
    if track == "acql":
        text += (f"; picks right {mkt['right']} (market) vs {dead['right']} (Deadeye), the market's lead "
                 f"{_picks(mkt.get('picks_vs_deadeye'))} a week")
    return text


def write2(res: dict, where: Path) -> str:
    """The report for a strategy-lab-2 run (strategylab.run2)."""
    p = res["protocol"]
    prim = res["primary_timing"]
    seen = p["seen_seasons"]
    lines = [f"# Strategy lab report - run {res['run']} (two tracks)", "",
             f"Protocol `{p['id']}` (fingerprint {res['protocol_mark']}, registered {p['registered']}), lab "
             f"{res['lab']}, code {res['code'] or 'unknown'}. Took {res['took']:.0f}s. Nothing in this report "
             "changes a pick, and Deadeye stays the champion on both tracks.", "",
             "## The two questions, kept apart", ""]
    for track, about in p["tracks"].items():
        lines.append(f"- **{track}** - {about['question']}. Every strategy gives {about['chance']}, is taught on "
                     f"that answer alone, and is judged by {about['measure']}.")
    lines += ["",
              "Development (the seasons before 2023) chooses each track's finalists, frozen in freeze.json before "
              f"anything else is scored. {seen[0]}-{seen[-1]} are shown as **seen**: {p['seen_note']}. "
              f"The test is {p['test']}; only that can earn a nomination.", ""]

    lines += ["## The short of it", ""]
    for track, tr in res["tracks"].items():
        specs = tr["timings"][prim]["specs"]
        names = {i: s["spec"]["name"] for i, s in specs.items()}
        leak = (res.get("leak") or {}).get(track)
        lines.append(f"- **{track.capitalize()} track**, {prim} line, development: "
                     f"{_baseline_line(specs, 'dev', track)}.")
        lines.append(f"  - Seen seasons (record only): {_baseline_line(specs, 'seen', track)}.")
        lines.append("  - Finalists (frozen): " + "; ".join(f"{names.get(i, i)} - {specs[i]['status']}"
                                                         for i in tr["finalists"]) + ".")
        lines.append(f"  - Holm family on development: {tr['holm_family']} hypotheses (this run's {tr['tried']}, "
                     "plus every one tried before for this question or under strategy-lab-1).")
        lines.append(f"  - Leak check: {'passed' if leak and leak[0] else 'FAILED' if leak else 'not run'}"
                     + (f" - {leak[1]}" if leak else "") + ".")
    lines.append("- **Nominations:** none - no locked week has been scored under this protocol yet.")
    lines.append("")

    for n, (track, tr) in enumerate(res["tracks"].items(), start=1):
        t = tr["timings"][prim]
        specs = t["specs"]
        span = f"{t['dev_seasons'][0]}-{t['dev_seasons'][-1]}, " if t["dev_seasons"] else ""
        lines += [f"## {n}. {track.capitalize()} track: every candidate, development ({span}{t['dev_games']:,} games)",
                  ""]
        if track == "acql":
            lines += ["Sorted by ACQL picks credited a week against Deadeye's card (each strategy takes its likelier "
                      "side). 'Games on another side' counts the games where the strategy and Deadeye took different "
                      "sides - the only games that can move the pool score.", ""]
        else:
            lines += ["Sorted by home-win log loss. Positive edges are better than Deadeye. The market here is the "
                      "line at that timing on the straight-up curve (the archive has no moneyline before the close).",
                      ""]
        lines += _track_rows(specs, "dev", track) + [""]
        if t["seen_seasons"]:
            lines += [f"**Seen seasons ({t['seen_seasons'][0]}-{t['seen_seasons'][-1]}, {t['seen_games']:,} games) - "
                      "for the record, not evidence:**", ""]
            lines += _track_rows({i: s for i, s in specs.items() if s.get("seen")}, "seen", track) + [""]
        for timing, tt in tr["timings"].items():
            if timing != prim:
                lines.append(f"- Diagnostic, {timing} line: {_baseline_line(tt['specs'], 'dev', track)}.")
        ref = (res.get("closing_reference") or {}).get(track) or {}
        if ref:
            lines += ["", f"The market at each timing, on the {ref.get('games', 0):,} games every timing shares:", "",
                      "| Line | Games | Log loss | Brier |", "|---|---|---|---|"]
            for k, v in ref.items():
                if isinstance(v, dict):
                    lines.append(f"| {k} | {v['games']} | {v['logloss']:.4f} | {v['brier']:.4f} |")
        lines.append("")

    k = len(res["tracks"])
    lines += [f"## {k + 1}. Gates on the locked weeks (written before any was scored)", ""]
    for track, gates in p["gates"].items():
        lines.append(f"**{track}**")
        lines += [f"- {g}" for g in gates]
        lines.append("")
    lines += ["`python -m acql.training lab score` scores the locked weeks on both tracks and writes "
              "data/training/lab/champions.json. A finalist that passes every gate is a nomination for the owner, "
              "never a switch.", "",
              f"## {k + 2}. Where everything is", "",
              "- Every strategy's chance for every game, per track and timing, with the answer: "
              f"`{', '.join(a['file'] for a in res['archive'].values())}` (sha256 of the unzipped CSV in results.json).",
              "- Every candidate ever tried, per track: `data/training/lab/registry.jsonl` (append-only).",
              "- The champions, one per track: `data/training/lab/champions.json`.", ""]
    text = "\n".join(lines)
    (Path(where) / "report.md").write_text(text, encoding="utf-8")
    return text
