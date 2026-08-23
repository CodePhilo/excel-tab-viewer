# Packaging Excel Tab Viewer as a Windows .exe

This must be done **on a Windows machine** — PyInstaller does not cross-compile,
so running it on macOS/Linux produces a binary for that OS, not a `.exe`.

## 1. Prerequisites

- Windows 10/11
- Python 3.11+ installed (matches what you've been developing with)
- The project folder, with your virtual environment set up:

```powershell
cd excel-tab-viewer
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

`requirements.txt` now includes `pyinstaller==6.21.0` (current stable, tested
with Python 3.13), so this one `pip install` covers everything.

## 2. Build

From the project root, with `venv` still active:

```powershell
pyinstaller excel_tab_viewer.spec
```

This takes a couple of minutes — PyInstaller is tracing every module pandas,
openpyxl, and PySide6 might import. When it finishes, you'll have:

```
dist/
  ExcelTabViewer/
    ExcelTabViewer.exe      <- the app
    _internal/              <- all its dependencies (DLLs, Qt plugins, resources/style.qss, etc.)
```

**Ship the entire `ExcelTabViewer` folder, not just the `.exe`.** The `.exe`
alone will not run without `_internal` sitting next to it. Zip the whole
folder to distribute it.

## 3. Test it

```powershell
dist\ExcelTabViewer\ExcelTabViewer.exe
```

Open a file, try filters, save a profile, hit Refresh — the same checklist
from each build step, just against the packaged build instead of `python
main.py`. A few things specifically worth re-checking here, since they only
show up in a packaged build:

- **Test on a genuinely clean machine or VM if you can** — one without Python
  or your dev tools installed. That's the real test of whether every
  dependency actually got bundled, versus your dev machine quietly filling
  gaps from its own installed packages.
- **Windows SmartScreen will likely flag it** the first time it's run, with a
  "Windows protected your PC" prompt — this is expected for any unsigned
  `.exe`, not a sign something's wrong. Click "More info" → "Run anyway".
  This goes away only with a paid code-signing certificate, which is outside
  this project's scope but worth knowing about if you plan to distribute
  this beyond your own machines.
- **Antivirus false positives** are a known PyInstaller quirk (some AV
  heuristics are suspicious of self-extracting/packed executables in
  general). The one-dir build here is deliberately the less-flagged option —
  see the note below.

## 4. Why one-dir instead of one-file

The spec builds a **one-dir** bundle (a folder with the `.exe` plus loose
dependency files) rather than a single-file `.exe`. This was a deliberate
choice:

| | One-dir (this spec) | One-file (`--onefile`) |
|---|---|---|
| Startup speed | Fast — files load directly | Slower — self-extracts to a temp folder on every launch |
| Antivirus false positives | Less common | More common (self-extracting `.exe`s trip more heuristics) |
| Distribution | Zip a folder | Single `.exe` file |
| Debugging a broken build | Easier — you can see which DLL/file is missing | Harder — everything's hidden inside |

If you'd still rather ship a single file, change `EXE(..., exclude_binaries=True, ...)` to `exclude_binaries=False`, remove the `COLLECT(...)` block entirely, and pass `--onefile` isn't needed since that's controlled by the spec structure itself — the PyInstaller docs cover converting a spec between the two modes if you want to go that route later.

## 5. Hidden-import gotchas (already handled in the spec, explained here)

PyInstaller works by statically scanning your code's imports, which mostly
works — but pandas and openpyxl both do a lot of *dynamic* importing
internally (pandas' datetime/timezone C extensions, openpyxl's cell-writing
modules), which the static scanner can miss. The symptom is always the same:
`python main.py` works perfectly, but the packaged `.exe` crashes on launch
or the moment you try to load a file, with a `ModuleNotFoundError` for
something you never imported yourself.

The spec avoids this by pulling in **every** submodule of `pandas` and
`openpyxl` via `collect_submodules(...)`, rather than trying to guess which
specific ones are needed. This makes the build a bit larger than the
theoretical minimum, but it's far more reliable than chasing missing-module
errors one at a time after each build.

If you ever add a new dependency (say, a charting library in a future step)
and the packaged `.exe` throws a `ModuleNotFoundError` that `python main.py`
doesn't, this is almost always why — add that package to the
`hidden_imports` list in `excel_tab_viewer.spec` the same way, or add its
name to `hiddenimports=[...]` directly if `collect_submodules` doesn't apply.

## 6. Adding an icon (optional)

Drop an `.ico` file at `resources/app.ico`, then uncomment this line in
`excel_tab_viewer.spec`:

```python
# icon="resources/app.ico",
```

and rebuild. (PySide6/Qt can only use `.ico` for the Windows taskbar/title
bar icon — PNG/SVG won't work here.)

## 7. Rebuilding after code changes

Just re-run `pyinstaller excel_tab_viewer.spec`. PyInstaller caches
intermediate build files in a `build/` folder; if a rebuild ever behaves
strangely after a big change (e.g. adding a new package), delete both
`build/` and `dist/` and rebuild from scratch to rule out stale cache state:

```powershell
rmdir /s /q build
rmdir /s /q dist
pyinstaller excel_tab_viewer.spec
```
