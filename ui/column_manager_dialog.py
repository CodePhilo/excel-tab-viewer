"""
ui/column_manager_dialog.py

Lets the user check/uncheck which columns are visible in a single tab's
table. This never touches the underlying DataFrame — it only affects
which columns QTableView shows, so hidden columns can be restored
instantly with no reload.
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


class ColumnManagerDialog(QDialog):
    def __init__(self, column_names: list[str], hidden_columns: set[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Columns")
        self.resize(300, 400)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Uncheck a column to hide it from this tab's view:"))

        self.list_widget = QListWidget()
        for name in column_names:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked if name in hidden_columns else Qt.Checked)
            item.setData(Qt.UserRole, name)
            self.list_widget.addItem(item)
        layout.addWidget(self.list_widget)

        button_row = QHBoxLayout()
        show_all_btn = QPushButton("Show All")
        show_all_btn.clicked.connect(lambda: self._set_all(Qt.Checked))
        hide_all_btn = QPushButton("Hide All")
        hide_all_btn.clicked.connect(lambda: self._set_all(Qt.Unchecked))
        button_row.addWidget(show_all_btn)
        button_row.addWidget(hide_all_btn)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _set_all(self, state) -> None:
        for i in range(self.list_widget.count()):
            self.list_widget.item(i).setCheckState(state)

    def hidden_columns(self) -> set[str]:
        """Returns the set of column names the user left unchecked (i.e. to hide)."""
        result = set()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.Unchecked:
                result.add(item.data(Qt.UserRole))
        return result
