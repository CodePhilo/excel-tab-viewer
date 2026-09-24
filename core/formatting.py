"""
core/formatting.py

One place that decides how a cell value reads as text — used for what the
table shows AND for what text search/filters match against, so searching
always matches what's on screen. Plain str() made blank cells read "nan"
(a quick search for "na" matched every row with an empty number cell),
whole numbers in a column with blanks read "12.0", and date-only values
read "2026-01-05 00:00:00".
"""

from __future__ import annotations

import datetime

import numpy as np
import pandas as pd

# Excel itself displays at most 15 significant digits.
_FLOAT_FORMAT = "{:.15g}"


def display_text(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass  # not a scalar pd.isna understands; fall through to str()
    if isinstance(value, (bool, np.bool_)):
        return "TRUE" if value else "FALSE"  # as Excel shows them
    if isinstance(value, (float, np.floating)):
        if float(value).is_integer() and abs(value) < 1e15:
            return str(int(value))
        return _FLOAT_FORMAT.format(value)
    if isinstance(value, datetime.datetime):  # includes pd.Timestamp
        if (value.hour, value.minute, value.second, value.microsecond) == (0, 0, 0, 0):
            return value.strftime("%Y-%m-%d")
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def to_text_series(series: pd.Series) -> pd.Series:
    return series.map(display_text)


def to_text_frame(df: pd.DataFrame) -> pd.DataFrame:
    """The whole sheet as display text (blank cells as ""), for text search."""
    return df.apply(to_text_series)
