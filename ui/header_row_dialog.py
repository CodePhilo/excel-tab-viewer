"""
ui/header_row_dialog.py

Lets the user pick which row of a sheet actually holds the column headers,
for files where the real header isn't row 1 (title rows, blank rows, or
merged cells above it). Shows a raw preview of the first ~10 rows (no
header interpretation at all) with Excel-style 1-indexed row numbers, and
lets the user either type a row number or click a row in the preview.
"""

from __future__ import annotations

import pandas as pd
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QDialogButtonBox,
)
from PySide6.QtCore import Qt

PREVIEW_ROW_COUNT = 10


class HeaderRowDialog(QDialog):
    def __init__(self, file_display_name: str, sheet_name: str, preview_df: pd.DataFrame, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Header Row")
        self.resize(560, 420)
        self._preview_df = preview_df
        self._updating = False  # guards against the spin box and table fighting each other

        layout = QVBoxLayout(self)

        label = QLabel(
            f"'{file_display_name}' — sheet '{sheet_name}'\n"
            "Click the row that contains the column names, or type its row number below. "
            "Rows above it will be skipped; everything below becomes data."
        )
        label.setWordWrap(True)
        layout.addWidget(label)

        row_picker_row = QHBoxLayout()
        row_picker_row.addWidget(QLabel("Header row:"))
        self.row_spin = QSpinBox()
        self.row_spin.setMinimum(1)
        self.row_spin.setMaximum(max(1, len(preview_df)))
        self.row_spin.setValue(1)
        self.row_spin.valueChanged.connect(self._on_spin_changed)
        row_picker_row.addWidget(self.row_spin)
        row_picker_row.addStretch(1)
        layout.addLayout(row_picker_row)

        self.table = QTableWidget()
        self.table.setColumnCount(len(preview_df.columns))
        self.table.setRowCount(len(preview_df))
        self.table.setHorizontalHeaderLabels([f"Col {i + 1}" for i in range(len(preview_df.columns))])
        self.table.setVerticalHeaderLabels([str(i + 1) for i in range(len(preview_df))])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)

        for r in range(len(preview_df)):
            for c in range(len(preview_df.columns)):
                value = preview_df.iat[r, c]
                text = "" if pd.isna(value) else str(value)
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, c, item)

        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)
        layout.addWidget(self.table)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if len(preview_df) > 0:
            self.table.selectRow(0)

    def _on_spin_changed(self, value: int) -> None:
        if self._updating:
            return
        self._updating = True
        try:
            row_index = value - 1
            if 0 <= row_index < self.table.rowCount():
                self.table.selectRow(row_index)
        finally:
            self._updating = False

    def _on_table_selection_changed(self) -> None:
        if self._updating:
            return
        selected = self.table.selectedItems()
        if not selected:
            return
        self._updating = True
        try:
            self.row_spin.setValue(selected[0].row() + 1)
        finally:
            self._updating = False

    def selected_header_row(self) -> int:
        """Returns the chosen header row as a 0-indexed value, matching
        pandas' `header=` convention (row 1 in the UI -> 0 here)."""
        return self.row_spin.value() - 1
