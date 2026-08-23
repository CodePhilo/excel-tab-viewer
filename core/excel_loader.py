"""
core/excel_loader.py

Pure, UI-free functions for reading Excel files. All pandas/openpyxl
error handling is centralized here so the UI layer only ever needs to
catch a single exception type: ExcelLoadError.
"""

from __future__ import annotations

import os
import pandas as pd


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
        xls = pd.ExcelFile(path, engine="openpyxl" if path.lower().endswith(("xlsx", "xlsm")) else None)
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


def load_sheet(path: str, sheet_name: str, header_row: int = 0) -> pd.DataFrame:
    """
    Load a single sheet into a DataFrame. `header_row` is 0-indexed (row 0 =
    the sheet's first row, matching pandas' `header=` convention) and tells
    pandas which row holds the column names — everything above it (title
    rows, blank rows, etc.) is discarded, everything below becomes data.
    Defaults to 0 (the first row), matching the previous fixed behavior.
    Raises ExcelLoadError with a friendly message on failure.
    """
    if not os.path.exists(path):
        raise ExcelLoadError(f"File not found:\n{path}")

    try:
        engine = "openpyxl" if path.lower().endswith(("xlsx", "xlsm")) else None
        df = pd.read_excel(path, sheet_name=sheet_name, header=header_row, engine=engine)
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
    at all (header=None), so every row — including a would-be header row —
    comes back as plain data. Used to let the user preview a sheet and pick
    which row is actually the header (Step: header-row selector).
    """
    if not os.path.exists(path):
        raise ExcelLoadError(f"File not found:\n{path}")

    try:
        engine = "openpyxl" if path.lower().endswith(("xlsx", "xlsm")) else None
        df = pd.read_excel(path, sheet_name=sheet_name, header=None, nrows=n_rows, engine=engine)
        df.columns = [str(c) for c in df.columns]
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
