#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de diagnóstico del sistema
Verifica que todo esté correctamente configurado para ejecutar la aplicación
"""

import os
import sys
import json
import subprocess
from pathlib import Path

def print_seccion(titulo):
    """Imprime un título de sección"""
    print("\n" + "="*80)
    print(f"🔍 {titulo}")
    print("="*80)

def print_ok(mensaje):
    """Imprime un mensaje de éxito"""
    print(f"✅ {mensaje}")

def print_error(mensaje):
    """Imprime un mensaje de error"""
    print(f"❌ {mensaje}")

def print_advertencia(mensaje):
    """Imprime una advertencia"""
    print(f"⚠️  {mensaje}")

def verificar_python():
    """Verifica la versión de Python"""
    print_seccion("VERIFICACIÓN DE PYTHON")
    
    version = sys.version_info
    print(f"Versión de Python: {version.major}.{version.minor}.{version.micro}")
    
    if version.major < 3:
        print_error("Se requiere Python 3.x")
        return False
    elif version.major == 3 and version.minor < 8:
        print_advertencia("Se recomienda Python 3.8 o superior")
        return False
    else:
        print_ok(f"Python {version.major}.{version.minor} es compatible")
        return True

def verificar_archivos_requeridos():
    """Verifica que existan los archivos esenciales"""
    print_seccion("ARCHIVOS REQUERIDOS")
    
    archivos_requeridos = [
        'app.py',
        'requirements.txt',
        'templates/base.html',
        'static',
        'config_sistema.json'
    ]
    
    faltantes = []
    for archivo in archivos_requeridos:
        if os.path.exists(archivo):
            print_ok(f"✓ {archivo}")
        else:
            print_error(f"✗ {archivo} - NO ENCONTRADO")
            faltantes.append(archivo)
    
    return len(faltantes) == 0

def verificar_dependencias():
    """Verifica las dependencias instaladas"""
    print_seccion("DEPENDENCIAS DE PYTHON")
    
    if not os.path.exists('requirements.txt'):
        print_error("No se encuentra requirements.txt")
        return False
    
    # Leer requirements.txt
    dependencias = []
    try:
        with open('requirements.txt', 'r', encoding='utf-8') as f:
            for linea in f:
                linea = linea.strip()
                if linea and not linea.startswith('#'):
                    # Extraer el nombre del paquete (antes del ==)
                    nombre = linea.split('==')[0].split('>=')[0].split('<=')[0].strip()
                    dependencias.append(nombre)
    except Exception as e:
        print_error(f"Error leyendo requirements.txt: {e}")
        return False
    
    faltantes = []
    instaladas = []
    
    for dep in dependencias:
        try:
            __import__(dep.lower().replace('-', '_'))
            instaladas.append(dep)
            print_ok(f"✓ {dep}")
        except ImportError:
            # Algunas dependencias tienen nombres diferentes al importar
            modulos_especiales = {
                'beautifulsoup4': 'bs4',
                'Flask-WTF': 'flask_wtf',
                'Flask-SQLAlchemy': 'flask_sqlalchemy',
                'Pillow': 'PIL',
                'qrcode[pil]': 'qrcode'
            }
            
            modulo_import = modulos_especiales.get(dep, dep.lower().replace('-', '_'))
            try:
                __import__(modulo_import)
                instaladas.append(dep)
                print_ok(f"✓ {dep} (como {modulo_import})")
            except ImportError:
                faltantes.append(dep)
                print_error(f"✗ {dep} - NO INSTALADO")
    
    if faltantes:
        print_advertencia(f"\nFaltan {len(faltantes)} dependencias. Ejecuta: pip install -r requirements.txt")
        return False
    
    print_ok(f"Todas las {len(dependencias)} dependencias están instaladas")
    return True

def verificar_archivos_json():
    """Verifica que los archivos JSON existan o puedan crearse"""
    print_seccion("ARCHIVOS DE DATOS JSON")
    
    archivos_json = [
        'clientes.json',
        'inventario.json',
        'usuarios.json',
        'config_sistema.json',
        'facturas_json/facturas.json',
        'notas_entrega.json',
        'cotizaciones_json/cotizaciones.json',
        'pagos_recibidos.json',
        'cuentas_por_cobrar.json',
        'proveedores.json',
        'ordenes_servicio.json'
    ]
    
    problemas = []
    
    for archivo in archivos_json:
        try:
            # Crear directorio si no existe
            directorio = os.path.dirname(archivo)
            if directorio and not os.path.exists(directorio):
                os.makedirs(directorio, exist_ok=True)
                print_advertencia(f"Directorio creado: {directorio}")
            
            # Verificar o crear archivo
            if os.path.exists(archivo):
                # Verificar que sea JSON válido
                try:
                    with open(archivo, 'r', encoding='utf-8') as f:
                        json.load(f)
                    print_ok(f"✓ {archivo}")
                except json.JSONDecodeError:
                    print_error(f"✗ {archivo} - JSON INVÁLIDO")
                    problemas.append(archivo)
            else:
                # Crear archivo vacío
                with open(archivo, 'w', encoding='utf-8') as f:
                    json.dump({}, f, ensure_ascii=False, indent=4)
                print_advertencia(f"⚠ {archivo} - CREADO (vacío)")
        except Exception as e:
            print_error(f"✗ {archivo} - ERROR: {e}")
            problemas.append(archivo)
    
    return len(problemas) == 0

def verificar_directorios():
    """Verifica que existan los directorios necesarios"""
    print_seccion("DIRECTORIOS REQUERIDOS")
    
    directorios = [
        'static',
        'static/uploads',
        'static/imagenes_productos',
        'templates',
        'facturas_json',
        'facturas_pdf',
        'cotizaciones_json',
        'cotizaciones_pdf',
        'documentos_fiscales',
        'uploads',
        'logs'
    ]
    
    problemas = []
    
    for directorio in directorios:
        try:
            if os.path.exists(directorio):
                print_ok(f"✓ {directorio}")
            else:
                os.makedirs(directorio, exist_ok=True)
                print_advertencia(f"⚠ {directorio} - CREADO")
        except Exception as e:
            print_error(f"✗ {directorio} - ERROR: {e}")
            problemas.append(directorio)
    
    return len(problemas) == 0

def verificar_configuracion():
    """Verifica la configuración del sistema"""
    print_seccion("CONFIGURACIÓN DEL SISTEMA")
    
    if not os.path.exists('config_sistema.json'):
        print_error("config_sistema.json no existe")
        return False
    
    try:
        with open('config_sistema.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        print_ok("✓ config_sistema.json es válido")
        
        # Verificar campos importantes
        campos_importantes = ['moneda_sistema', 'tasa_actual_usd']
        for campo in campos_importantes:
            if campo in config:
                print_ok(f"✓ Campo '{campo}' presente")
            else:
                print_advertencia(f"⚠ Campo '{campo}' no encontrado (se puede agregar por defecto)")
        
        return True
    except json.JSONDecodeError as e:
        print_error(f"config_sistema.json tiene errores de sintaxis: {e}")
        return False
    except Exception as e:
        print_error(f"Error leyendo config_sistema.json: {e}")
        return False

def verificar_rutas_absolutas():
    """Verifica si hay rutas absolutas problemáticas"""
    print_seccion("VERIFICACIÓN DE RUTAS")
    
    problemas = []
    
    # Leer app.py
    try:
        with open('app.py', 'r', encoding='utf-8') as f:
            contenido = f.read()
        
        # Buscar rutas absolutas comunes
        rutas_problematicas = [
            'C:\\',
            '/home/',
            '/Users/',
            'OneDrive',
            'Escritorio'
        ]
        
        for ruta in rutas_problematicas:
            if ruta in contenido:
                print_advertencia(f"⚠ Se encontró ruta potencialmente problemática: {ruta}")
                problemas.append(ruta)
        
        # Verificar que se use BASE_DIR
        if 'BASE_DIR = os.path.dirname(os.path.abspath(__file__))' in contenido:
            print_ok("✓ Usa BASE_DIR para rutas relativas")
        else:
            print_advertencia("⚠ No se encontró uso de BASE_DIR")
        
    except Exception as e:
        print_error(f"Error verificando rutas: {e}")
    
    return len(problemas) == 0

def verificar_puerto():
    """Verifica si el puerto está disponible"""
    print_seccion("VERIFICACIÓN DE PUERTO")
    
    import socket
    
    puerto_default = 5000
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        resultado = sock.connect_ex(('localhost', puerto_default))
        sock.close()
        
        if resultado == 0:
            print_advertencia(f"⚠ El puerto {puerto_default} está en uso")
            print_advertencia("   Puedes cambiar el puerto con: python app.py --port 5001")
            return False
        else:
            print_ok(f"✓ Puerto {puerto_default} disponible")
            return True
    except Exception as e:
        print_error(f"Error verificando puerto: {e}")
        return False

def generar_reporte():
    """Genera un reporte completo"""
    print("\n" + "="*80)
    print("📊 REPORTE DE DIAGNÓSTICO COMPLETO")
    print("="*80)
    
    resultados = {
        'Python': verificar_python(),
        'Archivos Requeridos': verificar_archivos_requeridos(),
        'Dependencias': verificar_dependencias(),
        'Directorios': verificar_directorios(),
        'Archivos JSON': verificar_archivos_json(),
        'Configuración': verificar_configuracion(),
        'Rutas': verificar_rutas_absolutas(),
        'Puerto': verificar_puerto()
    }
    
    print_seccion("RESUMEN")
    
    exitosos = sum(1 for v in resultados.values() if v)
    total = len(resultados)
    
    for nombre, resultado in resultados.items():
        if resultado:
            print_ok(f"{nombre}: OK")
        else:
            print_error(f"{nombre}: PROBLEMAS")
    
    print(f"\n{'='*80}")
    print(f"📈 Resultado: {exitosos}/{total} verificaciones exitosas")
    print("="*80)
    
    if exitosos == total:
        print("\n🎉 ¡TODO ESTÁ CORRECTO! Puedes ejecutar la aplicación.")
        print("\n   Ejecuta: python app.py")
        return 0
    else:
        print("\n⚠️  HAY PROBLEMAS QUE RESOLVER:")
        if not resultados['Dependencias']:
            print("\n   1. Instala las dependencias faltantes:")
            print("      pip install -r requirements.txt")
        if not resultados['Directorios']:
            print("\n   2. El script intentó crear los directorios faltantes")
        if not resultados['Archivos JSON']:
            print("\n   3. Revisa los archivos JSON mencionados arriba")
        print("\n   Después de resolver los problemas, ejecuta este script nuevamente.")
        return 1

if __name__ == "__main__":
    try:
        exit_code = generar_reporte()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n⚠️ Diagnóstico cancelado por el usuario")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error inesperado: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

