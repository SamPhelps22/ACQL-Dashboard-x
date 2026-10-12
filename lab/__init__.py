"""Deadeye's Model Lab: experiments kept apart from the production app.

Nothing in `acql/` imports this package, and nothing here writes anything
the app reads. Code here may import `acql` modules, read-only, to reuse the
app's own conventions (team codes, file parsers, the Eastern-time rule).
"""
