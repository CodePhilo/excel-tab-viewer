"""
models/table_model.py

A read-only Qt table model backed by a pandas DataFrame.

Design note: we keep a `_full_df` (as loaded from disk) and a `_view_df`
(what's currently displayed, after filters). For Step 1 there is no
filtering yet, so _view_df is just a reference to _full_df. This split
is set up now so Step 4 (filtering) only needs to add apply_filter() /
clear_filter() without reshaping the model itself.
"""

from __future__ import annotations

import html

import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

TOOLTIP_MAX_CHARS = 1000
TOOLTIP_MAX_LINES = 25


def _tooltip_text(text: str) -> str:
    """Bounded, wrapping tooltip for a cell value. Qt never wraps a plain-text
    tooltip, so a long cell produced a tooltip wider than the screen (and a
    many-line cell one taller than it). Rich text makes Qt wrap it to a sane
    width; very long values are cut short with a pointer to the row detail
    view, which always shows the full value."""
    truncated = False
    if len(text) > TOOLTIP_MAX_CHARS:
        text = text[:TOOLTIP_MAX_CHARS]
        truncated = True
    lines = text.splitlines()
    if len(lines) > TOOLTIP_MAX_LINES:
        lines = lines[:TOOLTIP_MAX_LINES]
        truncated = True
    body = "<br>".join(html.escape(line) for line in lines)
    if truncated:
        body += "<br><i>... (double-click the row to see the full value)</i>"
    return f"<qt>{body}</qt>"


class ExcelTableModel(QAbstractTableModel):
    def __init__(self, df: pd.DataFrame, parent=None):
        super().__init__(parent)
        self._full_df = df
        self._view_df = df

    # --- Qt required overrides -------------------------------------------------

    def rowCount(self, parent=QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._view_df.index)

    def columnCount(self, parent=QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._view_df.columns)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        value = self._view_df.iat[index.row(), index.column()]
        if pd.isna(value):
            return "" if role == Qt.DisplayRole else None
        if role == Qt.DisplayRole:
            text = str(value)
            if "\n" in text or "\r" in text:
                # Collapse embedded line breaks so a multi-line cell can't force
                # the column absurdly wide. The DataFrame itself is untouched —
                # this only affects what's painted in the cell; filtering,
                # search, and export all still see the real, unmodified value.
                text = text.replace("\r\n", " ⏎ ").replace("\n", " ⏎ ").replace("\r", " ⏎ ")
            return text
        if role == Qt.ToolTipRole:
            return _tooltip_text(str(value))  # original value, real line breaks preserved
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role == Qt.ToolTipRole and orientation == Qt.Horizontal:
            # Long header names are elided in the capped-width column; show them in full here.
            return _tooltip_text(str(self._view_df.columns[section]))
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return str(self._view_df.columns[section])
        return str(section + 1)  # 1-based row numbers, like Excel

    # --- Convenience accessors ---------------------------------------------------

    def cell_text(self, row: int, column: int) -> str:
        """The full, unmodified text of a visible cell (no line-break collapsing),
        for copying and the cell preview."""
        value = self._view_df.iat[row, column]
        return "" if pd.isna(value) else str(value)

    def column_names(self) -> list[str]:
        return [str(c) for c in self._full_df.columns]

    def row_count_full(self) -> int:
        return len(self._full_df.index)

    def column_count_full(self) -> int:
        return len(self._full_df.columns)

    def set_dataframe(self, df: pd.DataFrame) -> None:
        """Replace the underlying data entirely (used by Refresh in a later step)."""
        self.beginResetModel()
        self._full_df = df
        self._view_df = df
        self.endResetModel()

    # --- Filtering ---------------------------------------------------------------

    def apply_filter(self, mask: pd.Series) -> None:
        """Show only rows where mask is True. Never modifies _full_df, so
        clearing the filter (or Refresh) can always fall back to the full data."""
        self.beginResetModel()
        self._view_df = self._full_df[mask]
        self.endResetModel()

    def clear_filter(self) -> None:
        self.beginResetModel()
        self._view_df = self._full_df
        self.endResetModel()

    def visible_row_count(self) -> int:
        return len(self._view_df.index)

    def is_filtered(self) -> bool:
        return len(self._view_df.index) != len(self._full_df.index)
