"""Deadeye's training ground: challengers taught and tested away from the card.

Deadeye is the betting line, nudged toward the published computer models
(pricing.py). Whether that nudge - or any cleverer one - is worth anything
can only be settled on games the recipe had not seen, and one season's
seventy-odd games cannot settle it. This package is where it is settled:

    data          one row a game, every number from before the game, with
                  where it came from and when it was taken
    features      what a recipe may look at, and how much of it there is
    recipes       the line alone, Deadeye as it runs, a ridge regression on
                  what the line got wrong, weighted crowds, fixed nudges
    probability   the margin-to-chance curve, against ones fitted to results
    walkforward   every week priced by recipes taught on the weeks before it
    evaluate      the same games for everyone, scored the same way
    report        what came of it, and whether anything has earned a place
    registry      a taught challenger, kept apart from the live model
    snapshots     each week's numbers as they stood at the pool's deadline

Nothing in the dashboard imports this package, so nothing here can change a
pick: it reads the app's records (from a copy of the database), measures, and
writes under data/training. Run it with `python -m acql.training`.

No Qt here.
"""

#: Marks every saved run and model, so a record can be told from one made by
#: different rules.
VERSION = "1.0"
