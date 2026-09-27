"""
core/excel_loader.py

Pure, UI-free functions for reading Excel files. All pandas/openpyxl
error handling is centralized here so the UI layer only ever needs to
catch a single exception type: ExcelLoadError.
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd
from pandas.errors import EmptyDataError
from pandas.io.parsers import TextParser


class ExcelLoadError(Exception):
    """Raised for any problem loading an Excel file, with a user-friendly message."""


def _friendly_path(path: str) -> str:
    return os.path.basename(path)


def list_sheet_names(path: str) -> list[str]:
    """
    Return the list of sheet names in the given workbook, without loading
    full sheet data. Raises ExcelLoadError with a friendly message on failure.
    """
    if not os.path.exists(path):
        raise ExcelLoadError(f"File not found:\n{path}")

    try:
        # read_only mode (used internally by pandas' openpyxl reader) keeps a live
        # handle on the file for lazy access. We close it explicitly the moment
        # we're done, rather than relying on garbage-collection timing — otherwise
        # the lingering handle can cause a Windows "sharing violation" if the file
        # is also open in Excel and the user tries to save there.
        xls = pd.ExcelFile(path, engine="openpyxl" if _uses_openpyxl(path) else None)
        try:
            return xls.sheet_names
        finally:
            xls.close()
    except PermissionError:
        raise ExcelLoadError(
            f"'{_friendly_path(path)}' could not be opened.\n"
            "It may be currently open and locked in Excel. Close it and try again."
        )
    except Exception as exc:
        raise ExcelLoadError(
            f"Could not read '{_friendly_path(path)}'.\n"
            f"The file may be corrupted or in an unsupported format.\n\nDetails: {exc}"
        )


# Passed to every read_excel() call. By default pandas re-parses text cells
# as if they came from a CSV: a text column holding "0044", "+0044123" or
# "00012" silently becomes the integers 44 / 44123 / 12, and text such as
# "N/A", "NA", "null" or "None" becomes an empty cell. dtype=object keeps
# every cell exactly as openpyxl/xlrd returned it (text stays text, real
# numbers stay numbers), and only genuinely blank cells count as missing.
_READ_OPTIONS = dict(dtype=object, keep_default_na=False, na_values=[""])


def _uses_openpyxl(path: str) -> bool:
    return path.lower().endswith(("xlsx", "xlsm"))


def _column_letter(index: int) -> str:
    """0-indexed column position -> Excel column letters (0 -> A, 26 -> AA)."""
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def _read_sparse_rows(path: str, sheet_name: str, max_rows: int | None = None) -> list[dict[int, object]]:
    """
    Read an .xlsx/.xlsm sheet as one {column position: value} dict per row,
    holding only the cells that actually have a value (trailing empty rows
    dropped). pandas' own reader pads every row out to the sheet's right-most
    used cell, so a single stray value in column XFD turned a 5-column sheet
    into 16,384 columns of blanks — minutes of loading and a frozen window.
    Cell values are converted exactly as pandas' openpyxl reader does.
    """
    from openpyxl import load_workbook
    from openpyxl.cell.cell import TYPE_ERROR, TYPE_NUMERIC

    wb = load_workbook(path, read_only=True, data_only=True, keep_links=False)
    try:
        if sheet_name not in wb.sheetnames:
            raise ValueError(f"Worksheet named '{sheet_name}' not found")
        ws = wb[sheet_name]
        # The sheet's stored dimensions are often wrong (or huge because of
        # formatting); without them each row only reaches its own last cell.
        ws.reset_dimensions()
        rows: list[dict[int, object]] = []
        for row in ws.rows:
            cells: dict[int, object] = {}
            for cell in row:
                value = cell.value
                if value is None or value == "" or cell.data_type == TYPE_ERROR:
                    continue  # pandas reads error cells (#N/A, #REF!, ...) as blank too
                if cell.data_type == TYPE_NUMERIC:
                    as_int = int(value)
                    value = as_int if as_int == value else float(value)
                cells[cell.column - 1] = value
            rows.append(cells)
            if max_rows is not None and len(rows) >= max_rows:
                break
    finally:
        wb.close()  # read-only mode keeps the file open until closed

    while rows and not rows[-1]:
        rows.pop()
    return rows


def _used_columns(rows: list[dict[int, object]]) -> list[int]:
    used: set[int] = set()
    for cells in rows:
        used.update(cells)
    return sorted(used)


def _load_sparse_sheet(path: str, sheet_name: str, header_row: int) -> pd.DataFrame:
    rows = _read_sparse_rows(path, sheet_name)
    if not rows:
        return pd.DataFrame()
    if header_row >= len(rows):
        raise ValueError(f"the sheet only has {len(rows)} rows")
    # Keep only columns with a header or at least one value; rows above the
    # header are discarded anyway, so they don't count.
    columns = _used_columns(rows[header_row:])
    data = [[cells.get(c, "") for c in columns] for cells in rows]
    try:
        # The same parser pd.read_excel() hands a sheet's cells to.
        return TextParser(data, header=header_row, skip_blank_lines=False, **_READ_OPTIONS).read()
    except EmptyDataError:
        return pd.DataFrame()


def _drop_blank_unnamed_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Drop columns with no header and no values (pandas names them 'Unnamed: N')."""
    blank = [c for c in df.columns if str(c).startswith("Unnamed: ") and df[c].isna().all()]
    return df.drop(columns=blank) if blank else df


def load_sheet(path: str, sheet_name: str, header_row: int = 0) -> pd.DataFrame:
    """
    Load a single sheet into a DataFrame. `header_row` is 0-indexed (row 0 =
    the sheet's first row, matching pandas' `header=` convention) and tells
    pandas which row holds the column names — everything above it (title
    rows, blank rows, etc.) is discarded, everything below becomes data.
    Columns with neither a header nor any value are left out, however far
    apart the used columns are in the sheet.
    Raises ExcelLoadError with a friendly message on failure.
    """
    if not os.path.exists(path):
        raise ExcelLoadError(f"File not found:\n{path}")

    try:
        if _uses_openpyxl(path):
            df = _load_sparse_sheet(path, sheet_name, header_row)
        else:
            # .xls sheets are at most 256 columns wide, so pandas' reader is fine.
            df = pd.read_excel(path, sheet_name=sheet_name, header=header_row, **_READ_OPTIONS)
            df = _drop_blank_unnamed_columns(df)
        # Give columns whose cells were real numbers/dates in Excel a proper
        # numeric/datetime dtype again (so >=, <=, between compare correctly).
        # A column containing any text cell stays text, untouched.
        df = df.infer_objects()
        # Normalize column names to strings (handles stray numeric/blank headers).
        df.columns = [str(c) for c in df.columns]
        return df
    except PermissionError:
        raise ExcelLoadError(
            f"'{_friendly_path(path)}' could not be opened.\n"
            "It may be currently open and locked in Excel. Close it and try again."
        )
    except ValueError as exc:
        # Typically raised when the sheet name no longer exists in the file,
        # or the requested header row is beyond the sheet's actual row count.
        raise ExcelLoadError(
            f"Could not load sheet '{sheet_name}' from '{_friendly_path(path)}' "
            f"with header row {header_row + 1}.\nDetails: {exc}"
        )
    except Exception as exc:
        raise ExcelLoadError(
            f"Could not read sheet '{sheet_name}' from '{_friendly_path(path)}'.\n"
            f"Details: {exc}"
        )


def load_sheet_preview(path: str, sheet_name: str, n_rows: int = 10) -> pd.DataFrame:
    """
    Load the first `n_rows` raw rows of a sheet with no header interpretation
    at all, so every row — including a would-be header row — comes back as
    plain data. Used to let the user preview a sheet and pick which row is
    actually the header (Step: header-row selector). Empty columns are left
    out; the rest are named by their Excel column letter (A, B, ...).
    """
    if not os.path.exists(path):
        raise ExcelLoadError(f"File not found:\n{path}")

    try:
        if _uses_openpyxl(path):
            # One extra row, so blank rows inside the window are kept when
            # the sheet carries on below it (only trailing ones are trimmed).
            rows = _read_sparse_rows(path, sheet_name, max_rows=n_rows + 1)[:n_rows]
            columns = _used_columns(rows)
            df = pd.DataFrame(
                [[cells.get(c, np.nan) for c in columns] for cells in rows],
                columns=[_column_letter(c) for c in columns],
                dtype=object,
            )
        else:
            df = pd.read_excel(path, sheet_name=sheet_name, header=None, nrows=n_rows, **_READ_OPTIONS)
            df = df.dropna(axis=1, how="all")
            df.columns = [_column_letter(c) for c in df.columns]
        return df
    except PermissionError:
        raise ExcelLoadError(
            f"'{_friendly_path(path)}' could not be opened.\n"
            "It may be currently open and locked in Excel. Close it and try again."
        )
    except Exception as exc:
        raise ExcelLoadError(
            f"Could not preview sheet '{sheet_name}' from '{_friendly_path(path)}'.\n"
            f"Details: {exc}"
        )
