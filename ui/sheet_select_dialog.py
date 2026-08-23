"""
ui/sheet_select_dialog.py

When an opened workbook has more than one sheet, this dialog lets the
user check off any number of sheets to open — each checked sheet
becomes its own tab. (Step 1 only allowed picking a single sheet via
QInputDialog; this replaces that with a multi-select checklist.)
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QLabel,
    QDialogButtonBox,
)
from PySide6.QtCore import Qt


class SheetSelectDialog(QDialog):
    def __init__(self, file_display_name: str, sheet_names: list[str], already_open: set[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Sheets")
        self.resize(320, 380)

        layout = QVBoxLayout(self)

        label = QLabel(f"'{file_display_name}' has {len(sheet_names)} sheets.\nChoose which to open:")
        layout.addWidget(label)

        self.list_widget = QListWidget()
        for name in sheet_names:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            if name in already_open:
                # Already open in a tab — pre-check it and let the user re-open
                # it if they want, but clearly mark it so they don't do so by accident.
                item.setText(f"{name}  (already open)")
                item.setCheckState(Qt.Unchecked)
            else:
                item.setCheckState(Qt.Unchecked)
            item.setData(Qt.UserRole, name)
            self.list_widget.addItem(item)
        # Default: check the first not-yet-open sheet, for the common single-sheet-of-interest case.
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.UserRole) not in already_open:
                item.setCheckState(Qt.Checked)
                break
        layout.addWidget(self.list_widget)

        select_row = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(lambda: self._set_all(Qt.Checked))
        select_none_btn = QPushButton("Select None")
        select_none_btn.clicked.connect(lambda: self._set_all(Qt.Unchecked))
        select_row.addWidget(select_all_btn)
        select_row.addWidget(select_none_btn)
        select_row.addStretch(1)
        layout.addLayout(select_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _set_all(self, state) -> None:
        for i in range(self.list_widget.count()):
            self.list_widget.item(i).setCheckState(state)

    def selected_sheets(self) -> list[str]:
        result = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.Checked:
                result.append(item.data(Qt.UserRole))
        return result
