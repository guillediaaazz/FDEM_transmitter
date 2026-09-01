from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


project_root = Path(SPECPATH)
icon_path = project_root / "build" / "generated" / "fdem.ico"

datas = collect_data_files("customtkinter")
datas += [(str(icon_path), "assets")]

hiddenimports = collect_submodules("bleak.backends.winrt")
hiddenimports += [
    "bleak",
    "bleak.backends.winrt.client",
    "bleak.backends.winrt.scanner",
    "serial",
    "serial.win32",
]

a = Analysis(
    [str(project_root / "launcher.py")],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "unittest"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FDEM TX Controller",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_path),
    version=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="FDEM TX Controller",
)
