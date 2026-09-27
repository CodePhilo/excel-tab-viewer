"""
ui/folder_rule_dialog.py

FolderRuleDialog builds a FolderRule: a folder, any number of file-name
conditions (begins with / ends with / contains / ...), which sheets to
open, and the header row — with a live list of the files it matches.

FolderRulesDialog lists the rules active in this session (from
File > Open Files by Name Pattern, or from a loaded profile) and lets the
user add, edit, or remove them. Saving a profile saves these rules.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.folder_rules import CRITERIA_LABELS, SHEET_MODES, FolderRule

MATCH_REFRESH_DEBOUNCE_MS = 300
MAX_LISTED_MATCHES = 500


class _CriterionRow(QWidget):
    """One condition: kind + text + remove button."""

    changed = Signal()
    remove_requested = Signal(object)  # emits self

    def __init__(self, kind: str = "begins", text: str = "", parent=None):
        super().__init__(parent)
        self.kind_combo = QComboBox()
        for key, label in CRITERIA_LABELS.items():
            self.kind_combo.addItem(label, userData=key)
        self.kind_combo.setCurrentIndex(max(0, self.kind_combo.findData(kind)))
        self.kind_combo.currentIndexChanged.connect(self.changed)

        self.text_edit = QLineEdit(text)
        self.text_edit.setPlaceholderText("Part of the file name, e.g. Sales_")
        self.text_edit.textChanged.connect(self.changed)

        remove_btn = QPushButton()
        remove_btn.setObjectName("smallIconButton")  # icon + compact padding come from style.qss
        remove_btn.setFixedWidth(30)
        remove_btn.setToolTip("Remove this condition")
        remove_btn.clicked.connect(lambda: self.remove_requested.emit(self))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.kind_combo)
        layout.addWidget(self.text_edit, stretch=1)
        layout.addWidget(remove_btn)

    def criterion(self) -> tuple[str, str]:
        return (self.kind_combo.currentData(), self.text_edit.text().strip())


class FolderRuleDialog(QDialog):
    def __init__(self, rule: FolderRule | None = None, ok_text: str = "Open Matching Files", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Open Files by Name Pattern")
        self.resize(620, 560)
        self._rows: list[_CriterionRow] = []

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(MATCH_REFRESH_DEBOUNCE_MS)
        self._refresh_timer.timeout.connect(self._refresh_matches)

        # Folder
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Folder to look in")
        self.folder_edit.textChanged.connect(self._schedule_refresh)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_folder)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.folder_edit, stretch=1)
        folder_row.addWidget(browse_btn)

        self.subfolders_check = QCheckBox("Include subfolders")
        self.subfolders_check.toggled.connect(self._schedule_refresh)

        # Conditions
        self.match_combo = QComboBox()
        self.match_combo.addItem("all of these conditions", userData=True)
        self.match_combo.addItem("any of these conditions", userData=False)
        self.match_combo.currentIndexChanged.connect(self._schedule_refresh)
        match_row = QHBoxLayout()
        match_row.addWidget(QLabel("File name must match"))
        match_row.addWidget(self.match_combo)
        match_row.addStretch(1)

        self.criteria_layout = QVBoxLayout()
        self.criteria_layout.setContentsMargins(0, 0, 0, 0)
        add_btn = QPushButton("+ Add Condition")
        add_btn.clicked.connect(lambda: self._add_row())
        add_row = QHBoxLayout()
        add_row.addWidget(add_btn)
        add_row.addStretch(1)

        # Sheets + header row
        self.sheets_combo = QComboBox()
        for key, label in SHEET_MODES.items():
            self.sheets_combo.addItem(label, userData=key)
        self.sheets_combo.currentIndexChanged.connect(self._update_sheet_names_enabled)
        self.sheet_names_edit = QLineEdit()
        self.sheet_names_edit.setPlaceholderText("Sheet names, separated by commas")
        sheets_row = QHBoxLayout()
        sheets_row.addWidget(self.sheets_combo)
        sheets_row.addWidget(self.sheet_names_edit, stretch=1)

        self.header_spin = QSpinBox()
        self.header_spin.setRange(1, 1000)
        self.header_spin.setMaximumWidth(90)
        self.header_spin.setToolTip("The row holding the column names. Rows above it are skipped.")

        options = QFormLayout()
        options.addRow("Sheets to open:", sheets_row)
        options.addRow("Header row:", self.header_spin)

        # Matching files
        self.matches_label = QLabel()
        self.matches_list = QListWidget()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setText(ok_text)
        # The button box sizes buttons without the stylesheet's padding, which
        # clipped the first letter of a long label like this one.
        self.ok_button.setMinimumWidth(self.ok_button.fontMetrics().horizontalAdvance(ok_text) + 48)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Folder:"))
        layout.addLayout(folder_row)
        layout.addWidget(self.subfolders_check)
        layout.addSpacing(6)
        layout.addLayout(match_row)
        layout.addLayout(self.criteria_layout)
        layout.addLayout(add_row)
        layout.addSpacing(6)
        layout.addLayout(options)
        layout.addSpacing(6)
        layout.addWidget(self.matches_label)
        layout.addWidget(self.matches_list, stretch=1)
        layout.addWidget(buttons)

        rule = rule or FolderRule(folder="", criteria=[("begins", "")])
        self.folder_edit.setText(rule.folder)
        self.subfolders_check.setChecked(rule.include_subfolders)
        self.match_combo.setCurrentIndex(self.match_combo.findData(rule.match_all))
        for kind, text in rule.criteria or [("begins", "")]:
            self._add_row(kind, text)
        self.sheets_combo.setCurrentIndex(max(0, self.sheets_combo.findData(rule.sheets)))
        self.sheet_names_edit.setText(", ".join(rule.sheet_names))
        self.header_spin.setValue(rule.header_row + 1)
        self._update_sheet_names_enabled()
        self._refresh_matches()

    def _add_row(self, kind: str = "begins", text: str = "") -> None:
        row = _CriterionRow(kind, text)
        row.changed.connect(self._schedule_refresh)
        row.remove_requested.connect(self._remove_row)
        self._rows.append(row)
        self.criteria_layout.addWidget(row)
        row.text_edit.setFocus()
        self._schedule_refresh()

    def _remove_row(self, row: _CriterionRow) -> None:
        self._rows.remove(row)
        self.criteria_layout.removeWidget(row)
        row.deleteLater()
        self._schedule_refresh()

    def _browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose Folder", self.folder_edit.text())
        if folder:
            self.folder_edit.setText(os.path.normpath(folder))

    def _update_sheet_names_enabled(self) -> None:
        self.sheet_names_edit.setEnabled(self.sheets_combo.currentData() == "named")

    def _schedule_refresh(self, *_args) -> None:
        self._refresh_timer.start()  # restarts the countdown while the user is still typing

    def _refresh_matches(self) -> None:
        self.matches_list.clear()
        rule = self.rule()
        if not rule.folder:
            self.matches_label.setText("Choose a folder to see the matching files.")
            self.ok_button.setEnabled(False)
            return
        try:
            paths = rule.find_files()
        except OSError as exc:
            self.matches_label.setText(f"Can't read this folder: {exc}")
            self.ok_button.setEnabled(False)
            return
        # A rule matching nothing yet is still worth keeping (tomorrow's file
        # may not exist today), so OK stays enabled once the folder is valid.
        self.ok_button.setEnabled(True)
        count = len(paths)
        self.matches_label.setText(f"Matching files: {count:,}" if count else "No files match yet.")
        for path in paths[:MAX_LISTED_MATCHES]:
            item = QListWidgetItem(os.path.relpath(path, rule.folder))
            item.setToolTip(path)
            self.matches_list.addItem(item)
        if count > MAX_LISTED_MATCHES:
            self.matches_list.addItem(f"... and {count - MAX_LISTED_MATCHES:,} more")

    def accept(self) -> None:
        self._refresh_timer.stop()
        self._refresh_matches()  # don't accept on a stale, not-yet-refreshed folder check
        if self.ok_button.isEnabled():
            super().accept()

    def rule(self) -> FolderRule:
        names = [n.strip() for n in self.sheet_names_edit.text().split(",") if n.strip()]
        return FolderRule(
            folder=os.path.normpath(self.folder_edit.text().strip()) if self.folder_edit.text().strip() else "",
            criteria=[c for c in (row.criterion() for row in self._rows) if c[1]],
            match_all=self.match_combo.currentData(),
            include_subfolders=self.subfolders_check.isChecked(),
            sheets=self.sheets_combo.currentData(),
            sheet_names=names,
            header_row=self.header_spin.value() - 1,
        )


class FolderRulesDialog(QDialog):
    """Add / edit / remove the session's folder rules. Changes are applied
    by the caller through the three signals, as they happen."""

    add_requested = Signal()
    edit_requested = Signal(int)
    remove_requested = Signal(int)

    def __init__(self, rules: list[FolderRule], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Folder Rules")
        self.resize(640, 320)

        intro = QLabel(
            "Each rule opens the files in a folder whose names match its conditions. "
            "Rules are saved with the profile and checked again whenever it's loaded "
            "and on Refresh All Tabs, so new matching files open automatically."
        )
        intro.setWordWrap(True)

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(lambda _item: self._emit_for_current(self.edit_requested))
        self.list_widget.currentRowChanged.connect(self._update_buttons)

        add_btn = QPushButton("Add...")
        add_btn.clicked.connect(self.add_requested)
        self.edit_btn = QPushButton("Edit...")
        self.edit_btn.clicked.connect(lambda: self._emit_for_current(self.edit_requested))
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(lambda: self._emit_for_current(self.remove_requested))
        side = QVBoxLayout()
        side.addWidget(add_btn)
        side.addWidget(self.edit_btn)
        side.addWidget(self.remove_btn)
        side.addStretch(1)

        body = QHBoxLayout()
        body.addWidget(self.list_widget, stretch=1)
        body.addLayout(side)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(body)
        layout.addWidget(buttons)

        self.set_rules(rules)

    def set_rules(self, rules: list[FolderRule]) -> None:
        row = self.list_widget.currentRow()
        self.list_widget.clear()
        for rule in rules:
            item = QListWidgetItem(rule.describe())
            item.setToolTip(rule.describe())
            self.list_widget.addItem(item)
        if not rules:
            placeholder = QListWidgetItem("No folder rules yet. Click Add to create one.")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list_widget.addItem(placeholder)
        self._rule_count = len(rules)
        self.list_widget.setCurrentRow(min(max(row, 0), len(rules) - 1) if rules else -1)
        self._update_buttons()

    def _update_buttons(self, *_args) -> None:
        has = 0 <= self.list_widget.currentRow() < self._rule_count
        self.edit_btn.setEnabled(has)
        self.remove_btn.setEnabled(has)

    def _emit_for_current(self, signal) -> None:
        row = self.list_widget.currentRow()
        if 0 <= row < self._rule_count:
            signal.emit(row)
