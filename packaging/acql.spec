# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the ACQL Dashboard.

Build from the project root:

    python -m PyInstaller packaging/acql.spec --noconfirm

Produces a single self-contained executable in dist/. The person running it
needs no Python and no pip - they drop their spreadsheets in a data/ folder
beside the executable and double-click.
"""

import sys
from pathlib import Path

# SPECPATH is injected by PyInstaller and points at this file's folder.
ROOT = Path(SPECPATH).resolve().parent

block_cipher = None

# Qt ships far more than a dashboard needs; dropping these keeps the binary
# to a sane size without touching anything the app actually imports.
EXCLUDES = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngine",
    "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQml", "PySide6.Qt3DCore",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtBluetooth",
    "PySide6.QtNetworkAuth", "PySide6.QtPositioning", "PySide6.QtSensors",
    "PySide6.QtSerialPort", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtDesigner", "PySide6.QtTest",
    "PySide6.QtSql", "PySide6.QtHelp", "PySide6.QtOpenGLWidgets",
    "tkinter", "pytest", "IPython", "jupyter", "notebook", "sphinx",
    "scipy", "PIL.ImageQt", "PyQt5", "PyQt6",
]
# Note: do NOT exclude unittest/pydoc/doctest. They look like test-only
# modules, but pyparsing imports unittest at module scope and matplotlib
# imports pyparsing, so excluding it breaks the bundle at startup.

a = Analysis(
    [str(ROOT / "packaging" / "entrypoint.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "acql",
        "acql.awards",
        "acql.config",
        "acql.models",
        "acql.names",
        "acql.repository",
        "acql.writeback",
        "acql.sources",
        "acql.sources.discovery",
        "acql.sources.stats_xls",
        "acql.sources.workbook",
        "acql.ui",
        "acql.ui.app",
        "acql.ui.charts",
        "acql.ui.theme",
        "acql.ui.widgets",
        "acql.ui.pages",
        "acql.ui.pages.base",
        "acql.ui.pages.data",
        "acql.ui.pages.overview",
        "acql.ui.pages.player",
        "acql.ui.pages.pools",
        "acql.ui.pages.standings",
        "acql.ui.pages.weekly",
        "acql.ui.pages.winnings",
        # Pulled in dynamically by the backends, so name them explicitly.
        "matplotlib.backends.backend_qtagg",
        "openpyxl",
        "xlrd",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

icon_file = None
for candidate in ("acql.ico", "acql.icns"):
    path = ROOT / "packaging" / candidate
    if path.exists():
        if (candidate.endswith(".ico") and sys.platform == "win32") or (
            candidate.endswith(".icns") and sys.platform == "darwin"
        ):
            icon_file = str(path)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="ACQL Dashboard",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    # A GUI app: no console window should appear behind it on Windows.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file,
)

# macOS expects an .app bundle rather than a bare executable.
if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="ACQL Dashboard.app",
        icon=icon_file,
        bundle_identifier="com.acql.dashboard",
        info_plist={
            "CFBundleName": "ACQL Dashboard",
            "CFBundleDisplayName": "ACQL Dashboard",
            "CFBundleShortVersionString": "1.0.0",
            "CFBundleVersion": "1.0.0",
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.sports",
        },
    )
