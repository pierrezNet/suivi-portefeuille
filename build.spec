# -*- mode: python ; coding: utf-8 -*-
"""Spécification PyInstaller — exécutable Windows « Suivi Portefeuille ».

Mode --onedir (dossier de distribution) : démarrage plus rapide que --onefile
et nettement moins de faux positifs antivirus.

À construire SUR Windows (PyInstaller ne croise pas) — typiquement le runner
GitHub Actions windows-latest :

    pip install -r requirements.txt -r requirements-build.txt
    pyinstaller build.spec --noconfirm

Sortie : dist/Suivi-Portefeuille/  (contient Suivi-Portefeuille.exe + deps).
"""

from PyInstaller.utils.hooks import collect_all, collect_data_files


# --- Données embarquées : Flask sert templates/static depuis le bundle -------
datas = [
    ("app/templates", "app/templates"),
    ("app/static", "app/static"),
    ("tools/templates", "tools/templates"),  # assets PWA + page mobile chiffrée
]
binaries = []
# cffi/_cffi_backend : binaire natif requis par cryptography.
hiddenimports = ["_cffi_backend", "et_xmlfile"]

# Paquets à binaires/données natifs : sans collect_all, le .exe lève des
# ModuleNotFoundError / DLL manquantes au runtime.
for paquet in ("cryptography", "openpyxl", "icalendar"):
    d, b, h = collect_all(paquet)
    datas += d
    binaries += b
    hiddenimports += h

# Base de fuseaux horaires (utilisée par icalendar / zoneinfo).
datas += collect_data_files("tzdata")


a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # yfinance/pandas/numpy : dépendance OPTIONNELLE (métadonnées Yahoo), non
    # embarquée volontairement (offline-first + poids). La feature se dégrade
    # proprement en son absence (enrichir_pour_titre renvoie None).
    excludes=["yfinance", "pandas", "numpy"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Suivi-Portefeuille",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,            # UPX augmente les faux positifs antivirus
    console=False,        # pas de fenêtre console noire (UX amis)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,            # icône .ico optionnelle à ajouter plus tard
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Suivi-Portefeuille",
)
