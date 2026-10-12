"""The historical dataset for Deadeye's walk-forward backtest.

    python -m lab.history.build            fetch inputs, build, verify, report

One prediction record per game per cutoff, built only from what was available
at that cutoff. Odds snapshots and individual model forecasts are kept in
their own tables with the times they became available, and the actual results
in a table no record is ever built from. See lab/reports/data-audit.md for
what each source can and cannot vouch for.
"""
