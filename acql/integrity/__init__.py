"""The Integrity Engine: checks that the pool's numbers add up, everywhere they are shown.

    engine.py    the checks, run over the one Season repository.load_season builds
    history.py   every run, every issue, every decision, kept in the app's database
    center.py    the Integrity Center, a localhost-only page (python -m acql.integrity center)

Read-only by design: nothing here edits stats.xls, the workbook, a pick sheet,
a locked pick, a result or a money figure. A failed check is reported with the
original values and where they came from; changing an official number stays
with the commissioner (a ruling, or a corrected source file).
"""
