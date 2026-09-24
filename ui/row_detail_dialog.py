"""
ui/row_detail_dialog.py

A small dialog shown on double-clicking a table row: lists every column
for that row as a two-column grid — column name on the left, value on the
right — so a wide record can be read without scrolling sideways. Values are
shown in a read-only multi-line text widget (not a QLabel) so real embedded
line breaks in the original cell data render correctly here, even though
the table itself collapses them for display.

Each field is sized to its own full (wrapped) content height, with its own
scrollbar disabled — so there's exactly one scrollbar for the whole dialog
(the outer QScrollArea), not one per field plus a global one.
"""

from __future__ import annotations

import pandas as pd
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QGridLayout,
    QLabel,
    QPlainTextEdit,
    QDialogButtonBox,
    QScrollArea,
    QWidget,
)
from PySide6.QtCore import Qt

from core.formatting import display_text

HEADER_COLUMN_WIDTH = 160  # px; long header names wrap within this instead of pushing values far right
ROW_SHADE_EVEN = "#ffffff"
ROW_SHADE_ODD = "#f3f5f8"


class RowDetailDialog(QDialog):
    def __init__(self, row_label: int, row: pd.Series, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Row {row_label} Details")
        self.resize(560, 480)
        self._value_widgets: list[QPlainTextEdit] = []

        outer_layout = QVBoxLayout(self)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer_layout.addWidget(self._scroll)

        grid_container = QWidget()
        grid = QGridLayout(grid_container)
        grid.setContentsMargins(10, 10, 10, 10)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(0, 0)  # header column: only as wide as it needs to be
        grid.setColumnStretch(1, 1)  # value column: takes the remaining width

        for i, column_name in enumerate(row.index):
            value = row[column_name]
            text = display_text(value)
            shade = ROW_SHADE_EVEN if i % 2 == 0 else ROW_SHADE_ODD

            label = QLabel(str(column_name))
            label.setWordWrap(True)  # long header names wrap to a second line, not truncate
            label.setMaximumWidth(HEADER_COLUMN_WIDTH)
            label.setMinimumWidth(HEADER_COLUMN_WIDTH)
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            label.setStyleSheet(f"font-weight: 600; background-color: {shade}; padding: 6px 4px;")

            value_widget = QPlainTextEdit(text)
            value_widget.setReadOnly(True)
            value_widget.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
            # No scrollbar of its own — the field grows to fit all of its content
            # instead. Height gets computed for real in _update_field_heights(),
            # once the widget's actual on-screen width is known.
            value_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            value_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            value_widget.setStyleSheet(f"background-color: {shade}; border: none; padding: 4px;")

            grid.addWidget(label, i, 0)
            grid.addWidget(value_widget, i, 1)
            self._value_widgets.append(value_widget)

        self._scroll.setWidget(grid_container)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        buttons.button(QDialogButtonBox.StandardButton.Close).clicked.connect(self.accept)
        outer_layout.addWidget(buttons)

    def _update_field_heights(self) -> None:
        """Resize every field to exactly fit its own wrapped content at its
        current width. Called on show and on every resize, since how much a
        field wraps (and therefore how tall it needs to be) depends on the
        dialog's current width."""
        for value_widget in self._value_widgets:
            width = value_widget.viewport().width()
            if width <= 0:
                continue
            doc = value_widget.document().clone(value_widget)
            doc.setTextWidth(width)
            height = int(doc.size().height()) + value_widget.frameWidth() * 2 + 4
            value_widget.setFixedHeight(max(height, value_widget.fontMetrics().lineSpacing() + 8))
            doc.deleteLater()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._update_field_heights()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_field_heights()
