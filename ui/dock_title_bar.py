"""
ui/dock_title_bar.py

Title bar for the app's dock widgets. Qt's built-in dock title buttons
ignore the stylesheet's icon size and draw their float/close icons at about
8px — tiny next to every other icon in the app. This replaces them with
normal tool buttons using the same 16px icon set as the rest of the UI.

Mouse presses on the bar itself are left unhandled, so QDockWidget still
does the dragging, and double-click to float/re-dock, as usual.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QDockWidget, QHBoxLayout, QLabel, QToolButton, QWidget

from ui.icons import icon


class DockTitleBar(QWidget):
    def __init__(self, dock: QDockWidget):
        super().__init__(dock)
        self.setObjectName("dockTitleBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)  # plain QWidget subclasses skip QSS backgrounds otherwise
        self._dock = dock

        title = QLabel(dock.windowTitle())
        title.setObjectName("dockTitleLabel")
        dock.windowTitleChanged.connect(title.setText)

        float_btn = self._make_button("float", "Float / re-dock this panel")
        float_btn.clicked.connect(lambda: dock.setFloating(not dock.isFloating()))
        close_btn = self._make_button("close", "Close this panel (reopen it from the View menu)")
        close_btn.clicked.connect(dock.close)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 4, 4)
        layout.setSpacing(2)
        layout.addWidget(title, stretch=1)
        layout.addWidget(float_btn)
        layout.addWidget(close_btn)

    def _make_button(self, icon_name: str, tooltip: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName("dockTitleButton")
        button.setIcon(icon(icon_name))
        button.setIconSize(QSize(16, 16))
        button.setToolTip(tooltip)
        button.setAutoRaise(True)
        return button
