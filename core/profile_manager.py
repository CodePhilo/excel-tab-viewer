"""
core/profile_manager.py

Profiles are stored as individual JSON files under an app-data folder
(%APPDATA%/ExcelTabViewer/profiles on Windows). JSON was chosen over
SQLite here: profiles are small, human-inspectable/debuggable, and
there's no need for relational queries across them — each profile is
just "the set of files + per-file sheet/column/filter state".

A profile's JSON shape:
{
  "files": [
    {
      "path": "C:\\...\\Products.xlsx",
      "sheet_name": "Sheet1",
      "hidden_columns": ["Internal Notes"],
      "quick_search_column": null,        # null means "All Columns"
      "quick_search_text": "",
      "conditions": [
        {"column": "Category", "operator": "equals", "value": "Electronics", "value2": null}
      ]
    },
    ...
  ]
}
"""

from __future__ import annotations

import json
import os
import shutil
import sys

INVALID_NAME_CHARS = set('/\\:*?"<>|')


class ProfileError(Exception):
    """Raised for any problem creating, reading, or modifying a profile."""


def get_app_data_dir() -> str:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        # Non-Windows fallback, useful for development/testing this app on
        # macOS/Linux even though the shipped target platform is Windows.
        base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    app_dir = os.path.join(base, "ExcelTabViewer")
    os.makedirs(app_dir, exist_ok=True)
    return app_dir


def get_profiles_dir() -> str:
    d = os.path.join(get_app_data_dir(), "profiles")
    os.makedirs(d, exist_ok=True)
    return d


def _validate_name(name: str) -> str:
    if not name or not name.strip():
        raise ProfileError("Profile name cannot be empty.")
    name = name.strip()
    if any(ch in INVALID_NAME_CHARS for ch in name):
        raise ProfileError('Profile name cannot contain any of: / \\ : * ? " < > |')
    return name


def _profile_path(name: str) -> str:
    return os.path.join(get_profiles_dir(), f"{name}.json")


def list_profiles() -> list[str]:
    d = get_profiles_dir()
    names = [fname[:-5] for fname in os.listdir(d) if fname.lower().endswith(".json")]
    return sorted(names, key=str.lower)


def profile_exists(name: str) -> bool:
    name = _validate_name(name)
    return os.path.isfile(_profile_path(name))


def save_profile(name: str, state: dict) -> None:
    name = _validate_name(name)
    try:
        with open(_profile_path(name), "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except OSError as exc:
        raise ProfileError(f"Could not save profile '{name}': {exc}")


def load_profile(name: str) -> dict:
    name = _validate_name(name)
    path = _profile_path(name)
    if not os.path.isfile(path):
        raise ProfileError(f"Profile '{name}' does not exist.")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise ProfileError(f"Could not read profile '{name}': {exc}")


def delete_profile(name: str) -> None:
    name = _validate_name(name)
    path = _profile_path(name)
    if not os.path.isfile(path):
        raise ProfileError(f"Profile '{name}' does not exist.")
    try:
        os.remove(path)
    except OSError as exc:
        raise ProfileError(f"Could not delete profile '{name}': {exc}")


def rename_profile(old_name: str, new_name: str) -> None:
    old_name = _validate_name(old_name)
    new_name = _validate_name(new_name)
    old_path = _profile_path(old_name)
    new_path = _profile_path(new_name)
    if not os.path.isfile(old_path):
        raise ProfileError(f"Profile '{old_name}' does not exist.")
    if os.path.isfile(new_path):
        raise ProfileError(f"A profile named '{new_name}' already exists.")
    try:
        os.rename(old_path, new_path)
    except OSError as exc:
        raise ProfileError(f"Could not rename profile: {exc}")


def duplicate_profile(name: str, new_name: str) -> None:
    name = _validate_name(name)
    new_name = _validate_name(new_name)
    src_path = _profile_path(name)
    dst_path = _profile_path(new_name)
    if not os.path.isfile(src_path):
        raise ProfileError(f"Profile '{name}' does not exist.")
    if os.path.isfile(dst_path):
        raise ProfileError(f"A profile named '{new_name}' already exists.")
    try:
        shutil.copyfile(src_path, dst_path)
    except OSError as exc:
        raise ProfileError(f"Could not duplicate profile: {exc}")
