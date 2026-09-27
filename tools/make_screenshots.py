"""
tools/make_screenshots.py

Renders the README screenshots in docs/screenshots/ from the demo files,
so they can be regenerated after any UI change instead of captured by hand:

    python demo/make_demo_files.py      # if the demo files aren't there yet
    python tools/make_screenshots.py

Runs Qt off-screen (no window appears). Menus and message boxes are drawn
onto the window image where they would pop up. Your own saved profiles and
window layout are not touched.
"""

from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(ROOT, "demo")
OUT = os.path.join(ROOT, "docs", "screenshots")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))
os.environ["APPDATA"] = tempfile.mkdtemp()  # keep profiles written here away from the real ones
sys.path.insert(0, ROOT)

from PySide6.QtCore import QItemSelection, QItemSelectionModel, QPoint, Qt  # noqa: E402
from PySide6.QtGui import QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QWidget  # noqa: E402

import main as app_main  # noqa: E402
from core.folder_rules import FolderRule  # noqa: E402
from core.excel_loader import load_sheet_preview  # noqa: E402
from ui.folder_rule_dialog import FolderRuleDialog  # noqa: E402
from ui.header_row_dialog import HeaderRowDialog  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402

WINDOW_SIZE = (1180, 660)


def settle(app: QApplication) -> None:
    for _ in range(3):
        app.processEvents()


def overlay(base: QPixmap, widget: QWidget, top_left: QPoint) -> QPixmap:
    """Draw a popup (menu, message box) onto a window image."""
    result = QPixmap(base)
    painter = QPainter(result)
    painter.drawPixmap(top_left, widget.grab())
    painter.end()
    return result


def save(pixmap: QPixmap, name: str) -> None:
    path = os.path.join(OUT, name)
    pixmap.save(path)
    print("wrote", os.path.relpath(path, ROOT))


def new_window(app: QApplication) -> MainWindow:
    window = MainWindow()
    window.resize(*WINDOW_SIZE)
    window.global_search_dock.hide()
    window.show()
    settle(app)
    return window


def open_sales(window: MainWindow, app: QApplication):
    window._open_sheet_tab(os.path.join(DEMO, "Sales_2026-01.xlsx"), "Orders")
    tab = window.tab_widget.currentWidget()
    settle(app)
    return tab


def shot_sorting(app: QApplication) -> None:
    window = new_window(app)
    tab = open_sales(window, app)
    tab.set_sort([("Region", True), ("Total", False)])
    settle(app)

    header = tab.table_view.horizontalHeader()
    section = tab.model.column_names().index("Total")
    x = header.sectionViewportPosition(section) + header.sectionSize(section) // 2
    pos = QPoint(x, header.height() // 2)
    menu = QMenu(window)
    for text in ("Sort Smallest to Largest", "Sort Largest to Smallest",
                 "Then by Smallest to Largest", "Then by Largest to Smallest"):
        menu.addAction(text)
    menu.addSeparator()
    menu.addAction("Clear Sort (file order)")
    menu.adjustSize()
    at = header.mapTo(window, pos)
    at.setX(min(at.x(), window.width() - menu.width() - 8))  # keep the menu inside the picture
    save(overlay(window.grab(), menu, at), "sorting.png")
    window.close()


def shot_selection_summary(app: QApplication) -> None:
    window = new_window(app)
    tab = open_sales(window, app)
    model = tab.model
    col = model.column_names().index("Total")
    selection = QItemSelection(model.index(0, col - 2), model.index(11, col))
    tab.table_view.selectionModel().select(selection, QItemSelectionModel.SelectionFlag.ClearAndSelect)
    window.selection_summary_label.setText(tab.selection_summary())
    settle(app)
    save(window.grab(), "selection-summary.png")
    window.close()


def shot_export(app: QApplication) -> None:
    window = new_window(app)
    tab = open_sales(window, app)
    tab.filter_bar.set_quick_search("Status", "Pending")
    tab.apply_filters()
    tab.set_sort([("Total", False)])
    tab.hidden_columns = {"Discount Code", "Customer Phone"}
    tab.apply_column_visibility()
    settle(app)
    rows = tab.model.visible_row_count()
    box = QMessageBox(QMessageBox.Icon.Question, "Export Complete",
                      f"Saved {rows:,} rows x 9 columns to:\n"
                      r"C:\Reports\Sales_2026-01 - Orders (filtered).xlsx" "\n\nOpen it now?",
                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, window)
    box.adjustSize()
    base = window.grab()
    top_left = QPoint((base.width() - box.width()) // 2, (base.height() - box.height()) // 2)
    save(overlay(base, box, top_left), "export.png")
    window.close()


def shot_name_pattern(app: QApplication) -> None:
    dialog = FolderRuleDialog(FolderRule(DEMO, [("begins", "Sales_"), ("ends", "")], sheets="first"))
    dialog.folder_edit.setText(r"C:\Reports\Monthly")  # a tidier path for the picture
    dialog._refresh_timer.stop()
    # Show the demo folder's matches under the tidier path.
    rule = FolderRule(DEMO, [("begins", "Sales_")])
    dialog.matches_list.clear()
    matches = rule.find_files()
    dialog.matches_label.setText(f"Matching files: {len(matches)}")
    for path in matches:
        dialog.matches_list.addItem(os.path.basename(path))
    dialog.ok_button.setEnabled(True)
    dialog.show()
    settle(app)
    save(dialog.grab(), "name-pattern.png")
    dialog.close()


def shot_header_row(app: QApplication) -> None:
    path = os.path.join(DEMO, "Inventory_Report.xlsx")
    dialog = HeaderRowDialog("Inventory_Report.xlsx", "Stock", load_sheet_preview(path, "Stock"))
    dialog.resize(640, 440)
    dialog.row_spin.setValue(4)
    dialog.show()
    settle(app)
    save(dialog.grab(), "header-row.png")
    dialog.close()


def main() -> None:
    if not os.path.isfile(os.path.join(DEMO, "Sales_2026-01.xlsx")):
        sys.exit("Demo files missing: run  python demo/make_demo_files.py  first.")
    os.makedirs(OUT, exist_ok=True)

    app = QApplication(sys.argv)
    # A separate settings key, so the saved window layout of the real app
    # neither affects these pictures nor gets overwritten by them.
    app.setOrganizationName("ExcelTabViewerScreenshots")
    app.setApplicationName("Excel Tab Viewer")
    app.setStyle("Fusion")
    app_main._load_stylesheet(app)

    shot_sorting(app)
    shot_selection_summary(app)
    shot_export(app)
    shot_name_pattern(app)
    shot_header_row(app)


if __name__ == "__main__":
    main()
