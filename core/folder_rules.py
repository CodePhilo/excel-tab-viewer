"""
core/folder_rules.py

A folder rule opens every Excel file in a folder whose name matches a set
of conditions ("begins with Sales_", "ends with 2026", ...). Rules are
stored in profiles, and re-checked each time the profile is loaded (and
on Refresh All), so files added to the folder later — e.g. a new daily
report — open automatically without editing the profile.

A rule's JSON shape (inside a profile's "folder_rules" list):
{
  "folder": "C:\\Reports",
  "include_subfolders": false,
  "match_all": true,                  # false = any one condition is enough
  "criteria": [{"kind": "begins", "text": "Sales_"}],
  "sheets": "first",                  # "first" | "all" | "named"
  "sheet_names": [],                  # used when sheets == "named"
  "header_row": 0,                    # 0-indexed, as in load_sheet()
  "tab_states": [ ...FileTab.get_saved_state() of its open tabs... ]
}
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field

EXCEL_EXTENSIONS = (".xlsx", ".xlsm", ".xls")

CRITERIA_LABELS = {
    "begins": "Begins with",
    "ends": "Ends with",
    "contains": "Contains",
    "not_contains": "Does not contain",
    "wildcard": "Matches pattern (* ?)",
}

SHEET_MODES = {
    "first": "First sheet",
    "all": "All sheets",
    "named": "Sheets named",
}


def _criterion_matches(kind: str, text: str, name: str) -> bool:
    """Case-insensitive test of one condition against a file name. Tried
    against the name both with and without its extension, so "ends with
    2026" matches "Sales 2026.xlsx" and "ends with .xlsm" works too."""
    text = text.lower()
    stem = os.path.splitext(name)[0]
    candidates = (name, stem)
    if kind == "begins":
        return name.startswith(text)
    if kind == "ends":
        return any(c.endswith(text) for c in candidates)
    if kind == "contains":
        return text in name
    if kind == "not_contains":
        return text not in name
    if kind == "wildcard":
        return any(fnmatch.fnmatchcase(c, text) for c in candidates)
    return False


@dataclass
class FolderRule:
    folder: str
    criteria: list[tuple[str, str]] = field(default_factory=list)  # (kind, text)
    match_all: bool = True
    include_subfolders: bool = False
    sheets: str = "first"
    sheet_names: list[str] = field(default_factory=list)
    header_row: int = 0
    # Session-only, never saved: (path, sheet) tabs of this rule the user
    # closed, so Refresh All doesn't keep reopening them.
    dismissed: set = field(default_factory=set, compare=False, repr=False)

    def matches(self, file_name: str) -> bool:
        name = file_name.lower()
        if not name.endswith(EXCEL_EXTENSIONS) or name.startswith("~$"):
            return False  # "~$Book.xlsx" is Excel's lock file for an open workbook
        results = [_criterion_matches(kind, text, name) for kind, text in self.criteria if text]
        if not results:
            return True  # no conditions: every Excel file in the folder
        return all(results) if self.match_all else any(results)

    def find_files(self) -> list[str]:
        """Full paths of the matching files, sorted by name. Raises OSError
        if the folder can't be read."""
        if not os.path.isdir(self.folder):
            raise FileNotFoundError(f"Folder not found: {self.folder}")
        found: list[str] = []
        if self.include_subfolders:
            for root, _dirs, files in os.walk(self.folder):
                found.extend(os.path.join(root, f) for f in files if self.matches(f))
        else:
            with os.scandir(self.folder) as entries:
                found.extend(e.path for e in entries if e.is_file() and self.matches(e.name))
        return sorted(found, key=lambda p: os.path.relpath(p, self.folder).lower())

    def pick_sheets(self, sheet_names: list[str]) -> list[str]:
        """Which of a matched file's sheets this rule opens."""
        if self.sheets == "all":
            return list(sheet_names)
        if self.sheets == "named":
            wanted = {n.strip().lower() for n in self.sheet_names if n.strip()}
            return [s for s in sheet_names if s.lower() in wanted]
        return sheet_names[:1]

    def describe(self) -> str:
        """One line for lists and menus, e.g. 'C:\\Reports — begins with "Sales_"'."""
        parts = [
            f'{CRITERIA_LABELS.get(kind, kind).lower()} "{text}"'
            for kind, text in self.criteria if text
        ]
        joiner = " and " if self.match_all else " or "
        conditions = joiner.join(parts) if parts else "all Excel files"
        subfolders = " (with subfolders)" if self.include_subfolders else ""
        return f"{self.folder}{subfolders} — {conditions}"

    def to_dict(self) -> dict:
        return {
            "folder": self.folder,
            "include_subfolders": self.include_subfolders,
            "match_all": self.match_all,
            "criteria": [{"kind": kind, "text": text} for kind, text in self.criteria],
            "sheets": self.sheets,
            "sheet_names": list(self.sheet_names),
            "header_row": self.header_row,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FolderRule":
        sheets = d.get("sheets", "first")
        return cls(
            folder=d.get("folder", ""),
            criteria=[
                (c.get("kind", "contains"), c.get("text", ""))
                for c in d.get("criteria", [])
                if c.get("kind") in CRITERIA_LABELS
            ],
            match_all=bool(d.get("match_all", True)),
            include_subfolders=bool(d.get("include_subfolders", False)),
            sheets=sheets if sheets in SHEET_MODES else "first",
            sheet_names=list(d.get("sheet_names", [])),
            header_row=int(d.get("header_row", 0)),
        )
