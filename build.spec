# -*- mode: python ; coding: utf-8 -*-
"""
Archivo de especificación para PyInstaller
Ejecutar: pyinstaller build.spec
"""

block_cipher = None

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('templates', 'templates'),
        ('static', 'static'),
    ],
    hiddenimports=[
        'flask',
        'werkzeug',
        'jinja2',
        'markupsafe',
        'itsdangerous',
        'click',
        'blinker',
        'qrcode',
        'PIL',
        'PIL.Image',
        'PIL.ImageTk',
        'email',
        'email.mime',
        'email.mime.text',
        'email.mime.multipart',
        'smtplib',
        'bs4',
        'requests',
        'urllib3',
        'certifi',
        'charset_normalizer',
        'idna',
        'config_maps',
        'seguridad_fiscal',
        'numeracion_fiscal',
        'comunicacion_seniat',
        'exportacion_seniat',
        'filtros_dashboard',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='SistemaGestion',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Mostrar consola para ver errores (cambiar a False cuando funcione)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # Agregar ruta a .ico si tienes un ícono
)

