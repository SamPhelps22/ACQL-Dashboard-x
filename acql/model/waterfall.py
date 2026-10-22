"""One game's arithmetic, step by step (idea #23).

pricing.price() turns the market's number into Deadeye's expected margin in
a few moves. This retraces them for one game - without changing any of
them - so the scouting report can show where every point came from:

    the market's line                     the home side's margin
    + the moneyline's say                 straight-up games only
    + the models' opinion                 their share of the raw disagreement
    - the slate's home lean               not about this game
    - what the market has moved since     news the models never had
    = Deadeye's expected margin           exactly what pricing gives

Margins are for the home side, in points. The steps always add up to the
priced margin; a test holds that.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import pricing, predictions


@dataclass(frozen=True)
class Step:
    label: str
    points: float          # this step's move (or the value itself for start/end)
    kind: str              # "start", "move" or "end"
    note: str = ""


def steps(game, ctx: pricing.Context, price: pricing.Price) -> list[Step]:
    """The moves from the market's number to the priced margin. [] when unpriced."""
    if price.margin is None or price.base is None:
        return []
    forecast = ctx.forecasts.get(game.index)
    out = [Step("Market line", price.base, "start",
                "typed in by hand" if price.typed else "the latest number kept")]
    anchor = price.base if price.typed else pricing._anchor(game, forecast, price.base)
    if abs(anchor - price.base) > 1e-9:
        out.append(Step("Moneyline", anchor - price.base, "move", "a straight-up game follows the moneyline"))
    if price.edge is not None and forecast is not None:
        share = forecast.model_weight(ctx.weight, ctx.typical)
        raw = predictions.home_margin(game, forecast, forecast.edge) or 0.0
        leaned = predictions.home_margin(game, forecast, forecast.edge - ctx.lean) or 0.0
        live = price.edge
        out.append(Step("Computer models", share * raw, "move",
                        f"{share:.0%} of their {raw:+.1f}-point disagreement"))
        if abs(leaned - raw) > 1e-9:
            out.append(Step("Home lean removed", share * (leaned - raw), "move",
                            f"the slate's shared {ctx.lean:+.1f} points"))
        if abs(live - leaned) > 1e-9:
            out.append(Step("Line has moved since", share * (live - leaned), "move",
                            "disagreement the market has already acted on"))
    out.append(Step("Expected margin", price.margin, "end",
                    f"results scatter {price.sd:.1f} points either way"))
    return out


def total(found: list[Step]) -> float:
    """What the steps add up to (equal to the last step's value)."""
    return sum(s.points for s in found if s.kind != "end")
