"""
ui/icons.py

Loads icons from resources/icons (the same SVG set style.qss uses) for
widgets that set their icon in code rather than through the stylesheet.
"""

from __future__ import annotations

import os

from PySide6.QtGui import QIcon

ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", "icons")


def icon(name: str) -> QIcon:
    """The named icon, with its '-hover' variant (if any) as the Active mode
    — which auto-raise tool buttons show while the mouse is over them."""
    result = QIcon(os.path.join(ICON_DIR, f"{name}.svg"))
    hover_path = os.path.join(ICON_DIR, f"{name}-hover.svg")
    if os.path.isfile(hover_path):
        result.addFile(hover_path, mode=QIcon.Mode.Active)
    return result
