"""Parsers for the two spreadsheet formats the pool produces."""

from .discovery import discover, classify
from .stats_xls import parse_stats
from .workbook import parse_workbook

__all__ = ["discover", "classify", "parse_stats", "parse_workbook"]
