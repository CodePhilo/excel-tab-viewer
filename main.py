"""
main.py

Entry point. Creates the QApplication, applies the stylesheet, installs a
global exception handler (so an unexpected bug shows a message box and gets
logged, instead of the app silently misbehaving or vanishing), and shows
the MainWindow.
"""

import os
import sys
import traceback

from PySide6.QtWidgets import QApplication, QMessageBox

from ui.main_window import MainWindow
from core.profile_manager import get_app_data_dir


def _install_exception_hook() -> None:
    """Catch any exception that escapes a Qt slot/callback. Without this,
    such errors are easy to miss (PySide6 prints them to stderr, which a
    packaged .exe has no visible console for) and can leave the app in a
    confusing half-broken state with no explanation to the user."""

    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))

        try:
            log_path = os.path.join(get_app_data_dir(), "crash.log")
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(tb_text + "\n" + ("-" * 60) + "\n")
        except OSError:
            log_path = None

        if QApplication.instance() is not None:
            detail = f"\n\nDetails were logged to:\n{log_path}" if log_path else ""
            QMessageBox.critical(
                None,
                "Unexpected Error",
                f"Something went wrong:\n\n{exc_value}{detail}\n\n"
                "The application will try to keep running, but you may want to save your work "
                "and restart if things seem off.",
            )
        else:
            sys.__excepthook__(exc_type, exc_value, exc_traceback)

    sys.excepthook = handle_exception


def _load_stylesheet(app: QApplication) -> None:
    style_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "style.qss")
    icon_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "icons")
    if not os.path.isfile(style_path):
        return
    try:
        with open(style_path, "r", encoding="utf-8") as f:
            css = f.read()
        # url() in Qt stylesheets resolves relative to the process's working
        # directory, not the .qss file's location — swap in an absolute path
        # (forward slashes; Qt wants those even on Windows) so icons load
        # correctly no matter how/where the app is launched from.
        css = css.replace("%ICONDIR%", icon_dir.replace(os.sep, "/"))
        app.setStyleSheet(css)
    except OSError:
        pass  # a missing/unreadable stylesheet shouldn't stop the app from launching


def main() -> None:
    _install_exception_hook()

    app = QApplication(sys.argv)
    app.setOrganizationName("ExcelTabViewer")  # QSettings (window layout, filter panel) key off these
    app.setApplicationName("Excel Tab Viewer")
    app.setStyle("Fusion")  # native styles ignore custom QSS sub-controls (icons,
                             # checkboxes, arrows) — Fusion respects them fully
    _load_stylesheet(app)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
