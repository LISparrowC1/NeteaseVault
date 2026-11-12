# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build: one program folder, with the Node engine bundled."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve()
PROJECT = ROOT.parent

datas = [
    (str(PROJECT / "engine"), "engine"),
    (str(PROJECT / "app" / "db" / "schema.sql"), "app/db"),
]
runtime = PROJECT / "runtime"
if runtime.exists():
    datas.append((str(runtime), "runtime"))
datas += collect_data_files("soundfile")
datas += collect_data_files("zhconv")
datas += collect_data_files("musicdl")
datas += collect_data_files("certifi")

hiddenimports = (
    ["zhconv", "certifi"]
    + collect_submodules("musicdl.modules")
    + collect_submodules("soundfile")
    + ["PySide6.QtMultimedia", "PySide6.QtNetwork", "PySide6.QtWidgets", "PySide6.QtSvg"]
)

a = Analysis(
    [str(PROJECT / "run.py")],
    pathex=[str(PROJECT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pandas", "scipy", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NeteaseVault",
    icon=str(ROOT / "icon.ico"),
    version=str(ROOT / "version_info.txt"),
    debug=False,
    strip=False,
    upx=False,
    console=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    contents_directory="data",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="NeteaseVault",
)

if __name__ == "__main__":
    # `pyinstaller build.spec` drives the Analysis above.
    pass
