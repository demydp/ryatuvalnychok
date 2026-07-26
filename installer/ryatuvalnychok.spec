# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec для Рятувальничка. Собирает onedir-бандл (не onefile) — старт быстрее
(не нужно каждый раз распаковывать всё во временную папку) и путь к бандлованным ресурсам
(ffmpeg и т.п.) предсказуем: он просто рядом с .exe (см. app/paths.py: INSTALL_DIR).

Запускать не напрямую, а через installer/build.ps1 (тот же PyInstaller, но с очисткой
build/dist и последующей сборкой Inno Setup инсталлятора).
"""
import os

from PyInstaller.utils.hooks import collect_data_files

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

datas = [
    (os.path.join(ROOT, "app", "templates"), "app/templates"),
    (os.path.join(ROOT, "app", "static"), "app/static"),
]
datas += collect_data_files("whisper")
datas += collect_data_files("imageio_ffmpeg")

block_cipher = None

a = Analysis(
    [os.path.join(ROOT, "run.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=["whisper", "tiktoken_ext.openai_public", "tiktoken_ext"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Ryatuvalnychok",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=os.path.join(ROOT, "dashboard.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="Ryatuvalnychok",
)
