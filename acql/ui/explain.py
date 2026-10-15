"""What the ⓘ icons say: the words behind Deadeye's numbers, in one place.

The figures quoted come from the model's own constants, so an explanation
can't drift from what the app actually does.
"""

from __future__ import annotations

from ..feeds import odds
from ..model import evidence
from ..pool import bigloser, briefing
from ..version import MODEL_NAME


def _pct(x: float) -> str:
    return f"{x:.0%}"


def _bands() -> str:
    floors = [f for f, _ in evidence.STRENGTHS]
    names = [n for _, n in evidence.STRENGTHS]
    parts = [f"{names[0]} {_pct(floors[0])}+"]
    for i in range(1, len(floors) - 1):
        parts.append(f"{names[i]} {_pct(floors[i])}–{_pct(floors[i - 1])}")
    parts.append(f"{names[-1]} under {_pct(floors[-2])}")
    return ", ".join(parts)


PROBABILITIES = (
    f"Each percentage is {MODEL_NAME}'s chance that the pick is credited - out of 100 games "
    "like this one, how many it expects the pick to win. It starts from the betting line "
    "and is nudged by the signals listed under each pick. "
    f"Bands: {_bands()}. On a line game the chance is of covering the pool's line, not "
    "just of winning."
)

MARKET_MOVEMENT = (
    "The spread the books opened with against where it stands now. A move toward a team "
    "means money and news (injuries, weather) have come in on that side. Only moves of "
    f"{odds.BIG_MOVE:g} points or more are listed; {MODEL_NAME} reprices its chances on "
    "the latest line every time the lines are updated. Once cards are due the lines lock."
)

HARD_TO_CALL = (
    f"A coin flip is a pick {MODEL_NAME} gives under {_pct(evidence.STRENGTHS[-2][0])} - "
    "close to a 50/50 game. These are where the week is won or lost, so they are worth a "
    "look at the signals, and the place to go against the pool if you need to catch up. "
    "A pick turned on purpose to differ from the pool isn't counted as a coin flip."
)

BIG_LOSERS = (
    f"Each card names three Big Losers: teams you think will lose by {bigloser.MARGIN} or "
    "more. Each one that does scores a point on top of your pick'em wins. "
    f"The percentage is the chance of a {bigloser.MARGIN}+ point loss: how often teams with "
    "that line have lost so badly in every season since 1999. A point the whole pool "
    "also holds moves nobody, so a team few cards have can be worth more than a likelier one."
)

EXPECTED_WINS = (
    "The number of picks the card should get right on average: the sum of the chances "
    "of every pick. Not a forecast of an exact score - a typical week lands a game or two "
    "either side."
)

WIN_THE_WEEK = (
    "The chance this card has the best score in the pool, from thousands of simulated "
    "weeks against how the pool's coaches tend to pick. Going against the pool on close "
    "games can lower expected wins but raise this."
)

CONFIDENT_NOTE = (
    f"Picks at {_pct(briefing.CONFIDENT)} or more are shown in green as confident."
)

MODEL_RECORD = (
    f"Got right: how many of {MODEL_NAME}'s picks came in each week. Said it would: the sum "
    "of the chances it gave them beforehand. Lines that track each other mean its "
    "percentages are trustworthy; a got-right line running below says they are too high."
)

FOLLOWING = (
    f"{MODEL_NAME}'s card is saved before the first kickoff and scored afterwards, beside "
    "the card you played. Place is where its card would have finished among everyone "
    "in the pool that week."
)

CALIBRATION = (
    "Calibration: picks sorted into bands by the chance given, then how often each band "
    "really came in. A model whose 70% picks win about 70% of the time is honest. Bars "
    "above the line mean it was too cautious, below it too sure. Small bands are noisy."
)

BACKTEST = (
    "The same rules replayed over every season from 2010 to 2025, each week using only "
    "what was known before kickoff and paid by this pool's rule (a dollar a game to the "
    "week's best card). Points are games right plus Big Loser points per week; 'give or "
    "take' is the uncertainty - a gain smaller than twice it isn't proven."
)
