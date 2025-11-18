# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[('templates', 'templates'), ('static', 'static'), ('config_maps.py', '.'), ('seguridad_fiscal.py', '.'), ('numeracion_fiscal.py', '.'), ('comunicacion_seniat.py', '.'), ('exportacion_seniat.py', '.'), ('filtros_dashboard.py', '.')],
    hiddenimports=['flask', 'werkzeug', 'jinja2', 'markupsafe', 'itsdangerous', 'click', 'blinker', 'qrcode', 'PIL', 'PIL.Image', 'PIL.ImageTk', 'email', 'email.mime', 'email.mime.text', 'email.mime.multipart', 'smtplib', 'bs4', 'requests', 'urllib3', 'certifi', 'charset_normalizer', 'idna', 'config_maps', 'seguridad_fiscal', 'numeracion_fiscal', 'comunicacion_seniat', 'exportacion_seniat', 'filtros_dashboard'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SistemaGestion',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='NONE',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SistemaGestion',
)
