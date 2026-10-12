"""What the dashboard and its places are called - each name once, here.

The dashboard is Operation Sunday, with Deadeye (version.MODEL_NAME) as the
prediction engine inside it. The name and the look are the brand; the places
themselves are called what they are - Season, This Week, Game Day - so
nobody has to learn where anything lives. The pool's website is not part of
it and keeps the league's own name.

These are only what is *shown*. The app keeps its settings under its
original name (acql.APP_NAME), so nothing saved is lost by the names here
changing.
"""

from __future__ import annotations

from .version import MODEL_NAME

BRAND = "Operation Sunday"
TAGLINE = "Good analysis. Better Sundays."

# ---- the sidebar's places, and the tabs inside them -------------------------------
SEASON = "Season"                   # overview, standings, money, odds, charts
OVERVIEW = "Overview"
THIS_WEEK = "This Week"             # the week's card, and why
CARD = "Your card"
EVERY_GAME = "Every game"           # every game on the slate, priced
RADAR = "Radar"                     # every game by how it could go
GAME_DAY = "Game Day"               # the games as they happen
EVERYONE = "Everyone's picks"       # the whole pool's cards for the week, side by side
RESULTS = "Results"                 # how the week went
SIDE_POOLS = "Side Pools"           # Big Loser and the suicide pool
PLAYER = "Player"                   # one coach's season
INSIGHTS = "Insights"               # the pool's habits, and every team
POOL = "The pool"
TEAMS = "Teams"
MODEL = MODEL_NAME                  # the model: how good it is, and what is inside
REPORT_CARD = "Report card"
DETAILS = "Details"
LAB = "Model Lab"
HITS = "Hits & misses"              # where its picks come good, and what each miss was
MODEL_CHARTS = "Charts"             # its season in pictures
RECIPE = "Recipe"                   # what each ingredient does, and what a different share would change
COMPUTERS = "Computer models"   # each published model on its own, and what the crowd is worth
DATA = "Data & Update"              # what is loaded, and updating the app
READINESS = "Readiness"             # is everything the picks are made from up to date

#: The mission names the places wore for a while (2.16, before it shipped),
#: so a place the window remembered under one still opens.
FORMERLY = {
    "Command Center": SEASON, "Mission Briefing": THIS_WEEK, "Live Ops": GAME_DAY,
    "After-Action Report": RESULTS, "Side Missions": SIDE_POOLS, "Personnel File": PLAYER,
    "Intelligence": INSIGHTS, "Black Box": MODEL, "Logistics": DATA,
}
