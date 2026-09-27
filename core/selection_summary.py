"""
core/selection_summary.py

The Count / Sum / Average / Min / Max line for selected cells, as Excel
shows in its status bar. Like Excel, only real numbers are totalled: text
that looks like a number ("0044") and TRUE/FALSE are counted but not summed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_numeric_dtype


def _numbers(block: pd.DataFrame) -> np.ndarray:
    parts = []
    for col in block.columns:
        series = block[col]
        if is_bool_dtype(series):
            continue
        if is_numeric_dtype(series):
            parts.append(series.dropna().to_numpy(dtype=float))
        elif series.dtype == object:
            values = [
                v for v in series
                if isinstance(v, (int, float, np.integer, np.floating))
                and not isinstance(v, (bool, np.bool_))
                and not pd.isna(v)
            ]
            if values:
                parts.append(np.asarray(values, dtype=float))
    return np.concatenate(parts) if parts else np.empty(0)


def _fmt(value: float) -> str:
    value = round(float(value), 4)
    if value.is_integer() and abs(value) < 1e15:
        return f"{int(value):,}"
    return f"{value:,.4f}".rstrip("0").rstrip(".")


def summarize(blocks: list[pd.DataFrame]) -> str:
    """Summary text for the selected cell blocks, or "" for fewer than two
    cells (Excel shows nothing for a single cell either)."""
    cells = sum(b.size for b in blocks)
    if cells < 2:
        return ""
    count = int(sum(b.notna().to_numpy().sum() for b in blocks))
    numbers = np.concatenate([_numbers(b) for b in blocks]) if blocks else np.empty(0)
    parts = [f"Count: {count:,}"]
    if len(numbers):
        parts += [
            f"Sum: {_fmt(numbers.sum())}",
            f"Average: {_fmt(numbers.mean())}",
            f"Min: {_fmt(numbers.min())}",
            f"Max: {_fmt(numbers.max())}",
        ]
    return "    ".join(parts)
