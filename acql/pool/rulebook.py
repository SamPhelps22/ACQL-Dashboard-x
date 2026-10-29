"""The Rulebook Explorer's rules: what the pool's own code and exports enforce.

Every rule here is one the project already applies - each names the file
(and where it matters, the constant) it comes from, so the website can never
state a rule the scoring doesn't follow. The numbers in the wording (the Big
Loser margin, how many Big Loser picks, the buy-in) are read from the same
constants the scoring reads, so changing one changes both.

Rules nobody has written down - the prize amounts of the side pools, whether
a suicide team may be used twice - are listed as unverified rather than
guessed. Only the current season's rules are on file: there is no earlier
rulebook in the project, so earlier seasons say so instead of borrowing
these.

Nothing here changes a score. The website shows it (poolpage.snapshot puts
`rulebook()` in the page's data).
"""

from __future__ import annotations

from ..config import BIG_LOSER_PICKS, DEFAULT_BUY_IN

VERIFIED = "verified"        # applied by the pool's code, checked against the official exports
ON_RECORD = "on record"      # stated by the commissioner / Sam and applied by the code
UNVERIFIED = "unverified"    # mentioned in the files, but the rule itself isn't written anywhere

CATEGORIES = [
    ("scoring", "Main pool scoring"),
    ("weekly", "Weekly results"),
    ("season", "Season standings"),
    ("ties", "Tie-breaking"),
    ("suicide", "Suicide Pool"),
    ("bigloser", "Big Loser"),
    ("side", "Other side pools"),
    ("deadlines", "Deadlines and submitting picks"),
    ("history", "Rule changes"),
]


def _blowout() -> int:
    from ..feeds.results import BLOWOUT
    return int(BLOWOUT)


def _deadline_words() -> str:
    from ..feeds.oddslock import DEADLINE
    day = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][DEADLINE[0]]
    hour, minute = DEADLINE[1], DEADLINE[2]
    clock = f"{(hour - 1) % 12 + 1}:{minute:02d} {'pm' if hour >= 12 else 'am'}"
    return f"{day} {clock}"


def rules(buy_in: float | None = None) -> list[dict]:
    """Every rule, in category order. Each one: id, category, title, rule,
    applies, how, example (hypothetical, labelled), exceptions, links (site
    pages), source (where it is enforced), status, seasons."""
    blow = _blowout()
    picks = int(BIG_LOSER_PICKS)
    fee = float(buy_in if buy_in else DEFAULT_BUY_IN)
    fee_text = f"${fee:,.0f}" if fee == int(fee) else f"${fee:,.2f}"
    out = [
        # ---- main pool scoring ----
        dict(id="one-win-per-game", category="scoring", title="One win for every game picked right",
             rule="Every week each coach picks a side in every game on the commissioner's sheet. Each pick the pool credits is one win.",
             applies="Every game on every week's sheet.",
             how="A card's regular wins are the number of its picks that match the side credited with each game (see how lined games are credited).",
             example="Hypothetical: a 16-game week. Coach Ava's sheet matches the credited side in 11 games, so she has 11 regular wins.",
             exceptions="A game that ends level with no line is credited to nobody (see Unlined ties).",
             links=["picks", "weeks"], source="acql/pool/standings.py (regrade) and the commissioner's graded sheets",
             status=VERIFIED),
        dict(id="lined-games", category="scoring", title="Lined games: the favourite must cover",
             rule="When the sheet gives a game a line, the favourite is credited only if it wins by at least the line. A win by exactly the line counts for the favourite. Otherwise the underdog is credited, even if it lost the game.",
             applies="Every game the sheet lists with a favourite and a line.",
             how="Points needed = the line rounded up to a whole number (a 3-point line needs 3, a 3.5-point line needs 4). Favourite's winning margin ≥ points needed → favourite credited; anything less → underdog credited.",
             example="Hypothetical: Hawks favoured by 6.5 beat the Bears 27-21 (by 6). They needed 7, so the Bears are credited and everyone who picked the Bears gets the win.",
             exceptions="A win by exactly a whole-number line goes to the favourite - the commissioner graded it that way (graded 2025 week 15 sheet: 49ers by 13, won 37-24, credited to San Francisco).",
             links=["picks", "weeks"], source="acql/analytics.py line_need; acql/feeds/results.py credited",
             status=ON_RECORD),
        dict(id="unlined-ties", category="scoring", title="Unlined games that end level",
             rule="A game with no line that ends in a tie is credited to nobody: every pick on it is wrong. It still counts as played, so the week can finish.",
             applies="Only games without a line that finish level.",
             how="The game's credited side is recorded as \"Tie\"; no card earns a win from it.",
             example="Hypothetical: an unlined Jets-Colts game ends 20-20. Nobody gets a win for it; the most anyone can score that week is one fewer.",
             exceptions="A lined game can't end this way - one side always covers or doesn't.",
             links=["weeks"], source="acql/feeds/results.py TIE, credited", status=VERIFIED),
        dict(id="weekly-total", category="scoring", title="A week's total = regular wins + Big Loser points",
             rule=f"A card's score for the week is its regular wins plus its Big Loser points (up to {picks}).",
             applies="Every week.",
             how=f"Total = regular wins + Big Loser points. The most a card can score is the number of games plus the {picks} Big Loser points the sheet allows.",
             example="Hypothetical: 11 regular wins and 2 Big Loser points make a week of 13.",
             exceptions="None on record.",
             links=["weeks", "pools"], source="acql/pool/standings.py (W column); poolpage._week (most)", status=VERIFIED),
        # ---- weekly ----
        dict(id="weekly-winner", category="weekly", title="Winning a week",
             rule="The week is won by the highest total. Coaches level on the top score share the win.",
             applies="Every finished week.",
             how="Winners = every coach whose total equals the week's top score. There is no tie-breaker for a week.",
             example="Hypothetical: Ava and Ben both score 14, everyone else less. Both win the week and split its pot evenly.",
             exceptions="None on record.",
             links=["weeks", "money"], source="acql/pool/standings.py (+PTS); acql/ui/recap.py winners", status=VERIFIED),
        dict(id="weekly-pot", category="weekly", title="The weekly pot",
             rule="Every coach pays in what they fell short of the week's top score; the pot is split between the coaches on the top score.",
             applies="Every finished week, in the official export's points columns (-PTS, +PTS, NET).",
             how="Pot = the sum of (top score - your score) over every coach. Each winner's share = pot / number of winners. Your -PTS adds (your score - top score) each week; +PTS adds your pot shares.",
             example="Hypothetical: three coaches score 14, 12 and 10. The top is 14, so the pot is 0 + 2 + 4 = 6 points, all to the 14.",
             exceptions="Weeks whose money the files don't give are marked on the site rather than worked out.",
             links=["money"], source="acql/pool/standings.py (-PTS, +PTS, pot)", status=VERIFIED),
        dict(id="week-places", category="weekly", title="Places within a week",
             rule="Within one week, coaches on the same total share the same place (1, 2, 2, 4).",
             applies="Week-by-week places the website shows (past weeks, the weekly tables).",
             how="Place = 1 + the number of coaches with a higher total that week.",
             example="Hypothetical: totals 14, 12, 12, 10 give places 1, 2, 2, 4.",
             exceptions="This is how the site lists a week; the season table breaks ties (see Tie-breaking).",
             links=["weeks"], source="acql/ui/recap.py _places; the site's rankAll", status=VERIFIED),
        # ---- season ----
        dict(id="season-wins", category="season", title="Season standings: most wins",
             rule="The season table ranks coaches by total wins - regular wins plus Big Loser points, all season.",
             applies="The official season standings.",
             how="W = every week's total added up. L = the most anyone could have won, minus W. PCT = W over that most. GB = the leader's W minus yours.",
             example="Hypothetical: after three weeks Ava has 13 + 11 + 12 = 36 wins and leads; Ben has 34, so he is 2 games back.",
             exceptions="Missing a week scores nothing for that week; it is not excused.",
             links=["standings"], source="acql/pool/standings.py (W, L, PCT, GB); stats.xls is authoritative",
             status=VERIFIED),
        dict(id="official-source", category="season", title="Which numbers are official",
             rule="The commissioner's stats.xls export is the official record for standings, weekly scores, the Big Loser pool and the Suicide pool. Where another file disagrees, stats.xls is kept and the disagreement is flagged.",
             applies="Every week stats.xls covers. Weeks after the newest export are worked out the same way and shown as provisional until it arrives.",
             how="The site and dashboard read the newest stats.xls first and only roll forward over weeks it doesn't cover yet.",
             example="Hypothetical: the dashboard workbook says Ben scored 12 in week 4 but stats.xls says 11. The standings use 11 and the dashboard lists the conflict.",
             exceptions="Weeks the commissioner has ruled on (official totals stand / the recount stands) follow the ruling.",
             links=["standings"], source="acql/repository.py merge policy; acql/pool/rulings.py", status=VERIFIED),
        # ---- ties ----
        dict(id="season-tie", category="ties", title="Season tie-breaker: higher the week before",
             rule="Coaches level on season wins are ordered by who was higher in the standings the week before.",
             applies="The official season table, whenever two or more coaches have the same W.",
             how="1) Most season wins. 2) If level, whoever held the higher place in the previous week's standings ranks higher.",
             example="Hypothetical: after week 5 Ava and Ben both have 60 wins. After week 4 Ben was 3rd and Ava 6th, so Ben is placed above Ava.",
             exceptions="No further tie-breaker is on record (for coaches also level the week before, the export's order is taken as given). The website's past-week tables and modes share places instead of breaking ties; only the latest week uses the official order.",
             links=["standings"], source="acql/pool/standings.py (Pos); poolpage.snapshot (official places)", status=VERIFIED),
        dict(id="weekly-tie", category="ties", title="Weekly ties are shared",
             rule="There is no tie-breaker for a week: coaches level on the top score all win it and split the pot.",
             applies="Every week.",
             how="See The weekly pot - the pot is divided evenly between the tied winners.",
             example="Hypothetical: a 3-way tie on 13 with a 9-point pot gives each winner 3 points.",
             exceptions="None on record.",
             links=["weeks", "money"], source="acql/pool/standings.py (+PTS)", status=VERIFIED),
        # ---- suicide ----
        dict(id="suicide-survive", category="suicide", title="Surviving a week",
             rule="Each coach still alive picks one team a week. You survive only if that team is credited with its game. No pick means you're out.",
             applies="Every week of a running round, to every coach still alive.",
             how="The pick is checked against the side credited with the game - the same crediting as the main pool, so on a lined game the team has to cover.",
             example="Hypothetical: Ava takes the Chiefs, favoured by 7. They win by 3, so the underdog is credited and Ava is out.",
             exceptions="None on record.",
             links=["pools"], source="acql/pool/standings.py replay_suicide; stats.xls is authoritative", status=VERIFIED),
        dict(id="suicide-win", category="suicide", title="Winning a round, and starting again",
             rule="The last coach left wins the round. If everyone still alive goes out in the same week, they share it. A new round starts the next week with everyone back in.",
             applies="Whenever one coach (or none) is left alive.",
             how="After each week: survivors ≤ 1 → round over; winners = the survivor, or everyone who was alive that week; next week everyone is alive again.",
             example="Hypothetical: three coaches are alive in week 9 and all three lose. They share the round and week 10 starts a new one with the whole pool.",
             exceptions="None on record.",
             links=["pools"], source="acql/pool/standings.py replay_suicide; acql/repository.py _restart_suicide_pool", status=VERIFIED),
        dict(id="suicide-reuse", category="suicide", title="Using a team twice",
             rule="Not verified: whether a coach may pick the same team twice in one round isn't written in the project's files. The site lists each coach's used teams but doesn't enforce anything.",
             applies="-", how="-", example="-", exceptions="Ask the commissioner.",
             links=["pools"], source="not found in the project", status=UNVERIFIED),
        dict(id="suicide-prize", category="suicide", title="Suicide pool prize",
             rule="Not verified: the prize is paid by hand as part of the export's Pie Splits; the amount isn't written down anywhere in the project.",
             applies="-", how="-", example="-", exceptions="-", links=["money"],
             source="stats.xls Pie Splits column (amounts only)", status=UNVERIFIED),
        # ---- big loser ----
        dict(id="bigloser-picks", category="bigloser", title=f"Big Loser: pick {picks} teams to lose by {blow}+",
             rule=f"Each week a coach may name {picks} teams. Each one that loses its game by {blow} points or more earns a point.",
             applies="Every week.",
             how=f"Uses the real final score, not the line: a team that loses by {blow} or more scores. The points count in the week's total and in the season's Big Loser column.",
             example=f"Hypothetical: Ben takes the Jets, Titans and Panthers. The Jets lose by {blow + 3} and the Titans by {blow - 1}; the Panthers win. Ben gets 1 Big Loser point.",
             exceptions=f"A loss by exactly {blow} counts.",
             links=["pools"], source="acql/feeds/results.py BLOWOUT; acql/config.py BIG_LOSER_PICKS", status=VERIFIED),
        dict(id="bigloser-prize", category="bigloser", title="Big Loser prize",
             rule="Not verified: the Big Loser pool's prize is paid by hand in the export's Pie Splits; how it is decided and split isn't written down in the project.",
             applies="-", how="-", example="-", exceptions="-", links=["pools", "money"],
             source="stats.xls Pie Splits column (amounts only)", status=UNVERIFIED),
        # ---- other side pools ----
        dict(id="pie-splits", category="side", title="Side-pool money (Pie Splits)",
             rule="Side-pool money - suicide, Big Loser and top-10 payouts - is entered by hand by the commissioner as Pie Splits and added to each coach's +PTS.",
             applies="Whenever the commissioner pays a side pool.",
             how="+PTS = weekly pot shares + Pie Splits. NET = -PTS + +PTS.",
             example="Hypothetical: a coach with 40 points of pot shares and a 25-point Pie Split shows +PTS of 65.",
             exceptions="The top-10 pool's own rules (who qualifies, when it pays) are not written down in the project - unverified.",
             links=["money"], source="acql/pool/standings.py (+PTS); acql/models.py pie_splits", status=VERIFIED),
        dict(id="buy-in", category="side", title="Buy-in",
             rule=f"The season buy-in is {fee_text}, taken off each coach's points at the start (-PTS begins at minus the buy-in).",
             applies="The whole season.",
             how="-PTS = -buy-in + each week's (your score - top score).",
             example=f"Hypothetical: a coach who wins every week never adds to -PTS, so it stays at -{fee_text[1:]}.",
             exceptions="None on record.",
             links=["money"], source="acql/pool/standings.py (-PTS); the dashboard's buy-in setting", status=VERIFIED),
        # ---- deadlines ----
        dict(id="deadline", category="deadlines", title="When picks are due",
             rule="Picks are due by the time the commissioner posts on the league's main page (Eastern time). Picks go in through the commissioner's form.",
             applies="Every week.",
             how=f"The site's countdown uses the posted time, or the week's first kickoff if that is sooner. If nothing is posted, the dashboard assumes {_deadline_words()} - that default is the dashboard's setting, not a written league rule.",
             example="Hypothetical: the commissioner posts \"due Thursday 7:30\" and Thursday's game kicks off at 8:15. The countdown ends at 7:30.",
             exceptions="Unverified: what happens to a late or missing card beyond scoring nothing is not written in the project.",
             links=["home"], source="acql/site/mainsite.py due; acql/feeds/oddslock.py deadline, lock_time", status=ON_RECORD),
        dict(id="picks-private", category="deadlines", title="When suicide picks are shown",
             rule="The website shows a coach's suicide picks only for weeks whose games are over.",
             applies="Every week of a running round.",
             how="A suicide pick for a week still to be played is left out of the site's data.",
             example="Hypothetical: on Saturday nobody can see Ava's suicide pick for that weekend; on Tuesday everyone can.",
             exceptions="This is how the website behaves, not a written league rule.",
             links=["pools"], source="acql/ui/poolpage.py snapshot (suicide picks: played weeks only)", status=ON_RECORD),
        # ---- history ----
        dict(id="rule-versions", category="history", title="Earlier seasons' rules",
             rule="Only the current season's rules are on file. The project has no earlier rulebook and no past seasons' records, so these rules are not applied to earlier seasons and earlier seasons show none.",
             applies="Seasons before the current one.",
             how="-",
             example="-",
             exceptions="Commissioner rulings on individual weeks are kept (acql/pool/rulings.py) and listed on the dashboard's Data page.",
             links=["history"], source="acql/site/siteextras.py page_history (no past seasons stored)", status=UNVERIFIED),
    ]
    order = {c: i for i, (c, _) in enumerate(CATEGORIES)}
    out.sort(key=lambda r: order[r["category"]])
    return out


def rulebook(season_label: str, buy_in: float | None = None) -> dict:
    """What the page needs: the categories, the rules, and which season they
    are documented for."""
    found = rules(buy_in)
    for r in found:
        r["seasons"] = [season_label]
    return {
        "categories": [{"id": c, "label": label} for c, label in CATEGORIES],
        "rules": found,
        "seasons": [season_label],
        "statuses": {VERIFIED: "Verified against the pool's code and official exports",
                     ON_RECORD: "On record from the commissioner and applied by the code",
                     UNVERIFIED: "Could not be verified from the project's files"},
    }
