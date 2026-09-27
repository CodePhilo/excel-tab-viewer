"""
ui/file_tab.py

FileTab is the widget that lives inside a single QTabWidget tab.

Step 3 adds per-tab column visibility: a "Manage Columns" button opens
a checklist dialog, and unchecked columns are hidden via
QTableView.setColumnHidden() — the underlying DataFrame is never
touched, so hidden columns can be restored instantly and Refresh
(Step 5) can re-apply the same hidden set after a reload.

Filter bar and refresh button are added in later steps.
"""

from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTableView,
    QHeaderView,
    QPushButton,
    QMessageBox,
    QAbstractItemView,
    QStyledItemDelegate,
    QApplication,
    QMenu,
    QFileDialog,
)
from PySide6.QtCore import Qt, Signal, QSettings, QTimer, QUrl
from PySide6.QtGui import QColor, QKeySequence, QShortcut, QDesktopServices
from pandas.api.types import is_datetime64_any_dtype, is_numeric_dtype

from models.table_model import ExcelTableModel
from core.excel_loader import load_sheet, ExcelLoadError
from core.exporter import export_frame, ExportError
from core.selection_summary import summarize
from core.filters import compile_conditions, compile_quick_search, FilterCondition
from ui.column_manager_dialog import ColumnManagerDialog
from ui.elided_label import ElidedLabel
from ui.filter_bar import FilterBar
from ui.row_detail_dialog import RowDetailDialog

MAX_COLUMN_WIDTH = 320  # px; wide cells (e.g. multi-line text) get elided rather than stretching the column
MAX_TAB_LABEL_CHARS = 40  # longer file/sheet names are shortened on the tab itself (full name in its tooltip)
ROW_HIGHLIGHT_COLOR = QColor("#ffe58a")
SELECTION_SUMMARY_DEBOUNCE_MS = 120
EXPORT_DIR_SETTING = "export/last_dir"
INVALID_FILENAME_CHARS = '<>:"/\\|?*'


def _tsv_field(text: str) -> str:
    """Quote a value for tab-separated clipboard text the way Excel does, so a
    cell containing tabs, line breaks, or quotes pastes back as one cell."""
    if any(ch in text for ch in ('\t', '\n', '\r', '"')):
        return '"' + text.replace('"', '""') + '"'
    return text


class _RowHighlightDelegate(QStyledItemDelegate):
    """Paints a persistent background for one marked row (see
    FileTab.set_highlighted_row), independent of normal selection — used to
    keep a cross-tab search match visible even after the user clicks
    elsewhere in the table and selection moves on."""

    def __init__(self, file_tab: "FileTab", parent=None):
        super().__init__(parent)
        self._file_tab = file_tab

    def paint(self, painter, option, index):
        if self._file_tab.highlighted_row == index.row():
            painter.save()
            painter.fillRect(option.rect, ROW_HIGHLIGHT_COLOR)
            painter.restore()
        super().paint(painter, option, index)


class FileTab(QWidget):
    # (title, full text) of the table's current cell, or ("", "") when there is none.
    current_cell_changed = Signal(str, str)
    # Count / Sum / Average / Min / Max of the selected cells, or "".
    selection_summary_changed = Signal(str)

    def __init__(self, file_path: str, sheet_name: str, header_row: int = 0, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.sheet_name = sheet_name
        # 0-indexed row (within the sheet) that holds the column names. Remembered
        # here so Refresh and profile saves reuse the same choice the user made
        # when opening the file, rather than re-defaulting to row 1.
        self.header_row = header_row
        # The FolderRule that opened this tab (set by MainWindow), or None for
        # a file opened directly. Profiles save such tabs under their rule.
        self.folder_rule = None

        # Column names the user has hidden in this tab, by name (not index) so
        # visibility survives a Refresh even if column order/count shifts slightly.
        self.hidden_columns: set[str] = set()

        df = load_sheet(file_path, sheet_name, header_row=header_row)  # raises ExcelLoadError on failure
        self.model = ExcelTableModel(df)

        self.info_label = ElidedLabel()
        self._update_info_label()

        self.manage_columns_btn = QPushButton("Manage Columns...")
        self.manage_columns_btn.clicked.connect(self.open_column_manager)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setToolTip("Reload this file from disk")
        self.refresh_btn.clicked.connect(self.refresh)

        self.export_btn = QPushButton("Export...")
        self.export_btn.setToolTip("Save the rows and columns shown here as a new Excel or CSV file")
        self.export_btn.clicked.connect(self.export_view)

        toolbar_row = QHBoxLayout()
        toolbar_row.addWidget(self.info_label, stretch=1)
        toolbar_row.addWidget(self.refresh_btn)
        toolbar_row.addWidget(self.manage_columns_btn)
        toolbar_row.addWidget(self.export_btn)

        self.filter_bar = FilterBar(df)
        self.filter_bar.filters_changed.connect(self.apply_filters)

        # Position (0-indexed, within the current view) of the one row a
        # cross-tab search result jump should keep visibly marked, or None.
        self.highlighted_row: int | None = None

        self.table_view = QTableView()
        self.table_view.setModel(self.model)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSortingEnabled(False)  # sorting on filtered views comes later
        self.table_view.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table_view.horizontalHeader().setStretchLastSection(False)
        self.table_view.setTextElideMode(Qt.TextElideMode.ElideRight)
        # Headers are centered by default, so a long header name in a capped
        # column was clipped on both sides; left-align and elide it instead
        # (the full name is in the header's tooltip).
        header = self.table_view.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.table_view.setWordWrap(False)
        self.table_view.setItemDelegate(_RowHighlightDelegate(self, self.table_view))
        self.table_view.resizeColumnsToContents()
        self._cap_column_widths()
        # Double-clicking a column divider auto-fits that column to its content,
        # uncapped — a long-text column became tens of thousands of px wide.
        # Qt's own auto-fit is connected first, so this runs right after it.
        self.table_view.horizontalHeader().sectionHandleDoubleClicked.connect(self._cap_column_width)
        self.table_view.doubleClicked.connect(self._show_row_detail)
        self.table_view.selectionModel().currentChanged.connect(self._emit_current_cell)

        # Selections change on every mouse move while dragging; total them
        # once the user pauses rather than on each step.
        self._summary_timer = QTimer(self)
        self._summary_timer.setSingleShot(True)
        self._summary_timer.setInterval(SELECTION_SUMMARY_DEBOUNCE_MS)
        self._summary_timer.timeout.connect(
            lambda: self.selection_summary_changed.emit(self.selection_summary())
        )
        self.table_view.selectionModel().selectionChanged.connect(lambda *_: self._summary_timer.start())

        # Clicking a header selects the column (as in Excel, and so its cells
        # can be totalled); sorting lives in the header's right-click menu.
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_header_context_menu)

        copy_shortcut = QShortcut(QKeySequence.StandardKey.Copy, self.table_view)
        copy_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        copy_shortcut.activated.connect(self.copy_selection)
        self.table_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table_view.customContextMenuRequested.connect(self._show_table_context_menu)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addLayout(toolbar_row)
        layout.addWidget(self.filter_bar)
        layout.addWidget(self.table_view)

    def set_highlighted_row(self, row_position: int | None) -> None:
        """Mark (or clear, if None) one row's background so it stays visibly
        distinct — used to jump to and mark a cross-tab search match. Unlike
        normal selection, this persists even after the user clicks elsewhere
        in the table, until explicitly cleared or the view's rows change."""
        self.highlighted_row = row_position
        self.table_view.viewport().update()
        if row_position is not None:
            model_index = self.model.index(row_position, 0)
            self.table_view.scrollTo(model_index)
            self.table_view.selectRow(row_position)

    def _cap_column_widths(self) -> None:
        """After auto-sizing, clamp any column wider than MAX_COLUMN_WIDTH.
        Content that no longer fits is elided with '...' (via setTextElideMode
        above) rather than stretching the column — this is what actually fixes
        the wide-cell problem; resizeColumnsToContents() alone doesn't cap width."""
        for col_index in range(self.model.columnCount()):
            self._cap_column_width(col_index)

    def _cap_column_width(self, col_index: int) -> None:
        if self.table_view.columnWidth(col_index) > MAX_COLUMN_WIDTH:
            self.table_view.setColumnWidth(col_index, MAX_COLUMN_WIDTH)

    # --- Current cell, copy, context menu -------------------------------------------

    def current_cell_info(self) -> tuple[str, str]:
        """(title, full text) of the table's current cell, for the cell preview panel."""
        index = self.table_view.currentIndex()
        if not index.isValid():
            return ("", "")
        column = str(self.model._view_df.columns[index.column()])
        return (f"{column} — row {index.row() + 1}", self.model.cell_text(index.row(), index.column()))

    def _emit_current_cell(self, *_args) -> None:
        self.current_cell_changed.emit(*self.current_cell_info())

    def copy_selection(self) -> None:
        """Copy the selected cells to the clipboard as tab-separated text (pastes
        straight into Excel), using the full values — not the elided/collapsed
        text drawn in the grid. Hidden columns are skipped."""
        indexes = [
            i for i in self.table_view.selectionModel().selectedIndexes()
            if not self.table_view.isColumnHidden(i.column())
        ]
        if not indexes:
            return
        rows = sorted({i.row() for i in indexes})
        cols = sorted({i.column() for i in indexes})
        selected = {(i.row(), i.column()) for i in indexes}
        lines = []
        for r in rows:
            fields = [_tsv_field(self.model.cell_text(r, c)) if (r, c) in selected else "" for c in cols]
            lines.append("\t".join(fields))
        QApplication.clipboard().setText("\n".join(lines))

    def _show_table_context_menu(self, pos) -> None:
        index = self.table_view.indexAt(pos)
        menu = QMenu(self)
        copy_action = menu.addAction("Copy")
        copy_action.setShortcut(QKeySequence.StandardKey.Copy)
        copy_action.setEnabled(self.table_view.selectionModel().hasSelection())
        copy_action.triggered.connect(self.copy_selection)
        details_action = menu.addAction("Show Row Details...")
        details_action.setEnabled(index.isValid())
        details_action.triggered.connect(lambda _checked=False: self._show_row_detail(index))
        menu.exec(self.table_view.viewport().mapToGlobal(pos))

    # --- Sorting -------------------------------------------------------------------------

    def _show_header_context_menu(self, pos) -> None:
        header = self.table_view.horizontalHeader()
        section = header.logicalIndexAt(pos)
        if section < 0:
            return
        column = str(self.model._view_df.columns[section])
        series = self.model._full_df[column]
        if is_datetime64_any_dtype(series):
            up, down = "Oldest to Newest", "Newest to Oldest"
        elif is_numeric_dtype(series):
            up, down = "Smallest to Largest", "Largest to Smallest"
        else:
            up, down = "A to Z", "Z to A"

        keys = self.model.sort_keys()
        others = [k for k in keys if k[0] != column]
        menu = QMenu(self)
        menu.addAction(f"Sort {up}").triggered.connect(lambda: self.set_sort([(column, True)]))
        menu.addAction(f"Sort {down}").triggered.connect(lambda: self.set_sort([(column, False)]))
        # "Then by" adds this column as a tie-breaker after the current sort.
        then_up = menu.addAction(f"Then by {up}")
        then_up.triggered.connect(lambda: self.set_sort(others + [(column, True)]))
        then_down = menu.addAction(f"Then by {down}")
        then_down.triggered.connect(lambda: self.set_sort(others + [(column, False)]))
        then_up.setEnabled(bool(others))
        then_down.setEnabled(bool(others))
        menu.addSeparator()
        clear = menu.addAction("Clear Sort (file order)")
        clear.setEnabled(bool(keys))
        clear.triggered.connect(lambda: self.set_sort([]))
        menu.exec(header.mapToGlobal(pos))

    def set_sort(self, keys: list[tuple[str, bool]]) -> None:
        self.highlighted_row = None  # row positions are about to change; a stale mark would be wrong
        self.model.set_sort(keys)
        self._fit_sorted_headers()
        self._update_info_label()
        self.apply_column_visibility()  # a model reset can drop column-hidden flags
        self._emit_current_cell()
        self._summary_timer.start()

    def _fit_sorted_headers(self) -> None:
        """Widen sorted columns just enough for their '▲1 Name' header — a
        column sized to short values otherwise showed only '▲1 R…'. Never
        narrows a column, and stays within MAX_COLUMN_WIDTH."""
        metrics = self.table_view.horizontalHeader().fontMetrics()
        names = self.model.column_names()
        for column, _ascending in self.model.sort_keys():
            index = names.index(column)
            text = str(self.model.headerData(index, Qt.Orientation.Horizontal))
            needed = min(metrics.horizontalAdvance(text) + 32, MAX_COLUMN_WIDTH)
            if self.table_view.columnWidth(index) < needed:
                self.table_view.setColumnWidth(index, needed)

    # --- Export ---------------------------------------------------------------------------

    def export_view(self) -> None:
        """Save what's on screen — filtered rows, sort order, visible columns —
        as a new .xlsx or .csv file. The source file is never changed."""
        df = self.model.visible_frame(self.hidden_columns)
        if len(df.columns) == 0:
            QMessageBox.information(self, "Nothing to Export", "All columns are hidden.")
            return

        settings = QSettings()
        folder = settings.value(EXPORT_DIR_SETTING, os.path.dirname(self.file_path))
        stem = os.path.splitext(os.path.basename(self.file_path))[0]
        name = f"{stem} - {self.sheet_name}" + (" (filtered)" if self.model.is_filtered() else "")
        name = "".join("_" if ch in INVALID_FILENAME_CHARS else ch for ch in name)
        path, chosen_filter = QFileDialog.getSaveFileName(
            self,
            "Export Current View",
            os.path.join(folder, name + ".xlsx"),
            "Excel Workbook (*.xlsx);;CSV UTF-8 (*.csv)",
        )
        if not path:
            return
        if not path.lower().endswith((".xlsx", ".csv")):
            path += ".csv" if "csv" in chosen_filter.lower() else ".xlsx"
        settings.setValue(EXPORT_DIR_SETTING, os.path.dirname(path))

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            export_frame(df, path, self.sheet_name)
        except ExportError as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Could Not Export", str(exc))
            return
        QApplication.restoreOverrideCursor()

        reply = QMessageBox.question(
            self,
            "Export Complete",
            f"Saved {len(df):,} rows x {len(df.columns):,} columns to:\n{path}\n\nOpen it now?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # --- Selection summary ---------------------------------------------------------------

    def selection_summary(self) -> str:
        """Count / Sum / Average / Min / Max of the selected cells (hidden
        columns left out), worked out from the selection's rectangles rather
        than cell by cell, so selecting a whole column stays fast."""
        df = self.model._view_df
        blocks = []
        for block in self.table_view.selectionModel().selection():
            cols = [
                c for c in range(block.left(), block.right() + 1)
                if not self.table_view.isColumnHidden(c)
            ]
            if cols:
                blocks.append(df.iloc[block.top(): block.bottom() + 1, cols])
        return summarize(blocks)

    def _show_row_detail(self, index) -> None:
        """Double-click handler: show the full row as a vertical field list,
        using the real (un-elided) values straight from the DataFrame."""
        if not index.isValid():
            return
        row = self.model._view_df.iloc[index.row()]
        row_label = index.row() + 1  # 1-indexed, matching the table's own row numbers
        dialog = RowDetailDialog(row_label, row, self)
        dialog.exec()

    def _update_info_label(self) -> None:
        file_name = os.path.basename(self.file_path)
        total_rows = self.model.row_count_full()
        cols = self.model.column_count_full()
        if self.model.is_filtered():
            visible_rows = self.model.visible_row_count()
            row_text = f"{visible_rows:,} of {total_rows:,} rows"
        else:
            row_text = f"{total_rows:,} rows"
        text = f"{file_name} — sheet '{self.sheet_name}'  ({row_text} x {cols:,} columns)"
        keys = self.model.sort_keys()
        if keys:
            text += "  · sorted by " + ", then ".join(
                f"{col} {'▲' if asc else '▼'}" for col, asc in keys
            )
        self.info_label.setText(text)

    def apply_filters(self) -> None:
        """Recompute the combined quick-search + condition mask and apply it to the model."""
        self.highlighted_row = None  # row positions are about to change; a stale mark would be wrong
        full_df = self.model._full_df  # the unfiltered data; filters always compile against this
        quick_column, quick_text = self.filter_bar.quick_search_state()
        conditions = self.filter_bar.active_conditions()

        if not quick_text and not conditions:
            self.model.clear_filter()
        else:
            mask = compile_quick_search(self.model.text_frame(), quick_column, quick_text)
            if conditions:
                mask &= compile_conditions(full_df, conditions)
            self.model.apply_filter(mask)

        self._update_info_label()
        # Re-apply column visibility since beginResetModel/endResetModel from the
        # filter can reset column-hidden flags on some Qt versions.
        self.apply_column_visibility()
        self._emit_current_cell()  # the model reset cleared the current cell
        self._summary_timer.start()  # ... and the selection

    def open_column_manager(self) -> None:
        dialog = ColumnManagerDialog(self.model.column_names(), self.hidden_columns, self)
        if dialog.exec() == dialog.DialogCode.Accepted:
            self.hidden_columns = dialog.hidden_columns()
            self.apply_column_visibility()

    def apply_column_visibility(self) -> None:
        """Hide/show columns in the table view to match self.hidden_columns.
        Never modifies the underlying DataFrame."""
        for col_index, name in enumerate(self.model.column_names()):
            self.table_view.setColumnHidden(col_index, name in self.hidden_columns)

    def reload_from_disk(self) -> None:
        """
        Re-read the file+sheet from disk and refresh the table. Raises
        ExcelLoadError on failure (e.g. file moved/deleted/locked) — the
        caller decides how to surface that (see refresh() below, and
        MainWindow.refresh_all_tabs() for the bulk version).
        """
        df = load_sheet(self.file_path, self.sheet_name, header_row=self.header_row)  # raises ExcelLoadError on failure
        self.highlighted_row = None  # row positions are about to change; a stale mark would be wrong
        self.model.set_dataframe(df)
        self._update_info_label()

        # Drop any hidden-column names that no longer exist in the reloaded data,
        # then re-apply visibility so the view reflects the (possibly changed) columns.
        current_columns = set(self.model.column_names())
        self.hidden_columns = self.hidden_columns & current_columns
        self.apply_column_visibility()

        # Refresh the filter bar's column/value choices against the new data, then
        # recompute the existing quick-search/condition filters against it, so a
        # Refresh doesn't silently drop the filters the user already had applied.
        self.filter_bar.update_dataframe(df)
        self.apply_filters()

    def refresh(self) -> None:
        """Per-tab Refresh button handler: reload from disk, showing a friendly
        error dialog (and keeping the last-good data on screen) if it fails."""
        try:
            self.reload_from_disk()
        except ExcelLoadError as exc:
            QMessageBox.warning(self, "Could Not Refresh", str(exc))

    def tab_label(self) -> str:
        """Full "file [sheet]" name, used in messages and search results."""
        base = os.path.splitext(os.path.basename(self.file_path))[0]
        return f"{base} [{self.sheet_name}]"

    def short_tab_label(self) -> str:
        """Text shown on the QTabWidget tab itself — shortened so one long
        name can't fill the whole tab bar (the full name is the tab's tooltip)."""
        label = self.tab_label()
        if len(label) <= MAX_TAB_LABEL_CHARS:
            return label
        keep = MAX_TAB_LABEL_CHARS - 1
        return label[: keep - keep // 3] + "…" + label[-(keep // 3):]

    @property
    def key(self) -> tuple[str, str]:
        """Uniquely identifies this (file, sheet) combination, used to prevent
        opening the same sheet twice and to look up the tab in the sidebar tree."""
        return (self.file_path, self.sheet_name)

    # --- Profile support (Step 6) ----------------------------------------------------

    def get_saved_state(self) -> dict:
        """Serialize this tab's per-file settings (not the data itself) for
        storing in a profile: path, sheet, hidden columns, and filters."""
        quick_column, quick_text = self.filter_bar.quick_search_state()
        conditions = [cond.to_dict() for cond in self.filter_bar.active_conditions()]
        return {
            "path": self.file_path,
            "sheet_name": self.sheet_name,
            "header_row": self.header_row,
            "hidden_columns": sorted(self.hidden_columns),
            "quick_search_column": quick_column,
            "quick_search_text": quick_text,
            "conditions": conditions,
            "sort": [[col, asc] for col, asc in self.model.sort_keys()],
        }

    def apply_saved_state(self, state: dict) -> None:
        """Restore hidden columns and filters from a saved profile entry.
        Assumes the tab was just created from the same (path, sheet) the
        state was saved for; columns/values no longer present are skipped
        gracefully rather than raising."""
        current_columns = set(self.model.column_names())
        self.hidden_columns = set(state.get("hidden_columns", [])) & current_columns
        self.apply_column_visibility()

        self.filter_bar.set_quick_search(
            state.get("quick_search_column"), state.get("quick_search_text", "")
        )
        conditions = [FilterCondition.from_dict(d) for d in state.get("conditions", [])]
        self.filter_bar.set_conditions(conditions)

        self.set_sort([(col, bool(asc)) for col, asc in state.get("sort", [])])

        self.apply_filters()
