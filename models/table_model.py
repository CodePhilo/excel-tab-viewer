"""
models/table_model.py

A read-only Qt table model backed by a pandas DataFrame.

Design note: we keep a `_full_df` (as loaded from disk) and a `_view_df`
(what's currently displayed, after filters). For Step 1 there is no
filtering yet, so _view_df is just a reference to _full_df. This split
is set up now so Step 4 (filtering) only needs to add apply_filter() /
clear_filter() without reshaping the model itself.

_view_df is always rebuilt the same way: _full_df, narrowed by the current
filter mask (if any), then put in the current sort order (if any) — so a
filter change keeps the sort and a sort change keeps the filter.
"""

from __future__ import annotations

import html

import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from core.formatting import display_text, to_text_frame
from core.sorting import sort_order

SORT_ARROWS = {True: "▲", False: "▼"}

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
        self._text_df: pd.DataFrame | None = None  # lazily built display-text copy of _full_df
        self._mask: pd.Series | None = None  # current filter, or None for all rows
        self._sort_keys: list[tuple[str, bool]] = []  # (column, ascending), first one decides

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
        if role not in (Qt.DisplayRole, Qt.ToolTipRole):
            return None
        text = display_text(self._view_df.iat[index.row(), index.column()])
        if not text:
            return "" if role == Qt.DisplayRole else None
        if role == Qt.DisplayRole:
            if "\n" in text or "\r" in text:
                # Collapse embedded line breaks so a multi-line cell can't force
                # the column absurdly wide. The DataFrame itself is untouched —
                # this only affects what's painted in the cell; filtering,
                # search, and export all still see the real, unmodified value.
                text = text.replace("\r\n", " ⏎ ").replace("\n", " ⏎ ").replace("\r", " ⏎ ")
            return text
        return _tooltip_text(text)  # tooltip: real line breaks preserved

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role == Qt.ToolTipRole and orientation == Qt.Horizontal:
            # Long header names are elided in the capped-width column; show them in full here.
            return _tooltip_text(str(self._view_df.columns[section]))
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            name = str(self._view_df.columns[section])
            for position, (column, ascending) in enumerate(self._sort_keys):
                if column == name:
                    # Number the arrows once there's more than one sort column.
                    # In front of the name, so eliding a long name keeps it.
                    order = str(position + 1) if len(self._sort_keys) > 1 else ""
                    return f"{SORT_ARROWS[ascending]}{order} {name}"
            return name
        return str(section + 1)  # 1-based row numbers, like Excel

    # --- Convenience accessors ---------------------------------------------------

    def cell_text(self, row: int, column: int) -> str:
        """The full, unmodified text of a visible cell (no line-break collapsing),
        for copying and the cell preview."""
        return display_text(self._view_df.iat[row, column])

    def text_frame(self) -> pd.DataFrame:
        """All of _full_df as display text, for quick/cross-tab search. Built on
        first use and reused until the data is replaced (Refresh)."""
        if self._text_df is None:
            self._text_df = to_text_frame(self._full_df)
        return self._text_df

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
        self._text_df = None
        self._mask = None
        # Keep sorting by columns that are still there after a reload.
        self._sort_keys = [(c, asc) for c, asc in self._sort_keys if c in df.columns]
        self._rebuild_view()
        self.endResetModel()

    def _rebuild_view(self) -> None:
        df = self._full_df if self._mask is None else self._full_df[self._mask]
        if self._sort_keys:
            df = df.iloc[sort_order(df, self._sort_keys)]
        self._view_df = df

    # --- Filtering ---------------------------------------------------------------

    def apply_filter(self, mask: pd.Series) -> None:
        """Show only rows where mask is True. Never modifies _full_df, so
        clearing the filter (or Refresh) can always fall back to the full data."""
        self.beginResetModel()
        self._mask = mask
        self._rebuild_view()
        self.endResetModel()

    def clear_filter(self) -> None:
        self.beginResetModel()
        self._mask = None
        self._rebuild_view()
        self.endResetModel()

    def visible_row_count(self) -> int:
        return len(self._view_df.index)

    def is_filtered(self) -> bool:
        return len(self._view_df.index) != len(self._full_df.index)

    # --- Sorting -----------------------------------------------------------------

    def sort_keys(self) -> list[tuple[str, bool]]:
        return list(self._sort_keys)

    def set_sort(self, keys: list[tuple[str, bool]]) -> None:
        """Sort the view by (column, ascending) pairs; [] restores file order."""
        self.beginResetModel()
        self._sort_keys = [(c, bool(asc)) for c, asc in keys if c in self._full_df.columns]
        self._rebuild_view()
        self.endResetModel()

    def visible_frame(self, hidden_columns: set[str] = frozenset()) -> pd.DataFrame:
        """The rows and columns currently shown — filtered, sorted, without
        hidden columns — for export."""
        keep = [c for c in self._view_df.columns if str(c) not in hidden_columns]
        return self._view_df[keep]
