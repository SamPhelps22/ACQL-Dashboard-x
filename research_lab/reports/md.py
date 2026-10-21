"""Markdown tables without extra dependencies."""

from __future__ import annotations

import math

import pandas as pd


def _fmt(v, digits):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    return str(v).replace("|", "/")


def table(df: pd.DataFrame, digits: int = 4) -> str:
    cols = list(df.columns)
    out = ["| " + " | ".join(map(str, cols)) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for row in df.itertuples(index=False):
        out.append("| " + " | ".join(_fmt(v, digits) for v in row) + " |")
    return "\n".join(out)
