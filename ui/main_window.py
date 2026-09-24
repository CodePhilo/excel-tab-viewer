"""
ui/main_window.py

Step 2 scope: open multiple files at once (multi-select file dialog),
choose any number of sheets per file (each becomes its own tab), avoid
opening the same (file, sheet) twice, and provide a sidebar tree for
navigating between open files/sheets — grouped by file, showing each
open sheet's row/column counts, with click-to-jump-to-tab.
"""

from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QMainWindow,
    QTabWidget,
    QFileDialog,
    QMessageBox,
    QDockWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QInputDialog,
    QLineEdit,
    QPushButton,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QStackedWidget,
    QMenu,
    QPlainTextEdit,
)
from PySide6.QtGui import QAction
from PySide6.QtCore import Qt, QSettings

import pandas as pd

from ui.dock_title_bar import DockTitleBar
from ui.file_tab import FileTab
from ui.sheet_select_dialog import SheetSelectDialog
from ui.header_row_dialog import HeaderRowDialog
from core.excel_loader import list_sheet_names, load_sheet_preview, ExcelLoadError
from core.filters import compile_quick_search
from core import profile_manager
from core.profile_manager import ProfileError

MAX_GLOBAL_RESULTS_PER_TAB = 100
MAX_PREVIEW_VALUE_CHARS = 40  # per value in a cross-tab search result line
DEFAULT_WINDOW_SIZE = (1200, 750)


def _preview_value(value) -> str:
    """One short, single-line rendering of a cell for a search-result line —
    a long or multi-line cell otherwise made that result row enormous."""
    if pd.isna(value):
        return ""
    text = " ".join(str(value).split())
    if len(text) > MAX_PREVIEW_VALUE_CHARS:
        text = text[: MAX_PREVIEW_VALUE_CHARS - 1] + "…"
    return text


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Excel Tab Viewer")

        # Tracks every currently open (file_path, sheet_name) -> FileTab widget,
        # so we can prevent duplicate tabs and look up a tab quickly from the sidebar.
        self.open_tabs: dict[tuple[str, str], FileTab] = {}

        # Tracks the one FileTab (if any) with an active cross-tab-search row
        # highlight, so clicking a new result can clear the previous one —
        # only one row is ever highlighted across the whole app at a time.
        self._highlighted_tab: FileTab | None = None

        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self._close_tab)
        self.tab_widget.setMovable(True)
        self.tab_widget.currentChanged.connect(self._on_current_tab_changed)
        # Keep tabs at their natural width and scroll (via arrow buttons) once
        # they overflow, instead of shrinking/eliding as more tabs are opened.
        self.tab_widget.setUsesScrollButtons(True)
        self.tab_widget.tabBar().setExpanding(False)
        self.tab_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tab_widget.customContextMenuRequested.connect(self._show_tab_context_menu)

        self.empty_state_widget = self._build_empty_state()

        self.central_stack = QStackedWidget()
        self.central_stack.addWidget(self.empty_state_widget)  # index 0
        self.central_stack.addWidget(self.tab_widget)  # index 1
        self.setCentralWidget(self.central_stack)

        self._build_sidebar()
        self._build_global_search()
        self._build_cell_preview()
        self._build_menu()
        self._build_profiles_menu()

        self.statusBar().showMessage("Ready")
        self._update_central_stack()
        self._restore_window_layout()

    # --- Window size / layout ------------------------------------------------------

    def _restore_window_layout(self) -> None:
        """Reopen at the size/position and dock layout the user last left, or —
        first run, or a saved position that's no longer on any screen — at a
        size that fits the current screen. (A fixed 1200x750 was taller than the
        usable area of a 1366x768 laptop, putting the bottom of the window,
        status bar included, off-screen.)"""
        settings = QSettings()
        geometry = settings.value("window/geometry")
        if geometry is None or not self.restoreGeometry(geometry):
            available = self.screen().availableGeometry()
            width = min(DEFAULT_WINDOW_SIZE[0], int(available.width() * 0.9))
            height = min(DEFAULT_WINDOW_SIZE[1], int(available.height() * 0.9))
            self.resize(width, height)
            self.move(available.center() - self.rect().center())
        state = settings.value("window/state")
        if state is not None:
            self.restoreState(state)

    def closeEvent(self, event) -> None:
        settings = QSettings()
        settings.setValue("window/geometry", self.saveGeometry())
        settings.setValue("window/state", self.saveState())
        super().closeEvent(event)

    def _build_empty_state(self) -> QWidget:
        widget = QWidget()
        widget.setObjectName("emptyStateWidget")

        title = QLabel("No files open")
        title.setObjectName("emptyStateTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        subtitle = QLabel("Open one or more Excel files to view, filter, and compare them side by side.")
        subtitle.setObjectName("emptyStateSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)

        open_btn = QPushButton("Open Excel File(s)...")
        open_btn.setObjectName("emptyStateButton")
        open_btn.clicked.connect(self.open_files_dialog)

        layout = QVBoxLayout(widget)
        layout.addStretch(1)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(12)
        layout.addWidget(open_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch(1)
        return widget

    def _update_central_stack(self) -> None:
        """Show the empty-state placeholder when nothing is open, the tab
        widget otherwise — so the app never greets the user with a blank pane."""
        self.central_stack.setCurrentWidget(
            self.tab_widget if self.tab_widget.count() > 0 else self.empty_state_widget
        )

    # --- Sidebar -------------------------------------------------------------------

    def _build_sidebar(self) -> None:
        self.sidebar_tree = QTreeWidget()
        self.sidebar_tree.setHeaderLabels(["Open Files / Sheets"])
        self.sidebar_tree.itemClicked.connect(self._on_sidebar_item_clicked)

        dock = QDockWidget("Files", self)
        dock.setObjectName("filesDock")  # saveState()/restoreState() identify docks by name
        dock.setWidget(self.sidebar_tree)
        # DockWidgetClosable is required for toggleViewAction() (used in the View menu)
        # to actually show/hide the dock, not just flip its checkmark.
        dock.setFeatures(
            QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
            | QDockWidget.DockWidgetClosable
        )
        dock.setTitleBarWidget(DockTitleBar(dock))
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)
        self.sidebar_dock = dock

    def _find_or_create_file_node(self, file_path: str) -> QTreeWidgetItem:
        """Return the top-level tree item for this file, creating it if needed."""
        for i in range(self.sidebar_tree.topLevelItemCount()):
            node = self.sidebar_tree.topLevelItem(i)
            if node.data(0, Qt.UserRole) == file_path:
                return node
        node = QTreeWidgetItem([os.path.basename(file_path)])
        node.setData(0, Qt.UserRole, file_path)
        node.setToolTip(0, file_path)
        self.sidebar_tree.addTopLevelItem(node)
        node.setExpanded(True)
        return node

    def _add_sidebar_entry(self, tab: FileTab) -> None:
        file_node = self._find_or_create_file_node(tab.file_path)
        rows = tab.model.row_count_full()
        cols = tab.model.column_count_full()
        child = QTreeWidgetItem([f"{tab.sheet_name}  ({rows:,} x {cols:,})"])
        child.setData(0, Qt.UserRole, tab.key)
        file_node.addChild(child)

    def _remove_sidebar_entry(self, tab: FileTab) -> None:
        for i in range(self.sidebar_tree.topLevelItemCount()):
            file_node = self.sidebar_tree.topLevelItem(i)
            if file_node.data(0, Qt.UserRole) != tab.file_path:
                continue
            for j in range(file_node.childCount()):
                child = file_node.child(j)
                if child.data(0, Qt.UserRole) == tab.key:
                    file_node.removeChild(child)
                    break
            if file_node.childCount() == 0:
                index = self.sidebar_tree.indexOfTopLevelItem(file_node)
                self.sidebar_tree.takeTopLevelItem(index)
            break

    def _update_sidebar_entry(self, tab: FileTab) -> None:
        """Refresh a sidebar row/column count label after a Refresh reload."""
        for i in range(self.sidebar_tree.topLevelItemCount()):
            file_node = self.sidebar_tree.topLevelItem(i)
            if file_node.data(0, Qt.UserRole) != tab.file_path:
                continue
            for j in range(file_node.childCount()):
                child = file_node.child(j)
                if child.data(0, Qt.UserRole) == tab.key:
                    rows = tab.model.row_count_full()
                    cols = tab.model.column_count_full()
                    child.setText(0, f"{tab.sheet_name}  ({rows:,} x {cols:,})")
                    return
            break

    def _on_sidebar_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        key = item.data(0, Qt.UserRole)
        if key is None or isinstance(key, str):
            return  # a top-level file node was clicked, not a sheet — nothing to jump to
        tab = self.open_tabs.get(key)
        if tab is not None:
            self.tab_widget.setCurrentWidget(tab)

    def _on_current_tab_changed(self, index: int) -> None:
        """Keep the sidebar selection and cell preview in sync with the active tab."""
        tab = self.tab_widget.widget(index)
        if tab is None:
            self._set_cell_preview("", "")
            return
        self._set_cell_preview(*tab.current_cell_info())
        for i in range(self.sidebar_tree.topLevelItemCount()):
            file_node = self.sidebar_tree.topLevelItem(i)
            for j in range(file_node.childCount()):
                child = file_node.child(j)
                if child.data(0, Qt.UserRole) == tab.key:
                    self.sidebar_tree.setCurrentItem(child)
                    return

    # --- Menu / actions ----------------------------------------------------------

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        open_action = QAction("&Open Excel File(s)...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.open_files_dialog)
        file_menu.addAction(open_action)

        file_menu.addSeparator()

        refresh_current_action = QAction("Refresh Current Tab", self)
        refresh_current_action.setShortcut("Ctrl+R")
        refresh_current_action.triggered.connect(self.refresh_current_tab)
        file_menu.addAction(refresh_current_action)
        self.refresh_current_action = refresh_current_action

        refresh_all_action = QAction("Refresh All Tabs", self)
        refresh_all_action.setShortcut("Ctrl+Shift+R")
        refresh_all_action.triggered.connect(self.refresh_all_tabs)
        file_menu.addAction(refresh_all_action)

        view_menu = self.menuBar().addMenu("&View")
        view_menu.addAction(self.sidebar_dock.toggleViewAction())
        view_menu.addAction(self.global_search_dock.toggleViewAction())
        cell_preview_action = self.cell_preview_dock.toggleViewAction()
        cell_preview_action.setShortcut("F3")
        view_menu.addAction(cell_preview_action)

        toolbar = self.addToolBar("Main")
        toolbar.setObjectName("mainToolbar")
        toolbar.setMovable(False)
        toolbar.addAction(open_action)
        toolbar.addAction(refresh_current_action)
        toolbar.addAction(refresh_all_action)
        toolbar.addSeparator()
        toolbar.addWidget(self.global_search_bar_widget)

    # --- Opening files -------------------------------------------------------------

    def open_files_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Open Excel File(s)",
            "",
            "Excel Files (*.xlsx *.xlsm *.xls);;All Files (*)",
        )
        if not paths:
            return  # user cancelled

        for path in paths:
            self._handle_file(path)

    def _handle_file(self, path: str) -> None:
        try:
            sheet_names = list_sheet_names(path)
        except ExcelLoadError as exc:
            self._show_load_error(exc)
            return

        if not sheet_names:
            QMessageBox.warning(
                self,
                "No Sheets Found",
                f"'{os.path.basename(path)}' doesn't appear to contain any sheets.",
            )
            return

        already_open = {sheet for (p, sheet) in self.open_tabs if p == path}

        if len(sheet_names) == 1:
            sheet_name = sheet_names[0]
            if sheet_name in already_open:
                self.tab_widget.setCurrentWidget(self.open_tabs[(path, sheet_name)])
                return
            header_row = self._prompt_header_row(path, sheet_name)
            if header_row is None:
                return  # user cancelled the header-row picker
            self._open_sheet_tab(path, sheet_name, header_row=header_row)
            return

        dialog = SheetSelectDialog(os.path.basename(path), sheet_names, already_open, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return  # user cancelled sheet selection for this file

        chosen = dialog.selected_sheets()
        if not chosen:
            return  # nothing checked, nothing to do

        for sheet_name in chosen:
            if (path, sheet_name) in self.open_tabs:
                continue  # already open — silently skip rather than duplicate
            header_row = self._prompt_header_row(path, sheet_name)
            if header_row is None:
                continue  # user cancelled for this particular sheet; move on to the next
            self._open_sheet_tab(path, sheet_name, header_row=header_row)

    def _prompt_header_row(self, path: str, sheet_name: str) -> int | None:
        """Show a preview of the sheet and let the user pick which row holds
        the column headers. Returns the chosen row (0-indexed, matching
        pandas' `header=`), or None if the user cancelled or the preview
        itself couldn't be loaded."""
        try:
            preview_df = load_sheet_preview(path, sheet_name)
        except ExcelLoadError as exc:
            self._show_load_error(exc)
            return None

        dialog = HeaderRowDialog(os.path.basename(path), sheet_name, preview_df, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return None
        return dialog.selected_header_row()

    def _open_sheet_tab(
        self,
        path: str,
        sheet_name: str,
        header_row: int = 0,
        saved_state: dict | None = None,
    ) -> None:
        try:
            tab = FileTab(path, sheet_name, header_row=header_row)
        except ExcelLoadError as exc:
            self._show_load_error(exc)
            return

        if saved_state is not None:
            tab.apply_saved_state(saved_state)

        tab.current_cell_changed.connect(
            lambda title, text, t=tab: self._on_tab_cell_changed(t, title, text)
        )
        index = self.tab_widget.addTab(tab, tab.short_tab_label())
        self.tab_widget.setTabToolTip(index, f"{tab.file_path}\nSheet: {tab.sheet_name}")
        self.tab_widget.setCurrentIndex(index)
        self.open_tabs[tab.key] = tab
        self._add_sidebar_entry(tab)
        self._update_central_stack()

        rows = tab.model.row_count_full()
        cols = tab.model.column_count_full()
        self.statusBar().showMessage(
            f"Loaded '{os.path.basename(path)}' [{sheet_name}] — {rows:,} rows x {cols:,} columns",
            5000,
        )

    def _close_tab(self, index: int) -> None:
        widget = self.tab_widget.widget(index)
        self.tab_widget.removeTab(index)
        if widget is not None:
            self.open_tabs.pop(widget.key, None)
            self._remove_sidebar_entry(widget)
            if self._highlighted_tab is widget:
                self._highlighted_tab = None
            widget.deleteLater()
        self._update_central_stack()

    def _show_tab_context_menu(self, pos) -> None:
        bar = self.tab_widget.tabBar()
        index = bar.tabAt(bar.mapFrom(self.tab_widget, pos))

        menu = QMenu(self)
        if index >= 0:
            close_action = menu.addAction("Close Tab")
            close_action.triggered.connect(lambda checked=False, i=index: self._close_tab(i))
            menu.addSeparator()

        close_all_action = menu.addAction("Close All Tabs")
        close_all_action.setEnabled(self.tab_widget.count() > 0)
        close_all_action.triggered.connect(self._close_all_tabs)

        menu.exec(self.tab_widget.mapToGlobal(pos))

    def _close_all_tabs(self) -> None:
        while self.tab_widget.count() > 0:
            self._close_tab(0)

    # --- Refresh ---------------------------------------------------------------------

    def refresh_current_tab(self) -> None:
        tab = self.tab_widget.currentWidget()
        if tab is None:
            return  # no tabs open
        tab.refresh()  # FileTab.refresh() shows its own error dialog on failure
        self._update_sidebar_entry(tab)
        self.statusBar().showMessage(f"Refreshed '{tab.tab_label()}'", 4000)

    def refresh_all_tabs(self) -> None:
        """Reload every open tab from disk. Continues past individual failures
        (e.g. one file moved or locked) and reports them together at the end,
        rather than stopping at the first error."""
        if self.tab_widget.count() == 0:
            self.statusBar().showMessage("No tabs open to refresh", 4000)
            return

        errors: list[str] = []
        succeeded = 0
        for tab in list(self.open_tabs.values()):
            try:
                tab.reload_from_disk()
            except ExcelLoadError as exc:
                errors.append(f"{os.path.basename(tab.file_path)} [{tab.sheet_name}]:\n{exc}")
            else:
                succeeded += 1
                self._update_sidebar_entry(tab)

        if errors:
            QMessageBox.warning(
                self,
                "Some Files Could Not Be Refreshed",
                "\n\n".join(errors),
            )
        self.statusBar().showMessage(
            f"Refreshed {succeeded} of {succeeded + len(errors)} tabs", 5000
        )

    # --- Cross-tab global search (Step 7) -------------------------------------------

    def _build_global_search(self) -> None:
        self.global_search_edit = QLineEdit()
        self.global_search_edit.setPlaceholderText("Search across all open tabs...")
        self.global_search_edit.returnPressed.connect(self.run_global_search)

        search_btn = QPushButton("Search All Tabs")
        search_btn.clicked.connect(lambda _checked=False: self.run_global_search())

        search_bar = QWidget()
        search_bar.setLayout(QHBoxLayout())
        search_bar.layout().setContentsMargins(0, 0, 0, 0)
        search_bar.layout().addWidget(self.global_search_edit)
        search_bar.layout().addWidget(search_btn)
        self.global_search_bar_widget = search_bar

        self.global_results_tree = QTreeWidget()
        self.global_results_tree.setHeaderLabels(["Search Results"])
        self.global_results_tree.itemClicked.connect(self._on_global_result_clicked)

        dock = QDockWidget("Cross-Tab Search", self)
        dock.setObjectName("crossTabSearchDock")
        dock.setWidget(self.global_results_tree)
        dock.setFeatures(
            QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
            | QDockWidget.DockWidgetClosable
        )
        dock.setTitleBarWidget(DockTitleBar(dock))
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        # Hidden until there are results to show (run_global_search opens it),
        # so it doesn't take a third of a small screen's width up front.
        dock.hide()
        self.global_search_dock = dock

    # --- Cell preview ------------------------------------------------------------------

    def _build_cell_preview(self) -> None:
        """A dock showing the current cell's full value, wrapped and selectable —
        the grid itself can only show a long value elided to its column width."""
        self.cell_preview_title = QLabel()
        self.cell_preview_title.setWordWrap(True)
        self.cell_preview_title.setStyleSheet("font-weight: 600;")
        self.cell_preview_text = QPlainTextEdit()
        self.cell_preview_text.setReadOnly(True)
        self.cell_preview_text.setPlaceholderText("Select a cell to see its full value here.")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.cell_preview_title)
        layout.addWidget(self.cell_preview_text)

        dock = QDockWidget("Cell Preview", self)
        dock.setObjectName("cellPreviewDock")
        dock.setWidget(container)
        dock.setFeatures(
            QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
            | QDockWidget.DockWidgetClosable
        )
        dock.setTitleBarWidget(DockTitleBar(dock))
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        dock.hide()  # opt-in via View > Cell Preview (F3)
        self.cell_preview_dock = dock

    def _set_cell_preview(self, title: str, text: str) -> None:
        self.cell_preview_title.setText(title)
        self.cell_preview_text.setPlainText(text)

    def _on_tab_cell_changed(self, tab: FileTab, title: str, text: str) -> None:
        if tab is self.tab_widget.currentWidget():
            self._set_cell_preview(title, text)

    def run_global_search(self) -> None:
        text = self.global_search_edit.text().strip()
        self.global_results_tree.clear()

        if not text:
            return

        if self.tab_widget.count() == 0:
            placeholder = QTreeWidgetItem(["Open a file first."])
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.global_results_tree.addTopLevelItem(placeholder)
            return

        total_matches = 0
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            full_df = tab.model._full_df  # search the whole file, ignoring this tab's own filters
            mask = compile_quick_search(full_df, None, text)
            matched_positions = mask.to_numpy().nonzero()[0]  # 0-based positions, matching table row order
            if len(matched_positions) == 0:
                continue

            total_matches += len(matched_positions)
            match_word = "match" if len(matched_positions) == 1 else "matches"
            file_node = QTreeWidgetItem([f"{tab.tab_label()} — {len(matched_positions)} {match_word}"])
            file_node.setFlags(Qt.ItemFlag.ItemIsEnabled)  # header row, not itself clickable

            shown = matched_positions[:MAX_GLOBAL_RESULTS_PER_TAB]
            preview_columns = list(full_df.columns[:3])
            for pos in shown:
                row = full_df.iloc[pos]
                row_label = full_df.index[pos]  # the actual pandas index label, used for row lookup on click
                preview = ", ".join(f"{_preview_value(c)}: {_preview_value(row[c])}" for c in preview_columns)
                # +1 so this matches the 1-indexed row numbers shown in the table itself
                # (position, not the raw pandas index label, which could differ after filtering elsewhere).
                child = QTreeWidgetItem([f"Row {pos + 1}: {preview}"])
                child.setData(0, Qt.UserRole, (tab.key, int(row_label)))
                file_node.addChild(child)

            if len(matched_positions) > MAX_GLOBAL_RESULTS_PER_TAB:
                more = QTreeWidgetItem(
                    [f"... and {len(matched_positions) - MAX_GLOBAL_RESULTS_PER_TAB} more"]
                )
                more.setFlags(Qt.ItemFlag.NoItemFlags)
                file_node.addChild(more)

            self.global_results_tree.addTopLevelItem(file_node)
            file_node.setExpanded(True)

        if total_matches == 0:
            no_match = QTreeWidgetItem([f"No matches found for '{text}'."])
            no_match.setFlags(Qt.ItemFlag.NoItemFlags)
            self.global_results_tree.addTopLevelItem(no_match)
            self.statusBar().showMessage(f"No matches found for '{text}'", 4000)
        else:
            tabs_with_matches = self.global_results_tree.topLevelItemCount()
            self.statusBar().showMessage(
                f"Found {total_matches} match(es) across {tabs_with_matches} tab(s)", 5000
            )

        if not self.global_search_dock.isVisible():
            self.global_search_dock.setVisible(True)

    def _on_global_result_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        data = item.data(0, Qt.UserRole)
        if data is None:
            return  # a header/placeholder row was clicked, not an actual result

        tab_key, row_idx = data
        tab = self.open_tabs.get(tab_key)
        if tab is None:
            return  # the tab was closed since this search was run

        self.tab_widget.setCurrentWidget(tab)

        # The match is guaranteed to exist in the full data, but this tab's own
        # filters might currently be hiding it — clear them so the whole point
        # of a cross-tab search (finding data regardless of per-tab filters)
        # actually results in a visible row, not a jump to nothing.
        if row_idx not in tab.model._view_df.index:
            tab.filter_bar.set_quick_search(None, "")
            tab.filter_bar.clear_conditions()  # this also triggers apply_filters()

        # Only one row highlighted at a time — clear whichever tab had the
        # previous mark (which may be this same tab or a different one).
        if self._highlighted_tab is not None and self._highlighted_tab is not tab:
            self._highlighted_tab.set_highlighted_row(None)

        if row_idx in tab.model._view_df.index:
            position = tab.model._view_df.index.get_loc(row_idx)
            tab.set_highlighted_row(position)
            self._highlighted_tab = tab

    # --- Error display -------------------------------------------------------------

    def _show_load_error(self, exc: ExcelLoadError) -> None:
        QMessageBox.critical(self, "Could Not Load File", str(exc))

    # --- Profiles (Step 6) -----------------------------------------------------------

    def _build_profiles_menu(self) -> None:
        self.profiles_menu = self.menuBar().addMenu("&Profiles")

        save_action = QAction("Save Profile As...", self)
        save_action.triggered.connect(self.save_profile_as)
        self.profiles_menu.addAction(save_action)
        self.profiles_menu.addSeparator()

        # Create the "Open Profile" submenu widget ONCE and keep it alive for
        # the app's lifetime. Only its list of profile QActions is cleared and
        # rebuilt each time the menu opens — the QMenu widget itself is never
        # destroyed and recreated. (Repeatedly destroying/recreating a QMenu
        # widget on every open is unnecessary churn, and can trip a rare
        # PySide/shiboken edge case where a freshly created widget reuses the
        # same underlying C++ memory address as one just destroyed.)
        self.open_profile_submenu = self.profiles_menu.addMenu("Open Profile")

        self.profiles_menu.addSeparator()

        self.rename_profile_action = QAction("Rename Profile...", self)
        self.rename_profile_action.triggered.connect(self.rename_profile_dialog)
        self.profiles_menu.addAction(self.rename_profile_action)

        self.duplicate_profile_action = QAction("Duplicate Profile...", self)
        self.duplicate_profile_action.triggered.connect(self.duplicate_profile_dialog)
        self.profiles_menu.addAction(self.duplicate_profile_action)

        self.delete_profile_action = QAction("Delete Profile...", self)
        self.delete_profile_action.triggered.connect(self.delete_profile_dialog)
        self.profiles_menu.addAction(self.delete_profile_action)

        # Refreshed every time the menu is opened, so it always reflects the
        # current list of saved profiles.
        self.profiles_menu.aboutToShow.connect(self._refresh_profiles_menu)

    def _refresh_profiles_menu(self) -> None:
        """Refresh only the dynamic parts of the Profiles menu (the list of
        saved profiles, and whether Rename/Duplicate/Delete are enabled) —
        never destroys or recreates any QMenu widget, only QAction leaf items."""
        names = profile_manager.list_profiles()

        self.open_profile_submenu.clear()
        if not names:
            empty_action = QAction("(No saved profiles)", self)
            empty_action.setEnabled(False)
            self.open_profile_submenu.addAction(empty_action)
        else:
            for name in names:
                action = QAction(name, self)
                action.triggered.connect(lambda checked=False, n=name: self.load_profile_by_name(n))
                self.open_profile_submenu.addAction(action)

        self.rename_profile_action.setEnabled(bool(names))
        self.duplicate_profile_action.setEnabled(bool(names))
        self.delete_profile_action.setEnabled(bool(names))

    def _collect_current_state(self) -> dict:
        """Build the saveable state for every currently open tab, in tab order."""
        files = []
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            files.append(tab.get_saved_state())
        return {"files": files}

    def save_profile_as(self) -> None:
        if self.tab_widget.count() == 0:
            QMessageBox.information(self, "Nothing to Save", "Open at least one file before saving a profile.")
            return

        name, ok = QInputDialog.getText(self, "Save Profile As", "Profile name:")
        if not ok:
            return
        name = name.strip()
        if not name:
            return

        if profile_manager.profile_exists(name):
            reply = QMessageBox.question(
                self,
                "Overwrite Profile?",
                f"A profile named '{name}' already exists. Overwrite it?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        try:
            profile_manager.save_profile(name, self._collect_current_state())
        except ProfileError as exc:
            QMessageBox.critical(self, "Could Not Save Profile", str(exc))
            return

        self.statusBar().showMessage(f"Profile '{name}' saved", 4000)
        QMessageBox.information(self, "Profile Saved", f"Profile '{name}' saved.")

    def load_profile_by_name(self, name: str) -> None:
        try:
            state = profile_manager.load_profile(name)
        except ProfileError as exc:
            QMessageBox.critical(self, "Could Not Load Profile", str(exc))
            return

        opened = 0
        for entry in state.get("files", []):
            path = entry.get("path", "")
            sheet_name = entry.get("sheet_name", "")

            if not os.path.exists(path):
                reply = QMessageBox.question(
                    self,
                    "File Not Found",
                    f"'{path}' could not be found.\nWould you like to locate it manually?",
                    QMessageBox.Yes | QMessageBox.No,
                )
                if reply != QMessageBox.Yes:
                    continue
                new_path, _ = QFileDialog.getOpenFileName(
                    self,
                    f"Locate '{os.path.basename(path)}'",
                    "",
                    "Excel Files (*.xlsx *.xlsm *.xls);;All Files (*)",
                )
                if not new_path:
                    continue
                path = new_path

            if (path, sheet_name) in self.open_tabs:
                self.tab_widget.setCurrentWidget(self.open_tabs[(path, sheet_name)])
                continue  # already open — don't duplicate the tab

            self._open_sheet_tab(
                path, sheet_name, header_row=entry.get("header_row", 0), saved_state=entry
            )
            opened += 1

        self.statusBar().showMessage(f"Profile '{name}' loaded — {opened} file(s) opened", 5000)

    def _pick_existing_profile(self, title: str, label: str) -> str | None:
        names = profile_manager.list_profiles()
        if not names:
            return None
        name, ok = QInputDialog.getItem(self, title, label, names, 0, False)
        if not ok or not name:
            return None
        return name

    def rename_profile_dialog(self) -> None:
        old_name = self._pick_existing_profile("Rename Profile", "Choose a profile to rename:")
        if not old_name:
            return
        new_name, ok = QInputDialog.getText(self, "Rename Profile", "New name:", text=old_name)
        if not ok or not new_name.strip():
            return
        try:
            profile_manager.rename_profile(old_name, new_name.strip())
        except ProfileError as exc:
            QMessageBox.critical(self, "Could Not Rename Profile", str(exc))

    def duplicate_profile_dialog(self) -> None:
        name = self._pick_existing_profile("Duplicate Profile", "Choose a profile to duplicate:")
        if not name:
            return
        new_name, ok = QInputDialog.getText(self, "Duplicate Profile", "New profile name:", text=f"{name} copy")
        if not ok or not new_name.strip():
            return
        try:
            profile_manager.duplicate_profile(name, new_name.strip())
        except ProfileError as exc:
            QMessageBox.critical(self, "Could Not Duplicate Profile", str(exc))

    def delete_profile_dialog(self) -> None:
        name = self._pick_existing_profile("Delete Profile", "Choose a profile to delete:")
        if not name:
            return
        reply = QMessageBox.question(
            self,
            "Delete Profile?",
            f"Delete profile '{name}'? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            profile_manager.delete_profile(name)
        except ProfileError as exc:
            QMessageBox.critical(self, "Could Not Delete Profile", str(exc))
