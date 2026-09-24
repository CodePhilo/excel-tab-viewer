# excel_tab_viewer.spec
#
# PyInstaller build spec for Excel Tab Viewer.
#
# Build with:   pyinstaller excel_tab_viewer.spec
# (see PACKAGING.md for full step-by-step instructions and gotchas)
#
# This must be run on Windows to produce a Windows .exe — PyInstaller does
# not cross-compile. Running it on macOS/Linux produces a binary for that
# platform instead, which is useful for validating the spec itself but not
# for producing the final Windows build.

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# pandas and openpyxl both do a lot of dynamic/lazy importing internally
# (e.g. pandas' datetime/timezone machinery, openpyxl's cell writers), which
# PyInstaller's static import scanner can miss. Pulling in every submodule
# of each package is the simplest way to avoid a working `python main.py`
# that then throws ModuleNotFoundError only once packaged.
hidden_imports = (
    collect_submodules("openpyxl")
    + collect_submodules("pandas")
    + [
        # A short list of specific modules that have been known to get
        # missed even with collect_submodules, depending on pandas version.
        "pandas._libs.tslibs.base",
        "pandas._libs.tslibs.np_datetime",
        "pandas._libs.tslibs.nattype",
        "pandas._libs.window.aggregations",
    ]
)

# Anything the app reads from disk at runtime (not imported as Python code)
# needs to be listed here explicitly, or it won't be in the bundled folder.
datas = [
    ("resources/style.qss", "resources"),
    # style.qss and main.py load these at runtime; without them the packaged
    # app drew no combo/spin/tab/tree arrows at all.
    ("resources/icons", "resources/icons"),
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Excluded because they're never imported by this app but sometimes get
    # pulled in transitively by pandas/PySide6, bloating the build for no
    # reason. If a build ever fails complaining one of these is actually
    # needed, just remove it from this list.
    excludes=["tkinter", "matplotlib", "PyQt5", "PyQt6", "IPython", "notebook"],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ExcelTabViewer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # windowed app: no console window pops up alongside it
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="resources/icons/app.ico",  # rebuild with: python resources/make_app_ico.py
)

# COLLECT produces a folder (one-dir build): ExcelTabViewer.exe plus its
# dependencies as loose files alongside it. See PACKAGING.md for why this
# is the recommended default over a single-file --onefile build.
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ExcelTabViewer",
)
