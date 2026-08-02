# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


project_root = Path(SPECPATH)
font_names = [
    "eaw_diplo_16mbs.fnt",
    "eaw_diplo_16mbs.dds",
    "eaw_diplo_16mbs_cryllic.fnt",
    "eaw_diplo_16mbs_cryllic.dds",
    "hoi_24header.fnt",
    "hoi_24header.dds",
    "eaw_24header_cryllic.fnt",
    "eaw_24header_cryllic.dds",
]
datas = [
    (
        str(project_root / "assets" / "fonts" / name),
        "assets/fonts",
    )
    for name in font_names
]

a = Analysis(
    [str(project_root / "main.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=["PIL.DdsImagePlugin"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="EaWFocusTextPreview",
    version=str(project_root / "version_info.txt"),
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
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="EaWFocusTextPreview",
)
