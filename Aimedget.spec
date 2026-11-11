# -*- mode: python ; coding: utf-8 -*-
"""
Build do Aimedget com PyInstaller, em modo PASTA (onedir): dist/Aimedget/Aimedget.exe + dist/Aimedget/_internal/.

Por que pasta e não um .exe único:
- Abre mais rápido (o .exe único descompacta tudo numa pasta temporária a cada abertura).
- O Qt (PySide6) é LGPL: em pasta, as DLLs do Qt ficam separadas e podem ser trocadas pelo usuário.
- O instalador (installer/Aimedget.iss) instala a pasta, e a versão portátil é essa mesma pasta zipada.

Uso: python -m PyInstaller Aimedget.spec --noconfirm   (ou tools/build_release.ps1, que faz tudo)
"""

import os
import re

ROOT_DIR = os.path.abspath(SPECPATH)

# Versão: fonte única em app/core/version.py (o app, o instalador e a release leem dali)
with open(os.path.join(ROOT_DIR, "app", "core", "version.py"), encoding="utf-8") as _f:
    VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', _f.read()).group(1)
_v = [int(x) for x in VERSION.split("-")[0].split(".")] + [0, 0, 0]
VERSION_TUPLE = tuple(_v[:4])

# Propriedades do .exe (Windows: botão direito > Propriedades > Detalhes)
from PyInstaller.utils.win32.versioninfo import (  # noqa: E402
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
)

version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=VERSION_TUPLE, prodvers=VERSION_TUPLE),
    kids=[
        StringFileInfo([StringTable("041604B0", [
            StringStruct("CompanyName", "Aimedget"),
            StringStruct("FileDescription", "Aimedget"),
            StringStruct("FileVersion", VERSION),
            StringStruct("InternalName", "Aimedget"),
            StringStruct("OriginalFilename", "Aimedget.exe"),
            StringStruct("ProductName", "Aimedget"),
            StringStruct("ProductVersion", VERSION),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0416, 1200])]),
    ],
)

# Arquivos de desenvolvimento dentro de assets/ que não vão para o usuário
_DEV_ONLY = {"widget-preview.html", "demo.html", "tonearm-animated-demo.svg"}

datas = []
for folder, _dirs, files in os.walk(os.path.join(ROOT_DIR, "assets")):
    rel = os.path.relpath(folder, ROOT_DIR)
    for name in files:
        if name in _DEV_ONLY or name.endswith(".zip"):
            continue
        datas.append((os.path.join(folder, name), rel))

hiddenimports = [
    'winrt',
    'winrt.system',
    'winrt.windows.foundation',
    'winrt.windows.foundation.collections',
    'winrt.windows.media.control',
    'winrt.windows.storage.streams',
    'PySide6.QtSvg',
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'PySide6.QtNetwork',   # instância única (QLocalServer)
]

excludes = [
    'tkinter',
    'unittest',
    'test',
    'PySide6.QtWebEngine',
    'PySide6.QtWebEngineCore',
    'PySide6.QtWebEngineWidgets',
    'PySide6.QtPdf',
    'PySide6.QtPdfWidgets',
    'PySide6.QtQml',
    'PySide6.QtQuick',
    'PySide6.QtQuickWidgets',
    'PySide6.QtDesigner',
    'PySide6.Qt3D',
    'mysql',
    'flask',
    'werkzeug',
    'jinja2',
    'scipy',
    'numpy',
    'pandas',
    'matplotlib',
]

a = Analysis(
    ['app/main.py'],
    pathex=[ROOT_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

# Partes do Qt que entram arrastadas por plugins, mas o app não usa (~45 MB a menos):
# - opengl32sw.dll: OpenGL por software. O app desenha tudo com QPainter (raster), sem OpenGL.
# - Qt Quick / QML / PDF / teclado virtual: o app é Qt Widgets puro.
# - translations/: o app tem i18n próprio (app/core/i18n.py) e não instala QTranslator.
_UNUSED_QT = re.compile(
    r"(opengl32sw\.dll"
    r"|Qt6(Quick|Qml|QmlModels|QmlMeta|QmlWorkerScript|Pdf|VirtualKeyboard)\w*\.dll"
    r"|qpdf\.dll|qtvirtualkeyboardplugin\.dll)$",
    re.IGNORECASE,
)
a.binaries = [b for b in a.binaries if not _UNUSED_QT.search(b[0])]
a.datas = [d for d in a.datas if not d[0].replace("\\", "/").startswith("PySide6/translations/")]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,       # onedir: as DLLs vão para a pasta (COLLECT), não para dentro do .exe
    name='Aimedget',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                   # UPX em DLLs do Qt é causa clássica de falso positivo de antivírus
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT_DIR, 'assets', 'aimedget_icon.ico'),
    version=version_info,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='Aimedget',
)
