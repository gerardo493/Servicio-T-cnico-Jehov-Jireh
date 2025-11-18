"""
Script para construir el ejecutable con PyInstaller
Ejecutar: python build_exe.py
"""
import PyInstaller.__main__
import os
import sys

# Obtener el directorio actual
current_dir = os.path.dirname(os.path.abspath(__file__))

# Archivos y carpetas a incluir
add_data = [
    f'templates{os.pathsep}templates',
    f'static{os.pathsep}static',
]

# Incluir módulos Python personalizados si existen
custom_modules = [
    'config_maps.py',
    'seguridad_fiscal.py',
    'numeracion_fiscal.py',
    'comunicacion_seniat.py',
    'exportacion_seniat.py',
    'filtros_dashboard.py',
]

# Verificar y agregar módulos que existan
for module in custom_modules:
    if os.path.exists(module):
        add_data.append(f'{module}{os.pathsep}.')

# Archivos ocultos a importar (módulos que PyInstaller no detecta automáticamente)
hidden_imports = [
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
]

# Argumentos para PyInstaller
args = [
    'app.py',
    '--name=SistemaGestion',
    '--onedir',  # Usar --onedir en lugar de --onefile para mejor rendimiento
    '--console',  # Mostrar consola para ver errores (cambiar a --windowed cuando funcione)
    '--clean',  # Limpiar archivos temporales antes de construir
    '--noconfirm',  # Sobrescribir sin preguntar
    '--icon=NONE',  # Agregar ruta a .ico si tienes un ícono
]

# Agregar archivos de datos
for data in add_data:
    args.append(f'--add-data={data}')

# Agregar imports ocultos
for imp in hidden_imports:
    args.append(f'--hidden-import={imp}')

# Ejecutar PyInstaller
print("🔨 Iniciando construcción del ejecutable...")
print(f"📁 Directorio: {current_dir}")
print(f"📦 Archivos a incluir: {len(add_data)}")
print(f"🔍 Imports ocultos: {len(hidden_imports)}")
print("\n" + "="*60)
print("Ejecutando PyInstaller...")
print("="*60 + "\n")

try:
    PyInstaller.__main__.run(args)
    print("\n" + "="*60)
    print("✅ ¡Ejecutable construido exitosamente!")
    print("="*60)
    print(f"\n📂 El ejecutable está en: {os.path.join(current_dir, 'dist', 'SistemaGestion')}")
    print("\n⚠️ IMPORTANTE:")
    print("1. Copia los archivos JSON existentes a la carpeta 'dist/SistemaGestion/'")
    print("2. Asegúrate de que config_sistema.json esté en esa carpeta")
    print("3. Los archivos JSON se crearán automáticamente si no existen")
    print("4. El ejecutable 'SistemaGestion.exe' está listo para distribuir")
except Exception as e:
    print(f"\n❌ Error construyendo ejecutable: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

