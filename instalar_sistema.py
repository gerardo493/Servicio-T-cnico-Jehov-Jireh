#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de instalación automática del sistema
Configura todo lo necesario para ejecutar la aplicación en una nueva PC
"""

import os
import sys
import subprocess
import json
from pathlib import Path

def print_seccion(titulo):
    """Imprime un título de sección"""
    print("\n" + "="*80)
    print(f"🔧 {titulo}")
    print("="*80)

def print_ok(mensaje):
    """Imprime un mensaje de éxito"""
    print(f"✅ {mensaje}")

def print_error(mensaje):
    """Imprime un mensaje de error"""
    print(f"❌ {mensaje}")

def print_info(mensaje):
    """Imprime información"""
    print(f"ℹ️  {mensaje}")

def ejecutar_comando(comando, descripcion, mostrar_salida=True):
    """Ejecuta un comando del sistema"""
    try:
        resultado = subprocess.run(
            comando,
            shell=True,
            check=True,
            capture_output=True,
            text=True,
            encoding='utf-8'
        )
        
        if mostrar_salida and resultado.stdout:
            print(resultado.stdout)
        
        return True
    except subprocess.CalledProcessError as e:
        if mostrar_salida:
            print_error(f"Error: {e.stderr if e.stderr else str(e)}")
        return False

def verificar_python():
    """Verifica e instala Python si es necesario"""
    print_seccion("VERIFICACIÓN DE PYTHON")
    
    version = sys.version_info
    print(f"Versión de Python detectada: {version.major}.{version.minor}.{version.micro}")
    
    if version.major < 3:
        print_error("Se requiere Python 3.x")
        print_info("Descarga Python desde: https://www.python.org/downloads/")
        return False
    
    if version.major == 3 and version.minor < 8:
        print_error("Se requiere Python 3.8 o superior")
        print_info("Actualiza Python desde: https://www.python.org/downloads/")
        return False
    
    print_ok(f"Python {version.major}.{version.minor} es compatible")
    return True

def crear_directorios():
    """Crea todos los directorios necesarios"""
    print_seccion("CREACIÓN DE DIRECTORIOS")
    
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
        'exportaciones_seniat',
        'uploads',
        'uploads/capturas',
        'logs',
        'reportes_clientes',
        'reportes_cuentas',
        'backups'
    ]
    
    creados = 0
    for directorio in directorios:
        try:
            os.makedirs(directorio, exist_ok=True)
            if not os.path.exists(directorio):
                os.makedirs(directorio)
                print_ok(f"Creado: {directorio}")
                creados += 1
            else:
                print_info(f"Ya existe: {directorio}")
        except Exception as e:
            print_error(f"Error creando {directorio}: {e}")
    
    if creados > 0:
        print_ok(f"Se crearon {creados} directorios nuevos")
    else:
        print_ok("Todos los directorios ya existen")
    
    return True

def crear_archivos_json():
    """Crea los archivos JSON necesarios con estructura inicial"""
    print_seccion("CREACIÓN DE ARCHIVOS JSON")
    
    archivos_json = {
        'clientes.json': {},
        'inventario.json': {},
        'usuarios.json': {},
        'notas_entrega.json': {},
        'pagos_recibidos.json': {},
        'cuentas_por_cobrar.json': {},
        'proveedores.json': {},
        'ordenes_servicio.json': {},
        'roles_usuarios.json': {
            "admin": {"nombre": "Administrador", "permisos": ["all"]},
            "tecnico": {"nombre": "Técnico", "permisos": ["ordenes", "inventario"]},
            "ventas": {"nombre": "Ventas", "permisos": ["clientes", "ventas"]}
        },
        'empresa.json': {
            "nombre": "Tu Empresa",
            "rif": "J-123456789-0",
            "direccion": "",
            "telefono": "",
            "email": ""
        },
        'control_numeracion_fiscal.json': {
            "facturas": {"ultimo_numero": 0},
            "notas_entrega": {"ultimo_numero": 0},
            "cotizaciones": {"ultimo_numero": 0}
        },
        'series_numeracion.json': {},
        'movimientos_inventario.json': [],
        'facturas_json/facturas.json': {},
        'cotizaciones_json/cotizaciones.json': {},
        'ultima_tasa_bcv.json': {
            "tasa_usd": 36.00,
            "tasa_eur": 39.00,
            "fecha": "2024-01-01"
        }
    }
    
    creados = 0
    actualizados = 0
    
    for archivo, datos_iniciales in archivos_json.items():
        try:
            # Crear directorio si no existe
            directorio = os.path.dirname(archivo)
            if directorio and not os.path.exists(directorio):
                os.makedirs(directorio, exist_ok=True)
            
            # Verificar si el archivo existe
            if os.path.exists(archivo):
                # Verificar que sea JSON válido
                try:
                    with open(archivo, 'r', encoding='utf-8') as f:
                        json.load(f)
                    print_info(f"Ya existe y es válido: {archivo}")
                except json.JSONDecodeError:
                    # Archivo corrupto, crear uno nuevo
                    with open(archivo, 'w', encoding='utf-8') as f:
                        json.dump(datos_iniciales, f, ensure_ascii=False, indent=4)
                    print_ok(f"Corregido: {archivo}")
                    actualizados += 1
            else:
                # Crear archivo nuevo
                with open(archivo, 'w', encoding='utf-8') as f:
                    json.dump(datos_iniciales, f, ensure_ascii=False, indent=4)
                print_ok(f"Creado: {archivo}")
                creados += 1
        except Exception as e:
            print_error(f"Error con {archivo}: {e}")
    
    print_ok(f"Se crearon {creados} archivos nuevos y se corrigieron {actualizados}")
    return True

def instalar_dependencias():
    """Instala las dependencias de Python"""
    print_seccion("INSTALACIÓN DE DEPENDENCIAS")
    
    if not os.path.exists('requirements.txt'):
        print_error("No se encuentra requirements.txt")
        return False
    
    print_info("Instalando dependencias desde requirements.txt...")
    print_info("Esto puede tardar varios minutos...")
    
    # Actualizar pip primero
    print_info("Actualizando pip...")
    ejecutar_comando(f"{sys.executable} -m pip install --upgrade pip", "Actualizando pip", mostrar_salida=False)
    
    # Instalar dependencias
    if ejecutar_comando(f"{sys.executable} -m pip install -r requirements.txt", "Instalando dependencias", mostrar_salida=False):
        print_ok("Dependencias instaladas correctamente")
        return True
    else:
        print_error("Error instalando dependencias")
        print_info("Intenta ejecutar manualmente: pip install -r requirements.txt")
        return False

def verificar_configuracion():
    """Verifica y crea config_sistema.json si no existe"""
    print_seccion("VERIFICACIÓN DE CONFIGURACIÓN")
    
    if not os.path.exists('config_sistema.json'):
        print_info("Creando config_sistema.json con valores por defecto...")
        
        config_default = {
            "nombre_sistema": "Sistema de Gestión Técnica",
            "moneda_sistema": "USD",
            "tasa_actual_usd": 36.00,
            "tasa_actual_eur": 39.00,
            "ultima_actualizacion": "",
            "impuestos": {
                "iva": 16.0,
                "retencion_iva": 75.0
            },
            "configuracion_general": {
                "backup_automatico": True,
                "notificaciones_email": False,
                "notificaciones_whatsapp": False
            }
        }
        
        try:
            with open('config_sistema.json', 'w', encoding='utf-8') as f:
                json.dump(config_default, f, ensure_ascii=False, indent=4)
            print_ok("config_sistema.json creado con valores por defecto")
            print_info("Puedes personalizar la configuración desde la interfaz web")
        except Exception as e:
            print_error(f"Error creando config_sistema.json: {e}")
            return False
    else:
        print_ok("config_sistema.json ya existe")
        try:
            with open('config_sistema.json', 'r', encoding='utf-8') as f:
                json.load(f)
            print_ok("config_sistema.json es válido")
        except json.JSONDecodeError as e:
            print_error(f"config_sistema.json tiene errores: {e}")
            return False
    
    return True

def crear_usuario_admin():
    """Crea un usuario administrador inicial si no existe"""
    print_seccion("VERIFICACIÓN DE USUARIOS")
    
    if not os.path.exists('usuarios.json'):
        print_info("No existe usuarios.json, se creará automáticamente al iniciar la app")
        return True
    
    try:
        with open('usuarios.json', 'r', encoding='utf-8') as f:
            usuarios = json.load(f)
        
        if usuarios and len(usuarios) > 0:
            print_ok(f"Encontrados {len(usuarios)} usuarios")
            return True
        else:
            print_info("No hay usuarios registrados")
            print_info("Debes crear un usuario administrador desde la interfaz web")
            return True
    except Exception as e:
        print_error(f"Error leyendo usuarios.json: {e}")
        return False

def verificar_archivos_requeridos():
    """Verifica que existan los archivos esenciales"""
    print_seccion("VERIFICACIÓN DE ARCHIVOS ESENCIALES")
    
    archivos_requeridos = [
        'app.py',
        'requirements.txt',
        'templates/base.html'
    ]
    
    faltantes = []
    for archivo in archivos_requeridos:
        if os.path.exists(archivo):
            print_ok(f"✓ {archivo}")
        else:
            print_error(f"✗ {archivo} - NO ENCONTRADO")
            faltantes.append(archivo)
    
    if faltantes:
        print_error("Faltan archivos esenciales. Asegúrate de copiar todos los archivos del sistema.")
        return False
    
    return True

def main():
    """Función principal de instalación"""
    print("\n" + "="*80)
    print("🚀 INSTALACIÓN DEL SISTEMA DE GESTIÓN TÉCNICA")
    print("="*80)
    print("\nEste script configurará todo lo necesario para ejecutar la aplicación.\n")
    
    # Verificar que estamos en el directorio correcto
    if not os.path.exists('app.py'):
        print_error("No se encuentra app.py en el directorio actual")
        print_info("Por favor, ejecuta este script desde el directorio del proyecto")
        return False
    
    pasos = [
        ("Python", verificar_python),
        ("Archivos Requeridos", verificar_archivos_requeridos),
        ("Directorios", crear_directorios),
        ("Archivos JSON", crear_archivos_json),
        ("Configuración", verificar_configuracion),
        ("Dependencias", instalar_dependencias),
        ("Usuarios", crear_usuario_admin)
    ]
    
    resultados = {}
    for nombre, funcion in pasos:
        try:
            resultados[nombre] = funcion()
        except Exception as e:
            print_error(f"Error en {nombre}: {e}")
            resultados[nombre] = False
    
    # Resumen final
    print_seccion("RESUMEN DE INSTALACIÓN")
    
    exitosos = sum(1 for v in resultados.values() if v)
    total = len(resultados)
    
    for nombre, resultado in resultados.items():
        if resultado:
            print_ok(f"{nombre}: ✓")
        else:
            print_error(f"{nombre}: ✗")
    
    print(f"\n{'='*80}")
    print(f"📈 Progreso: {exitosos}/{total} pasos completados")
    print("="*80)
    
    if exitosos == total:
        print("\n🎉 ¡INSTALACIÓN COMPLETADA EXITOSAMENTE!")
        print("\n📝 Próximos pasos:")
        print("   1. Ejecuta el diagnóstico: python diagnostico_sistema.py")
        print("   2. Inicia la aplicación: python app.py")
        print("   3. Abre tu navegador en: http://localhost:5000")
        print("   4. Crea tu primer usuario administrador")
        print("\n" + "="*80)
        return True
    else:
        print("\n⚠️  HAY PROBLEMAS QUE RESOLVER:")
        if not resultados.get('Python'):
            print("\n   1. Instala Python 3.8 o superior desde: https://www.python.org/downloads/")
        if not resultados.get('Dependencias'):
            print("\n   2. Instala las dependencias manualmente:")
            print("      pip install -r requirements.txt")
        print("\n   Después de resolver los problemas, ejecuta este script nuevamente.")
        print("\n" + "="*80)
        return False

if __name__ == "__main__":
    try:
        exito = main()
        sys.exit(0 if exito else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️ Instalación cancelada por el usuario")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error inesperado: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

