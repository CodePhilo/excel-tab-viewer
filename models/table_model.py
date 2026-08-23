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

import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


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
            return str(value)  # full original value, real line breaks preserved
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return str(self._view_df.columns[section])
        return str(section + 1)  # 1-based row numbers, like Excel

    # --- Convenience accessors ---------------------------------------------------

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
