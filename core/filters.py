"""
core/filters.py

Filter conditions are small, JSON-serializable objects rather than raw
pandas query strings — this keeps them safe to store in profile JSON
later (Step 6), easy to turn into UI rows, and avoids any risk of
evaluating user-typed text as code (no DataFrame.query(), no eval()).

compile_conditions() turns a list of conditions into a single combined
boolean mask (AND across all conditions) by dispatching each operator
to a small, explicit pandas expression.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, asdict
from typing import Optional

import pandas as pd

# Operators that need no value at all (e.g. "is empty").
NO_VALUE_OPERATORS = {"is_empty", "not_empty"}
# Operators that need exactly one value.
ONE_VALUE_OPERATORS = {"contains", "equals", "not_equals", "gte", "lte"}
# Operators that need two values (a range).
TWO_VALUE_OPERATORS = {"between"}

ALL_OPERATORS = NO_VALUE_OPERATORS | ONE_VALUE_OPERATORS | TWO_VALUE_OPERATORS

OPERATOR_LABELS = {
    "contains": "Contains",
    "equals": "Equals",
    "not_equals": "Not equals",
    "gte": "Greater than or equal to",
    "lte": "Less than or equal to",
    "between": "Between (range)",
    "is_empty": "Is empty",
    "not_empty": "Is not empty",
}


@dataclass
class FilterCondition:
    column: str
    operator: str
    value: Optional[str] = None
    value2: Optional[str] = None  # only used by "between"

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "FilterCondition":
        return FilterCondition(
            column=d["column"],
            operator=d["operator"],
            value=d.get("value"),
            value2=d.get("value2"),
        )


def _is_empty_mask(series: pd.Series) -> pd.Series:
    return series.isna() | (series.astype(str).str.strip() == "")


def _has_wildcards(text: str) -> bool:
    """* and ? are only treated as wildcards if present — plain text with
    neither character keeps behaving exactly as a literal substring match."""
    return "*" in text or "?" in text


def _wildcard_pattern(text: str) -> str:
    """Translate a glob-style pattern (* = any chars, ? = one char) into a
    regex that matches the whole string — the same convention Excel/Access
    use for wildcard criteria. A plain 'contains' search with wildcards
    still needs the user to wrap it in '*...*' themselves, same as Excel."""
    return fnmatch.translate(text)


def _coerce_value(series: pd.Series, raw_value: str):
    """
    Try to coerce a user-typed string to match the column's dtype, so
    comparisons behave numerically/chronologically rather than as text.
    Falls back to the raw string if coercion isn't possible or applicable.
    """
    if raw_value is None:
        return None
    if pd.api.types.is_numeric_dtype(series.dtype):
        try:
            return float(raw_value)
        except (TypeError, ValueError):
            return raw_value
    if pd.api.types.is_datetime64_any_dtype(series.dtype):
        try:
            return pd.to_datetime(raw_value)
        except (TypeError, ValueError):
            return raw_value
    return raw_value


def _compile_one(df: pd.DataFrame, cond: FilterCondition) -> pd.Series:
    if cond.column not in df.columns:
        # Column no longer exists (e.g. after a Refresh where the file changed) —
        # treat as "no match" rather than raising, so a stale filter doesn't crash the app.
        return pd.Series(False, index=df.index)

    series = df[cond.column]

    if cond.operator == "is_empty":
        return _is_empty_mask(series)
    if cond.operator == "not_empty":
        return ~_is_empty_mask(series)

    if cond.operator == "contains":
        text = "" if cond.value is None else str(cond.value)
        if _has_wildcards(text):
            return series.astype(str).str.match(_wildcard_pattern(text), case=False, na=False)
        return series.astype(str).str.contains(text, case=False, na=False, regex=False)

    if cond.operator in ("equals", "not_equals", "gte", "lte"):
        target = _coerce_value(series, cond.value)
        if cond.operator == "equals":
            if isinstance(target, str) and _has_wildcards(target):
                return series.astype(str).str.match(_wildcard_pattern(target), case=False, na=False)
            if isinstance(target, str):
                return series.astype(str).str.lower() == target.lower()
            return series == target
        if cond.operator == "not_equals":
            if isinstance(target, str) and _has_wildcards(target):
                return ~series.astype(str).str.match(_wildcard_pattern(target), case=False, na=False)
            if isinstance(target, str):
                return series.astype(str).str.lower() != target.lower()
            return series != target
        if cond.operator == "gte":
            return series >= target
        if cond.operator == "lte":
            return series <= target

    if cond.operator == "between":
        low = _coerce_value(series, cond.value)
        high = _coerce_value(series, cond.value2)
        mask = pd.Series(True, index=df.index)
        if low is not None and low != "":
            mask &= series >= low
        if high is not None and high != "":
            mask &= series <= high
        return mask

    # Unknown operator — fail safe to "no match" rather than raising.
    return pd.Series(False, index=df.index)


def compile_conditions(df: pd.DataFrame, conditions: list[FilterCondition]) -> pd.Series:
    """Combine all conditions with AND logic into a single boolean mask."""
    mask = pd.Series(True, index=df.index)
    for cond in conditions:
        try:
            mask &= _compile_one(df, cond)
        except Exception:
            # A single malformed condition (e.g. bad numeric text on a numeric
            # column) shouldn't crash the whole filter — treat it as no-match.
            mask &= pd.Series(False, index=df.index)
    return mask


def compile_quick_search(df: pd.DataFrame, column: Optional[str], text: str) -> pd.Series:
    """
    Quick single-box search. If column is None (or 'All Columns'), search every
    column; otherwise restrict to the one selected column. Case-insensitive
    'contains' semantics for plain text; '*'/'?' wildcards switch to a
    whole-string glob match (Excel-style) when present.
    """
    if not text:
        return pd.Series(True, index=df.index)

    has_wild = _has_wildcards(text)
    pattern = _wildcard_pattern(text) if has_wild else None

    def _match(col: pd.Series) -> pd.Series:
        if has_wild:
            return col.astype(str).str.match(pattern, case=False, na=False)
        return col.astype(str).str.contains(text, case=False, na=False, regex=False)

    if column and column in df.columns:
        return _match(df[column])

    # Search across all columns: match if ANY column contains the text.
    mask = pd.Series(False, index=df.index)
    for col in df.columns:
        mask |= _match(df[col])
    return mask
