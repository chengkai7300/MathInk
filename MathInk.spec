# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec: single-file MathInk.exe (tray launcher).
# Build with: .\.venv\Scripts\python -m PyInstaller MathInk.spec --noconfirm

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules("uvicorn") + [
    "app.main",
    "app.session",
    "app.image_ops",
    "app.latex_utils",
    "app.engines.comer",
    "app.engines.vlm",
    "pystray._win32",
]

a = Analysis(
    ["launcher.py"],
    pathex=["backend"],
    binaries=[],
    datas=[
        ("web", "web"),
        ("models/comer", "models/comer"),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["torch", "matplotlib", "tkinter", "IPython", "pytest", "notebook", "scipy"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="MathInk",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon="assets/mathink.ico",
)
