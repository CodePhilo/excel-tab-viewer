"""
One-off script: renders resources/icons/app.svg into a multi-size
resources/icons/app.ico for the .exe (Windows needs .ico for the file and
taskbar icon). Rerun after changing app.svg:

    python resources/make_app_ico.py
"""

import os
import struct
import sys

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def _render_png(renderer: QSvgRenderer, size: int) -> bytes:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


def main() -> None:
    app = QGuiApplication(sys.argv)  # noqa: F841 — QImage/QPainter need a GUI app instance
    renderer = QSvgRenderer(os.path.join(ICON_DIR, "app.svg"))
    images = [(size, _render_png(renderer, size)) for size in SIZES]

    # ICO = 6-byte header, one 16-byte directory entry per image, then the
    # images themselves (PNG-compressed entries are valid since Windows Vista).
    offset = 6 + 16 * len(images)
    header = struct.pack("<HHH", 0, 1, len(images))
    entries, blobs = b"", b""
    for size, png in images:
        dim = 0 if size >= 256 else size  # 0 means 256 in the ICO format
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        blobs += png
        offset += len(png)

    out_path = os.path.join(ICON_DIR, "app.ico")
    with open(out_path, "wb") as f:
        f.write(header + entries + blobs)
    print("wrote", out_path)


if __name__ == "__main__":
    main()
