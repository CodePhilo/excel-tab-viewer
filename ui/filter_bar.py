"""
ui/filter_bar.py

Reusable filter UI for a single tab. Two independent pieces, per the
earlier design decision:

1. Quick search — one column (or "All Columns") + a text box. Applies
   live with a short debounce, since it's cheap to recompute a single
   'contains' mask on every keystroke.

2. Multi-column AND filter — any number of condition rows (column +
   operator + value), combined with explicit "Apply Filters" / "Clear
   Filters" buttons rather than live updates, since recomputing several
   compound conditions on every keystroke would be wasteful and laggy
   on larger sheets.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QComboBox,
    QPushButton,
    QGroupBox,
)

from core.filters import (
    FilterCondition,
    OPERATOR_LABELS,
    NO_VALUE_OPERATORS,
    TWO_VALUE_OPERATORS,
)

QUICK_SEARCH_DEBOUNCE_MS = 300
ALL_COLUMNS_LABEL = "All Columns"
MAX_DROPDOWN_UNIQUE_VALUES = 200  # avoid populating a combo with huge unique sets


class ConditionRow(QWidget):
    """One row of the multi-column filter panel: column + operator + value(s)."""

    remove_requested = Signal(object)  # emits self

    def __init__(self, df: pd.DataFrame, parent=None):
        super().__init__(parent)
        self._df = df

        self.column_combo = QComboBox()
        self.column_combo.addItems([str(c) for c in df.columns])

        self.operator_combo = QComboBox()
        for op_key, op_label in OPERATOR_LABELS.items():
            self.operator_combo.addItem(op_label, userData=op_key)
        self.operator_combo.currentIndexChanged.connect(self._update_value_widgets)

        # value1 doubles as an editable combo pre-filled with unique values,
        # covering the "dropdown of unique values" filter type, while still
        # allowing free-typed text for contains/between/etc.
        self.value1_combo = QComboBox()
        self.value1_combo.setEditable(True)
        # Without this, QComboBox's default sizing grows to fit its widest
        # dropdown item — and since this dropdown is pre-filled with a
        # column's actual unique values, one long or multi-line cell value
        # was enough to balloon this widget (and the whole window) far wider
        # than the screen. Bounding it here doesn't touch the item values
        # themselves, so exact-match ("Equals") filtering still compares
        # against the real, untruncated value.
        self.value1_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.value1_combo.setMinimumContentsLength(24)
        self.value1_combo.setMaximumWidth(320)
        self.value2_edit = QLineEdit()
        self.value2_edit.setPlaceholderText("to...")

        self.remove_btn = QPushButton("✕")
        self.remove_btn.setFixedWidth(28)
        self.remove_btn.setToolTip("Remove this condition")
        self.remove_btn.clicked.connect(lambda: self.remove_requested.emit(self))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.column_combo, stretch=2)
        layout.addWidget(self.operator_combo, stretch=2)
        layout.addWidget(self.value1_combo, stretch=2)
        layout.addWidget(self.value2_edit, stretch=1)
        layout.addWidget(self.remove_btn)

        self.column_combo.currentIndexChanged.connect(self._populate_value_choices)
        self._populate_value_choices()
        self._update_value_widgets()

    def _current_column(self) -> str:
        return self.column_combo.currentText()

    def _populate_value_choices(self) -> None:
        col = self._current_column()
        self.value1_combo.clear()
        if not col or col not in self._df.columns:
            return
        try:
            uniques = self._df[col].dropna().unique()
        except Exception:
            uniques = []
        if len(uniques) <= MAX_DROPDOWN_UNIQUE_VALUES:
            for v in sorted(map(str, uniques))[:MAX_DROPDOWN_UNIQUE_VALUES]:
                self.value1_combo.addItem(v)
        self.value1_combo.setEditText("")

    def update_dataframe(self, df: pd.DataFrame) -> None:
        """
        Refresh this row's column list and unique-value choices after a Refresh
        (Step 5), preserving the currently selected column and typed values
        whenever they're still valid against the new data.
        """
        current_col = self._current_column()
        current_value1 = self.value1_combo.currentText()
        current_value2 = self.value2_edit.text()

        self._df = df

        self.column_combo.blockSignals(True)
        self.column_combo.clear()
        self.column_combo.addItems([str(c) for c in df.columns])
        if current_col in df.columns:
            self.column_combo.setCurrentText(current_col)
        self.column_combo.blockSignals(False)

        self._populate_value_choices()
        self.value1_combo.setEditText(current_value1)
        self.value2_edit.setText(current_value2)

    def _update_value_widgets(self) -> None:
        op = self.operator_combo.currentData()
        needs_value = op not in NO_VALUE_OPERATORS
        needs_two = op in TWO_VALUE_OPERATORS
        self.value1_combo.setVisible(needs_value)
        self.value2_edit.setVisible(needs_two)

    def to_condition(self) -> FilterCondition:
        op = self.operator_combo.currentData()
        value = self.value1_combo.currentText() if op not in NO_VALUE_OPERATORS else None
        value2 = self.value2_edit.text() if op in TWO_VALUE_OPERATORS else None
        return FilterCondition(column=self._current_column(), operator=op, value=value, value2=value2)

    def set_from_condition(self, cond: FilterCondition) -> None:
        """Restore this row's widgets from a saved FilterCondition (used when
        loading a profile in Step 6). Order matters: set column first (which
        repopulates the value dropdown), then operator, then the value text —
        otherwise repopulating would wipe out a value we just set."""
        existing_columns = [self.column_combo.itemText(i) for i in range(self.column_combo.count())]
        if cond.column in existing_columns:
            self.column_combo.setCurrentText(cond.column)

        idx = self.operator_combo.findData(cond.operator)
        if idx >= 0:
            self.operator_combo.setCurrentIndex(idx)
        self._update_value_widgets()

        if cond.value is not None:
            self.value1_combo.setEditText(cond.value)
        if cond.value2 is not None:
            self.value2_edit.setText(cond.value2)


class FilterBar(QWidget):
    """
    Emits filters_changed whenever the effective filter should be recomputed:
    - immediately (debounced) when the quick search box changes
    - only when the user clicks "Apply Filters" or "Clear Filters" for the
      multi-column panel
    """

    filters_changed = Signal()

    def __init__(self, df: pd.DataFrame, parent=None):
        super().__init__(parent)
        self._df = df
        self._condition_rows: list[ConditionRow] = []

        # --- Quick search row ---
        self.quick_column_combo = QComboBox()
        self.quick_column_combo.addItem(ALL_COLUMNS_LABEL)
        self.quick_column_combo.addItems([str(c) for c in df.columns])

        self.quick_search_edit = QLineEdit()
        self.quick_search_edit.setPlaceholderText("Quick search...")

        self.quick_clear_btn = QPushButton("Clear")
        self.quick_clear_btn.clicked.connect(self._clear_quick_search)

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self.filters_changed.emit)
        self.quick_search_edit.textChanged.connect(
            lambda: self._debounce_timer.start(QUICK_SEARCH_DEBOUNCE_MS)
        )
        self.quick_column_combo.currentIndexChanged.connect(lambda _index: self.filters_changed.emit())

        quick_row = QHBoxLayout()
        quick_row.addWidget(QLabel("Quick search:"))
        quick_row.addWidget(self.quick_column_combo, stretch=1)
        quick_row.addWidget(self.quick_search_edit, stretch=3)
        quick_row.addWidget(self.quick_clear_btn)

        # --- Multi-column condition panel ---
        self.conditions_group = QGroupBox("Filters (all conditions must match)")
        self.conditions_layout = QVBoxLayout()
        self.conditions_group.setLayout(self.conditions_layout)

        add_row_btn = QPushButton("+ Add Condition")
        add_row_btn.clicked.connect(self.add_condition_row)

        apply_btn = QPushButton("Apply Filters")
        apply_btn.clicked.connect(lambda _checked: self.filters_changed.emit())

        clear_btn = QPushButton("Clear Filters")
        clear_btn.clicked.connect(self.clear_conditions)

        buttons_row = QHBoxLayout()
        buttons_row.addWidget(add_row_btn)
        buttons_row.addStretch(1)
        buttons_row.addWidget(clear_btn)
        buttons_row.addWidget(apply_btn)

        self.conditions_layout.addLayout(buttons_row)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(quick_row)
        layout.addWidget(self.conditions_group)

        self.add_condition_row()  # start with one empty row for convenience

    # --- Quick search --------------------------------------------------------------

    def _clear_quick_search(self) -> None:
        self.quick_search_edit.blockSignals(True)
        self.quick_search_edit.clear()
        self.quick_search_edit.blockSignals(False)
        self.filters_changed.emit()

    def quick_search_state(self) -> tuple[Optional[str], str]:
        column = self.quick_column_combo.currentText()
        text = self.quick_search_edit.text().strip()
        return (None if column == ALL_COLUMNS_LABEL else column, text)

    # --- Condition rows --------------------------------------------------------------

    def add_condition_row(self) -> None:
        row = ConditionRow(self._df)
        row.remove_requested.connect(self._remove_condition_row)
        # Insert above the buttons row, which is always the last item in the layout.
        insert_index = self.conditions_layout.count() - 1
        self.conditions_layout.insertWidget(insert_index, row)
        self._condition_rows.append(row)

    def _remove_condition_row(self, row: ConditionRow) -> None:
        if row in self._condition_rows:
            self._condition_rows.remove(row)
        self.conditions_layout.removeWidget(row)
        row.deleteLater()

    def clear_conditions(self) -> None:
        for row in list(self._condition_rows):
            self._remove_condition_row(row)
        self.filters_changed.emit()

    def active_conditions(self) -> list[FilterCondition]:
        """Only conditions with a usable value (or that need no value) count."""
        result = []
        for row in self._condition_rows:
            cond = row.to_condition()
            if cond.operator in NO_VALUE_OPERATORS:
                result.append(cond)
            elif cond.value:  # skip rows the user hasn't filled in yet
                result.append(cond)
        return result

    # --- Refresh support -----------------------------------------------------------

    def update_dataframe(self, df: pd.DataFrame) -> None:
        """
        Called after a Refresh reloads the sheet from disk. Updates the quick-search
        column list and every condition row's column/value choices against the new
        data, preserving current selections wherever they're still valid.
        """
        self._df = df

        current_quick_col = self.quick_column_combo.currentText()
        self.quick_column_combo.blockSignals(True)
        self.quick_column_combo.clear()
        self.quick_column_combo.addItem(ALL_COLUMNS_LABEL)
        self.quick_column_combo.addItems([str(c) for c in df.columns])
        idx = self.quick_column_combo.findText(current_quick_col)
        self.quick_column_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.quick_column_combo.blockSignals(False)

        for row in self._condition_rows:
            row.update_dataframe(df)

    # --- Profile support (Step 6) ----------------------------------------------------

    def set_quick_search(self, column: Optional[str], text: str) -> None:
        """Restore quick-search state from a saved profile, without triggering
        the debounced auto-apply for every intermediate change — the caller
        (FileTab.apply_saved_state) applies filters once after everything is set."""
        available = [ALL_COLUMNS_LABEL] + [str(c) for c in self._df.columns]
        target = column if column in available else ALL_COLUMNS_LABEL
        idx = self.quick_column_combo.findText(target)

        self.quick_column_combo.blockSignals(True)
        self.quick_column_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.quick_column_combo.blockSignals(False)

        self.quick_search_edit.blockSignals(True)
        self.quick_search_edit.setText(text or "")
        self.quick_search_edit.blockSignals(False)

    def set_conditions(self, conditions: list[FilterCondition]) -> None:
        """Replace all condition rows with the given saved conditions."""
        for row in list(self._condition_rows):
            self._remove_condition_row(row)

        if not conditions:
            self.add_condition_row()  # keep one empty row for convenience
            return

        for cond in conditions:
            self.add_condition_row()
            self._condition_rows[-1].set_from_condition(cond)
