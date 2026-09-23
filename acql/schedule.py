"""The season's schedule: who plays whom, and where, in every week.

One row a team, one column a week, as the league publishes it: an opponent's
code for a home game, "@" in front of it for a road game, BYE for a week off.
It is checked on import - every pairing has to be mutual and the two sides
have to disagree about who is at home - so a typo cannot quietly invent a
game that nobody else is playing in.

This is here so a week can be looked at before anyone has typed it into the
workbook and before the week's predictions file exists. It carries no
opinions, only fixtures.
"""

from __future__ import annotations

from .config import WEEKS_IN_SEASON
from .models import Game

BYE = "BYE"

#: Team code, then one entry a week. Paste a new season's table in here.
TABLE = """
    ARI @LAC SEA @SF @NYG DET @LAR DEN @DAL @SEA LAR @KC WSH PHI BYE NYJ @NO LV SF
    ATL @PIT CAR @GB @NO BAL CHI SF @TB CIN KC BYE @MIN DET @CLE @WSH TB NO @CAR
    BAL @IND NO @DAL TEN @ATL @CLE CIN @BUF JAX LAC @CAR @HOU BYE TB @PIT CLE @CIN PIT
    BUF @HOU DET LAC NE @LAR @LV BYE BAL @MIN @NYJ MIA KC @NE @GB CHI @DEN @MIA NYJ
    CAR CHI @ATL @CLE DET BYE @PHI TB @GB DEN @NO BAL @TB @MIN NO CIN @PIT SEA ATL
    CHI @CAR MIN PHI NYJ @GB @ATL NE @SEA TB BYE NO @DET JAX @MIA @BUF GB DET @MIN
    CIN TB @HOU @PIT JAX @MIA BYE @BAL TEN @ATL PIT @WSH NO @CLE KC @CAR @IND BAL CLE
    CLE @JAX @TB CAR PIT @NYJ BAL @TEN @PIT @NO HOU BYE LV CIN ATL @NYG @BAL IND @CIN
    DAL @NYG WSH BAL @HOU TB @GB @PHI ARI @IND SF TEN PHI @SEA BYE @LAR JAX NYG @WSH
    DEN @KC JAX LAR @SF @LAC SEA @ARI KC @CAR BYE LV @PIT MIA @NYJ @LV BUF @NE LAC
    DET NO @BUF NYJ @CAR @ARI BYE GB MIN @MIA NE TB CHI @ATL TEN @MIN NYG @CHI @GB
    GB @MIN @NYJ ATL @TB CHI DAL @DET CAR @NE MIN BYE @LAR @NO BUF MIA @CHI HOU DET
    HOU BUF CIN @IND DAL @TEN @JAX NYG BYE @LAC @CLE IND BAL @PIT @WSH JAX @PHI @GB TEN
    IND BAL @KC HOU @WSH @PIT TEN @MIN @JAX DAL MIA @HOU NYG BYE @PHI @TEN CIN @CLE JAX
    JAX CLE @DEN NE @CIN PHI HOU BYE IND @BAL @TEN @NYG TEN @CHI PIT @HOU @DAL WSH @IND
    KC DEN IND @MIA @LV BYE LAC @SEA @DEN NYJ @ATL ARI @BUF @LAR @CIN NE SF @LAC LV
    LV MIA @LAC @NO KC @NE BUF LAR @NYJ @SF SEA @DEN @CLE BYE LAC DEN TEN @ARI @KC
    LAR SF NYG @DEN @PHI BUF ARI @LV LAC @WSH @ARI BYE GB KC @SF DAL @SEA @TB SEA
    LAC ARI LV @BUF @SEA DEN @KC BYE @LAR HOU @BAL NYJ NE @TB @LV SF @MIA KC @DEN
    MIA @LV @SF KC @MIN CIN BYE @NYJ NE DET @IND @BUF NYJ @DEN CHI @GB LAC BUF @NE
    MIN GB @CHI @TB MIA @NO BYE IND @DET BUF @GB @SF ATL CAR @NE DET WSH @NYJ CHI
    NE @SEA PIT @JAX @BUF LV NYJ @CHI @MIA GB @DET BYE @LAC BUF MIN @KC @NYJ DEN MIA
    NO @DET @BAL LV ATL MIN @NYG PIT BYE CLE CAR @CHI @CIN GB @CAR @TB ARI @ATL TB
    NYG DAL @LAR TEN ARI @WSH NO @HOU BYE @PHI WSH JAX @IND SF @SEA CLE @DET @DAL PHI
    NYJ @TEN GB @DET @CHI CLE @NE MIA LV @KC BUF @LAC @MIA BYE DEN @ARI NE MIN @BUF
    PHI WSH @TEN @CHI LAR @JAX CAR DAL @WSH NYG BYE PIT @DAL @ARI IND SEA HOU @SF @NYG
    PIT ATL @NE CIN @CLE IND @TB @NO CLE BYE @CIN @PHI DEN HOU @JAX BAL CAR @TEN @BAL
    SF @LAR MIA ARI DEN @SEA WSH @ATL BYE LV @DAL MIN SEA @NYG LAR @LAC @KC PHI @ARI
    SEA NE @ARI @WSH LAC SF @DEN KC CHI ARI @LV BYE @SF DAL NYG @PHI LAR @CAR @LAR
    TB @CIN CLE MIN GB @DAL PIT @CAR ATL @CHI BYE @DET CAR LAC @BAL NO @ATL LAR @NO
    TEN NYJ PHI @NYG @BAL HOU @IND CLE @CIN BYE JAX @DAL @JAX WSH @DET IND @LV PIT @HOU
    WSH @PHI @DAL SEA IND NYG @SF BYE PHI LAR @NYG CIN @ARI @TEN HOU ATL @MIN @JAX DAL
"""


def _read(table: str = TABLE) -> dict[str, list[str]]:
    rows = {}
    for line in table.strip().splitlines():
        parts = line.split()
        if len(parts) > 1:
            rows[parts[0].upper()] = [p.upper() for p in parts[1:]]
    return rows


SEASON: dict[str, list[str]] = _read()
WEEKS = min(WEEKS_IN_SEASON, min((len(v) for v in SEASON.values()), default=0))


def _check() -> list[str]:
    """Every fixture, from both sides, has to say the same thing."""
    complaints = []
    for team, weeks in SEASON.items():
        for index, entry in enumerate(weeks[:WEEKS]):
            if entry == BYE:
                continue
            away = entry.startswith("@")
            other = entry.lstrip("@")
            back = SEASON.get(other, [])
            if len(back) <= index:
                complaints.append(f"week {index + 1}: {team} plays {other}, who isn't listed")
                continue
            if back[index].lstrip("@") != team or back[index].startswith("@") == away:
                complaints.append(
                    f"week {index + 1}: {team} has {entry} but {other} has {back[index]}"
                )
    return complaints


PROBLEMS = _check()


def teams() -> list[str]:
    return sorted(SEASON)


def fixture(team: str, week: int) -> tuple[str, bool] | None:
    """(opponent code, at home) for one team in one week; None on a bye."""
    weeks = SEASON.get(team.upper(), [])
    if not 1 <= week <= len(weeks):
        return None
    entry = weeks[week - 1]
    if entry == BYE:
        return None
    return entry.lstrip("@"), not entry.startswith("@")


def byes(week: int) -> list[str]:
    """The teams with the week off."""
    return sorted(
        team for team, weeks in SEASON.items()
        if 1 <= week <= len(weeks) and weeks[week - 1] == BYE
    )


def pairings(week: int) -> list[tuple[str, str]]:
    """(away code, home code) for every game in a week, home team in order."""
    found = []
    for team, weeks in SEASON.items():
        if not 1 <= week <= len(weeks):
            continue
        entry = weeks[week - 1]
        if entry != BYE and not entry.startswith("@"):
            found.append((entry, team))          # this team is at home
    return sorted(found, key=lambda pair: (pair[1], pair[0]))


def slate(week: int) -> list[Game]:
    """The week's games, named the way the workbook names them.

    The order is alphabetical by home team - the sheet's own order isn't
    knowable from a schedule - so these are only used when neither the
    workbook nor a predictions file has the week.
    """
    from .predictions import DISPLAY

    def name(code: str) -> str:
        return DISPLAY.get(code.lower(), code)

    return [
        Game(index, name(home), name(away))
        for index, (away, home) in enumerate(pairings(week), start=1)
    ]
