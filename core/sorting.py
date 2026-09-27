"""
core/sorting.py

Row ordering for the table's column sort. Text columns loaded from Excel
often mix types (numbers, text, dates in one column), which pandas can't
sort directly, so every column is first turned into a plain numeric rank
following Excel's own order: numbers, then dates, then text (A-Z, ignoring
case), then TRUE/FALSE — with blank cells always last, in either direction.
"""

from __future__ import annotations

import datetime

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_datetime64_any_dtype, is_numeric_dtype

from core.formatting import display_text


def _mixed_key(value):
    """A comparable key for one cell of a mixed-type column, or None if blank."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (bool, np.bool_)):
        return (3, int(value), "")
    if isinstance(value, (int, float, np.integer, np.floating)):
        return (0, float(value), "")
    if isinstance(value, (datetime.date, datetime.datetime, datetime.time)):
        return (1, 0.0, display_text(value))  # ISO-style text sorts chronologically
    return (2, 0.0, display_text(value).casefold())


def _rank(series: pd.Series) -> pd.Series:
    """The column as floats that sort in Excel's order (NaN for blanks)."""
    if is_datetime64_any_dtype(series):
        return series.astype("int64").where(series.notna()).astype(float)
    if is_numeric_dtype(series) and not is_bool_dtype(series):
        return series.astype(float)
    keys = [_mixed_key(v) for v in series]
    ranks = {k: i for i, k in enumerate(sorted({k for k in keys if k is not None}))}
    return pd.Series([np.nan if k is None else ranks[k] for k in keys], index=series.index, dtype=float)


def sort_order(df: pd.DataFrame, keys: list[tuple[str, bool]]) -> np.ndarray:
    """Row positions of `df` sorted by `keys` — (column, ascending) pairs, the
    first one deciding and each next one breaking ties. Equal rows keep their
    original order. Columns missing from `df` are ignored."""
    keys = [(col, asc) for col, asc in keys if col in df.columns]
    if not keys or df.empty:
        return np.arange(len(df))
    ranks = pd.DataFrame(
        {i: _rank(df[col]).to_numpy() for i, (col, _asc) in enumerate(keys)}
    )
    ordered = ranks.sort_values(
        by=list(range(len(keys))),
        ascending=[asc for _col, asc in keys],
        kind="mergesort",
        na_position="last",
    )
    return ordered.index.to_numpy()
