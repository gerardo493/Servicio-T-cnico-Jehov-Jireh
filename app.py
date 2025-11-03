# -*- coding: utf-8 -*-
import json
import os
import urllib3
import urllib.parse
import requests
import csv
import qrcode
import io
import base64
import traceback
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, make_response, send_file, session, abort, send_from_directory
from werkzeug.utils import secure_filename
# SOLUCIÓN: Importar CSRFProtect de manera compatible
try:
    from flask_wtf.csrf import CSRFProtect
except ImportError:
    # Fallback para versiones más nuevas
    from flask_wtf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash
from config_maps import get_maps_config
from seguridad_fiscal import seguridad_fiscal
from numeracion_fiscal import control_numeracion
from comunicacion_seniat import comunicador_seniat
from exportacion_seniat import exportador_seniat
from filtros_dashboard import obtener_estadisticas_filtradas, obtener_opciones_filtro, obtener_metricas_tarjeta, obtener_opciones_filtro_avanzado
try:
    import pdfkit
except ImportError:
    pdfkit = None
from functools import wraps
import re
from uuid import uuid4
import zipfile
from io import StringIO
from flask_sqlalchemy import SQLAlchemy
import copy

# --- Inicializar la Aplicación Flask ---
app = Flask(__name__)

# Clase para hacer que los diccionarios sean accesibles con notación de punto en Jinja2
class DotDict(dict):
    """Permite acceso a diccionarios con notación de punto"""
    def __init__(self, *args, **kwargs):
        super().__init__()
        # Manejar argumentos de inicialización
        if args:
            if isinstance(args[0], dict):
                for key, value in args[0].items():
                    if isinstance(value, dict) and not isinstance(value, DotDict):
                        self[key] = DotDict(value)
                    else:
                        self[key] = value
            else:
                super().__init__(*args, **kwargs)
        else:
            # Manejar kwargs
            for key, value in kwargs.items():
                if isinstance(value, dict) and not isinstance(value, DotDict):
                    self[key] = DotDict(value)
                else:
                    self[key] = value
    
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{key}'")
    
    def __setattr__(self, key, value):
        # Si el valor es un dict, convertirlo a DotDict
        if isinstance(value, dict) and not isinstance(value, DotDict):
            value = DotDict(value)
        # Usar super().__setitem__ para evitar recursión infinita
        super().__setitem__(key, value)
    
    def __setitem__(self, key, value):
        # Si el valor es un dict, convertirlo a DotDict
        if isinstance(value, dict) and not isinstance(value, DotDict):
            value = DotDict(value)
        super().__setitem__(key, value)
    
    def to_dict(self):
        """Convierte recursivamente DotDict a diccionario normal"""
        result = {}
        for key, value in self.items():
            if isinstance(value, DotDict):
                result[key] = value.to_dict()
            elif isinstance(value, list):
                result[key] = [item.to_dict() if isinstance(item, DotDict) else item for item in value]
            else:
                result[key] = value
        return result

# --- Configuración de la Aplicación ---
app.config['SECRET_KEY'] = 'tu_clave_secreta_aqui'
app.config['SESSION_COOKIE_SECURE'] = False  # Para desarrollo local
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)

# Contexto global para templates
@app.context_processor
def inject_alertas():
    """Inyecta alertas activas en todos los templates"""
    try:
        config = cargar_configuracion()
        alertas_config = config.get('alertas', {})
        
        # Solo verificar alertas si hay alguna configurada como activa
        alertas_habilitadas = [
            k for k, v in alertas_config.items() 
            if isinstance(v, bool) and v and k not in ['canal_notificacion', 'horario_alertas']
        ]
        
        # Solo cargar alertas si hay al menos una habilitada (para no sobrecargar)
        if alertas_habilitadas:
            alertas_activas = verificar_alertas()
        else:
            alertas_activas = []
        
        return {
            'alertas_activas': alertas_activas,
            'total_alertas': len(alertas_activas),
            'alertas_config': alertas_config
        }
    except Exception as e:
        print(f"Error inyectando alertas: {e}")
        return {
            'alertas_activas': [],
            'total_alertas': 0,
            'alertas_config': {}
        }

@app.context_processor
def inject_empresa():
    """
    Inyecta los datos de empresa en todos los templates.
    Usa config_sistema.json como fuente única de verdad.
    """
    try:
        empresa = cargar_empresa()
        # Asegurar que siempre devolvemos un dict válido con todos los campos necesarios
        if not isinstance(empresa, dict):
            empresa = {}
    except Exception as e:
        print(f"⚠️ Error cargando empresa en inject_empresa: {e}")
        empresa = {
            "nombre": "Servicio Técnico Jehová Jireh",
            "rif": "J-000000000",
            "telefono": "0000-0000000",
            "direccion": "Dirección de la empresa",
            "ciudad": "",
            "estado": "",
            "pais": "Venezuela",
            "whatsapp": "",
            "email": "",
            "website": "",
            "instagram": "",
            "descripcion": "",
            "horario": "",
            "logo_path": "static/logo.png"
        }
    
    return {
        'empresa': empresa,
        'moment': datetime.now
    }

# Función helper para convertir DotDict a dict para JSON
@app.template_filter('to_dict')
def to_dict_filter(obj):
    """Convierte DotDict a diccionario para serialización JSON"""
    if isinstance(obj, DotDict):
        return obj.to_dict()
    elif isinstance(obj, dict):
        return {k: to_dict_filter(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [to_dict_filter(item) for item in obj]
    else:
        return obj

# Filtro para parsear JSON strings
@app.template_filter('from_json')
def from_json_filter(value):
    """Convierte un string JSON a objeto"""
    import json
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []
    return value

# Función para formatear números
def fmt_num(value):
    """Formatear números con separadores de miles"""
    try:
        if value is None:
            return "0.00"
        return f"{safe_float(value):,.2f}"
    except (ValueError, TypeError):
        return "0.00"

# Registrar la función como filtro de Jinja2
app.jinja_env.filters['fmt_num'] = fmt_num
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# --- Configuración CSRF ---
# DESHABILITADO COMPLETAMENTE PARA RESOLVER ERRORES
app.config['WTF_CSRF_ENABLED'] = False
app.config['WTF_CSRF_TIME_LIMIT'] = 3600  # 1 hora
app.config['WTF_CSRF_SSL_STRICT'] = False  # Para desarrollo local
app.config['WTF_CSRF_HEADERS'] = ['X-CSRFToken']  # Headers personalizados

# --- Inicializar CSRF ---
# CSRF se inicializa más adelante en la línea 1009 después de configurar la app
# Mantener esta variable como None por ahora para evitar conflictos
csrf = None

# --- Helper para Tokens CSRF ---
def get_csrf_token():
    """Genera un token CSRF válido"""
    if csrf:
        return csrf._get_token()
    return None

# --- Constantes ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
IMAGENES_PRODUCTOS_FOLDER = os.path.join(BASE_DIR, 'static', 'imagenes_productos')
ARCHIVO_CLIENTES = 'clientes.json'
ARCHIVO_INVENTARIO = 'inventario.json'
ARCHIVO_FACTURAS = 'facturas_json/facturas.json'
ARCHIVO_CUENTAS = 'cuentas_por_cobrar.json'
ARCHIVO_NOTAS_ENTREGA = 'notas_entrega.json'
ARCHIVO_PAGOS_RECIBIDOS = 'pagos_recibidos.json'
ULTIMA_TASA_BCV_FILE = 'ultima_tasa_bcv.json'
ALLOWED_EXTENSIONS = {'csv', 'jpg', 'jpeg', 'png', 'gif', 'pdf'}
BITACORA_FILE = 'bitacora.log'

# --- Funciones de Utilidad ---

def cargar_datos(nombre_archivo):
    """Carga datos desde un archivo JSON."""
    try:
        # Asegurar que el directorio existe
        directorio = os.path.dirname(nombre_archivo)
        if directorio:  # Si hay un directorio en la ruta
            os.makedirs(directorio, exist_ok=True)
            
        if not os.path.exists(nombre_archivo):
            print(f"Archivo {nombre_archivo} no existe. Creando nuevo archivo.")
            with open(nombre_archivo, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False, indent=4)
            return {}
            
        with open(nombre_archivo, 'r', encoding='utf-8') as f:
            contenido = f.read()
            if not contenido.strip():
                print(f"Archivo {nombre_archivo} está vacío.")
                return {}
            try:
                return json.loads(contenido)
            except json.JSONDecodeError as e:
                print(f"Error decodificando JSON en {nombre_archivo}: {e}")
                return {}
    except Exception as e:
        print(f"Error leyendo {nombre_archivo}: {e}")
        return {}

def cargar_json_seguro(json_str, default=None):
    """Carga JSON de forma segura, retorna default si falla"""
    if default is None:
        default = []
    if not json_str:
        return default
    try:
        if isinstance(json_str, list):
            return json_str
        elif isinstance(json_str, str):
            return json.loads(json_str)
        else:
            return default
    except (json.JSONDecodeError, TypeError) as e:
        print(f"Error parseando JSON: {e}")
        return default

def parsear_fecha_segura(fecha_str, formatos=['%Y-%m-%d', '%d/%m/%Y', '%Y-%m-%d %H:%M:%S'], default=None):
    """Intenta parsear fecha con múltiples formatos, retorna default si falla"""
    if not fecha_str:
        return default
    for formato in formatos:
        try:
            return datetime.strptime(fecha_str, formato)
        except ValueError:
            continue
    return default

def guardar_datos(nombre_archivo, datos):
    """Guarda datos en un archivo JSON."""
    try:
        # Asegurar que el directorio existe
        directorio = os.path.dirname(nombre_archivo)
        if directorio:  # Si hay un directorio en la ruta
            try:
                os.makedirs(directorio, exist_ok=True)
                print(f"Directorio {directorio} creado/verificado exitosamente")
            except Exception as e:
                print(f"Error creando directorio {directorio}: {e}")
                return False
        
        # Verificar que los datos son serializables
        try:
            json.dumps(datos)
        except Exception as e:
            print(f"Error serializando datos: {e}")
            return False
        
        # Intentar guardar con manejo de errores específico
        try:
            # Primero intentamos escribir en un archivo temporal
            temp_file = nombre_archivo + '.tmp'
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(datos, f, ensure_ascii=False, indent=4)
            
            # Si la escritura temporal fue exitosa, reemplazamos el archivo original
            if os.path.exists(nombre_archivo):
                os.remove(nombre_archivo)
            os.rename(temp_file, nombre_archivo)
            
            print(f"Datos guardados exitosamente en {nombre_archivo}")
            return True
        except Exception as e:
            print(f"Error escribiendo en archivo {nombre_archivo}: {e}")
            # Limpiar archivo temporal si existe
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass
            return False
    except Exception as e:
        print(f"Error general guardando {nombre_archivo}: {e}")
        return False

def guardar_ultima_tasa_bcv(tasa):
    """
    Guarda la tasa BCV en config_sistema.json (fuente principal) 
    y también en ultima_tasa_bcv.json (compatibilidad).
    """
    try:
        tasa_valor = safe_float(tasa)
        if not tasa_valor or tasa_valor < 10:
            print(f"⚠️ Tasa inválida para guardar: {tasa}")
            return False
        
        # 1. Guardar en config_sistema.json (fuente principal)
        try:
            config = cargar_configuracion()
            if 'tasas' not in config:
                config['tasas'] = {}
            
            config['tasas']['tasa_actual_usd'] = round(tasa_valor, 2)
            config['tasas']['ultima_actualizacion'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            if guardar_configuracion(config):
                print(f"✅ Tasa BCV guardada en config_sistema.json: {tasa_valor}")
            else:
                print(f"⚠️ Error guardando tasa en config_sistema.json")
        except Exception as e:
            print(f"⚠️ Error guardando tasa en config_sistema.json: {e}")
        
        # 2. Guardar también en ultima_tasa_bcv.json (compatibilidad hacia atrás)
        try:
            data = {
                'tasa': tasa_valor,
                'fecha': datetime.now().isoformat(),
                'ultima_actualizacion': datetime.now().isoformat()
            }
            
            with open(ULTIMA_TASA_BCV_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            
            print(f"✅ Tasa BCV guardada también en {ULTIMA_TASA_BCV_FILE}: {tasa_valor}")
        except Exception as e:
            print(f"⚠️ Error guardando en {ULTIMA_TASA_BCV_FILE}: {e}")
            
        # 3. Registrar en bitácora si hay sesión activa
        try:
            from flask import has_request_context
            if has_request_context() and 'usuario' in session:
                registrar_bitacora(session['usuario'], 'Actualizar tasa BCV', f'Tasa: {tasa_valor}')
            else:
                registrar_bitacora('Sistema', 'Actualizar tasa BCV', f'Tasa: {tasa_valor}')
        except Exception as e:
            print(f"⚠️ Error registrando en bitácora: {e}")
                
        return True
            
    except Exception as e:
        print(f"⚠️ Error general en guardar_ultima_tasa_bcv: {e}")
        return False

def cargar_ultima_tasa_bcv():
    """
    Carga la última tasa BCV desde config_sistema.json (fuente principal).
    Si no está disponible, intenta cargar desde ultima_tasa_bcv.json.
    """
    try:
        # 1. Primero intentar desde config_sistema.json
        config = cargar_configuracion()
        tasas_config = config.get('tasas', {})
        tasa_usd = safe_float(tasas_config.get('tasa_actual_usd', 0))
        
        if tasa_usd and tasa_usd > 10:
            return tasa_usd
        
        # 2. Si no hay en config, intentar desde ultima_tasa_bcv.json (legacy)
        if os.path.exists(ULTIMA_TASA_BCV_FILE):
            try:
                with open(ULTIMA_TASA_BCV_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    tasa_legacy = safe_float(data.get('tasa', 0))
                    
                    if tasa_legacy and tasa_legacy > 10:
                        # Migrar a config_sistema.json si es válida
                        if 'tasas' not in config:
                            config['tasas'] = {}
                        config['tasas']['tasa_actual_usd'] = round(tasa_legacy, 2)
                        config['tasas']['ultima_actualizacion'] = data.get('fecha', datetime.now().isoformat())
                        guardar_configuracion(config)
                        print(f"✅ Tasa migrada desde {ULTIMA_TASA_BCV_FILE} a config_sistema.json")
                        return tasa_legacy
            except Exception as e:
                print(f"⚠️ Error leyendo {ULTIMA_TASA_BCV_FILE}: {e}")
        
        return None
        
    except Exception as e:
        print(f"⚠️ Error cargando última tasa BCV: {e}")
        return None

def obtener_ultima_tasa_del_sistema():
    try:
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        tasas_encontradas = []
        
        for nota in notas.values():
            if nota.get('tasa_bcv'):
                try:
                    tasa = safe_float(nota['tasa_bcv'])
                    if tasa > 10:
                        tasas_encontradas.append(tasa)
                except:
                    continue
        
        # Buscar en cuentas por cobrar si existen
        try:
            cuentas = cargar_datos(ARCHIVO_CUENTAS)
            for cuenta in cuentas.values():
                if cuenta.get('tasa_bcv'):
                    try:
                        tasa = safe_float(cuenta['tasa_bcv'])
                        if tasa > 10:
                            tasas_encontradas.append(tasa)
                    except:
                        continue
        except:
            pass
        
        if tasas_encontradas:
            # Usar la tasa más alta (más reciente) del sistema
            tasa_mas_reciente = max(tasas_encontradas)
            print(f"Tasa encontrada en el sistema: {tasa_mas_reciente}")
            return tasa_mas_reciente
        
        return None
        
    except Exception as e:
        print(f"Error buscando tasa en el sistema: {e}")
        return None

def inicializar_archivos_por_defecto():
    """Inicializa archivos necesarios si no existen."""
    try:
        # Crear archivo de tasa BCV por defecto si no existe
        if not os.path.exists(ULTIMA_TASA_BCV_FILE):
            # Intentar obtener la tasa más reciente del sistema
            tasa_sistema = obtener_ultima_tasa_del_sistema()
            
            if tasa_sistema and tasa_sistema > 10:
                tasa_default = tasa_sistema
                print(f"Usando tasa del sistema: {tasa_default}")
            else:
                # Solo usar tasa por defecto si no hay ninguna en el sistema
                tasa_default = 135.0  # Tasa más reciente conocida
                print(f"Usando tasa por defecto del sistema: {tasa_default}")
            
            with open(ULTIMA_TASA_BCV_FILE, 'w', encoding='utf-8') as f:
                json.dump({'tasa': tasa_default, 'fecha': datetime.now().isoformat()}, f)
            print(f"Archivo de tasa BCV creado con tasa: {tasa_default}")
    except Exception as e:
        print(f"Error inicializando archivos por defecto: {e}")

def actualizar_tasa_bcv_automaticamente():
    """Actualiza la tasa BCV automáticamente si han pasado más de 24 horas."""
    try:
        if not os.path.exists(ULTIMA_TASA_BCV_FILE):
            print("Archivo de tasa BCV no existe, creando...")
            inicializar_archivos_por_defecto()
            return
        
        with open(ULTIMA_TASA_BCV_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            ultima_actualizacion = data.get('fecha', '')
        
        if ultima_actualizacion:
            try:
                ultima_fecha = datetime.fromisoformat(ultima_actualizacion)
                tiempo_transcurrido = datetime.now() - ultima_fecha
                
                # Actualizar si han pasado más de 24 horas
                if tiempo_transcurrido.total_seconds() > 24 * 3600:
                    print("🔄 Han pasado más de 24 horas, actualizando tasa BCV automáticamente...")
                    nueva_tasa = obtener_tasa_bcv_dia()
                    if nueva_tasa and nueva_tasa > 10:
                        print(f"✅ Tasa BCV actualizada automáticamente: {nueva_tasa}")
                    else:
                        print("❌ No se pudo actualizar la tasa BCV automáticamente")
                        # Intentar usar tasa del sistema como fallback
                        tasa_sistema = obtener_ultima_tasa_del_sistema()
                        if tasa_sistema and tasa_sistema > 10:
                            print(f"WARNING Usando tasa del sistema como fallback: {tasa_sistema}")
                            guardar_ultima_tasa_bcv(tasa_sistema)
                else:
                    print(f"⏰ Tasa BCV actualizada recientemente, no es necesario actualizar")
                    # Aún así, verificar si hay una tasa más reciente disponible
                    print("🔍 Verificando si hay tasa más reciente disponible...")
                    tasa_web = obtener_tasa_bcv_dia()
                    if tasa_web and tasa_web > 0:
                        print(f"🎯 Tasa más reciente encontrada: {tasa_web}")
                        guardar_ultima_tasa_bcv(tasa_web)
            except Exception as e:
                print(f"Error verificando fecha de actualización: {e}")
        else:
            # Si no hay fecha, verificar si la tasa actual es válida
            tasa_actual = data.get('tasa', 0)
            if not tasa_actual or tasa_actual <= 10:
                print("Tasa BCV no válida, buscando en el sistema...")
                tasa_sistema = obtener_ultima_tasa_del_sistema()
                if tasa_sistema and tasa_sistema > 10:
                    print(f"Actualizando con tasa del sistema: {tasa_sistema}")
                    guardar_ultima_tasa_bcv(tasa_sistema)
        
    except Exception as e:
        print(f"Error en actualización automática de tasa BCV: {e}")
        # En caso de error, intentar usar tasa del sistema
        try:
            tasa_sistema = obtener_ultima_tasa_del_sistema()
            if tasa_sistema and tasa_sistema > 10:
                print(f"Usando tasa del sistema después de error: {tasa_sistema}")
                guardar_ultima_tasa_bcv(tasa_sistema)
        except:
            pass

def registrar_bitacora(usuario, accion, detalles='', documento_tipo='', documento_numero=''):
    """
    Función mejorada de bitácora que mantiene compatibilidad y agrega funcionalidad SENIAT
    """
    from datetime import datetime
    from flask import has_request_context, request, session
    
    # Sistema de bitácora tradicional (para compatibilidad)
    ip = ''
    ubicacion = ''
    lat = ''
    lon = ''
    
    try:
        if has_request_context():
            ip = request.headers.get('X-Forwarded-For', request.remote_addr)
            if ip == '127.0.0.1':
                ip = '190.202.123.123'  # IP pública de Venezuela para pruebas
        # Usar ubicación precisa si está en session
        if has_request_context() and 'ubicacion_precisa' in session:
            lat = session['ubicacion_precisa'].get('lat', '')
            lon = session['ubicacion_precisa'].get('lon', '')
            ubicacion = session['ubicacion_precisa'].get('texto', '')
        elif has_request_context():
            resp = requests.get(f'http://ip-api.com/json/{ip}', timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('status') == 'success':
                    lat = data.get('lat', '')
                    lon = data.get('lon', '')
                    ubicacion = ', '.join([v for v in [data.get('city', ''), data.get('regionName', ''), data.get('country', '')] if v])
                else:
                    ubicacion = f"API sin datos: {data}"
            else:
                ubicacion = f"API status: {resp.status_code}"
    except Exception as e:
        # Si hay algún error al acceder a Flask objects o API, usar valores por defecto
        print(f"Error en registrar_bitacora: {e}")
        ip = 'N/A'
        ubicacion = 'N/A'
        lat = ''
        lon = ''
    
    # Bitácora tradicional
    linea = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Usuario: {usuario} | Acción: {accion} | Detalles: {detalles} | IP: {ip} | Ubicación: {ubicacion} | Coordenadas: {lat},{lon}\n"
    with open(BITACORA_FILE, 'a', encoding='utf-8') as f:
        f.write(linea)
    
    # Sistema de auditoría fiscal SENIAT (cuando aplique)
    if documento_tipo or documento_numero or 'nota' in accion.lower() or 'fiscal' in accion.lower():
        try:
            seguridad_fiscal.registrar_log_fiscal(
                usuario=usuario,
                accion=accion,
                documento_tipo=documento_tipo or 'GENERAL',
                documento_numero=documento_numero or 'N/A',
                ip_externa=ip,
                detalles=detalles
            )
        except Exception as e:
            # En caso de error en logs fiscales, registrar en bitácora tradicional
            error_linea = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ERROR_LOG_FISCAL: {str(e)}\n"
            with open(BITACORA_FILE, 'a', encoding='utf-8') as f:
                f.write(error_linea)
    
    # Retornar éxito
    return True

# Decorador para requerir login
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'usuario' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'usuario' not in session:
            return redirect(url_for('login'))
        # Verificar si es admin (puedes ajustar esta lógica según tu sistema)
        if session.get('usuario') != 'admin':
            flash('No tiene permisos de administrador para acceder a esta página', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def verify_password(username, password):
    """Verifica la contraseña de un usuario."""
    try:
        usuarios = cargar_datos('usuarios.json')
        
        # Verificar formato antiguo (directo)
        if username in usuarios:
            user_data = usuarios[username]
            if 'password' in user_data:
                return check_password_hash(user_data['password'], password)
        
        # Verificar formato nuevo (con subcarpeta 'usuarios')
        if 'usuarios' in usuarios and username in usuarios['usuarios']:
            user_data = usuarios['usuarios'][username]
            
            # Verificar hash SHA-256
            if 'password_hash' in user_data:
                import hashlib
                password_hash = hashlib.sha256(password.encode()).hexdigest()
                return password_hash == user_data['password_hash']
            
            # Verificar hash de Werkzeug
            if 'password' in user_data:
                return check_password_hash(user_data['password'], password)
        
        return False
    except Exception as e:
        print(f"Error verificando contraseña: {e}")
        return False

def safe_float(value, default=0.0):
    """Convierte un valor a float de forma segura."""
    try:
        if value is None:
            return default
        # Convertir a string, reemplazar comas por puntos, y convertir a float
        return float(str(value).replace(',', '.'))
    except (ValueError, TypeError):
        return default

def obtener_estadisticas():
    """Obtiene estadísticas para el dashboard."""
    clientes = cargar_datos(ARCHIVO_CLIENTES)
    inventario = cargar_datos(ARCHIVO_INVENTARIO)
    notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
    mes_actual = datetime.now().month
    total_clientes = len(clientes)
    total_productos = len(inventario)
    # Contar notas del mes actual con manejo de errores
    notas_mes = 0
    for n in notas.values():
        fecha_str = n.get('fecha', '')
        if fecha_str:
            try:
                fecha_dt = datetime.strptime(fecha_str, '%Y-%m-%d')
                if fecha_dt.month == mes_actual:
                    notas_mes += 1
            except (ValueError, TypeError):
                # Si la fecha no tiene formato válido, continuar con la siguiente
                continue
    total_cobrar_usd = 0
    for n in notas.values():
        total_nota = safe_float(n.get('total_usd', 0))
        total_abonado = safe_float(n.get('total_abonado', 0))
        saldo = max(0, total_nota - total_abonado)
        if saldo > 0:  # Considerar cualquier saldo mayor a 0
            total_cobrar_usd += saldo
    # Asegura que tasa_bcv sea float y no Response
    tasa_bcv = obtener_tasa_bcv()
    if hasattr(tasa_bcv, 'json'):
        # Si es un Response, extrae el valor
        try:
            tasa_bcv = tasa_bcv.json.get('tasa', 1.0)
        except Exception:
            tasa_bcv = 1.0
    try:
        tasa_bcv = safe_float(tasa_bcv)
    except Exception:
        tasa_bcv = 1.0
    total_cobrar_bs = total_cobrar_usd * tasa_bcv
    notas_con_id = []
    for nota_id, nota in notas.items():
        nota_copia = nota.copy()
        
        # Obtener solo el nombre del cliente
        cliente_id = nota.get('cliente_id', '')
        if cliente_id and cliente_id in clientes:
            nota_copia['cliente'] = clientes[cliente_id].get('nombre', 'Cliente no encontrado')
        else:
            nota_copia['cliente'] = 'Cliente no encontrado'
            
        notas_con_id.append(nota_copia)
    
    # Ordenar notas por fecha con manejo de errores
    def obtener_fecha_orden(nota):
        fecha_str = nota.get('fecha', '')
        if fecha_str:
            try:
                return datetime.strptime(fecha_str, '%Y-%m-%d')
            except (ValueError, TypeError):
                # Si la fecha es inválida, usar fecha mínima para que aparezcan al final
                return datetime.min
        return datetime.min
    
    ultimas_notas = sorted(notas_con_id, key=obtener_fecha_orden, reverse=True)[:5]
    productos_bajo_stock = [p for p in inventario.values() if int(p.get('cantidad', 0)) < 10]
    
    # Obtener órdenes de servicio pendientes
    ordenes_servicio = cargar_datos('ordenes_servicio.json')
    if not isinstance(ordenes_servicio, dict):
        ordenes_servicio = {}
    
    ordenes_pendientes = []
    for orden_id, orden in ordenes_servicio.items():
        # Validar que orden es un diccionario
        if not isinstance(orden, dict):
            continue
            
        estado = orden.get('estado', '')
        if estado in ['pendiente', 'en_proceso', 'diagnostico', 'en_espera_revision']:
            # Convertir a DotDict para que el template pueda usar notación de punto
            orden_copia = DotDict(orden.copy())
            orden_copia['id'] = orden_id
            orden_copia.id = orden_id  # También como atributo
            
            # Obtener nombre del cliente
            cliente_id = orden.get('cliente_id', '')
            if cliente_id and cliente_id in clientes:
                orden_copia['cliente'] = clientes[cliente_id].get('nombre', 'Cliente no encontrado')
            else:
                # Si no hay cliente_id, usar el nombre del cliente directamente
                cliente_info = orden.get('cliente', {})
                if isinstance(cliente_info, dict):
                    orden_copia['cliente'] = cliente_info.get('nombre', 'Cliente no encontrado')
                else:
                    orden_copia['cliente'] = 'Cliente no encontrado'
            
            # Asegurar que 'estado' existe
            if 'estado' not in orden_copia:
                orden_copia['estado'] = estado
            
            ordenes_pendientes.append(orden_copia)
    
    # Ordenar por fecha de creación (más recientes primero) y tomar las últimas 5
    ordenes_pendientes = sorted(ordenes_pendientes, key=lambda x: x.get('fecha_creacion', ''), reverse=True)[:5]
    
    # Calcular pagos recibidos del mes actual
    total_pagos_recibidos_usd = 0
    total_pagos_recibidos_bs = 0
    
    # Sumar pagos de las notas de entrega del mes actual
    for n in notas.values():
        if 'pagos' in n and n['pagos']:
            for pago in n['pagos']:
                fecha_nota = n.get('fecha', '')
                if fecha_nota:
                    fecha_dt = parsear_fecha_segura(fecha_nota, ['%Y-%m-%d'])
                    if fecha_dt and fecha_dt.month == mes_actual:
                        monto = safe_float(pago.get('monto', 0))
                        total_pagos_recibidos_usd += monto
                        total_pagos_recibidos_bs += monto * safe_float(n.get('tasa_bcv', tasa_bcv))
    
    # Sumar pagos del archivo pagos_recibidos.json del mes actual
    try:
        pagos_recibidos = cargar_datos(ARCHIVO_PAGOS_RECIBIDOS)
        if pagos_recibidos and isinstance(pagos_recibidos, dict):
            for pago_id, pago in pagos_recibidos.items():
                if not isinstance(pago, dict):
                    continue
                
                # Obtener fecha del pago
                fecha_pago = pago.get('fecha', '')
                if not fecha_pago:
                    continue
                
                try:
                    # Parsear fecha con múltiples formatos de forma segura
                    fecha_parseada = parsear_fecha_segura(fecha_pago, ['%Y-%m-%d', '%d/%m/%Y'])
                    
                    # Si la fecha es del mes actual, sumar al total
                    if fecha_parseada and fecha_parseada.month == mes_actual:
                        monto_usd = safe_float(pago.get('monto_usd', 0))
                        monto_bs = safe_float(pago.get('monto_bs', 0))
                        
                        # Si no tiene monto_bs, calcularlo usando tasa_bcv
                        if monto_bs == 0 and monto_usd > 0:
                            tasa_pago = safe_float(pago.get('tasa_bcv', tasa_bcv))
                            monto_bs = monto_usd * tasa_pago
                        
                        total_pagos_recibidos_usd += monto_usd
                        total_pagos_recibidos_bs += monto_bs
                except (ValueError, TypeError) as e:
                    print(f"DEBUG: Error procesando fecha de pago {pago_id}: {e}")
                    continue
    except Exception as e:
        print(f"DEBUG: Error cargando pagos recibidos para dashboard: {e}")
        # Continuar sin los pagos recibidos si hay error
    return {
        'total_clientes': total_clientes,
        'total_productos': total_productos,
        'notas_mes': notas_mes,
        'total_cobrar': f"{total_cobrar_usd:,.2f}",
        'total_cobrar_usd': total_cobrar_usd,
        'total_cobrar_bs': total_cobrar_bs,
        'tasa_bcv': tasa_bcv,
        'ultimas_notas': ultimas_notas,
        'productos_bajo_stock': productos_bajo_stock,
        'ordenes_pendientes': ordenes_pendientes,
        'total_pagos_recibidos_usd': total_pagos_recibidos_usd,
        'total_pagos_recibidos_bs': total_pagos_recibidos_bs
    }

def obtener_ordenes_estados_vencidos():
    """Verifica órdenes con estados vencidos según tiempos máximos configurados"""
    try:
        ordenes = cargar_datos('ordenes_servicio.json')
        config_sistema = cargar_configuracion()
        estados_config = config_sistema.get('estados_ordenes', {})
        
        ordenes_vencidas = []
        ahora = datetime.now()
        
        for orden_id, orden in ordenes.items():
            estado_actual = orden.get('estado', '')
            fecha_actualizacion = orden.get('fecha_actualizacion', orden.get('fecha_creacion', ''))
            
            if not fecha_actualizacion:
                continue
            
            # Obtener configuración del estado
            estado_config = estados_config.get(estado_actual, {})
            tiempo_maximo = estado_config.get('tiempo_maximo', 0)  # en horas
            
            if tiempo_maximo > 0:
                try:
                    try:
                        fecha_dt = datetime.strptime(fecha_actualizacion, '%Y-%m-%d %H:%M:%S')
                        horas_transcurridas = (ahora - fecha_dt).total_seconds() / 3600
                    except (ValueError, TypeError):
                        # Si la fecha no tiene formato válido, continuar con la siguiente orden
                        continue
                    
                    if horas_transcurridas > tiempo_maximo:
                        ordenes_vencidas.append({
                            'id': orden_id,
                            'cliente': orden.get('cliente', {}).get('nombre', 'Sin nombre'),
                            'estado': estado_actual,
                            'tiempo_excedido': round(horas_transcurridas - tiempo_maximo, 1),
                            'fecha_actualizacion': fecha_actualizacion
                        })
                except Exception as e:
                    print(f"Error procesando fecha para orden {orden_id}: {e}")
                    continue
        
        return ordenes_vencidas
    except Exception as e:
        print(f"Error obteniendo órdenes vencidas: {e}")
        return []

def obtener_tasa_bcv():
    """
    Obtiene la tasa BCV (USD/BS) desde config_sistema.json como fuente principal.
    Si no está disponible, intenta cargar desde ultima_tasa_bcv.json y migrar.
    """
    try:
        # 1. Primero intentar desde config_sistema.json
        config = cargar_configuracion()
        tasas_config = config.get('tasas', {})
        tasa_usd = safe_float(tasas_config.get('tasa_actual_usd', 0))
        
        if tasa_usd and tasa_usd > 10:
            print(f"✅ Tasa BCV obtenida desde config_sistema.json: {tasa_usd}")
            return tasa_usd
        
        # 2. Si no hay tasa en config, intentar migrar desde ultima_tasa_bcv.json
        if os.path.exists(ULTIMA_TASA_BCV_FILE):
            try:
                with open(ULTIMA_TASA_BCV_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    tasa_legacy = safe_float(data.get('tasa', 0))
                    
                    if tasa_legacy and tasa_legacy > 10:
                        # Migrar a config_sistema.json
                        if 'tasas' not in config:
                            config['tasas'] = {}
                        config['tasas']['tasa_actual_usd'] = round(tasa_legacy, 2)
                        config['tasas']['ultima_actualizacion'] = data.get('fecha', datetime.now().isoformat())
                        guardar_configuracion(config)
                        print(f"✅ Tasa migrada desde ultima_tasa_bcv.json a config_sistema.json: {tasa_legacy}")
                        return tasa_legacy
            except Exception as e:
                print(f"⚠️ Error leyendo ultima_tasa_bcv.json: {e}")
        
        # 3. Buscar en el sistema (notas de entrega, cuentas por cobrar)
        tasa_sistema = obtener_ultima_tasa_del_sistema()
        if tasa_sistema and tasa_sistema > 10:
            # Guardar en config para futuras consultas
            if 'tasas' not in config:
                config['tasas'] = {}
            config['tasas']['tasa_actual_usd'] = round(tasa_sistema, 2)
            config['tasas']['ultima_actualizacion'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            guardar_configuracion(config)
            print(f"✅ Tasa obtenida del sistema y guardada en config: {tasa_sistema}")
            return tasa_sistema
        
        # 4. Usar tasa por defecto de la configuración
        tasa_defecto = safe_float(tasas_config.get('tasa_usd_defecto', 216.37))
        if tasa_defecto and tasa_defecto > 10:
            print(f"⚠️ Usando tasa por defecto de configuración: {tasa_defecto}")
            return tasa_defecto
        
        print("⚠️ No se encontró tasa válida en ninguna fuente")
        return None
        
    except Exception as e:
        print(f"⚠️ Error inesperado obteniendo tasa BCV: {e}")
        return None

def obtener_tasa_bcv_dia():
    """Obtiene la tasa oficial USD/BS del BCV desde la web. Devuelve float o None si falla."""
    try:
        # SIEMPRE intentar obtener desde la web primero (no usar tasa local)
        url = 'https://www.bcv.org.ve/glosario/cambio-oficial'
        print(f"🔍 Obteniendo tasa BCV ACTUAL desde: {url}")
        
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        resp = requests.get(url, timeout=20, verify=False)
        
        if resp.status_code != 200:
            print(f"❌ Error HTTP al obtener tasa BCV: {resp.status_code}")
            return None
        
        print(f"✅ Página BCV obtenida exitosamente, analizando contenido...")
        soup = BeautifulSoup(resp.text, 'html.parser')
        tasa = None
        
        # Método 1: Buscar por id='dolar' (método principal)
        dolar_div = soup.find('div', id='dolar')
        if dolar_div:
            strong = dolar_div.find('strong')
            if strong:
                txt = strong.text.strip().replace('.', '').replace(',', '.')
                try:
                    posible = safe_float(txt)
                    if posible > 10:
                        tasa = posible
                        print(f"🎯 Tasa BCV encontrada por ID 'dolar': {tasa}")
                except:
                    pass
        
        # Método 2: Buscar por id='usd' (alternativo)
        if not tasa:
            usd_div = soup.find('div', id='usd')
            if usd_div:
                strong = usd_div.find('strong')
                if strong:
                    txt = strong.text.strip().replace('.', '').replace(',', '.')
                    try:
                        posible = safe_float(txt)
                        if posible > 10:
                            tasa = posible
                            print(f"🎯 Tasa BCV encontrada por ID 'usd': {tasa}")
                    except:
                        pass
        
        # Método 3: Buscar por strong con texto que parezca una tasa
        if not tasa:
            for strong in soup.find_all('strong'):
                txt = strong.text.strip().replace('.', '').replace(',', '.')
                try:
                    posible = safe_float(txt)
                    if 10 < posible < 500:  # Rango específico para tasa USD
                        tasa = posible
                        print(f"🎯 Tasa BCV encontrada por strong: {tasa}")
                        break
                except:
                    continue
        
        # Método 4: Buscar por span con clase específica
        if not tasa:
            for span in soup.find_all('span', class_='centrado'):
                txt = span.text.strip().replace('.', '').replace(',', '.')
                try:
                    posible = safe_float(txt)
                    if posible > 10 and posible < 1000:
                        tasa = posible
                        print(f"🎯 Tasa BCV encontrada por span: {tasa}")
                        break
                except:
                    continue
        
        # Método 5: Buscar por regex más específico
        if not tasa:
            import re
            # Buscar patrones como 36,50 o 36.50 (más específico)
            matches = re.findall(r'(\d{2,}[.,]\d{2,})', resp.text)
            for m in matches:
                try:
                    posible = safe_float(m.replace('.', '').replace(',', '.'))
                    if posible > 10 and posible < 1000:
                        tasa = posible
                        print(f"🎯 Tasa BCV encontrada por regex: {tasa}")
                        break
                except:
                    continue
        
        # Método 6: Buscar en tablas específicas
        if not tasa:
            for table in soup.find_all('table'):
                for row in table.find_all('tr'):
                    for cell in row.find_all(['td', 'th']):
                        txt = cell.text.strip().replace('.', '').replace(',', '.')
                        try:
                            posible = safe_float(txt)
                            if posible > 10 and posible < 1000:
                                tasa = posible
                                print(f"🎯 Tasa BCV encontrada en tabla: {tasa}")
                                break
                        except:
                            continue
                    if tasa:
                        break
                if tasa:
                    break
        
        # Método 7: Buscar por texto que contenga "USD" o "Dólar"
        if not tasa:
            for element in soup.find_all(['div', 'span', 'p']):
                if 'USD' in element.text or 'Dólar' in element.text or 'dólar' in element.text:
                    txt = element.text.strip()
                    # Extraer números del texto
                    import re
                    numbers = re.findall(r'(\d+[.,]\d+)', txt)
                    for num in numbers:
                        try:
                            posible = safe_float(num.replace('.', '').replace(',', '.'))
                            if posible > 10 and posible < 1000:
                                tasa = posible
                                print(f"🎯 Tasa BCV encontrada por texto USD: {tasa}")
                                break
                        except:
                            continue
                    if tasa:
                        break
        
        if tasa and tasa > 10:
            # Guardar la tasa en el archivo
            guardar_ultima_tasa_bcv(tasa)
            print(f"💾 Tasa BCV ACTUAL guardada exitosamente: {tasa}")
            return tasa
        else:
            print("❌ No se pudo encontrar una tasa BCV válida en la página")
            # Solo como último recurso, usar tasa local
            tasa_local = cargar_ultima_tasa_bcv()
            if tasa_local and tasa_local > 10:
                print(f"WARNING Usando tasa BCV local como fallback: {tasa_local}")
                return tasa_local
            return None
            
    except Exception as e:
        print(f"❌ Error obteniendo tasa BCV: {e}")
        # Solo como último recurso, usar tasa local
        try:
            tasa_fallback = cargar_ultima_tasa_bcv()
            if tasa_fallback and tasa_fallback > 10:
                print(f"WARNING Usando tasa BCV de fallback después de error: {tasa_fallback}")
                return tasa_fallback
        except:
            pass
        return None

# Llamar inicialización
inicializar_archivos_por_defecto()

# Ejecutar actualización automática al iniciar
actualizar_tasa_bcv_automaticamente()
# SECRET_KEY ya configurado arriba
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max-limit
csrf = CSRFProtect(app)

# --- Configuración de rutas de capturas (compatibles con Render y local) ---
# En Render no podemos escribir en /data. Usamos una carpeta del proyecto
# que en despliegue se enlaza a un disco persistente (storage) en el start command.
IS_RENDER = bool(os.environ.get('RENDER') or os.environ.get('RENDER_EXTERNAL_HOSTNAME'))
BASE_PATH = os.path.dirname(os.path.abspath(__file__))
CAPTURAS_FOLDER = os.path.join(BASE_PATH, 'uploads', 'capturas')
CAPTURAS_URL = '/uploads/capturas'

# Asegurar que las carpetas de capturas existen
os.makedirs(CAPTURAS_FOLDER, exist_ok=True)

@app.route('/uploads/capturas/<filename>')
def serve_captura(filename):
    try:
        return send_from_directory(CAPTURAS_FOLDER, filename)
    except Exception as e:
        print(f"Error sirviendo captura {filename}: {str(e)}")
        abort(404)

# --- Healthcheck ---
@app.route('/healthz')
def healthcheck():
    try:
        now = datetime.utcnow().isoformat() + 'Z'
        # Verificar que las carpetas críticas existen
        critical_dirs = [
            os.path.join(BASE_PATH, 'uploads'),
            os.path.join(BASE_PATH, 'uploads', 'capturas')
        ]
        for d in critical_dirs:
            os.makedirs(d, exist_ok=True)
        return jsonify({
            'status': 'ok',
            'time': now
        }), 200
    except Exception as e:
        return jsonify({'status': 'error', 'detail': str(e)}), 500

# --- Funciones de Utilidad ---
def allowed_file(filename):
    """Verifica si la extensión del archivo está permitida."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def guardar_imagen_producto(imagen, producto_id):
    """Guarda la imagen de un producto y retorna la ruta relativa con '/' como separador."""
    if imagen and allowed_file(imagen.filename):
        # Generar nombre único para la imagen
        extension = imagen.filename.rsplit('.', 1)[1].lower()
        nombre_archivo = f"producto_{producto_id}.{extension}"
        ruta_archivo = os.path.join(IMAGENES_PRODUCTOS_FOLDER, nombre_archivo)
        
        # Guardar la imagen
        imagen.save(ruta_archivo)
        
        # Retornar la ruta relativa para guardar en la base de datos (siempre con /)
        return f"imagenes_productos/{nombre_archivo}"
    return None

def generar_qr_producto(data, producto_id):
    """Genera un código QR para un producto y retorna la ruta de la imagen."""
    try:
        # Crear el código QR
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(data)
        qr.make(fit=True)
        
        # Crear la imagen
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Guardar la imagen
        qr_filename = f"qr_producto_{producto_id}.png"
        qr_path = os.path.join(IMAGENES_PRODUCTOS_FOLDER, qr_filename)
        img.save(qr_path)
        
        # Retornar la ruta relativa
        return f"imagenes_productos/{qr_filename}"
    except Exception as e:
        print(f"Error generando QR para producto {producto_id}: {e}")
        return None

def generar_qr_base64(data):
    """Genera un código QR y retorna la imagen en base64."""
    try:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(data)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Convertir a base64
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        img_base64 = base64.b64encode(buffer.getvalue()).decode()
        
        return f"data:image/png;base64,{img_base64}"
    except Exception as e:
        print(f"Error generando QR base64: {e}")
    return None

def cargar_clientes_desde_csv(archivo_csv):
    """Carga clientes desde un archivo CSV."""
    clientes = cargar_datos(ARCHIVO_CLIENTES)
    try:
        with open(archivo_csv, 'r', encoding='utf-8') as f:
            lector = csv.DictReader(f)
            for fila in lector:
                tipo_id = fila.get('tipo_id', 'V')
                numero_id = fila.get('numero_id', '').strip()
                if not numero_id.isdigit():
                    continue
                nuevo_id = f"{tipo_id}-{numero_id}"
                if nuevo_id not in clientes:
                    clientes[nuevo_id] = {
                        'id': nuevo_id,
                        'nombre': fila.get('nombre', '').strip(),
                        'email': fila.get('email', '').strip() if 'email' in fila else '',
                        'telefono': fila.get('telefono', '').strip() if 'telefono' in fila else '',
                        'direccion': fila.get('direccion', '').strip() if 'direccion' in fila else ''
                    }
        return guardar_datos(ARCHIVO_CLIENTES, clientes)
    except Exception as e:
        print(f"Error cargando clientes desde CSV: {e}")
        return False

def cargar_productos_desde_csv(archivo_csv):
    """Carga productos desde un archivo CSV."""
    inventario = cargar_datos(ARCHIVO_INVENTARIO)
    try:
        with open(archivo_csv, 'r', encoding='utf-8') as f:
            lector = csv.DictReader(f)
            for fila in lector:
                nuevo_id = str(len(inventario) + 1)
                inventario[nuevo_id] = {
                    'nombre': fila.get('nombre', '').strip(),
                    'precio': safe_float(fila.get('precio', 0)),
                    'cantidad': int(fila.get('cantidad', 0)),
                    'categoria': fila.get('categoria', '').strip(),
                    'ruta_imagen': "",
                    'ultima_entrada': None,
                    'ultima_salida': None
                }
        return guardar_datos(ARCHIVO_INVENTARIO, inventario)
    except Exception as e:
        print(f"Error cargando productos desde CSV: {e}")
        return False

def validar_stock_repuestos(repuestos_seleccionados):
    """Valida que hay stock suficiente antes de aprobar presupuesto"""
    inventario = cargar_datos(ARCHIVO_INVENTARIO)
    problemas = []
    
    for repuesto in repuestos_seleccionados:
        if repuesto['id'] in inventario:
            stock_actual = inventario[repuesto['id']]['cantidad']
            if stock_actual < repuesto['cantidad']:
                problemas.append(f"{repuesto['nombre']}: Stock {stock_actual}, Necesario {repuesto['cantidad']}")
        else:
            problemas.append(f"{repuesto['nombre']}: Producto no encontrado en inventario")
    
    return len(problemas) == 0, problemas

def descontar_repuestos_inventario(orden_id, repuestos_seleccionados):
    """Descuenta repuestos del inventario cuando se aprueba presupuesto"""
    inventario = cargar_datos(ARCHIVO_INVENTARIO)
    movimientos = []
    
    print(f"DEBUG: Descontando repuestos para orden {orden_id}")
    print(f"DEBUG: Repuestos a descontar: {repuestos_seleccionados}")
    
    for repuesto in repuestos_seleccionados:
        if repuesto['id'] in inventario:
            stock_actual = inventario[repuesto['id']]['cantidad']
            cantidad_necesaria = repuesto['cantidad']
            
            print(f"DEBUG: {repuesto['nombre']} - Stock actual: {stock_actual}, Necesario: {cantidad_necesaria}")
            
            if stock_actual >= cantidad_necesaria:
                # Descontar del inventario
                inventario[repuesto['id']]['cantidad'] -= cantidad_necesaria
                inventario[repuesto['id']]['ultima_salida'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                # Registrar movimiento
                movimientos.append({
                    'tipo': 'salida',
                    'producto_id': repuesto['id'],
                    'producto_nombre': repuesto['nombre'],
                    'cantidad': cantidad_necesaria,
                    'motivo': f'Reparación orden {orden_id}',
                    'fecha': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'usuario': session.get('username', 'Sistema'),
                    'orden_servicio': orden_id
                })
                
                print(f"DEBUG: ✅ {repuesto['nombre']} descontado exitosamente")
            else:
                # No hay stock suficiente
                error_msg = f"Stock insuficiente para {repuesto['nombre']} (Stock: {stock_actual}, Necesario: {cantidad_necesaria})"
                print(f"DEBUG: ❌ {error_msg}")
                return False, error_msg
        else:
            error_msg = f"Producto {repuesto['nombre']} no encontrado en inventario"
            print(f"DEBUG: ❌ {error_msg}")
            return False, error_msg
    
    # Guardar cambios en inventario
    if guardar_datos(ARCHIVO_INVENTARIO, inventario):
        # Registrar movimientos
        registrar_movimientos_inventario(movimientos)
        print(f"DEBUG: ✅ Inventario actualizado y movimientos registrados")
        return True, f"Repuestos descontados exitosamente: {len(movimientos)} movimientos"
    else:
        print(f"DEBUG: ❌ Error guardando inventario")
        return False, "Error guardando cambios en inventario"

def registrar_movimientos_inventario(movimientos):
    """Registra movimientos de inventario en archivo separado"""
    try:
        movimientos_file = 'movimientos_inventario.json'
        movimientos_existentes = cargar_datos(movimientos_file)
        
        if not movimientos_existentes:
            movimientos_existentes = []
        
        movimientos_existentes.extend(movimientos)
        guardar_datos(movimientos_file, movimientos_existentes)
        print(f"DEBUG: ✅ Movimientos registrados: {len(movimientos)} movimientos")
    except Exception as e:
        print(f"DEBUG: ❌ Error registrando movimientos: {e}")

def limpiar_valor_monetario(valor):
    """Limpia y convierte un valor monetario a float."""
    if valor is None:
        return 0.0
    if isinstance(valor, (int, float)):
        return safe_float(valor)
    try:
        # Eliminar símbolos y espacios
        valor = str(valor).replace('$', '').replace(',', '').replace('Bs', '').strip()
        # Reemplazar coma decimal por punto si existe
        if ',' in valor:
            valor = valor.replace(',', '.')
        return safe_float(valor)
    except (ValueError, TypeError):
        return 0.0

def cargar_empresa():
    """
    Carga los datos de la empresa desde config_sistema.json.
    Si no existe configuración, intenta migrar desde empresa.json.
    """
    try:
        # Primero intentar cargar desde config_sistema.json
        config = cargar_configuracion()
        empresa_data = config.get('empresa', {})
        
        # Si la empresa no tiene nombre configurado, intentar migrar desde empresa.json
        if not empresa_data.get('nombre'):
            try:
                if os.path.exists('empresa.json'):
                    with open('empresa.json', 'r', encoding='utf-8') as f:
                        empresa_antigua = json.load(f)
                        
                    # Migrar datos a config_sistema.json
                    if empresa_antigua.get('nombre'):
                        empresa_data['nombre'] = empresa_antigua.get('nombre', '')
                        empresa_data['rif'] = empresa_antigua.get('rif', '')
                        empresa_data['telefono'] = empresa_antigua.get('telefono', '')
                        empresa_data['direccion'] = empresa_antigua.get('direccion', '')
                        
                        # Guardar en config_sistema.json
                        config['empresa'] = empresa_data
                        guardar_configuracion(config)
                        print("✅ Datos de empresa migrados desde empresa.json a config_sistema.json")
            except Exception as e:
                print(f"⚠️ Error al migrar empresa.json: {e}")
        
        # Si aún no hay datos, usar valores por defecto
        if not empresa_data.get('nombre'):
            empresa_data = {
                "nombre": "Servicio Técnico Jehová Jireh",
                "rif": "J-000000000",
                "telefono": "0000-0000000",
                "direccion": "Dirección de la empresa",
                "ciudad": "",
                "estado": "",
                "pais": "Venezuela",
                "whatsapp": "",
                "email": "",
                "website": "",
                "instagram": "",
                "descripcion": "",
                "horario": "",
                "logo_path": "static/logo.png"
            }
        
        return empresa_data
        
    except Exception as e:
        print(f"⚠️ Error cargando empresa: {e}")
        return {
            "nombre": "Servicio Técnico Jehová Jireh",
            "rif": "J-000000000",
            "telefono": "0000-0000000",
            "direccion": "Dirección de la empresa",
            "ciudad": "",
            "estado": "",
            "pais": "Venezuela",
            "whatsapp": "",
            "email": "",
            "website": "",
            "instagram": "",
            "descripcion": "",
            "horario": "",
            "logo_path": "static/logo.png"
        }

def es_fecha_valida(fecha_str):
    """Valida si una fecha es válida y puede ser comparada."""
    if not fecha_str or not isinstance(fecha_str, str):
        return False
    try:
        datetime.strptime(fecha_str, '%Y-%m-%d')
        return True
    except ValueError:
        return False

def limpiar_monto(monto):
    if not monto:
        return 0.0
    return safe_float(str(monto).replace('$', '').replace('Bs', '').replace(',', '').strip())

# --- Rutas protegidas ---
@app.route('/')
@login_required
def index():
    stats = obtener_estadisticas()
    notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
    total_facturado_usd = sum(safe_float(f.get('total_usd', 0)) for f in notas.values())
    cantidad_notas = len(notas)
    promedio_nota_usd = total_facturado_usd / cantidad_notas if cantidad_notas > 0 else 0
    # Obtener tasa EUR del BCV directamente (igual que el endpoint api_tasas_actualizadas)
    tasa_bcv_eur = 0
    try:
        tasa_bcv_usd = stats.get('tasa_bcv', 0)
        if tasa_bcv_usd and tasa_bcv_usd > 10:
            # Intentar obtener tasas del BCV
            import requests
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            
            url_bcv = 'https://www.bcv.org.ve/glosario/cambio-oficial'
            resp = requests.get(url_bcv, timeout=10, verify=False)
            
            if resp.status_code == 200:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, 'html.parser')
                
                # Buscar todas las tasas en strong elements
                tasas = []
                for strong in soup.find_all('strong'):
                    txt = strong.text.strip().replace('.', '').replace(',', '.')
                    try:
                        posible = float(txt)
                        if 10 < posible < 1000:
                            tasas.append(posible)
                    except:
                        continue
                
                # Si tenemos más de una tasa, la segunda debería ser EUR
                if len(tasas) >= 2:
                    tasa_bcv_eur = tasas[1]
                    print(f"✅ Tasa EUR para dashboard: {tasa_bcv_eur}")
    except Exception as e:
        print(f"Error obteniendo tasa EUR para dashboard: {e}")
        # Fallback: calcular basado en USD
        if stats.get('tasa_bcv') and stats.get('tasa_bcv', 0) > 10:
            tasa_bcv_eur = stats.get('tasa_bcv', 0) * 1.05
    advertencia_tasa = None
    if not stats.get('tasa_bcv') or stats.get('tasa_bcv', 0) < 1:
        advertencia_tasa = '¡Advertencia! No se ha podido obtener la tasa BCV actual.'
    stats['tasa_bcv_eur'] = tasa_bcv_eur
    return render_template('index.html', **stats, advertencia_tasa=advertencia_tasa, total_facturado_usd=total_facturado_usd, promedio_nota_usd=promedio_nota_usd)

# Rutas de la API para filtros del dashboard
@app.route('/api/dashboard-filtros')
@login_required
def api_dashboard_filtros():
    """API para obtener estadísticas filtradas del dashboard."""
    filtro_tipo = request.args.get('tipo')
    filtro_valor = request.args.get('valor')
    
    try:
        stats = obtener_estadisticas_filtradas(filtro_tipo, filtro_valor)
        return jsonify({
            'success': True,
            'data': stats
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/opciones-filtro')
@login_required
def api_opciones_filtro():
    """API para obtener las opciones disponibles para los filtros."""
    try:
        opciones = obtener_opciones_filtro()
        return jsonify({
            'success': True,
            'data': opciones
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/tarjeta-filtro')
@login_required
def api_tarjeta_filtro():
    """API para obtener métricas filtradas de una tarjeta específica."""
    tarjeta = request.args.get('tarjeta')
    filtro_tipo = request.args.get('tipo')
    filtro_valor = request.args.get('valor')
    
    if not tarjeta:
        return jsonify({
            'success': False,
            'error': 'Tarjeta no especificada'
        }), 400
    
    try:
        metricas = obtener_metricas_tarjeta(tarjeta, filtro_tipo, filtro_valor)
        return jsonify({
            'success': True,
            'data': metricas
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/opciones-filtro-avanzado')
@login_required
def api_opciones_filtro_avanzado():
    """API para obtener las opciones de filtros avanzados con menús anidados."""
    try:
        opciones = obtener_opciones_filtro_avanzado()
        return jsonify({
            'success': True,
            'data': opciones
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# Ruta de prueba sin autenticación para debugging
@app.route('/api/test-tarjeta-filtro')
def api_test_tarjeta_filtro():
    """API de prueba para obtener métricas filtradas sin autenticación."""
    tarjeta = request.args.get('tarjeta')
    filtro_tipo = request.args.get('tipo')
    filtro_valor = request.args.get('valor')
    
    print(f"🔍 DEBUG API: tarjeta={tarjeta}, tipo={filtro_tipo}, valor={filtro_valor}")
    
    if not tarjeta:
        return jsonify({
            'success': False,
            'error': 'Tarjeta no especificada'
        }), 400
    
    try:
        metricas = obtener_metricas_tarjeta(tarjeta, filtro_tipo, filtro_valor)
        print(f"✅ DEBUG API: Respuesta para {tarjeta}: {metricas}")
        return jsonify({
            'success': True,
            'data': metricas
        })
    except Exception as e:
        print(f"❌ DEBUG API: Error para {tarjeta}: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# Ruta de prueba sin autenticación para opciones de filtro
@app.route('/api/test-opciones-filtro')
def api_test_opciones_filtro():
    """API de prueba para obtener opciones de filtro sin autenticación."""
    try:
        opciones = obtener_opciones_filtro()
        return jsonify({
            'success': True,
            'data': opciones
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/mapa-avanzado')
@login_required
def mapa_avanzado():
    """Muestra el mapa avanzado con las ubicaciones de los clientes."""
    try:
        # Cargar datos necesarios
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        cuentas = cargar_datos(ARCHIVO_CUENTAS)
        
        if clientes is None:
            clientes = {}
        if facturas is None:
            facturas = {}
        if cuentas is None:
            cuentas = {}
        
        # Calcular estadísticas por cliente para el mapa
        clientes_estadisticas = {}
        for id_cliente, cliente in clientes.items():
            notas_cliente = [f for f in notas.values() if f.get('cliente_id') == id_cliente]
            total_facturas = len(notas_cliente)
            total_facturado = sum(safe_float(f.get('total_usd', 0)) for f in notas_cliente)
            total_abonado = sum(safe_float(f.get('total_abonado', 0)) for f in notas_cliente)
            total_por_cobrar = max(0, total_facturado - total_abonado)
            
            clientes_estadisticas[id_cliente] = {
                'total_notas_entrega': total_facturas,
                'total_facturado': total_facturado,
                'total_abonado': total_abonado,
                'total_por_cobrar': total_por_cobrar
            }
        
        # Obtener configuración de mapas
        maps_config = get_maps_config()
        
        return render_template('mapa_avanzado.html', 
                             clientes=clientes, 
                             clientes_estadisticas=clientes_estadisticas,
                             maps_config=maps_config)
    
    except Exception as e:
        print(f"Error en mapa_avanzado: {str(e)}")
        flash(f'Error al cargar el mapa avanzado: {str(e)}', 'danger')
        return redirect(url_for('mostrar_clientes'))

@app.route('/clientes')
@login_required
def mostrar_clientes():
    clientes = cargar_datos(ARCHIVO_CLIENTES)
    notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
    cuentas = cargar_datos(ARCHIVO_CUENTAS)
    
    # Filtros mejorados
    q = request.args.get('q', '').strip().lower()
    filtro_orden = request.args.get('filtro_orden', 'nombre')
    filtro_tipo = request.args.get('filtro_tipo', '')
    filtro_estado = request.args.get('filtro_estado', '')
    
    # Aplicar filtros de búsqueda
    if q:
        clientes_filtrados = {}
        for k, v in clientes.items():
            # Búsqueda en múltiples campos
            if (q in v.get('nombre', '').lower() or 
                q in v.get('cedula_rif', '').lower() or 
                q in v.get('email', '').lower() or 
                q in v.get('telefono', '').lower() or 
                q in v.get('direccion', '').lower() or
                q in k.lower()):
                clientes_filtrados[k] = v
        clientes = clientes_filtrados
    
    # Filtro por tipo de identificación
    if filtro_tipo:
        clientes = {k: v for k, v in clientes.items() if v.get('tipo_id', '') == filtro_tipo}
    
    # Filtro por estado (activo/inactivo)
    if filtro_estado:
        if filtro_estado == 'activo':
            clientes = {k: v for k, v in clientes.items() if v.get('activo', True)}
        elif filtro_estado == 'inactivo':
            clientes = {k: v for k, v in clientes.items() if not v.get('activo', True)}
    
    # Ordenamiento mejorado
    if filtro_orden == 'nombre':
        clientes = dict(sorted(clientes.items(), key=lambda item: item[1].get('nombre', '').lower()))
    elif filtro_orden == 'cedula_rif':
        clientes = dict(sorted(clientes.items(), key=lambda item: item[1].get('cedula_rif', '').lower()))
    elif filtro_orden == 'fecha_creacion':
        clientes = dict(sorted(clientes.items(), key=lambda item: item[1].get('fecha_creacion', ''), reverse=True))
    elif filtro_orden == 'email':
        clientes = dict(sorted(clientes.items(), key=lambda item: item[1].get('email', '').lower()))
    
    # Calcular totales por cliente
    clientes_totales = {}
    for id_cliente, cliente in clientes.items():
        notas_cliente = [f for f in notas.values() if f.get('cliente_id') == id_cliente]
        total_notas_entrega = sum(safe_float(f.get('total_usd', 0)) for f in notas_cliente)
        total_abonado = sum(safe_float(f.get('total_abonado', 0)) for f in notas_cliente)
        total_por_cobrar = max(0, total_notas_entrega - total_abonado)
        clientes_totales[id_cliente] = {
            'total_facturado': total_notas_entrega,  # Mantener nombre para compatibilidad
            'total_abonado': total_abonado,
            'total_por_cobrar': total_por_cobrar
        }
    
    # Estadísticas para el dashboard
    total_clientes = len(clientes)
    clientes_activos = len([c for c in clientes.values() if c.get('activo', True)])
    clientes_inactivos = total_clientes - clientes_activos
    
    return render_template('clientes.html', 
                         clientes=clientes, 
                         q=q, 
                         filtro_orden=filtro_orden,
                         filtro_tipo=filtro_tipo,
                         filtro_estado=filtro_estado,
                         clientes_totales=clientes_totales,
                         total_clientes=total_clientes,
                         clientes_activos=clientes_activos,
                         clientes_inactivos=clientes_inactivos,
                         total_clientes_general=len(clientes))

def normalizar_cedula_rif(cedula_rif):
    """
    Normaliza cédula/RIF para comparación eliminando espacios, guiones y convirtiendo a mayúsculas.
    """
    if not cedula_rif:
        return ''
    return str(cedula_rif).replace('-', '').replace('_', '').replace('.', '').replace(' ', '').upper()

def obtener_cedula_rif_cliente(cliente):
    """
    Obtiene la cédula/RIF de un cliente independientemente del formato usado.
    Retorna la cédula normalizada.
    """
    # Intentar diferentes campos posibles
    cedula = cliente.get('cedula_rif', '') or cliente.get('rif', '')
    
    # Si tiene estructura SENIAT, construir cédula completa
    if not cedula:
        tipo_id = cliente.get('tipo_identificacion', '')
        numero_id = cliente.get('numero_identificacion', '')
        dv = cliente.get('digito_verificador', '')
        if tipo_id and numero_id:
            if dv:
                cedula = f"{tipo_id}-{numero_id}-{dv}"
            else:
                cedula = f"{tipo_id}-{numero_id}"
    
    return normalizar_cedula_rif(cedula)

def validar_digito_verificador_seniat(tipo_id, numero_id, digito_verificador):
    """
    Valida el dígito verificador según el algoritmo oficial del SENIAT.
    Basado en la Providencia 00102 del SENIAT.
    """
    try:
        # Convertir a enteros
        numero = int(numero_id)
        dv = int(digito_verificador)
        
        # Algoritmo SENIAT para dígito verificador
        # Multiplicar cada dígito por su posición (de derecha a izquierda)
        # Sumar los resultados y obtener el módulo 11
        
        numero_str = str(numero).zfill(9)  # Rellenar con ceros a la izquierda
        multiplicadores = [3, 2, 7, 6, 5, 4, 3, 2, 1]
        
        suma = 0
        for i, digito in enumerate(numero_str):
            suma += int(digito) * multiplicadores[i]
        
        # Calcular el dígito verificador
        resto = suma % 11
        if resto < 2:
            dv_calculado = resto
        else:
            dv_calculado = 11 - resto
        
        return dv == dv_calculado
        
    except (ValueError, IndexError):
        return False

def validar_telefono(telefono):
    """
    Valida formato de teléfono venezolano.
    Retorna (es_valido, mensaje_error)
    """
    if not telefono:
        return False, "El teléfono es obligatorio"
    
    # Limpiar teléfono
    telefono_limpio = telefono.replace('-', '').replace(' ', '').replace('(', '').replace(')', '').replace('+', '')
    
    # Eliminar código de país si está presente
    if telefono_limpio.startswith('58'):
        telefono_limpio = telefono_limpio[2:]
    
    # Validar que sean solo dígitos
    if not telefono_limpio.isdigit():
        return False, "El teléfono debe contener solo números"
    
    # Validar longitud (10 dígitos para Venezuela)
    if len(telefono_limpio) < 10:
        return False, "El teléfono debe tener al menos 10 dígitos"
    
    if len(telefono_limpio) > 11:
        return False, "El teléfono no puede tener más de 11 dígitos"
    
    return True, None

def validar_email(email):
    """
    Valida formato de email.
    Retorna (es_valido, mensaje_error)
    """
    if not email:
        return True, None  # Email es opcional
    
    # Validar formato básico con regex
    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        return False, "Formato de email inválido"
    
    return True, None

def normalizar_cedula_rif(cedula_rif):
    """
    Normaliza cédula/RIF para comparación (elimina espacios, guiones, convierte a mayúsculas).
    Retorna la cédula normalizada.
    """
    if not cedula_rif:
        return ''
    # Eliminar espacios, guiones, guiones bajos y convertir a mayúsculas
    return str(cedula_rif).replace('-', '').replace('_', '').replace(' ', '').upper()

def obtener_cedula_rif_cliente(cliente):
    """
    Obtiene la cédula/RIF de un cliente, manejando ambos formatos (cedula_rif o estructura SENIAT).
    Retorna la cédula normalizada o None si no existe.
    """
    # Intentar obtener de cedula_rif (formato simple)
    cedula = cliente.get('cedula_rif', '')
    if cedula:
        return normalizar_cedula_rif(cedula)
    
    # Intentar obtener de estructura SENIAT
    tipo_id = cliente.get('tipo_identificacion', '')
    numero_id = cliente.get('numero_identificacion', '')
    digito_verificador = cliente.get('digito_verificador', '')
    
    if tipo_id and numero_id:
        # Construir formato SENIAT: TIPO-NUMERO-DIGITO
        rif_seniat = f"{tipo_id}-{numero_id}"
        if digito_verificador:
            rif_seniat += f"-{digito_verificador}"
        return normalizar_cedula_rif(rif_seniat)
    
    # Intentar obtener de 'rif' directamente
    rif = cliente.get('rif', '')
    if rif:
        return normalizar_cedula_rif(rif)
    
    return None

def obtener_cedula_rif_cliente_sin_normalizar(cliente):
    """
    Obtiene la cédula/RIF de un cliente sin normalizar (para mostrar).
    Retorna la cédula en formato original o None si no existe.
    """
    # Intentar obtener de cedula_rif (formato simple)
    cedula = cliente.get('cedula_rif', '')
    if cedula:
        return cedula
    
    # Intentar obtener de estructura SENIAT
    tipo_id = cliente.get('tipo_identificacion', '')
    numero_id = cliente.get('numero_identificacion', '')
    digito_verificador = cliente.get('digito_verificador', '')
    
    if tipo_id and numero_id:
        # Construir formato SENIAT: TIPO-NUMERO-DIGITO
        rif_seniat = f"{tipo_id}-{numero_id}"
        if digito_verificador:
            rif_seniat += f"-{digito_verificador}"
        return rif_seniat
    
    # Intentar obtener de 'rif' directamente
    rif = cliente.get('rif', '')
    if rif:
        return rif
    
    return None

@app.route('/clientes/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo_cliente():
    """Formulario para nuevo cliente - Formulario simplificado y moderno."""
    if request.method == 'POST':
        try:
            print("Iniciando proceso de creación de cliente...")
            
            # Cargar clientes existentes
            clientes = cargar_datos(ARCHIVO_CLIENTES)
            if clientes is None:
                print("No se pudieron cargar los clientes existentes, creando nuevo diccionario")
                clientes = {}
            
            # === VALIDACIONES SIMPLIFICADAS ===
            nombre = request.form.get('nombre', '').strip()
            cedula_rif = request.form.get('cedula_rif', '').strip()
            email = request.form.get('email', '').strip().lower()
            telefono = request.form.get('telefono', '').strip()
            direccion = request.form.get('direccion', '').strip()
            
            print(f"Datos recibidos - Nombre: {nombre}, Cédula: {cedula_rif}, Email: {email}")
            
            # === VALIDACIONES BÁSICAS ===
            errores = []
            
            # 1. VALIDACIÓN DE NOMBRE
            if not nombre:
                errores.append("El nombre es obligatorio")
            elif len(nombre) < 2:
                errores.append("El nombre debe tener al menos 2 caracteres")
            
            # 2. VALIDACIÓN DE CÉDULA/RIF
            if not cedula_rif:
                errores.append("La cédula/RIF es obligatoria")
            elif len(cedula_rif) < 6:
                errores.append("La cédula/RIF debe tener al menos 6 caracteres")
            
            # 3. VALIDACIÓN DE TELÉFONO
            telefono_valido, error_telefono = validar_telefono(telefono)
            if not telefono_valido:
                errores.append(error_telefono)
            
            # 4. VALIDACIÓN DE DIRECCIÓN
            if not direccion:
                errores.append("La dirección es obligatoria")
            elif len(direccion) < 10:
                errores.append("La dirección debe tener al menos 10 caracteres")
            
            # 5. VALIDACIÓN DE EMAIL (opcional pero con formato válido)
            email_valido, error_email = validar_email(email)
            if not email_valido:
                errores.append(error_email)
            
            # Si hay errores, mostrarlos
            if errores:
                for error in errores:
                    flash(f"❌ {error}", 'danger')
                return render_template('cliente_form.html')
            
            # === VERIFICAR DUPLICADOS ===
            # Normalizar cédula/RIF para comparación
            cedula_normalizada = normalizar_cedula_rif(cedula_rif)
            
            # Verificar duplicados por cédula/RIF normalizada
            for cliente_id, cliente_existente in clientes.items():
                cedula_existente = obtener_cedula_rif_cliente(cliente_existente)
                if cedula_existente and cedula_existente == cedula_normalizada:
                    flash(f'Ya existe un cliente con la cédula/RIF {cedula_rif}. Cliente existente: {cliente_existente.get("nombre", "Sin nombre")}', 'danger')
                    return render_template('cliente_form.html')
            
            # Verificar duplicados por email (si se proporciona)
            if email:
                email_normalizado = email.lower().strip()
                for cliente_id, cliente_existente in clientes.items():
                    email_existente = cliente_existente.get('email', '').lower().strip()
                    if email_existente and email_existente == email_normalizado:
                        flash(f'Ya existe un cliente con el email {email}. Duplicado detectado: {cliente_existente.get("nombre", "Sin nombre")}', 'danger')
                        return render_template('cliente_form.html')
            
            # === CREAR NUEVO CLIENTE ===
            nuevo_id = str(uuid4())
            fecha_actual = datetime.now().isoformat()
            
            # Obtener datos adicionales del formulario
            telefono2 = request.form.get('telefono2', '').strip()
            fecha_nacimiento = request.form.get('fecha_nacimiento', '')
            profesion = request.form.get('profesion', '')
            categoria_cliente = request.form.get('categoria_cliente', 'regular')
            vendedor_asignado = request.form.get('vendedor_asignado', '')
            fuente_captacion = request.form.get('fuente_captacion', '')
            notas_internas = request.form.get('notas_internas', '')
            etiquetas_str = request.form.get('etiquetas', '')
            etiquetas = [e.strip() for e in etiquetas_str.split(',') if e.strip()] if etiquetas_str else []
            
            # Procesar archivos adjuntos (con rollback en caso de error)
            foto_cliente = None
            foto_path = None
            documentos = []
            documentos_paths = []
            firma_filename = None
            firma_path = None
            
            try:
                # Procesar foto
                if 'foto_cliente' in request.files:
                    foto = request.files['foto_cliente']
                    if foto and foto.filename:
                        # Validar tamaño y tipo
                        if foto.content_length and foto.content_length > 5 * 1024 * 1024:  # 5MB
                            flash('La foto no puede ser mayor a 5MB', 'warning')
                        else:
                            # Guardar foto
                            foto_filename = f"cliente_{nuevo_id}_{foto.filename}"
                            foto_path = os.path.join('static/uploads/clientes', foto_filename)
                            os.makedirs(os.path.dirname(foto_path), exist_ok=True)
                            foto.save(foto_path)
                            foto_cliente = foto_filename
                
                # Procesar documentos adjuntos
                if 'documentos' in request.files:
                    for doc in request.files.getlist('documentos'):
                        if doc and doc.filename:
                            # Validar tamaño y tipo
                            if doc.content_length and doc.content_length > 10 * 1024 * 1024:  # 10MB
                                flash(f'El documento {doc.filename} no puede ser mayor a 10MB', 'warning')
                                continue
                            
                            # Validar extensión
                            allowed_extensions = ['.pdf', '.doc', '.docx', '.jpg', '.jpeg', '.png']
                            if not any(doc.filename.lower().endswith(ext) for ext in allowed_extensions):
                                flash(f'El archivo {doc.filename} no tiene una extensión válida', 'warning')
                                continue
                            
                            doc_filename = f"doc_{nuevo_id}_{doc.filename}"
                            doc_path = os.path.join('static/uploads/clientes/documentos', doc_filename)
                            os.makedirs(os.path.dirname(doc_path), exist_ok=True)
                            doc.save(doc_path)
                            documentos.append(doc_filename)
                            documentos_paths.append(doc_path)
                
                # Procesar firma digital
                firma_digital = request.form.get('firma_digital', '')
                if firma_digital:
                    try:
                        # Guardar firma como imagen
                        firma_filename = f"firma_{nuevo_id}.png"
                        firma_path = os.path.join('static/uploads/clientes/firmas', firma_filename)
                        os.makedirs(os.path.dirname(firma_path), exist_ok=True)
                        
                        # Decodificar base64 y guardar
                        import base64
                        firma_data = firma_digital.split(',')[1]
                        with open(firma_path, 'wb') as f:
                            f.write(base64.b64decode(firma_data))
                    except Exception as e:
                        print(f"Error al guardar firma: {e}")
                        flash('Error al guardar la firma digital', 'warning')
                        firma_filename = None
                        firma_path = None
            except Exception as e:
                # Rollback: eliminar archivos guardados si hay error
                print(f"Error al procesar archivos, haciendo rollback: {e}")
                if foto_path and os.path.exists(foto_path):
                    try:
                        os.remove(foto_path)
                    except:
                        pass
                for doc_path in documentos_paths:
                    if os.path.exists(doc_path):
                        try:
                            os.remove(doc_path)
                        except:
                            pass
                if firma_path and os.path.exists(firma_path):
                    try:
                        os.remove(firma_path)
                    except:
                        pass
                flash(f'Error al procesar archivos: {str(e)}', 'danger')
                return render_template('cliente_form.html')
            
            # Crear objeto cliente
            nuevo_cliente = {
                'id': nuevo_id,
                'cedula_rif': cedula_rif,
                'nombre': nombre,
                'email': email,
                'telefono': telefono,
                'telefono2': telefono2,
                'direccion': direccion,
                'fecha_creacion': fecha_actual,
                'fecha_actualizacion': fecha_actual,
                'activo': True,
                'fecha_nacimiento': fecha_nacimiento,
                'profesion': profesion,
                'categoria_cliente': categoria_cliente,
                'vendedor_asignado': vendedor_asignado,
                'fuente_captacion': fuente_captacion,
                'notas_internas': notas_internas,
                'etiquetas': etiquetas,
                'foto_cliente': foto_cliente,
                'documentos': documentos,
                'firma_digital': firma_filename,
                'historial_cambios': [{
                    'fecha': fecha_actual,
                    'usuario': session.get('usuario', 'Sistema'),
                    'cambio': 'Cliente creado',
                    'detalles': 'Cliente creado con formulario simplificado'
                }]
            }
            
            # Agregar cliente a la lista
            clientes[nuevo_id] = nuevo_cliente
            
            # Guardar datos
            if guardar_datos(ARCHIVO_CLIENTES, clientes):
                print(f"✅ Cliente creado exitosamente: {nuevo_id}")
                flash(f'✅ Cliente {nombre} creado exitosamente', 'success')
                return redirect(url_for('mostrar_clientes'))
            else:
                print("❌ Error al guardar cliente, haciendo rollback de archivos")
                # Rollback: eliminar archivos guardados si falla el guardado del cliente
                if foto_path and os.path.exists(foto_path):
                    try:
                        os.remove(foto_path)
                    except:
                        pass
                for doc_path in documentos_paths:
                    if os.path.exists(doc_path):
                        try:
                            os.remove(doc_path)
                        except:
                            pass
                if firma_path and os.path.exists(firma_path):
                    try:
                        os.remove(firma_path)
                    except:
                        pass
                flash('❌ Error al guardar el cliente. Los archivos adjuntos fueron eliminados.', 'danger')
                return render_template('cliente_form.html')
                
        except Exception as e:
            print(f"❌ Error en nuevo_cliente: {str(e)}")
            flash(f'❌ Error al crear cliente: {str(e)}', 'danger')
            return render_template('cliente_form.html')
    
    return render_template('cliente_form.html')

@app.route('/inventario')
@login_required
def mostrar_inventario():
    inventario = cargar_datos(ARCHIVO_INVENTARIO)
    q = request.args.get('q', '')
    filtro_categoria = request.args.get('categoria', '')
    filtro_tipo = request.args.get('tipo', '')  # piezas, accesorios, etc.
    filtro_orden = request.args.get('orden', 'nombre')
    
    # Categorías predefinidas del sistema
    categorias_sistema = {
        'piezas': {
            'nombre': 'Piezas de Reparación',
            'icono': 'fas fa-cogs',
            'color': '#2196F3',
            'subcategorias': ['Pantallas', 'Baterías', 'Cargadores', 'Placas', 'Botones', 'Cámaras', 'Altavoces', 'Micrófonos', 'Conectores', 'Otros']
        },
        'accesorios': {
            'nombre': 'Accesorios',
            'icono': 'fas fa-mobile-alt',
            'color': '#4CAF50',
            'subcategorias': ['Fundas', 'Protectores', 'Cables', 'Adaptadores', 'Auriculares', 'Cargadores', 'Soportes', 'Otros']
        },
        'herramientas': {
            'nombre': 'Herramientas',
            'icono': 'fas fa-tools',
            'color': '#FF9800',
            'subcategorias': ['Destornilladores', 'Pinzas', 'Pistolas de Aire', 'Multímetros', 'Soldadores', 'Otros']
        },
        'consumibles': {
            'nombre': 'Consumibles',
            'icono': 'fas fa-flask',
            'color': '#9C27B0',
            'subcategorias': ['Pegamentos', 'Cintas', 'Limpieza', 'Soldadura', 'Otros']
        }
    }
    
    # Obtener categorías existentes en el inventario
    categorias_existentes = set()
    for producto in inventario.values():
        if producto.get('categoria'):
            categorias_existentes.add(producto['categoria'])
    
    # Filtrar productos
    productos_filtrados = {}
    piezas = {}
    accesorios = {}
    herramientas = {}
    consumibles = {}
    
    for id, producto in inventario.items():
        # Filtro de búsqueda
        if q and q.lower() not in producto['nombre'].lower():
            continue
        # Filtro de categoría
        if filtro_categoria and producto.get('categoria') != filtro_categoria:
            continue
        # Filtro de tipo
        if filtro_tipo and producto.get('tipo') != filtro_tipo:
            continue
            
        productos_filtrados[id] = producto
        
        # Separar por tipo
        tipo = producto.get('tipo', 'piezas')
        if tipo == 'piezas':
            piezas[id] = producto
        elif tipo == 'accesorios':
            accesorios[id] = producto
        elif tipo == 'herramientas':
            herramientas[id] = producto
        elif tipo == 'consumibles':
            consumibles[id] = producto
    
    # Ordenar productos
    if filtro_orden == 'nombre':
        productos_filtrados = dict(sorted(productos_filtrados.items(), key=lambda x: x[1]['nombre']))
        piezas = dict(sorted(piezas.items(), key=lambda x: x[1]['nombre']))
        accesorios = dict(sorted(accesorios.items(), key=lambda x: x[1]['nombre']))
        herramientas = dict(sorted(herramientas.items(), key=lambda x: x[1]['nombre']))
        consumibles = dict(sorted(consumibles.items(), key=lambda x: x[1]['nombre']))
    elif filtro_orden == 'stock':
        productos_filtrados = dict(sorted(productos_filtrados.items(), key=lambda x: x[1]['cantidad']))
        piezas = dict(sorted(piezas.items(), key=lambda x: x[1]['cantidad']))
        accesorios = dict(sorted(accesorios.items(), key=lambda x: x[1]['cantidad']))
        herramientas = dict(sorted(herramientas.items(), key=lambda x: x[1]['cantidad']))
        consumibles = dict(sorted(consumibles.items(), key=lambda x: x[1]['cantidad']))
    
    # Obtener tasa de cambio actual del BCV
    try:
        tasa_cambio = obtener_tasa_bcv()
        if not tasa_cambio or tasa_cambio <= 0:
            # Si no se puede obtener la tasa del BCV, usar la última guardada
            ultima_tasa = cargar_ultima_tasa_bcv()
            tasa_cambio = ultima_tasa if ultima_tasa else 36.5
    except:
        # En caso de error, usar tasa por defecto
        tasa_cambio = 36.5
    
    # Calcular estadísticas
    total_productos = len(inventario)
    total_piezas = len(piezas)
    total_accesorios = len(accesorios)
    total_herramientas = len(herramientas)
    total_consumibles = len(consumibles)
    
    # Calcular valor total del inventario
    valor_total_usd = sum(safe_float(p.get('precio', 0)) * int(p.get('cantidad', 0)) for p in inventario.values())
    valor_total_bs = valor_total_usd * tasa_cambio
    
    # Productos con stock bajo (menos de 5 unidades)
    stock_bajo = {id: p for id, p in inventario.items() if int(p.get('cantidad', 0)) < 5}
    
    return render_template('inventario_moderno.html', 
                         inventario=productos_filtrados,
                         piezas=piezas,
                         accesorios=accesorios,
                         herramientas=herramientas,
                         consumibles=consumibles,
                         categorias_sistema=categorias_sistema,
                         categorias_existentes=categorias_existentes,
                         q=q,
                         filtro_categoria=filtro_categoria,
                         filtro_tipo=filtro_tipo,
                         filtro_orden=filtro_orden,
                         tasa_cambio=tasa_cambio,
                         total_productos=total_productos,
                         total_piezas=total_piezas,
                         total_accesorios=total_accesorios,
                         total_herramientas=total_herramientas,
                         total_consumibles=total_consumibles,
                         valor_total_usd=valor_total_usd,
                         valor_total_bs=valor_total_bs,
                         stock_bajo=stock_bajo)

@app.route('/inventario/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo_producto():
    # Cargar el inventario
    inventario = cargar_datos(ARCHIVO_INVENTARIO)
    
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        tipo = request.form.get('tipo', 'piezas')
        categoria = request.form.get('categoria')
        subcategoria = request.form.get('subcategoria', '')
        precio = safe_float(request.form.get('precio', 0))
        cantidad = int(request.form.get('cantidad', 0))
        descripcion = request.form.get('descripcion', '')
        codigo_barras = request.form.get('codigo_barras', '').strip()
        proveedor = request.form.get('proveedor', '')
        ubicacion = request.form.get('ubicacion', '')
        stock_minimo = int(request.form.get('stock_minimo', 5))
        
        if not nombre or not tipo:
            flash('El nombre y el tipo son requeridos', 'danger')
            return redirect(url_for('nuevo_producto'))
        
        # Validar código de barras único
        if codigo_barras:
            productos_con_codigo = [pid for pid, p in inventario.items() 
                                   if p.get('codigo_barras') == codigo_barras]
            if productos_con_codigo:
                flash(f'Ya existe un producto con el código de barras: {codigo_barras}', 'danger')
                return redirect(url_for('nuevo_producto'))
        
        # Generar nuevo ID - validar que las claves sean numéricas
        if inventario:
            claves_numericas = []
            for k in inventario.keys():
                try:
                    claves_numericas.append(int(k))
                except (ValueError, TypeError):
                    continue
            nuevo_id = str(max(claves_numericas) + 1) if claves_numericas else '1'
        else:
            nuevo_id = '1'
        
        # Procesar imagen si se subió una
        ruta_imagen = None
        if 'imagen' in request.files:
            ruta_imagen = guardar_imagen_producto(request.files['imagen'], nuevo_id)
        
        # Generar código QR
        qr_data = f"ID: {nuevo_id}\nNombre: {nombre}\nTipo: {tipo}\nCategoría: {categoria}\nPrecio: ${precio}\nStock disponible: {cantidad}"
        qr_code = generar_qr_producto(qr_data, nuevo_id)
        
        # Crear nuevo producto
        inventario[nuevo_id] = {
            'nombre': nombre,
            'tipo': tipo,
            'categoria': categoria,
            'subcategoria': subcategoria,
            'precio': precio,
            'cantidad': cantidad,
            'descripcion': descripcion,
            'codigo_barras': codigo_barras,
            'proveedor': proveedor,
            'ubicacion': ubicacion,
            'stock_minimo': stock_minimo,
            'imagen': ruta_imagen,
            'qr_code': qr_code,
            'fecha_creacion': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'fecha_actualizacion': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'ultima_entrada': datetime.now().isoformat(),
            'ruta_imagen': ruta_imagen
        }
        
        # Registrar movimiento inicial si hay cantidad
        if cantidad > 0:
            movimiento = {
                'tipo': 'entrada',
                'producto_id': nuevo_id,
                'producto_nombre': nombre,
                'cantidad': cantidad,
                'motivo': 'Creación de producto',
                'fecha': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'usuario': session.get('username', 'Sistema')
            }
            registrar_movimientos_inventario([movimiento])
        
        if guardar_datos(ARCHIVO_INVENTARIO, inventario):
            flash('Producto creado exitosamente', 'success')
        else:
            flash('Error al crear el producto', 'danger')
        
        return redirect(url_for('mostrar_inventario'))
    
    # Categorías predefinidas del sistema
    categorias_sistema = {
        'piezas': {
            'nombre': 'Piezas de Reparación',
            'icono': 'fas fa-cogs',
            'color': '#2196F3',
            'subcategorias': ['Pantallas', 'Baterías', 'Cargadores', 'Placas', 'Botones', 'Cámaras', 'Altavoces', 'Micrófonos', 'Conectores', 'Otros']
        },
        'accesorios': {
            'nombre': 'Accesorios',
            'icono': 'fas fa-mobile-alt',
            'color': '#4CAF50',
            'subcategorias': ['Fundas', 'Protectores', 'Cables', 'Adaptadores', 'Auriculares', 'Cargadores', 'Soportes', 'Otros']
        },
        'herramientas': {
            'nombre': 'Herramientas',
            'icono': 'fas fa-tools',
            'color': '#FF9800',
            'subcategorias': ['Destornilladores', 'Pinzas', 'Pistolas de Aire', 'Multímetros', 'Soldadores', 'Otros']
        },
        'consumibles': {
            'nombre': 'Consumibles',
            'icono': 'fas fa-flask',
            'color': '#9C27B0',
            'subcategorias': ['Pegamentos', 'Cintas', 'Limpieza', 'Soldadura', 'Otros']
        }
    }
    
    # Cargar proveedores activos
    proveedores_data = cargar_datos('proveedores.json')
    proveedores = {}
    for id_prov, prov in proveedores_data.get('proveedores', {}).items():
        if prov.get('activo', True):  # Solo mostrar activos
            proveedores[id_prov] = prov
    
    return render_template('producto_form_moderno.html', categorias_sistema=categorias_sistema, proveedores=proveedores)

@app.route('/inventario/<id>/editar', methods=['GET', 'POST'])
@login_required
def editar_producto(id):
    # Cargar el inventario
    inventario = cargar_datos(ARCHIVO_INVENTARIO)
    
    if id not in inventario:
        flash('Producto no encontrado', 'danger')
        return redirect(url_for('mostrar_inventario'))
    
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        tipo = request.form.get('tipo', 'piezas')
        categoria = request.form.get('categoria')
        subcategoria = request.form.get('subcategoria', '')
        precio = safe_float(request.form.get('precio', 0))
        cantidad = int(request.form.get('cantidad', 0))
        descripcion = request.form.get('descripcion', '')
        codigo_barras = request.form.get('codigo_barras', '').strip()
        proveedor = request.form.get('proveedor', '')
        ubicacion = request.form.get('ubicacion', '')
        stock_minimo = int(request.form.get('stock_minimo', 5))
        
        if not nombre or not tipo:
            flash('El nombre y el tipo son requeridos', 'danger')
            return redirect(url_for('editar_producto', id=id))
        
        # Validar código de barras único (excluyendo el producto actual)
        if codigo_barras:
            productos_con_codigo = [pid for pid, p in inventario.items() 
                                   if p.get('codigo_barras') == codigo_barras and pid != id]
            if productos_con_codigo:
                flash(f'Ya existe otro producto con el código de barras: {codigo_barras}', 'danger')
                return redirect(url_for('editar_producto', id=id))
        
        # Procesar imagen si se subió una nueva
        ruta_imagen = inventario[id].get('ruta_imagen')
        if 'imagen' in request.files and request.files['imagen'].filename:
            nueva_ruta = guardar_imagen_producto(request.files['imagen'], id)
            if nueva_ruta:
                # Eliminar imagen anterior si existe
                if ruta_imagen:
                    try:
                        ruta_anterior = os.path.join(BASE_DIR, 'static', ruta_imagen)
                        if os.path.exists(ruta_anterior):
                            os.remove(ruta_anterior)
                    except Exception as e:
                        print(f"Error eliminando imagen anterior: {e}")
                ruta_imagen = nueva_ruta
        
        # Generar nuevo código QR si cambió la información
        qr_data = f"ID: {id}\nNombre: {nombre}\nTipo: {tipo}\nCategoría: {categoria}\nPrecio: ${precio}\nStock disponible: {cantidad}"
        qr_code = generar_qr_producto(qr_data, id)
        
        # Registrar movimiento si cambió la cantidad
        cantidad_anterior = inventario[id].get('cantidad', 0)
        diferencia = cantidad - cantidad_anterior
        
        # Actualizar producto
        inventario[id].update({
            'nombre': nombre,
            'tipo': tipo,
            'categoria': categoria,
            'subcategoria': subcategoria,
            'precio': precio,
            'cantidad': cantidad,
            'descripcion': descripcion,
            'codigo_barras': codigo_barras,
            'proveedor': proveedor,
            'ubicacion': ubicacion,
            'stock_minimo': stock_minimo,
            'ruta_imagen': ruta_imagen,
            'qr_code': qr_code,
            'fecha_actualizacion': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        
        # Registrar movimiento si hay diferencia en la cantidad
        if diferencia != 0:
            movimiento = {
                'tipo': 'entrada' if diferencia > 0 else 'salida',
                'producto_id': id,
                'producto_nombre': nombre,
                'cantidad': abs(diferencia),
                'motivo': f'Edición de producto (anterior: {cantidad_anterior}, nuevo: {cantidad})',
                'fecha': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'usuario': session.get('username', 'Sistema')
            }
            registrar_movimientos_inventario([movimiento])
            
            # Actualizar última entrada/salida
            if diferencia > 0:
                inventario[id]['ultima_entrada'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            else:
                inventario[id]['ultima_salida'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        if guardar_datos(ARCHIVO_INVENTARIO, inventario):
            flash('Producto actualizado exitosamente', 'success')
        else:
            flash('Error al actualizar el producto', 'danger')
        
        return redirect(url_for('mostrar_inventario'))
    
    # Categorías predefinidas del sistema
    categorias_sistema = {
        'piezas': {
            'nombre': 'Piezas de Reparación',
            'icono': 'fas fa-cogs',
            'color': '#2196F3',
            'subcategorias': ['Pantallas', 'Baterías', 'Cargadores', 'Placas', 'Botones', 'Cámaras', 'Altavoces', 'Micrófonos', 'Conectores', 'Otros']
        },
        'accesorios': {
            'nombre': 'Accesorios',
            'icono': 'fas fa-mobile-alt',
            'color': '#4CAF50',
            'subcategorias': ['Fundas', 'Protectores', 'Cables', 'Adaptadores', 'Auriculares', 'Cargadores', 'Soportes', 'Otros']
        },
        'herramientas': {
            'nombre': 'Herramientas',
            'icono': 'fas fa-tools',
            'color': '#FF9800',
            'subcategorias': ['Destornilladores', 'Pinzas', 'Pistolas de Aire', 'Multímetros', 'Soldadores', 'Otros']
        },
        'consumibles': {
            'nombre': 'Consumibles',
            'icono': 'fas fa-flask',
            'color': '#9C27B0',
            'subcategorias': ['Pegamentos', 'Cintas', 'Limpieza', 'Soldadura', 'Otros']
        }
    }
    
    # Cargar proveedores activos
    proveedores_data = cargar_datos('proveedores.json')
    proveedores = {}
    for id_prov, prov in proveedores_data.get('proveedores', {}).items():
        if prov.get('activo', True):  # Solo mostrar activos
            proveedores[id_prov] = prov
    
    # Agregar el ID al producto para el template
    producto = inventario[id].copy()
    producto['id'] = id
    
    return render_template('producto_form_moderno.html', producto=producto, categorias_sistema=categorias_sistema, proveedores=proveedores)

@app.route('/inventario/qr/<id>')
@login_required
def generar_qr_producto_route(id):
    """Genera y muestra el código QR de un producto."""
    inventario = cargar_datos(ARCHIVO_INVENTARIO)
    if id not in inventario:
        abort(404)
    
    producto = inventario[id]
    qr_data = f"ID: {id}\nNombre: {producto['nombre']}\nTipo: {producto.get('tipo', 'piezas')}\nCategoría: {producto.get('categoria', 'Sin categoría')}\nPrecio: ${producto.get('precio', 0)}"
    
    qr_base64 = generar_qr_base64(qr_data)
    if qr_base64:
        return jsonify({'qr': qr_base64})
    else:
        return jsonify({'error': 'Error generando QR'}), 500

@app.route('/inventario/<id>/eliminar', methods=['POST'])
@login_required
def eliminar_producto(id):
    inventario = cargar_datos(ARCHIVO_INVENTARIO)
    if id not in inventario:
        abort(404)
    
    # Validar referencias antes de eliminar
    # Buscar en órdenes de servicio si el producto está en uso
    ordenes = cargar_datos('ordenes_servicio.json')
    productos_en_uso = []
    
    for orden_id, orden in ordenes.items():
        # Buscar en reparaciones
        if 'reparacion' in orden and 'repuestos_usados' in orden['reparacion']:
            for repuesto in orden['reparacion']['repuestos_usados']:
                if repuesto.get('id') == id:
                    productos_en_uso.append(f"Orden {orden_id}")
        
        # Buscar en diagnósticos
        if 'diagnostico' in orden and 'repuestos_seleccionados' in orden['diagnostico']:
            try:
                repuestos_str = orden.get('diagnostico', {}).get('repuestos_seleccionados', '[]')
                repuestos = cargar_json_seguro(repuestos_str, [])
                for repuesto in repuestos:
                    if repuesto.get('id') == id:
                        productos_en_uso.append(f"Diagnóstico orden {orden_id}")
            except:
                pass
    
    # Si hay referencias, advertir al usuario
    if productos_en_uso:
        flash(f'No se puede eliminar el producto porque está en uso en: {", ".join(productos_en_uso[:5])}{" y más..." if len(productos_en_uso) > 5 else ""}', 'warning')
        return redirect(url_for('mostrar_inventario'))
    
    # Eliminar producto
    producto_nombre = inventario[id].get('nombre', 'Producto')
    del inventario[id]
    
    if guardar_datos(ARCHIVO_INVENTARIO, inventario):
        flash(f'Producto "{producto_nombre}" eliminado exitosamente', 'success')
    else:
        flash('Error al eliminar el producto', 'danger')
    
    return redirect(url_for('mostrar_inventario'))

@app.route('/inventario/<id>')
def ver_producto(id):
    """Muestra los detalles de un producto del inventario."""
    inventario = cargar_datos(ARCHIVO_INVENTARIO)
    producto = inventario.get(id)
    if not producto:
        flash('Producto no encontrado', 'danger')
        return redirect(url_for('mostrar_inventario'))
    return render_template('producto_detalle.html', producto=producto, id=id)


# ========================================
# RUTAS PARA GESTIÓN DE PROVEEDORES
# ========================================

@app.route('/proveedores')
@login_required
def mostrar_proveedores():
    """Listar todos los proveedores"""
    proveedores = cargar_datos('proveedores.json')
    config = cargar_configuracion()
    inventario = cargar_datos(ARCHIVO_INVENTARIO)
    
    # Contar productos por proveedor
    productos_por_proveedor = {}
    for prod_id, prod in inventario.items():
        prov = prod.get('proveedor', 'Sin proveedor')
        if prov not in productos_por_proveedor:
            productos_por_proveedor[prov] = 0
        productos_por_proveedor[prov] += 1
    
    return render_template('proveedores.html', proveedores=proveedores.get('proveedores', {}), 
                         config=config, productos_por_proveedor=productos_por_proveedor)

@app.route('/proveedores/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo_proveedor():
    """Crear o editar un proveedor"""
    if request.method == 'POST':
        try:
            proveedores = cargar_datos('proveedores.json')
            id_proveedor = request.form.get('id') or str(len(proveedores.get('proveedores', {})) + 1)
            
            proveedores['proveedores'][id_proveedor] = {
                'nombre': request.form.get('nombre', ''),
                'razon_social': request.form.get('razon_social', ''),
                'rif': request.form.get('rif', ''),
                'telefono': request.form.get('telefono', ''),
                'email': request.form.get('email', ''),
                'direccion': request.form.get('direccion', ''),
                'ciudad': request.form.get('ciudad', ''),
                'estado': request.form.get('estado', ''),
                'pais': request.form.get('pais', 'Venezuela'),
                'contacto_principal': request.form.get('contacto_principal', ''),
                'tipo_productos': request.form.get('tipo_productos', ''),
                'terminos_pago': request.form.get('terminos_pago', '30'),
                'tiempo_entrega_promedio': int(request.form.get('tiempo_entrega_promedio', 7)),
                'categoria_proveedor': request.form.get('categoria_proveedor', ''),
                'notas': request.form.get('notas', ''),
                'activo': request.form.get('activo') == 'on',
                'fecha_creacion': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'fecha_actualizacion': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            if guardar_datos('proveedores.json', proveedores):
                flash('Proveedor guardado exitosamente', 'success')
                return redirect(url_for('mostrar_proveedores'))
            else:
                flash('Error al guardar el proveedor', 'danger')
        except Exception as e:
            flash(f'Error: {str(e)}', 'danger')
    
    return render_template('proveedor_form.html')

@app.route('/proveedores/<id>/editar', methods=['GET', 'POST'])
@login_required
def editar_proveedor(id):
    """Editar un proveedor existente"""
    proveedores = cargar_datos('proveedores.json')
    
    if id not in proveedores.get('proveedores', {}):
        flash('Proveedor no encontrado', 'danger')
        return redirect(url_for('mostrar_proveedores'))
    
    if request.method == 'POST':
        try:
            proveedores['proveedores'][id].update({
                'nombre': request.form.get('nombre', ''),
                'razon_social': request.form.get('razon_social', ''),
                'rif': request.form.get('rif', ''),
                'telefono': request.form.get('telefono', ''),
                'email': request.form.get('email', ''),
                'direccion': request.form.get('direccion', ''),
                'ciudad': request.form.get('ciudad', ''),
                'estado': request.form.get('estado', ''),
                'pais': request.form.get('pais', 'Venezuela'),
                'contacto_principal': request.form.get('contacto_principal', ''),
                'tipo_productos': request.form.get('tipo_productos', ''),
                'terminos_pago': request.form.get('terminos_pago', '30'),
                'tiempo_entrega_promedio': int(request.form.get('tiempo_entrega_promedio', 7)),
                'categoria_proveedor': request.form.get('categoria_proveedor', ''),
                'notas': request.form.get('notas', ''),
                'activo': request.form.get('activo') == 'on',
                'fecha_actualizacion': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            
            if guardar_datos('proveedores.json', proveedores):
                flash('Proveedor actualizado exitosamente', 'success')
                return redirect(url_for('mostrar_proveedores'))
            else:
                flash('Error al actualizar el proveedor', 'danger')
        except Exception as e:
            flash(f'Error: {str(e)}', 'danger')
    
    proveedor = proveedores['proveedores'][id].copy()
    proveedor['id'] = id
    
    return render_template('proveedor_form.html', proveedor=proveedor)

@app.route('/proveedores/<id>/eliminar', methods=['POST'])
@login_required
def eliminar_proveedor(id):
    """Eliminar un proveedor"""
    proveedores = cargar_datos('proveedores.json')
    
    if id in proveedores.get('proveedores', {}):
        del proveedores['proveedores'][id]
        guardar_datos('proveedores.json', proveedores)
        flash('Proveedor eliminado exitosamente', 'success')
    else:
        flash('Proveedor no encontrado', 'danger')
    
    return redirect(url_for('mostrar_proveedores'))

@app.route('/api/proveedores/listar')
@login_required
def api_listar_proveedores():
    """API para listar proveedores activos"""
    proveedores = cargar_datos('proveedores.json')
    activos = {}
    
    for id_prov, prov in proveedores.get('proveedores', {}).items():
        if prov.get('activo', False):
            activos[id_prov] = prov
    
    return jsonify(activos)



# ========================================
# RUTAS PARA NOTAS DE ENTREGA
# ========================================

@app.route('/notas-entrega')
@login_required
def mostrar_notas_entrega():
    """Muestra la lista de notas de entrega con filtros y estadísticas."""
    try:
        # Cargar datos
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        
        # Calcular estadísticas
        estadisticas = {
            'total': len(notas),
            'pendientes': len([n for n in notas.values() if n.get('estado') == 'PENDIENTE_ENTREGA']),
            'entregadas': len([n for n in notas.values() if n.get('estado') == 'ENTREGADO']),
            'anuladas': len([n for n in notas.values() if n.get('estado') == 'ANULADO']),
            'valor_total': sum(safe_float(n.get('total_usd', 0)) for n in notas.values())
        }
        
        # Agregar nombre del cliente a cada nota
        for nota in notas.values():
            cliente_id = nota.get('cliente_id')
            if cliente_id and cliente_id in clientes:
                nota['cliente_nombre'] = clientes[cliente_id].get('nombre', 'Cliente no encontrado')
            else:
                nota['cliente_nombre'] = 'Cliente no encontrado'
        
        return render_template('notas_entrega_moderno.html', 
                             notas=notas, 
                             clientes=clientes,
                             estadisticas=estadisticas)
    except Exception as e:
        print(f"Error en mostrar_notas_entrega: {e}")
        flash('Error cargando notas de entrega', 'error')
        return redirect(url_for('index'))

@app.route('/notas-entrega/nueva', methods=['GET', 'POST'])
@login_required
def nueva_nota_entrega():
    """Crea una nueva nota de entrega."""
    if request.method == 'POST':
        try:
            # Obtener datos del formulario
            cliente_id = request.form.get('cliente_id')
            fecha = request.form.get('fecha')
            hora = request.form.get('hora', datetime.now().strftime('%H:%M:%S'))
            modalidad_pago = request.form.get('modalidad_pago', 'contado')
            
            # Validar campos obligatorios
            if not cliente_id or not fecha:
                flash('Error: Cliente y fecha son campos obligatorios', 'error')
                return redirect(url_for('nueva_nota_entrega'))
            dias_credito = request.form.get('dias_credito', '30')
            observaciones = request.form.get('observaciones', '')
            porcentaje_descuento = float(request.form.get('porcentaje_descuento', 0))
            
            # Obtener productos, cantidades y precios
            productos = request.form.getlist('productos[]')
            cantidades = request.form.getlist('cantidades[]')
            precios = request.form.getlist('precios[]')
            
            # Validar que hay productos
            if not productos or not cantidades or not precios:
                flash('La nota de entrega debe tener al menos un producto', 'error')
                return redirect(url_for('nueva_nota_entrega'))
            
            # Validar que todos los arrays tengan la misma longitud
            if not (len(productos) == len(cantidades) == len(precios)):
                flash('Error: Los productos, cantidades y precios deben tener la misma cantidad de elementos', 'error')
                return redirect(url_for('nueva_nota_entrega'))
            
            # Calcular totales
            try:
                subtotal_usd = sum(float(precios[i]) * int(cantidades[i]) for i in range(len(precios)))
            except (ValueError, TypeError, IndexError) as e:
                flash(f'Error calculando totales: {str(e)}', 'error')
                return redirect(url_for('nueva_nota_entrega'))
            descuento = subtotal_usd * (porcentaje_descuento / 100)
            total_usd = subtotal_usd - descuento
            
            # Obtener tasa BCV actual
            try:
                # Intentar obtener tasa del archivo primero
                tasa_bcv = obtener_tasa_bcv()
                if not tasa_bcv or tasa_bcv < 10:
                    # Si no hay tasa válida, intentar obtener del BCV
                    tasa_bcv = obtener_tasa_bcv_dia()
                    if not tasa_bcv or tasa_bcv < 10:
                        # Fallback con tasa realista
                        tasa_bcv = cargar_ultima_tasa_bcv()
                        if not tasa_bcv or tasa_bcv < 10:
                            tasa_bcv = 216.37  # Tasa real actual aproximada
                fecha_tasa_bcv = datetime.now().strftime('%Y-%m-%d')
                print(f"✅ Usando tasa BCV: {tasa_bcv}")
            except Exception as e:
                print(f"Error obteniendo tasa BCV: {e}")
                tasa_bcv = 216.37  # Tasa real actual
                fecha_tasa_bcv = datetime.now().strftime('%Y-%m-%d')
            
            # Obtener numeración secuencial interna (no fiscal)
            notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
            numero_secuencial = len(notas) + 1
            numero_nota = f"NE-{numero_secuencial:04d}"
            
            # Crear la nota de entrega
            nota = {
                'numero': numero_nota,
                'cliente_id': cliente_id,
                'fecha': fecha,
                'hora': hora,
                'modalidad_pago': modalidad_pago,
                'dias_credito': int(dias_credito) if modalidad_pago == 'credito' else None,
                'fecha_vencimiento': (datetime.strptime(fecha, '%Y-%m-%d') + timedelta(days=int(dias_credito))).strftime('%Y-%m-%d') if modalidad_pago == 'credito' and dias_credito else None,
                'productos': productos,
                'cantidades': [int(c) for c in cantidades],
                'precios': [float(p) for p in precios],
                'subtotal_usd': subtotal_usd,
                'descuento': descuento,
                'total_usd': total_usd,
                'tasa_bcv': tasa_bcv,
                'fecha_tasa_bcv': fecha_tasa_bcv,
                'total_bs': total_usd * tasa_bcv,
                'estado': 'PENDIENTE_ENTREGA',
                'observaciones': observaciones,
                'creado_por': session.get('usuario', 'SISTEMA'),
                'fecha_creacion': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'fecha_entrega': None,
                'entregado_por': None,
                'recibido_por': None,
                'firma_recibido': False
            }
            
            # Guardar la nota
            notas[numero_nota] = nota
            if guardar_datos(ARCHIVO_NOTAS_ENTREGA, notas):
                flash(f'Nota de entrega {numero_nota} creada exitosamente', 'success')
                return redirect(url_for('ver_nota_entrega', id=numero_nota))
            else:
                flash('Error guardando la nota de entrega', 'error')
                return redirect(url_for('nueva_nota_entrega'))
                
        except Exception as e:
            print(f"Error creando nota de entrega: {e}")
            flash(f'Error creando nota de entrega: {str(e)}', 'error')
            return redirect(url_for('nueva_nota_entrega'))
    
    # GET - Mostrar formulario
    clientes = cargar_datos(ARCHIVO_CLIENTES)
    inventario = cargar_datos(ARCHIVO_INVENTARIO)
    
    return render_template('nueva_nota_entrega.html', 
                         clientes=clientes, 
                         inventario=inventario)

@app.route('/notas-entrega/<id>')
@login_required
def ver_nota_entrega(id):
    """Muestra los detalles de una nota de entrega."""
    try:
        print(f"DEBUG: Intentando cargar nota de entrega {id}")
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        
        print(f"DEBUG: Notas cargadas: {len(notas)}, Clientes cargados: {len(clientes)}")
        
        if id not in notas:
            print(f"DEBUG: Nota {id} no encontrada en las notas disponibles: {list(notas.keys())}")
            flash('Nota de entrega no encontrada', 'error')
            return redirect(url_for('mostrar_notas_entrega'))
        
        nota = notas[id]
        print(f"DEBUG: Nota encontrada: {nota.get('numero', 'Sin número')}")
        
        cliente_id = nota.get('cliente_id')
        if not cliente_id:
            print(f"DEBUG: Nota {id} no tiene cliente_id")
            flash('La nota no tiene cliente asignado', 'error')
            return redirect(url_for('mostrar_notas_entrega'))
        
        print(f"DEBUG: Cliente ID: {cliente_id}")
        cliente = clientes.get(cliente_id, {})
        print(f"DEBUG: Cliente encontrado: {cliente.get('nombre', 'Sin nombre')}")
        
        # Agregar campos por defecto para compatibilidad
        nota['porcentaje_descuento'] = nota.get('porcentaje_descuento', 0)
        nota['descuento'] = nota.get('descuento', 0)
        nota['total_usd'] = nota.get('total_usd', nota.get('subtotal_usd', 0))
        nota['tasa_bcv'] = nota.get('tasa_bcv', 0)
        nota['fecha_tasa_bcv'] = nota.get('fecha_tasa_bcv', 'N/A')
        
        print(f"DEBUG: Renderizando template ver_nota_entrega.html")
        return render_template('ver_nota_entrega.html', 
                             nota=nota, 
                             cliente=cliente)
    except Exception as e:
        print(f"DEBUG: Error viendo nota de entrega: {e}")
        import traceback
        traceback.print_exc()
        flash('Error cargando nota de entrega', 'error')
        return redirect(url_for('mostrar_notas_entrega'))

@app.route('/notas-entrega/<id>/editar', methods=['GET', 'POST'])
@login_required
def editar_nota_entrega(id):
    """Edita una nota de entrega existente."""
    try:
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        
        if id not in notas:
            flash('Nota de entrega no encontrada', 'error')
            return redirect(url_for('mostrar_notas_entrega'))
        
        if request.method == 'POST':
            # Actualizar datos de la nota
            nota = notas[id]
            
            # Permitir edición de notas entregadas (solo campos no relacionados con productos)
            # Si está entregada y se cambian productos, advertir sobre impacto en inventario
            estado_original = nota.get('estado', 'PENDIENTE_ENTREGA')
            if estado_original == 'ENTREGADO':
                # Si está entregada, solo permitir edición de campos no críticos
                # No permitir cambios en productos para evitar inconsistencias de inventario
                productos_originales = nota.get('productos', [])
                cantidades_originales = nota.get('cantidades', [])
                
                productos_nuevos = request.form.getlist('productos[]')
                cantidades_nuevas = request.form.getlist('cantidades[]')
                
                # Normalizar cantidades a enteros para comparación
                try:
                    cant_orig_int = [int(c) if isinstance(c, str) else c for c in cantidades_originales]
                    cant_nuevas_int = [int(c) for c in cantidades_nuevas]
                except (ValueError, TypeError) as e:
                    print(f"Error normalizando cantidades: {e}")
                    cant_orig_int = cantidades_originales
                    cant_nuevas_int = [int(c) for c in cantidades_nuevas if c]
                
                # Verificar si hay cambios en productos
                if (productos_originales != productos_nuevos or cant_orig_int != cant_nuevas_int):
                    flash('No se pueden modificar productos de una nota ya entregada. Use duplicar nota para crear una nueva.', 'error')
                    return redirect(url_for('ver_nota_entrega', id=id))
            
            # Actualizar campos editables
            nota['fecha'] = request.form.get('fecha', nota.get('fecha', datetime.now().strftime('%Y-%m-%d')))
            nota['hora'] = request.form.get('hora', nota.get('hora', datetime.now().strftime('%H:%M:%S')))
            nota['modalidad_pago'] = request.form.get('modalidad_pago', nota.get('modalidad_pago', 'contado'))
            
            # Manejar días de crédito de forma segura
            if request.form.get('modalidad_pago') == 'credito':
                dias_credito_str = request.form.get('dias_credito', '30')
                try:
                    nota['dias_credito'] = int(dias_credito_str) if dias_credito_str else 30
                except (ValueError, TypeError):
                    nota['dias_credito'] = 30
            else:
                nota['dias_credito'] = None
            
            nota['observaciones'] = request.form.get('observaciones', nota.get('observaciones', ''))
            
            # Recalcular totales solo si no está entregada o si está pendiente y hay cambios en productos
            productos = request.form.getlist('productos[]')
            cantidades = request.form.getlist('cantidades[]')
            precios = request.form.getlist('precios[]')
            
            # Solo recalcular totales si está pendiente y hay cambios en productos
            if estado_original != 'ENTREGADO' and productos and cantidades and precios:
                # Validar que todos los arrays tengan la misma longitud
                if len(productos) == len(cantidades) == len(precios):
                    try:
                        subtotal_usd = sum(float(precios[i]) * int(cantidades[i]) for i in range(len(precios)))
                        porcentaje_descuento = float(request.form.get('porcentaje_descuento', 0))
                        descuento = subtotal_usd * (porcentaje_descuento / 100)
                        total_usd = subtotal_usd - descuento
                        
                        nota['productos'] = productos
                        nota['cantidades'] = [int(c) for c in cantidades]
                        nota['precios'] = [float(p) for p in precios]
                        nota['subtotal_usd'] = subtotal_usd
                        nota['descuento'] = descuento
                        nota['total_usd'] = total_usd
                        
                        # Obtener tasa BCV con fallback seguro
                        tasa_bcv = nota.get('tasa_bcv')
                        if not tasa_bcv or tasa_bcv < 1:
                            # Intentar obtener tasa actual
                            try:
                                tasa_temp = obtener_tasa_bcv()
                                if tasa_temp and tasa_temp > 1:
                                    tasa_bcv = tasa_temp
                                else:
                                    tasa_temp = cargar_ultima_tasa_bcv()
                                    if tasa_temp and tasa_temp > 1:
                                        tasa_bcv = tasa_temp
                                    else:
                                        tasa_bcv = 216.37  # Fallback
                                nota['tasa_bcv'] = tasa_bcv
                            except Exception as e:
                                print(f"Error obteniendo tasa BCV: {e}")
                                tasa_bcv = nota.get('tasa_bcv') or 216.37
                        
                        nota['total_bs'] = float(total_usd) * float(tasa_bcv)
                    except (ValueError, TypeError, IndexError) as e:
                        print(f"Error calculando totales: {e}")
                        flash(f'Error calculando totales: {str(e)}', 'error')
                else:
                    flash('Error: Los productos, cantidades y precios deben tener la misma cantidad de elementos', 'error')
                    return redirect(url_for('ver_nota_entrega', id=id))
            
            # Actualizar fecha de vencimiento si es crédito
            if nota.get('modalidad_pago') == 'credito' and nota.get('dias_credito'):
                try:
                    fecha_nota = nota.get('fecha')
                    if not fecha_nota:
                        fecha_nota = datetime.now().strftime('%Y-%m-%d')
                        nota['fecha'] = fecha_nota
                    
                    fecha_base = datetime.strptime(fecha_nota, '%Y-%m-%d')
                    dias = int(nota.get('dias_credito', 30))
                    nota['fecha_vencimiento'] = (fecha_base + timedelta(days=dias)).strftime('%Y-%m-%d')
                except (ValueError, TypeError, KeyError) as e:
                    print(f"Error calculando fecha de vencimiento: {e}")
                    # Si hay error, intentar calcular desde hoy
                    try:
                        dias_credito = int(nota.get('dias_credito', 30))
                        nota['fecha_vencimiento'] = (datetime.now() + timedelta(days=dias_credito)).strftime('%Y-%m-%d')
                    except Exception as e2:
                        print(f"Error en fallback de fecha de vencimiento: {e2}")
                        pass
            
            # Guardar cambios
            if guardar_datos(ARCHIVO_NOTAS_ENTREGA, notas):
                flash('Nota de entrega actualizada exitosamente', 'success')
                return redirect(url_for('ver_nota_entrega', id=id))
            else:
                flash('Error guardando cambios', 'error')
        
        # GET - Mostrar formulario de edición
        try:
            clientes = cargar_datos(ARCHIVO_CLIENTES) or {}
            inventario = cargar_datos(ARCHIVO_INVENTARIO) or {}
            nota = notas.get(id)
            
            if not nota:
                flash('Nota de entrega no encontrada', 'error')
                return redirect(url_for('mostrar_notas_entrega'))
            
            # Asegurar que la nota tenga todos los campos necesarios
            if 'productos' not in nota:
                nota['productos'] = []
            if 'cantidades' not in nota:
                nota['cantidades'] = []
            if 'precios' not in nota:
                nota['precios'] = []
            if 'tasa_bcv' not in nota or not nota.get('tasa_bcv'):
                try:
                    tasa_bcv = obtener_tasa_bcv() or cargar_ultima_tasa_bcv() or 216.37
                    nota['tasa_bcv'] = tasa_bcv
                except:
                    nota['tasa_bcv'] = 216.37
            
            # Inicializar campos numéricos y de descuento
            if 'subtotal_usd' not in nota:
                nota['subtotal_usd'] = nota.get('total_usd', 0)
            if 'descuento' not in nota:
                nota['descuento'] = 0
            if 'porcentaje_descuento' not in nota:
                subtotal = nota.get('subtotal_usd', 0) or nota.get('total_usd', 0)
                if subtotal > 0 and nota.get('descuento', 0) > 0:
                    nota['porcentaje_descuento'] = (nota.get('descuento', 0) / subtotal) * 100
                else:
                    nota['porcentaje_descuento'] = 0
            if 'total_usd' not in nota:
                nota['total_usd'] = nota.get('subtotal_usd', 0)
            if 'total_bs' not in nota:
                nota['total_bs'] = nota.get('total_usd', 0) * nota.get('tasa_bcv', 216.37)
            
            # Inicializar campos de texto opcionales
            if 'observaciones' not in nota:
                nota['observaciones'] = ''
            if 'modalidad_pago' not in nota:
                nota['modalidad_pago'] = 'contado'
            if 'dias_credito' not in nota:
                nota['dias_credito'] = None
            if 'hora' not in nota:
                nota['hora'] = datetime.now().strftime('%H:%M:%S')
            if 'fecha' not in nota:
                nota['fecha'] = datetime.now().strftime('%Y-%m-%d')
            if 'numero' not in nota:
                nota['numero'] = id
            if 'numero_secuencial' not in nota:
                nota['numero_secuencial'] = 1
            
            return render_template('editar_nota_entrega.html', 
                                 nota=nota, 
                                 clientes=clientes, 
                                 inventario=inventario)
        except Exception as e:
            print(f"Error cargando formulario de edición: {e}")
            import traceback
            traceback.print_exc()
            flash(f'Error cargando formulario de edición: {str(e)}', 'error')
            return redirect(url_for('mostrar_notas_entrega'))
    except Exception as e:
        import traceback
        error_detail = str(e)
        error_trace = traceback.format_exc()
        print(f"Error editando nota de entrega: {error_detail}")
        print(f"Traceback completo:\n{error_trace}")
        flash(f'Error editando nota de entrega: {error_detail}', 'error')
        
        # Intentar redirigir a la nota si tenemos el ID, sino al listado
        try:
            if 'id' in locals() and id:
                return redirect(url_for('ver_nota_entrega', id=id))
        except:
            pass
        
        return redirect(url_for('mostrar_notas_entrega'))

@app.route('/notas-entrega/<id>/entregar', methods=['POST'])
@login_required
def marcar_nota_entregada(id):
    """Marca una nota como entregada."""
    try:
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        
        if id not in notas:
            flash('Nota de entrega no encontrada', 'error')
            return redirect(url_for('mostrar_notas_entrega'))
        
        nota = notas[id]
        
        estado_actual = nota.get('estado', 'PENDIENTE_ENTREGA')
        if estado_actual != 'PENDIENTE_ENTREGA':
            flash('Solo se pueden entregar notas pendientes', 'error')
            return redirect(url_for('ver_nota_entrega', id=id))
        
        # Marcar como entregada
        nota['estado'] = 'ENTREGADO'
        nota['fecha_entrega'] = datetime.now().strftime('%Y-%m-%d')
        nota['hora_entrega'] = datetime.now().strftime('%H:%M:%S')
        nota['entregado_por'] = session.get('usuario', 'SISTEMA')
        nota['recibido_por'] = request.form.get('recibido_por', 'Cliente')
        nota['firma_recibido'] = True
        
        # Guardar cambios
        if guardar_datos(ARCHIVO_NOTAS_ENTREGA, notas):
            flash(f'Nota de entrega {id} marcada como entregada', 'success')
            
            # Notificar al cliente si está habilitado
            try:
                clientes = cargar_datos(ARCHIVO_CLIENTES)
                cliente_id = nota.get('cliente_id')
                if cliente_id and cliente_id in clientes:
                    cliente = clientes[cliente_id]
                    cliente_email = cliente.get('email', '')
                    cliente_telefono = cliente.get('telefono', '')
                    
                    mensaje_notificacion = f"""
📦 *Nota de Entrega {id} Entregada*

✅ Su pedido ha sido entregado exitosamente.

📋 *Detalles:*
• Nota: {id}
• Fecha: {nota['fecha_entrega']} - {nota['hora_entrega']}
• Entregado por: {nota['entregado_por']}
• Recibido por: {nota['recibido_por']}

💰 *Total:* ${nota.get('total_usd', 0)} USD
                            """
                    
                    notificar_cliente(
                        cliente_email,
                        cliente_telefono,
                        f"✅ Nota de Entrega {id} Entregada",
                        mensaje_notificacion,
                        'nota_entregada'
                    )
            except Exception as e:
                print(f"❌ Error notificando al cliente: {e}")
        else:
            flash('Error guardando cambios', 'error')
        
        return redirect(url_for('ver_nota_entrega', id=id))
    except Exception as e:
        print(f"Error marcando nota como entregada: {e}")
        flash('Error marcando nota como entregada', 'error')
        return redirect(url_for('mostrar_notas_entrega'))

@app.route('/notas-entrega/<id>/anular', methods=['POST'])
@login_required
def anular_nota_entrega(id):
    """Anula una nota de entrega."""
    try:
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        
        if id not in notas:
            flash('Nota de entrega no encontrada', 'error')
            return redirect(url_for('mostrar_notas_entrega'))
        
        nota = notas[id]
        
        estado_actual = nota.get('estado', 'PENDIENTE_ENTREGA')
        if estado_actual == 'ANULADO':
            flash('La nota ya está anulada', 'warning')
            return redirect(url_for('ver_nota_entrega', id=id))
        
        # Anular la nota
        nota['estado'] = 'ANULADO'
        nota['fecha_anulacion'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        nota['anulado_por'] = session.get('usuario', 'SISTEMA')
        nota['motivo_anulacion'] = request.form.get('motivo_anulacion', 'Sin motivo especificado')
        
        # Guardar cambios
        if guardar_datos(ARCHIVO_NOTAS_ENTREGA, notas):
            flash(f'Nota de entrega {id} anulada exitosamente', 'success')
        else:
            flash('Error guardando cambios', 'error')
        
        return redirect(url_for('ver_nota_entrega', id=id))
    except Exception as e:
        print(f"Error anulando nota de entrega: {e}")
        flash('Error anulando nota de entrega', 'error')
        return redirect(url_for('mostrar_notas_entrega'))

@app.route('/notas-entrega/<id>/eliminar', methods=['POST'])
@login_required
def eliminar_nota_entrega(id):
    """Elimina permanentemente una nota de entrega."""
    try:
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        
        if id not in notas:
            flash('Nota de entrega no encontrada', 'error')
            return redirect(url_for('mostrar_notas_entrega'))
        
        nota = notas[id]
        estado_nota = nota.get('estado', 'PENDIENTE_ENTREGA')
        
        # Si la nota está entregada, restaurar stock del inventario antes de eliminar
        if estado_nota == 'ENTREGADO':
            try:
                inventario = cargar_datos(ARCHIVO_INVENTARIO)
                productos = nota.get('productos', [])
                cantidades = nota.get('cantidades', [])
                movimientos = []
                
                for i, producto_id in enumerate(productos):
                    if producto_id in inventario and i < len(cantidades):
                        cantidad_restaurada = int(cantidades[i])
                        
                        # Usar 'cantidad' como campo principal, con fallback a 'stock' por compatibilidad
                        cantidad_actual = inventario[producto_id].get('cantidad')
                        if cantidad_actual is None:
                            cantidad_actual = inventario[producto_id].get('stock', 0)
                        cantidad_actual = int(cantidad_actual)
                        
                        nuevo_stock = cantidad_actual + cantidad_restaurada
                        inventario[producto_id]['cantidad'] = nuevo_stock
                        
                        # Registrar movimiento
                        movimiento = {
                            'fecha': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                            'tipo': 'ENTRADA',
                            'motivo': f'Restauración por eliminación de nota de entrega {id}',
                            'producto_id': producto_id,
                            'producto_nombre': inventario[producto_id].get('nombre', 'N/A'),
                            'cantidad': cantidad_restaurada,
                            'cantidad_anterior': cantidad_actual,
                            'cantidad_nueva': nuevo_stock,
                            'usuario': session.get('usuario', 'SISTEMA')
                        }
                        movimientos.append(movimiento)
                        
                        print(f"✅ Stock restaurado: Producto {producto_id} - {cantidad_actual} + {cantidad_restaurada} = {nuevo_stock}")
                
                # Guardar inventario actualizado
                if guardar_datos(ARCHIVO_INVENTARIO, inventario):
                    # Registrar movimientos
                    if movimientos:
                        registrar_movimientos_inventario(movimientos)
                    print(f"✅ Inventario restaurado para nota {id}")
                else:
                    print(f"⚠️ Error guardando inventario al restaurar stock de nota {id}")
            except Exception as e:
                print(f"❌ Error restaurando stock al eliminar nota {id}: {e}")
                # Continuar con la eliminación aunque falle la restauración de stock
                flash(f'Nota eliminada, pero hubo un error restaurando el inventario: {str(e)}', 'warning')
        
        # Eliminar la nota
        del notas[id]
        
        # Guardar cambios
        if guardar_datos(ARCHIVO_NOTAS_ENTREGA, notas):
            # Registrar en bitácora
            try:
                registrar_bitacora(session.get('usuario', 'SISTEMA'), 'Eliminar nota de entrega', 
                                 f"Nota eliminada: {id}, Cliente: {nota.get('cliente_nombre', 'N/A')}, Estado: {estado_nota}")
            except:
                pass  # Si hay error en bitácora, no fallar el proceso
            
            mensaje = f'Nota de entrega {id} eliminada exitosamente'
            if estado_nota == 'ENTREGADO':
                mensaje += ' (stock restaurado)'
            flash(mensaje, 'success')
        else:
            flash('Error guardando cambios', 'error')
        
        return redirect(url_for('mostrar_notas_entrega'))
    except Exception as e:
        print(f"Error eliminando nota de entrega: {e}")
        flash('Error eliminando nota de entrega', 'error')
        return redirect(url_for('mostrar_notas_entrega'))

@app.route('/notas-entrega/<id>/duplicar', methods=['POST'])
@login_required
def duplicar_nota_entrega(id):
    """Duplica una nota de entrega existente."""
    try:
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        
        if id not in notas:
            flash('Nota de entrega no encontrada', 'error')
            return redirect(url_for('mostrar_notas_entrega'))
        
        # Obtener la nota original
        nota_original = notas[id]
        
        # Generar nuevo número
        numero_secuencial = len(notas) + 1
        nuevo_numero = f"NE-{numero_secuencial:04d}"
        
        # Crear copia de la nota
        nueva_nota = nota_original.copy()
        nueva_nota['numero'] = nuevo_numero
        nueva_nota['fecha'] = datetime.now().strftime('%Y-%m-%d')
        nueva_nota['hora'] = datetime.now().strftime('%H:%M:%S')
        nueva_nota['estado'] = 'PENDIENTE_ENTREGA'
        nueva_nota['fecha_creacion'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        nueva_nota['creado_por'] = session.get('usuario', 'SISTEMA')
        nueva_nota['fecha_entrega'] = None
        nueva_nota['entregado_por'] = None
        nueva_nota['recibido_por'] = None
        nueva_nota['firma_recibido'] = False
        
        # Actualizar fecha de vencimiento si es crédito
        if nueva_nota.get('modalidad_pago') == 'credito' and nueva_nota.get('dias_credito'):
            try:
                fecha_nota = nueva_nota.get('fecha')
                if not fecha_nota:
                    fecha_nota = datetime.now().strftime('%Y-%m-%d')
                    nueva_nota['fecha'] = fecha_nota
                
                fecha_base = datetime.strptime(fecha_nota, '%Y-%m-%d')
                dias = int(nueva_nota.get('dias_credito', 30))
                nueva_nota['fecha_vencimiento'] = (fecha_base + timedelta(days=dias)).strftime('%Y-%m-%d')
            except (ValueError, TypeError, KeyError) as e:
                print(f"Error calculando fecha de vencimiento al duplicar: {e}")
                try:
                    dias_credito = int(nueva_nota.get('dias_credito', 30))
                    nueva_nota['fecha_vencimiento'] = (datetime.now() + timedelta(days=dias_credito)).strftime('%Y-%m-%d')
                except:
                    pass
        
        # Guardar la nueva nota
        notas[nuevo_numero] = nueva_nota
        if guardar_datos(ARCHIVO_NOTAS_ENTREGA, notas):
            flash(f'Nota de entrega duplicada como {nuevo_numero}', 'success')
            return redirect(url_for('ver_nota_entrega', id=nuevo_numero))
        else:
            flash('Error guardando la nota duplicada', 'error')
            return redirect(url_for('ver_nota_entrega', id=id))
    except Exception as e:
        print(f"Error duplicando nota de entrega: {e}")
        flash('Error duplicando nota de entrega', 'error')
        return redirect(url_for('mostrar_notas_entrega'))

@app.route('/nota/qr/<id>')
def ver_nota_qr(id):
    """Muestra la información de la nota cuando se escanea el QR."""
    try:
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        
        if id not in notas:
            return render_template('qr_error.html', 
                                 mensaje=f"Nota de entrega {id} no encontrada")
        
        nota = notas[id]
        cliente_id = nota.get('cliente_id')
        cliente = clientes.get(cliente_id, {})
        
        # Crear resumen de información
        info_nota = {
            'numero': nota.get('numero', id),
            'fecha': nota.get('fecha', 'N/A'),
            'hora': nota.get('hora', ''),
            'estado': nota.get('estado', ''),
            'total_usd': nota.get('total_usd', 0),
            'total_bs': nota.get('total_bs', 0),
            'tasa_bcv': nota.get('tasa_bcv', 0),
            'productos': len(nota.get('productos', [])),
            'cliente': cliente.get('nombre', 'Cliente no especificado'),
            'modalidad': nota.get('modalidad_pago', ''),
            'observaciones': nota.get('observaciones', '')
        }
        
        return render_template('qr_nota_entrega.html', nota=info_nota)
    except Exception as e:
        print(f"Error mostrando QR de nota: {e}")
        return render_template('qr_error.html', mensaje="Error cargando la nota")

@app.route('/notas-entrega/<id>/imprimir')
@login_required
def imprimir_nota_entrega(id):
    """Genera PDF de la nota de entrega."""
    try:
        print(f"DEBUG: Intentando imprimir nota de entrega {id}")
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        inventario = cargar_datos(ARCHIVO_INVENTARIO)
        
        print(f"DEBUG: Datos cargados - Notas: {len(notas)}, Clientes: {len(clientes)}, Inventario: {len(inventario)}")
        
        if id not in notas:
            print(f"DEBUG: Nota {id} no encontrada en las notas disponibles: {list(notas.keys())}")
            flash('Nota de entrega no encontrada', 'error')
            return redirect(url_for('mostrar_notas_entrega'))
        
        nota = notas[id]
        print(f"DEBUG: Nota encontrada: {nota.get('numero', 'Sin número')}")
        
        cliente_id = nota.get('cliente_id')
        if not cliente_id:
            print(f"DEBUG: Nota {id} no tiene cliente_id")
            flash('La nota no tiene cliente asignado', 'error')
            return redirect(url_for('mostrar_notas_entrega'))
        
        cliente = clientes.get(cliente_id, {})
        print(f"DEBUG: Cliente encontrado: {cliente.get('nombre', 'Sin nombre')}")
        
        # Agregar información completa del cliente a la nota
        nota['cliente_nombre'] = cliente.get('nombre', 'Cliente no encontrado')
        nota['cliente_identificacion'] = cliente.get('identificacion', cliente.get('rif', ''))
        nota['cliente_direccion'] = cliente.get('direccion', '')
        nota['cliente_telefono'] = cliente.get('telefono', '')
        nota['cliente_email'] = cliente.get('email', '')
        
        # Procesar productos para notas generadas desde servicio técnico
        if 'productos' in nota and isinstance(nota['productos'], list):
            # Nota normal con IDs de productos
            productos_nombres = []
            productos_codigos = []
            
            for producto_id in nota.get('productos', []):
                producto = inventario.get(str(producto_id), {})
                productos_nombres.append(producto.get('nombre', f'Producto ID: {producto_id}'))
                productos_codigos.append(producto.get('codigo', ''))
            
            nota['productos_nombres'] = productos_nombres
            nota['productos_codigos'] = productos_codigos
        else:
            # Nota generada desde servicio técnico - usar productos_nota directamente
            productos_nombres = nota.get('productos', [])
            productos_codigos = [''] * len(productos_nombres)  # Sin códigos para servicios
            
            nota['productos_nombres'] = productos_nombres
            nota['productos_codigos'] = productos_codigos
        
        # Agregar campos por defecto para compatibilidad
        nota['porcentaje_descuento'] = nota.get('porcentaje_descuento', 0)
        nota['descuento'] = nota.get('descuento', 0)
        nota['total_usd'] = nota.get('total_usd', nota.get('subtotal_usd', 0))
        nota['tasa_bcv'] = nota.get('tasa_bcv', 0)
        nota['fecha_tasa_bcv'] = nota.get('fecha_tasa_bcv', 'N/A')
        
        # Cargar tasa BCV si no está disponible
        if not nota.get('tasa_bcv') or nota.get('tasa_bcv') == 0:
            try:
                with open(ULTIMA_TASA_BCV_FILE, 'r', encoding='utf-8') as f:
                    tasa_data = json.load(f)
                    nota['tasa_bcv'] = tasa_data.get('tasa', 0)
                    nota['fecha_tasa_bcv'] = tasa_data.get('fecha', 'N/A')
            except:
                nota['tasa_bcv'] = 0
                nota['fecha_tasa_bcv'] = 'N/A'
        
        # Generar QR con la URL para escanear
        try:
            # Obtener la URL base del request
            base_url = request.url_root.rstrip('/')
            qr_url = f"{base_url}/nota/qr/{id}"
            print(f"DEBUG: QR URL generada: {qr_url}")
            
            # Generar el código QR
            qr_base64 = generar_qr_base64(qr_url)
            if qr_base64:
                print(f"DEBUG: QR generado exitosamente")
            else:
                print(f"DEBUG: Error generando QR")
                qr_base64 = None
        except Exception as e:
            print(f"DEBUG: Error generando QR: {e}")
            qr_base64 = None
        
        print(f"DEBUG: QR Base64 generado: {qr_base64[:50] if qr_base64 else 'None'}...")
        print(f"DEBUG: Renderizando template pdf_nota_entrega.html")
        print(f"DEBUG: QR URL: {qr_url if 'qr_url' in locals() else 'No generada'}")
        
        return render_template('pdf_nota_entrega.html', 
                             nota=nota, 
                             cliente=cliente,
                             qr_url=qr_url if 'qr_url' in locals() else '',
                             qr_base64=qr_base64)
    except Exception as e:
        print(f"DEBUG: Error generando PDF: {e}")
        import traceback
        traceback.print_exc()
        flash('Error generando PDF', 'error')
        return redirect(url_for('ver_nota_entrega', id=id))


@app.route('/test-whatsapp')
def test_whatsapp():
    return jsonify({'message': 'Ruta de prueba funcionando'})

@app.route('/test-notas')
def test_notas():
    return jsonify({'message': 'Ruta de notas funcionando', 'rutas': [str(rule) for rule in app.url_map.iter_rules() if 'nota' in str(rule)]})

@app.route('/notas-entrega/reporte')
@login_required
def reporte_notas_entrega():
    """Reporte de notas de entrega con filtro por mes."""
    try:
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        
        # Obtener parámetros de filtro
        mes_filtro = request.args.get('mes', '')
        año_filtro = request.args.get('año', '')
        
        # Filtrar notas por mes y año
        notas_filtradas = {}
        if mes_filtro and año_filtro:
            for numero, nota in notas.items():
                fecha_nota = datetime.strptime(nota.get('fecha', ''), '%Y-%m-%d')
                if fecha_nota.month == int(mes_filtro) and fecha_nota.year == int(año_filtro):
                    notas_filtradas[numero] = nota
        else:
            # Si no hay filtros, mostrar todas las notas
            notas_filtradas = notas
        
        # Agregar información del cliente a cada nota
        for numero, nota in notas_filtradas.items():
            cliente_id = nota.get('cliente_id')
            if cliente_id and cliente_id in clientes:
                nota['cliente_nombre'] = clientes[cliente_id].get('nombre', 'Cliente no especificado')
                nota['cliente_telefono'] = clientes[cliente_id].get('telefono', '')
            else:
                nota['cliente_nombre'] = 'Cliente no especificado'
                nota['cliente_telefono'] = ''
        
        # Calcular estadísticas
        total_notas = len(notas_filtradas)
        total_usd = sum(nota.get('total_usd', 0) for nota in notas_filtradas.values())
        total_bs = sum(nota.get('total_bs', 0) for nota in notas_filtradas.values())
        
        # Obtener opciones de meses y años
        meses = [
            {'valor': '1', 'nombre': 'Enero'}, {'valor': '2', 'nombre': 'Febrero'},
            {'valor': '3', 'nombre': 'Marzo'}, {'valor': '4', 'nombre': 'Abril'},
            {'valor': '5', 'nombre': 'Mayo'}, {'valor': '6', 'nombre': 'Junio'},
            {'valor': '7', 'nombre': 'Julio'}, {'valor': '8', 'nombre': 'Agosto'},
            {'valor': '9', 'nombre': 'Septiembre'}, {'valor': '10', 'nombre': 'Octubre'},
            {'valor': '11', 'nombre': 'Noviembre'}, {'valor': '12', 'nombre': 'Diciembre'}
        ]
        
        años = []
        año_actual = datetime.now().year
        for año in range(año_actual - 2, año_actual + 1):
            años.append({'valor': str(año), 'nombre': str(año)})
        
        return render_template('reporte_notas_entrega.html', 
                             notas=notas_filtradas,
                             total_notas=total_notas,
                             total_usd=total_usd,
                             total_bs=total_bs,
                             mes_filtro=mes_filtro,
                             año_filtro=año_filtro,
                             meses=meses,
                             años=años)
    except Exception as e:
        print(f"Error en reporte_notas_entrega: {e}")
        flash('Error generando el reporte', 'error')
        return redirect(url_for('mostrar_notas_entrega'))

@app.route('/notas-entrega/reporte/imprimir')
@login_required
def imprimir_reporte_notas():
    """Imprimir reporte de notas de entrega en PDF."""
    try:
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        
        # Obtener parámetros de filtro
        mes_filtro = request.args.get('mes', '')
        año_filtro = request.args.get('año', '')
        
        # Filtrar notas por mes y año
        notas_filtradas = {}
        if mes_filtro and año_filtro:
            for numero, nota in notas.items():
                fecha_nota = datetime.strptime(nota.get('fecha', ''), '%Y-%m-%d')
                if fecha_nota.month == int(mes_filtro) and fecha_nota.year == int(año_filtro):
                    notas_filtradas[numero] = nota
        else:
            # Si no hay filtros, mostrar todas las notas
            notas_filtradas = notas
        
        # Agregar información del cliente a cada nota
        for numero, nota in notas_filtradas.items():
            cliente_id = nota.get('cliente_id')
            if cliente_id and cliente_id in clientes:
                nota['cliente_nombre'] = clientes[cliente_id].get('nombre', 'Cliente no especificado')
                nota['cliente_telefono'] = clientes[cliente_id].get('telefono', '')
            else:
                nota['cliente_nombre'] = 'Cliente no especificado'
                nota['cliente_telefono'] = ''
        
        # Calcular estadísticas
        total_notas = len(notas_filtradas)
        total_usd = sum(nota.get('total_usd', 0) for nota in notas_filtradas.values())
        total_bs = sum(nota.get('total_bs', 0) for nota in notas_filtradas.values())
        
        # Obtener nombre del mes
        meses = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
                'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
        nombre_mes = meses[int(mes_filtro)] if mes_filtro else 'Todos'
        
        return render_template('pdf_reporte_notas_entrega.html',
                             notas=notas_filtradas,
                             total_notas=total_notas,
                             total_usd=total_usd,
                             total_bs=total_bs,
                             mes_filtro=mes_filtro,
                             año_filtro=año_filtro,
                             nombre_mes=nombre_mes)
    except Exception as e:
        print(f"Error en imprimir_reporte_notas: {e}")
        flash('Error generando el PDF del reporte', 'error')
        return redirect(url_for('reporte_notas_entrega'))

# ===== MÓDULO DE PAGOS RECIBIDOS =====

@app.route('/pagos-recibidos')
@login_required
def mostrar_pagos_recibidos():
    """Mostrar lista de pagos recibidos."""
    try:
        print(f"DEBUG: Iniciando mostrar_pagos_recibidos")
        
        # Cargar pagos
        pagos = cargar_datos(ARCHIVO_PAGOS_RECIBIDOS)
        print(f"DEBUG: Pagos cargados: {len(pagos)}")
        
        # Obtener filtros
        metodo_filtro = request.args.get('metodo', '')
        cliente_filtro = request.args.get('cliente', '')
        fecha_desde = request.args.get('fecha_desde', '')
        fecha_hasta = request.args.get('fecha_hasta', '')
        
        print(f"DEBUG: Filtros - método: {metodo_filtro}, cliente: {cliente_filtro}, fecha_desde: {fecha_desde}, fecha_hasta: {fecha_hasta}")
        
        # Obtener tasa BCV para cálculos
        tasa_bcv_calc = obtener_tasa_bcv() or 216.37
        
        # Calcular monto_bs para todos los pagos si no existe
        for id_pago, pago in pagos.items():
            if 'monto_bs' not in pago or not pago.get('monto_bs'):
                monto_usd = float(pago.get('monto_usd', 0))
                tasa_pago = float(pago.get('tasa_bcv', tasa_bcv_calc))
                pago['monto_bs'] = monto_usd * tasa_pago
                print(f"DEBUG: Calculado monto_bs para {id_pago}: {pago['monto_bs']}")
        
        # Filtrar pagos
        pagos_filtrados = {}
        for id_pago, pago in pagos.items():
            # Filtro por método
            if metodo_filtro and pago.get('metodo_pago', '') != metodo_filtro:
                continue
            
            # Filtro por cliente
            if cliente_filtro and cliente_filtro.lower() not in pago.get('cliente', '').lower():
                continue
            
            # Filtro por fecha (con manejo de errores)
            if fecha_desde:
                try:
                    fecha_pago_str = pago.get('fecha', '')
                    if fecha_pago_str and fecha_pago_str.strip():
                        fecha_pago = datetime.strptime(fecha_pago_str, '%Y-%m-%d')
                        fecha_desde_obj = datetime.strptime(fecha_desde, '%Y-%m-%d')
                        if fecha_pago < fecha_desde_obj:
                            continue
                except (ValueError, TypeError) as e:
                    print(f"Error en filtro fecha_desde: {e}")
                    continue  # Si la fecha no es válida, excluir el pago
            
            if fecha_hasta:
                try:
                    fecha_pago_str = pago.get('fecha', '')
                    if fecha_pago_str and fecha_pago_str.strip():
                        fecha_pago = datetime.strptime(fecha_pago_str, '%Y-%m-%d')
                        fecha_hasta_obj = datetime.strptime(fecha_hasta, '%Y-%m-%d')
                        if fecha_pago > fecha_hasta_obj:
                            continue
                except (ValueError, TypeError) as e:
                    print(f"Error en filtro fecha_hasta: {e}")
                    continue  # Si la fecha no es válida, excluir el pago
            
            pagos_filtrados[id_pago] = pago
        
        # Obtener clientes para el filtro
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        
        # Calcular pagos pendientes por cliente
        pagos_pendientes = {}
        
        # Cargar notas de entrega para calcular pendientes
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        tasa_bcv = obtener_tasa_bcv()
        
        for cliente_id, cliente in clientes.items():
            total_pendiente_usd = 0
            total_pendiente_bs = 0
            
            for nota_id, nota in notas.items():
                if nota.get('cliente_id') == cliente_id:
                    total_usd = float(nota.get('total_usd', 0))
                    total_abonado = float(nota.get('total_abonado', 0))
                    saldo_pendiente = max(0, total_usd - total_abonado)
                    
                    if saldo_pendiente > 0:
                        total_pendiente_usd += saldo_pendiente
                        total_pendiente_bs += saldo_pendiente * float(nota.get('tasa_bcv', tasa_bcv))
            
            if total_pendiente_usd > 0:
                pagos_pendientes[cliente_id] = {
                    'total_usd': total_pendiente_usd,
                    'total_bs': total_pendiente_bs
                }
        
        # Métodos de pago disponibles
        metodos_pago = ['Efectivo', 'Transferencia', 'Pago Móvil', 'Zelle', 'Divisas']
        
        return render_template('pagos_recibidos.html', 
                             pagos=pagos_filtrados,
                             clientes=clientes,
                             metodos_pago=metodos_pago,
                             metodo_filtro=metodo_filtro,
                             cliente_filtro=cliente_filtro,
                             fecha_desde=fecha_desde,
                             fecha_hasta=fecha_hasta,
                             pagos_pendientes=pagos_pendientes)
    except Exception as e:
        print(f"Error en mostrar_pagos_recibidos: {e}")
        flash('Error cargando los pagos recibidos', 'error')
        return redirect(url_for('index'))

@app.route('/pagos-recibidos/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo_pago_recibido():
    """Crear nuevo pago recibido."""
    if request.method == 'POST':
        try:
            # Obtener datos del formulario
            cliente = request.form.get('cliente', '').strip()
            monto_usd = float(request.form.get('monto_usd', 0))
            monto_bs = float(request.form.get('monto_bs', 0))
            metodo_pago = request.form.get('metodo_pago', '')
            numero_referencia = request.form.get('numero_referencia', '').strip()
            banco = request.form.get('banco', '').strip()
            observaciones = request.form.get('observaciones', '').strip()
            numero_nota = request.form.get('numero_nota', '').strip()
            
            # Validar datos requeridos
            if not cliente or not metodo_pago:
                flash('Cliente y método de pago son requeridos', 'error')
                return redirect(url_for('nuevo_pago_recibido'))
            
            # Obtener tasa BCV actual
            tasa_bcv = obtener_tasa_bcv()
            
            # Calcular montos si no se proporcionaron
            if monto_usd > 0 and monto_bs == 0:
                monto_bs = monto_usd * tasa_bcv
            elif monto_bs > 0 and monto_usd == 0:
                monto_usd = monto_bs / tasa_bcv
            
            # Crear ID único para el pago
            id_pago = str(uuid4())
            
            # Manejar archivo adjunto (comprobante)
            comprobante_adjunto = None
            if 'comprobante_adjunto' in request.files:
                archivo = request.files['comprobante_adjunto']
                if archivo and archivo.filename != '' and allowed_file(archivo.filename):
                    try:
                        # Generar nombre único para el archivo
                        filename = secure_filename(archivo.filename)
                        extension = filename.rsplit('.', 1)[1].lower()
                        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                        filename = f"comprobante_{id_pago}_{timestamp}.{extension}"
                        
                        # Ruta completa del archivo
                        ruta_archivo = os.path.join(UPLOAD_FOLDER, filename)
                        
                        # Guardar el archivo
                        archivo.save(ruta_archivo)
                        
                        # Guardar la ruta relativa para el frontend (desde static/)
                        comprobante_adjunto = f"uploads/{filename}"
                        print(f"✅ Comprobante guardado: {comprobante_adjunto}")
                    except Exception as e:
                        print(f"Error guardando comprobante: {e}")
            
            # Crear objeto pago
            pago = {
                'id': id_pago,
                'cliente': cliente,
                'monto_usd': monto_usd,
                'monto_bs': monto_bs,
                'metodo_pago': metodo_pago,
                'numero_referencia': numero_referencia,
                'banco': banco,
                'observaciones': observaciones,
                'numero_nota': numero_nota,
                'fecha': datetime.now().strftime('%Y-%m-%d'),
                'hora': datetime.now().strftime('%H:%M:%S'),
                'tasa_bcv': tasa_bcv,
                'usuario': session.get('username', 'Sistema'),
                'comprobante_adjunto': comprobante_adjunto
            }
            
            # Guardar pago
            pagos = cargar_datos(ARCHIVO_PAGOS_RECIBIDOS)
            pagos[id_pago] = pago
            guardar_datos(ARCHIVO_PAGOS_RECIBIDOS, pagos)
            
            # Si está asociado a una nota, actualizar cuenta por cobrar
            if numero_nota:
                actualizar_cuenta_por_cobrar(numero_nota, monto_usd, monto_bs)
            
            # Notificar al cliente si está habilitado
            try:
                clientes = cargar_datos(ARCHIVO_CLIENTES)
                # Buscar cliente por nombre
                for cliente_id, cliente_data in clientes.items():
                    if cliente_data.get('nombre') == cliente:
                        cliente_email = cliente_data.get('email', '')
                        cliente_telefono = cliente_data.get('telefono', '')
                        
                        mensaje_notificacion = f"""
💰 *Pago Recibido*

✅ Hemos recibido su pago exitosamente.

📋 *Detalles:*
• Monto: ${monto_usd} USD / Bs. {monto_bs}
• Método: {metodo_pago}
• Referencia: {numero_referencia if numero_referencia else 'N/A'}
• Fecha: {pago['fecha']} - {pago['hora']}
• Nota: {numero_nota if numero_nota else 'N/A'}

Gracias por su pago.
                        """
                        
                        notificar_cliente(
                            cliente_email,
                            cliente_telefono,
                            "💰 Pago Recibido",
                            mensaje_notificacion,
                            'pago_recibido'
                        )
                        break
            except Exception as e:
                print(f"❌ Error notificando pago al cliente: {e}")
            
            flash('Pago registrado exitosamente', 'success')
            return redirect(url_for('mostrar_pagos_recibidos'))
            
        except Exception as e:
            print(f"Error en nuevo_pago_recibido: {e}")
            flash('Error registrando el pago', 'error')
            return redirect(url_for('nuevo_pago_recibido'))
    
    # GET - Mostrar formulario
    try:
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        tasa_bcv = obtener_tasa_bcv()
        
        # Calcular pagos pendientes por cliente
        pagos_pendientes = {}
        for cliente_id, cliente in clientes.items():
            total_pendiente_usd = 0
            total_pendiente_bs = 0
            
            for nota_id, nota in notas.items():
                if nota.get('cliente_id') == cliente_id:
                    total_usd = float(nota.get('total_usd', 0))
                    total_abonado = float(nota.get('total_abonado', 0))
                    saldo_pendiente = max(0, total_usd - total_abonado)
                    
                    if saldo_pendiente > 0:
                        total_pendiente_usd += saldo_pendiente
                        total_pendiente_bs += saldo_pendiente * float(nota.get('tasa_bcv', tasa_bcv))
            
            if total_pendiente_usd > 0:
                pagos_pendientes[cliente_id] = {
                    'total_usd': total_pendiente_usd,
                    'total_bs': total_pendiente_bs
                }
        
        # Métodos de pago disponibles
        metodos_pago = ['Efectivo', 'Transferencia', 'Pago Móvil', 'Zelle', 'Divisas']
        
        return render_template('nuevo_pago_recibido.html',
                             clientes=clientes,
                             notas=notas,
                             metodos_pago=metodos_pago,
                             tasa_bcv=tasa_bcv,
                             pagos_pendientes=pagos_pendientes)
    except Exception as e:
        print(f"Error cargando formulario nuevo_pago_recibido: {e}")
        flash('Error cargando el formulario', 'error')
        return redirect(url_for('mostrar_pagos_recibidos'))

@app.route('/pagos-recibidos/<id>')
@login_required
def ver_pago_recibido(id):
    """Ver detalles de un pago recibido."""
    try:
        pagos = cargar_datos(ARCHIVO_PAGOS_RECIBIDOS)
        pago = pagos.get(id)
        
        if not pago:
            flash('Pago no encontrado', 'error')
            return redirect(url_for('mostrar_pagos_recibidos'))
        
        return render_template('ver_pago_recibido.html', pago=pago)
    except Exception as e:
        print(f"Error en ver_pago_recibido: {e}")
        flash('Error cargando el pago', 'error')
        return redirect(url_for('mostrar_pagos_recibidos'))

@app.route('/pagos-recibidos/<id>/editar', methods=['GET', 'POST'])
@login_required
def editar_pago_recibido(id):
    """Editar pago recibido."""
    if request.method == 'POST':
        try:
            pagos = cargar_datos(ARCHIVO_PAGOS_RECIBIDOS)
            pago = pagos.get(id)
            
            if not pago:
                flash('Pago no encontrado', 'error')
                return redirect(url_for('mostrar_pagos_recibidos'))
            
            # Actualizar datos
            pago['cliente'] = request.form.get('cliente', '').strip()
            pago['monto_usd'] = float(request.form.get('monto_usd', 0))
            pago['monto_bs'] = float(request.form.get('monto_bs', 0))
            pago['metodo_pago'] = request.form.get('metodo_pago', '')
            pago['numero_referencia'] = request.form.get('numero_referencia', '').strip()
            pago['banco'] = request.form.get('banco', '').strip()
            pago['observaciones'] = request.form.get('observaciones', '').strip()
            pago['numero_nota'] = request.form.get('numero_nota', '').strip()
            pago['fecha_modificacion'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # Guardar cambios
            pagos[id] = pago
            guardar_datos(ARCHIVO_PAGOS_RECIBIDOS, pagos)
            
            flash('Pago actualizado exitosamente', 'success')
            return redirect(url_for('ver_pago_recibido', id=id))
            
        except Exception as e:
            print(f"Error en editar_pago_recibido: {e}")
            flash('Error actualizando el pago', 'error')
            return redirect(url_for('editar_pago_recibido', id=id))
    
    # GET - Mostrar formulario de edición
    try:
        pagos = cargar_datos(ARCHIVO_PAGOS_RECIBIDOS)
        pago = pagos.get(id)
        
        if not pago:
            flash('Pago no encontrado', 'error')
            return redirect(url_for('mostrar_pagos_recibidos'))
        
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        
        # Métodos de pago disponibles
        metodos_pago = ['Efectivo', 'Transferencia', 'Pago Móvil', 'Zelle', 'Divisas']
        
        return render_template('editar_pago_recibido.html',
                             pago=pago,
                             clientes=clientes,
                             notas=notas,
                             metodos_pago=metodos_pago)
    except Exception as e:
        print(f"Error cargando formulario editar_pago_recibido: {e}")
        flash('Error cargando el formulario', 'error')
        return redirect(url_for('mostrar_pagos_recibidos'))

@app.route('/pagos-recibidos/<id>/eliminar', methods=['POST'])
@login_required
def eliminar_pago_recibido(id):
    """Eliminar pago recibido."""
    try:
        pagos = cargar_datos(ARCHIVO_PAGOS_RECIBIDOS)
        pago = pagos.get(id)
        
        if not pago:
            flash('Pago no encontrado', 'error')
            return redirect(url_for('mostrar_pagos_recibidos'))
        
        # Eliminar pago
        del pagos[id]
        guardar_datos(ARCHIVO_PAGOS_RECIBIDOS, pagos)
        
        flash('Pago eliminado exitosamente', 'success')
        return redirect(url_for('mostrar_pagos_recibidos'))
    except Exception as e:
        print(f"Error en eliminar_pago_recibido: {e}")
        flash('Error eliminando el pago', 'error')
        return redirect(url_for('mostrar_pagos_recibidos'))

@app.route('/pagos-recibidos/<id>/comprobante')
@login_required
def comprobante_pago(id):
    """Generar comprobante de pago en PDF."""
    try:
        pagos = cargar_datos(ARCHIVO_PAGOS_RECIBIDOS)
        pago = pagos.get(id)
        
        if not pago:
            flash('Pago no encontrado', 'error')
            return redirect(url_for('mostrar_pagos_recibidos'))
        
        return render_template('pdf_comprobante_pago.html', pago=pago)
    except Exception as e:
        print(f"Error en comprobante_pago: {e}")
        flash('Error generando el comprobante', 'error')
        return redirect(url_for('mostrar_pagos_recibidos'))

@app.route('/pagos-recibidos/reporte')
@login_required
def reporte_pagos_recibidos():
    """Reporte de pagos recibidos por período."""
    try:
        pagos = cargar_datos(ARCHIVO_PAGOS_RECIBIDOS)
        
        # Obtener parámetros de filtro
        fecha_desde = request.args.get('fecha_desde', '')
        fecha_hasta = request.args.get('fecha_hasta', '')
        metodo_filtro = request.args.get('metodo', '')
        cliente_filtro = request.args.get('cliente', '')
        
        # Filtrar pagos
        pagos_filtrados = {}
        for id_pago, pago in pagos.items():
            # Filtro por fecha
            if fecha_desde:
                fecha_pago = datetime.strptime(pago.get('fecha', ''), '%Y-%m-%d')
                fecha_desde_obj = datetime.strptime(fecha_desde, '%Y-%m-%d')
                if fecha_pago < fecha_desde_obj:
                    continue
            
            if fecha_hasta:
                fecha_pago = datetime.strptime(pago.get('fecha', ''), '%Y-%m-%d')
                fecha_hasta_obj = datetime.strptime(fecha_hasta, '%Y-%m-%d')
                if fecha_pago > fecha_hasta_obj:
                    continue
            
            # Filtro por método
            if metodo_filtro and pago.get('metodo_pago', '') != metodo_filtro:
                continue
            
            # Filtro por cliente
            if cliente_filtro and cliente_filtro.lower() not in pago.get('cliente', '').lower():
                continue
            
            pagos_filtrados[id_pago] = pago
        
        # Calcular estadísticas
        total_pagos = len(pagos_filtrados)
        total_usd = sum(pago.get('monto_usd', 0) for pago in pagos_filtrados.values())
        total_bs = sum(pago.get('monto_bs', 0) for pago in pagos_filtrados.values())
        
        # Estadísticas por método de pago
        estadisticas_metodo = {}
        for pago in pagos_filtrados.values():
            metodo = pago.get('metodo_pago', 'Sin método')
            if metodo not in estadisticas_metodo:
                estadisticas_metodo[metodo] = {'cantidad': 0, 'total_usd': 0, 'total_bs': 0}
            estadisticas_metodo[metodo]['cantidad'] += 1
            estadisticas_metodo[metodo]['total_usd'] += pago.get('monto_usd', 0)
            estadisticas_metodo[metodo]['total_bs'] += pago.get('monto_bs', 0)
        
        # Obtener clientes para filtro
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        
        # Métodos de pago disponibles
        metodos_pago = ['Efectivo', 'Transferencia', 'Pago Móvil', 'Zelle', 'Divisas']
        
        return render_template('reporte_pagos_recibidos.html',
                             pagos=pagos_filtrados,
                             total_pagos=total_pagos,
                             total_usd=total_usd,
                             total_bs=total_bs,
                             estadisticas_metodo=estadisticas_metodo,
                             clientes=clientes,
                             metodos_pago=metodos_pago,
                             fecha_desde=fecha_desde,
                             fecha_hasta=fecha_hasta,
                             metodo_filtro=metodo_filtro,
                             cliente_filtro=cliente_filtro)
    except Exception as e:
        print(f"Error en reporte_pagos_recibidos: {e}")
        flash('Error generando el reporte', 'error')
        return redirect(url_for('mostrar_pagos_recibidos'))

@app.route('/pagos-recibidos/exportar')
@login_required
def exportar_pagos_recibidos():
    """Exportar pagos recibidos en CSV."""
    try:
        pagos = cargar_datos(ARCHIVO_PAGOS_RECIBIDOS)
        
        # Obtener parámetros de filtro
        fecha_desde = request.args.get('fecha_desde', '')
        fecha_hasta = request.args.get('fecha_hasta', '')
        metodo_filtro = request.args.get('metodo', '')
        
        # Filtrar pagos
        pagos_filtrados = {}
        for id_pago, pago in pagos.items():
            # Filtro por fecha
            if fecha_desde:
                fecha_pago = datetime.strptime(pago.get('fecha', ''), '%Y-%m-%d')
                fecha_desde_obj = datetime.strptime(fecha_desde, '%Y-%m-%d')
                if fecha_pago < fecha_desde_obj:
                    continue
            
            if fecha_hasta:
                fecha_pago = datetime.strptime(pago.get('fecha', ''), '%Y-%m-%d')
                fecha_hasta_obj = datetime.strptime(fecha_hasta, '%Y-%m-%d')
                if fecha_pago > fecha_hasta_obj:
                    continue
            
            # Filtro por método
            if metodo_filtro and pago.get('metodo_pago', '') != metodo_filtro:
                continue
            
            pagos_filtrados[id_pago] = pago
        
        # Crear CSV
        output = StringIO()
        writer = csv.writer(output)
        
        # Encabezados
        writer.writerow(['ID', 'Cliente', 'Monto USD', 'Monto Bs', 'Método de Pago', 
                        'Número de Referencia', 'Banco', 'Fecha', 'Hora', 'Observaciones'])
        
        # Datos
        for pago in pagos_filtrados.values():
            writer.writerow([
                pago.get('id', ''),
                pago.get('cliente', ''),
                pago.get('monto_usd', 0),
                pago.get('monto_bs', 0),
                pago.get('metodo_pago', ''),
                pago.get('numero_referencia', ''),
                pago.get('banco', ''),
                pago.get('fecha', ''),
                pago.get('hora', ''),
                pago.get('observaciones', '')
            ])
        
        # Preparar respuesta
        output.seek(0)
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv; charset=utf-8'
        response.headers['Content-Disposition'] = f'attachment; filename=pagos_recibidos_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        
        return response
        
    except Exception as e:
        print(f"Error en exportar_pagos_recibidos: {e}")
        flash('Error exportando los pagos', 'error')
        return redirect(url_for('mostrar_pagos_recibidos'))

def actualizar_cuenta_por_cobrar(numero_nota, monto_usd, monto_bs):
    """Actualizar cuenta por cobrar cuando se recibe un pago."""
    try:
        cuentas = cargar_datos(ARCHIVO_CUENTAS)
        
        # Buscar la cuenta asociada a la nota
        for id_cuenta, cuenta in cuentas.items():
            if cuenta.get('numero') == numero_nota:
                # Actualizar saldo
                saldo_actual_usd = cuenta.get('saldo_usd', 0)
                saldo_actual_bs = cuenta.get('saldo_bs', 0)
                
                nuevo_saldo_usd = max(0, saldo_actual_usd - monto_usd)
                nuevo_saldo_bs = max(0, saldo_actual_bs - monto_bs)
                
                cuenta['saldo_usd'] = nuevo_saldo_usd
                cuenta['saldo_bs'] = nuevo_saldo_bs
                cuenta['abonado_usd'] = cuenta.get('abonado_usd', 0) + monto_usd
                cuenta['abonado_bs'] = cuenta.get('abonado_bs', 0) + monto_bs
                
                # Actualizar estado
                if nuevo_saldo_usd <= 0:
                    cuenta['estado'] = 'Cobrada'
                elif cuenta.get('abonado_usd', 0) > 0:
                    cuenta['estado'] = 'Abonada'
                
                cuenta['fecha_ultimo_pago'] = datetime.now().strftime('%Y-%m-%d')
                
                # Guardar cambios
                cuentas[id_cuenta] = cuenta
                guardar_datos(ARCHIVO_CUENTAS, cuentas)
                break
                
    except Exception as e:
        print(f"Error actualizando cuenta por cobrar: {e}")

@app.route('/test-nueva-nota', methods=['GET', 'POST'])
@login_required
def test_nueva_nota():
    """Ruta de prueba para nueva nota de entrega."""
    if request.method == 'POST':
        try:
            # Datos básicos para prueba
            cliente_id = request.form['cliente_id']
            fecha = request.form['fecha']
            hora = request.form.get('hora', datetime.now().strftime('%H:%M:%S'))
            modalidad_pago = request.form['modalidad_pago']
            
            # Productos
            productos = request.form.getlist('productos[]')
            cantidades = request.form.getlist('cantidades[]')
            precios = request.form.getlist('precios[]')
            
            # Crear nota de prueba
            notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
            numero_secuencial = len(notas) + 1
            numero_nota = f"NE-{numero_secuencial:04d}"
            
            nota = {
                'numero': numero_nota,
                'cliente_id': cliente_id,
                'fecha': fecha,
                'hora': hora,
                'modalidad_pago': modalidad_pago,
                'productos': productos,
                'cantidades': [int(c) for c in cantidades],
                'precios': [float(p) for p in precios],
                'subtotal_usd': sum(float(precios[i]) * int(cantidades[i]) for i in range(len(precios))),
                'descuento': 0,
                'total_usd': sum(float(precios[i]) * int(cantidades[i]) for i in range(len(precios))),
                'tasa_bcv': 36.00,
                'total_bs': sum(float(precios[i]) * int(cantidades[i]) for i in range(len(precios))) * 36.00,
                'estado': 'PENDIENTE_ENTREGA',
                'observaciones': 'Nota de prueba',
                'creado_por': session.get('usuario', 'SISTEMA'),
                'fecha_creacion': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            notas[numero_nota] = nota
            if guardar_datos(ARCHIVO_NOTAS_ENTREGA, notas):
                flash(f'Nota de prueba {numero_nota} creada exitosamente', 'success')
                return redirect(url_for('mostrar_notas_entrega'))
            else:
                flash('Error guardando la nota de prueba', 'error')
        except Exception as e:
            print(f"Error en test_nueva_nota: {e}")
            flash(f'Error: {str(e)}', 'error')
    
    # GET - Mostrar formulario de prueba
    clientes = cargar_datos(ARCHIVO_CLIENTES)
    inventario = cargar_datos(ARCHIVO_INVENTARIO)
    return render_template('test_nueva_nota.html', clientes=clientes, inventario=inventario)

# Rutas para capturar URLs malformadas específicas
@app.route('/configurar_secuencia', methods=['GET', 'POST'])
@login_required
def configurar_secuencia():
    estado = control_numeracion.obtener_estado_numeracion('FACTURA')
    serie = estado.get('FACTURA', {})
    if request.method == 'POST':
        try:
            nuevo = int(request.form.get('siguiente_numero'))
            # Actualizar archivo de control directamente
            from numeracion_fiscal import ControlNumeracionFiscal
            ctrl = ControlNumeracionFiscal()
            control = ctrl._cargar_control()
            prefijo = (request.form.get('prefijo') or '').strip()
            if not prefijo:
                prefijo = control['series']['FACTURA'].get('prefijo', 'FAC-')
            # normalizar prefijo (opcional: asegurar guion final)
            # if not prefijo.endswith('-'): prefijo += '-'
            control['series']['FACTURA']['siguiente_numero'] = max(nuevo, 1)
            control['series']['FACTURA']['prefijo'] = prefijo
            # reconstruir formato respetando longitud existente
            longitud = int(control['series']['FACTURA'].get('longitud_numero', 8) or 8)
            control['series']['FACTURA']['formato'] = f"{prefijo}" + "{numero:" + f"0{longitud}d" + "}"
            ctrl._guardar_control(control)
            flash('Secuencia actualizada correctamente', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            flash(f'Error actualizando secuencia: {e}', 'danger')
    return render_template('configurar_secuencia.html', serie=serie)





@app.route('/debug/clientes')
@login_required
def debug_clientes():
    """Ruta de debug para verificar el estado de los clientes."""
    try:
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        if clientes is None:
            return "❌ Error: No se pudieron cargar los clientes"
        
        return f"✅ Clientes cargados: {len(clientes)}<br>IDs: {list(clientes.keys())[:10]}"
    except Exception as e:
        return f"❌ Error: {str(e)}"

@app.route('/clientes/<path:id>')
def ver_cliente(id):
    """Muestra los detalles de un cliente."""
    try:
        print(f"Iniciando carga de detalles del cliente: {id}")
        # Cargar datos con manejo de errores
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        if clientes is None:
            clientes = {}
            print("No se pudieron cargar los clientes")
        
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        if notas is None:
            notas = {}
            print("No se pudieron cargar las notas")
        
        cuentas = cargar_datos(ARCHIVO_CUENTAS)
        if cuentas is None:
            cuentas = {}
            print("No se pudieron cargar las cuentas")
        
        # Obtener tasa BCV con manejo de errores
        try:
            tasa_bcv = obtener_tasa_bcv()
            if tasa_bcv is None or tasa_bcv <= 0:
                tasa_bcv = 1.0
                print("Usando tasa BCV por defecto: 1.0")
        except Exception as e:
            print(f"Error al obtener tasa BCV: {e}")
            tasa_bcv = 1.0
        
        print(f"Clientes cargados: {len(clientes)}")
        print(f"Buscando cliente con ID: {id}")
        print(f"IDs disponibles: {list(clientes.keys())[:5]}...")  # Mostrar solo los primeros 5
        
        if id not in clientes:
            print(f"Cliente {id} no encontrado en la base de datos")
            flash('❌ Cliente no encontrado', 'danger')
            return redirect(url_for('mostrar_clientes'))
        
        cliente = clientes[id]
        print(f"Cliente encontrado: {cliente.get('nombre', 'Sin nombre')}")
        
        # Calcular totales financieros de forma más robusta
        notas_cliente = [f for f in notas.values() if f.get('cliente_id') == id]
        
        total_notas_entrega = 0.0
        for nota in notas_cliente:
            try:
                total_notas_entrega += safe_float(nota.get('total_usd', 0))
            except (ValueError, TypeError):
                continue
        
        # Total abonado
        total_abonado = 0.0
        for nota in notas_cliente:
            try:
                total_abonado += safe_float(nota.get('total_abonado', 0))
            except (ValueError, TypeError):
                continue
        
        # Total por cobrar desde cuentas
        cuenta = next((c for c in cuentas.values() if c.get('cliente_id') == id), None)
        total_por_cobrar = 0.0
        if cuenta:
            try:
                total_por_cobrar = safe_float(cuenta.get('saldo_pendiente', 0))
            except (ValueError, TypeError):
                total_por_cobrar = 0.0
        
        total_por_cobrar_notas = total_notas_entrega - total_abonado
        if total_por_cobrar == 0 and total_por_cobrar_notas > 0:
            total_por_cobrar = total_por_cobrar_notas
        
        # Convertir a bolívares con manejo de errores
        if tasa_bcv and tasa_bcv > 0:
            total_por_cobrar_bs = total_por_cobrar * tasa_bcv
        else:
            total_por_cobrar_bs = total_por_cobrar
        
        # Estadísticas adicionales
        cantidad_notas = len(notas_cliente)
        ultima_nota = None
        if notas_cliente:
            facturas_ordenadas = sorted(notas_cliente, key=lambda x: x.get('fecha', ''), reverse=True)
            ultima_nota = facturas_ordenadas[0].get('fecha') if facturas_ordenadas else None
        
        # Obtener órdenes de servicio del cliente
        ordenes_servicio = cargar_datos('ordenes_servicio.json')
        if ordenes_servicio is None:
            ordenes_servicio = {}
        
        ordenes_cliente = []
        for orden_id, orden in ordenes_servicio.items():
            if isinstance(orden, dict):
                # Buscar por cliente_id directo o por objeto cliente
                orden_cliente_id = None
                if 'cliente_id' in orden:
                    orden_cliente_id = orden['cliente_id']
                elif 'cliente' in orden:
                    if isinstance(orden['cliente'], dict) and 'id' in orden['cliente']:
                        orden_cliente_id = orden['cliente']['id']
                    elif isinstance(orden['cliente'], str):
                        orden_cliente_id = orden['cliente']
                
                if orden_cliente_id == id:
                    # Agregar ID de la orden al objeto
                    orden_con_id = orden.copy()
                    orden_con_id['id'] = orden_id
                    ordenes_cliente.append(orden_con_id)
        
        # Ordenar órdenes por fecha (más recientes primero)
        ordenes_cliente.sort(key=lambda x: x.get('fecha_recepcion', x.get('fecha_creacion', '')), reverse=True)
        
        # Actualizar totales en el objeto cliente para el template
        cliente_para_template = cliente.copy()
        cliente_para_template['total_facturado'] = total_notas_entrega
        cliente_para_template['total_abonado'] = total_abonado
        cliente_para_template['total_por_cobrar'] = total_por_cobrar
        cliente_para_template['total_ordenes'] = len(ordenes_cliente)
        cliente_para_template['ordenes'] = ordenes_cliente
        cliente_para_template['notas'] = notas_cliente
        
        # Obtener configuración del mapa con manejo de errores
        try:
            maps_config = get_maps_config()
        except Exception as e:
            print(f"Error al obtener configuración de mapas: {e}")
            maps_config = {
                'api_key': '',
                'libraries': [],
                'default_center': {'lat': 10.5, 'lng': -66.9},
                'default_zoom': 12,
                'map_types': {'roadmap': 'Mapa'},
                'clustering': {'grid_size': 50, 'max_zoom': 15},
                'heatmap': {'radius': 20, 'opacity': 0.6},
                'geocoding': {'timeout': 5, 'max_retries': 3}
            }
        
        return render_template('cliente_detalle.html', 
                             cliente=cliente_para_template, 
                             total_facturado=total_notas_entrega, 
                             total_abonado=total_abonado, 
                             total_por_cobrar=total_por_cobrar, 
                             total_por_cobrar_bs=total_por_cobrar_bs, 
                             tasa_bcv=tasa_bcv,
                             cantidad_notas=cantidad_notas,
                             ultima_factura=ultima_nota,
                             maps_config=maps_config)
    
    except Exception as e:
        import traceback
        print(f"Error al cargar detalles del cliente {id}: {e}")
        print(f"Traceback completo: {traceback.format_exc()}")
        flash(f'❌ Error al cargar los detalles del cliente: {str(e)}', 'danger')
        return redirect(url_for('mostrar_clientes'))

@app.route('/clientes/<path:id>/editar', methods=['GET', 'POST'])
@login_required
def editar_cliente(id):
    """Formulario para editar un cliente - VALIDACIONES SENIAT APLICADAS."""
    clientes = cargar_datos(ARCHIVO_CLIENTES)
    if id not in clientes:
        flash('❌ Cliente no encontrado', 'danger')
        return redirect(url_for('mostrar_clientes'))
        
    if request.method == 'POST':
        try:
            print(f"Editando cliente SENIAT: {id}")
            
            # === OBTENER DATOS CON VALIDACIONES SENIAT ===
            nombre = request.form.get('nombre', '').strip().upper()
            email = request.form.get('email', '').strip().lower()
            telefono_raw = request.form.get('telefono', '').replace(' ', '').replace('-', '')
            codigo_pais = request.form.get('codigo_pais', '+58')
            telefono = f"{codigo_pais}{telefono_raw}"
            direccion = request.form.get('direccion', '').strip().title()
            
            # === VALIDACIONES OBLIGATORIAS SENIAT ===
            errores = []
            
            if not nombre:
                errores.append("Nombre completo es obligatorio")
            if not direccion:
                errores.append("Dirección completa es obligatoria")
            if len(direccion) < 10:
                errores.append("Dirección debe tener al menos 10 caracteres")
            
            # Validar teléfono usando función de validación
            telefono_valido, error_telefono = validar_telefono(telefono)
            if not telefono_valido:
                errores.append(error_telefono)
            
            # Validar email usando función de validación
            email_valido, error_email = validar_email(email)
            if not email_valido:
                errores.append(error_email)
                
            # Si hay errores, mostrarlos
            if errores:
                for error in errores:
                    flash(f"❌ SENIAT: {error}", 'danger')
                return render_template('cliente_form.html', cliente=clientes[id])
            
            # === ACTUALIZAR CLIENTE MANTENIENDO DATOS SENIAT ===
            cliente_actual = clientes[id]
            
            # Preservar datos fiscales inmutables
            cliente_actualizado = {
                'id': id,  # RIF inmutable
                'rif': cliente_actual.get('rif', id),  # RIF no se puede cambiar
                'tipo_identificacion': cliente_actual.get('tipo_identificacion', ''),
                'numero_identificacion': cliente_actual.get('numero_identificacion', ''),
                'digito_verificador': cliente_actual.get('digito_verificador', ''),
                
                # Datos actualizables
                'nombre': nombre,
                'email': email,
                'telefono': telefono,
                'direccion': direccion,
                
                # Metadatos
                'fecha_creacion': cliente_actual.get('fecha_creacion', datetime.now().isoformat()),
                'usuario_creacion': cliente_actual.get('usuario_creacion', 'SISTEMA'),
                'fecha_ultima_actualizacion': datetime.now().isoformat(),
                'usuario_ultima_actualizacion': session.get('usuario', 'SISTEMA'),
                'activo': cliente_actual.get('activo', True),
                'validado_seniat': True  # Mantener validación SENIAT
            }
            
            print(f"Cliente SENIAT actualizado: {cliente_actualizado}")
            
            # Guardar cambios
            clientes[id] = cliente_actualizado
            if guardar_datos(ARCHIVO_CLIENTES, clientes):
                
                # === REGISTRO FISCAL EN BITÁCORA ===
                registrar_bitacora(
                    session['usuario'], 
                    'Editar cliente SENIAT', 
                    f"RIF: {id}, Nombre: {nombre}",
                    'CLIENTE',
                    id
                )
                
                flash(f'✅ Cliente RIF {id} actualizado exitosamente (SENIAT válido)', 'success')
                return redirect(url_for('mostrar_clientes'))
            else:
                flash('❌ Error al actualizar el cliente', 'danger')
                
        except Exception as e:
            print(f"Error editando cliente SENIAT: {str(e)}")
            flash('❌ Error al procesar la actualización del cliente', 'danger')
            
    return render_template('cliente_form.html', cliente=clientes[id])

@app.route('/clientes/<path:id>/eliminar', methods=['POST'])
@login_required
def eliminar_cliente(id):
    """Elimina un cliente con validación de integridad referencial."""
    try:
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        if id not in clientes:
            flash('Cliente no encontrado', 'danger')
            return redirect(url_for('mostrar_clientes'))
        
        # Verificar referencias antes de eliminar
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        if notas is None:
            notas = {}
        
        ordenes = cargar_datos('ordenes_servicio.json')
        if ordenes is None:
            ordenes = {}
        
        cuentas = cargar_datos(ARCHIVO_CUENTAS)
        if cuentas is None:
            cuentas = {}
        
        # Buscar referencias del cliente
        notas_cliente = []
        for nota_id, nota in notas.items():
            if isinstance(nota, dict) and nota.get('cliente_id') == id:
                notas_cliente.append(nota_id)
        
        ordenes_cliente = []
        for orden_id, orden in ordenes.items():
            if isinstance(orden, dict):
                orden_cliente_id = None
                if 'cliente_id' in orden:
                    orden_cliente_id = orden['cliente_id']
                elif 'cliente' in orden:
                    if isinstance(orden['cliente'], dict) and 'id' in orden['cliente']:
                        orden_cliente_id = orden['cliente']['id']
                    elif isinstance(orden['cliente'], str):
                        orden_cliente_id = orden['cliente']
                
                if orden_cliente_id == id:
                    ordenes_cliente.append(orden_id)
        
        cuentas_cliente = []
        for cuenta_id, cuenta in cuentas.items():
            if isinstance(cuenta, dict) and cuenta.get('cliente_id') == id:
                cuentas_cliente.append(cuenta_id)
        
        # Si hay referencias, no permitir eliminación
        if notas_cliente or ordenes_cliente or cuentas_cliente:
            mensaje = f'No se puede eliminar el cliente porque tiene: '
            referencias = []
            if notas_cliente:
                referencias.append(f'{len(notas_cliente)} nota(s) de entrega')
            if ordenes_cliente:
                referencias.append(f'{len(ordenes_cliente)} orden(es) de servicio')
            if cuentas_cliente:
                referencias.append(f'{len(cuentas_cliente)} cuenta(s) por cobrar')
            
            mensaje += ', '.join(referencias)
            mensaje += '. En su lugar, marque el cliente como inactivo.'
            
            flash(mensaje, 'warning')
            return redirect(url_for('mostrar_clientes'))
        
        # Si no hay referencias, proceder con la eliminación
        cliente_nombre = clientes[id].get('nombre', 'Cliente')
        del clientes[id]
        
        if guardar_datos(ARCHIVO_CLIENTES, clientes):
            registrar_bitacora(
                session.get('usuario', 'Sistema'),
                'Eliminar cliente',
                f'Cliente eliminado: {cliente_nombre} (ID: {id})',
                'CLIENTE',
                id
            )
            flash(f'Cliente {cliente_nombre} eliminado exitosamente', 'success')
        else:
            flash('Error al eliminar el cliente', 'danger')
            
    except Exception as e:
        print(f"Error al eliminar cliente: {str(e)}")
        flash(f'Error al eliminar el cliente: {str(e)}', 'danger')
    
    return redirect(url_for('mostrar_clientes'))

@app.route('/inventario/ajustar-stock', methods=['GET', 'POST'])
def ajustar_stock():
    if request.method == 'POST':
        productos = request.form.getlist('productos[]')
        tipo_ajuste = request.form.get('tipo_ajuste')
        cantidad_str = request.form.get('cantidad', '0')
        motivo = request.form.get('motivo', '')
        usuario = session.get('usuario', '')
        
        if not productos:
            flash('Debe seleccionar al menos un producto', 'danger')
            return redirect(url_for('ajustar_stock'))
        
        # Validar cantidad
        try:
            cantidad = int(cantidad_str)
            if cantidad <= 0:
                flash('La cantidad debe ser mayor a 0', 'danger')
                return redirect(url_for('ajustar_stock'))
        except (ValueError, TypeError):
            flash('La cantidad debe ser un número válido', 'danger')
            return redirect(url_for('ajustar_stock'))
        inventario = cargar_datos(ARCHIVO_INVENTARIO)
        fecha_actual = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        movimientos = []
        for id_producto in productos:
            if id_producto in inventario:
                producto = inventario[id_producto]
                if tipo_ajuste == 'entrada':
                    producto['cantidad'] += cantidad
                    producto['ultima_entrada'] = fecha_actual
                else:  # salida
                    if producto['cantidad'] >= cantidad:
                        producto['cantidad'] -= cantidad
                        producto['ultima_salida'] = fecha_actual
                    else:
                        flash(f'No hay suficiente stock para {producto["nombre"]}', 'warning')
                        continue
                if 'historial_ajustes' not in producto:
                    producto['historial_ajustes'] = []
                producto['historial_ajustes'].append({
                    'fecha': fecha_actual,
                    'tipo': tipo_ajuste,
                    'cantidad': cantidad,
                    'motivo': motivo,
                    'usuario': usuario
                })
                # Registrar movimiento
                movimientos.append({
                    'tipo': tipo_ajuste,
                    'producto_id': id_producto,
                    'producto_nombre': producto.get('nombre', ''),
                    'cantidad': cantidad,
                    'motivo': motivo or f'Ajuste de stock - {tipo_ajuste}',
                    'fecha': fecha_actual,
                    'usuario': usuario
                })
        guardar_datos(ARCHIVO_INVENTARIO, inventario)
        # Registrar todos los movimientos
        if movimientos:
            registrar_movimientos_inventario(movimientos)
        flash(f'Ajuste de stock realizado para {len(productos)} producto(s)', 'success')
        return redirect(url_for('mostrar_inventario'))
    inventario = cargar_datos(ARCHIVO_INVENTARIO)
    # Filtros y orden
    q = request.args.get('q', '').strip().lower()
    filtro_categoria = request.args.get('categoria', '').strip().lower()
    filtro_orden = request.args.get('orden', 'nombre')
    # Filtrar por búsqueda
    if q:
        inventario = {k: v for k, v in inventario.items() if q in v.get('nombre', '').lower()}
    # Filtrar por categoría
    if filtro_categoria:
        inventario = {k: v for k, v in inventario.items() if filtro_categoria in v.get('categoria', '').lower()}
    # Ordenar
    if filtro_orden == 'nombre':
        inventario = dict(sorted(inventario.items(), key=lambda item: item[1].get('nombre', '').lower()))
    elif filtro_orden == 'stock':
        inventario = dict(sorted(inventario.items(), key=lambda item: item[1].get('cantidad', 0)))
    
    return render_template('ajustar_stock.html', inventario=inventario, q=q, filtro_categoria=filtro_categoria, filtro_orden=filtro_orden)

@app.route('/inventario/reporte')
def reporte_inventario():
    try:
        inventario = cargar_datos('inventario.json')
        empresa = cargar_empresa()
        # Obtener la tasa BCV actual
        tasa_bcv = obtener_tasa_bcv()
        advertencia_tasa = None
        try:
            tasa_bcv = safe_float(tasa_bcv)
        except Exception:
            tasa_bcv = 0
        if not tasa_bcv or tasa_bcv < 1:
            advertencia_tasa = '¡Advertencia! No se ha podido obtener la tasa BCV actual.'
        # Obtener la fecha actual
        fecha_actual = datetime.now()
        # Calcular estadísticas
        total_productos = len(inventario)
        total_stock = sum(producto['cantidad'] for producto in inventario.values())
        valor_total = sum(producto['cantidad'] * producto['precio'] for producto in inventario.values())
        # Productos por categoría
        productos_por_categoria = {}
        for producto in inventario.values():
            categoria = producto['categoria']
            if categoria not in productos_por_categoria:
                productos_por_categoria[categoria] = {
                    'productos': [],
                    'cantidad': 0,
                    'valor': 0
                }
            productos_por_categoria[categoria]['productos'].append(producto)
            productos_por_categoria[categoria]['cantidad'] += producto['cantidad']
            productos_por_categoria[categoria]['valor'] += producto['cantidad'] * producto['precio']
        # Productos con bajo stock (menos de 10 unidades)
        productos_bajo_stock = {
            id: producto for id, producto in inventario.items() 
            if producto['cantidad'] < 10
        }
        # --- Historial de ajustes masivos ---
        ajustes_masivos = []
        for producto in inventario.values():
            nombre_producto = producto.get('nombre', '')
            if 'historial_ajustes' in producto:
                for ajuste in producto['historial_ajustes']:
                    ajustes_masivos.append({
                        'fecha': ajuste.get('fecha', ''),
                        'motivo': ajuste.get('motivo', ''),
                        'producto': nombre_producto,
                        'ingreso': ajuste['cantidad'] if ajuste.get('tipo') == 'entrada' else 0,
                        'salida': ajuste['cantidad'] if ajuste.get('tipo') == 'salida' else 0,
                        'usuario': '',
                        'observaciones': ajuste.get('motivo', '')
                    })
        # Ordenar por fecha descendente
        from datetime import datetime as dt
        def parse_fecha(f):
            try:
                return dt.strptime(f['fecha'], '%Y-%m-%d %H:%M:%S')
            except:
                return dt.min
        ajustes_masivos = sorted(ajustes_masivos, key=parse_fecha, reverse=True)
        return render_template('reporte_inventario.html',
                             inventario=inventario,
                             total_productos=total_productos,
                             total_stock=total_stock,
                             valor_total=valor_total,
                             productos_por_categoria=productos_por_categoria,
                             productos_bajo_stock=productos_bajo_stock,
                             empresa=empresa,
                             tasa_bcv=tasa_bcv,
                             fecha_actual=fecha_actual,
                             advertencia_tasa=advertencia_tasa,
                             ajustes_masivos=ajustes_masivos)
    except Exception as e:
        flash(f'Error al generar el reporte: {str(e)}', 'danger')
        return redirect(url_for('mostrar_inventario'))


@app.route('/inventario/reporte-neomorfico')
@login_required
def reporte_inventario_neomorfico():
    """Genera reporte de inventario con estilo neomórfico mejorado"""
    try:
        # Cargar inventario
        inventario = cargar_datos(ARCHIVO_INVENTARIO)
        
        # Obtener tasa BCV actual
        tasa_bcv = cargar_ultima_tasa_bcv()
        if not tasa_bcv or tasa_bcv <= 0:
            tasa_bcv = 205.68  # Tasa de fallback
        
        # Configuración de tipos de productos
        tipos_config = {
            'piezas': {'nombre': 'Piezas', 'color': '#667eea', 'icono': 'fas fa-cogs'},
            'accesorios': {'nombre': 'Accesorios', 'color': '#f093fb', 'icono': 'fas fa-mobile-alt'},
            'herramientas': {'nombre': 'Herramientas', 'color': '#4facfe', 'icono': 'fas fa-tools'},
            'consumibles': {'nombre': 'Consumibles', 'color': '#43e97b', 'icono': 'fas fa-box-open'},
            'otros': {'nombre': 'Otros', 'color': '#ffd93d', 'icono': 'fas fa-question-circle'}
        }
        
        # Inicializar estructura del reporte
        reporte_por_tipo = {}
        for tipo, info in tipos_config.items():
            reporte_por_tipo[tipo] = {
                'nombre': info['nombre'],
                'color': info['color'],
                'icono': info['icono'],
                'total_productos': 0,
                'total_stock': 0,
                'total_valor_usd': 0,
                'total_valor_bs': 0,
                'categorias': {}
            }
        
        # Procesar productos de manera optimizada
        for id_producto, producto in inventario.items():
            # Validar y limpiar datos
            tipo = producto.get('tipo', 'otros').lower().strip()
            categoria = producto.get('categoria', 'Sin categoría').strip()
            cantidad = max(0, int(producto.get('cantidad', 0)))
            precio_usd = max(0, safe_float(producto.get('precio', 0)))
            
            # Calcular valores
            precio_bs = precio_usd * tasa_bcv
            valor_total_usd = cantidad * precio_usd
            valor_total_bs = cantidad * precio_bs
            
            # Asegurar que el tipo existe
            if tipo not in reporte_por_tipo:
                tipo = 'otros'
            
            # Actualizar totales del tipo
            reporte_por_tipo[tipo]['total_productos'] += 1
            reporte_por_tipo[tipo]['total_stock'] += cantidad
            reporte_por_tipo[tipo]['total_valor_usd'] += valor_total_usd
            reporte_por_tipo[tipo]['total_valor_bs'] += valor_total_bs
            
            # Inicializar categoría si no existe
            if categoria not in reporte_por_tipo[tipo]['categorias']:
                reporte_por_tipo[tipo]['categorias'][categoria] = {
                    'total_productos': 0,
                    'total_stock': 0,
                    'total_valor_usd': 0,
                    'total_valor_bs': 0,
                    'productos': []
                }
            
            # Actualizar totales de la categoría
            reporte_por_tipo[tipo]['categorias'][categoria]['total_productos'] += 1
            reporte_por_tipo[tipo]['categorias'][categoria]['total_stock'] += cantidad
            reporte_por_tipo[tipo]['categorias'][categoria]['total_valor_usd'] += valor_total_usd
            reporte_por_tipo[tipo]['categorias'][categoria]['total_valor_bs'] += valor_total_bs
            
            # Agregar producto a la categoría
            reporte_por_tipo[tipo]['categorias'][categoria]['productos'].append({
                'id': id_producto,
                'nombre': producto.get('nombre', 'Sin nombre').strip(),
                'cantidad': cantidad,
                'precio_usd': precio_usd,
                'precio_bs': precio_bs,
                'valor_total_usd': valor_total_usd,
                'valor_total_bs': valor_total_bs
            })
        
        # Ordenar productos dentro de cada categoría por nombre
        for tipo_data in reporte_por_tipo.values():
            for categoria_data in tipo_data['categorias'].values():
                categoria_data['productos'].sort(key=lambda x: x['nombre'].lower())
        
        # Calcular totales generales
        total_general = {
            'total_productos': sum(tipo['total_productos'] for tipo in reporte_por_tipo.values()),
            'total_stock': sum(tipo['total_stock'] for tipo in reporte_por_tipo.values()),
            'total_valor_usd': sum(tipo['total_valor_usd'] for tipo in reporte_por_tipo.values()),
            'total_valor_bs': sum(tipo['total_valor_bs'] for tipo in reporte_por_tipo.values())
        }
        
        # Filtrar tipos sin productos para optimizar el template
        reporte_por_tipo_filtrado = {
            tipo: datos for tipo, datos in reporte_por_tipo.items() 
            if datos['total_productos'] > 0
        }
        
        return render_template('reporte_inventario_neomorfico_final.html',
                             inventario=inventario,
                             reporte_por_tipo=reporte_por_tipo_filtrado,
                             total_productos=total_general['total_productos'],
                             total_stock=total_general['total_stock'],
                             total_valor_usd=total_general['total_valor_usd'],
                             total_valor_bs=total_general['total_valor_bs'],
                             tasa_bcv=tasa_bcv,
                             fecha_actual=datetime.now().strftime('%d/%m/%Y %H:%M'))
    
    except Exception as e:
        print(f"Error generando reporte de inventario: {str(e)}")
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Error - Reporte de Inventario</title>
            <style>
                body {{ 
                    font-family: Arial, sans-serif; 
                    background: #f0f0f3; 
                    padding: 2rem; 
                    text-align: center; 
                }}
                .error-card {{
                    background: #f0f0f3;
                    border-radius: 20px;
                    padding: 2rem;
                    box-shadow: 20px 20px 60px #d1d9e6, -20px -20px 60px #ffffff;
                    max-width: 500px;
                    margin: 0 auto;
                }}
                .error-title {{ color: #e53e3e; font-size: 1.5rem; margin-bottom: 1rem; }}
                .error-message {{ color: #2d3748; margin-bottom: 2rem; }}
                .btn {{ 
                    background: #667eea; 
                    color: white; 
                    padding: 0.8rem 1.5rem; 
                    border: none; 
                    border-radius: 10px; 
                    text-decoration: none; 
                    display: inline-block; 
                }}
            </style>
        </head>
        <body>
            <div class="error-card">
                <h1 class="error-title">Error al Generar Reporte</h1>
                <p class="error-message">{str(e)}</p>
                <a href="/inventario" class="btn">Volver al Inventario</a>
            </div>
        </body>
        </html>
        """

# --- API Endpoints ---
@app.route('/api/productos')
def api_productos():
    """API endpoint para obtener productos."""
    try:
        inventario = cargar_datos(ARCHIVO_INVENTARIO)
        
        # Convertir inventario a formato compatible con el frontend
        productos = []
        for producto_id, producto in inventario.items():
            productos.append({
                'id': producto_id,
                'nombre': producto.get('nombre', ''),
                'categoria': producto.get('categoria', 'Sin categoría'),
                'precio': safe_float(producto.get('precio', 0)),
                'cantidad': int(producto.get('cantidad', 0)),
                'descripcion': producto.get('descripcion', '')
            })
        
        return jsonify({
            'success': True,
            'productos': productos,
            'total': len(productos)
        })
    except Exception as e:
        print(f"DEBUG: Error en API productos: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'productos': [],
            'total': 0
        })

@app.route('/api/clientes')
def api_clientes():
    """API endpoint para obtener clientes."""
    clientes = cargar_datos(ARCHIVO_CLIENTES)
    return jsonify(clientes)

@app.route('/api/tasa-bcv')
def api_tasa_bcv():
    try:
        # Intentar obtener la tasa del día
        tasa = obtener_tasa_bcv_dia()
        if tasa:
            return jsonify({'tasa': tasa, 'advertencia': False})
        
        # Si no hay tasa del día, intentar obtener la última tasa guardada
        ultima_tasa = cargar_ultima_tasa_bcv()
        if ultima_tasa:
            return jsonify({'tasa': ultima_tasa, 'advertencia': True})
        
        # Si no hay tasa guardada, usar tasa correcta del dólar
        tasa_fallback = 205.68
        print("WARNING Usando tasa BCV USD de fallback en API: 205.68")
        return jsonify({'tasa': tasa_fallback, 'advertencia': True})
        
    except Exception as e:
        print(f"Error en /api/tasa-bcv: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/ordenes-servicio')
def api_ordenes_servicio():
    """API para obtener todas las órdenes de servicio para autocompletado"""
    try:
        print("🔍 Cargando órdenes de servicio para API...")
        ordenes = cargar_datos('ordenes_servicio.json')
        if not isinstance(ordenes, dict):
            ordenes = {}
        
        print(f"📊 Total de órdenes cargadas: {len(ordenes)}")
        
        # Filtrar solo órdenes que tengan información completa
        ordenes_filtradas = []
        for orden_id, orden in ordenes.items():
            print(f"🔍 Procesando orden {orden_id}: {type(orden)}")
            if isinstance(orden, dict):
                print(f"  - Cliente: {'cliente' in orden}")
                print(f"  - Equipo: {'equipo' in orden}")
                print(f"  - Número: {'numero_orden' in orden}")
                print(f"  - Orden completa: {orden}")
                
                if ('cliente' in orden and 
                    'equipo' in orden and 
                    'numero_orden' in orden):
                    orden_filtrada = {
                        'id': orden_id,
                        'numero_orden': orden.get('numero_orden', orden_id),
                        'cliente': orden.get('cliente', {}),
                        'equipo': orden.get('equipo', {}),
                        'estado': orden.get('estado', 'desconocido')
                    }
                    ordenes_filtradas.append(orden_filtrada)
                    print(f"  ✅ Orden agregada: {orden_filtrada['numero_orden']}")
                else:
                    print(f"  ❌ Orden rechazada por falta de datos")
        
        print(f"📋 Órdenes filtradas: {len(ordenes_filtradas)}")
        return jsonify({'ordenes': ordenes_filtradas})
        
    except Exception as e:
        print(f"❌ Error en /api/ordenes-servicio: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/orden-servicio/<orden_id>')
def api_orden_servicio(orden_id):
    """API para obtener una orden de servicio específica"""
    try:
        ordenes = cargar_datos('ordenes_servicio.json')
        if not isinstance(ordenes, dict):
            ordenes = {}
        
        if orden_id not in ordenes:
            return jsonify({'success': False, 'error': 'Orden no encontrada'}), 404
        
        orden = ordenes[orden_id]
        return jsonify({'success': True, 'orden': orden})
        
    except Exception as e:
        print(f"Error en /api/orden-servicio/{orden_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/tecnicos-registrados')
@login_required
def api_tecnicos_registrados():
    """API para obtener todos los técnicos registrados en las órdenes"""
    try:
        ordenes = cargar_datos('ordenes_servicio.json')
        
        # Extraer técnicos únicos de las órdenes
        tecnicos_dict = {}
        
        for orden_id, orden in ordenes.items():
            if isinstance(orden, dict):
                tecnico_nombre = orden.get('tecnico_asignado', '')
                
                if tecnico_nombre and tecnico_nombre.strip():
                    tecnico_nombre = tecnico_nombre.strip()
                    
                    # Si no existe, crear entrada
                    if tecnico_nombre not in tecnicos_dict:
                        tecnico_info = orden.get('tecnico_info', {})
                        tecnicos_dict[tecnico_nombre] = {
                            'nombre': tecnico_nombre,
                            'especialidad': tecnico_info.get('especialidad', ''),
                            'telefono': tecnico_info.get('telefono', ''),
                            'email': tecnico_info.get('email', ''),
                            'ordenes_asignadas': 0,
                            'ultima_asignacion': orden.get('fecha_actualizacion', '')
                        }
                    
                    # Incrementar contador de órdenes
                    tecnicos_dict[tecnico_nombre]['ordenes_asignadas'] += 1
                    
                    # Actualizar última asignación si es más reciente
                    fecha_orden = orden.get('fecha_actualizacion', '')
                    if fecha_orden > tecnicos_dict[tecnico_nombre]['ultima_asignacion']:
                        tecnicos_dict[tecnico_nombre]['ultima_asignacion'] = fecha_orden
        
        # Convertir a lista y ordenar por nombre
        tecnicos = list(tecnicos_dict.values())
        tecnicos.sort(key=lambda x: x['nombre'].upper())
        
        return jsonify({
            'success': True,
            'tecnicos': tecnicos,
            'total': len(tecnicos)
        })
        
    except Exception as e:
        print(f"Error en /api/tecnicos-registrados: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e), 'tecnicos': []}), 500

@app.route('/api/buscar-clientes')
def api_buscar_clientes():
    """API para búsqueda predictiva de clientes."""
    try:
        q = request.args.get('q', '').strip()
        if not q or len(q) < 2:
            return jsonify({'clientes': []})
        
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        resultados = []
        
        q_lower = q.lower()
        for id_cliente, cliente in clientes.items():
            nombre_cliente = cliente.get('nombre', '').lower()
            # Buscar cédula/RIF en ambos formatos
            rif_cliente = obtener_cedula_rif_cliente(cliente) or ''
            rif_cliente = rif_cliente.lower()
            
            # Búsqueda predictiva
            nombre_match = q_lower in nombre_cliente
            rif_match = q_lower in rif_cliente
            
            # Búsqueda por palabras
            palabras_busqueda = q_lower.split()
            nombre_palabras_match = all(palabra in nombre_cliente for palabra in palabras_busqueda)
            rif_palabras_match = all(palabra in rif_cliente for palabra in palabras_busqueda)
            
            if nombre_match or rif_match or nombre_palabras_match or rif_palabras_match:
                # Obtener cédula/RIF en formato apropiado para mostrar (sin normalizar)
                cedula_display = obtener_cedula_rif_cliente_sin_normalizar(cliente) or cliente.get('cedula_rif', cliente.get('rif', ''))
                
                resultados.append({
                    'id': id_cliente,
                    'nombre': cliente.get('nombre', ''),
                    'rif': cedula_display,
                    'cedula_rif': cedula_display,
                    'email': cliente.get('email', ''),
                    'telefono': cliente.get('telefono', '')
                })
        
        # Limitar a 10 resultados para mejor rendimiento
        return jsonify({'clientes': resultados[:10]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/listar-clientes')
def api_listar_clientes():
    """API para listar todos los clientes."""
    try:
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        lista_clientes = []
        
        for id_cliente, cliente in clientes.items():
            lista_clientes.append({
                'id': id_cliente,
                'nombre': cliente.get('nombre', ''),
                'cedula_rif': cliente.get('cedula_rif', ''),
                'telefono': cliente.get('telefono', ''),
                'telefono2': cliente.get('telefono2', ''),
                'email': cliente.get('email', ''),
                'direccion': cliente.get('direccion', '')
            })
        
        return jsonify({'clientes': lista_clientes})
    except Exception as e:
        return jsonify({'error': str(e), 'clientes': []}), 500

@app.route('/api/buscar-cliente-exacto', methods=['POST'])
def api_buscar_cliente_exacto():
    """API para buscar cliente exacto por nombre o cédula."""
    try:
        data = request.get_json()
        nombre = data.get('nombre', '').strip().lower() if data.get('nombre') else ''
        cedula = data.get('cedula', '').strip().lower() if data.get('cedula') else ''
        
        if not nombre and not cedula:
            return jsonify({'cliente': None, 'existe': False})
        
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        
        # Buscar cliente exacto por nombre o cédula
        for id_cliente, cliente in clientes.items():
            nombre_cliente = cliente.get('nombre', '').strip().lower()
            cedula_cliente = cliente.get('cedula_rif', '').strip().lower()
            
            # Comparar nombres (ignorando case y espacios extra)
            if nombre and nombre_cliente == nombre:
                return jsonify({
                    'cliente': {
                        'id': id_cliente,
                        'nombre': cliente.get('nombre', ''),
                        'cedula_rif': cliente.get('cedula_rif', ''),
                        'telefono': cliente.get('telefono', ''),
                        'telefono2': cliente.get('telefono2', ''),
                        'email': cliente.get('email', ''),
                        'direccion': cliente.get('direccion', '')
                    },
                    'existe': True
                })
            
            # Comparar cédulas
            if cedula and cedula_cliente == cedula:
                return jsonify({
                    'cliente': {
                        'id': id_cliente,
                        'nombre': cliente.get('nombre', ''),
                        'cedula_rif': cliente.get('cedula_rif', ''),
                        'telefono': cliente.get('telefono', ''),
                        'telefono2': cliente.get('telefono2', ''),
                        'email': cliente.get('email', ''),
                        'direccion': cliente.get('direccion', '')
                    },
                    'existe': True
                })
        
        return jsonify({'cliente': None, 'existe': False})
        
    except Exception as e:
        return jsonify({'error': str(e), 'cliente': None, 'existe': False}), 500

@app.route('/api/geocodificar')
def api_geocodificar():
    """API para geocodificar direcciones usando OpenStreetMap Nominatim."""
    try:
        direccion = request.args.get('direccion', '').strip()
        if not direccion:
            return jsonify({'error': 'Dirección requerida'}), 400
        
        # Usar OpenStreetMap Nominatim (gratuito)
        url = f"https://nominatim.openstreetmap.org/search"
        params = {
            'q': direccion,
            'format': 'json',
            'limit': 1,
            'addressdetails': 1
        }
        
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data:
                resultado = data[0]
                return jsonify({
                    'lat': safe_float(resultado['lat']),
                    'lon': safe_float(resultado['lon']),
                    'display_name': resultado['display_name'],
                    'address': resultado.get('address', {})
                })
            else:
                return jsonify({'error': 'No se encontró la dirección'}), 404
        else:
            return jsonify({'error': 'Error en el servicio de geocodificación'}), 500
    
    except requests.exceptions.Timeout:
        return jsonify({'error': 'Timeout en el servicio de geocodificación'}), 408
    except requests.exceptions.RequestException as e:
        return jsonify({'error': f'Error de conexión: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': f'Error interno: {str(e)}'}), 500

def obtener_tasa_bcv_dia():
    """Obtiene la tasa oficial USD/BS del BCV desde la web. Devuelve float o None si falla."""
    try:
        # SIEMPRE intentar obtener desde la web primero (no usar tasa local)
        url = 'https://www.bcv.org.ve/glosario/cambio-oficial'
        print(f"🔍 Obteniendo tasa BCV ACTUAL desde: {url}")
        
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        resp = requests.get(url, timeout=20, verify=False)
        
        if resp.status_code != 200:
            print(f"❌ Error HTTP al obtener tasa BCV: {resp.status_code}")
            return None
        
        print(f"✅ Página BCV obtenida exitosamente, analizando contenido...")
        soup = BeautifulSoup(resp.text, 'html.parser')
        tasa = None
        
        # Método 1: Buscar por id='dolar' (método principal)
        dolar_div = soup.find('div', id='dolar')
        if dolar_div:
            strong = dolar_div.find('strong')
            if strong:
                txt = strong.text.strip().replace('.', '').replace(',', '.')
                try:
                    posible = safe_float(txt)
                    if 10 < posible < 500:  # Rango más específico para tasa USD
                        tasa = posible
                        print(f"🎯 Tasa BCV USD encontrada por ID 'dolar': {tasa}")
                except:
                    pass
        
        # Método 2: Buscar por id='usd' (alternativo)
        if not tasa:
            usd_div = soup.find('div', id='usd')
            if usd_div:
                strong = usd_div.find('strong')
                if strong:
                    txt = strong.text.strip().replace(".", "").replace(",", ".")
                    try:
                        posible = safe_float(txt)
                        if 10 < posible < 500:  # Rango más específico para tasa USD
                            tasa = posible
                            print(f"🎯 Tasa BCV USD encontrada por ID 'usd': {tasa}")
                    except:
                        pass
        # Método 3: Buscar por strong con texto que parezca una tasa
        if not tasa:
            for strong in soup.find_all('strong'):
                txt = strong.text.strip().replace('.', '').replace(',', '.')
                try:
                    posible = safe_float(txt)
                    if 10 < posible < 500:  # Rango específico para tasa USD
                        tasa = posible
                        print(f"🎯 Tasa BCV encontrada por strong: {tasa}")
                        break
                except:
                    continue
        
        # Método 4: Buscar por span con clase específica
        if not tasa:
            for span in soup.find_all('span', class_='centrado'):
                txt = span.text.strip().replace('.', '').replace(',', '.')
                try:
                    posible = safe_float(txt)
                    if posible > 10 and posible < 1000:
                        tasa = posible
                        print(f"🎯 Tasa BCV encontrada por span: {tasa}")
                        break
                except:
                    continue
        
        # Método 5: Buscar por regex más específico
        if not tasa:
            import re
            # Buscar patrones como 36,50 o 36.50 (más específico)
            matches = re.findall(r'(\d{2,}[.,]\d{2,})', resp.text)
            for m in matches:
                try:
                    posible = safe_float(m.replace('.', '').replace(',', '.'))
                    if posible > 10 and posible < 1000:
                        tasa = posible
                        print(f"🎯 Tasa BCV encontrada por regex: {tasa}")
                        break
                except:
                    continue
        
        # Método 6: Buscar en tablas específicas
        if not tasa:
            for table in soup.find_all('table'):
                for row in table.find_all('tr'):
                    for cell in row.find_all(['td', 'th']):
                        txt = cell.text.strip().replace('.', '').replace(',', '.')
                        try:
                            posible = safe_float(txt)
                            if posible > 10 and posible < 1000:
                                tasa = posible
                                print(f"🎯 Tasa BCV encontrada en tabla: {tasa}")
                                break
                        except:
                            continue
                    if tasa:
                        break
                if tasa:
                    break
        
        # Método 7: Buscar por texto que contenga "USD" o "Dólar"
        if not tasa:
            for element in soup.find_all(['div', 'span', 'p']):
                if 'USD' in element.text or 'Dólar' in element.text or 'dólar' in element.text:
                    txt = element.text.strip()
                    # Extraer números del texto
                    import re
                    numbers = re.findall(r'(\d+[.,]\d+)', txt)
                    for num in numbers:
                        try:
                            posible = safe_float(num.replace('.', '').replace(',', '.'))
                            if posible > 10 and posible < 1000:
                                tasa = posible
                                print(f"🎯 Tasa BCV encontrada por texto USD: {tasa}")
                                break
                        except:
                            continue
                    if tasa:
                        break
        
        if tasa and tasa > 10:
            # Guardar la tasa en el archivo
            guardar_ultima_tasa_bcv(tasa)
            print(f"💾 Tasa BCV ACTUAL guardada exitosamente: {tasa}")
            return tasa
        else:
            print("❌ No se pudo encontrar una tasa BCV válida en la página")
            # Solo como último recurso, usar tasa local
            tasa_local = cargar_ultima_tasa_bcv()
            if tasa_local and tasa_local > 10:
                print(f"WARNING Usando tasa BCV local como fallback: {tasa_local}")
                return tasa_local
            return None
            
    except Exception as e:
        print(f"❌ Error obteniendo tasa BCV: {e}")
        # Solo como último recurso, usar tasa local
        try:
            tasa_fallback = cargar_ultima_tasa_bcv()
            if tasa_fallback and tasa_fallback > 10:
                print(f"WARNING Usando tasa BCV de fallback después de error: {tasa_fallback}")
                return tasa_fallback
        except:
            pass
        return None

# --- Manejo de Errores ---
@app.errorhandler(404)
def pagina_no_encontrada(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def error_servidor(e):
    return render_template('500.html'), 500

@app.route('/clientes/reporte')
def reporte_clientes():
    try:
        # Obtener filtros de la URL
        q = request.args.get('q', '')
        orden = request.args.get('orden', 'nombre')
        fecha_desde = request.args.get('fecha_desde', '')
        fecha_hasta = request.args.get('fecha_hasta', '')
        monto_min = request.args.get('monto_min', '')
        monto_max = request.args.get('monto_max', '')
        tipo_cliente = request.args.get('tipo_cliente', 'todos')
        
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        inventario = cargar_datos(ARCHIVO_INVENTARIO)
        empresa = cargar_empresa()
        
        # Obtener la tasa BCV actual
        tasa_bcv = obtener_tasa_bcv()
        advertencia_tasa = None
        try:
            tasa_bcv = safe_float(tasa_bcv)
        except Exception:
            tasa_bcv = 0
        if not tasa_bcv or tasa_bcv < 1:
            advertencia_tasa = '¡Advertencia! No se ha podido obtener la tasa BCV actual.'
        
        # Calcular estadísticas generales
        total_clientes = len(clientes)
        total_notas_entrega = len(notas)
        total_facturado_general = 0
        total_abonado_general = 0
        total_cobrar = 0
        total_bs_general = 0
        
        # Estadísticas por cliente
        stats_clientes = {}
        for id_cliente, cliente in clientes.items():
            stats_clientes[id_cliente] = {
                'id': id_cliente,
                'nombre': cliente['nombre'],
                'cedula_rif': cliente.get('cedula_rif', ''),
                'email': cliente.get('email', ''),
                'telefono': cliente.get('telefono', ''),
                'direccion': cliente.get('direccion', ''),
                'fecha_registro': cliente.get('fecha_creacion', ''),
                'activo': cliente.get('activo', True),
                'total_notas_entrega': 0,
                'total_entregado_usd': 0,
                'total_entregado_bs': 0,
                'ultima_entrega': None,
                'total_facturado_usd': 0,
                'total_facturado_bs': 0,
                'total_abonado_usd': 0,
                'total_abonado_bs': 0,
                'total_por_cobrar_usd': 0,
                'total_por_cobrar_bs': 0,
                'promedio_por_nota_usd': 0,
                'promedio_por_nota_bs': 0,
                'dias_ultima_entrega': 0,
                'categoria_cliente': cliente.get('categoria_cliente', 'regular'),
                'vendedor_asignado': cliente.get('vendedor_asignado', ''),
                'fuente_captacion': cliente.get('fuente_captacion', ''),
                'etiquetas': cliente.get('etiquetas', [])
            }
        
        for nota in notas.values():
            id_cliente = nota.get('cliente_id')
            if id_cliente in stats_clientes:
                stats = stats_clientes[id_cliente]
                stats['total_notas_entrega'] += 1
                
                # Calcular totales en USD y BS
                total_usd = safe_float(nota.get('total_usd', 0))
                total_bs = safe_float(nota.get('total_bs', 0))
                total_abonado_usd = safe_float(nota.get('total_abonado', 0))
                total_abonado_bs = total_abonado_usd * tasa_bcv if tasa_bcv > 0 else 0
                total_por_cobrar_usd = max(0, total_usd - total_abonado_usd)
                total_por_cobrar_bs = max(0, total_bs - total_abonado_bs)
                
                # Actualizar estadísticas del cliente
                stats['total_facturado_usd'] += total_usd
                stats['total_facturado_bs'] += total_bs
                stats['total_abonado_usd'] += total_abonado_usd
                stats['total_abonado_bs'] += total_abonado_bs
                stats['total_por_cobrar_usd'] += total_por_cobrar_usd
                stats['total_por_cobrar_bs'] += total_por_cobrar_bs
                stats['total_entregado_usd'] += total_usd
                stats['total_entregado_bs'] += total_bs
                
                # Actualizar última entrega
                fecha_nota = nota.get('fecha')
                if fecha_nota:
                    if not stats['ultima_entrega'] or fecha_nota > stats['ultima_entrega']:
                        stats['ultima_entrega'] = fecha_nota
                
                # Actualizar totales generales
                total_facturado_general += total_usd
                total_abonado_general += total_abonado_usd
                total_cobrar += total_por_cobrar_usd
                total_bs_general += total_bs
        
        # Calcular promedios por cliente
        for stats in stats_clientes.values():
            if stats['total_notas_entrega'] > 0:
                stats['promedio_por_nota_usd'] = stats['total_entregado_usd'] / stats['total_notas_entrega']
                stats['promedio_por_nota_bs'] = stats['total_entregado_bs'] / stats['total_notas_entrega']
                
                # Calcular días desde última entrega
                if stats['ultima_entrega']:
                    try:
                        fecha_ultima = datetime.strptime(stats['ultima_entrega'], '%Y-%m-%d')
                        dias_diferencia = (datetime.now() - fecha_ultima).days
                        stats['dias_ultima_entrega'] = dias_diferencia
                    except:
                        stats['dias_ultima_entrega'] = 0
        
        # Ordenar clientes por total de entregas (Top 10 Mejores Clientes)
        top_clientes = sorted(
            [stats for stats in stats_clientes.values() if stats['total_entregado_usd'] > 0],
            key=lambda x: x['total_entregado_usd'],
            reverse=True
        )[:10]
        
        # Ordenar clientes por total por cobrar (Top 5 Clientes con Mayor Cuenta por Cobrar)
        peores_clientes = []
        for stats in stats_clientes.values():
            if stats['total_por_cobrar_usd'] > 0:
                peores_clientes.append(stats)
        
        peores_clientes = sorted(peores_clientes, key=lambda x: x['total_por_cobrar_usd'], reverse=True)[:5]
        
        # Estadísticas adicionales del sistema
        clientes_activos = len([c for c in stats_clientes.values() if c['activo']])
        clientes_inactivos = len([c for c in stats_clientes.values() if not c['activo']])
        clientes_con_entregas = len([c for c in stats_clientes.values() if c['total_notas_entrega'] > 0])
        clientes_sin_entregas = len([c for c in stats_clientes.values() if c['total_notas_entrega'] == 0])
        
        # Análisis por categoría de cliente
        categorias_clientes = {}
        for stats in stats_clientes.values():
            categoria = stats['categoria_cliente']
            if categoria not in categorias_clientes:
                categorias_clientes[categoria] = {
                    'total': 0,
                    'con_entregas': 0,
                    'total_entregas_usd': 0,
                    'total_entregas_bs': 0
                }
            categorias_clientes[categoria]['total'] += 1
            if stats['total_notas_entrega'] > 0:
                categorias_clientes[categoria]['con_entregas'] += 1
                categorias_clientes[categoria]['total_entregas_usd'] += stats['total_entregado_usd']
                categorias_clientes[categoria]['total_entregas_bs'] += stats['total_entregado_bs']
        
        # Análisis por fuente de captación
        fuentes_captacion = {}
        for stats in stats_clientes.values():
            fuente = stats['fuente_captacion'] or 'No especificada'
            if fuente not in fuentes_captacion:
                fuentes_captacion[fuente] = {
                    'total': 0,
                    'con_entregas': 0,
                    'total_entregas_usd': 0
                }
            fuentes_captacion[fuente]['total'] += 1
            if stats['total_notas_entrega'] > 0:
                fuentes_captacion[fuente]['con_entregas'] += 1
                fuentes_captacion[fuente]['total_entregas_usd'] += stats['total_entregado_usd']
        
        # Análisis por vendedor asignado
        vendedores = {}
        for stats in stats_clientes.values():
            vendedor = stats['vendedor_asignado'] or 'Sin asignar'
            if vendedor not in vendedores:
                vendedores[vendedor] = {
                    'total': 0,
                    'con_entregas': 0,
                    'total_entregas_usd': 0
                }
            vendedores[vendedor]['total'] += 1
            if stats['total_notas_entrega'] > 0:
                vendedores[vendedor]['con_entregas'] += 1
                vendedores[vendedor]['total_entregas_usd'] += stats['total_entregado_usd']
        
        # ========================================
        # MÉTRICAS AVANZADAS
        # ========================================
        
        # 1. Promedio de entrega por cliente
        clientes_con_entregas_lista = [stats for stats in stats_clientes.values() if stats['total_entregado_usd'] > 0]
        promedio_entrega_cliente = total_facturado_general / len(clientes_con_entregas_lista) if clientes_con_entregas_lista else 0
        
        mayor_nota = 0
        cliente_mayor_nota = None
        for nota in notas.values():
            total_nota = safe_float(nota.get('total_usd', 0))
            if total_nota > mayor_nota:
                mayor_nota = total_nota
                cliente_mayor_nota = nota.get('cliente_id')
        
        # 3. Clientes nuevos este mes y año
        now = datetime.now()
        mes_actual = now.month
        anio_actual = now.year
        
        clientes_nuevos_mes = 0
        clientes_nuevos_anio = 0
        
        for nota in notas.values():
            fecha_nota = nota.get('fecha')
            if fecha_nota:
                try:
                    fecha_dt = datetime.strptime(fecha_nota, '%Y-%m-%d')
                    if fecha_dt.month == mes_actual and fecha_dt.year == anio_actual:
                        clientes_nuevos_mes += 1
                    if fecha_dt.year == anio_actual:
                        clientes_nuevos_anio += 1
                except:
                    continue
        
        # 4. Clientes activos e inactivos (basado en campo activo del cliente)
        clientes_inactivos_lista = []
        clientes_activos_lista = []
        clientes_inactivos_ids = set()
        clientes_activos_ids = set()
        
        for stats in stats_clientes.values():
            # Verificar primero el campo activo del cliente
            if stats.get('activo', True):
                        clientes_activos_lista.append(stats)
                        clientes_activos_ids.add(stats['id'])
            else:
                clientes_inactivos_lista.append(stats)
                clientes_inactivos_ids.add(stats['id'])
        
        clientes_con_facturas = len([stats for stats in stats_clientes.values() if stats['total_notas_entrega'] > 0])
        tasa_conversion = (clientes_con_facturas / total_clientes * 100) if total_clientes > 0 else 0
        
        cliente_mas_frecuente = max(stats_clientes.values(), key=lambda x: x['total_notas_entrega']) if stats_clientes else None
        
        promedio_notas_cliente = total_notas_entrega / total_clientes if total_clientes > 0 else 0
        
        # 8. Clientes VIP (top 20% por valor de entregas)
        if clientes_con_entregas_lista:
            clientes_ordenados = sorted(clientes_con_entregas_lista, key=lambda x: x['total_entregado_usd'], reverse=True)
            num_vip = max(1, int(len(clientes_ordenados) * 0.2))  # 20% de clientes
            clientes_vip = clientes_ordenados[:num_vip]
            clientes_vip_ids = {c['id'] for c in clientes_vip}
        else:
            clientes_vip = []
            clientes_vip_ids = set()
        
        valor_promedio_nota = total_facturado_general / total_notas_entrega if total_notas_entrega > 0 else 0
        
        # 10. Clientes con mayor saldo pendiente
        clientes_saldo_pendiente = [stats for stats in stats_clientes.values() if stats['total_por_cobrar_usd'] > 0]
        clientes_saldo_pendiente = sorted(clientes_saldo_pendiente, key=lambda x: x['total_por_cobrar_usd'], reverse=True)[:10]
        
        # ========================================
        # FILTRADO AVANZADO
        # ========================================
        
        # Filtrar clientes según los criterios
        clientes_filtrados = {}
        for id_cliente, cliente in clientes.items():
            # Filtro de búsqueda predictiva por nombre o RIF
            if q:
                q_lower = q.lower().strip()
                nombre_cliente = cliente.get('nombre', '').lower()
                rif_cliente = cliente.get('rif', '').lower()
                
                # Búsqueda predictiva: verificar si el término está en cualquier parte del nombre o RIF
                nombre_match = q_lower in nombre_cliente
                rif_match = q_lower in rif_cliente
                
                # Búsqueda por palabras: dividir el término de búsqueda y verificar cada palabra
                palabras_busqueda = q_lower.split()
                nombre_palabras_match = all(palabra in nombre_cliente for palabra in palabras_busqueda)
                rif_palabras_match = all(palabra in rif_cliente for palabra in palabras_busqueda)
                
                # Si no hay coincidencia en ninguna de las opciones, continuar
                if not (nombre_match or rif_match or nombre_palabras_match or rif_palabras_match):
                    continue
            
            # Obtener estadísticas del cliente
            stats = stats_clientes.get(id_cliente, {})
            
            # Filtro por tipo de cliente
            ultima_compra_filtro = stats.get('ultima_compra')
            if tipo_cliente == 'activos':
                if not es_fecha_valida(ultima_compra_filtro) or ultima_compra_filtro < fecha_limite:
                    continue
            elif tipo_cliente == 'inactivos':
                if es_fecha_valida(ultima_compra_filtro) and ultima_compra_filtro >= fecha_limite:
                    continue
            elif tipo_cliente == 'vip' and id_cliente not in [c['id'] for c in clientes_vip]:
                continue
            elif tipo_cliente == 'pendientes' and stats.get('total_por_cobrar_usd', 0) <= 0:
                continue
            
            # Filtro por monto mínimo/máximo
            if monto_min and stats.get('total_entregado_usd', 0) < safe_float(monto_min):
                continue
            if monto_max and stats.get('total_entregado_usd', 0) > safe_float(monto_max):
                continue
            
            if fecha_desde or fecha_hasta:
                tiene_facturas_en_rango = False
                for nota in notas.values():
                    if nota.get('cliente_id') == id_cliente:
                        fecha_nota = nota.get('fecha', '')
                        if fecha_nota:
                            try:
                                fecha_dt = datetime.strptime(fecha_nota, '%Y-%m-%d')
                                if fecha_desde and fecha_dt < datetime.strptime(fecha_desde, '%Y-%m-%d'):
                                    continue
                                if fecha_hasta and fecha_dt > datetime.strptime(fecha_hasta, '%Y-%m-%d'):
                                    continue
                                tiene_facturas_en_rango = True
                            except:
                                continue
                if not tiene_facturas_en_rango:
                    continue
            
            clientes_filtrados[id_cliente] = cliente
        
        # Ordenar clientes filtrados
        if orden == 'nombre':
            clientes_filtrados = dict(sorted(clientes_filtrados.items(), key=lambda x: x[1]['nombre']))
        elif orden == 'rif':
            clientes_filtrados = dict(sorted(clientes_filtrados.items(), key=lambda x: x[1].get('rif', '')))
        elif orden == 'entregas':
            clientes_filtrados = dict(sorted(clientes_filtrados.items(), 
                                           key=lambda x: stats_clientes.get(x[0], {}).get('total_entregado_usd', 0), reverse=True))
        elif orden == 'ultima_entrega':
            clientes_filtrados = dict(sorted(clientes_filtrados.items(), 
                                           key=lambda x: stats_clientes.get(x[0], {}).get('ultima_entrega') or '', reverse=True))
        
        # Estadísticas de productos más comprados
        productos_stats = {}
        for nota in notas.values():
            productos = nota.get('productos', [])
            cantidades = nota.get('cantidades', [])
            precios = nota.get('precios', [])
            
            for i in range(len(productos)):
                id_producto = productos[i]
                if id_producto in inventario:
                    if id_producto not in productos_stats:
                        productos_stats[id_producto] = {
                            'nombre': inventario[id_producto]['nombre'],
                            'cantidad': 0,
                            'valor': 0
                        }
                    try:
                        cantidad = int(cantidades[i])
                        precio = safe_float(precios[i])
                        productos_stats[id_producto]['cantidad'] += cantidad
                        productos_stats[id_producto]['valor'] += cantidad * precio
                    except (ValueError, TypeError, IndexError):
                        continue
        
        # Ordenar productos por cantidad (Top 10 Productos Más Comprados)
        top_productos = sorted(
            productos_stats.values(),
            key=lambda x: x['cantidad'],
            reverse=True
        )[:10]
        
        return render_template('reporte_clientes.html',
            clientes=clientes,
            clientes_filtrados=clientes_filtrados,
            notas_entrega=notas,
            inventario=inventario,
            empresa=empresa,
            tasa_bcv=tasa_bcv,
            advertencia_tasa=advertencia_tasa,
            total_clientes=total_clientes,
            total_notas_entrega=total_notas_entrega,
            total_facturado_usd=total_facturado_general,
            total_facturado_bs=total_bs_general,
            total_abonado_usd=total_abonado_general,
            total_abonado_bs=total_abonado_general * tasa_bcv if tasa_bcv > 0 else 0,
            total_por_cobrar_usd=total_cobrar,
            total_por_cobrar_bs=total_cobrar * tasa_bcv if tasa_bcv > 0 else 0,
            top_clientes=top_clientes,
            peores_clientes=peores_clientes,
            top_productos=top_productos,
            # Estadísticas del sistema
            clientes_activos=clientes_activos,
            clientes_inactivos=clientes_inactivos,
            clientes_con_entregas=clientes_con_entregas,
            clientes_sin_entregas=clientes_sin_entregas,
            categorias_clientes=categorias_clientes,
            fuentes_captacion=fuentes_captacion,
            vendedores=vendedores,
            # Métricas avanzadas
            promedio_entrega_cliente=promedio_entrega_cliente,
            mayor_nota=mayor_nota,
            cliente_mayor_nota=cliente_mayor_nota,
            clientes_nuevos_mes=clientes_nuevos_mes,
            clientes_nuevos_anio=clientes_nuevos_anio,
            tasa_conversion=tasa_conversion,
            cliente_mas_frecuente=cliente_mas_frecuente,
            promedio_notas_cliente=promedio_notas_cliente,
            promedio_facturas_cliente=promedio_notas_cliente,
            clientes_vip=clientes_vip,
            clientes_vip_ids=clientes_vip_ids,
            valor_promedio_nota=valor_promedio_nota,
            clientes_saldo_pendiente=clientes_saldo_pendiente,
            clientes_inactivos_ids=clientes_inactivos_ids,
            clientes_activos_ids=clientes_activos_ids,
            stats_clientes=stats_clientes,
            # Filtros
            q=q,
            orden=orden,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            monto_min=monto_min,
            monto_max=monto_max,
            tipo_cliente=tipo_cliente
        )
    except Exception as e:
        print(f"Error en reporte_clientes: {e}")
        return str(e), 500

@app.route('/clientes/exportar')
def exportar_clientes():
    """Exportar clientes a Excel con filtros aplicados."""
    try:
        # Obtener filtros de la URL
        q = request.args.get('q', '').strip().lower()
        filtro_orden = request.args.get('filtro_orden', 'nombre')
        filtro_tipo = request.args.get('filtro_tipo', '')
        filtro_estado = request.args.get('filtro_estado', '')
        
        # Cargar datos
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        ordenes = cargar_datos('ordenes_servicio.json')
        
        # Aplicar filtros (misma lógica que mostrar_clientes)
        if q:
            clientes_filtrados = {}
            for k, v in clientes.items():
                if (q in v.get('nombre', '').lower() or 
                    q in v.get('cedula_rif', '').lower() or 
                    q in v.get('email', '').lower() or 
                    q in v.get('telefono', '').lower() or 
                    q in v.get('direccion', '').lower() or
                    q in k.lower()):
                    clientes_filtrados[k] = v
            clientes = clientes_filtrados
        
        if filtro_tipo:
            clientes = {k: v for k, v in clientes.items() if v.get('tipo_id', '') == filtro_tipo}
        
        if filtro_estado:
            if filtro_estado == 'activo':
                clientes = {k: v for k, v in clientes.items() if v.get('activo', True)}
            elif filtro_estado == 'inactivo':
                clientes = {k: v for k, v in clientes.items() if not v.get('activo', True)}
        
        # Ordenamiento
        if filtro_orden == 'nombre':
            clientes = dict(sorted(clientes.items(), key=lambda item: item[1].get('nombre', '').lower()))
        elif filtro_orden == 'cedula_rif':
            clientes = dict(sorted(clientes.items(), key=lambda item: item[1].get('cedula_rif', '').lower()))
        elif filtro_orden == 'fecha_creacion':
            clientes = dict(sorted(clientes.items(), key=lambda item: item[1].get('fecha_creacion', ''), reverse=True))
        elif filtro_orden == 'email':
            clientes = dict(sorted(clientes.items(), key=lambda item: item[1].get('email', '').lower()))
        
        # Crear archivo Excel
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output)
        worksheet = workbook.add_worksheet('Clientes')
        
        # Formato para encabezados
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#00ff88',
            'font_color': 'white',
            'border': 1,
            'align': 'center'
        })
        
        # Formato para datos
        data_format = workbook.add_format({
            'border': 1,
            'align': 'left'
        })
        
        # Formato para números
        number_format = workbook.add_format({
            'border': 1,
            'align': 'right',
            'num_format': '#,##0.00'
        })
        
        # Encabezados
        headers = [
            'ID Cliente', 'Tipo ID', 'Cédula/RIF', 'Nombre', 'Email', 
            'Teléfono', 'Teléfono 2', 'Dirección', 'Fecha Registro',
            'Total Facturado', 'Total Abonado', 'Por Cobrar', 'Órdenes de Servicio'
        ]
        
        # Escribir encabezados
        for col, header in enumerate(headers):
            worksheet.write(0, col, header, header_format)
        
        # Escribir datos
        row = 1
        for cliente_id, cliente in clientes.items():
            # Calcular estadísticas del cliente
            notas_cliente = [f for f in notas.values() if f.get('cliente_id') == cliente_id]
            ordenes_cliente = [o for o in ordenes.values() if o.get('cliente_id') == cliente_id]
            
            total_facturado = sum(safe_float(f.get('total_usd', 0)) for f in notas_cliente)
            total_abonado = sum(safe_float(f.get('total_abonado', 0)) for f in notas_cliente)
            total_por_cobrar = max(0, total_facturado - total_abonado)
            
            # Datos del cliente
            data = [
                cliente_id,
                cliente.get('tipo_id', 'V'),
                cliente.get('cedula_rif', ''),
                cliente.get('nombre', ''),
                cliente.get('email', ''),
                cliente.get('telefono', ''),
                cliente.get('telefono2', ''),
                cliente.get('direccion', ''),
                cliente.get('fecha_creacion', ''),
                total_facturado,
                total_abonado,
                total_por_cobrar,
                len(ordenes_cliente)
            ]
            
            # Escribir fila
            for col, value in enumerate(data):
                if col >= 9:  # Columnas numéricas
                    worksheet.write(row, col, value, number_format)
                else:
                    worksheet.write(row, col, value, data_format)
            
            row += 1
        
        # Ajustar ancho de columnas
        worksheet.set_column('A:A', 15)  # ID Cliente
        worksheet.set_column('B:B', 8)   # Tipo ID
        worksheet.set_column('C:C', 15)  # Cédula/RIF
        worksheet.set_column('D:D', 25)  # Nombre
        worksheet.set_column('E:E', 25)  # Email
        worksheet.set_column('F:F', 15)  # Teléfono
        worksheet.set_column('G:G', 15)  # Teléfono 2
        worksheet.set_column('H:H', 30)  # Dirección
        worksheet.set_column('I:I', 12)  # Fecha Registro
        worksheet.set_column('J:J', 15)  # Total Facturado
        worksheet.set_column('K:K', 15)  # Total Abonado
        worksheet.set_column('L:L', 15)  # Por Cobrar
        worksheet.set_column('M:M', 15)  # Órdenes de Servicio
        
        # Cerrar workbook
        workbook.close()
        output.seek(0)
        
        # Crear respuesta
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        response.headers['Content-Disposition'] = f'attachment; filename=clientes_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
        
        return response
        
    except Exception as e:
        print(f"Error en exportar_clientes: {str(e)}")
        flash(f'Error al exportar clientes: {str(e)}', 'danger')
        return redirect(url_for('mostrar_clientes'))

@app.route('/clientes/pagos-pendientes')
@login_required
def clientes_pagos_pendientes():
    """Vista especializada para clientes con pagos pendientes."""
    try:
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        
        # Filtrar solo clientes con pagos pendientes
        clientes_pendientes = {}
        total_pendiente = 0
        
        for cliente_id, cliente in clientes.items():
            notas_cliente = [f for f in notas.values() if f.get('cliente_id') == cliente_id]
            total_notas_entrega = sum(safe_float(f.get('total_usd', 0)) for f in notas_cliente)
            total_abonado = sum(safe_float(f.get('total_abonado', 0)) for f in notas_cliente)
            total_por_cobrar = max(0, total_notas_entrega - total_abonado)
            
            if total_por_cobrar > 0:
                clientes_pendientes[cliente_id] = {
                    **cliente,
                    'total_facturado': total_notas_entrega,  # Mantener nombre para compatibilidad
                    'total_abonado': total_abonado,
                    'total_por_cobrar': total_por_cobrar,
                    'dias_pendiente': calcular_dias_pendiente(notas_cliente)
                }
                total_pendiente += total_por_cobrar
        
        # Ordenar por monto pendiente (mayor a menor)
        clientes_pendientes = dict(sorted(
            clientes_pendientes.items(), 
            key=lambda x: x[1]['total_por_cobrar'], 
            reverse=True
        ))
        
        return render_template('clientes_pagos_pendientes.html',
                             clientes=clientes_pendientes,
                             total_pendiente=total_pendiente,
                             total_clientes=len(clientes_pendientes))
    except Exception as e:
        print(f"Error en clientes_pagos_pendientes: {str(e)}")
        flash(f'Error al cargar clientes con pagos pendientes: {str(e)}', 'danger')
        return redirect(url_for('mostrar_clientes'))

@app.route('/clientes/accion-masiva', methods=['POST'])
@login_required
def accion_masiva_clientes():
    """Activar/desactivar múltiples clientes."""
    try:
        accion = request.form.get('accion')
        cliente_ids = request.form.getlist('cliente_ids')
        
        if not cliente_ids:
            flash('No se seleccionaron clientes', 'warning')
            return redirect(url_for('mostrar_clientes'))
        
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        clientes_modificados = 0
        
        for cliente_id in cliente_ids:
            if cliente_id in clientes:
                if accion == 'activar':
                    clientes[cliente_id]['activo'] = True
                    clientes_modificados += 1
                elif accion == 'desactivar':
                    clientes[cliente_id]['activo'] = False
                    clientes_modificados += 1
        
        guardar_datos(ARCHIVO_CLIENTES, clientes)
        
        flash(f'Se {accion}ron {clientes_modificados} clientes exitosamente', 'success')
        return redirect(url_for('mostrar_clientes'))
        
    except Exception as e:
        print(f"Error en accion_masiva_clientes: {str(e)}")
        flash(f'Error al ejecutar acción masiva: {str(e)}', 'danger')
        return redirect(url_for('mostrar_clientes'))

@app.route('/clientes/comunicacion-masiva', methods=['POST'])
@login_required
def comunicacion_masiva_clientes():
    """Envío de comunicación masiva a clientes."""
    try:
        tipo_comunicacion = request.form.get('tipo_comunicacion')
        cliente_ids = request.form.getlist('cliente_ids')
        mensaje = request.form.get('mensaje', '').strip()
        asunto = request.form.get('asunto', '').strip()
        
        if not cliente_ids:
            flash('No se seleccionaron clientes', 'warning')
            return redirect(url_for('mostrar_clientes'))
        
        if not mensaje:
            flash('El mensaje es obligatorio', 'warning')
            return redirect(url_for('mostrar_clientes'))
        
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        clientes_contactados = 0
        
        for cliente_id in cliente_ids:
            if cliente_id in clientes:
                cliente = clientes[cliente_id]
                
                if tipo_comunicacion == 'whatsapp':
                    telefono = cliente.get('telefono', '').replace('+58', '').replace('+', '')
                    if telefono and len(telefono) >= 10:
                        enlace_whatsapp = f"https://wa.me/58{telefono}?text={mensaje}"
                        # Aquí podrías integrar con una API de WhatsApp
                        clientes_contactados += 1
                
                elif tipo_comunicacion == 'email':
                    email = cliente.get('email', '')
                    if email and '@' in email:
                        # Aquí podrías integrar con un servicio de email
                        clientes_contactados += 1
        
        flash(f'Comunicación enviada a {clientes_contactados} clientes', 'success')
        return redirect(url_for('mostrar_clientes'))
        
    except Exception as e:
        print(f"Error en comunicacion_masiva_clientes: {str(e)}")
        flash(f'Error al enviar comunicación: {str(e)}', 'danger')
        return redirect(url_for('mostrar_clientes'))

@app.route('/clientes/por-fecha')
@login_required
def clientes_por_fecha():
    """Vista de clientes filtrados por fecha de registro/actividad."""
    try:
        fecha_desde = request.args.get('fecha_desde', '')
        fecha_hasta = request.args.get('fecha_hasta', '')
        tipo_fecha = request.args.get('tipo_fecha', 'registro')  # registro o actividad
        
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        
        clientes_filtrados = {}
        
        for cliente_id, cliente in clientes.items():
            fecha_cliente = None
            
            if tipo_fecha == 'registro':
                fecha_cliente = cliente.get('fecha_creacion', '')
            elif tipo_fecha == 'actividad':
                # Buscar la fecha más reciente de actividad
                notas_cliente = [f for f in notas.values() if f.get('cliente_id') == cliente_id]
                fechas_actividad = [f.get('fecha', '') for f in notas_cliente if f.get('fecha')]
                fechas_actividad.append(cliente.get('fecha_creacion', ''))
                fecha_cliente = max(fechas_actividad) if fechas_actividad else cliente.get('fecha_creacion', '')
            
            if fecha_cliente:
                if fecha_desde and fecha_cliente < fecha_desde:
                    continue
                if fecha_hasta and fecha_cliente > fecha_hasta:
                    continue
                
                clientes_filtrados[cliente_id] = cliente
        
        return render_template('clientes_por_fecha.html',
                             clientes=clientes_filtrados,
                             fecha_desde=fecha_desde,
                             fecha_hasta=fecha_hasta,
                             tipo_fecha=tipo_fecha,
                             datetime=datetime,
                             timedelta=timedelta)
    except Exception as e:
        print(f"Error en clientes_por_fecha: {str(e)}")
        flash(f'Error al filtrar clientes por fecha: {str(e)}', 'danger')
        return redirect(url_for('mostrar_clientes'))

@app.route('/clientes/calendario')
@login_required
def clientes_calendario():
    """Vista de calendario con clientes y órdenes de servicio por fecha."""
    try:
        mes = request.args.get('mes', datetime.now().month)
        año = request.args.get('año', datetime.now().year)
        filtro_tipo = request.args.get('tipo', 'todos')  # todos, clientes, ordenes, diagnosticos
        
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        ordenes = cargar_datos('ordenes_servicio.json')
        
        # Crear calendario con eventos por fecha
        calendario = {}
        
        # Procesar clientes (registros)
        if filtro_tipo in ['todos', 'clientes']:
            for cliente_id, cliente in clientes.items():
                fecha_registro = cliente.get('fecha_creacion', '')
                if fecha_registro:
                    try:
                        fecha_obj = datetime.fromisoformat(fecha_registro.replace('Z', '+00:00'))
                        if fecha_obj.month == int(mes) and fecha_obj.year == int(año):
                            dia = fecha_obj.day
                            if dia not in calendario:
                                calendario[dia] = []
                            calendario[dia].append({
                                'id': cliente_id,
                                'nombre': cliente.get('nombre', 'Sin nombre'),
                                'tipo': 'registro_cliente',
                                'descripcion': 'Nuevo cliente registrado',
                                'hora': fecha_obj.strftime('%H:%M'),
                                'icono': 'fas fa-user-plus',
                                'color': '#4CAF50'
                            })
                    except:
                        continue
        
        # Procesar órdenes de servicio
        if filtro_tipo in ['todos', 'ordenes'] and ordenes:
            for orden_id, orden in ordenes.items():
                # Fecha de recepción
                fecha_recepcion = orden.get('fecha_recepcion', '')
                if fecha_recepcion:
                    try:
                        fecha_obj = datetime.fromisoformat(fecha_recepcion.replace('Z', '+00:00'))
                        if fecha_obj.month == int(mes) and fecha_obj.year == int(año):
                            dia = fecha_obj.day
                            if dia not in calendario:
                                calendario[dia] = []
                            
                            # Calcular tiempo estimado de reparación
                            tiempo_estimado = orden.get('tiempo_estimado_reparacion', 'No especificado')
                            if tiempo_estimado == 'No especificado':
                                # Calcular basado en el tipo de problema
                                categoria = orden.get('categoria_problema', '')
                                if 'pantalla' in categoria.lower():
                                    tiempo_estimado = '2-3 días'
                                elif 'bateria' in categoria.lower():
                                    tiempo_estimado = '1 día'
                                elif 'software' in categoria.lower():
                                    tiempo_estimado = '1-2 días'
                                else:
                                    tiempo_estimado = '3-5 días'
                            
                            calendario[dia].append({
                                'id': orden_id,
                                'nombre': f"Orden {orden.get('numero_orden', orden_id)}",
                                'cliente': orden.get('cliente', {}).get('nombre', 'Sin nombre'),
                                'tipo': 'orden_recepcion',
                                'descripcion': f"Equipo: {orden.get('equipo', {}).get('marca', 'N/A')} {orden.get('equipo', {}).get('modelo', 'N/A')}",
                                'problema': orden.get('problema_reportado', 'Sin descripción'),
                                'tiempo_estimado': tiempo_estimado,
                                'estado': orden.get('estado', 'Sin estado'),
                                'prioridad': orden.get('prioridad', 'media'),
                                'tecnico': orden.get('tecnico_asignado', 'Sin asignar'),
                                'hora': fecha_obj.strftime('%H:%M'),
                                'icono': 'fas fa-tools',
                                'color': '#FF9800'
                            })
                    except:
                        continue
                
                # Fecha de entrega estimada
                fecha_entrega = orden.get('fecha_entrega_estimada', '')
                if fecha_entrega:
                    try:
                        fecha_obj = datetime.fromisoformat(fecha_entrega.replace('Z', '+00:00'))
                        if fecha_obj.month == int(mes) and fecha_obj.year == int(año):
                            dia = fecha_obj.day
                            if dia not in calendario:
                                calendario[dia] = []
                            
                            calendario[dia].append({
                                'id': f"{orden_id}_entrega",
                                'nombre': f"Entrega estimada - {orden.get('numero_orden', orden_id)}",
                                'cliente': orden.get('cliente', {}).get('nombre', 'Sin nombre'),
                                'tipo': 'orden_entrega',
                                'descripcion': f"Entrega estimada de reparación",
                                'hora': fecha_obj.strftime('%H:%M'),
                                'icono': 'fas fa-shipping-fast',
                                'color': '#2196F3'
                            })
                    except:
                        continue
        
        # Procesar diagnósticos
        if filtro_tipo in ['todos', 'diagnosticos'] and ordenes:
            for orden_id, orden in ordenes.items():
                # Buscar diagnósticos en el historial
                historial = orden.get('historial', [])
                for evento in historial:
                    if evento.get('tipo') == 'diagnostico':
                        fecha_diagnostico = evento.get('fecha', '')
                        if fecha_diagnostico:
                            try:
                                fecha_obj = datetime.fromisoformat(fecha_diagnostico.replace('Z', '+00:00'))
                                if fecha_obj.month == int(mes) and fecha_obj.year == int(año):
                                    dia = fecha_obj.day
                                    if dia not in calendario:
                                        calendario[dia] = []
                                    
                                    diagnostico = evento.get('diagnostico', {})
                                    calendario[dia].append({
                                        'id': f"{orden_id}_diagnostico_{fecha_obj.strftime('%Y%m%d%H%M')}",
                                        'nombre': f"Diagnóstico - {orden.get('numero_orden', orden_id)}",
                                        'cliente': orden.get('cliente', {}).get('nombre', 'Sin nombre'),
                                        'tipo': 'diagnostico',
                                        'descripcion': diagnostico.get('problema_encontrado', 'Sin diagnóstico'),
                                        'solucion_propuesta': diagnostico.get('solucion_propuesta', 'Sin solución'),
                                        'costo_estimado': diagnostico.get('costo_estimado', 0),
                                        'tiempo_estimado': diagnostico.get('tiempo_estimado', 'No especificado'),
                                        'hora': fecha_obj.strftime('%H:%M'),
                                        'icono': 'fas fa-stethoscope',
                                        'color': '#9C27B0'
                                    })
                            except:
                                continue
        
        # Ordenar eventos por hora dentro de cada día
        for dia in calendario:
            calendario[dia].sort(key=lambda x: x.get('hora', '00:00'))
        
        return render_template('clientes_calendario.html',
                             calendario=calendario,
                             mes=int(mes),
                             año=int(año),
                             filtro_tipo=filtro_tipo,
                             datetime=datetime)
    except Exception as e:
        print(f"Error en clientes_calendario: {str(e)}")
        flash(f'Error al cargar calendario: {str(e)}', 'danger')
        return redirect(url_for('mostrar_clientes'))

def calcular_dias_pendiente(notas_cliente):
    """Calcula los días de pago pendiente más antiguo."""
    try:
        fechas_pendientes = []
        for nota in notas_cliente:
            if nota.get('estado') == 'pendiente' and nota.get('fecha'):
                fechas_pendientes.append(datetime.fromisoformat(nota['fecha'].replace('Z', '+00:00')))
        
        if fechas_pendientes:
            fecha_mas_antigua = min(fechas_pendientes)
            return (datetime.now() - fecha_mas_antigua).days
        return 0
    except:
        return 0

@app.route('/clientes/<path:id>/historial')
def historial_cliente(id):
    clientes = cargar_datos(ARCHIVO_CLIENTES)
    notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
    cuentas = cargar_datos(ARCHIVO_CUENTAS)
    inventario = cargar_datos(ARCHIVO_INVENTARIO)
    
    if id not in clientes:
        flash('Cliente no encontrado', 'danger')
        return redirect(url_for('mostrar_clientes'))
    
    cliente = clientes[id]
    now = datetime.now()
    # Manejo robusto de filtros (evitar ValueError por strings vacíos)
    anio_param = request.args.get('anio')
    try:
        filtro_anio = int(anio_param) if anio_param else now.year
    except (TypeError, ValueError):
        filtro_anio = now.year
    # Mes robusto
    mes_param = request.args.get('mes', '')
    try:
        filtro_mes = int(mes_param) if mes_param else ''
    except (TypeError, ValueError):
        filtro_mes = ''

    notas_cliente = []
    for factura_id, factura_data in notas.items():
        if factura_data.get('cliente_id') != id:
            continue
        factura_copia = factura_data.copy()
        nota_copia['id'] = nota_id
        total_abonado = 0
        pagos = factura_copia.get('pagos') or []
        try:
            pagos_iterables = pagos.values() if isinstance(pagos, dict) else pagos
        except Exception:
            pagos_iterables = []
        for pago in pagos_iterables:
            try:
                monto = safe_float(pago.get('monto', 0))
                total_abonado += monto
            except Exception:
                continue
        try:
            total_usd_nota = safe_float(factura_copia.get('total_usd', factura_copia.get('total', 0)))
        except Exception:
            total_usd_nota = 0.0
        factura_copia['total_abonado'] = total_abonado
        factura_copia['saldo_pendiente'] = max(total_usd_nota - total_abonado, 0)
        notas_cliente.append(factura_copia)
    
    facturas_filtradas = []
    for f in notas_cliente:
        fecha = f.get('fecha', '')
        try:
            fecha_dt = datetime.strptime(fecha, '%Y-%m-%d')
            if fecha_dt.year == filtro_anio and (not filtro_mes or fecha_dt.month == filtro_mes):
                facturas_filtradas.append(f)
        except Exception:
            continue

    # Calcular totales anuales (protegido)
    facturas_anio_actual = []
    for f in notas_cliente:
        fecha_txt = f.get('fecha', '')
        try:
            if fecha_txt:
                if datetime.strptime(fecha_txt, '%Y-%m-%d').year == now.year:
                    facturas_anio_actual.append(f)
        except Exception:
            continue
    total_anual_usd = sum(safe_float(f.get('total_usd', 0)) for f in facturas_anio_actual)
    total_anual_bs = sum(safe_float(f.get('total_bs', 0)) for f in facturas_anio_actual)

    # Calcular totales mensuales (protegido)
    facturas_mes_actual = []
    for f in notas_cliente:
        fecha_txt = f.get('fecha', '')
        try:
            if fecha_txt:
                fecha_dt = datetime.strptime(fecha_txt, '%Y-%m-%d')
                if fecha_dt.year == now.year and fecha_dt.month == now.month:
                    facturas_mes_actual.append(f)
        except Exception:
            continue
    total_mensual_usd = sum(safe_float(f.get('total_usd', 0)) for f in facturas_mes_actual)
    total_mensual_bs = sum(safe_float(f.get('total_bs', 0)) for f in facturas_mes_actual)
    
    cuenta = next((c for c in cuentas.values() if c.get('cliente_id') == id), None)
    
    # Totales filtrados
    total_compras = sum(
        safe_float(f.get('total_usd', f.get('total', 0)))
        for f in facturas_filtradas
    )
    total_bs = sum(
        safe_float(f.get('total_bs', 0)) if f.get('total_bs', 0) else (
            safe_float(f.get('total_usd', f.get('total', 0))) * safe_float(f.get('tasa_bcv', 0) or 0)
        )
        for f in facturas_filtradas
    )

    # Productos comprados filtrados
    productos_comprados = {}
    for nota in facturas_filtradas:
        productos = nota.get('productos', [])
        cantidades = nota.get('cantidades', [])
        precios = nota.get('precios', [])
        
        for i in range(len(productos)):
            prod_id = productos[i]
            if prod_id in inventario:
                if prod_id not in productos_comprados:
                    productos_comprados[prod_id] = {
                        'nombre': inventario[prod_id]['nombre'],
                        'cantidad': 0,
                        'valor': 0
                    }
                try:
                    cantidad = int(cantidades[i])
                    precio = safe_float(precios[i])
                    productos_comprados[prod_id]['cantidad'] += cantidad
                    productos_comprados[prod_id]['valor'] += cantidad * precio
                except (ValueError, TypeError, IndexError):
                    continue

    # Ordenar productos por valor total
    productos_comprados = dict(sorted(productos_comprados.items(), key=lambda x: x[1]['valor'], reverse=True))

    # Para el formulario de filtro (protegido)
    anios_disponibles_set = set()
    for f in notas_cliente:
        fecha_txt = f.get('fecha', '')
        if not fecha_txt:
            continue
        try:
            anios_disponibles_set.add(datetime.strptime(fecha_txt, '%Y-%m-%d').year)
        except Exception:
            continue
    anios_disponibles = sorted(anios_disponibles_set)
    
    try:
        promedio_por_nota = safe_float(total_compras) / len(facturas_filtradas) if len(facturas_filtradas) > 0 and total_compras is not None else 0.0
    except (TypeError, ValueError, ZeroDivisionError):
        promedio_por_nota = 0.0
    
    # Obtener configuración de mapas
    maps_config = get_maps_config()
    
    return render_template(
        'historial_cliente.html',
        cliente=cliente,
        facturas=facturas_filtradas,
        cuenta=cuenta,
        total_compras=total_compras,
        total_bs=total_bs,
        total_anual_usd=total_anual_usd,
        total_anual_bs=total_anual_bs,
        total_mensual_usd=total_mensual_usd,
        total_mensual_bs=total_mensual_bs,
        productos_comprados=productos_comprados,
        filtro_anio=filtro_anio,
        filtro_mes=filtro_mes,
        anios_disponibles=anios_disponibles,
        promedio_por_factura=promedio_por_nota,
        maps_config=maps_config,
        now=now
    )

@app.route('/inventario/cargar-csv', methods=['GET', 'POST'])
def cargar_productos_csv():
    """Formulario para cargar productos desde CSV."""
    if request.method == 'POST':
        if 'archivo' not in request.files:
            flash('No se seleccionó ningún archivo', 'danger')
            return redirect(request.url)
        
        archivo = request.files['archivo']
        if archivo.filename == '':
            flash('No se seleccionó ningún archivo', 'danger')
            return redirect(request.url)
        
        if archivo and allowed_file(archivo.filename):
            try:
                filename = secure_filename(archivo.filename)
                ruta_archivo = os.path.join(UPLOAD_FOLDER, filename)
                archivo.save(ruta_archivo)
                
                if cargar_productos_desde_csv(ruta_archivo):
                    flash('Productos cargados exitosamente', 'success')
                else:
                    flash('Error al cargar los productos', 'danger')
                
                # Limpiar archivo después de procesarlo
                try:
                    os.remove(ruta_archivo)
                except:
                    pass
                    
                return redirect(url_for('mostrar_inventario'))
            except Exception as e:
                flash(f'Error al procesar el archivo: {str(e)}', 'danger')
                return redirect(request.url)
        
        flash('Tipo de archivo no permitido', 'danger')
        return redirect(request.url)
    
    return render_template('cargar_csv.html', tipo='productos')

@app.route('/inventario/eliminar-multiples', methods=['POST'])
def eliminar_productos_multiples():
    try:
        productos = json.loads(request.form.get('productos', '[]'))
        if not productos:
            flash('No se seleccionaron productos para eliminar', 'warning')
            return redirect(url_for('mostrar_inventario'))
        
        inventario = cargar_datos('inventario.json')
        eliminados = 0
        
        for id in productos:
            if id in inventario:
                del inventario[id]
                eliminados += 1
        
        if guardar_datos('inventario.json', inventario):
            flash(f'Se eliminaron {eliminados} productos exitosamente', 'success')
        else:
            flash('Error al guardar los cambios', 'danger')
            
    except Exception as e:
        flash(f'Error al eliminar los productos: {str(e)}', 'danger')
    
    return redirect(url_for('mostrar_inventario'))

# --- Filtro personalizado para fechas legibles ---
@app.template_filter('datetimeformat')
def datetimeformat(value, format='%d/%m/%Y %H:%M:%S'):
    """Convierte una cadena de fecha a formato legible."""
    if not value:
        return ''
    try:
        # Intentar parsear formato ISO
        if 'T' in value:
            value = value.split('.')[0].replace('T', ' ')
        dt = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
        return dt.strftime(format)
    except Exception:
        return value  # Si falla, mostrar la cadena original

# --- Filtro personalizado para números en formato español ---
@app.template_filter('es_number')
def es_number(value, decimales=2):
    """Convierte un número a formato español (punto para miles, coma para decimales)."""
    try:
        # Si es None o string vacío, retornar 0
        if value is None or value == '':
            return f"0,{decimales * '0'}"
            
        # Convertir a float
        value = safe_float(value)
        
        # Si es 0, retornar formato con decimales
        if value == 0:
            return f"0,{decimales * '0'}"
            
        # Formatear con separadores de miles y decimales
        formatted = f"{abs(value):,.{decimales}f}"
        
        # Reemplazar comas y puntos para formato español
        formatted = formatted.replace(",", "X").replace(".", ",").replace("X", ".")
        
        # Agregar signo negativo si corresponde
        if value < 0:
            formatted = f"-{formatted}"
            
        return formatted
    except Exception:
        return str(value) if value is not None else "0"

@app.template_filter('money')
def money(value, decimals=2):
    """Formatea un número como moneda con separadores de miles (coma) y punto decimal."""
    try:
        if value is None or value == '':
            return f"0.{'0' * decimals}"
        
        value = safe_float(value)
        return f"{value:,.{decimals}f}"
    except Exception:
        return str(value) if value is not None else "0.00"

# --- Filtro personalizado para conversión segura a float ---
@app.template_filter('float')
def float_filter(value, default=0.0):
    """Filtro Jinja2 para conversión segura a float."""
    return safe_float(value, default)

# --- Filtro personalizado para formatear moneda ---
@app.template_filter('format_currency')
def format_currency(value, currency='USD', decimales=2):
    """Formatea un número como moneda."""
    try:
        # Si es None o string vacío, retornar 0
        if value is None or value == '':
            return f"$0,{decimales * '0'}"
            
        # Convertir a float
        value = safe_float(value)
        
        # Si es 0, retornar formato con decimales
        if value == 0:
            return f"$0,{decimales * '0'}"
        
        # Formatear con separadores de miles
        if currency == 'USD':
            return f"${value:,.{decimales}f}"
        elif currency == 'VES' or currency == 'BS':
            return f"Bs {value:,.{decimales}f}"
        else:
            return f"{currency} {value:,.{decimales}f}"
            
    except (ValueError, TypeError):
        return f"$0,{decimales * '0'}"

# ===== RUTA PARA RECORDATORIOS WHATSAPP MEJORADA =====
@app.route('/cuentas-por-cobrar/enviar_recordatorio_whatsapp', methods=['POST'])
def enviar_recordatorio_cuentas_por_cobrar_body():
    """Endpoint que recibe cliente_id por body JSON y genera recordatorio inteligente con diferentes niveles de urgencia."""
    print(f"🔍 RUTA REGISTRADA: /cuentas-por-cobrar/enviar_recordatorio_whatsapp")
    print(f"🔍 Endpoint llamado - Método: {request.method}")
    
    try:
        # Obtener datos del body
        data = request.get_json(silent=True)
        print(f"🔍 JSON recibido: {data}")
        
        if not data:
            data = request.form.to_dict()
            print(f"🔍 Form data recibido: {data}")
        
        cliente_id = str(data.get('cliente_id') or '').strip()
        print(f"🔍 Cliente ID extraído: '{cliente_id}'")
        
        if not cliente_id:
            return jsonify({'error': 'Falta cliente_id en la solicitud'}), 400
        
        # Cargar datos directamente aquí
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        
        if cliente_id not in clientes:
            return jsonify({'error': 'Cliente no encontrado'}), 404
        
        cliente = clientes[cliente_id]
        telefono = cliente.get('telefono', '')
        
        if not telefono:
            return jsonify({'error': 'El cliente no tiene teléfono registrado'}), 400
        
        facturas_pendientes = []
        total_pendiente = 0.0
        
        for nota_id, nota in notas.items():
            if nota.get('cliente_id') == cliente_id:
                total_nota = safe_float(nota.get('total_usd', 0))
                total_abonado = safe_float(nota.get('total_abonado', 0))
                saldo_pendiente = max(0, total_nota - total_abonado)
                
                if saldo_pendiente > 0:
                    facturas_pendientes.append({
                        'id': factura_id,
                        'numero': nota.get('numero', 'N/A'),
                        'fecha': nota.get('fecha', 'N/A'),
                        'total': total_nota,
                        'abonado': total_abonado,
                        'saldo': saldo_pendiente
                    })
                    total_pendiente += saldo_pendiente
        
        if not facturas_pendientes:
            return jsonify({
                'success': True,
                'message': 'El cliente no tiene facturas pendientes de pago',
                'total_notas_entrega': 0,
                'total_pendiente': 0
            })
        
        # Formatear teléfono
        telefono_limpio = str(telefono).replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        if not telefono_limpio.startswith('58'):
            telefono_limpio = '58' + telefono_limpio.lstrip('0')
        
        # Determinar nivel de urgencia basado en el monto y antigüedad
        from datetime import date
        hoy = date.today()
        factura_mas_antigua = None
        dias_vencimiento = 0
        facturas_vencidas = []
        
        for nota in facturas_pendientes:
            try:
                fecha_nota = datetime.strptime(nota['fecha'], '%Y-%m-%d').date()
                dias = (hoy - fecha_nota).days
                
                # Calcular fecha de vencimiento si es a crédito
                condicion_pago = nota.get('condicion_pago', 'contado')
                if condicion_pago in ['credito', 'crédito', '30 dias', '30 días', '60 dias', '60 días']:
                    if '30' in condicion_pago:
                        fecha_vencimiento = fecha_nota + timedelta(days=30)
                    elif '60' in condicion_pago:
                        fecha_vencimiento = fecha_nota + timedelta(days=60)
                    else:
                        fecha_vencimiento = fecha_nota + timedelta(days=30)  # Por defecto 30 días
                    
                    dias_vencimiento_nota = (hoy - fecha_vencimiento).days
                    if dias_vencimiento_nota > 0:
                        facturas_vencidas.append({
                            'numero': nota['numero'],
                            'dias_vencido': dias_vencimiento_nota,
                            'fecha_vencimiento': fecha_vencimiento.strftime('%Y-%m-%d')
                        })
                
                if dias > dias_vencimiento:
                    dias_vencimiento = dias
                    factura_mas_antigua = nota
            except:
                continue
        
        # Obtener tipo de mensaje del request (si se envía) o determinar automáticamente
        tipo_mensaje_solicitado = data.get('tipo_mensaje', '').upper()
        
        if tipo_mensaje_solicitado in ['URGENTE', 'MEDIO', 'FLEXIBLE']:
            # Usar el tipo solicitado por el usuario
            tipo_mensaje = tipo_mensaje_solicitado
        else:
            # Determinar automáticamente según urgencia
            if total_pendiente > 1000 or dias_vencimiento > 60:
                tipo_mensaje = "URGENTE"
            elif total_pendiente > 500 or dias_vencimiento > 30:
                tipo_mensaje = "MEDIO"
            else:
                tipo_mensaje = "FLEXIBLE"
        
        # Asignar emoji y tono según el tipo
        if tipo_mensaje == "URGENTE":
            emoji_principal = "🚨"
            tono = "urgente"
        elif tipo_mensaje == "MEDIO":
            emoji_principal = "WARNING"
            tono = "medio"
        else:  # FLEXIBLE
            emoji_principal = "💼"
            tono = "flexible"
        
        # Crear mensaje personalizado según el tipo
        if tipo_mensaje == "URGENTE":
            mensaje = f"""{emoji_principal} *RECORDATORIO URGENTE DE PAGO* {emoji_principal}

👋 Hola {cliente.get('nombre', 'Cliente')}

🚨 *ATENCIÓN INMEDIATA REQUERIDA*

📊 *Resumen de Facturas Pendientes:*
• Total de facturas: {len(facturas_pendientes)}
• Monto pendiente: *${total_pendiente:.2f} USD*
• Factura más antigua: {factura_mas_antigua['numero'] if factura_mas_antigua else 'N/A'} ({dias_vencimiento} días)
{f"• Facturas vencidas: {len(facturas_vencidas)} facturas" if facturas_vencidas else ""}

⏰ *Este recordatorio requiere acción inmediata*

🏢 *NOMBRE_DE_EMPRESA*
📍 Centro Comercial Caña de Azúcar (Antiguo Merbumar)
   Nave A, Locales 154-156, Maracay-Edo. Aragua
📧 email@empresa.com
📱 0424-728-6225
🆔 RIF: J-XXXXXXXXX

📞 *Por favor contacta urgentemente para coordinar el pago*

🙏 *Tu pronta respuesta es muy importante*"""
            
        elif tipo_mensaje == "MEDIO":
            mensaje = f"""{emoji_principal} *Recordatorio de Pago* {emoji_principal}

👋 Hola {cliente.get('nombre', 'Cliente')}

📋 *Recordatorio de Facturas Pendientes:*
• Total de facturas: {len(facturas_pendientes)}
• Monto pendiente: *${total_pendiente:.2f} USD*
• Días transcurridos: {dias_vencimiento} días
{f"• Facturas vencidas: {len(facturas_vencidas)} facturas" if facturas_vencidas else ""}

🏢 *NOMBRE_DE_EMPRESA*
📍 Centro Comercial Caña de Azúcar (Antiguo Merbumar)
   Nave A, Locales 154-156, Maracay-Edo. Aragua
📧 email@empresa.com
📱 0424-728-6225
🆔 RIF: J-XXXXXXXXX

📞 *Te invitamos a contactar para coordinar el pago*

⏰ *Es importante regularizar esta situación*"""
            
        else:  # FLEXIBLE
            mensaje = f"""{emoji_principal} *Recordatorio Amigable* {emoji_principal}

👋 Hola {cliente.get('nombre', 'Cliente')}

📋 *Información de Facturas Pendientes:*
• Total de facturas: {len(facturas_pendientes)}
• Monto pendiente: *${total_pendiente:.2f} USD*
{f"• Facturas vencidas: {len(facturas_vencidas)} facturas" if facturas_vencidas else ""}

🏢 *NOMBRE_DE_EMPRESA*
📍 Centro Comercial Caña de Azúcar (Antiguo Merbumar)
   Nave A, Locales 154-156, Maracay-Edo. Aragua
📧 email@empresa.com
📱 0424-728-6225
🆔 RIF: J-XXXXXXXXX

📞 *Cuando puedas, contáctanos para coordinar el pago*

🙏 *Gracias por tu atención*"""
        
        # Generar enlaces
        mensaje_codificado = urllib.parse.quote(mensaje)
        enlace_whatsapp = f"https://wa.me/{telefono_limpio}?text={mensaje_codificado}"
        enlace_web = f"https://web.whatsapp.com/send?phone={telefono_limpio}&text={mensaje_codificado}"
        
        resultado = {
            'success': True,
            'message': f'Recordatorio {tipo_mensaje.lower()} preparado para WhatsApp',
            'enlace_whatsapp': enlace_whatsapp,
            'enlace_web': enlace_web,
            'telefono': telefono,
            'mensaje': mensaje,
            'cliente_nombre': cliente.get('nombre', 'N/A'),
            'total_notas_entrega': len(facturas_pendientes),
            'total_facturado': sum(f['total'] for f in facturas_pendientes),
            'total_abonado': sum(f['abonado'] for f in facturas_pendientes),
            'total_pendiente': total_pendiente,
            'tipo_mensaje': tipo_mensaje,
            'dias_vencimiento': dias_vencimiento,
            'emoji_principal': emoji_principal,
            'tono': tono,
            'facturas_vencidas': facturas_vencidas,
            'total_facturas_vencidas': len(facturas_vencidas)
        }
        
        print(f"✅ Recordatorio {tipo_mensaje} preparado exitosamente para {cliente.get('nombre', 'N/A')}")
        return jsonify(resultado)
        
    except Exception as e:
        print(f"❌ Error en endpoint: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Error: {str(e)}'}), 500

@app.route('/cuentas-por-cobrar')
@login_required
def mostrar_cuentas_por_cobrar():
    """
    Muestra las cuentas por cobrar basadas exclusivamente en notas de entrega.
    Adaptado para trabajar solo con el sistema de notas de entrega.
    """
    notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
    clientes = cargar_datos(ARCHIVO_CLIENTES)
    cuentas = cargar_datos(ARCHIVO_CUENTAS)
    
    filtro = request.args.get('estado', 'por_cobrar')
    filtro_norm = (filtro or '').lower()
    if filtro_norm in ['cobrado', 'cobradas']:
        filtro_norm = 'cobrada'
    if filtro_norm in ['abonadas']:
        filtro_norm = 'abonada'
    
    # Sub-filtros de fecha/cliente y vencidas
    mes_param = request.args.get('mes', '')
    anio_param = request.args.get('anio', '')
    cliente_param = request.args.get('cliente', '').strip()
    solo_vencidas = request.args.get('solo_vencidas', '0') == '1'
    
    try:
        mes_seleccionado = int(mes_param) if mes_param else None
    except Exception:
        mes_seleccionado = None
    try:
        anio_seleccionado = int(anio_param) if anio_param else None
    except Exception:
        anio_seleccionado = None
    
    # Procesar filtro de cliente
    cliente_seleccionado = None
    cliente_nombre_seleccionado = None
    if cliente_param:
        try:
            cliente_seleccionado = cliente_param
            cliente_nombre_seleccionado = clientes.get(cliente_param, {}).get('nombre', cliente_param)
        except Exception:
            cliente_seleccionado = None
            cliente_nombre_seleccionado = None
    
    # Lista de clientes disponibles para el selector
    clientes_disponibles = []
    for cliente_id, cliente_data in clientes.items():
        if isinstance(cliente_data, dict) and 'nombre' in cliente_data:
            clientes_disponibles.append({
                'id': cliente_id,
                'nombre': cliente_data['nombre']
            })
    # Ordenar por nombre
    clientes_disponibles.sort(key=lambda x: x['nombre'].lower())
    
    # Años disponibles para selector
    anios_disponibles = sorted({
        int(f['fecha'].split('-')[0]) for f in notas.values() if f.get('fecha') and '-' in f.get('fecha')
    })
    
    # Variables para cálculos
    cuentas_filtradas = {}
    total_por_cobrar_usd = 0
    total_por_cobrar_bs = 0
    total_facturado_usd = 0
    total_abonado_usd = 0
    display_facturado_usd = 0.0
    display_abonado_usd = 0.0
    display_por_cobrar_usd = 0.0
    tasa_bcv = obtener_tasa_bcv() or 1.0
    clientes_deudores = set()
    
    from datetime import date, datetime as dt
    hoy = date.today()
    
    # Buckets de antigüedad
    buckets = {'0-30': 0.0, '31-60': 0.0, '61-90': 0.0, '90+': 0.0}
    overdue_usd = 0.0
    vencidas_count = 0
    sum_age_weight = 0.0

    # Procesar notas de entrega para cuentas por cobrar
    for id, nota in notas.items():
        # Calcular totales de la nota
        total_usd = safe_float(nota.get('subtotal_usd', 0))
        estado_nota = nota.get('estado', 'PENDIENTE_ENTREGA')
        
        # Determinar estado para cuentas por cobrar basado en la nota
        if estado_nota == 'PAGADA':
            estado = 'cobrada'
            total_abonado = total_usd
            saldo_pendiente = 0
        elif estado_nota == 'ABONADA':
            estado = 'abonada'
            # Calcular abonado basado en pagos
            pagos = nota.get('pagos', [])
            total_abonado = sum(safe_float(pago.get('monto', 0)) for pago in pagos)
            saldo_pendiente = max(total_usd - total_abonado, 0)
        else:  # PENDIENTE_ENTREGA, ENTREGADO, etc.
            estado = 'por_cobrar'
            total_abonado = 0
            saldo_pendiente = total_usd

        # Filtros por mes/año
        fecha_str = nota.get('fecha')
        if (mes_seleccionado or anio_seleccionado) and fecha_str:
            try:
                y, m, _ = fecha_str.split('-')
                if anio_seleccionado and int(y) != anio_seleccionado:
                    continue
                if mes_seleccionado and int(m) != mes_seleccionado:
                    continue
            except Exception:
                continue

        # Aplicar filtro de estado
        include = False
        if filtro_norm == 'todas':
            include = True
        elif filtro_norm == 'abonada':
            include = (estado == 'abonada')
        elif filtro_norm == 'cobrada':
            include = (estado == 'cobrada')
        elif filtro_norm == 'por_cobrar':
            include = (estado == 'por_cobrar')
        else:
            include = (filtro_norm == estado)

        # Filtro por cliente
        if include and cliente_param:
            if str(nota.get('cliente_id', '')) != cliente_param:
                include = False

        if include:
            # Calcular edad y días vencidos
            dias_emision = 0
            dias_vencidos = 0
            if fecha_str:
                try:
                    dias_emision = (hoy - dt.strptime(fecha_str, '%Y-%m-%d').date()).days
                except Exception:
                    dias_emision = 0
            
            fecha_vencimiento = nota.get('fecha_vencimiento', '')
            if fecha_vencimiento:
                try:
                    dias_vencidos = (hoy - dt.strptime(fecha_vencimiento, '%Y-%m-%d').date()).days
                except Exception:
                    dias_vencidos = 0

            cuentas_filtradas[id] = {
                'factura_id': id,
                'numero': nota.get('numero', id),
                'cliente_id': nota.get('cliente_id'),
                'cliente_nombre': clientes.get(nota.get('cliente_id'), {}).get('nombre', nota.get('cliente_id')),
                'total_usd': total_usd,
                'abonado_usd': total_abonado,
                'saldo_pendiente': saldo_pendiente,
                'estado': estado,
                'fecha': fecha_str,
                'condicion_pago': nota.get('condicion_pago', ''),
                'fecha_vencimiento': fecha_vencimiento,
                'edad_dias': dias_emision,
                'dias_vencidos': max(dias_vencidos, 0),
                'tipo_documento': 'Nota de Entrega',
                'nota_entrega_id': id
            }
            
            # Acumular totales
            display_facturado_usd += total_usd
            display_abonado_usd += total_abonado
            display_por_cobrar_usd += saldo_pendiente
            total_facturado_usd += total_usd
            total_abonado_usd += total_abonado

            # Procesar cuentas con saldo pendiente
            if estado in ['por_cobrar', 'abonada'] and saldo_pendiente > 0:
                total_por_cobrar_usd += saldo_pendiente
                clientes_deudores.add(nota.get('cliente_id'))
                
                if dias_vencidos > 0:
                    overdue_usd += saldo_pendiente
                    vencidas_count += 1
                    if dias_vencidos <= 30:
                        buckets['0-30'] += saldo_pendiente
                    elif dias_vencidos <= 60:
                        buckets['31-60'] += saldo_pendiente
                    elif dias_vencidos <= 90:
                        buckets['61-90'] += saldo_pendiente
                    else:
                        buckets['90+'] += saldo_pendiente
                    sum_age_weight += dias_vencidos * saldo_pendiente

    # Aplicar sub-filtro: solo vencidas
    if filtro == 'por_cobrar' and solo_vencidas:
        cuentas_filtradas = {
            k: v for k, v in cuentas_filtradas.items()
            if v.get('estado') == 'por_cobrar' and v.get('dias_vencidos', 0) > 0
        }

    # Calcular totales en bolívares
    total_por_cobrar_bs = total_por_cobrar_usd * tasa_bcv
    total_facturado_bs = total_facturado_usd * tasa_bcv
    total_abonado_bs = total_abonado_usd * tasa_bcv
    
    # Contar facturas filtradas
    cantidad_facturas = len(cuentas_filtradas)
    
    # Calcular KPIs específicos por filtro
    kpis = {}
    no_vencida_usd = total_por_cobrar_usd - overdue_usd
    
    if filtro_norm == 'por_cobrar':
        count_pc = len([c for c in cuentas_filtradas.values() if c['estado'] == 'por_cobrar'])
        # Concentración Top 5 deudores
        agg_pc = {}
        for c in cuentas_filtradas.values():
            if c['estado'] == 'por_cobrar' and c['saldo_pendiente'] > 0:
                cid = c['cliente_id']
                agg_pc[cid] = agg_pc.get(cid, 0.0) + c['saldo_pendiente']
        top5_sum = sum(v for _, v in sorted(agg_pc.items(), key=lambda x: x[1], reverse=True)[:5])
        conc_top5 = round((top5_sum / total_por_cobrar_usd) * 100, 1) if total_por_cobrar_usd > 0 else 0.0
        ticket_pc = round((total_por_cobrar_usd / count_pc), 2) if count_pc > 0 else 0.0
        kpis.update({
            'saldo_vencido_usd': round(overdue_usd, 2),
            'saldo_no_vencido_usd': round(no_vencida_usd, 2),
            'ticket_promedio_usd': ticket_pc,
            'concentracion_top5': conc_top5
        })
    elif filtro_norm == 'abonada':
        abonadas = [c for c in cuentas_filtradas.values() if c['estado'] == 'abonada']
        total_abonado_set = sum(c['total_usd'] - c['saldo_pendiente'] for c in abonadas)
        saldo_pendiente_set = sum(c['saldo_pendiente'] for c in abonadas)
        facturado_set = sum(c['total_usd'] for c in abonadas)
        avg_abonado_set = round((total_abonado_set / len(abonadas)), 2) if abonadas else 0.0
        progreso = round((total_abonado_set / facturado_set) * 100, 1) if facturado_set > 0 else 0.0
        kpis.update({
            'total_abonado_set': round(total_abonado_set, 2),
            'saldo_pendiente_set': round(saldo_pendiente_set, 2),
            'promedio_abonado_set': avg_abonado_set,
            'progreso_recuperacion': progreso
        })
    elif filtro_norm == 'cobrada':
        cobradas = [c for c in cuentas_filtradas.values() if c['estado'] == 'cobrada']
        total_pagado_set = sum(c['total_usd'] for c in cobradas)
        avg_pagado_set = round((total_pagado_set / len(cobradas)), 2) if cobradas else 0.0
        # Concentración Top1
        agg_cb = {}
        for c in cobradas:
            cid = c['cliente_id']
            agg_cb[cid] = agg_cb.get(cid, 0.0) + c['total_usd']
        if agg_cb:
            top1_monto = max(agg_cb.values())
            conc_top1 = round((top1_monto / total_pagado_set) * 100, 1) if total_pagado_set > 0 else 0.0
        else:
            conc_top1 = 0.0
        kpis.update({
            'total_pagado_set': round(total_pagado_set, 2),
            'promedio_pagado_set': avg_pagado_set,
            'concentracion_top1': conc_top1
        })

    # Generar datos para gráficas
    grafica_barras = {
        'labels': ['Facturado', 'Abonado', 'Por Cobrar'],
        'data': [display_facturado_usd, display_abonado_usd, display_por_cobrar_usd],
        'facturas': [cantidad_facturas, cantidad_facturas, cantidad_facturas],
        'avg': [display_facturado_usd/cantidad_facturas if cantidad_facturas > 0 else 0, 
                display_abonado_usd/cantidad_facturas if cantidad_facturas > 0 else 0, 
                display_por_cobrar_usd/cantidad_facturas if cantidad_facturas > 0 else 0]
    }
    
    # Gráfica de pastel - Top deudores
    top_deudores = []
    if filtro_norm == 'por_cobrar':
        agg_deudores = {}
        for c in cuentas_filtradas.values():
            if c['estado'] == 'por_cobrar' and c['saldo_pendiente'] > 0:
                cid = c['cliente_id']
                agg_deudores[cid] = agg_deudores.get(cid, 0.0) + c['saldo_pendiente']
        top_deudores = [{'cliente_id': cid, 'cliente': clientes.get(cid, {}).get('nombre', cid), 'monto': monto} 
                       for cid, monto in sorted(agg_deudores.items(), key=lambda x: x[1], reverse=True)[:5]]
    elif filtro_norm in ['abonada', 'cobrada']:
        agg_clientes = {}
        for c in cuentas_filtradas.values():
            cid = c['cliente_id']
            if cid not in agg_clientes:
                agg_clientes[cid] = {'total_facturado': 0, 'abonado_usd': 0, 'facturas': 0}
            agg_clientes[cid]['total_facturado'] += c['total_usd']
            agg_clientes[cid]['abonado_usd'] += c['abonado_usd']
            agg_clientes[cid]['facturas'] += 1
        
        for cid, data in agg_clientes.items():
            data['participacion'] = round((data['abonado_usd'] / display_abonado_usd) * 100, 1) if display_abonado_usd > 0 else 0
            data['ticket_promedio'] = round(data['abonado_usd'] / data['facturas'], 2) if data['facturas'] > 0 else 0
        
        top_deudores = [{'cliente_id': cid, 'cliente': clientes.get(cid, {}).get('nombre', cid), **data} 
                       for cid, data in sorted(agg_clientes.items(), key=lambda x: x[1]['abonado_usd'], reverse=True)[:10]]

    # Gráfica de pastel
    if top_deudores:
        grafica_pastel = {
            'labels': [d['cliente'] for d in top_deudores],
            'data': [d['monto'] for d in top_deudores]
        }
    else:
        grafica_pastel = {'labels': [], 'data': []}

    # Gráfica de antigüedad
    grafica_antiguedad = {
        'labels': ['No Vencida', '0-30 días', '31-60 días', '61-90 días', '90+ días'],
        'data': [
            no_vencida_usd,
            buckets['0-30'],
            buckets['31-60'],
            buckets['61-90'],
            buckets['90+']
        ]
    }

    # Resumen para estado cobradas
    resumen_cobradas = None
    if filtro_norm == 'cobrada' and cuentas_filtradas:
        cobradas = [c for c in cuentas_filtradas.values() if c['estado'] == 'cobrada']
        if cobradas:
            montos = [c['total_usd'] for c in cobradas]
            resumen_cobradas = {
                'facturas': len(cobradas),
                'ticket_promedio': round(sum(montos) / len(montos), 2),
                'cliente_top': max(cobradas, key=lambda x: x['total_usd'])['cliente_nombre'],
                'monto_top': max(montos),
                'min_pagado': min(montos),
                'max_pagado': max(montos),
                'mediana_pagado': sorted(montos)[len(montos)//2] if montos else 0,
                'ultima_cobranza': max(c['fecha'] for c in cobradas if c['fecha'])
            }

    total_por_cobrar_bs = total_por_cobrar_usd * tasa_bcv
    total_facturado_bs = total_facturado_usd * tasa_bcv
    total_abonado_bs = total_abonado_usd * tasa_bcv
    # Contar directamente lo filtrado; en 'abonada' incluye abonadas y cobradas con abonos
    cantidad_notas = len(cuentas_filtradas)
    no_vencidas_count = max(cantidad_notas - vencidas_count, 0)
    cantidad_clientes = len(clientes_deudores)
    promedio_por_nota = total_por_cobrar_usd / cantidad_notas if cantidad_notas > 0 else 0
    # Top según filtro (deudores o buen pagador)
    if (request.args.get('estado','por_cobrar') in ['abonada','abonadas','cobrada','cobradas']):
        agreg = {}
        if filtro_norm == 'cobrada':
            for c in cuentas_filtradas.values():
                if c['estado'] == 'cobrada':
                    cid = c['cliente_id']
                    entry = agreg.get(cid, {'abonado_usd': 0.0, 'total_facturado': 0.0, 'facturas': 0})
                    abonado = c['total_usd']
                    entry['abonado_usd'] += abonado
                    entry['total_facturado'] += c['total_usd']
                    entry['facturas'] += 1
                    agreg[cid] = entry
            total_base = sum(v['abonado_usd'] for v in agreg.values()) or 1.0
            top_pairs = sorted(agreg.items(), key=lambda x: x[1]['abonado_usd'], reverse=True)[:10]
            top_deudores = [{
                'cliente_id': cid,
                'cliente': clientes.get(cid, {}).get('nombre', cid),
                'abonado_usd': data['abonado_usd'],
                'total_facturado': data['total_facturado'],
                'facturas': data['facturas'],
                'participacion': round((data['abonado_usd'] / total_base) * 100, 1),
                'ticket_promedio': round((data['abonado_usd'] / data['facturas']), 2) if data['facturas'] > 0 else 0.0
            } for cid, data in top_pairs]
        else:  # abonada
            for c in cuentas_filtradas.values():
                if c['estado'] == 'abonada':
                    cid = c['cliente_id']
                    entry = agreg.get(cid, {'abonado_usd': 0.0, 'total_facturado': 0.0, 'facturas': 0})
                    entry['abonado_usd'] += c['abonado_usd']
                    entry['total_facturado'] += c['total_usd']
                    entry['facturas'] += 1
                    agreg[cid] = entry
            total_base = sum(v['abonado_usd'] for v in agreg.values()) or 1.0
            top_pairs = sorted(agreg.items(), key=lambda x: x[1]['abonado_usd'], reverse=True)[:10]
            top_deudores = [{
                'cliente_id': cid,
                'cliente': clientes.get(cid, {}).get('nombre', cid),
                'abonado_usd': data['abonado_usd'],
                'total_facturado': data['total_facturado'],
                'facturas': data['facturas'],
                'participacion': round((data['abonado_usd'] / total_base) * 100, 1),
                'ticket_promedio': round((data['abonado_usd'] / data['facturas']), 2) if data['facturas'] > 0 else 0.0
            } for cid, data in top_pairs]
    else:
        deudores = {}
        deudores_count = {}
        total_pendiente_set = 0.0
        for c in cuentas_filtradas.values():
            if c['estado'] == 'por_cobrar' and c['saldo_pendiente'] > 0:
                cid = c['cliente_id']
                deudores[cid] = deudores.get(cid, 0.0) + c['saldo_pendiente']
                deudores_count[cid] = deudores_count.get(cid, 0) + 1
                total_pendiente_set += c['saldo_pendiente']
        top_pairs = sorted(deudores.items(), key=lambda x: x[1], reverse=True)[:5]
        top_deudores = [
            {
                'cliente_id': cid,
                'cliente': clientes.get(cid, {}).get('nombre', cid),
                'monto': monto,
                'participacion': round(((monto / (total_pendiente_set or 1.0)) * 100), 1),
                'facturas': deudores_count.get(cid, 0),
                'ticket_promedio': round((monto / deudores_count.get(cid, 1)), 2)
            }
            for cid, monto in top_pairs
        ]
    # Datos mínimos para gráficas
    monto_cobrado = sum(c['total_usd'] - c['saldo_pendiente'] for c in cuentas_filtradas.values() if c['estado'] == 'cobrada')
    if (request.args.get('estado','por_cobrar') in ['abonada','abonadas','cobrada','cobradas']):
        resumen_cobradas = None
        if filtro_norm == 'cobrada':
            total_pagado = sum(c['total_usd'] for c in cuentas_filtradas.values())
            count_filtrado = len(cuentas_filtradas)
            avg_pagado = round(total_pagado / count_filtrado, 2) if count_filtrado > 0 else 0.0
            barras = {
                'labels': ['Pagado', 'Facturado'],
                'data': [round(total_pagado, 2), round(total_pagado, 2)],
                'facturas': [count_filtrado, count_filtrado],
                'avg': [avg_pagado, avg_pagado]
            }
            # Top cliente buena paga
            # Reutilizar agreg calculado arriba en la rama cobradas
            try:
                top_pairs_tmp = []
                agreg_tmp = {}
                for c in cuentas_filtradas.values():
                    cid = c['cliente_id']
                    entry = agreg_tmp.get(cid, {'pagado': 0.0})
                    entry['pagado'] += c['total_usd']
                    agreg_tmp[cid] = entry
                top_pairs_tmp = sorted(agreg_tmp.items(), key=lambda x: x[1]['pagado'], reverse=True)
                # Estadísticas adicionales cobradas
                montos = [c['total_usd'] for c in cuentas_filtradas.values()]
                montos_sorted = sorted(montos)
                min_pagado = round(montos_sorted[0], 2) if montos_sorted else 0.0
                max_pagado = round(montos_sorted[-1], 2) if montos_sorted else 0.0
                med_pagado = 0.0
                if montos_sorted:
                    n = len(montos_sorted)
                    mid = n // 2
                    if n % 2 == 1:
                        med_pagado = round(montos_sorted[mid], 2)
                    else:
                        med_pagado = round((montos_sorted[mid - 1] + montos_sorted[mid]) / 2.0, 2)
                # Última cobranza (por fecha de pago)
                ultima_cobranza = ''
                try:
                    fechas = []
                    for fid in cuentas_filtradas.keys():
                        f = notas.get(fid, {})
                        for p in f.get('pagos', []) or []:
                            pf = p.get('fecha', '')
                            if pf:
                                try:
                                    fechas.append(dtd.strptime(pf[:19], '%Y-%m-%d %H:%M:%S'))
                                except Exception:
                                    pass
                    if fechas:
                        ultima_cobranza = max(fechas).strftime('%Y-%m-%d %H:%M:%S')
                except Exception:
                    ultima_cobranza = ''
                if top_pairs_tmp:
                    top_cid, top_data = top_pairs_tmp[0]
                    resumen_cobradas = {
                        'facturas': count_filtrado,
                        'ticket_promedio': avg_pagado,
                        'cliente_top': clientes.get(top_cid, {}).get('nombre', top_cid),
                        'monto_top': round(top_data['pagado'], 2),
                        'min_pagado': min_pagado,
                        'max_pagado': max_pagado,
                        'mediana_pagado': med_pagado,
                        'ultima_cobranza': ultima_cobranza
                    }
                else:
                    resumen_cobradas = {
                        'facturas': count_filtrado,
                        'ticket_promedio': avg_pagado,
                        'cliente_top': '-',
                        'monto_top': 0.0,
                        'min_pagado': 0.0,
                        'max_pagado': 0.0,
                        'mediana_pagado': 0.0,
                        'ultima_cobranza': ''
                    }
            except Exception:
                resumen_cobradas = {
                    'facturas': count_filtrado,
                    'ticket_promedio': avg_pagado,
                    'cliente_top': '-',
                    'monto_top': 0.0,
                    'min_pagado': 0.0,
                    'max_pagado': 0.0,
                    'mediana_pagado': 0.0,
                    'ultima_cobranza': ''
                }
        else:
            total_abonado_filtrado = sum(c['total_usd'] - c['saldo_pendiente'] for c in cuentas_filtradas.values())
            count_filtrado = len(cuentas_filtradas)
            avg_abonado = round(total_abonado_filtrado / count_filtrado, 2) if count_filtrado > 0 else 0.0
            barras = {
                'labels': ['Abonado', 'Facturado'],
                'data': [round(total_abonado_filtrado, 2),
                         round(sum(c['total_usd'] for c in cuentas_filtradas.values()), 2)],
                'facturas': [count_filtrado, count_filtrado],
                'avg': [avg_abonado, avg_abonado]
            }
        agg = {}
        for c in cuentas_filtradas.values():
            client_name = clientes.get(c['cliente_id'], {}).get('nombre', c['cliente_id'])
            # Para abonadas/cobradas, sumar abonado efectivo
            agg[client_name] = agg.get(client_name, 0) + (c['total_usd'] - c['saldo_pendiente'])
        labels = list(agg.keys())[:8]
        data = [agg[k] for k in labels]
        pastel = { 'labels': labels, 'data': data }
    else:
        # Por cobrar: barras detalladas Por cobrar vs Vencida vs No vencida + promedios
        count_por_cobrar = len([c for c in cuentas_filtradas.values() if c['estado'] == 'por_cobrar'])
        no_vencida_usd = max(total_por_cobrar_usd - overdue_usd, 0.0)
        no_vencidas_count = max(count_por_cobrar - vencidas_count, 0)
        avg_por_cobrar = round(total_por_cobrar_usd / count_por_cobrar, 2) if count_por_cobrar > 0 else 0.0
        avg_vencida = round(overdue_usd / vencidas_count, 2) if vencidas_count > 0 else 0.0
        avg_no_vencida = round(no_vencida_usd / no_vencidas_count, 2) if no_vencidas_count > 0 else 0.0
        barras = {
            'labels': ['Por cobrar', 'Vencida', 'No vencida'],
            'data': [round(total_por_cobrar_usd, 2), round(overdue_usd, 2), round(no_vencida_usd, 2)],
            'facturas': [count_por_cobrar, vencidas_count, no_vencidas_count],
            'avg': [avg_por_cobrar, avg_vencida, avg_no_vencida]
        }
        # Pastel: Top deudores por saldo pendiente
        agg = {}
        for c in cuentas_filtradas.values():
            if c['estado'] == 'por_cobrar' and c['saldo_pendiente'] > 0:
                name = clientes.get(c['cliente_id'], {}).get('nombre', c['cliente_id'])
                agg[name] = agg.get(name, 0) + c['saldo_pendiente']
        labels = sorted(agg.keys(), key=lambda k: agg[k], reverse=True)[:8]
        data = [agg[k] for k in labels]
        pastel = { 'labels': labels, 'data': data }

    no_vencida_usd = max(total_por_cobrar_usd - overdue_usd, 0.0)
    antiguedad = {
        'labels': ['No vencida','0-30', '31-60', '61-90', '90+'],
        'data': [round(no_vencida_usd,2), round(buckets['0-30'],2), round(buckets['31-60'],2), round(buckets['61-90'],2), round(buckets['90+'],2)]
    }

    dso = round((sum_age_weight / total_por_cobrar_usd), 1) if total_por_cobrar_usd > 0 else 0.0
    porc_recuperado = round((total_abonado_usd / total_facturado_usd) * 100, 1) if total_facturado_usd > 0 else 0.0
    porc_vencido = round((overdue_usd / total_por_cobrar_usd) * 100, 1) if total_por_cobrar_usd > 0 else 0.0

    no_vencida_usd = max(total_por_cobrar_usd - overdue_usd, 0.0)

    # KPIs dinámicos por estado
    kpis = {'tipo': filtro_norm}
    if filtro_norm == 'por_cobrar':
        count_pc = len([c for c in cuentas_filtradas.values() if c['estado'] == 'por_cobrar'])
        # Concentración Top 5 deudores
        agg_pc = {}
        for c in cuentas_filtradas.values():
            if c['estado'] == 'por_cobrar' and c['saldo_pendiente'] > 0:
                cid = c['cliente_id']
                agg_pc[cid] = agg_pc.get(cid, 0.0) + c['saldo_pendiente']
        top5_sum = sum(v for _, v in sorted(agg_pc.items(), key=lambda x: x[1], reverse=True)[:5])
        conc_top5 = round((top5_sum / total_por_cobrar_usd) * 100, 1) if total_por_cobrar_usd > 0 else 0.0
        ticket_pc = round((total_por_cobrar_usd / count_pc), 2) if count_pc > 0 else 0.0
        kpis.update({
            'saldo_vencido_usd': round(overdue_usd, 2),
            'saldo_no_vencido_usd': round(no_vencida_usd, 2),
            'ticket_promedio_usd': ticket_pc,
            'concentracion_top5': conc_top5
        })
    elif filtro_norm == 'abonada':
        abonadas = [c for c in cuentas_filtradas.values() if c['estado'] == 'abonada']
        total_abonado_set = sum(c['total_usd'] - c['saldo_pendiente'] for c in abonadas)
        saldo_pendiente_set = sum(c['saldo_pendiente'] for c in abonadas)
        facturado_set = sum(c['total_usd'] for c in abonadas)
        avg_abonado_set = round((total_abonado_set / len(abonadas)), 2) if abonadas else 0.0
        progreso = round((total_abonado_set / facturado_set) * 100, 1) if facturado_set > 0 else 0.0
        kpis.update({
            'total_abonado_set': round(total_abonado_set, 2),
            'saldo_pendiente_set': round(saldo_pendiente_set, 2),
            'promedio_abonado_set': avg_abonado_set,
            'progreso_recuperacion': progreso
        })
    elif filtro_norm == 'cobrada':
        cobradas = [c for c in cuentas_filtradas.values() if c['estado'] == 'cobrada']
        total_pagado_set = sum(c['total_usd'] for c in cobradas)
        avg_pagado_set = round((total_pagado_set / len(cobradas)), 2) if cobradas else 0.0
        # Concentración Top1
        agg_cb = {}
        for c in cobradas:
            cid = c['cliente_id']
            agg_cb[cid] = agg_cb.get(cid, 0.0) + c['total_usd']
        if agg_cb:
            top1_monto = max(agg_cb.values())
            conc_top1 = round((top1_monto / total_pagado_set) * 100, 1) if total_pagado_set > 0 else 0.0
        else:
            conc_top1 = 0.0
        kpis.update({
            'total_pagado_set': round(total_pagado_set, 2),
            'promedio_pagado_set': avg_pagado_set,
            'concentracion_top1': conc_top1
        })

    return render_template('cuentas_por_cobrar_moderno.html',
        cuentas=cuentas_filtradas,
        clientes=clientes,
        notas=notas,
        filtro=filtro,
        mes_seleccionado=mes_seleccionado,
        anio_seleccionado=anio_seleccionado,
        anios_disponibles=anios_disponibles,
        solo_vencidas=solo_vencidas,
        cliente_seleccionado=cliente_seleccionado,
        cliente_nombre_seleccionado=cliente_nombre_seleccionado,
        clientes_disponibles=clientes_disponibles,
        total_por_cobrar_usd=total_por_cobrar_usd,
        total_por_cobrar_bs=total_por_cobrar_bs,
        tasa_bcv=tasa_bcv,
        total_facturado_usd=total_facturado_usd,
        total_facturado_bs=total_facturado_bs,
        total_abonado_usd=total_abonado_usd,
        total_abonado_bs=total_abonado_bs,
        cantidad_facturas=cantidad_facturas,
        vencidas_count=vencidas_count,
        no_vencidas_count=len([c for c in cuentas_filtradas.values() if c.get('dias_vencidos', 0) <= 0]),
        display_facturado_usd=display_facturado_usd,
        display_abonado_usd=display_abonado_usd,
        display_por_cobrar_usd=display_por_cobrar_usd,
        cantidad_clientes=len(clientes_deudores),
        promedio_por_factura=round(display_facturado_usd / cantidad_facturas, 2) if cantidad_facturas > 0 else 0,
        top_deudores=top_deudores,
        grafica_barras=grafica_barras,
        grafica_pastel=grafica_pastel,
        grafica_antiguedad=grafica_antiguedad,
        dso=round(sum_age_weight / total_por_cobrar_usd, 1) if total_por_cobrar_usd > 0 else 0,
        porcentaje_recuperado=round((total_abonado_usd / total_facturado_usd) * 100, 1) if total_facturado_usd > 0 else 0,
        porcentaje_vencido=round((overdue_usd / total_por_cobrar_usd) * 100, 1) if total_por_cobrar_usd > 0 else 0,
        vencido_usd=overdue_usd,
        no_vencida_usd=no_vencida_usd,
        resumen_cobradas=resumen_cobradas,
        kpis=kpis,
        buckets=buckets
    )

@app.route('/api/pagos-filtrados')
@login_required
def api_pagos_filtrados():
    """API para obtener pagos recibidos filtrados por período"""
    try:
        periodo = request.args.get('periodo', 'todos')
        print(f"Filtrando pagos para período: {periodo}")
        
        notas_data = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        print(f"Tipo de datos cargados: {type(notas_data)}")
        
        # Convertir diccionario a lista si es necesario
        if isinstance(notas_data, dict):
            notas = list(notas_data.values())
        else:
            notas = notas_data
            
        print(f"Total de notas cargadas: {len(notas)}")
        
        pagos = []
        total_usd = 0
        total_bs = 0
        
        # Obtener tasa BCV actual
        tasa_bcv = None
        try:
            r = requests.get('https://s3.amazonaws.com/dolartoday/data.json', timeout=5)
            data = r.json()
            tasa_bcv = safe_float(data['USD']['bcv']) if 'USD' in data and 'bcv' in data['USD'] else None
        except:
            tasa_bcv = 36.5  # Tasa por defecto
        
        hoy = datetime.now().date()
        
        for nota in notas:
            if nota.get('estado', '').lower() == 'pagada' and nota.get('pagos'):
                try:
                    # Obtener la fecha del último pago
                    pagos_nota = nota.get('pagos', [])
                    if pagos_nota:
                        ultimo_pago = pagos_nota[-1]  # Último pago de la lista
                        fecha_pago_str = ultimo_pago.get('fecha', '')
                    else:
                        fecha_pago_str = ''
                    
                    if fecha_pago_str:
                        # Convertir fecha del pago (formato: '2025-09-21 22:58:12')
                        fecha_pago = datetime.strptime(fecha_pago_str.split(' ')[0], '%Y-%m-%d').date()
                        
                        # Aplicar filtro según el período
                        incluir = False
                        if periodo == 'hoy':
                            incluir = fecha_pago == hoy
                        elif periodo == 'semana':
                            inicio_semana = hoy - timedelta(days=hoy.weekday())
                            incluir = fecha_pago >= inicio_semana and fecha_pago <= hoy
                        elif periodo == 'mes':
                            inicio_mes = hoy.replace(day=1)
                            incluir = fecha_pago >= inicio_mes and fecha_pago <= hoy
                        elif periodo == 'todos':
                            incluir = True
                        
                        if incluir:
                            monto_usd = safe_float(nota.get('total_usd', 0))
                            monto_bs = safe_float(nota.get('total_bs', 0))
                            total_usd += monto_usd
                            total_bs += monto_bs
                            pagos.append(nota)
                            print(f"Incluido: ID {nota.get('id')}, Fecha: {fecha_pago}, USD: {monto_usd}, Bs: {monto_bs}")
                            
                except (ValueError, KeyError, IndexError) as e:
                    print(f"Error procesando nota {nota.get('id', 'N/A')}: {e}")
                    continue
        
        # También incluir pagos del archivo pagos_recibidos.json
        try:
            pagos_recibidos = cargar_datos(ARCHIVO_PAGOS_RECIBIDOS)
            if pagos_recibidos and isinstance(pagos_recibidos, dict):
                for pago_id, pago in pagos_recibidos.items():
                    if not isinstance(pago, dict):
                        continue
                    
                    fecha_pago_str = pago.get('fecha', '')
                    if not fecha_pago_str:
                        continue
                    
                    try:
                        # Parsear fecha (puede estar en formato 'YYYY-MM-DD' o 'DD/MM/YYYY')
                        fecha_pago = None
                        if '-' in fecha_pago_str:
                            fecha_pago = datetime.strptime(fecha_pago_str.split(' ')[0], '%Y-%m-%d').date()
                        elif '/' in fecha_pago_str:
                            fecha_pago = datetime.strptime(fecha_pago_str, '%d/%m/%Y').date()
                        else:
                            continue
                        
                        # Aplicar filtro según el período
                        incluir = False
                        if periodo == 'hoy':
                            incluir = fecha_pago == hoy
                        elif periodo == 'semana':
                            inicio_semana = hoy - timedelta(days=hoy.weekday())
                            incluir = fecha_pago >= inicio_semana and fecha_pago <= hoy
                        elif periodo == 'mes':
                            inicio_mes = hoy.replace(day=1)
                            incluir = fecha_pago >= inicio_mes and fecha_pago <= hoy
                        elif periodo == 'todos':
                            incluir = True
                        
                        if incluir:
                            monto_usd = safe_float(pago.get('monto_usd', 0))
                            monto_bs = safe_float(pago.get('monto_bs', 0))
                            
                            # Si no tiene monto_bs, calcularlo usando tasa_bcv
                            if monto_bs == 0 and monto_usd > 0:
                                tasa_pago = safe_float(pago.get('tasa_bcv', tasa_bcv))
                                monto_bs = monto_usd * tasa_pago
                            
                            total_usd += monto_usd
                            total_bs += monto_bs
                            pagos.append(pago)
                            print(f"Incluido pago recibido: ID {pago_id}, Fecha: {fecha_pago}, USD: {monto_usd}, Bs: {monto_bs}")
                    except (ValueError, TypeError) as e:
                        print(f"Error procesando pago recibido {pago_id}: {e}")
                        continue
        except Exception as e:
            print(f"Error cargando pagos recibidos en filtrado: {e}")
        
        # Formatear números usando la función existente
        total_usd_formatted = es_number(total_usd)
        total_bs_formatted = es_number(total_bs)
        
        print(f"Pagos encontrados (notas + recibidos): {len(pagos)}, Total USD: {total_usd}, Total Bs: {total_bs}")
        
        return jsonify({
            'success': True,
            'total_usd': total_usd_formatted,
            'total_bs': total_bs_formatted,
            'periodo': periodo,
            'cantidad_pagos': len(pagos)
        })
        
    except Exception as e:
        print(f"Error en API pagos-filtrados: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e),
            'total_usd': '0,00',
            'total_bs': '0,00',
            'periodo': request.args.get('periodo', 'todos'),
            'cantidad_pagos': 0
        })

@app.route('/api/cobranza-filtrada')
@login_required
def api_cobranza_filtrada():
    """API para obtener cuentas por cobrar filtradas por período"""
    try:
        periodo = request.args.get('periodo', 'todos')
        print(f"Filtrando cobranza para período: {periodo}")
        
        notas_data = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        print(f"Tipo de datos cargados: {type(notas_data)}")
        
        # Convertir diccionario a lista si es necesario
        if isinstance(notas_data, dict):
            notas = list(notas_data.values())
        else:
            notas = notas_data
            
        print(f"Total de notas cargadas: {len(notas)}")
        
        cobranza = []
        total_usd = 0
        total_bs = 0
        
        hoy = datetime.now().date()
        
        for nota in notas:
            if nota.get('estado', '').lower() in ['pendiente', 'por_cobrar', 'credito']:
                try:
                    fecha_factura_str = nota.get('fecha', '')
                    
                    if fecha_factura_str:
                        fecha_nota = datetime.strptime(fecha_factura_str, '%Y-%m-%d').date()
                        
                        # Aplicar filtro según el período
                        incluir = False
                        if periodo == 'hoy':
                            incluir = fecha_nota == hoy
                        elif periodo == 'semana':
                            inicio_semana = hoy - timedelta(days=hoy.weekday())
                            incluir = fecha_nota >= inicio_semana and fecha_nota <= hoy
                        elif periodo == 'mes':
                            inicio_mes = hoy.replace(day=1)
                            incluir = fecha_nota >= inicio_mes and fecha_nota <= hoy
                        elif periodo == 'todos':
                            incluir = True
                        
                        if incluir:
                            monto_usd = safe_float(nota.get('total_usd', 0))
                            monto_bs = safe_float(nota.get('total_bs', 0))
                            total_usd += monto_usd
                            total_bs += monto_bs
                            cobranza.append(nota)
                            print(f"Incluido: ID {nota.get('id')}, Fecha: {fecha_factura}, USD: {monto_usd}, Bs: {monto_bs}")
                            
                except (ValueError, KeyError) as e:
                    print(f"Error procesando nota {nota.get('id', 'N/A')}: {e}")
                    continue
        
        # Formatear números usando la función existente
        total_usd_formatted = es_number(total_usd)
        total_bs_formatted = es_number(total_bs)
        
        print(f"Cobranza encontrada: {len(cobranza)}, Total USD: {total_usd}, Total Bs: {total_bs}")
        
        return jsonify({
            'success': True,
            'total_usd': total_usd_formatted,
            'total_bs': total_bs_formatted,
            'periodo': periodo,
            'cantidad_notas': len(cobranza)
        })
        
    except Exception as e:
        print(f"Error en API cobranza-filtrada: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e),
            'total_usd': '0,00',
            'total_bs': '0,00',
            'periodo': request.args.get('periodo', 'todos'),
            'cantidad_notas': 0
        })


@app.template_filter('split')
def split_filter(value, delimiter=' '):
    """Filtro personalizado para dividir strings"""
    return value.split(delimiter)

@app.route('/inventario/')
def inventario_slash_redirect():
    return redirect(url_for('mostrar_inventario'))

@app.route('/qr/<id>')
def mostrar_stock_qr(id):
    """Mostrar información de stock cuando se escanea el QR"""
    inventario = cargar_datos(ARCHIVO_INVENTARIO)
    
    if id not in inventario:
        return render_template('qr_error.html', mensaje="Producto no encontrado")
    
    producto = inventario[id]
    
    # Información básica del producto
    info_producto = {
        'id': id,
        'nombre': producto.get('nombre', 'Sin nombre'),
        'categoria': producto.get('categoria', 'Sin categoría'),
        'tipo': producto.get('tipo', 'piezas'),
        'precio': safe_float(producto.get('precio', 0)),
        'cantidad': int(producto.get('cantidad', 0)),
        'stock_bajo': int(producto.get('cantidad', 0)) < 5
    }
    
    return render_template('qr_stock.html', producto=info_producto)





@app.route('/login', methods=['GET', 'POST'])
@csrf.exempt
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        if not username or not password:
            flash('Por favor ingrese usuario y contraseña', 'warning')
            return render_template('login.html')
        
        if verify_password(username, password):
            session['usuario'] = username
            registrar_bitacora(username, 'Inicio de sesión', 'Inicio de sesión exitoso')
            flash('Bienvenido al sistema', 'success')
            return redirect(url_for('index'))
        else:
            registrar_bitacora(username, 'Intento fallido', 'Intento fallido de inicio de sesión')
            flash('Usuario o contraseña incorrectos', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    usuario = session.get('usuario', 'desconocido')
    registrar_bitacora(usuario, 'Cierre de sesión', 'Sesión finalizada')
    session.pop('usuario', None)
    flash('Sesión cerrada exitosamente', 'info')
    return redirect(url_for('login'))

@app.route('/bitacora')
@login_required
def ver_bitacora():
    try:
        with open('bitacora.log', 'r', encoding='utf-8') as f:
            lineas = f.readlines()
    except Exception:
        lineas = []
    # Obtener filtros
    filtro_accion = request.args.get('accion', '')
    filtro_fecha = request.args.get('fecha', '')
    # Extraer acciones únicas
    acciones_unicas = set()
    for linea in lineas:
        partes = linea.strip().split('] ', 1)
        if len(partes) == 2:
            resto = partes[1].split(' | ')
            if len(resto) > 1:
                accion = resto[1].replace('Acción: ', '').strip()
                if accion:
                    acciones_unicas.add(accion)
    acciones_unicas = sorted(acciones_unicas)
    # Filtrar líneas
    lineas_filtradas = []
    for linea in lineas:
        partes = linea.strip().split('] ', 1)
        if len(partes) == 2:
            fecha_ok = True
            accion_ok = True
            # Filtrar por fecha
            if filtro_fecha:
                fecha_ok = partes[0][1:11] == filtro_fecha
            # Filtrar por acción
            resto = partes[1].split(' | ')
            if filtro_accion and len(resto) > 1:
                accion_ok = (resto[1].replace('Acción: ', '').strip() == filtro_accion)
            if fecha_ok and accion_ok:
                lineas_filtradas.append(linea)
        else:
            # Si la línea no tiene el formato esperado, igual la mostramos
            if not filtro_fecha and not filtro_accion:
                lineas_filtradas.append(linea)
    return render_template('bitacora.html', lineas=lineas_filtradas, acciones_unicas=acciones_unicas, filtro_accion=filtro_accion, filtro_fecha=filtro_fecha)

@app.route('/bitacora/limpiar', methods=['POST'])
@login_required
@csrf.exempt
def limpiar_bitacora():
    try:
        # Registrar la acción antes de limpiar
        usuario = session.get('usuario', 'desconocido')
        registrar_bitacora(usuario, 'Limpiar bitácora', 'Se limpió toda la bitácora del sistema')
        
        # Limpiar el archivo
        open('bitacora.log', 'w').close()
        
        flash('Bitácora limpiada exitosamente.', 'success')
    except Exception as e:
        flash(f'Error al limpiar la bitácora: {str(e)}', 'danger')
    
    return redirect(url_for('ver_bitacora'))

# Función de facturas eliminada - ahora todo es por notas de entrega

# Función de facturas eliminada - ahora todo es por notas de entrega

def enviar_recordatorio_whatsapp(id):
    # Validación simple del ID
    if not id or str(id).strip() == '':
        print("❌ ID de nota inválido")
        return jsonify({'error': 'ID de nota inválido'}), 400
    
    try:
        print(f"🔍 Iniciando envío de recordatorio WhatsApp para nota: {id}")
        print(f"🔍 Método de petición: {request.method}")
        print(f"🔍 Headers: {dict(request.headers)}")
        print(f"🔍 Content-Type: {request.content_type}")
        
        # Ignorar datos del body si existen - solo usar el ID de la URL
        print("🔍 Usando solo el ID de la URL, ignorando datos del body")
        
        # Cargar datos necesarios
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        
        print(f"📊 Facturas cargadas: {len(facturas)}")
        print(f"👥 Clientes cargados: {len(clientes)}")
        
        if id not in facturas:
            print(f"❌ Factura {id} no encontrada")
            return jsonify({'error': 'Factura no encontrada'}), 404
        
        nota = notas[id]
        cliente_id = nota.get('cliente_id')
        
        print(f"👤 Cliente ID: {cliente_id}")
        print(f"📄 Factura: {nota.get('numero', 'N/A')}")
        
        if not cliente_id:
            print(f"❌ Factura {id} no tiene cliente_id")
            return jsonify({'error': 'La nota no tiene cliente asignado'}), 400
        
        # Verificar si el cliente_id está en la lista de clientes
        print(f"🔍 Buscando cliente_id '{cliente_id}' en clientes...")
        print(f"🔍 Clientes disponibles: {list(clientes.keys())}")
        
        if cliente_id not in clientes:
            print(f"❌ Cliente {cliente_id} no encontrado en clientes")
            return jsonify({'error': 'Cliente no encontrado'}), 404
        
        cliente = clientes[cliente_id]
        telefono = cliente.get('telefono', '')
        
        print(f"📱 Teléfono del cliente: {telefono}")
        print(f"👤 Nombre del cliente: {cliente.get('nombre', 'N/A')}")
        
        if not telefono:
            print(f"❌ Cliente {cliente_id} no tiene teléfono")
            return jsonify({'error': 'El cliente no tiene número de teléfono registrado'}), 400
        
        # Limpiar y formatear el número de teléfono
        telefono_original = telefono
        try:
            telefono = limpiar_numero_telefono(telefono)
            print(f"📱 Teléfono formateado exitosamente: {telefono}")
        except Exception as e:
            print(f"❌ Error formateando teléfono: {e}")
            return jsonify({'error': f'Error formateando teléfono: {str(e)}'}), 400
        
        print(f"📱 Teléfono original: {telefono_original}")
        print(f"📱 Teléfono formateado: {telefono}")
        
        if not telefono or len(telefono) < 10:
            print(f"❌ Teléfono formateado no válido: {telefono}")
            return jsonify({'error': 'El número de teléfono no es válido'}), 400
        
        # Crear mensaje personalizado
        try:
            mensaje = crear_mensaje_recordatorio(nota, cliente)
            print(f"💬 Mensaje creado exitosamente: {len(mensaje)} caracteres")
        except Exception as e:
            print(f"❌ Error creando mensaje: {e}")
            return jsonify({'error': f'Error creando mensaje: {str(e)}'}), 400
        
        # Generar enlace de WhatsApp
        try:
            enlace_whatsapp = generar_enlace_whatsapp(telefono, mensaje)
            print(f"🔗 Enlace WhatsApp generado exitosamente: {enlace_whatsapp}")
        except Exception as e:
            print(f"❌ Error generando enlace: {e}")
            return jsonify({'error': f'Error generando enlace: {str(e)}'}), 400
        
        # Registrar en la bitácora
        try:
            registrar_bitacora(
                session.get('usuario', 'Sistema'),
                'Recordatorio WhatsApp Enviado',
                f'Factura {nota.get("numero", "N/A")} - Cliente: {cliente.get("nombre", "N/A")}'
            )
            print("📝 Registrado en bitácora")
        except Exception as e:
            print(f"WARNING Error registrando en bitácora: {e}")
        
        resultado = {
            'success': True,
            'message': 'Recordatorio preparado para WhatsApp',
            'enlace_whatsapp': enlace_whatsapp,
            'telefono': telefono,
            'mensaje': mensaje,
            'cliente_nombre': cliente.get('nombre', 'N/A'),
            'debug_info': {
                'factura_id': id,
                'cliente_id': cliente_id,
                'telefono_original': telefono_original,
                'telefono_formateado': telefono
            }
        }
        
        print(f"✅ Recordatorio preparado exitosamente para {cliente.get('nombre', 'N/A')}")
        return jsonify(resultado)
        
    except Exception as e:
        error_msg = f"Error al enviar recordatorio WhatsApp: {str(e)}"
        print(f"❌ {error_msg}")
        import traceback
        print(f"🔍 Traceback completo:")
        traceback.print_exc()
        
        return jsonify({
            'success': False,
            'error': f'Error al preparar el recordatorio: {str(e)}',
            'debug_info': {
                'factura_id': id,
                'error_type': type(e).__name__,
                'error_details': str(e)
            }
        })

@app.route('/guardar_ubicacion_precisa', methods=['POST'])
def guardar_ubicacion_precisa():
    data = request.get_json()
    if data and 'lat' in data and 'lon' in data:
        lat = data['lat']
        lon = data['lon']
        # Reverse geocoding con Nominatim
        try:
            url = f'https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=10&addressdetails=1'
            headers = {'User-Agent': 'mi-app-web/1.0'}
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                info = resp.json().get('address', {})
                ciudad = info.get('city') or info.get('town') or info.get('village') or info.get('hamlet') or ''
                estado = info.get('state', '')
                pais = info.get('country', '')
                texto = ', '.join([v for v in [ciudad, estado, pais] if v])
                session['ubicacion_precisa'] = {'lat': lat, 'lon': lon, 'texto': texto}
            else:
                session['ubicacion_precisa'] = {'lat': lat, 'lon': lon, 'texto': ''}
        except Exception:
            session['ubicacion_precisa'] = {'lat': lat, 'lon': lon, 'texto': ''}
        return jsonify({'status': 'ok'})
    return jsonify({'status': 'error'}), 400

@app.route('/probar-recordatorio-whatsapp/<id>')
def probar_recordatorio_whatsapp(id):
    """Ruta de prueba para verificar el funcionamiento del recordatorio WhatsApp."""
    try:
        print(f"🧪 PROBANDO recordatorio WhatsApp para nota: {id}")
        
        # Cargar datos necesarios
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        
        if id not in facturas:
            return jsonify({'error': 'Factura no encontrada'}), 404
        
        nota = notas[id]
        cliente_id = nota.get('cliente_id')
        
        if not cliente_id or cliente_id not in clientes:
            return jsonify({'error': 'Cliente no encontrado'}), 404
        
        cliente = clientes[cliente_id]
        telefono = cliente.get('telefono', '')
        
        if not telefono:
            return jsonify({'error': 'Cliente no tiene teléfono'}), 400
        
        # Limpiar y formatear el número de teléfono
        telefono_limpio = limpiar_numero_telefono(telefono)
        
        # Crear mensaje personalizado
        mensaje = crear_mensaje_recordatorio(nota, cliente)
        
        # Generar enlace de WhatsApp
        enlace_whatsapp = generar_enlace_whatsapp(telefono_limpio, mensaje)
        
        return jsonify({
            'success': True,
            'message': 'Recordatorio preparado para WhatsApp',
            'enlace_whatsapp': enlace_whatsapp,
            'telefono': telefono_limpio,
            'mensaje': mensaje,
            'cliente_nombre': cliente.get('nombre', 'N/A')
        })
        
    except Exception as e:
        print(f"❌ Error en prueba: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/whatsapp-ultra-simple/<id>', methods=['GET', 'POST'])
@csrf.exempt
def whatsapp_ultra_simple(id):
    """Función ultra simple que funciona con GET y POST para máxima compatibilidad."""
    try:
        print(f"🚀 WHATSAPP ULTRA SIMPLE para nota: {id}")
        
        # Cargar datos necesarios
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        
        if id not in facturas:
            return jsonify({'error': 'Factura no encontrada'}), 404
        
        nota = notas[id]
        cliente_id = nota.get('cliente_id')
        
        if not cliente_id or cliente_id not in clientes:
            return jsonify({'error': 'Cliente no encontrado'}), 404
        
        cliente = clientes[cliente_id]
        telefono = cliente.get('telefono', '')
        
        if not telefono:
            print(f"❌ Cliente {cliente_id} no tiene número de teléfono registrado")
            return jsonify({'error': 'Cliente no tiene número de teléfono registrado'}), 400
        
        # Limpiar y formatear el número de teléfono
        telefono_limpio = limpiar_numero_telefono(telefono)
        
        # Crear mensaje personalizado
        mensaje = crear_mensaje_recordatorio(nota, cliente)
        
        # Generar enlace de WhatsApp
        enlace_whatsapp = generar_enlace_whatsapp(telefono_limpio, mensaje)
        
        return jsonify({
            'success': True,
            'message': 'Recordatorio preparado para WhatsApp',
            'enlace_whatsapp': enlace_whatsapp,
            'telefono': telefono_limpio,
            'mensaje': mensaje,
            'cliente_nombre': cliente.get('nombre', 'N/A')
        })
        
    except Exception as e:
        print(f"❌ Error en WhatsApp ultra simple: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/whatsapp-simple/<id>', methods=['POST'])
@csrf.exempt
def whatsapp_simple(id):
    """Función ultra simple para recordatorios de WhatsApp sin autenticación.
    
    Nota: Si el cliente no tiene número de teléfono registrado, devuelve HTTP 400
    con el mensaje 'Cliente no tiene número de teléfono registrado'.
    """
    try:
        print(f"🚀 WHATSAPP SIMPLE para nota: {id}")
        
        # Cargar datos necesarios
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        
        if id not in facturas:
            return jsonify({'error': 'Factura no encontrada'}), 404
        
        nota = notas[id]
        cliente_id = nota.get('cliente_id')
        
        if not cliente_id or cliente_id not in clientes:
            return jsonify({'error': 'Cliente no encontrado'}), 404
        
        cliente = clientes[cliente_id]
        telefono = cliente.get('telefono', '')
        
        if not telefono:
            print(f"❌ Cliente {cliente_id} no tiene número de teléfono registrado")
            return jsonify({'error': 'Cliente no tiene número de teléfono registrado'}), 400
        
        # Limpiar y formatear el número de teléfono
        telefono_limpio = limpiar_numero_telefono(telefono)
        
        # Crear mensaje personalizado
        mensaje = crear_mensaje_recordatorio(nota, cliente)
        
        # Generar enlace de WhatsApp
        enlace_whatsapp = generar_enlace_whatsapp(telefono_limpio, mensaje)
        
        return jsonify({
            'success': True,
            'message': 'Recordatorio preparado para WhatsApp',
            'enlace_whatsapp': enlace_whatsapp,
            'telefono': telefono_limpio,
            'mensaje': mensaje,
            'cliente_nombre': cliente.get('nombre', 'N/A')
        })
        
    except Exception as e:
        print(f"❌ Error en WhatsApp simple: {e}")
        return jsonify({'error': str(e)}), 500

def whatsapp_backup(id):
    """Función de respaldo para recordatorios de WhatsApp."""
    try:
        print(f"🔄 FUNCIÓN DE RESPALDO WhatsApp para nota: {id}")
        
        # Cargar datos necesarios
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        
        if id not in facturas:
            return jsonify({'error': 'Factura no encontrada'}), 404
        
        nota = notas[id]
        cliente_id = nota.get('cliente_id')
        
        if not cliente_id or cliente_id not in clientes:
            return jsonify({'error': 'Cliente no encontrado'}), 404
        
        cliente = clientes[cliente_id]
        telefono = cliente.get('telefono', '')
        
        if not telefono:
            return jsonify({'error': 'Cliente no tiene teléfono'}), 400
        
        # Limpiar y formatear el número de teléfono
        telefono_limpio = limpiar_numero_telefono(telefono)
        
        # Crear mensaje personalizado
        mensaje = crear_mensaje_recordatorio(nota, cliente)
        
        # Generar enlace de WhatsApp
        enlace_whatsapp = generar_enlace_whatsapp(telefono_limpio, mensaje)
        
        return jsonify({
            'success': True,
            'message': 'Recordatorio preparado para WhatsApp (función de respaldo)',
            'enlace_whatsapp': enlace_whatsapp,
            'telefono': telefono_limpio,
            'mensaje': mensaje,
            'cliente_nombre': cliente.get('nombre', 'N/A')
        })
        
    except Exception as e:
        print(f"❌ Error en función de respaldo: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/forzar-actualizacion-tasa-bcv')
def forzar_actualizacion_tasa_bcv():
    """Fuerza la actualización de la tasa BCV desde la web del BCV."""
    try:
        print("🔄 FORZANDO actualización de tasa BCV desde web...")
        
        # Obtener tasa desde web (ignorar archivo local)
        nueva_tasa = obtener_tasa_bcv_dia()
        
        if nueva_tasa and nueva_tasa > 10:
            resultado = {
                'success': True,
                'message': f'Tasa BCV actualizada exitosamente: {nueva_tasa}',
                'tasa_nueva': nueva_tasa,
                'fecha_actualizacion': datetime.now().isoformat(),
                'fuente': 'BCV Web Oficial'
            }
            print(f"✅ Tasa BCV actualizada: {nueva_tasa}")
        else:
            resultado = {
                'success': False,
                'message': 'No se pudo obtener la tasa BCV desde la web',
                'error': 'Tasa no válida o no encontrada'
            }
            print("❌ No se pudo obtener tasa válida desde web")
        
        return jsonify(resultado)
        
    except Exception as e:
        error_msg = f"Error forzando actualización: {str(e)}"
        print(f"❌ {error_msg}")
        return jsonify({
            'success': False,
            'message': error_msg,
            'error': str(e)
        }), 500

@app.route('/probar-tasa-bcv')
def probar_tasa_bcv():
    """Ruta de prueba para verificar el funcionamiento de la tasa BCV."""
    try:
        resultado = {
            'archivo_existe': os.path.exists(ULTIMA_TASA_BCV_FILE),
            'tasa_local': None,
            'tasa_web': None,
            'tasa_final': None,
            'tasa_sistema': None,
            'errores': []
        }
        
        # Probar búsqueda en el sistema
        try:
            tasa_sistema = obtener_ultima_tasa_del_sistema()
            resultado['tasa_sistema'] = tasa_sistema
        except Exception as e:
            resultado['errores'].append(f"Error buscando tasa en sistema: {e}")
        
        # Probar carga de tasa local
        try:
            tasa_local = cargar_ultima_tasa_bcv()
            resultado['tasa_local'] = tasa_local
        except Exception as e:
            resultado['errores'].append(f"Error cargando tasa local: {e}")
        
        # Probar obtención de tasa web
        try:
            tasa_web = obtener_tasa_bcv_dia()
            resultado['tasa_web'] = tasa_web
        except Exception as e:
            resultado['errores'].append(f"Error obteniendo tasa web: {e}")
        
        # Probar función principal
        try:
            tasa_final = obtener_tasa_bcv()
            resultado['tasa_final'] = tasa_final
        except Exception as e:
            resultado['errores'].append(f"Error en función principal: {e}")
        
        # Información adicional
        resultado['info'] = {
            'archivo_tasa': ULTIMA_TASA_BCV_FILE,
            'fecha_prueba': datetime.now().isoformat(),
            'sistema_inteligente': 'Sí - Busca en facturas y cuentas'
        }
        
        return jsonify(resultado)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/actualizar-tasa-bcv', methods=['POST'])
@login_required
def actualizar_tasa_bcv():
    try:
        # Intentar obtener la tasa del día
        tasa = obtener_tasa_bcv_dia()
        
        if tasa is None or tasa <= 0:
            # Si falla, intentar obtener la tasa del archivo
            tasa = cargar_ultima_tasa_bcv()
            if tasa is None or tasa <= 0:
                # Fallback con tasa correcta del dólar
                tasa = 205.68
                print("WARNING Usando tasa BCV USD de fallback: 205.68")
        
        # Guardar la nueva tasa
        guardar_ultima_tasa_bcv(tasa)
        
        # Registrar en la bitácora
        registrar_bitacora(
            session.get('usuario', 'Sistema'),
            'Actualización de Tasa BCV',
            f'Nueva tasa: {tasa}'
        )
        
        return jsonify({
            'success': True,
            'tasa': tasa,
            'message': f'Tasa BCV actualizada exitosamente: {tasa}'
        })
        
    except Exception as e:
        print(f"Error al actualizar tasa BCV: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Error al actualizar la tasa BCV: {str(e)}'
        })


# Rutas para gestión de categorías
@app.route('/categorias')
@login_required
def gestionar_categorias():
    # Cargar el inventario
    inventario = cargar_datos(ARCHIVO_INVENTARIO)
    
    # Obtener categorías únicas
    categorias = []
    for id, producto in inventario.items():
        if producto.get('categoria') and producto['categoria'] not in [c['nombre'] for c in categorias]:
            categorias.append({
                'id': len(categorias) + 1,
                'nombre': producto['categoria']
            })
    
    return render_template('gestionar_categorias.html', categorias=categorias)

@app.route('/categorias', methods=['POST'])
@login_required
def crear_categoria():
    nombre = request.form.get('nombre')
    if not nombre:
        flash('El nombre de la categoría es requerido', 'danger')
        return redirect(url_for('gestionar_categorias'))
    
    # Cargar el inventario
    inventario = cargar_datos(ARCHIVO_INVENTARIO)
    
    # Verificar si la categoría ya existe
    for producto in inventario.values():
        if producto.get('categoria') == nombre:
            flash('Esta categoría ya existe', 'danger')
            return redirect(url_for('gestionar_categorias'))
    
    # Crear un nuevo producto con la categoría para mantenerla en el sistema
    nuevo_id = str(max([int(k) for k in inventario.keys()]) + 1) if inventario else '1'
    inventario[nuevo_id] = {
        'nombre': f'Producto de categoría {nombre}',
        'categoria': nombre,
        'precio': 0,
        'cantidad': 0,
        'ultima_entrada': datetime.now().isoformat()
    }
    
    if guardar_datos(ARCHIVO_INVENTARIO, inventario):
        flash('Categoría creada exitosamente', 'success')
    else:
        flash('Error al crear la categoría', 'danger')
    
    return redirect(url_for('gestionar_categorias'))

@app.route('/categorias/<int:id>/editar', methods=['POST'])
@login_required
def editar_categoria(id):
    nuevo_nombre = request.form.get('nuevo_nombre')
    if not nuevo_nombre:
        flash('El nuevo nombre de la categoría es requerido', 'danger')
        return redirect(url_for('gestionar_categorias'))
    
    # Cargar el inventario
    inventario = cargar_datos(ARCHIVO_INVENTARIO)
    
    # Verificar si el nuevo nombre ya existe
    for producto in inventario.values():
        if producto.get('categoria') == nuevo_nombre:
            flash('Ya existe una categoría con ese nombre', 'danger')
            return redirect(url_for('gestionar_categorias'))
    
    # Encontrar la categoría actual
    categoria_actual = None
    for producto in inventario.values():
        if producto.get('categoria') and producto['categoria'] not in [c['nombre'] for c in [{'nombre': p.get('categoria')} for p in inventario.values() if p.get('categoria')]]:
            categoria_actual = producto['categoria']
            break
    
    if not categoria_actual:
        flash('Categoría no encontrada', 'danger')
        return redirect(url_for('gestionar_categorias'))
    
    # Actualizar la categoría en todos los productos
    for producto in inventario.values():
        if producto.get('categoria') == categoria_actual:
            producto['categoria'] = nuevo_nombre
    
    if guardar_datos(ARCHIVO_INVENTARIO, inventario):
        flash('Categoría actualizada exitosamente', 'success')
    else:
        flash('Error al actualizar la categoría', 'danger')
    
    return redirect(url_for('gestionar_categorias'))

@app.route('/categorias/<int:id>/eliminar', methods=['POST'])
@login_required
def eliminar_categoria(id):
    # Cargar el inventario
    inventario = cargar_datos(ARCHIVO_INVENTARIO)
    
    # Encontrar la categoría
    categoria = None
    for producto in inventario.values():
        if producto.get('categoria') and producto['categoria'] not in [c['nombre'] for c in [{'nombre': p.get('categoria')} for p in inventario.values() if p.get('categoria')]]:
            categoria = producto['categoria']
            break
    
    if not categoria:
        flash('Categoría no encontrada', 'danger')
        return redirect(url_for('gestionar_categorias'))
    
    # Verificar si hay productos asociados
    productos_asociados = [p for p in inventario.values() if p.get('categoria') == categoria]
    if len(productos_asociados) > 1:  # Más de 1 porque uno es el producto de la categoría
        flash('No se puede eliminar la categoría porque tiene productos asociados', 'danger')
        return redirect(url_for('gestionar_categorias'))
    
    # Eliminar el producto de la categoría
    for id_producto, producto in list(inventario.items()):
        if producto.get('categoria') == categoria:
            del inventario[id_producto]
            break
    
    if guardar_datos(ARCHIVO_INVENTARIO, inventario):
        flash('Categoría eliminada exitosamente', 'success')
    else:
        flash('Error al eliminar la categoría', 'danger')
    
    return redirect(url_for('gestionar_categorias'))

@app.route('/inventario/ajustes-masivos')
@login_required
def ajustes_masivos():
    inventario = cargar_datos('inventario.json')
    # Recolectar todos los ajustes
    ajustes = []
    for producto in inventario.values():
        nombre_producto = producto.get('nombre', '')
        if 'historial_ajustes' in producto:
            for ajuste in producto['historial_ajustes']:
                tipo = ajuste.get('tipo', '')
                ajustes.append({
                    'fecha': ajuste.get('fecha', ''),
                    'motivo': ajuste.get('motivo', ''),
                    'producto': nombre_producto,
                    'tipo': tipo,
                    'ingreso': ajuste['cantidad'] if tipo == 'entrada' else 0,
                    'salida': ajuste['cantidad'] if tipo == 'salida' else 0,
                    'usuario': ajuste.get('usuario', ''),
                    'observaciones': ajuste.get('observaciones', ajuste.get('motivo', ''))
                })
    # Obtener filtros
    filtro_fecha = request.args.get('fecha', '')
    filtro_producto = request.args.get('producto', '').lower()
    filtro_usuario = request.args.get('usuario', '').lower()
    filtro_tipo = request.args.get('tipo', '')
    # Aplicar filtros
    if filtro_fecha:
        ajustes = [a for a in ajustes if a['fecha'][:10] == filtro_fecha]
    if filtro_producto:
        ajustes = [a for a in ajustes if filtro_producto in a['producto'].lower()]
    if filtro_usuario:
        ajustes = [a for a in ajustes if filtro_usuario in a['usuario'].lower()]
    if filtro_tipo:
        ajustes = [a for a in ajustes if a.get('tipo') == filtro_tipo]
    # Ordenar por fecha descendente
    ajustes.sort(key=lambda x: x['fecha'], reverse=True)
    # Obtener listas para filtros
    productos = sorted(list(set(a['producto'] for a in ajustes)))
    usuarios = sorted(list(set(a['usuario'] for a in ajustes)))
    return render_template('ajustes_masivos.html', 
                         ajustes=ajustes,
                         productos=productos,
                         usuarios=usuarios,
                         filtro_fecha=filtro_fecha,
                         filtro_producto=filtro_producto,
                         filtro_usuario=filtro_usuario,
                         filtro_tipo=filtro_tipo)

@app.route('/api/tasas')
def api_tasas():
    try:
        r = requests.get('https://s3.amazonaws.com/dolartoday/data.json', timeout=5)
        data = r.json()
        tasa_bcv = safe_float(data['USD']['bcv']) if 'USD' in data and 'bcv' in data['USD'] else None
        tasa_paralelo = safe_float(data['USD']['promedio']) if 'USD' in data and 'promedio' in data['USD'] else None
        tasa_bcv_eur = safe_float(data['EUR']['promedio']) if 'EUR' in data and 'promedio' in data['EUR'] else None
        return jsonify({
            'tasa_bcv': tasa_bcv,
            'tasa_paralelo': tasa_paralelo,
            'tasa_bcv_eur': tasa_bcv_eur
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tasas-actualizadas')
def api_tasas_actualizadas():
    try:
        # 1. Obtener tasas BCV (USD/BS y EUR/BS) desde el glosario oficial
        tasa_bcv = None
        tasa_bcv_eur = None
        try:
            print("🔍 Obteniendo tasas desde BCV Oficial: https://www.bcv.org.ve/glosario/cambio-oficial")
            url_bcv = 'https://www.bcv.org.ve/glosario/cambio-oficial'
            resp = requests.get(url_bcv, timeout=20, verify=False)
            
            if resp.status_code == 200:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, 'html.parser')
                
                # Buscar tasa USD en div con id='dolar'
                dolar_div = soup.find('div', id='dolar')
                if dolar_div:
                    strong = dolar_div.find('strong')
                    if strong:
                        txt = strong.text.strip().replace('.', '').replace(',', '.')
                        try:
                            tasa_bcv = float(txt)
                            print(f"✅ Tasa USD obtenida del BCV: {tasa_bcv}")
                        except:
                            pass
                
                # Buscar tasa EUR buscando en todos los divs que contengan "EUR" o "euro"
                for div in soup.find_all(['div', 'tr', 'td']):
                    texto = div.get_text(strip=True).upper()
                    if 'EUR' in texto or 'EURO' in texto:
                        strong = div.find('strong')
                        if strong:
                            txt = strong.text.strip().replace('.', '').replace(',', '.')
                            try:
                                posible = float(txt)
                                if posible > 10:
                                    tasa_bcv_eur = posible
                                    print(f"✅ Tasa EUR obtenida del BCV: {tasa_bcv_eur}")
                                    break
                            except:
                                continue
                
                # Si no encontramos EUR explícito, buscar el segundo valor en la tabla
                if not tasa_bcv_eur:
                    tasas_encontradas = []
                    for strong in soup.find_all('strong'):
                        txt = strong.text.strip().replace('.', '').replace(',', '.')
                        try:
                            posible = float(txt)
                            if 10 < posible < 1000:
                                tasas_encontradas.append(posible)
                        except:
                            continue
                    
                    if len(tasas_encontradas) >= 2:
                        # El segundo valor debería ser EUR
                        tasa_bcv_eur = tasas_encontradas[1]
                        print(f"✅ Tasa EUR (segunda tasa encontrada): {tasa_bcv_eur}")
            
        except Exception as e:
            print(f"Error obteniendo tasas del BCV Oficial: {e}")

        # 2. Tasa paralela: manual (no scraping ni API)
        tasa_paralelo = 0
        fuente_paralelo = 'manual'
        
        # 3. Fallbacks
        if tasa_bcv is None:
            tasa_bcv = cargar_ultima_tasa_bcv() or 1.0
        if tasa_paralelo is None:
            tasa_paralelo = tasa_bcv
        if tasa_bcv_eur is None:
            tasa_bcv_eur = 0

        # Guardar las tasas en configuración
        try:
            config = cargar_configuracion()
            if 'tasas' not in config:
                config['tasas'] = {}
            
            # Guardar tasa USD (esto también actualiza ultima_tasa_bcv.json)
            if tasa_bcv and tasa_bcv > 10:
                guardar_ultima_tasa_bcv(tasa_bcv)
            
            # Guardar tasa EUR directamente en config (solo EUR, USD ya se guardó arriba)
            if tasa_bcv_eur and tasa_bcv_eur > 10:
                config['tasas']['tasa_actual_eur'] = round(tasa_bcv_eur, 2)
            
            # Actualizar timestamp de última actualización
            config['tasas']['ultima_actualizacion'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            guardar_configuracion(config)
            print(f"✅ Tasas guardadas en configuración: USD={tasa_bcv}, EUR={tasa_bcv_eur}")
        except Exception as e:
            print(f"⚠️ Error guardando tasas en configuración: {e}")

        return jsonify({
            'success': True,
            'tasa_bcv': tasa_bcv,
            'tasa_paralelo': tasa_paralelo,
            'tasa_bcv_eur': tasa_bcv_eur,
            'fuente_paralelo': fuente_paralelo,
            'fecha_actualizacion': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
    except Exception as e:
        # En caso de error, devolver las últimas tasas guardadas
        ultima_tasa = cargar_ultima_tasa_bcv() or 1.0
        return jsonify({
            'success': False,
            'error': str(e),
            'tasa_bcv': ultima_tasa,
            'tasa_paralelo': ultima_tasa,
            'tasa_bcv_eur': 0,
            'fecha_actualizacion': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })

@app.route('/inventario/lista-precios')
@login_required
def lista_precios():
    
    # Obtener filtros
    filtro_categoria = request.args.get('categoria', '')
    filtro_precio_min = request.args.get('precio_min', '')
    filtro_precio_max = request.args.get('precio_max', '')
    filtro_busqueda = request.args.get('busqueda', '')
    
    # Cargar datos
    inventario = cargar_datos(ARCHIVO_INVENTARIO)
    empresa = cargar_empresa()
    fecha_actual = datetime.now()
    
    # Obtener categorías únicas
    categorias = sorted(set(producto.get('categoria', '') for producto in inventario.values() if producto.get('categoria')))
    
    # Filtrar productos
    productos_filtrados = {}
    for id_producto, producto in inventario.items():
        # Aplicar filtros
        if filtro_categoria and producto.get('categoria') != filtro_categoria:
            continue
            
        precio = safe_float(producto.get('precio', 0))
        if filtro_precio_min and precio < safe_float(filtro_precio_min):
            continue
        if filtro_precio_max and precio > safe_float(filtro_precio_max):
            continue
            
        if filtro_busqueda:
            busqueda = filtro_busqueda.lower()
            if busqueda not in producto.get('nombre', '').lower():
                continue
                
        productos_filtrados[id_producto] = producto
    
    return render_template('lista_precios.html', 
                         inventario=productos_filtrados, 
                         empresa=empresa,
                         now=fecha_actual,
                         categorias=categorias,
                         filtro_categoria=filtro_categoria,
                         filtro_precio_min=filtro_precio_min,
                         filtro_precio_max=filtro_precio_max,
                         filtro_busqueda=filtro_busqueda)

@app.route('/inventario/lista-precios/pdf')
@login_required
def lista_precios_pdf():
    # Obtener filtros
    filtro_categoria = request.args.get('categoria', '')
    filtro_precio_min = request.args.get('precio_min', '')
    filtro_precio_max = request.args.get('precio_max', '')
    filtro_busqueda = request.args.get('busqueda', '')
    # Cargar datos
    inventario = cargar_datos(ARCHIVO_INVENTARIO)
    empresa = cargar_empresa()
    
    # Convertir rutas relativas a absolutas para las imágenes
    # Usar logo_path en lugar de logo para mantener compatibilidad
    if empresa.get('logo_path'):
        empresa['logo'] = request.url_root.rstrip('/') + url_for('static', filename=empresa['logo_path'])
    elif empresa.get('logo'):
        empresa['logo'] = request.url_root.rstrip('/') + url_for('static', filename=empresa['logo'])
    if empresa.get('membrete'):
        empresa['membrete'] = request.url_root.rstrip('/') + url_for('static', filename=empresa['membrete'])
    
    fecha_actual = datetime.now()
    # Obtener categorías únicas
    categorias = sorted(set(producto.get('categoria', '') for producto in inventario.values() if producto.get('categoria')))
    # Filtrar productos
    productos_filtrados = {}
    for id_producto, producto in inventario.items():
        if filtro_categoria and producto.get('categoria') != filtro_categoria:
            continue
        precio = safe_float(producto.get('precio', 0))
        if filtro_precio_min and precio < safe_float(filtro_precio_min):
            continue
        if filtro_precio_max and precio > safe_float(filtro_precio_max):
            continue
        if filtro_busqueda:
            busqueda = filtro_busqueda.lower()
            if busqueda not in producto.get('nombre', '').lower():
                continue
        productos_filtrados[id_producto] = producto
    rendered = render_template('lista_precios.html', 
                             inventario=productos_filtrados, 
                             tipo=tipo, 
                             empresa=empresa, 
                             pdf=True,
                             now=fecha_actual,
                             app=app,
                             categorias=categorias,
                             filtro_categoria=filtro_categoria,
                             filtro_precio_min=filtro_precio_min,
                             filtro_precio_max=filtro_precio_max,
                             filtro_busqueda=filtro_busqueda)
    try:
        # Intentar diferentes ubicaciones comunes de wkhtmltopdf
        wkhtmltopdf_paths = [
            'C:\\Program Files\\wkhtmltopdf\\bin\\wkhtmltopdf.exe',
            '/usr/bin/wkhtmltopdf',
            '/usr/local/bin/wkhtmltopdf',
            'wkhtmltopdf'  # Si está en el PATH
        ]
        
        config = None
        for path in wkhtmltopdf_paths:
            if os.path.exists(path):
                config = pdfkit.configuration(wkhtmltopdf=path)
                break
        
        if config is None:
            # Si no se encuentra wkhtmltopdf, intentar usar el comando directamente
            config = pdfkit.configuration(wkhtmltopdf='wkhtmltopdf')
        
        options = {
            'page-size': 'A4',
            'margin-top': '20mm',
            'margin-right': '20mm',
            'margin-bottom': '20mm',
            'margin-left': '20mm',
            'encoding': 'UTF-8',
            'no-outline': None,
            'quiet': '',
            'print-media-type': None,
            'orientation': 'Portrait',
            'dpi': 300,
            'image-quality': 100,
            'enable-local-file-access': None,
            'javascript-delay': '1000',
            'no-stop-slow-scripts': None
        }
        pdf = pdfkit.from_string(rendered, False, options=options, configuration=config)
        response = make_response(pdf)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=lista_precios_{tipo}.pdf'
        return response
    except Exception as e:
        print(f"Error al generar PDF: {str(e)}")  # Para debugging
        flash(f'Error al generar PDF: {str(e)}', 'danger')
        return redirect(url_for('lista_precios', tipo=tipo))

# ========================================
# RUTAS SENIAT - INTERFACE DE CONSULTA Y ADMINISTRACIÓN
# ========================================

@app.route('/seniat/consulta')
def seniat_consulta():
    """Interfaz de consulta segura para el SENIAT"""
    # Esta ruta debe tener autenticación especial del SENIAT
    # Por seguridad, solo permitir acceso con credenciales SENIAT específicas
    auth_header = request.headers.get('Authorization')
    seniat_token = request.headers.get('X-SENIAT-Token')
    
    if not auth_header or not seniat_token:
        return jsonify({
            'error': 'Acceso no autorizado - Credenciales SENIAT requeridas',
            'codigo': 'AUTH_REQUIRED'
        }), 401
    
    # TODO: Implementar validación real de credenciales SENIAT
    # Por ahora, mensaje informativo
    return jsonify({
        'sistema': 'Sistema Fiscal Homologado SENIAT',
        'version': '1.0.0',
        'estado': 'ACTIVO',
        'endpoints_disponibles': [
            '/seniat/facturas/consultar',
            '/seniat/exportar/facturas',
            '/seniat/exportar/logs',
            '/seniat/auditoria/integridad',
            '/seniat/sistema/estado'
        ],
        'timestamp': datetime.now().isoformat()
    })

@app.route('/seniat/sistema/estado')
def seniat_estado_sistema():
    """Obtiene el estado del sistema fiscal"""
    try:
        # Estado de numeración
        estado_numeracion = control_numeracion.obtener_estado_numeracion()
        
        # Estado de comunicación SENIAT
        estado_comunicacion = comunicador_seniat.obtener_configuracion_actual()
        
        # Estadísticas generales
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        total_notas_entrega = len(notas)
        
        estado_sistema = {
            'version_sistema': '1.0.0',
            'fecha_consulta': datetime.now().isoformat(),
            'estadisticas': {
                'total_notas_entrega_emitidas': total_notas_entrega
            },
            'numeracion': {
                'series_activas': len([s for s in estado_numeracion.get('series', {}).values() if s.get('activa')]),
                'total_documentos_emitidos': estado_numeracion.get('auditoria', {}).get('total_documentos_emitidos', 0)
            },
            'comunicacion_seniat': {
                'configurado': bool(estado_comunicacion['configuracion'].get('rif_empresa')),
                'conectado': estado_comunicacion['estado_conexion'].get('conectado', False)
            },
            'seguridad': {
                'logs_fiscales_activos': True,
                'inmutabilidad_activa': True,
                'cifrado_activo': True
            }
        }
        
        return jsonify(estado_sistema)
        
    except Exception as e:
        return jsonify({
            'error': f'Error obteniendo estado: {str(e)}',
            'codigo': 'ESTADO_ERROR'
        }), 500

# --- Funciones Auxiliares para WhatsApp ---
def limpiar_numero_telefono(telefono):
    """Limpia y formatea un número de teléfono para WhatsApp."""
    try:
        print(f"🔧 Formateando teléfono: {telefono}")
        
        # Verificar que el teléfono no esté vacío
        if not telefono or str(telefono).strip() == '':
            raise ValueError("El número de teléfono está vacío")
        
        # Remover todos los caracteres no numéricos
        telefono_limpio = re.sub(r'[^\d]', '', str(telefono))
        print(f"🔧 Solo números: {telefono_limpio}")
        
        # Verificar que haya números después de limpiar
        if not telefono_limpio:
            raise ValueError("No se encontraron números en el teléfono")
        
        # Si empieza con 0, removerlo
        if telefono_limpio.startswith('0'):
            telefono_limpio = telefono_limpio[1:]
            print(f"🔧 Removido 0 inicial: {telefono_limpio}")
        
        # Si empieza con +58, removerlo
        if telefono_limpio.startswith('58'):
            telefono_limpio = telefono_limpio[2:]
            print(f"🔧 Removido 58 inicial: {telefono_limpio}")
        
        # Verificar longitud y agregar 58 si es necesario
        if len(telefono_limpio) == 10:
            telefono_limpio = '58' + telefono_limpio
            print(f"🔧 Agregado 58 para 10 dígitos: {telefono_limpio}")
        elif len(telefono_limpio) == 9:
            telefono_limpio = '58' + telefono_limpio
            print(f"🔧 Agregado 58 para 9 dígitos: {telefono_limpio}")
        
        print(f"🔧 Teléfono final formateado: {telefono_limpio}")
        
        # Validar que el resultado sea válido
        if len(telefono_limpio) < 11:
            raise ValueError(f"Teléfono formateado muy corto: {telefono_limpio}")
        
        return telefono_limpio
        
    except Exception as e:
        print(f"❌ Error en limpiar_numero_telefono: {e}")
        raise

def generar_enlace_whatsapp(telefono, mensaje):
    """Genera un enlace de WhatsApp con el mensaje predefinido."""
    try:
        print(f"🔗 Generando enlace para teléfono: {telefono}")
        print(f"🔗 Mensaje a codificar: {len(mensaje)} caracteres")
        
        # Codificar el mensaje para URL - preservar emojis
        mensaje_codificado = urllib.parse.quote(mensaje, safe='')
        print(f"🔗 Mensaje codificado: {len(mensaje_codificado)} caracteres")
        
        # Crear enlace de WhatsApp - usar wa.me para mejor compatibilidad y evitar errores 404
        enlace = f"https://wa.me/{telefono}?text={mensaje_codificado}"
        print(f"🔗 Enlace generado: {enlace[:100]}...")
        return enlace
    except Exception as e:
        print(f"❌ Error generando enlace: {e}")
        raise

def generar_enlaces_whatsapp_completos(telefono, mensaje):
    """Genera múltiples enlaces de WhatsApp para máxima compatibilidad."""
    try:
        print(f"🔗 Generando enlaces completos para teléfono: {telefono}")
        
        # Codificar el mensaje para URL
        mensaje_codificado = urllib.parse.quote(mensaje, safe='')
        
        # Enlaces con diferentes formatos para máxima compatibilidad
        enlaces = {
            'app_movil': f"https://wa.me/{telefono}?text={mensaje_codificado}",
            'web_whatsapp': f"https://web.whatsapp.com/send?phone={telefono}&text={mensaje_codificado}",
            'web_whatsapp_alt': f"https://web.whatsapp.com/send?phone={telefono}&text={mensaje_codificado}&app_absent=0",
            'fallback': f"https://wa.me/{telefono}"  # Sin mensaje, solo abre el chat
        }
        
        print(f"🔗 Enlaces generados exitosamente")
        return enlaces
    except Exception as e:
        print(f"❌ Error generando enlaces completos: {e}")
        raise

# --- Bloque para Ejecutar la Aplicación ---
# MOVIDO AL FINAL DEL ARCHIVO PARA QUE SE REGISTREN TODAS LAS RUTAS

@app.route('/initdb')
@admin_required
def initdb():
    db.create_all()
    return 'Base de datos inicializada correctamente.'

@app.route('/debug-recordatorio/<id>')
@csrf.exempt
def debug_recordatorio(id):
    """Ruta de debug para diagnosticar problemas con recordatorios."""
    try:
        print(f"🔍 DEBUG recordatorio para nota: {id}")
        
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        if id not in facturas:
            return jsonify({'error': 'Factura no encontrada'}), 404
        
        nota = notas[id]
        cliente_id = nota.get('cliente_id')
        
        # Verificar que el cliente existe
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        if not cliente_id or cliente_id not in clientes:
            return jsonify({'error': 'Cliente no encontrado'}), 404
        
        cliente = clientes[cliente_id]
        telefono = cliente.get('telefono', '')
        
        # Información de debug
        debug_info = {
            'factura_id': id,
            'factura_numero': nota.get('numero', 'N/A'),
            'cliente_id': cliente_id,
            'cliente_nombre': cliente.get('nombre', 'N/A'),
            'telefono_original': telefono,
            'telefono_formateado': None,
            'mensaje_generado': None,
            'enlace_generado': None,
            'errores': []
        }
        
        # Probar cada función paso a paso
        try:
            telefono_formateado = limpiar_numero_telefono(telefono)
            debug_info['telefono_formateado'] = telefono_formateado
            print(f"✅ Teléfono formateado: {telefono_formateado}")
        except Exception as e:
            error_msg = f"Error formateando teléfono: {e}"
            debug_info['errores'].append(error_msg)
            print(f"❌ {error_msg}")
            return jsonify(debug_info)
        
        try:
            mensaje = crear_mensaje_recordatorio(nota, cliente)
            debug_info['mensaje_generado'] = mensaje[:200] + '...' if len(mensaje) > 200 else mensaje
            print(f"✅ Mensaje generado: {len(mensaje)} caracteres")
        except Exception as e:
            error_msg = f"Error creando mensaje: {e}"
            debug_info['errores'].append(error_msg)
            print(f"❌ {error_msg}")
            return jsonify(debug_info)
        
        try:
            enlace = generar_enlace_whatsapp(telefono_formateado, mensaje)
            debug_info['enlace_generado'] = enlace[:200] + '...' if len(enlace) > 200 else enlace
            print(f"✅ Enlace generado: {len(enlace)} caracteres")
        except Exception as e:
            error_msg = f"Error generando enlace: {e}"
            debug_info['errores'].append(error_msg)
            print(f"❌ {error_msg}")
            return jsonify(debug_info)
        
        debug_info['success'] = True
        debug_info['message'] = 'Todas las funciones funcionan correctamente'
        print(f"✅ Debug completado exitosamente para nota {id}")
        return jsonify(debug_info)
        
    except Exception as e:
        import traceback
        error_info = {
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__,
            'traceback': traceback.format_exc()
        }
        print(f"❌ Error fatal en debug: {error_info}")
        return jsonify(error_info), 500

@app.route('/webauthn/register/options', methods=['POST'])
def webauthn_register_options():
    username = request.json.get('username')
    if not username:
        return jsonify({'error': 'Usuario requerido'}), 400
    user = User.query.filter_by(username=username).first()
    if not user:
        return jsonify({'error': 'Usuario no encontrado'}), 404
    options = generate_registration_options(user)
    session['webauthn_registration_challenge'] = options.challenge
    return jsonify(options.registration_dict)

@app.route('/webauthn/register/verify', methods=['POST'])
def webauthn_register_verify():
    username = request.json.get('username')
    credential = request.json.get('credential')
    if not username or not credential:
        return jsonify({'error': 'Datos incompletos'}), 400
    user = User.query.filter_by(username=username).first()
    if not user:
        return jsonify({'error': 'Usuario no encontrado'}), 404
    challenge = session.get('webauthn_registration_challenge')
    if not challenge:
        return jsonify({'error': 'Challenge no encontrado'}), 400
    try:
        response = WebAuthnRegistrationResponse(
            rp_id=os.environ.get('WEBAUTHN_RP_ID', 'localhost'),
            origin=os.environ.get('WEBAUTHN_ORIGIN', 'http://localhost:5000'),
            registration_response=credential,
            challenge=challenge,
            uv_required=False
        )
        cred = response.verify()
        user.credential_id = cred.credential_id
        user.public_key = cred.public_key
        user.sign_count = cred.sign_count
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/webauthn/authenticate/options', methods=['POST'])
def webauthn_authenticate_options():
    username = request.json.get('username')
    if not username:
        return jsonify({'error': 'Usuario requerido'}), 400
    user = User.query.filter_by(username=username).first()
    if not user or not user.credential_id:
        return jsonify({'error': 'Usuario o credencial no encontrada'}), 404
    options = generate_assertion_options(user)
    session['webauthn_authenticate_challenge'] = options.challenge
    return jsonify(options.assertion_dict)

@app.route('/webauthn/authenticate/verify', methods=['POST'])
def webauthn_authenticate_verify():
    username = request.json.get('username')
    credential = request.json.get('credential')
    if not username or not credential:
        return jsonify({'error': 'Datos incompletos'}), 400
    user = User.query.filter_by(username=username).first()
    if not user or not user.credential_id:
        return jsonify({'error': 'Usuario o credencial no encontrada'}), 404
    challenge = session.get('webauthn_authenticate_challenge')
    if not challenge:
        return jsonify({'error': 'Challenge no encontrado'}), 400
    try:
        response = WebAuthnAssertionResponse(
            rp_id=os.environ.get('WEBAUTHN_RP_ID', 'localhost'),
            origin=os.environ.get('WEBAUTHN_ORIGIN', 'http://localhost:5000'),
            assertion_response=credential,
            challenge=challenge,
            credential_public_key=user.public_key,
            credential_current_sign_count=user.sign_count,
            uv_required=False
        )
        sign_count = response.verify()
        user.sign_count = sign_count
        db.session.commit()
        session['usuario'] = username
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# --- Funcionalidad WhatsApp para Cuentas por Cobrar ---

# Ruta de prueba para verificar que la ruta con path funciona
@app.route('/test-path/<path:test_id>')
def test_path(test_id):
    return jsonify({'message': f'Ruta con path funcionando, ID recibido: {test_id}'})

# --- MÓDULO DE SERVICIO TÉCNICO ---

@app.route('/servicio-tecnico')
@login_required
def servicio_tecnico():
    """Página principal del módulo de servicio técnico"""
    try:
        ordenes = cargar_datos('ordenes_servicio.json')
        config = cargar_datos('config_servicio_tecnico.json')
        
        # Estadísticas básicas
        total_ordenes = len(ordenes)
        ordenes_pendientes = len([o for o in ordenes.values() if isinstance(o, dict) and o.get('estado') in ['en_espera_revision', 'en_diagnostico', 'presupuesto_enviado', 'aprobado_por_cliente', 'en_reparacion']])
        ordenes_completadas = len([o for o in ordenes.values() if isinstance(o, dict) and o.get('estado') == 'entregado'])
        
        # Obtener órdenes con estados vencidos
        ordenes_vencidas = obtener_ordenes_estados_vencidos()
        
        # Fecha actual para cálculos
        now = datetime.now()
        
        # Convertir órdenes a DotDict para que los templates puedan usar notación de punto
        ordenes_dotdict = {}
        for orden_id, orden in ordenes.items():
            if isinstance(orden, dict):
                orden_normalizado = DotDict(orden)
                # Asegurar que 'estado' existe
                if 'estado' not in orden_normalizado:
                    orden_normalizado['estado'] = 'desconocido'
                
                # Procesar fechas
                if orden_normalizado.get('fecha_recepcion'):
                    try:
                        fecha_recepcion = datetime.strptime(orden_normalizado.fecha_recepcion, '%Y-%m-%d').date()
                        orden_normalizado['dias_transcurridos'] = (now.date() - fecha_recepcion).days
                    except:
                        orden_normalizado['dias_transcurridos'] = 0
                else:
                    orden_normalizado['dias_transcurridos'] = 0
                
                # Calcular días restantes para entrega estimada
                if orden_normalizado.get('fecha_entrega_estimada'):
                    try:
                        fecha_entrega = datetime.strptime(orden_normalizado.fecha_entrega_estimada, '%Y-%m-%d').date()
                        orden_normalizado['dias_restantes'] = (fecha_entrega - now.date()).days
                        orden_normalizado['fecha_vencida'] = orden_normalizado['dias_restantes'] < 0
                        orden_normalizado['fecha_proxima'] = 0 <= orden_normalizado['dias_restantes'] <= 2
                    except:
                        orden_normalizado['dias_restantes'] = 0
                        orden_normalizado['fecha_vencida'] = False
                        orden_normalizado['fecha_proxima'] = False
                else:
                    orden_normalizado['dias_restantes'] = 0
                    orden_normalizado['fecha_vencida'] = False
                    orden_normalizado['fecha_proxima'] = False
                
                ordenes_dotdict[orden_id] = orden_normalizado
        
        return render_template('servicio_tecnico/index.html', 
                             ordenes=ordenes_dotdict,
                             config=config,
                             total_ordenes=total_ordenes,
                             ordenes_pendientes=ordenes_pendientes,
                             ordenes_completadas=ordenes_completadas,
                             ordenes_vencidas=ordenes_vencidas,
                             now=now)
    except Exception as e:
        print(f"DEBUG: Error en servicio_tecnico: {str(e)}")
        import traceback
        traceback.print_exc()
        # No mostrar el error al usuario, solo retornar valores por defecto
        # flash(f'Error cargando servicio técnico: {str(e)}', 'danger')
        
        # Retornar valores por defecto seguros
        return render_template('servicio_tecnico/index.html', 
                             ordenes={}, 
                             config={'estados_servicio': {}}, 
                             total_ordenes=0,
                             ordenes_pendientes=0,
                             ordenes_completadas=0,
                             now=datetime.now())

@app.route('/servicio-tecnico/crear-orden-prueba')
@login_required
def crear_orden_prueba():
    """Crear una orden de servicio de prueba con diagnóstico y repuestos"""
    try:
        ordenes = cargar_datos('ordenes_servicio.json')
        inventario = cargar_datos(ARCHIVO_INVENTARIO)
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        
        # Obtener algunos repuestos del inventario para usar en el diagnóstico
        repuestos_disponibles = []
        if inventario:
            repuestos_disponibles = [
                {
                    'id': rep_id,
                    'nombre': rep.get('nombre', 'Repuesto'),
                    'precio': float(rep.get('precio', 0)),
                    'cantidad': 1,
                    'categoria': rep.get('categoria', '')
                }
                for rep_id, rep in list(inventario.items())[:3]  # Tomar los primeros 3 repuestos
                if isinstance(rep, dict) and rep.get('cantidad', 0) > 0
            ]
        
        # Obtener un cliente de ejemplo o crear uno de prueba
        cliente_prueba = None
        if clientes:
            cliente_prueba = list(clientes.values())[0]
        else:
            cliente_prueba = {
                'nombre': 'Cliente de Prueba',
                'cedula_rif': 'V-12345678',
                'telefono': '0412-1234567',
                'email': 'cliente@prueba.com'
            }
        
        # Crear orden de prueba
        orden_id = f"OS-PRUEBA-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        numero_orden = orden_id
        
        nueva_orden = {
            'id': orden_id,
            'numero_orden': numero_orden,
            'fecha_recepcion': datetime.now().strftime('%Y-%m-%d'),
            'fecha_entrega_estimada': (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d'),
            'estado': 'en_reparacion',
            'prioridad': 'media',
            'tipo_servicio': 'Reparación',
            'tecnico_asignado': session.get('username', 'Técnico'),
            'costo_estimado': 100.00,
            
            # Datos del cliente
            'cliente_id': list(clientes.keys())[0] if clientes else 'cliente_prueba',
            'cliente': {
                'nombre': cliente_prueba.get('nombre', 'Cliente de Prueba'),
                'cedula_rif': cliente_prueba.get('cedula_rif', 'V-12345678'),
                'telefono': cliente_prueba.get('telefono', '0412-1234567'),
                'telefono2': '',
                'email': cliente_prueba.get('email', 'cliente@prueba.com'),
                'direccion': cliente_prueba.get('direccion', 'Dirección de prueba')
            },
            
            # Datos del equipo
            'equipo': {
                'marca': 'Samsung',
                'modelo': 'Galaxy S22',
                'imei': '123456789012345',
                'imei2': '',
                'color': 'Negro',
                'numero_serie': 'SN123456',
                'tipo': 'telefono'
            },
            
            # Problema reportado
            'problema_reportado': 'Pantalla rota y batería con fallas',
            'categoria_problema': 'Falla física',
            
            # Diagnóstico completo con repuestos
            'diagnostico': {
                'descripcion_tecnica': 'Se requiere cambio de pantalla y batería',
                'categoria_dano': 'Físico',
                'partes_revisadas': ['Pantalla', 'Batería', 'Cámara'],
                'resultado_diagnostico': 'Equipo requiere reparación',
                'costo_mano_obra': 50.00,
                'costo_piezas': sum([r['precio'] * r['cantidad'] for r in repuestos_disponibles]),
                'total_estimado': 50.00 + sum([r['precio'] * r['cantidad'] for r in repuestos_disponibles]),
                'detalle_repuestos': 'Pantalla y batería para Samsung Galaxy S22',
                'estado_presupuesto': 'aprobado',
                'fecha_diagnostico': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'fecha_presupuesto': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'tecnico_diagnostico': session.get('username', 'Técnico'),
                'repuestos_seleccionados': json.dumps(repuestos_disponibles) if repuestos_disponibles else '[]'
            },
            
            # Historial de estados
            'historial_estados': [
                {
                    'estado': 'en_espera_revision',
                    'fecha': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'usuario': session.get('username', 'Sistema'),
                    'comentarios': 'Orden de servicio creada'
                },
                {
                    'estado': 'en_diagnostico',
                    'fecha': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'usuario': session.get('username', 'Técnico'),
                    'comentarios': 'Diagnóstico completado'
                },
                {
                    'estado': 'presupuesto_enviado',
                    'fecha': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'usuario': session.get('username', 'Técnico'),
                    'comentarios': 'Presupuesto enviado y aprobado'
                },
                {
                    'estado': 'en_reparacion',
                    'fecha': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'usuario': session.get('username', 'Técnico'),
                    'comentarios': 'Presupuesto aprobado - Iniciando reparación'
                }
            ],
            
            # Metadatos
            'fecha_creacion': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'fecha_actualizacion': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # Guardar orden
        ordenes[orden_id] = nueva_orden
        guardar_datos('ordenes_servicio.json', ordenes)
        
        flash(f'Orden de prueba {numero_orden} creada exitosamente con diagnóstico y repuestos', 'success')
        return redirect(url_for('ver_orden_servicio', id=orden_id))
        
    except Exception as e:
        print(f"Error creando orden de prueba: {e}")
        import traceback
        traceback.print_exc()
        flash(f'Error creando orden de prueba: {str(e)}', 'danger')
        return redirect(url_for('servicio_tecnico'))

@app.route('/servicio-tecnico/nueva-orden', methods=['GET', 'POST'])
@login_required
def nueva_orden_servicio():
    """Crear nueva orden de servicio"""
    if request.method == 'GET':
        # Obtener cliente_id si se pasa como parámetro
        cliente_id = request.args.get('cliente_id')
        cliente_data = None
        
        if cliente_id:
            # Cargar datos del cliente para pre-llenar el formulario
            clientes = cargar_datos(ARCHIVO_CLIENTES)
            if clientes and cliente_id in clientes:
                cliente_data = clientes[cliente_id]
        
        return render_template('servicio_tecnico/nueva_orden.html', cliente_data=cliente_data)
    
    if request.method == 'POST':
        try:
            # Validar campos requeridos
            if not request.form.get('cliente_cedula'):
                flash('Error: La cédula/RIF del cliente es requerida', 'danger')
                return render_template('servicio_tecnico/nueva_orden.html')
        
            # Obtener datos del formulario
            datos_orden = {
            'id': f"OS-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            'numero_orden': f"OS-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            'fecha_recepcion': request.form.get('servicio_fecha_ingreso'),
            'fecha_entrega_estimada': request.form.get('servicio_fecha_entrega'),
            'estado': 'borrador' if request.form.get('tipo') == 'borrador' else request.form.get('servicio_estado', 'en_espera_revision'),
            'es_borrador': request.form.get('tipo') == 'borrador',
            'prioridad': request.form.get('servicio_prioridad', 'media'),
            'tipo_servicio': request.form.get('servicio_tipo'),
            'tecnico_asignado': request.form.get('servicio_tecnico', ''),
            'costo_estimado': safe_float(request.form.get('servicio_costo_estimado', 0)) if request.form.get('servicio_costo_estimado') else 0.0,
            
            # Datos del cliente
            'cliente_id': f"cliente_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            'cliente': {
                'id': f"cliente_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                'nombre': request.form.get('cliente_nombre'),
                'cedula_rif': request.form.get('cliente_cedula'),
                'telefono': request.form.get('cliente_telefono'),
                'telefono2': request.form.get('cliente_telefono2', ''),
                'telefono_fijo': '',
                'email': request.form.get('cliente_email', ''),
                'direccion': request.form.get('cliente_direccion', '')
            },
            
            # Datos del equipo
            'equipo': {
                'marca': request.form.get('equipo_marca'),
                'modelo': request.form.get('equipo_modelo'),
                'imei': request.form.get('equipo_imei1'),
                'imei2': request.form.get('equipo_imei2', ''),
                'color': request.form.get('equipo_color', ''),
                'ano': '',
                'numero_serie': request.form.get('equipo_serial', ''),
                'tipo': request.form.get('equipo_tipo', 'telefono')
            },
            
            # Problema reportado
            'problema_reportado': request.form.get('problema_descripcion'),
            'categoria_problema': request.form.get('problema_categoria'),
            'tipo_problema': request.form.get('problema_tipo', ''),
            
            # Accesorios entregados
            'accesorios_entregados': {
                'cargador': 'cargador' in request.form.getlist('accesorios[]'),
                'audifonos': 'audifonos' in request.form.getlist('accesorios[]'),
                'caja': 'caja' in request.form.getlist('accesorios[]'),
                'cable': 'cable' in request.form.getlist('accesorios[]'),
                'tarjeta_memoria': False,
                'capacidad_memoria': '',
                'marca_memoria': '',
                'tipo_memoria': '',
                'sim_card': False,
                'tipo_sim': '',
                'operadora_sim1': '',
                'operadora_sim1_doble': '',
                'operadora_sim2': '',
                'numero_sim1': '',
                'numero_sim1_doble': '',
                'numero_sim2': '',
                'otros': ''
            },
            
            # Condición física
            'condicion_fisica': {
                'rayones': 'rayones' in request.form.getlist('condiciones[]'),
                'golpes': False,
                'pantalla': 'pantalla_rota' in request.form.getlist('condiciones[]'),
                'carcasa': False,
                'botones': False,
                'conectores': False,
                'bateria': 'sin_bateria' in request.form.getlist('condiciones[]'),
                'audio': False,
                'agua': 'agua' in request.form.getlist('condiciones[]'),
                'sobrecalentamiento': False,
                'carcasa_suelta': False,
                'pantalla_parpadea': False,
                'equipo_enciende': True,
                'restauracion_fabrica': False,
                'observaciones': ''
            },
            
            # Diagnóstico inicial
            'diagnostico': {
                'problema_identificado': '',
                'solucion_aplicada': '',
                'piezas_usadas': [],
                'comentarios_tecnicos': request.form.get('observaciones_internas', ''),
                'costo_mano_obra': 0.0,
                'costo_piezas': 0.0,
                'total_estimado': safe_float(request.form.get('servicio_costo_estimado', 0)) if request.form.get('servicio_costo_estimado') else 0.0
            },
            
            # Historial de estados
            'historial_estados': [{
                'estado': request.form.get('servicio_estado', 'en_espera_revision'),
                'fecha': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'usuario': session.get('usuario', 'sistema'),
                'comentarios': 'Orden de servicio creada'
            }],
            
            # Notificaciones
            'notificaciones_enviadas': [],
            'cliente_notificado': 'cliente_notificado' in request.form,
            'whatsapp_enviado': 'whatsapp_enviado' in request.form,
            'atendido_por': request.form.get('atendido_por', ''),
            
            # Datos de desbloqueo
            'desbloqueo': {
                'tipo': request.form.get('tipo_desbloqueo', ''),
                'estado': request.form.get('estado_desbloqueo', ''),
                'clave': request.form.get('clave_desbloqueo', ''),
                'notas': request.form.get('notas_desbloqueo', '')
            },
            
            # Metadatos
            'fecha_creacion': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'fecha_actualizacion': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'nota_entrega_generada': '',
            'urgente': request.form.get('servicio_prioridad') == 'urgente'
            }
        
            # Cargar órdenes existentes
            ordenes = cargar_datos('ordenes_servicio.json')
        
            # Validar que el IMEI esté presente
            if 'equipo' not in datos_orden or 'imei' not in datos_orden['equipo'] or not datos_orden['equipo']['imei']:
                flash('Error: El IMEI del equipo es requerido', 'danger')
                return render_template('servicio_tecnico/nueva_orden.html')
            
            # Verificar duplicados de IMEI
            imei1 = datos_orden['equipo']['imei']
            for orden_id, orden in ordenes.items():
                if isinstance(orden, dict) and 'equipo' in orden and 'imei' in orden['equipo'] and orden['equipo']['imei'] == imei1:
                    estado_orden = orden.get('estado', 'desconocido')
                    if estado_orden not in ['entregado', 'cancelado']:
                        flash(f'Ya existe una orden activa con el IMEI {imei1}: {orden.get("numero_orden", orden_id)}', 'warning')
                        return render_template('servicio_tecnico/nueva_orden.html')
            
            # Guardar nueva orden
            ordenes[datos_orden['id']] = datos_orden
            guardar_datos('ordenes_servicio.json', ordenes)
            
            # Guardar cliente si no existe
            clientes = cargar_datos('clientes.json')
            cliente_existente = False
            
            # Validar que el cliente tenga cedula_rif
            if 'cedula_rif' not in datos_orden['cliente'] or not datos_orden['cliente']['cedula_rif']:
                flash('Error: La cédula/RIF del cliente es requerida', 'danger')
                return render_template('servicio_tecnico/nueva_orden.html')
            
            for cliente_id, cliente in clientes.items():
                if 'cedula_rif' in cliente and cliente['cedula_rif'] == datos_orden['cliente']['cedula_rif']:
                    cliente_existente = True
                    break
            
            if not cliente_existente:
                clientes[datos_orden['cliente']['id']] = datos_orden['cliente']
                guardar_datos('clientes.json', clientes)
            
            # Procesar archivo de foto si existe
            if 'equipo_foto' in request.files:
                foto = request.files['equipo_foto']
                if foto and foto.filename:
                    # Crear directorio si no existe
                    upload_dir = 'uploads/equipos'
                    os.makedirs(upload_dir, exist_ok=True)
                    
                    # Generar nombre único para el archivo
                    filename = f"{datos_orden['id']}_{secure_filename(foto.filename)}"
                    foto_path = os.path.join(upload_dir, filename)
                    foto.save(foto_path)
                    
                    # Actualizar orden con ruta de la foto
                    datos_orden['foto_equipo'] = foto_path
                    ordenes[datos_orden['id']] = datos_orden
                    guardar_datos('ordenes_servicio.json', ordenes)
            
            # Enviar notificación por WhatsApp si está habilitado
            if datos_orden.get('whatsapp_enviado'):
                enviar_notificacion_whatsapp(datos_orden)
            
            if datos_orden.get('es_borrador'):
                flash(f'Borrador de orden {datos_orden["numero_orden"]} guardado exitosamente', 'info')
            else:
                flash(f'Orden de servicio {datos_orden["numero_orden"]} creada exitosamente', 'success')
                return redirect(url_for('servicio_tecnico'))
            
        except Exception as e:
            print(f"Error al crear orden de servicio: {str(e)}")
            flash(f'Error al crear la orden de servicio: {str(e)}', 'danger')
            return render_template('servicio_tecnico/nueva_orden.html')

def enviar_notificacion_whatsapp(orden):
    """Enviar notificación por WhatsApp"""
    try:
        # Asegurar que el estado exista y pueda ser convertido
        estado = orden.get('estado', 'desconocido')
        if isinstance(estado, str):
            estado_formateado = estado.replace('_', ' ').title()
        else:
            estado_formateado = str(estado).replace('_', ' ').title()
        
        mensaje = f"""
🔧 *Nueva Orden de Servicio*

📋 *Orden:* {orden['numero_orden']}
👤 *Cliente:* {orden['cliente']['nombre']}
📱 *Equipo:* {orden['equipo']['marca']} {orden['equipo']['modelo']}
⚠️ *Problema:* {orden['problema_reportado'][:100]}...
📅 *Fecha:* {orden['fecha_recepcion']}
🔧 *Estado:* {estado_formateado}

Gracias por confiar en nuestro servicio técnico.
        """
        
        # Aquí implementarías la lógica de envío de WhatsApp
        # Por ahora solo logueamos
        print(f"Enviando WhatsApp a {orden['cliente']['telefono']}: {mensaje}")
        
    except Exception as e:
        print(f"Error enviando WhatsApp: {str(e)}")
        import traceback
        traceback.print_exc()

@app.route('/servicio-tecnico/orden/<id>')
@login_required
def ver_orden_servicio(id):
    """Ver detalles de una orden de servicio"""
    try:
        ordenes = cargar_datos('ordenes_servicio.json')
        config = cargar_datos('config_servicio_tecnico.json')
        
        if id not in ordenes:
            flash('Orden de servicio no encontrada', 'danger')
            return redirect(url_for('servicio_tecnico'))
        
        orden = ordenes[id]
        
        # Convertir el diccionario a DotDict para que Jinja2 pueda acceder con notación de punto
        orden_normalizado = DotDict(orden)
        
        # Asegurar que 'estado' y otros campos importantes existan
        if 'estado' not in orden_normalizado:
            orden_normalizado['estado'] = 'desconocido'
        
        print(f"DEBUG: Orden normalizada: {orden_normalizado.get('estado')}")
        
        return render_template('servicio_tecnico/ver_orden.html', 
                             orden=orden_normalizado, 
                             config=config)
    except Exception as e:
        print(f"DEBUG: Error en ver_orden_servicio: {str(e)}")
        import traceback
        traceback.print_exc()
        # No mostrar el error al usuario, solo redirigir silenciosamente
        # flash(f'Error cargando orden de servicio: {str(e)}', 'danger')
        return redirect(url_for('servicio_tecnico'))

@app.route('/servicio-tecnico/orden/<id>/seguimiento')
@login_required
def seguimiento_detallado(id):
    """Seguimiento detallado de una orden de servicio"""
    try:
        ordenes = cargar_datos('ordenes_servicio.json')
        config = cargar_datos('config_servicio_tecnico.json')
        
        if id not in ordenes:
            flash('Orden de servicio no encontrada', 'danger')
            return redirect(url_for('servicio_tecnico'))
        
        orden = ordenes[id]
        
        # Convertir el diccionario a DotDict para que Jinja2 pueda acceder con notación de punto
        orden_normalizado = DotDict(orden)
        
        # Asegurar que los campos importantes existan
        if 'estado' not in orden_normalizado:
            orden_normalizado['estado'] = 'desconocido'
        if 'fecha_creacion' not in orden_normalizado:
            orden_normalizado['fecha_creacion'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Calcular progreso basado en el estado
        estados = config.get('estados_servicio', {})
        estados_list = list(estados.keys())
        
        if orden_normalizado.estado in estados_list:
            progreso_porcentaje = ((estados_list.index(orden_normalizado.estado) + 1) / len(estados_list)) * 100
        else:
            progreso_porcentaje = 0
        
        # Calcular métricas adicionales
        fecha_inicio = datetime.strptime(orden_normalizado.fecha_creacion, '%Y-%m-%d %H:%M:%S')
        fecha_actual = datetime.now()
        tiempo_transcurrido = fecha_actual - fecha_inicio
        
        # Calcular alertas automáticas
        alertas = []
        
        # Alerta de retraso en entrega
        if orden_normalizado.get('fecha_entrega_estimada'):
            fecha_entrega = datetime.strptime(orden_normalizado.fecha_entrega_estimada, '%Y-%m-%d')
            if fecha_actual > fecha_entrega:
                dias_retraso = (fecha_actual - fecha_entrega).days
                alertas.append({
                    'tipo': 'danger',
                    'titulo': 'Orden Vencida',
                    'mensaje': f'La orden lleva {dias_retraso} días de retraso',
                    'prioridad': 'alta'
                })
            elif (fecha_entrega - fecha_actual).days <= 1:
                alertas.append({
                    'tipo': 'warning',
                    'titulo': 'Vencimiento Próximo',
                    'mensaje': 'La orden vence mañana',
                    'prioridad': 'media'
                })
        
        # Alerta de técnico no asignado
        if not orden_normalizado.get('tecnico_asignado'):
            alertas.append({
                'tipo': 'warning',
                'titulo': 'Técnico No Asignado',
                'mensaje': 'Esta orden no tiene técnico asignado',
                'prioridad': 'media'
            })
        
        # Alerta de estado estancado
        estados_estancados = ['en_espera_revision', 'en_diagnostico']
        if orden_normalizado.estado in estados_estancados:
            fecha_ultima_actualizacion = datetime.strptime(
                orden_normalizado.get('fecha_actualizacion', orden_normalizado.fecha_creacion), 
                '%Y-%m-%d %H:%M:%S'
            )
            horas_sin_actualizar = (fecha_actual - fecha_ultima_actualizacion).total_seconds() / 3600
            
            if horas_sin_actualizar > 24:
                alertas.append({
                    'tipo': 'info',
                    'titulo': 'Estado Estancado',
                    'mensaje': f'La orden lleva {int(horas_sin_actualizar)} horas en estado "{orden_normalizado.estado.replace("_", " ")}"',
                    'prioridad': 'baja'
                })
        
        # Agregar métricas a la orden
        orden_normalizado['metricas'] = DotDict({
            'dias_transcurridos': tiempo_transcurrido.days,
            'horas_transcurridas': int(tiempo_transcurrido.total_seconds() / 3600),
            'cambios_estado': len(orden_normalizado.get('historial_estados', [])),
            'estado_actual': orden_normalizado.estado,
            'progreso_porcentaje': progreso_porcentaje,
            'alertas': alertas
        })
        
        return render_template('servicio_tecnico/seguimiento_detallado.html', 
                             orden=orden_normalizado, 
                             config_estados=config,
                             progreso_porcentaje=progreso_porcentaje)
    
    except Exception as e:
        print(f"DEBUG: Error en seguimiento_detallado: {str(e)}")
        import traceback
        traceback.print_exc()
        # No mostrar el error al usuario, solo redirigir silenciosamente
        # flash(f'Error cargando seguimiento detallado: {str(e)}', 'danger')
        return redirect(url_for('servicio_tecnico'))

@app.route('/api/servicio-tecnico/orden/<id>/seguimiento')
@login_required
def api_seguimiento_detallado(id):
    """API para obtener datos de seguimiento en tiempo real"""
    try:
        print(f"DEBUG: API seguimiento para orden {id}")
        ordenes = cargar_datos('ordenes_servicio.json')
        config = cargar_datos('config_servicio_tecnico.json')
        
        if id not in ordenes:
            print(f"DEBUG: Orden {id} no encontrada")
            return jsonify({'success': False, 'error': 'Orden no encontrada'}), 404
        
        orden = ordenes[id]
        
        # Calcular métricas actualizadas
        try:
            fecha_inicio = datetime.strptime(orden['fecha_creacion'], '%Y-%m-%d %H:%M:%S')
        except ValueError:
            # Intentar formato alternativo
            try:
                fecha_inicio = datetime.strptime(orden['fecha_creacion'], '%Y-%m-%d')
            except ValueError:
                fecha_inicio = datetime.now()
        
        fecha_actual = datetime.now()
        tiempo_transcurrido = fecha_actual - fecha_inicio
        
        # Calcular progreso
        estados = config.get('estados_servicio', {})
        estados_list = list(estados.keys())
        
        if orden['estado'] in estados_list:
            progreso_porcentaje = ((estados_list.index(orden['estado']) + 1) / len(estados_list)) * 100
        else:
            progreso_porcentaje = 0
        
        # Generar alertas actualizadas
        alertas = []
        
        # Alerta de retraso
        if orden.get('fecha_entrega_estimada'):
            try:
                fecha_entrega = datetime.strptime(orden['fecha_entrega_estimada'], '%Y-%m-%d')
                if fecha_actual > fecha_entrega:
                    dias_retraso = (fecha_actual - fecha_entrega).days
                    alertas.append({
                        'tipo': 'danger',
                        'titulo': 'Orden Vencida',
                        'mensaje': f'La orden lleva {dias_retraso} días de retraso',
                        'prioridad': 'alta'
                    })
            except (ValueError, TypeError) as e:
                print(f"DEBUG: Error parseando fecha_entrega_estimada: {e}")
        
        # Alerta de técnico no asignado
        if not orden.get('tecnico_asignado'):
            alertas.append({
                'tipo': 'warning',
                'titulo': 'Técnico No Asignado',
                'mensaje': 'Esta orden no tiene técnico asignado',
                'prioridad': 'media'
            })
        
        return jsonify({
            'success': True,
            'data': {
                'dias_transcurridos': tiempo_transcurrido.days,
                'horas_transcurridas': int(tiempo_transcurrido.total_seconds() / 3600),
                'progreso_porcentaje': round(progreso_porcentaje, 1),
                'estado_actual': orden['estado'],
                'cambios_estado': len(orden.get('historial_estados', [])),
                'alertas': alertas,
                'ultima_actualizacion': orden.get('fecha_actualizacion', orden['fecha_creacion'])
            }
        })
    
    except Exception as e:
        print(f"DEBUG: Error en API seguimiento: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/servicio-tecnico/orden/<id>/asignar-tecnico', methods=['POST'])
@login_required
def asignar_tecnico_orden(id):
    """Asignar técnico a una orden de servicio"""
    try:
        print(f"DEBUG: Asignando técnico para orden {id}")
        
        ordenes = cargar_datos('ordenes_servicio.json')
        
        if id not in ordenes:
            print(f"DEBUG: Orden {id} no encontrada")
            return jsonify({'success': False, 'message': 'Orden de servicio no encontrada'}), 404
        
        # Obtener datos del formulario
        data = request.get_json()
        tecnico_nombre = data.get('tecnico_nombre', '').strip()
        tecnico_especialidad = data.get('tecnico_especialidad', '')
        tecnico_telefono = data.get('tecnico_telefono', '').strip()
        tecnico_email = data.get('tecnico_email', '').strip()
        observaciones = data.get('observaciones', '').strip()
        
        print(f"DEBUG: Datos recibidos - Nombre: {tecnico_nombre}, Especialidad: {tecnico_especialidad}")
        
        # Validar datos requeridos
        if not tecnico_nombre:
            return jsonify({'success': False, 'message': 'El nombre del técnico es requerido'}), 400
        
        # Actualizar datos del técnico en la orden
        ordenes[id]['tecnico_asignado'] = tecnico_nombre
        ordenes[id]['fecha_actualizacion'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Agregar información adicional del técnico
        if 'tecnico_info' not in ordenes[id]:
            ordenes[id]['tecnico_info'] = {}
        
        ordenes[id]['tecnico_info'].update({
            'especialidad': tecnico_especialidad,
            'telefono': tecnico_telefono,
            'email': tecnico_email,
            'fecha_asignacion': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        
        # Inicializar historial si no existe
        if 'historial_estados' not in ordenes[id]:
            ordenes[id]['historial_estados'] = []
        
        # Agregar entrada al historial
        historial_entry = {
            "accion": "asignacion_tecnico",
            "descripcion": f"Técnico asignado: {tecnico_nombre}",
            "fecha": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "usuario": session.get('username', session.get('usuario', 'admin')),
            "detalles": {
                "tecnico_nombre": tecnico_nombre,
                "especialidad": tecnico_especialidad,
                "telefono": tecnico_telefono,
                "email": tecnico_email,
                "observaciones": observaciones
            }
        }
        
        ordenes[id]['historial_estados'].append(historial_entry)
        
        # Guardar cambios
        guardar_datos('ordenes_servicio.json', ordenes)
        
        print(f"DEBUG: Técnico asignado exitosamente: {tecnico_nombre}")
        
        return jsonify({
            'success': True,
            'message': f'Técnico {tecnico_nombre} asignado exitosamente',
            'tecnico_nombre': tecnico_nombre,
            'fecha_asignacion': ordenes[id]['fecha_actualizacion']
        })
        
    except Exception as e:
        print(f"DEBUG: Error asignando técnico: {str(e)}")
        import traceback
        traceback.print_exc()
        
        return jsonify({'success': False, 'message': f'Error asignando técnico: {str(e)}'}), 500

@app.route('/servicio-tecnico/orden/<id>/actualizar-estado', methods=['POST'])
@login_required
def actualizar_estado_orden(id):
    """Actualizar estado de una orden de servicio"""
    try:
        print(f"DEBUG: Actualizando estado para orden {id}")
        
        ordenes = cargar_datos('ordenes_servicio.json')
        config = cargar_datos('config_servicio_tecnico.json')
        
        # Detectar si es petición AJAX
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.headers.get('Content-Type') == 'application/json'
        
        if id not in ordenes:
            print(f"DEBUG: Orden {id} no encontrada")
            if is_ajax:
                return jsonify({'success': False, 'message': 'Orden de servicio no encontrada'}), 404
            flash('Orden de servicio no encontrada', 'danger')
            return redirect(url_for('servicio_tecnico'))
        
        # Manejar tanto JSON como form data
        if request.headers.get('Content-Type') == 'application/json':
            data = request.get_json()
            nuevo_estado = data.get('estado')
            comentarios = data.get('observaciones', '')
            tecnico_asignado = data.get('tecnico_asignado', '')
            prioridad = data.get('prioridad', '')
            fecha_entrega_estimada = data.get('fecha_entrega_estimada', '')
        else:
            nuevo_estado = request.form.get('nuevo_estado')
            comentarios = request.form.get('comentarios', '')
            tecnico_asignado = request.form.get('tecnico_asignado', '')
            prioridad = request.form.get('prioridad', '')
            fecha_entrega_estimada = request.form.get('fecha_entrega_estimada', '')
        
        print(f"DEBUG: Nuevo estado: {nuevo_estado}")
        print(f"DEBUG: Comentarios: {comentarios}")
        print(f"DEBUG: Técnico: {tecnico_asignado}")
        print(f"DEBUG: Prioridad: {prioridad}")
        
        # Validar que el estado no esté vacío
        if not nuevo_estado:
            if is_ajax:
                return jsonify({'success': False, 'message': 'Estado requerido'}), 400
            flash('Estado requerido', 'danger')
            return redirect(url_for('ver_orden_servicio', id=id))
        
        # Validar que el estado exista en la configuración
        estados_servicio = config.get('estados_servicio', {})
        if nuevo_estado not in estados_servicio:
            mensaje = f'Estado "{nuevo_estado}" no existe en la configuración'
            if is_ajax:
                return jsonify({'success': False, 'message': mensaje}), 400
            flash(mensaje, 'danger')
            return redirect(url_for('ver_orden_servicio', id=id))
        
        # Obtener estado anterior y configuración del nuevo estado
        estado_anterior = ordenes[id].get('estado', '')
        estado_config = estados_servicio[nuevo_estado]
        
        # Validar transición de estado (si el estado anterior tiene siguiente_estado definido)
        if estado_anterior and estado_anterior in estados_servicio:
            estado_anterior_config = estados_servicio[estado_anterior]
            siguiente_estado_valido = estado_anterior_config.get('siguiente_estado')
            
            # Si hay un siguiente_estado definido y no es el que se intenta cambiar, verificar si es un cambio regresivo permitido
            if siguiente_estado_valido and siguiente_estado_valido != nuevo_estado:
                # Permitir cambiar al mismo estado (no es un cambio real)
                if estado_anterior != nuevo_estado:
                    # Verificar si es un cambio regresivo permitido (puede estar configurado)
                    # Por ahora, solo permitimos cambios válidos hacia adelante o estados finales
                    # Se puede mejorar agregando una lista de estados_permitidos en la configuración
                    print(f"DEBUG: Transición de '{estado_anterior}' a '{nuevo_estado}' - siguiente válido: '{siguiente_estado_valido}'")
        
        # Verificar permisos según configuración de estados (usando config_sistema si está disponible)
        config_sistema = cargar_configuracion()
        estados_config_sistema = config_sistema.get('estados_ordenes', {})
        estado_config_sistema = estados_config_sistema.get(nuevo_estado, {})
        
        # Verificar si requiere admin
        if estado_config_sistema.get('requiere_admin', False):
            # Verificar si el usuario actual es admin
            usuarios = cargar_datos('usuarios.json')
            username = session.get('username', session.get('usuario', ''))
            usuario_actual = usuarios.get(username, {})
            rol_actual = usuario_actual.get('rol', 'vendedor')
            
            if rol_actual != 'admin':
                mensaje = f'Se requieren permisos de administrador para cambiar a estado: {estado_config.get("nombre", nuevo_estado.replace("_", " ").title())}'
                if is_ajax:
                    return jsonify({'success': False, 'message': mensaje}), 403
                flash(mensaje, 'danger')
                return redirect(url_for('ver_orden_servicio', id=id))
        
        # Verificar si requiere comentario obligatorio
        if estado_config_sistema.get('comentario_obligatorio', False) and not comentarios:
            mensaje = 'Se requiere un comentario para cambiar a este estado'
            if is_ajax:
                return jsonify({'success': False, 'message': mensaje}), 400
            flash(mensaje, 'warning')
            return redirect(url_for('ver_orden_servicio', id=id))
        
        # VALIDACIONES ESPECIALES ANTES DE CAMBIAR EL ESTADO
        # Validar diagnóstico antes de permitir cambiar a "en_reparacion"
        if nuevo_estado == 'en_reparacion':
            if 'diagnostico' not in ordenes[id] or not ordenes[id].get('diagnostico'):
                mensaje = 'Se requiere diagnóstico antes de marcar como en reparación'
                if is_ajax:
                    return jsonify({'success': False, 'message': mensaje}), 400
                flash(mensaje, 'warning')
                return redirect(url_for('ver_orden_servicio', id=id))
        
        # Validar datos de entrega antes de permitir cambiar a "entregado"
        elif nuevo_estado == 'entregado':
            if 'entrega' not in ordenes[id] or not ordenes[id].get('entrega'):
                mensaje = 'Se requiere completar el proceso de entrega antes de marcar como entregado'
                if is_ajax:
                    return jsonify({'success': False, 'message': mensaje}), 400
                flash(mensaje, 'warning')
                return redirect(url_for('ver_orden_servicio', id=id))
        
        # Si todas las validaciones pasan, proceder a actualizar el estado
        ordenes[id]['estado'] = nuevo_estado
        ordenes[id]['fecha_actualizacion'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Actualizar campos adicionales si se proporcionan
        if tecnico_asignado:
            ordenes[id]['tecnico_asignado'] = tecnico_asignado
        if prioridad:
            ordenes[id]['prioridad'] = prioridad
        if fecha_entrega_estimada:
            ordenes[id]['fecha_entrega_estimada'] = fecha_entrega_estimada
        
        # Inicializar historial si no existe
        if 'historial_estados' not in ordenes[id]:
            ordenes[id]['historial_estados'] = []
        
        # Agregar al historial
        historial_entry = {
            "estado": nuevo_estado,
            "fecha": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "usuario": session.get('username', session.get('usuario', 'admin')),
            "comentarios": comentarios
        }
        
        # Agregar información adicional al historial
        if tecnico_asignado:
            historial_entry["tecnico_asignado"] = tecnico_asignado
        if prioridad:
            historial_entry["prioridad"] = prioridad
        if fecha_entrega_estimada:
            historial_entry["fecha_entrega_estimada"] = fecha_entrega_estimada
        
        ordenes[id]['historial_estados'].append(historial_entry)
        
        # Guardar cambios
        guardar_datos('ordenes_servicio.json', ordenes)
        
        # Enviar notificación al cliente si está configurado
        if estado_config_sistema.get('notificar_cliente', False):
            try:
                # Obtener datos del cliente
                cliente = ordenes[id].get('cliente', {})
                if cliente and cliente.get('whatsapp'):
                    # Aquí puedes implementar la lógica de notificación por WhatsApp
                    print(f"📱 Notificación enviada a cliente por cambio de estado: {nuevo_estado}")
            except Exception as e:
                print(f"⚠️ Error enviando notificación: {e}")
        
        # Obtener nombre del estado para mostrar
        nombre_estado = estado_config.get('nombre', nuevo_estado.replace('_', ' ').title())
        
        print(f"DEBUG: Estado actualizado exitosamente a: {nombre_estado}")
        
        # Respuesta JSON para AJAX
        if is_ajax:
            return jsonify({
                'success': True,
                'message': f'Estado actualizado a: {nombre_estado}',
                'nuevo_estado': nuevo_estado,
                'estado_anterior': estado_anterior,
                'fecha_actualizacion': ordenes[id]['fecha_actualizacion']
            })
        
        # Respuesta HTML para form submission
        flash(f'Estado actualizado a: {nombre_estado}', 'success')
        return redirect(url_for('ver_orden_servicio', id=id))
        
    except Exception as e:
        print(f"DEBUG: Error actualizando estado: {str(e)}")
        import traceback
        traceback.print_exc()
        
        # Detectar si es petición AJAX (puede que is_ajax no esté definido si falla antes)
        is_ajax_error = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.headers.get('Content-Type') == 'application/json'
        
        if is_ajax_error:
            return jsonify({'success': False, 'message': f'Error actualizando estado: {str(e)}'}), 500
        
        flash(f'Error actualizando estado: {str(e)}', 'danger')
        return redirect(url_for('ver_orden_servicio', id=id))

@app.route('/servicio-tecnico/orden/<id>/diagnostico', methods=['GET', 'POST'])
@login_required
def diagnostico_orden(id):
    """Realizar diagnóstico de una orden de servicio"""
    try:
        ordenes = cargar_datos('ordenes_servicio.json')
        inventario = cargar_datos('inventario.json')
        
        if id not in ordenes:
            flash('Orden de servicio no encontrada', 'danger')
            return redirect(url_for('servicio_tecnico'))
        
        if request.method == 'POST':
            print(f"DEBUG: Procesando diagnóstico para orden {id}")
            print(f"DEBUG: Headers: {dict(request.headers)}")
            print(f"DEBUG: Content-Type: {request.headers.get('Content-Type')}")
            print(f"DEBUG: X-Requested-With: {request.headers.get('X-Requested-With')}")
            print(f"DEBUG: Form data: {dict(request.form)}")
            
            # Obtener datos del formulario
            descripcion_tecnica = request.form.get('descripcion_tecnica', '')
            categoria_dano = request.form.get('categoria_dano', '')
            partes_revisadas = request.form.getlist('partes_revisadas')
            resultado_diagnostico = request.form.get('resultado_diagnostico', '')
            costo_mano_obra = safe_float(request.form.get('costo_mano_obra', 0))
            costo_piezas = safe_float(request.form.get('costo_piezas', 0))
            total_estimado = safe_float(request.form.get('total_estimado', 0))
            detalle_repuestos = request.form.get('detalle_repuestos', '')
            estado_presupuesto = request.form.get('estado_presupuesto', 'pendiente')
            
            # Obtener repuestos seleccionados (si vienen del modal)
            repuestos_seleccionados = []
            if 'repuestos_seleccionados' in request.form:
                try:
                    repuestos_str = request.form.get('repuestos_seleccionados', '[]')
                    # Si ya es una lista (por algún error), usarla directamente
                    if isinstance(repuestos_str, list):
                        repuestos_seleccionados = repuestos_str
                    else:
                        repuestos_seleccionados = json.loads(repuestos_str)
                    # Validar que sea una lista
                    if not isinstance(repuestos_seleccionados, list):
                        print(f"DEBUG: Advertencia - repuestos_seleccionados no es lista: {type(repuestos_seleccionados)}")
                        repuestos_seleccionados = []
                except json.JSONDecodeError as e:
                    print(f"DEBUG: Error parseando repuestos_seleccionados: {e}")
                    repuestos_seleccionados = []
                except Exception as e:
                    print(f"DEBUG: Error inesperado con repuestos_seleccionados: {e}")
                    repuestos_seleccionados = []
            
            print(f"DEBUG: Datos procesados:")
            print(f"  - Descripción: '{descripcion_tecnica[:50]}...'")
            print(f"  - Categoría: '{categoria_dano}'")
            print(f"  - Partes revisadas: {partes_revisadas}")
            print(f"  - Resultado: '{resultado_diagnostico}'")
            print(f"  - Costo mano obra: {costo_mano_obra}")
            print(f"  - Costo piezas: {costo_piezas}")
            print(f"  - Total estimado: {total_estimado}")
            
            # Inicializar diagnóstico si no existe
            if 'diagnostico' not in ordenes[id]:
                ordenes[id]['diagnostico'] = {}
            
            # Actualizar diagnóstico (preservar datos anteriores si existen)
            diagnostico_actual = ordenes[id]['diagnostico']
            diagnostico_actual.update({
                "descripcion_tecnica": descripcion_tecnica,
                "categoria_dano": categoria_dano,
                "partes_revisadas": partes_revisadas,
                "resultado_diagnostico": resultado_diagnostico,
                "costo_mano_obra": costo_mano_obra,
                "costo_piezas": costo_piezas,
                "total_estimado": total_estimado,
                "detalle_repuestos": detalle_repuestos,
                "estado_presupuesto": estado_presupuesto,
                "fecha_diagnostico": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "tecnico_diagnostico": session.get('usuario', session.get('username', 'Técnico'))
            })
            
            # Guardar repuestos seleccionados como JSON string solo si hay repuestos
            if repuestos_seleccionados:
                try:
                    # Si ya está en string, no volver a serializar
                    if isinstance(repuestos_seleccionados, str):
                        diagnostico_actual["repuestos_seleccionados"] = repuestos_seleccionados
                    else:
                        diagnostico_actual["repuestos_seleccionados"] = json.dumps(repuestos_seleccionados)
                except Exception as e:
                    print(f"DEBUG: Error serializando repuestos: {e}")
                    diagnostico_actual["repuestos_seleccionados"] = "[]"
            else:
                # Si no hay repuestos pero hay detalle en texto, mantener el campo vacío
                diagnostico_actual["repuestos_seleccionados"] = "[]"
            
            ordenes[id]['diagnostico'] = diagnostico_actual
            
            # Procesar fotos del diagnóstico
            if 'fotos_diagnostico' in request.files:
                fotos = request.files.getlist('fotos_diagnostico')
                fotos_paths = []
                
                for foto in fotos:
                    if foto and foto.filename:
                        # Crear directorio si no existe
                        upload_folder = os.path.join(app.root_path, 'uploads', id, 'diagnostico')
                        os.makedirs(upload_folder, exist_ok=True)
                        
                        filename = secure_filename(foto.filename)
                        filepath = os.path.join(upload_folder, filename)
                        foto.save(filepath)
                        fotos_paths.append(f'/uploads/{id}/diagnostico/{filename}')
                
                if fotos_paths:
                    ordenes[id]['diagnostico']['fotos'] = fotos_paths
            
            # Determinar nuevo estado basado en el resultado del diagnóstico
            nuevo_estado = ordenes[id]['estado']
            if resultado_diagnostico == 'reparado':
                nuevo_estado = 'reparado'
            elif resultado_diagnostico == 'reparable':
                nuevo_estado = 'presupuesto_enviado'
            elif resultado_diagnostico == 'irreparable':
                nuevo_estado = 'irreparable'
            elif resultado_diagnostico == 'espera_aprobacion':
                nuevo_estado = 'espera_aprobacion'
            
            print(f"DEBUG: Resultado diagnóstico: '{resultado_diagnostico}', Nuevo estado: '{nuevo_estado}'")
            
            # Actualizar estado
            ordenes[id]['estado'] = nuevo_estado
            ordenes[id]['fecha_actualizacion'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # Inicializar historial si no existe
            if 'historial_estados' not in ordenes[id]:
                ordenes[id]['historial_estados'] = []
            
            # Agregar entrada al historial
            comentario_historial = f"Diagnóstico completado - Resultado: {resultado_diagnostico}"
            if repuestos_seleccionados:
                comentario_historial += f" - {len(repuestos_seleccionados)} repuesto(s) seleccionado(s)"
            
            ordenes[id]['historial_estados'].append({
                "estado": nuevo_estado,
                "fecha": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "usuario": session.get('usuario', session.get('username', 'Técnico')),
                "comentarios": comentario_historial
            })
            
            guardar_datos('ordenes_servicio.json', ordenes)
            print(f"DEBUG: Diagnóstico guardado exitosamente. Nuevo estado: {nuevo_estado}")
            
            # Respuesta JSON para AJAX
            print(f"DEBUG: X-Requested-With: {request.headers.get('X-Requested-With')}")
            print(f"DEBUG: ajax form param: {request.form.get('ajax')}")
            print(f"DEBUG: Content-Type: {request.headers.get('Content-Type')}")
            
            if (request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 
                request.form.get('ajax')):
                print("DEBUG: Enviando respuesta JSON para AJAX")
                return jsonify({
                    'success': True,
                    'message': 'Diagnóstico guardado exitosamente',
                    'nuevo_estado': nuevo_estado
                })
            
            print("DEBUG: Enviando respuesta HTML (no AJAX)")
            flash('Diagnóstico completado exitosamente', 'success')
            return redirect(url_for('ver_orden_servicio', id=id))
        
        orden = ordenes[id]
        return render_template('servicio_tecnico/diagnostico.html', 
                             orden=orden, 
                             inventario=inventario)
        
    except Exception as e:
        print(f"DEBUG: Error en diagnóstico: {str(e)}")
        print(f"DEBUG: X-Requested-With: {request.headers.get('X-Requested-With')}")
        print(f"DEBUG: ajax form param: {request.form.get('ajax')}")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.form.get('ajax'):
            print("DEBUG: Enviando respuesta JSON de error para AJAX")
            return jsonify({
                'success': False,
                'message': f'Error en diagnóstico: {str(e)}'
            })
        
        flash(f'Error en diagnóstico: {str(e)}', 'danger')
        return redirect(url_for('servicio_tecnico'))

@app.route('/servicio-tecnico/orden/<id>/diagnostico-pdf')
@login_required
def diagnostico_pdf(id):
    """Generar PDF del diagnóstico técnico detallado"""
    try:
        ordenes = cargar_datos('ordenes_servicio.json')
        
        if id not in ordenes:
            flash('Orden de servicio no encontrada', 'danger')
            return redirect(url_for('servicio_tecnico'))
        
        orden = ordenes[id]
        
        # Fecha actual para el PDF
        fecha_actual = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        
        # Renderizar template HTML con estilos optimizados para impresión
        return render_template('servicio_tecnico/diagnostico_pdf.html', 
                             orden=orden, 
                             fecha_actual=fecha_actual)
        
    except Exception as e:
        flash(f'Error generando PDF: {str(e)}', 'danger')
        return redirect(url_for('diagnostico_orden', id=id))

@app.route('/servicio-tecnico/orden/<id>/presupuesto-pdf')
@login_required
def presupuesto_pdf(id):
    """Generar PDF del presupuesto/cotización"""
    try:
        ordenes = cargar_datos('ordenes_servicio.json')
        
        if id not in ordenes:
            flash('Orden de servicio no encontrada', 'danger')
            return redirect(url_for('servicio_tecnico'))
        
        orden = ordenes[id]
        
        # Fecha actual para el PDF
        fecha_actual = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        
        # Obtener tasa BCV actual
        tasa_bcv = obtener_tasa_bcv()
        if not tasa_bcv or tasa_bcv <= 0:
            tasa_bcv = 216.37  # Tasa de fallback
        
        # Renderizar template HTML con estilos optimizados para impresión
        return render_template('servicio_tecnico/presupuesto_pdf.html', 
                             orden=orden, 
                             fecha_actual=fecha_actual,
                             tasa_bcv=tasa_bcv)
        
    except Exception as e:
        flash(f'Error generando PDF: {str(e)}', 'danger')
        return redirect(url_for('presupuesto_servicio', id=id))

@app.route('/servicio-tecnico/orden/<id>/presupuesto', methods=['GET', 'POST'])
@login_required
def presupuesto_servicio(id):
    """Generar y guardar presupuesto para una orden de servicio"""
    try:
        ordenes = cargar_datos('ordenes_servicio.json')
        
        if id not in ordenes:
            return jsonify({'success': False, 'message': 'Orden no encontrada'})
        
        if request.method == 'POST':
            # Actualizar presupuesto
            if 'diagnostico' not in ordenes[id]:
                ordenes[id]['diagnostico'] = {}
            
            # Obtener repuestos seleccionados
            repuestos_seleccionados = []
            if 'repuestos_seleccionados' in request.form:
                try:
                    import json
                    repuestos_seleccionados = json.loads(request.form.get('repuestos_seleccionados', '[]'))
                except:
                    repuestos_seleccionados = []
            
            ordenes[id]['diagnostico'].update({
                'costo_mano_obra': safe_float(request.form.get('costo_mano_obra', 0)),
                'costo_piezas': safe_float(request.form.get('costo_piezas', 0)),
                'total_estimado': safe_float(request.form.get('total_estimado', 0)),
                'detalle_repuestos': request.form.get('detalle_repuestos', ''),
                'estado_presupuesto': request.form.get('estado_presupuesto', 'pendiente'),
                'repuestos_seleccionados': json.dumps(repuestos_seleccionados),
                'fecha_presupuesto': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            
            # Si se aprueba el presupuesto, cambiar estado
            if request.form.get('estado_presupuesto') == 'aprobado':
                # Validar stock de repuestos antes de aprobar
                if repuestos_seleccionados:
                    print(f"DEBUG: Validando stock para {len(repuestos_seleccionados)} repuestos")
                    stock_ok, problemas = validar_stock_repuestos(repuestos_seleccionados)
                    
                    if not stock_ok:
                        print(f"DEBUG: ❌ Stock insuficiente: {problemas}")
                        return jsonify({
                            'success': False, 
                            'message': 'Stock insuficiente para aprobar presupuesto',
                            'problemas': problemas
                        })
                    
                    # Descontar repuestos del inventario
                    print(f"DEBUG: Descontando repuestos del inventario")
                    exito, mensaje = descontar_repuestos_inventario(id, repuestos_seleccionados)
                    
                    if not exito:
                        print(f"DEBUG: ❌ Error descontando repuestos: {mensaje}")
                        return jsonify({
                            'success': False, 
                            'message': f'Error descontando repuestos: {mensaje}'
                        })
                    
                    print(f"DEBUG: ✅ Repuestos descontados exitosamente: {mensaje}")
                
                # Cambiar estado a en_reparacion
                ordenes[id]['estado'] = 'en_reparacion'
                ordenes[id]['fecha_actualizacion'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                # Agregar al historial
                if 'historial_estados' not in ordenes[id]:
                    ordenes[id]['historial_estados'] = []
                
                comentario_historial = "Presupuesto aprobado - Iniciando reparación"
                if repuestos_seleccionados:
                    comentario_historial += f" - {len(repuestos_seleccionados)} repuestos descontados del inventario"
                
                ordenes[id]['historial_estados'].append({
                    "estado": "en_reparacion",
                    "fecha": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    "usuario": session.get('username', 'Técnico'),
                    "comentarios": comentario_historial
                })
            
            guardar_datos('ordenes_servicio.json', ordenes)
            return jsonify({'success': True, 'message': 'Presupuesto guardado exitosamente'})
        
        # GET - Mostrar presupuesto
        orden = ordenes[id]
        return render_template('servicio_tecnico/presupuesto.html', orden=orden)
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error: {str(e)}'})

@app.route('/servicio-tecnico/orden/<id>/reparacion', methods=['GET', 'POST'])
@login_required
def reparacion_orden(id):
    """Módulo de reparación del equipo"""
    try:
        print(f"DEBUG: Entrando a reparacion_orden para orden {id}")
        ordenes = cargar_datos('ordenes_servicio.json')
        inventario = cargar_datos('inventario.json')
        
        if id not in ordenes:
            print(f"DEBUG: Orden {id} no encontrada")
            # No mostrar el error al usuario
            return redirect(url_for('servicio_tecnico'))
        
        if request.method == 'POST':
            try:
                print(f"DEBUG: Procesando POST para orden {id}")
                # Procesar formulario de reparación
                acciones_realizadas = request.form.get('acciones_realizadas', '')
                resultado_pruebas = request.form.get('resultado_pruebas', '')
                observaciones_finales = request.form.get('observaciones_finales', '')
                tecnico_responsable = request.form.get('tecnico_responsable', session.get('usuario', session.get('username', 'Técnico')))
                fecha_inicio = request.form.get('fecha_inicio', '')
                fecha_fin = request.form.get('fecha_fin', '')
                
                # Procesar repuestos usados (si se envían desde el formulario)
                repuestos_usados = request.form.getlist('repuestos_usados')
                cantidades = request.form.getlist('cantidades_repuestos')
                costos_unitarios = request.form.getlist('costos_unitarios')
                
                repuestos_detalle = []
                total_repuestos = 0
                
                if repuestos_usados:
                    for i, repuesto_id in enumerate(repuestos_usados):
                        if repuesto_id and i < len(cantidades) and i < len(costos_unitarios):
                            try:
                                cantidad = int(cantidades[i]) if cantidades[i] else 0
                                costo_unitario = safe_float(costos_unitarios[i]) if costos_unitarios[i] else 0
                                
                                if cantidad > 0 and costo_unitario > 0:
                                    repuesto_info = inventario.get(repuesto_id, {})
                                    repuestos_detalle.append({
                                        'id': repuesto_id,
                                        'nombre': repuesto_info.get('nombre', 'Repuesto desconocido'),
                                        'cantidad': cantidad,
                                        'costo_unitario': costo_unitario,
                                        'subtotal': cantidad * costo_unitario
                                    })
                                    total_repuestos += cantidad * costo_unitario
                                    
                                    # Validar stock antes de descontar
                                    if repuesto_id in inventario:
                                        stock_actual = inventario[repuesto_id].get('cantidad', 0)
                                        if stock_actual < cantidad:
                                            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                                                return jsonify({
                                                    'success': False,
                                                    'message': f'Stock insuficiente para {repuesto_info.get("nombre", repuesto_id)}. Disponible: {stock_actual}, Requerido: {cantidad}'
                                                }), 400
                                            flash(f'Stock insuficiente para {repuesto_info.get("nombre", repuesto_id)}. Disponible: {stock_actual}', 'danger')
                                            return redirect(url_for('reparacion_orden', id=id))
                                        
                                        # Descontar del inventario
                                        inventario[repuesto_id]['cantidad'] = max(0, stock_actual - cantidad)
                            except (ValueError, TypeError) as e:
                                print(f"DEBUG: Error al procesar repuesto {i}: {str(e)}")
                                continue
                
                # Inicializar reparación si no existe
                if 'reparacion' not in ordenes[id]:
                    ordenes[id]['reparacion'] = {}
                
                # Preservar datos anteriores (como fotos)
                reparacion_actual = ordenes[id]['reparacion']
                
                # Actualizar datos de reparación
                reparacion_actual.update({
                    'acciones_realizadas': acciones_realizadas,
                    'resultado_pruebas': resultado_pruebas,
                    'observaciones_finales': observaciones_finales,
                    'tecnico_responsable': tecnico_responsable,
                    'fecha_inicio': fecha_inicio,
                    'fecha_fin': fecha_fin,
                    'fecha_actualizacion': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })
                
                # Si hay repuestos, agregarlos
                if repuestos_detalle:
                    if 'repuestos_usados' in reparacion_actual:
                        # Combinar con repuestos anteriores
                        repuestos_anteriores = reparacion_actual.get('repuestos_usados', [])
                        # Evitar duplicados
                        ids_existentes = {r.get('id') for r in repuestos_anteriores}
                        for repuesto in repuestos_detalle:
                            if repuesto['id'] not in ids_existentes:
                                repuestos_anteriores.append(repuesto)
                                ids_existentes.add(repuesto['id'])
                        reparacion_actual['repuestos_usados'] = repuestos_anteriores
                    else:
                        reparacion_actual['repuestos_usados'] = repuestos_detalle
                    
                    reparacion_actual['total_repuestos'] = total_repuestos
                
                ordenes[id]['reparacion'] = reparacion_actual
                
                # Actualizar estado según la acción
                accion = request.form.get('accion')
                nuevo_estado = ordenes[id]['estado']
                
                # Solo cambiar estado si no es 'guardar'
                if accion == 'en_pruebas':
                    nuevo_estado = 'en_pruebas'
                elif accion == 'reparado':
                    nuevo_estado = 'reparado'
                elif accion == 'listo_entrega':
                    nuevo_estado = 'listo_entrega'
                elif accion == 'guardar':
                    # Mantener el estado actual al guardar
                    pass
                
                ordenes[id]['estado'] = nuevo_estado
                ordenes[id]['fecha_actualizacion'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                # Inicializar historial si no existe
                if 'historial_estados' not in ordenes[id]:
                    ordenes[id]['historial_estados'] = []
                
                # Agregar al historial
                comentario_historial = f"Reparación actualizada - Estado: {nuevo_estado.replace('_', ' ').title()}"
                if repuestos_detalle:
                    comentario_historial += f" - {len(repuestos_detalle)} repuesto(s) utilizado(s)"
                
                ordenes[id]['historial_estados'].append({
                    "estado": nuevo_estado,
                    "fecha": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    "usuario": session.get('usuario', session.get('username', 'Técnico')),
                    "comentarios": comentario_historial
                })
                
                # Guardar cambios
                guardar_datos('ordenes_servicio.json', ordenes)
                if repuestos_detalle:
                    guardar_datos('inventario.json', inventario)
                
                print(f"DEBUG: Estado actualizado a {nuevo_estado}")
                
                # Respuesta JSON para AJAX
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({
                        'success': True,
                        'message': 'Reparación actualizada exitosamente',
                        'nuevo_estado': nuevo_estado
                    })
                
                flash('Reparación actualizada exitosamente', 'success')
                return redirect(url_for('ver_orden_servicio', id=id))
            except Exception as e:
                print(f"DEBUG: Error procesando POST: {str(e)}")
                import traceback
                traceback.print_exc()
                
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({
                        'success': False,
                        'message': f'Error: {str(e)}'
                    }), 500
                
                flash(f'Error actualizando reparación: {str(e)}', 'danger')
                return redirect(url_for('ver_orden_servicio', id=id))
        
        orden = ordenes[id]
        
        # Convertir a DotDict recursivamente
        print(f"DEBUG: Convirtiendo orden {id} a DotDict")
        orden_normalizado = DotDict(orden)
        
        # Asegurar campos críticos
        if 'estado' not in orden_normalizado:
            orden_normalizado['estado'] = 'desconocido'
        if 'id' not in orden_normalizado:
            orden_normalizado['id'] = id
        
        print(f"DEBUG: Orden normalizada - Estado: {orden_normalizado.get('estado')}")
        print(f"DEBUG: Cliente existe: {hasattr(orden_normalizado, 'cliente')}")
        print(f"DEBUG: Equipo existe: {hasattr(orden_normalizado, 'equipo')}")
        
        # Verificar que orden sea un DotDict completo
        if isinstance(orden_normalizado, DotDict):
            print(f"DEBUG: orden_normalizado es DotDict")
        else:
            print(f"DEBUG: ERROR - orden_normalizado NO es DotDict, es: {type(orden_normalizado)}")
        
        # Cargar datos de reparación existentes si existen
        repuestos_existentes = []
        if orden.get('reparacion') and orden['reparacion'].get('repuestos_usados'):
            repuestos_existentes = orden['reparacion']['repuestos_usados']
            print(f"DEBUG: Repuestos existentes en reparación: {len(repuestos_existentes)}")
        
        # Obtener repuestos seleccionados en el diagnóstico
        repuestos_diagnostico = []
        if orden.get('diagnostico'):
            diagnostico = orden['diagnostico']
            print(f"DEBUG: Diagnóstico encontrado. Keys: {diagnostico.keys() if isinstance(diagnostico, dict) else 'N/A'}")
            
            if isinstance(diagnostico, dict) and diagnostico.get('repuestos_seleccionados'):
                repuestos_str = diagnostico['repuestos_seleccionados']
                print(f"DEBUG: repuestos_seleccionados encontrado. Tipo: {type(repuestos_str)}, Valor: {repuestos_str[:100] if isinstance(repuestos_str, str) else repuestos_str}")
                
                try:
                    # Si ya es una lista, usarla directamente
                    if isinstance(repuestos_str, list):
                        repuestos_diagnostico = repuestos_str
                        print(f"DEBUG: repuestos_seleccionados ya es una lista: {len(repuestos_diagnostico)}")
                    elif isinstance(repuestos_str, str):
                        # Intentar parsear como JSON
                        repuestos_diagnostico = json.loads(repuestos_str)
                        print(f"DEBUG: repuestos_seleccionados parseado como JSON: {len(repuestos_diagnostico)}")
                    else:
                        print(f"DEBUG: repuestos_seleccionados tiene tipo inesperado: {type(repuestos_str)}")
                        repuestos_diagnostico = []
                    
                    # Validar que sea una lista
                    if not isinstance(repuestos_diagnostico, list):
                        print(f"DEBUG: Advertencia - repuestos_diagnostico no es lista: {type(repuestos_diagnostico)}")
                        repuestos_diagnostico = []
                    
                    print(f"DEBUG: Repuestos del diagnóstico finales: {len(repuestos_diagnostico)} repuestos")
                    if repuestos_diagnostico:
                        print(f"DEBUG: Primer repuesto: {repuestos_diagnostico[0]}")
                except json.JSONDecodeError as e:
                    print(f"DEBUG: Error JSON cargando repuestos del diagnóstico: {e}")
                    print(f"DEBUG: String que falló: {repuestos_str[:200] if isinstance(repuestos_str, str) else 'N/A'}")
                    repuestos_diagnostico = []
                except Exception as e:
                    print(f"DEBUG: Error inesperado cargando repuestos del diagnóstico: {e}")
                    import traceback
                    traceback.print_exc()
                    repuestos_diagnostico = []
            else:
                print(f"DEBUG: No hay repuestos_seleccionados en el diagnóstico")
        else:
            print(f"DEBUG: No hay diagnóstico en la orden")
        
        print(f"DEBUG: Renderizando template reparacion.html para orden {id}")
        print(f"DEBUG: Datos a pasar al template:")
        print(f"  - repuestos_diagnostico: {len(repuestos_diagnostico)} repuestos")
        print(f"  - repuestos_existentes: {len(repuestos_existentes)} repuestos")
        
        return render_template('servicio_tecnico/reparacion.html', 
                             orden=orden_normalizado, 
                             inventario=inventario,
                             repuestos_diagnostico=repuestos_diagnostico,
                             repuestos_existentes=repuestos_existentes)
        
    except Exception as e:
        print(f"DEBUG: Error en reparacion_orden: {str(e)}")
        import traceback
        traceback.print_exc()
        # No mostrar el error al usuario
        return redirect(url_for('servicio_tecnico'))

@app.route('/servicio-tecnico/orden/<id>/recalcular-repuestos', methods=['POST'])
@login_required
def recalcular_repuestos(id):
    """Recalcular repuestos utilizados basándose en el diagnóstico"""
    try:
        ordenes = cargar_datos('ordenes_servicio.json')
        
        if id not in ordenes:
            return jsonify({'success': False, 'message': 'Orden no encontrada'})
        
        orden = ordenes[id]
        
        # Verificar si hay diagnóstico con repuestos
        if not orden.get('diagnostico', {}).get('repuestos_seleccionados'):
            return jsonify({'success': False, 'message': 'No hay repuestos en el diagnóstico'})
        
        # Parsear repuestos del diagnóstico
        import json
        repuestos_str = orden.get('diagnostico', {}).get('repuestos_seleccionados', '[]')
        repuestos_diagnostico = cargar_json_seguro(repuestos_str, [])
        
        # Convertir al formato de reparación
        repuestos_detalle = []
        total_repuestos = 0
        
        for repuesto in repuestos_diagnostico:
            repuestos_detalle.append({
                'id': repuesto['id'],
                'nombre': repuesto['nombre'],
                'cantidad': repuesto['cantidad'],
                'costo_unitario': repuesto['precio'],
                'subtotal': repuesto['cantidad'] * repuesto['precio']
            })
            total_repuestos += repuesto['cantidad'] * repuesto['precio']
        
        # Actualizar datos de reparación
        if 'reparacion' not in orden:
            orden['reparacion'] = {}
        
        orden['reparacion'].update({
            'repuestos_usados': repuestos_detalle,
            'total_repuestos': total_repuestos,
            'fecha_actualizacion': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        
        # Guardar cambios
        guardar_datos('ordenes_servicio.json', ordenes)
        
        return jsonify({
            'success': True, 
            'message': f'Se recalcularon {len(repuestos_detalle)} repuestos por un total de ${total_repuestos:.2f}',
            'total_repuestos': total_repuestos
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error: {str(e)}'})

@app.route('/servicio-tecnico/orden/<id>/reparacion-completa', methods=['GET', 'POST'])
@login_required
def reparacion_completa(id):
    """Módulo de reparación completo con procesamiento de repuestos"""
    try:
        print(f"DEBUG: Entrando a reparacion_completa para orden {id}")
        ordenes = cargar_datos('ordenes_servicio.json')
        inventario = cargar_datos('inventario.json')
        
        if id not in ordenes:
            # No mostrar el error al usuario
            return redirect(url_for('servicio_tecnico'))
        
        if request.method == 'POST':
            # Obtener datos del formulario
            acciones_realizadas = request.form.get('acciones_realizadas', '')
            repuestos_usados = request.form.getlist('repuestos_usados')
            cantidades = request.form.getlist('cantidades_repuestos')
            costos_unitarios = request.form.getlist('costos_unitarios')
            fecha_inicio = request.form.get('fecha_inicio_reparacion', '')
            fecha_fin = request.form.get('fecha_fin_reparacion', '')
            resultado_pruebas = request.form.get('resultado_pruebas', '')
            observaciones_finales = request.form.get('observaciones_finales', '')
            costo_adicional = safe_float(request.form.get('costo_adicional', 0) or 0)
            tecnico_responsable = request.form.get('tecnico_responsable', session.get('usuario', session.get('username', 'Técnico')))
            
            print(f"DEBUG: Datos recibidos - Repuestos: {repuestos_usados}, Cantidades: {cantidades}, Costos: {costos_unitarios}")
            
            # Procesar repuestos usados
            repuestos_detalle = []
            total_repuestos = 0
            
            for i, repuesto_id in enumerate(repuestos_usados):
                if repuesto_id and i < len(cantidades) and i < len(costos_unitarios):
                    try:
                        cantidad = int(cantidades[i]) if cantidades[i] else 0
                        costo_unitario = safe_float(costos_unitarios[i]) if costos_unitarios[i] else 0
                        
                        print(f"DEBUG: Procesando repuesto {i}: ID={repuesto_id}, Cantidad={cantidad}, Costo={costo_unitario}")
                        
                        if cantidad > 0 and costo_unitario > 0:
                            # Buscar repuesto en inventario
                            repuesto_info = inventario.get(repuesto_id, {})
                            
                            repuestos_detalle.append({
                                'id': repuesto_id,
                                'nombre': repuesto_info.get('nombre', 'Repuesto desconocido'),
                                'cantidad': cantidad,
                                'costo_unitario': costo_unitario,
                                'subtotal': cantidad * costo_unitario
                            })
                            
                            total_repuestos += cantidad * costo_unitario
                            
                            # Validar stock antes de descontar
                            if repuesto_id in inventario:
                                stock_actual = inventario[repuesto_id].get('cantidad', 0)
                                if stock_actual < cantidad:
                                    print(f"DEBUG: Stock insuficiente para {repuesto_id}. Disponible: {stock_actual}, Requerido: {cantidad}")
                                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                                        return jsonify({
                                            'success': False,
                                            'message': f'Stock insuficiente para {repuesto_info.get("nombre", repuesto_id)}. Disponible: {stock_actual}, Requerido: {cantidad}'
                                        }), 400
                                    flash(f'Stock insuficiente para {repuesto_info.get("nombre", repuesto_id)}. Disponible: {stock_actual}', 'danger')
                                    return redirect(url_for('reparacion_completa', id=id))
                                # Descontar del inventario
                                inventario[repuesto_id]['cantidad'] = max(0, stock_actual - cantidad)
                                print(f"DEBUG: Stock actualizado para {repuesto_id}: {stock_actual} -> {inventario[repuesto_id]['cantidad']}")
                    except (ValueError, TypeError) as e:
                        print(f"DEBUG: Error al procesar repuesto {i}: {str(e)}")
                        continue
            
            print(f"DEBUG: Total repuestos procesados: {len(repuestos_detalle)}, Total costo: {total_repuestos}")
            
            # Si no hay repuestos procesados, intentar cargar del diagnóstico
            if len(repuestos_detalle) == 0 and ordenes[id].get('diagnostico', {}).get('repuestos_seleccionados'):
                try:
                    import json
                    repuestos_str = ordenes[id].get('diagnostico', {}).get('repuestos_seleccionados', '[]')
                    repuestos_diagnostico = cargar_json_seguro(repuestos_str, [])
                    print(f"DEBUG: Cargando repuestos del diagnóstico: {repuestos_diagnostico}")
                    
                    for repuesto in repuestos_diagnostico:
                        repuestos_detalle.append({
                            'id': repuesto['id'],
                            'nombre': repuesto['nombre'],
                            'cantidad': repuesto['cantidad'],
                            'costo_unitario': repuesto['precio'],
                            'subtotal': repuesto['cantidad'] * repuesto['precio']
                        })
                        total_repuestos += repuesto['cantidad'] * repuesto['precio']
                    
                    print(f"DEBUG: Repuestos del diagnóstico cargados: {len(repuestos_detalle)}, Total: {total_repuestos}")
                except Exception as e:
                    print(f"DEBUG: Error al cargar repuestos del diagnóstico: {str(e)}")
            
            # Inicializar reparación si no existe
            if 'reparacion' not in ordenes[id]:
                ordenes[id]['reparacion'] = {}
            
            # Preservar datos anteriores (como fotos, datos previos)
            reparacion_actual = ordenes[id]['reparacion']
            
            # Validar stock antes de descontar
            if repuestos_detalle:
                problemas_stock = []
                for repuesto in repuestos_detalle:
                    repuesto_id = repuesto['id']
                    cantidad_necesaria = repuesto['cantidad']
                    if repuesto_id in inventario:
                        stock_actual = inventario[repuesto_id].get('cantidad', 0)
                        if stock_actual < cantidad_necesaria:
                            problemas_stock.append(f"{repuesto['nombre']}: Disponible {stock_actual}, Requerido {cantidad_necesaria}")
                
                if problemas_stock:
                    mensaje_error = 'Stock insuficiente:\n' + '\n'.join(problemas_stock)
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.form.get('ajax'):
                        return jsonify({
                            'success': False,
                            'message': mensaje_error
                        }), 400
                    flash(mensaje_error, 'danger')
                    return redirect(url_for('reparacion_completa', id=id))
                
                # Descontar del inventario después de validar
                for repuesto in repuestos_detalle:
                    repuesto_id = repuesto['id']
                    cantidad = repuesto['cantidad']
                    if repuesto_id in inventario:
                        stock_actual = inventario[repuesto_id].get('cantidad', 0)
                        inventario[repuesto_id]['cantidad'] = max(0, stock_actual - cantidad)
                        print(f"DEBUG: Stock actualizado para {repuesto_id}: {stock_actual} -> {inventario[repuesto_id]['cantidad']}")
            
            # Actualizar datos de reparación
            reparacion_actual.update({
                'acciones_realizadas': acciones_realizadas,
                'fecha_inicio': fecha_inicio,
                'fecha_fin': fecha_fin,
                'resultado_pruebas': resultado_pruebas,
                'observaciones_finales': observaciones_finales,
                'costo_adicional': costo_adicional,
                'tecnico_responsable': tecnico_responsable,
                'fecha_actualizacion': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            
            # Si hay repuestos, actualizar la lista
            if repuestos_detalle:
                if 'repuestos_usados' in reparacion_actual:
                    # Combinar con repuestos anteriores si existen
                    repuestos_anteriores = reparacion_actual.get('repuestos_usados', [])
                    ids_existentes = {r.get('id') for r in repuestos_anteriores if isinstance(r, dict)}
                    for repuesto in repuestos_detalle:
                        if repuesto['id'] not in ids_existentes:
                            repuestos_anteriores.append(repuesto)
                        else:
                            # Actualizar cantidad si ya existe
                            for idx, r_ant in enumerate(repuestos_anteriores):
                                if isinstance(r_ant, dict) and r_ant.get('id') == repuesto['id']:
                                    repuestos_anteriores[idx] = repuesto
                                    break
                    reparacion_actual['repuestos_usados'] = repuestos_anteriores
                else:
                    reparacion_actual['repuestos_usados'] = repuestos_detalle
                
                reparacion_actual['total_repuestos'] = total_repuestos
            
            ordenes[id]['reparacion'] = reparacion_actual
            
            # Procesar fotos de reparación
            if 'fotos_reparacion' in request.files:
                fotos = request.files.getlist('fotos_reparacion')
                fotos_paths = []
                
                for foto in fotos:
                    if foto and foto.filename:
                        # Crear directorio si no existe
                        upload_folder = os.path.join(app.root_path, 'uploads', id, 'reparacion')
                        os.makedirs(upload_folder, exist_ok=True)
                        
                        filename = secure_filename(foto.filename)
                        filepath = os.path.join(upload_folder, filename)
                        foto.save(filepath)
                        fotos_paths.append(f'/uploads/{id}/reparacion/{filename}')
                
                if fotos_paths:
                    ordenes[id]['reparacion']['fotos'] = fotos_paths
            
            # Determinar nuevo estado
            accion_recibida = request.form.get('accion')
            print(f"DEBUG: Acción recibida: '{accion_recibida}'")
            print(f"DEBUG: Estado actual: '{ordenes[id]['estado']}'")
            
            nuevo_estado = ordenes[id]['estado']
            if accion_recibida == 'en_pruebas':
                nuevo_estado = 'en_pruebas'
                print("DEBUG: Cambiando estado a 'en_pruebas'")
            elif accion_recibida == 'reparado':
                nuevo_estado = 'reparado'
                print("DEBUG: Cambiando estado a 'reparado'")
            elif accion_recibida == 'listo_entrega':
                nuevo_estado = 'listo_entrega'
                print("DEBUG: Cambiando estado a 'listo_entrega'")
            else:
                print(f"DEBUG: Acción no reconocida: '{accion_recibida}', manteniendo estado actual")
            
            print(f"DEBUG: Nuevo estado: '{nuevo_estado}'")
            
            # Actualizar estado
            ordenes[id]['estado'] = nuevo_estado
            ordenes[id]['fecha_actualizacion'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # Inicializar historial si no existe
            if 'historial_estados' not in ordenes[id]:
                ordenes[id]['historial_estados'] = []
            
            # Agregar al historial
            comentario_historial = f"Reparación actualizada - Estado: {nuevo_estado.replace('_', ' ').title()}"
            if repuestos_detalle:
                comentario_historial += f" - {len(repuestos_detalle)} repuesto(s) utilizado(s) y descontado(s) del inventario"
            
            ordenes[id]['historial_estados'].append({
                "estado": nuevo_estado,
                "fecha": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "usuario": session.get('usuario', session.get('username', 'Técnico')),
                "comentarios": comentario_historial
            })
            
            # Guardar cambios
            print("DEBUG: Guardando datos de órdenes...")
            guardar_datos('ordenes_servicio.json', ordenes)
            print("DEBUG: Guardando datos de inventario...")
            guardar_datos('inventario.json', inventario)
            print("DEBUG: Datos guardados exitosamente")
            
            # Respuesta JSON para AJAX
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.form.get('ajax'):
                return jsonify({
                    'success': True,
                    'message': 'Reparación actualizada exitosamente',
                    'nuevo_estado': nuevo_estado
                })
            
            flash('Reparación actualizada exitosamente', 'success')
            return redirect(url_for('ver_orden_servicio', id=id))
        
        orden = ordenes[id]
        
        # Convertir a DotDict
        orden_normalizado = DotDict(orden)
        if 'estado' not in orden_normalizado:
            orden_normalizado['estado'] = 'desconocido'
        
        # Obtener repuestos seleccionados en el diagnóstico
        repuestos_diagnostico = []
        if orden.get('diagnostico') and orden['diagnostico'].get('repuestos_seleccionados'):
            repuestos_str = orden.get('diagnostico', {}).get('repuestos_seleccionados', '[]')
            repuestos_diagnostico = cargar_json_seguro(repuestos_str, [])
            print(f"DEBUG: Repuestos del diagnóstico cargados: {len(repuestos_diagnostico)}")
        
        return render_template('servicio_tecnico/reparacion.html', 
                             orden=orden_normalizado, 
                             inventario=inventario,
                             repuestos_diagnostico=repuestos_diagnostico)
        
    except Exception as e:
        print(f"DEBUG: Error en reparacion_completa: {str(e)}")
        import traceback
        traceback.print_exc()
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.form.get('ajax'):
            return jsonify({
                'success': False,
                'message': f'Error en reparación: {str(e)}'
            })
        
        # No mostrar el error al usuario
        return redirect(url_for('servicio_tecnico'))


@app.route('/servicio-tecnico/orden/<id>/entrega', methods=['GET', 'POST'])
@login_required
def entrega_orden(id):
    """Módulo de entrega del equipo reparado"""
    try:
        ordenes = cargar_datos('ordenes_servicio.json')
        
        if id not in ordenes:
            # No mostrar el error al usuario
            return redirect(url_for('servicio_tecnico'))
        
        # Métodos de pago disponibles (mismos que en pagos recibidos)
        metodos_pago = ['Efectivo', 'Transferencia', 'Pago Móvil', 'Zelle', 'Divisas', 'Punto de Venta', 'Cheque']
        
        if request.method == 'POST':
            try:
                print(f"DEBUG: Procesando entrega para orden {id}")
                # Obtener datos del formulario de entrega
                fecha_entrega = request.form.get('fecha_entrega', '')
                nombre_retira = request.form.get('nombre_retira', '')
                cedula_retira = request.form.get('cedula_retira', '')
                telefono_retira = request.form.get('telefono_retira', '')
                tipo_pago = request.form.get('tipo_pago', '')
                monto_pagado = safe_float(request.form.get('monto_pagado', 0) or 0)
                monto_pendiente = safe_float(request.form.get('monto_pendiente', 0) or 0)
                observaciones_entrega = request.form.get('observaciones_entrega', '')
                tecnico_entrega = request.form.get('tecnico_entrega', session.get('username', 'Técnico'))
                
                # Procesar firma digital si existe
                firma_digital = request.form.get('firma_digital', '')
                
                # Actualizar datos de entrega
                if 'entrega' not in ordenes[id]:
                    ordenes[id]['entrega'] = {}
                
                ordenes[id]['entrega'].update({
                    'fecha_entrega': fecha_entrega,
                    'nombre_retira': nombre_retira,
                    'cedula_retira': cedula_retira,
                    'telefono_retira': telefono_retira,
                    'tipo_pago': tipo_pago,
                    'monto_pagado': monto_pagado,
                    'monto_pendiente': monto_pendiente,
                    'observaciones_entrega': observaciones_entrega,
                    'tecnico_entrega': tecnico_entrega,
                    'firma_digital': firma_digital,
                    'fecha_actualizacion': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })
                
                # Cambiar estado a entregado
                ordenes[id]['estado'] = 'entregado'
                ordenes[id]['fecha_actualizacion'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                # Agregar al historial
                if 'historial_estados' not in ordenes[id]:
                    ordenes[id]['historial_estados'] = []
                
                ordenes[id]['historial_estados'].append({
                    "estado": "entregado",
                    "fecha": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    "usuario": session.get('username', 'Técnico'),
                    "comentarios": f"Equipo entregado a {nombre_retira} - Pago: {tipo_pago}"
                })
                
                # Registrar pago en pagos recibidos si hay monto pagado
                if monto_pagado > 0:
                    try:
                        pagos = cargar_datos(ARCHIVO_PAGOS_RECIBIDOS)
                        orden = ordenes[id]
                        cliente = orden.get('cliente', {})
                        
                        id_pago = f'PAGO-{datetime.now().strftime("%Y%m%d%H%M%S")}'
                        
                        pago_data = {
                            'id': id_pago,
                            'fecha': datetime.now().strftime('%Y-%m-%d'),
                            'cliente': cliente.get('nombre', 'Cliente'),
                            'cliente_id': orden.get('cliente_id', ''),
                            'concepto': f'Servicio Técnico - Orden {orden.get("numero_orden", "")}',
                            'metodo_pago': tipo_pago.title(),
                            'monto_usd': monto_pagado,
                            'monto_bs': monto_pagado * obtener_tasa_bcv(),
                            'tasa_bcv': obtener_tasa_bcv(),
                            'numero_referencia': f'ST-{orden.get("numero_orden", "")}',
                            'orden_servicio': id,
                            'banco': '',
                            'observaciones': f'Entrega de equipo: {orden.get("equipo", {}).get("marca", "")} {orden.get("equipo", {}).get("modelo", "")}',
                            'usuario_registro': session.get('username', 'Sistema'),
                            'fecha_registro': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        }
                        
                        pagos[id_pago] = pago_data
                        guardar_datos(ARCHIVO_PAGOS_RECIBIDOS, pagos)
                        print(f"DEBUG: Pago registrado en pagos recibidos: {id_pago}")
                    except Exception as e:
                        print(f"DEBUG: Error registrando pago en pagos recibidos: {e}")
                
                # Guardar cambios
                guardar_datos('ordenes_servicio.json', ordenes)
                
                # Respuesta JSON para AJAX
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.form.get('ajax'):
                    return jsonify({
                        'success': True,
                        'message': 'Entrega registrada exitosamente',
                        'nuevo_estado': 'entregado'
                    })
                
                flash('Entrega registrada exitosamente', 'success')
                return redirect(url_for('ver_orden_servicio', id=id))
            except Exception as e:
                print(f"DEBUG: Error en entrega_orden POST: {str(e)}")
                import traceback
                traceback.print_exc()
                
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.form.get('ajax'):
                    return jsonify({
                        'success': False,
                        'message': f'Error en entrega: {str(e)}'
                    }), 500
                
                flash(f'Error registrando entrega: {str(e)}', 'danger')
                return redirect(url_for('ver_orden_servicio', id=id))
        
        orden = ordenes[id]
        
        # Convertir a DotDict para que Jinja2 pueda usar notación de punto
        orden_normalizado = DotDict(orden)
        if 'estado' not in orden_normalizado:
            orden_normalizado['estado'] = 'desconocido'
        
        print(f"DEBUG: Orden normalizada para entrega - Estado: {orden_normalizado.get('estado')}")
        
        return render_template('servicio_tecnico/entrega.html', 
                             orden=orden_normalizado,
                             metodos_pago=metodos_pago)
        
    except Exception as e:
        print(f"DEBUG: Error en entrega_orden: {str(e)}")
        import traceback
        traceback.print_exc()
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.form.get('ajax'):
            return jsonify({
                'success': False,
                'message': f'Error en entrega: {str(e)}'
            })
        
        # No mostrar el error al usuario
        return redirect(url_for('servicio_tecnico'))

@app.route('/servicio-tecnico/orden/<id>/comprobante-retiro', methods=['GET'])
@login_required
def comprobante_retiro_servicio(id):
    """Generar comprobante de retiro para una orden de servicio"""
    try:
        print(f"DEBUG: Generando comprobante de retiro para orden {id}")
        
        ordenes = cargar_datos('ordenes_servicio.json')
        config = cargar_datos('config_servicio_tecnico.json')
        empresa = cargar_empresa()
        
        print(f"DEBUG: Ordenes cargadas: {len(ordenes)}")
        print(f"DEBUG: Config cargada: {bool(config)}")
        print(f"DEBUG: Empresa cargada: {bool(empresa)}")
        
        if id not in ordenes:
            print(f"DEBUG: Orden {id} no encontrada")
            flash('Orden de servicio no encontrada', 'danger')
            return redirect(url_for('servicio_tecnico'))
        
        orden = ordenes[id]
        print(f"DEBUG: Orden encontrada: {orden.get('numero_orden', 'Sin número')}")
        
        # Mostrar comprobante de retiro en HTML (para impresión)
        return render_template('servicio_tecnico/retiro_equipo_pdf.html', 
                             orden=orden, 
                             config=config,
                             empresa=empresa)
        
    except Exception as e:
        print(f"DEBUG: Error generando comprobante: {str(e)}")
        import traceback
        traceback.print_exc()
        flash(f'Error generando comprobante de retiro: {str(e)}', 'danger')
        return redirect(url_for('ver_orden_servicio', id=id))

@app.route('/servicio-tecnico/orden/<id>/enviar-notificacion', methods=['POST'])
@login_required
def enviar_notificacion_servicio(id):
    """Enviar notificación al cliente sobre el estado de su orden"""
    try:
        print(f"DEBUG: ===== INICIANDO ENVÍO DE NOTIFICACIÓN =====")
        print(f"DEBUG: Orden ID: {id}")
        print(f"DEBUG: Request method: {request.method}")
        print(f"DEBUG: Request headers: {dict(request.headers)}")
        print(f"DEBUG: Request form data: {dict(request.form)}")
        
        ordenes = cargar_datos('ordenes_servicio.json')
        config_servicio = cargar_datos('config_servicio_tecnico.json')
        config_sistema = cargar_configuracion()  # Usar config_sistema.json para habilitación
        
        print(f"DEBUG: Ordenes cargadas: {len(ordenes)}")
        print(f"DEBUG: Config servicio cargada: {bool(config_servicio)}")
        print(f"DEBUG: Config sistema cargada: {bool(config_sistema)}")
        
        if id not in ordenes:
            flash('Orden de servicio no encontrada', 'danger')
            return redirect(url_for('servicio_tecnico'))
        
        orden = ordenes[id]
        tipo_notificacion = request.form.get('tipo_notificacion')
        mensaje_personalizado = request.form.get('mensaje_personalizado', '')
        
        print(f"DEBUG: Tipo notificación: {tipo_notificacion}")
        
        # Generar mensaje según el tipo (usar plantillas de config_servicio_tecnico.json)
        if tipo_notificacion == 'equipo_recibido':
            mensaje = config_servicio['configuracion_notificaciones']['plantillas']['equipo_recibido'].format(
                cliente=orden['cliente']['nombre'],
                marca=orden['equipo']['marca'],
                modelo=orden['equipo']['modelo'],
                numero_orden=orden['numero_orden']
            )
        elif tipo_notificacion == 'diagnostico_completo':
            mensaje = config_servicio['configuracion_notificaciones']['plantillas']['diagnostico_completo'].format(
                cliente=orden['cliente']['nombre'],
                marca=orden['equipo']['marca'],
                modelo=orden['equipo']['modelo'],
                numero_orden=orden['numero_orden']
            )
        elif tipo_notificacion == 'reparacion_completa':
            mensaje = config_servicio['configuracion_notificaciones']['plantillas']['reparacion_completa'].format(
                cliente=orden['cliente']['nombre'],
                marca=orden['equipo']['marca'],
                modelo=orden['equipo']['modelo'],
                numero_orden=orden['numero_orden']
            )
        elif tipo_notificacion == 'presupuesto_enviado':
            mensaje = config_servicio['configuracion_notificaciones']['plantillas']['presupuesto_enviado'].format(
                cliente=orden['cliente']['nombre'],
                marca=orden['equipo']['marca'],
                modelo=orden['equipo']['modelo'],
                numero_orden=orden['numero_orden']
            )
        elif tipo_notificacion == 'reparacion_iniciada':
            mensaje = config_servicio['configuracion_notificaciones']['plantillas']['reparacion_iniciada'].format(
                cliente=orden['cliente']['nombre'],
                marca=orden['equipo']['marca'],
                modelo=orden['equipo']['modelo'],
                numero_orden=orden['numero_orden']
            )
        elif tipo_notificacion == 'costo_estimado':
            tasa_bcv = obtener_tasa_bcv()  # Usar función USD principal
            if not tasa_bcv or tasa_bcv < 10:
                tasa_bcv = 216.37  # Fallback con tasa USD
            costo_usd = orden.get('diagnostico', {}).get('total_estimado', 0)
            costo_bs = costo_usd * tasa_bcv
            tiempo_estimado = orden.get('tiempo_estimado', '3-5')
            
            mensaje = config_servicio['configuracion_notificaciones']['plantillas']['costo_estimado'].format(
                cliente=orden['cliente']['nombre'],
                marca=orden['equipo']['marca'],
                modelo=orden['equipo']['modelo'],
                numero_orden=orden['numero_orden'],
                costo_usd=costo_usd,
                costo_bs=f"{costo_bs:,.2f}",
                tiempo_estimado=tiempo_estimado
            )
        else:
            mensaje = mensaje_personalizado
        
        print(f"DEBUG: Mensaje generado: {mensaje[:100]}...")
        
        # Obtener métodos de envío del formulario (si no viene, usar ambos por defecto)
        metodos_envio_str = request.form.get('metodos_envio', 'whatsapp,email')
        metodos_envio = [m.strip() for m in metodos_envio_str.split(',')] if metodos_envio_str else ['whatsapp']
        
        # Usar config_sistema.json para habilitación de notificaciones
        notificaciones_sistema = config_sistema.get('notificaciones', {})
        whatsapp_habilitado = notificaciones_sistema.get('whatsapp_habilitado', False)
        email_habilitado = notificaciones_sistema.get('email_habilitado', False)
        
        resultados = {'whatsapp': False, 'email': False}
        enlace_whatsapp = None
        email_enviado = False
        email_cliente = orden['cliente'].get('email', '')
        
        telefono_limpio = None
        
        # Enviar por WhatsApp si está seleccionado y habilitado
        if 'whatsapp' in metodos_envio and whatsapp_habilitado:
            telefono = orden['cliente'].get('telefono', '')
            print(f"DEBUG: Teléfono del cliente: {telefono}")
            
            if telefono and telefono.strip():
                # Limpiar número de teléfono
                telefono_limpio = telefono.replace('+', '').replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
                
                # Asegurar que tenga código de país Venezuela (58)
                if not telefono_limpio.startswith('58'):
                    if telefono_limpio.startswith('0'):
                        telefono_limpio = '58' + telefono_limpio[1:]
                    else:
                        telefono_limpio = '58' + telefono_limpio
                    
                print(f"DEBUG: Teléfono limpio: {telefono_limpio}")
                    
                from urllib.parse import quote
                mensaje_codificado = quote(mensaje)
                enlace_final = f"https://wa.me/{telefono_limpio}?text={mensaje_codificado}"
                resultados['whatsapp'] = True
                enlace_whatsapp = enlace_final
                        
                print(f"DEBUG: Enlace WhatsApp: {enlace_final}")
            else:
                print("DEBUG: Cliente no tiene número de teléfono válido")
                flash('Cliente no tiene número de teléfono registrado', 'warning')
        
        # Enviar por Email si está seleccionado y habilitado
        if 'email' in metodos_envio and email_cliente and email_cliente.strip() and email_habilitado:
            try:
                # Preparar asunto según el tipo
                asuntos = {
                    'equipo_recibido': 'Equipo Recibido - Orden de Servicio',
                    'diagnostico_completo': 'Diagnóstico Completo - Orden de Servicio',
                    'presupuesto_enviado': 'Presupuesto Enviado - Orden de Servicio',
                    'reparacion_iniciada': 'Reparación Iniciada - Orden de Servicio',
                    'reparacion_completa': 'Reparación Completa - Orden de Servicio',
                    'costo_estimado': 'Costo Estimado - Orden de Servicio',
                    'personalizado': 'Notificación - Orden de Servicio'
                }
                asunto = asuntos.get(tipo_notificacion, 'Notificación - Orden de Servicio')
                
                resultado_email = enviar_email_reporte(asunto, mensaje, email_cliente, config_sistema)
                if resultado_email:
                    resultados['email'] = True
                    email_enviado = True
                    flash(f'✅ Email enviado exitosamente a {email_cliente}', 'success')
                    print(f"✅ Email enviado exitosamente a {email_cliente}")
                else:
                    flash(f'⚠️ Error al enviar email a {email_cliente}', 'warning')
                    print(f"⚠️ Error al enviar email a {email_cliente}")
            except Exception as e:
                print(f"❌ Error enviando email: {e}")
                flash(f'Error enviando email: {str(e)}', 'danger')
        elif 'email' in metodos_envio and not email_cliente:
            flash('Cliente no tiene email registrado', 'warning')
        
        # Registrar notificación enviada
            if 'notificaciones_enviadas' not in ordenes[id]:
                ordenes[id]['notificaciones_enviadas'] = []
                
        notificacion_registro = {
            "tipo": tipo_notificacion,
            "fecha": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "mensaje": mensaje,
            "usuario": session.get('usuario', 'admin'),
            "metodos_envio": metodos_envio,
            "resultados": resultados
        }
        
        if telefono_limpio:
            notificacion_registro["telefono"] = telefono_limpio
        if enlace_whatsapp:
            notificacion_registro["enlace_whatsapp"] = enlace_whatsapp
        if email_cliente:
            notificacion_registro["email"] = email_cliente
        if email_enviado:
            notificacion_registro["email_enviado"] = True
                
        ordenes[id]['notificaciones_enviadas'].append(notificacion_registro)
        ordenes[id]['fecha_actualizacion'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        guardar_datos('ordenes_servicio.json', ordenes)
        
        # Si hay enlace WhatsApp, redirigir a WhatsApp, sino volver a la orden
        if enlace_whatsapp and 'whatsapp' in metodos_envio:
            print(f"DEBUG: ===== REDIRIGIENDO A WHATSAPP =====")
            return redirect(enlace_whatsapp)
        else:
            print(f"DEBUG: ===== NOTIFICACIÓN ENVIADA EXITOSAMENTE =====")
            return redirect(url_for('ver_orden_servicio', id=id))
        
    except Exception as e:
        print(f"DEBUG: ===== ERROR EN ENVÍO DE NOTIFICACIÓN =====")
        print(f"DEBUG: Error: {str(e)}")
        print(f"DEBUG: Error type: {type(e)}")
        import traceback
        traceback.print_exc()
        
        # Si es una petición AJAX, devolver JSON
        if request.headers.get('Content-Type') == 'application/x-www-form-urlencoded':
            return jsonify({
                'success': False,
                'error': str(e),
                'message': f'Error enviando notificación: {str(e)}'
            }), 500
        else:
            flash(f'Error enviando notificación: {str(e)}', 'danger')
            return redirect(url_for('ver_orden_servicio', id=id))

@app.route('/api/servicio-tecnico/orden/<id>/enviar-notificacion-directa', methods=['POST'])
@login_required
def enviar_notificacion_directa(id):
    """Enviar notificación directa sin redirección"""
    try:
        print(f"DEBUG: ===== ENVÍO DIRECTO DE NOTIFICACIÓN =====")
        print(f"DEBUG: Orden ID: {id}")
        
        ordenes = cargar_datos('ordenes_servicio.json')
        config_servicio = cargar_datos('config_servicio_tecnico.json')
        config_sistema = cargar_configuracion()  # Usar config_sistema.json para habilitación
        
        if id not in ordenes:
            return jsonify({'success': False, 'error': 'Orden no encontrada'}), 404
        
        orden = ordenes[id]
        
        # Validar estructura de la orden
        if 'cliente' not in orden or not isinstance(orden['cliente'], dict):
            return jsonify({'success': False, 'error': 'Estructura de orden inválida: cliente no encontrado'}), 400
        
        if 'equipo' not in orden or not isinstance(orden['equipo'], dict):
            return jsonify({'success': False, 'error': 'Estructura de orden inválida: equipo no encontrado'}), 400
        
        tipo_notificacion = request.form.get('tipo_notificacion')
        mensaje_personalizado = request.form.get('mensaje_personalizado', '')
        metodos_envio_str = request.form.get('metodos_envio', 'whatsapp')  # Por defecto WhatsApp
        metodos_envio = [m.strip() for m in metodos_envio_str.split(',')] if metodos_envio_str else ['whatsapp']
        
        print(f"DEBUG: Tipo notificación: {tipo_notificacion}")
        print(f"DEBUG: Métodos de envío: {metodos_envio}")
        
        # Generar mensaje según el tipo (usar plantillas de config_servicio_tecnico.json)
        if tipo_notificacion == 'equipo_recibido':
            mensaje = config_servicio['configuracion_notificaciones']['plantillas']['equipo_recibido'].format(
                cliente=orden['cliente'].get('nombre', 'Cliente'),
                marca=orden['equipo'].get('marca', ''),
                modelo=orden['equipo'].get('modelo', ''),
                numero_orden=orden.get('numero_orden', id)
            )
        elif tipo_notificacion == 'diagnostico_completo':
            mensaje = config_servicio['configuracion_notificaciones']['plantillas']['diagnostico_completo'].format(
                cliente=orden['cliente'].get('nombre', 'Cliente'),
                marca=orden['equipo'].get('marca', ''),
                modelo=orden['equipo'].get('modelo', ''),
                numero_orden=orden.get('numero_orden', id)
            )
        elif tipo_notificacion == 'reparacion_completa':
            mensaje = config_servicio['configuracion_notificaciones']['plantillas']['reparacion_completa'].format(
                cliente=orden['cliente'].get('nombre', 'Cliente'),
                marca=orden['equipo'].get('marca', ''),
                modelo=orden['equipo'].get('modelo', ''),
                numero_orden=orden.get('numero_orden', id)
            )
        elif tipo_notificacion == 'presupuesto_enviado':
            mensaje = config_servicio['configuracion_notificaciones']['plantillas']['presupuesto_enviado'].format(
                cliente=orden['cliente'].get('nombre', 'Cliente'),
                marca=orden['equipo'].get('marca', ''),
                modelo=orden['equipo'].get('modelo', ''),
                numero_orden=orden.get('numero_orden', id)
            )
        elif tipo_notificacion == 'reparacion_iniciada':
            mensaje = config_servicio['configuracion_notificaciones']['plantillas']['reparacion_iniciada'].format(
                cliente=orden['cliente'].get('nombre', 'Cliente'),
                marca=orden['equipo'].get('marca', ''),
                modelo=orden['equipo'].get('modelo', ''),
                numero_orden=orden.get('numero_orden', id)
            )
        elif tipo_notificacion == 'costo_estimado':
            tasa_bcv = obtener_tasa_bcv()  # Usar función USD principal
            if not tasa_bcv or tasa_bcv < 10:
                tasa_bcv = 216.37  # Fallback con tasa USD
            costo_usd = orden.get('diagnostico', {}).get('total_estimado', 0)
            costo_bs = costo_usd * tasa_bcv
            tiempo_estimado = orden.get('tiempo_estimado', '3-5')
            
            mensaje = config_servicio['configuracion_notificaciones']['plantillas']['costo_estimado'].format(
                cliente=orden['cliente'].get('nombre', 'Cliente'),
                marca=orden['equipo'].get('marca', ''),
                modelo=orden['equipo'].get('modelo', ''),
                numero_orden=orden.get('numero_orden', id),
                costo_usd=costo_usd,
                costo_bs=f"{costo_bs:,.2f}",
                tiempo_estimado=tiempo_estimado
            )
        else:
            mensaje = mensaje_personalizado
        
        print(f"DEBUG: Mensaje generado: {mensaje[:100]}...")
        
        # Usar config_sistema.json para habilitación de notificaciones
        notificaciones_sistema = config_sistema.get('notificaciones', {})
        whatsapp_habilitado = notificaciones_sistema.get('whatsapp_habilitado', False)
        email_habilitado = notificaciones_sistema.get('email_habilitado', False)
        
        resultados = {'whatsapp': False, 'email': False}
        enlace_whatsapp = None
        email_enviado = False
        telefono_limpio = None
        
        # Preparar datos del cliente
        telefono = orden['cliente'].get('telefono', '')
        email_cliente = orden['cliente'].get('email', '')
        
        # Enviar por WhatsApp si está seleccionado y habilitado
        if 'whatsapp' in metodos_envio and whatsapp_habilitado and telefono and telefono.strip():
            # Limpiar número de teléfono
            telefono_limpio = telefono.replace('+', '').replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
            
            # Asegurar que tenga código de país Venezuela (58)
            if not telefono_limpio.startswith('58'):
                if telefono_limpio.startswith('0'):
                    telefono_limpio = '58' + telefono_limpio[1:]
                else:
                    telefono_limpio = '58' + telefono_limpio
            
            from urllib.parse import quote
            mensaje_codificado = quote(mensaje)
            enlace_whatsapp = f"https://wa.me/{telefono_limpio}?text={mensaje_codificado}"
            
            resultados['whatsapp'] = True
            print(f"DEBUG: Enlace WhatsApp generado: {enlace_whatsapp}")
        elif 'whatsapp' in metodos_envio:
            print(f"DEBUG: WhatsApp seleccionado pero no disponible (habilitado: {whatsapp_habilitado}, telefono: {bool(telefono)})")
        
        # Enviar por Email si está seleccionado y habilitado
        if 'email' in metodos_envio and email_cliente and email_cliente.strip() and email_habilitado:
            try:
                # Preparar asunto según el tipo
                asuntos = {
                    'equipo_recibido': 'Equipo Recibido - Orden de Servicio',
                    'diagnostico_completo': 'Diagnóstico Completo - Orden de Servicio',
                    'presupuesto_enviado': 'Presupuesto Enviado - Orden de Servicio',
                    'reparacion_iniciada': 'Reparación Iniciada - Orden de Servicio',
                    'reparacion_completa': 'Reparación Completa - Orden de Servicio',
                    'costo_estimado': 'Costo Estimado - Orden de Servicio',
                    'personalizado': 'Notificación - Orden de Servicio'
                }
                asunto = asuntos.get(tipo_notificacion, 'Notificación - Orden de Servicio')
                
                resultado_email = enviar_email_reporte(asunto, mensaje, email_cliente, config_sistema)
                if resultado_email:
                    resultados['email'] = True
                    email_enviado = True
                    print(f"✅ Email enviado exitosamente a {email_cliente}")
                else:
                    print(f"⚠️ Error al enviar email a {email_cliente}")
            except Exception as e:
                print(f"❌ Error enviando email: {e}")
                import traceback
                traceback.print_exc()
        elif 'email' in metodos_envio:
            print(f"DEBUG: Email seleccionado pero no disponible (habilitado: {email_habilitado}, email: {bool(email_cliente)})")
        
        # Registrar notificación
        if 'notificaciones_enviadas' not in ordenes[id]:
            ordenes[id]['notificaciones_enviadas'] = []
            
        notificacion_registro = {
            "tipo": tipo_notificacion,
            "fecha": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "mensaje": mensaje,
            "usuario": session.get('usuario', 'admin'),
            "metodos_envio": metodos_envio,
            "resultados": resultados
        }
        
        if telefono_limpio:
            notificacion_registro["telefono"] = telefono_limpio
        if enlace_whatsapp:
            notificacion_registro["enlace_whatsapp"] = enlace_whatsapp
        if email_cliente:
            notificacion_registro["email"] = email_cliente
        if email_enviado:
            notificacion_registro["email_enviado"] = True
        
        ordenes[id]['notificaciones_enviadas'].append(notificacion_registro)
        ordenes[id]['fecha_actualizacion'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        guardar_datos('ordenes_servicio.json', ordenes)
        
        print(f"DEBUG: ===== NOTIFICACIÓN REGISTRADA EXITOSAMENTE =====")
        
        return jsonify({
            'success': True,
            'mensaje': mensaje,
            'enlace_whatsapp': enlace_whatsapp,
            'telefono': telefono_limpio if telefono_limpio else None,
            'email': email_cliente if email_cliente else None,
            'email_enviado': email_enviado,
            'tipo': tipo_notificacion,
            'metodos_envio': metodos_envio,
            'resultados': resultados
        })
        
    except Exception as e:
        print(f"DEBUG: ===== ERROR EN ENVÍO DIRECTO =====")
        print(f"DEBUG: Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e),
            'message': f'Error enviando notificación: {str(e)}'
        }), 500

@app.route('/test-whatsapp-notificacion/<id>')
@login_required
def test_whatsapp_notificacion(id):
    """Función de prueba para verificar el envío de WhatsApp"""
    try:
        ordenes = cargar_datos('ordenes_servicio.json')
        config = cargar_datos('config_servicio_tecnico.json')
        
        if id not in ordenes:
            return jsonify({'error': 'Orden no encontrada'}), 404
        
        orden = ordenes[id]
        telefono = orden['cliente'].get('telefono', '')
        
        if not telefono:
            return jsonify({'error': 'Cliente no tiene teléfono'}), 400
        
        # Limpiar número
        telefono_limpio = telefono.replace('+', '').replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        if not telefono_limpio.startswith('58'):
            if telefono_limpio.startswith('0'):
                telefono_limpio = '58' + telefono_limpio[1:]
            else:
                telefono_limpio = '58' + telefono_limpio
        
        # Mensaje de prueba
        mensaje_prueba = f"🔧 *SERVICIO TÉCNICO JEHOVÁ JIREH* 🔧\n\n¡Hola {orden['cliente']['nombre']}! 👋\n\n📱 Esta es una notificación de prueba para tu orden *{orden['numero_orden']}*\n\n📞 *Contacto:*\n• 📱 Teléfono: 0424-123-4567\n• 💬 WhatsApp: 0424-123-4567\n\n¡Gracias por confiar en nosotros! 🙏"
        
        from urllib.parse import quote
        mensaje_codificado = quote(mensaje_prueba)
        enlace_final = f"https://wa.me/{telefono_limpio}?text={mensaje_codificado}"
        
        return jsonify({
            'success': True,
            'telefono_original': telefono,
            'telefono_limpio': telefono_limpio,
            'enlace_whatsapp': enlace_final,
            'mensaje': mensaje_prueba
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/comprobante-html/<id>')
@login_required
def comprobante_retiro_html(id):
    """Generar comprobante de retiro de equipo en HTML (para impresión)"""
    try:
        # Cargar datos de la orden
        ordenes = cargar_datos('ordenes_servicio.json')
        
        if id not in ordenes:
            flash('Orden de servicio no encontrada', 'danger')
            return redirect(url_for('servicio_tecnico'))
        
        orden = ordenes[id]
        
        # Preparar datos para la plantilla
        data = {
            'numero_orden': orden.get('numero_orden', 'N/A'),
            'fecha_retiro': datetime.now().strftime('%d/%m/%Y %H:%M'),
            'fecha_generacion': datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
            'cliente': {
                'nombre': orden.get('cliente', {}).get('nombre', 'No especificado'),
                'cedula_rif': orden.get('cliente', {}).get('cedula_rif', 'No especificado'),
                'telefono': orden.get('cliente', {}).get('telefono', 'No especificado'),
                'email': orden.get('cliente', {}).get('email', 'No especificado')
            },
            'equipo': {
                'marca': orden.get('equipo', {}).get('marca', 'No especificado'),
                'modelo': orden.get('equipo', {}).get('modelo', 'No especificado'),
                'color': orden.get('equipo', {}).get('color', 'No especificado'),
                'imei_1': orden.get('equipo', {}).get('imei', 'No especificado'),
                'imei_2': orden.get('equipo', {}).get('imei_2', 'No aplica'),
                'accesorios': orden.get('equipo', {}).get('accesorios', 'Ninguno'),
                'estado_retiro': orden.get('equipo', {}).get('estado_retiro', 'Funcionando correctamente')
            },
            'servicio': {
                'descripcion': orden.get('servicio_realizado', 'Reparación general'),
                'observaciones': orden.get('observaciones', 'Sin observaciones'),
                'tecnico': orden.get('tecnico_asignado', 'No asignado'),
                'garantia': orden.get('garantia', '90 días')
            }
        }
        
        # Renderizar la plantilla HTML simple
        html = render_template('comprobante_simple.html', data=data)
        
        return html
        
    except Exception as e:
        print(f"Error generando comprobante HTML: {e}")
        import traceback
        traceback.print_exc()
        flash(f'Error generando comprobante: {str(e)}', 'danger')
        return redirect(url_for('servicio_tecnico'))

@app.route('/comprobante/<id>')
@login_required
def comprobante_retiro(id):
    """Generar comprobante de retiro de equipo en PDF"""
    try:
        # Cargar datos de la orden
        ordenes = cargar_datos('ordenes_servicio.json')
        
        if id not in ordenes:
            flash('Orden de servicio no encontrada', 'danger')
            return redirect(url_for('servicio_tecnico'))
        
        orden = ordenes[id]
        
        # Preparar datos para la plantilla
        data = {
            'numero_orden': orden.get('numero_orden', 'N/A'),
            'fecha_retiro': datetime.now().strftime('%d/%m/%Y %H:%M'),
            'fecha_generacion': datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
            'cliente': {
                'nombre': orden.get('cliente', {}).get('nombre', 'No especificado'),
                'cedula_rif': orden.get('cliente', {}).get('cedula_rif', 'No especificado'),
                'telefono': orden.get('cliente', {}).get('telefono', 'No especificado'),
                'email': orden.get('cliente', {}).get('email', 'No especificado')
            },
            'equipo': {
                'marca': orden.get('equipo', {}).get('marca', 'No especificado'),
                'modelo': orden.get('equipo', {}).get('modelo', 'No especificado'),
                'color': orden.get('equipo', {}).get('color', 'No especificado'),
                'imei_1': orden.get('equipo', {}).get('imei', 'No especificado'),
                'imei_2': orden.get('equipo', {}).get('imei_2', 'No aplica'),
                'accesorios': orden.get('equipo', {}).get('accesorios', 'Ninguno'),
                'estado_retiro': orden.get('equipo', {}).get('estado_retiro', 'Funcionando correctamente')
            },
            'servicio': {
                'descripcion': orden.get('servicio_realizado', 'Reparación general'),
                'observaciones': orden.get('observaciones', 'Sin observaciones'),
                'tecnico': orden.get('tecnico_asignado', 'No asignado'),
                'garantia': orden.get('garantia', '90 días')
            }
        }
        
        # Renderizar la plantilla HTML
        html = render_template('comprobante.html', data=data)
        
        # Configurar pdfkit
        options = {
            'page-size': 'A4',
            'margin-top': '0.75in',
            'margin-right': '0.75in',
            'margin-bottom': '0.75in',
            'margin-left': '0.75in',
            'encoding': "UTF-8",
            'no-outline': None,
            'enable-local-file-access': None
        }
        
        # Generar PDF usando weasyprint (más estable en Windows)
        pdf_generated = False
        
        try:
            from weasyprint import HTML, CSS
            from weasyprint.text.fonts import FontConfiguration
            
            font_config = FontConfiguration()
            html_doc = HTML(string=html)
            pdf = html_doc.write_pdf(font_config=font_config)
            pdf_generated = True
            print("✅ PDF generado exitosamente con weasyprint")
            
        except ImportError:
            print("⚠️ weasyprint no está instalado, intentando con pdfkit...")
        except Exception as e:
            print(f"❌ Error generando PDF con weasyprint: {e}")
        
        # Fallback: usar pdfkit si weasyprint no está disponible o falla
        if not pdf_generated and pdfkit:
            try:
                pdf = pdfkit.from_string(html, False, options=options)
                pdf_generated = True
                print("✅ PDF generado exitosamente con pdfkit")
            except Exception as e:
                print(f"❌ Error generando PDF con pdfkit: {e}")
        
        # Si no se pudo generar PDF, devolver HTML con estilos para impresión
        if not pdf_generated:
            print("⚠️ No se pudo generar PDF, devolviendo HTML optimizado para impresión")
            # Agregar estilos de impresión al HTML
            html_with_print_styles = html.replace(
                '</head>',
                '''
                <style>
                @media print {
                    body { margin: 0; }
                    .no-print { display: none !important; }
                    .page-break { page-break-before: always; }
                }
                </style>
                <script>
                window.onload = function() {
                    // Auto-imprimir cuando se carga la página
                    setTimeout(function() {
                        window.print();
                    }, 1000);
                }
                </script>
                </head>'''
            )
            return html_with_print_styles
        
        # Crear respuesta PDF
        response = Response(pdf, mimetype='application/pdf')
        response.headers['Content-Disposition'] = f'inline; filename=comprobante_retiro_{id}.pdf'
        
        return response
        
    except Exception as e:
        print(f"Error generando comprobante: {e}")
        import traceback
        traceback.print_exc()
        flash(f'Error generando comprobante: {str(e)}', 'danger')
        return redirect(url_for('servicio_tecnico'))

@app.route('/servicio-tecnico/orden/<id>/generar-factura', methods=['POST'])
@login_required
def generar_factura_servicio(id):
    """Generar nota de entrega automáticamente desde una orden de servicio"""
    try:
        print(f"DEBUG: Iniciando generación de nota de entrega para orden {id}")
        
        ordenes = cargar_datos('ordenes_servicio.json')
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        inventario = cargar_datos('inventario.json')
        
        print(f"DEBUG: Datos cargados - Ordenes: {len(ordenes)}, Notas: {len(notas)}, Clientes: {len(clientes)}")
        
        if id not in ordenes:
            print(f"DEBUG: Orden {id} no encontrada")
            flash('Orden de servicio no encontrada', 'danger')
            return redirect(url_for('servicio_tecnico'))
        
        orden = ordenes[id]
        estado_orden = orden.get('estado', 'desconocido')
        print(f"DEBUG: Orden encontrada - Estado: {estado_orden}")
        
        # Verificar que la orden esté en estado apropiado
        if estado_orden not in ['reparado', 'entregado', 'listo_entrega']:
            print(f"DEBUG: Estado {estado_orden} no válido para generar nota")
            flash('La orden debe estar reparada, entregada o lista para entrega para generar la nota de entrega', 'warning')
            return redirect(url_for('ver_orden_servicio', id=id))
        
        print(f"DEBUG: Estado válido, procediendo con la generación")
        
        # Generar número de nota de entrega
        numero_secuencial = len(notas) + 1
        numero_nota = f"NE-{numero_secuencial:04d}"
        print(f"DEBUG: Número de nota generado: {numero_nota}")
        
        # Crear cliente si no existe
        cliente_data = orden.get('cliente', {})
        cliente_id = cliente_data.get('id') if cliente_data.get('id') else f"cliente_{len(clientes) + 1}"
        
        if cliente_id not in clientes:
            clientes[cliente_id] = {
                "id": cliente_id,
                "nombre": cliente_data.get('nombre', 'Cliente sin nombre'),
                "telefono": cliente_data.get('telefono', ''),
                "email": cliente_data.get('email', ''),
                "direccion": cliente_data.get('direccion', ''),
                "rif": cliente_data.get('rif', ''),
                "fecha_registro": datetime.now().strftime('%Y-%m-%d')
            }
            guardar_datos(ARCHIVO_CLIENTES, clientes)
        
        # Crear productos/servicios para la nota de entrega
        productos_nota = []
        cantidades = []
        precios = []
        
        # Agregar servicio de reparación
        equipo_data = orden.get('equipo', {})
        diagnostico_data = orden.get('diagnostico', {})
        marca = equipo_data.get('marca', 'N/A')
        modelo = equipo_data.get('modelo', 'N/A')
        costo_mano_obra = diagnostico_data.get('costo_mano_obra', 0)
        
        productos_nota.append(f"Servicio de Reparación - {marca} {modelo}")
        cantidades.append("1")
        precios.append(str(costo_mano_obra))
        
        # Agregar repuestos utilizados desde repuestos_seleccionados
        if diagnostico_data.get('repuestos_seleccionados'):
            try:
                import json
                repuestos_str = diagnostico_data.get('repuestos_seleccionados', '[]')
                repuestos_seleccionados = cargar_json_seguro(repuestos_str, [])
                for repuesto in repuestos_seleccionados:
                    productos_nota.append(repuesto.get('nombre', 'Repuesto'))
                    cantidades.append(str(repuesto.get('cantidad', 1)))
                    precios.append(str(repuesto.get('precio', 0)))
            except Exception as e:
                print(f"Error procesando repuestos_seleccionados: {e}")
                # Si hay error, agregar solo el detalle como texto
                if diagnostico_data.get('detalle_repuestos'):
                    productos_nota.append("Repuestos y Piezas")
                    cantidades.append("1")
                    precios.append(str(diagnostico_data.get('costo_piezas', 0)))
        
        # Obtener tasa BCV actual - SOLO USD
        try:
            tasa_bcv = obtener_tasa_bcv()  # Función principal que obtiene tasa USD
            if not tasa_bcv or tasa_bcv < 10:
                # Si no hay tasa válida, intentar obtener del BCV
                tasa_bcv = obtener_tasa_bcv_dia()
                if not tasa_bcv or tasa_bcv < 10:
                    # Fallback con tasa realista
                    tasa_bcv = cargar_ultima_tasa_bcv()
                    if not tasa_bcv or tasa_bcv < 10:
                        tasa_bcv = 216.37  # Tasa USD real actual aproximada
            fecha_tasa_bcv = datetime.now().strftime('%Y-%m-%d')
            print(f"✅ Usando tasa BCV USD: {tasa_bcv}")
        except Exception as e:
            print(f"Error obteniendo tasa BCV: {e}")
            tasa_bcv = 216.37  # Tasa USD real actual
            fecha_tasa_bcv = datetime.now().strftime('%Y-%m-%d')
        
        total_usd = diagnostico_data.get('total_estimado', 0)
        if total_usd == 0:
            # Calcular total si no está disponible
            total_usd = costo_mano_obra + diagnostico_data.get('costo_piezas', 0)
        total_bs = total_usd * tasa_bcv
        
        # Crear la nota de entrega
        nueva_nota = {
            "numero": numero_nota,
            "numero_secuencial": numero_secuencial,
            "fecha": datetime.now().strftime('%Y-%m-%d'),
            "hora": datetime.now().strftime('%H:%M:%S'),
            "timestamp_creacion": datetime.now().isoformat(),
            "cliente_id": cliente_id,
            "modalidad_pago": "contado",
            "productos": productos_nota,
            "cantidades": cantidades,
            "precios": precios,
            "subtotal_usd": total_usd,
            "total_usd": total_usd,
            "tasa_bcv": tasa_bcv,
            "fecha_tasa_bcv": fecha_tasa_bcv,
            "total_bs": total_bs,
            "estado": "PENDIENTE_ENTREGA",
            "usuario_creacion": session.get('usuario', 'admin'),
            "observaciones": f"Nota de entrega generada desde orden de servicio {orden.get('numero_orden', id)}",
            "orden_servicio_id": id,
            "firma_recibido": False,
            "fecha_entrega": None,
            "hora_entrega": None,
            "entregado_por": None,
            "recibido_por": None,
            "documento_identidad": None
        }
        
        # Guardar nota de entrega
        notas[numero_nota] = nueva_nota
        guardar_datos(ARCHIVO_NOTAS_ENTREGA, notas)
        print(f"DEBUG: Nota de entrega guardada exitosamente")
        
        # Descontar stock del inventario (solo para productos que existen en inventario)
        try:
            print(f"DEBUG: Iniciando descuento de stock del inventario")
            inventario = cargar_datos('inventario.json')
            productos_descontados = 0
            
            # Procesar repuestos del diagnóstico que puedan estar en inventario
            if diagnostico_data.get('repuestos_seleccionados'):
                try:
                    repuestos_str = diagnostico_data.get('repuestos_seleccionados', '[]')
                    repuestos_seleccionados = cargar_json_seguro(repuestos_str, [])
                    
                    for repuesto in repuestos_seleccionados:
                        # Buscar el producto en inventario por nombre o ID
                        producto_encontrado = None
                        repuesto_nombre = repuesto.get('nombre', '')
                        repuesto_id = repuesto.get('id', '')
                        for producto_id, producto_data in inventario.items():
                            if (producto_data.get('nombre', '').lower() == repuesto_nombre.lower() or 
                                producto_id == repuesto_id):
                                producto_encontrado = producto_id
                                break
                        
                        if producto_encontrado:
                            cantidad_actual = int(inventario[producto_encontrado].get('cantidad', 0))
                            cantidad_vendida = int(repuesto.get('cantidad', 1))
                            nuevo_stock = max(0, cantidad_actual - cantidad_vendida)
                            inventario[producto_encontrado]['cantidad'] = nuevo_stock
                            
                            print(f"DEBUG: Repuesto {repuesto_nombre}: Stock {cantidad_actual} → {nuevo_stock} (descontado: {cantidad_vendida})")
                            
                            # Registrar en bitácora
                            try:
                                registrar_bitacora(session.get('usuario', 'admin'), 'Descontar stock por nota de entrega', 
                                                 f"Repuesto: {repuesto_nombre}, Cantidad: {cantidad_vendida}, Stock anterior: {cantidad_actual}, Stock nuevo: {nuevo_stock}")
                            except:
                                pass  # Si hay error en bitácora, no fallar el proceso
                            
                            productos_descontados += 1
                        else:
                            print(f"DEBUG: Repuesto {repuesto_nombre} no encontrado en inventario (es un servicio)")
                            
                except Exception as e:
                    print(f"DEBUG: Error procesando repuestos_seleccionados: {e}")
            
            if productos_descontados > 0:
                guardar_datos('inventario.json', inventario)
                print(f"DEBUG: Stock descontado exitosamente para {productos_descontados} productos en nota {numero_nota}")
            else:
                print(f"DEBUG: No se descontó stock - todos los productos son servicios")
            
        except Exception as e:
            print(f"DEBUG: Error descontando stock: {e}")
            # No fallar la creación de la nota si hay error en stock
            flash(f'Nota creada pero hubo un error actualizando el inventario: {e}', 'warning')
        
        # Actualizar orden de servicio
        ordenes[id]['nota_entrega_generada'] = numero_nota
        ordenes[id]['fecha_actualizacion'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        guardar_datos('ordenes_servicio.json', ordenes)
        print(f"DEBUG: Orden de servicio actualizada")
        
        # Verificar si es una solicitud AJAX
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            print(f"DEBUG: Respondiendo con JSON para solicitud AJAX")
            print(f"DEBUG: Número de nota generada: {numero_nota}")
            print(f"DEBUG: URL de redirección: {url_for('ver_nota_entrega', id=numero_nota)}")
            return jsonify({
                'success': True,
                'message': f'Nota de entrega {numero_nota} generada exitosamente',
                'numero_nota': numero_nota,
                'redirect_url': url_for('ver_nota_entrega', id=numero_nota)
            })
        else:
            print(f"DEBUG: Redirigiendo a nota de entrega")
            print(f"DEBUG: Número de nota generada: {numero_nota}")
            print(f"DEBUG: URL de redirección: {url_for('ver_nota_entrega', id=numero_nota)}")
            flash(f'Nota de entrega {numero_nota} generada exitosamente desde la orden de servicio', 'success')
            return redirect(url_for('ver_nota_entrega', id=numero_nota))
        
    except Exception as e:
        error_msg = f'Error generando nota de entrega: {str(e)}'
        print(f"DEBUG: Error en generar_factura_servicio: {error_msg}")
        import traceback
        traceback.print_exc()
        
        # Verificar si es una solicitud AJAX
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'success': False,
                'message': error_msg
            })
        else:
            flash(error_msg, 'danger')
            return redirect(url_for('ver_orden_servicio', id=id))

@app.route('/servicio-tecnico/reportes')
@login_required
def reportes_servicio_tecnico():
    """Página de reportes detallados del servicio técnico"""
    try:
        # Cargar datos con manejo de errores
        ordenes = cargar_datos('ordenes_servicio.json')
        config = cargar_datos('config_servicio_tecnico.json')
        clientes = cargar_datos('clientes.json')
        
        # Verificar que los datos se cargaron correctamente
        if not isinstance(ordenes, dict):
            ordenes = {}
        if not isinstance(config, dict):
            config = {'estados_servicio': {}}
        if not isinstance(clientes, dict):
            clientes = {}
        
        # Estadísticas generales
        total_ordenes = len(ordenes)
        ordenes_por_estado = {}
        
        # Inicializar contadores para todos los estados
        if 'estados_servicio' in config:
            for estado_id in config['estados_servicio']:
                ordenes_por_estado[estado_id] = 0
        
        # Contar órdenes por estado
        for orden in ordenes.values():
            if isinstance(orden, dict) and 'estado' in orden:
                estado = orden.get('estado', 'desconocido')
                if estado in ordenes_por_estado:
                    ordenes_por_estado[estado] += 1
        
        # Órdenes por mes (últimos 6 meses con datos reales)
        ordenes_por_mes = {}
        ordenes_por_semana = {}
        ordenes_por_dia = {}
        
        # Generar solo los últimos 6 meses
        for i in range(6):
            fecha = datetime.now() - timedelta(days=30*i)
            mes_key = fecha.strftime('%Y-%m')
            ordenes_por_mes[mes_key] = 0
            
            for orden in ordenes.values():
                if isinstance(orden, dict) and 'fecha_recepcion' in orden:
                    if orden['fecha_recepcion'].startswith(mes_key):
                        ordenes_por_mes[mes_key] += 1
        
        # Órdenes por semana (últimas 8 semanas)
        for i in range(8):
            fecha = datetime.now() - timedelta(weeks=i)
            semana_key = fecha.strftime('%Y-W%U')
            ordenes_por_semana[semana_key] = 0
            
            for orden in ordenes.values():
                if isinstance(orden, dict) and 'fecha_recepcion' in orden:
                    try:
                        # Función auxiliar para parsear fechas de manera segura
                        def parsear_fecha(fecha_str):
                            if not fecha_str:
                                return None
                            formatos = ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%d/%m/%Y %H:%M:%S', '%d/%m/%Y']
                            for formato in formatos:
                                try:
                                    return datetime.strptime(fecha_str, formato)
                                except ValueError:
                                    continue
                            # Si falla, intentar solo la parte de fecha
                            try:
                                return datetime.strptime(fecha_str.split(' ')[0], '%Y-%m-%d')
                            except (ValueError, IndexError):
                                return None
                        
                        fecha_orden = parsear_fecha(orden['fecha_recepcion'])
                        
                        if fecha_orden and fecha_orden.strftime('%Y-W%U') == semana_key:
                            ordenes_por_semana[semana_key] += 1
                    except (ValueError, KeyError) as e:
                        # Si hay error en el parseo de fechas, continuar con la siguiente orden
                        print(f"Error parseando fecha de recepción en orden {orden.get('id', 'desconocida')}: {e}")
                        continue
        
        # Problemas más comunes (análisis detallado)
        problemas_comunes = {}
        problemas_detallados = {}
        equipos_por_tipo = {}
        equipos_por_modelo = {}
        
        for orden in ordenes.values():
            if isinstance(orden, dict) and 'problema_reportado' in orden:
                problema = str(orden['problema_reportado']).lower()
                
                # Análisis detallado de problemas
            if 'pantalla' in problema or 'pantalla' in problema:
                problemas_comunes['Pantalla'] = problemas_comunes.get('Pantalla', 0) + 1
                if 'rota' in problema:
                    problemas_detallados['Pantalla Rota'] = problemas_detallados.get('Pantalla Rota', 0) + 1
                elif 'no responde' in problema or 'tactil' in problema:
                    problemas_detallados['Pantalla No Responde'] = problemas_detallados.get('Pantalla No Responde', 0) + 1
                else:
                    problemas_detallados['Problemas de Pantalla'] = problemas_detallados.get('Problemas de Pantalla', 0) + 1
            elif 'bateria' in problema or 'batería' in problema:
                problemas_comunes['Batería'] = problemas_comunes.get('Batería', 0) + 1
                if 'no carga' in problema:
                    problemas_detallados['Batería No Carga'] = problemas_detallados.get('Batería No Carga', 0) + 1
                elif 'se agota' in problema or 'duración' in problema:
                    problemas_detallados['Batería Se Agota Rápido'] = problemas_detallados.get('Batería Se Agota Rápido', 0) + 1
                else:
                    problemas_detallados['Problemas de Batería'] = problemas_detallados.get('Problemas de Batería', 0) + 1
            elif 'carga' in problema:
                problemas_comunes['Problemas de Carga'] = problemas_comunes.get('Problemas de Carga', 0) + 1
                problemas_detallados['Problemas de Carga'] = problemas_detallados.get('Problemas de Carga', 0) + 1
            elif 'no enciende' in problema:
                problemas_comunes['No Enciende'] = problemas_comunes.get('No Enciende', 0) + 1
                problemas_detallados['No Enciende'] = problemas_detallados.get('No Enciende', 0) + 1
            elif 'audio' in problema or 'sonido' in problema:
                problemas_comunes['Audio'] = problemas_comunes.get('Audio', 0) + 1
                problemas_detallados['Problemas de Audio'] = problemas_detallados.get('Problemas de Audio', 0) + 1
            elif 'camara' in problema or 'cámara' in problema:
                problemas_comunes['Cámara'] = problemas_comunes.get('Cámara', 0) + 1
                problemas_detallados['Problemas de Cámara'] = problemas_detallados.get('Problemas de Cámara', 0) + 1
            elif 'wifi' in problema or 'conectividad' in problema:
                problemas_comunes['Conectividad'] = problemas_comunes.get('Conectividad', 0) + 1
                problemas_detallados['Problemas de Conectividad'] = problemas_detallados.get('Problemas de Conectividad', 0) + 1
            else:
                problemas_comunes['Otros'] = problemas_comunes.get('Otros', 0) + 1
                problemas_detallados['Otros Problemas'] = problemas_detallados.get('Otros Problemas', 0) + 1
                
            # Análisis de equipos
            if 'equipo' in orden and isinstance(orden['equipo'], dict):
                if 'marca' in orden['equipo']:
                    marca = orden['equipo']['marca']
                    equipos_por_tipo[marca] = equipos_por_tipo.get(marca, 0) + 1
                    
                    if 'modelo' in orden['equipo']:
                        modelo = orden['equipo']['modelo']
                        equipos_por_modelo[f"{marca} {modelo}"] = equipos_por_modelo.get(f"{marca} {modelo}", 0) + 1
        
        # Análisis de clientes
        clientes_activos = {}
        clientes_por_ordenes = {}
        clientes_por_estado = {}
        
        for orden in ordenes.values():
            if isinstance(orden, dict) and 'cliente' in orden and isinstance(orden['cliente'], dict):
                cliente_id = orden['cliente'].get('id', 'desconocido')
                cliente_nombre = orden['cliente'].get('nombre', 'Cliente Desconocido')
                
                if cliente_id not in clientes_activos:
                    clientes_activos[cliente_id] = {
                        'nombre': cliente_nombre,
                        'telefono': orden['cliente'].get('telefono', ''),
                        'email': orden['cliente'].get('email', ''),
                        'total_ordenes': 0,
                        'ordenes_completadas': 0,
                        'ordenes_canceladas': 0,
                        'ultima_orden': orden.get('fecha_recepcion', ''),
                        'estados': set()
                    }
                
                clientes_activos[cliente_id]['total_ordenes'] += 1
                clientes_activos[cliente_id]['estados'].add(orden.get('estado', ''))
                
                if orden.get('estado') == 'entregado':
                    clientes_activos[cliente_id]['ordenes_completadas'] += 1
                elif orden.get('estado') == 'cancelado':
                    clientes_activos[cliente_id]['ordenes_canceladas'] += 1
        
        # Convertir sets a listas para JSON
        for cliente in clientes_activos.values():
            cliente['estados'] = list(cliente['estados'])
        
        
        
        # Análisis de días de la semana
        ordenes_por_dia_semana = {}
        for orden in ordenes.values():
            if isinstance(orden, dict) and 'fecha_recepcion' in orden:
                try:
                    fecha = parsear_fecha(orden['fecha_recepcion'])
                    if fecha:
                        dia_semana = fecha.strftime('%A')
                        ordenes_por_dia_semana[dia_semana] = ordenes_por_dia_semana.get(dia_semana, 0) + 1
                except:
                    continue
        
        # Análisis de horas del día (si tenemos datos de hora)
        ordenes_por_hora = {}
        for orden in ordenes.values():
            if isinstance(orden, dict) and 'fecha_recepcion' in orden:
                try:
                    fecha_str = orden['fecha_recepcion']
                    if ' ' in fecha_str:  # Si incluye hora
                        hora = fecha_str.split(' ')[1].split(':')[0]
                        ordenes_por_hora[hora] = ordenes_por_hora.get(hora, 0) + 1
                except:
                    continue
        
        # Análisis de eficiencia por estado
        tiempos_por_estado = {}
        for orden in ordenes.values():
            if isinstance(orden, dict) and 'estado' in orden and 'fecha_recepcion' in orden and 'fecha_entrega' in orden:
                estado = orden.get('estado', 'desconocido')
                try:
                    fecha_recepcion = datetime.strptime(orden['fecha_recepcion'], '%Y-%m-%d')
                    fecha_entrega = datetime.strptime(orden['fecha_entrega'], '%Y-%m-%d')
                    dias_diferencia = (fecha_entrega - fecha_recepcion).days
                    if dias_diferencia >= 0:  # Solo incluir fechas válidas
                        if estado not in tiempos_por_estado:
                            tiempos_por_estado[estado] = []
                        tiempos_por_estado[estado].append(dias_diferencia)
                except:
                    continue
        
        eficiencia_por_estado = {}
        for estado, tiempos in tiempos_por_estado.items():
            if tiempos:
                eficiencia_por_estado[estado] = {
                    'promedio': sum(tiempos) / len(tiempos),
                    'cantidad': len(tiempos),
                    'eficiencia': 'alta' if sum(tiempos) / len(tiempos) < 3 else 'media' if sum(tiempos) / len(tiempos) < 7 else 'baja'
                }
        
        # Análisis de costos
        costos_mano_obra = []
        costos_piezas = []
        costos_totales = []
        
        for orden in ordenes.values():
            if isinstance(orden, dict) and 'diagnostico' in orden and isinstance(orden['diagnostico'], dict):
                costo_mano_obra = orden['diagnostico'].get('costo_mano_obra', 0)
                costo_piezas = orden['diagnostico'].get('costo_piezas', 0)
                costo_total = orden['diagnostico'].get('total_estimado', 0)
                
                if costo_mano_obra > 0:
                    costos_mano_obra.append(costo_mano_obra)
                if costo_piezas > 0:
                    costos_piezas.append(costo_piezas)
                if costo_total > 0:
                    costos_totales.append(costo_total)
        
        # Ordenar datos
        problemas_ordenados = sorted(problemas_comunes.items(), key=lambda x: x[1], reverse=True)
        problemas_detallados_ordenados = sorted(problemas_detallados.items(), key=lambda x: x[1], reverse=True)
        equipos_ordenados = sorted(equipos_por_tipo.items(), key=lambda x: x[1], reverse=True)
        modelos_ordenados = sorted(equipos_por_modelo.items(), key=lambda x: x[1], reverse=True)
        clientes_ordenados = sorted(clientes_activos.items(), key=lambda x: x[1]['total_ordenes'], reverse=True)
        meses_ordenados = sorted(ordenes_por_mes.items(), key=lambda x: x[0], reverse=True)
        semanas_ordenadas = sorted(ordenes_por_semana.items(), key=lambda x: x[0], reverse=True)
        
        # Calcular valores máximos
        max_problemas = max(problemas_comunes.values()) if problemas_comunes else 0
        max_equipos = max(equipos_por_tipo.values()) if equipos_por_tipo else 0
        max_meses = max(ordenes_por_mes.values()) if ordenes_por_mes else 0
        max_semanas = max(ordenes_por_semana.values()) if ordenes_por_semana else 0
        
        # Calcular tiempo promedio de reparación
        tiempos_reparacion = []
        for orden in ordenes.values():
            if isinstance(orden, dict) and 'fecha_recepcion' in orden and 'fecha_entrega' in orden:
                try:
                    fecha_recepcion = datetime.strptime(orden['fecha_recepcion'], '%Y-%m-%d')
                    fecha_entrega = datetime.strptime(orden['fecha_entrega'], '%Y-%m-%d')
                    dias_diferencia = (fecha_entrega - fecha_recepcion).days
                    if dias_diferencia >= 0:  # Solo incluir fechas válidas
                        tiempos_reparacion.append(dias_diferencia)
                except:
                    continue
        
        tiempo_promedio = sum(tiempos_reparacion) / len(tiempos_reparacion) if tiempos_reparacion else 0
        
        return render_template('servicio_tecnico/reportes.html',
                             total_ordenes=total_ordenes,
                             ordenes_por_estado=ordenes_por_estado,
                             ordenes_por_mes=ordenes_por_mes,
                             ordenes_por_semana=ordenes_por_semana,
                             problemas_comunes=problemas_comunes,
                             problemas_ordenados=problemas_ordenados,
                             problemas_detallados=problemas_detallados,
                             problemas_detallados_ordenados=problemas_detallados_ordenados,
                             equipos_por_tipo=equipos_por_tipo,
                             equipos_ordenados=equipos_ordenados,
                             equipos_por_modelo=equipos_por_modelo,
                             modelos_ordenados=modelos_ordenados,
                             clientes_activos=clientes_activos,
                             clientes_ordenados=clientes_ordenados,
                             ordenes_por_dia_semana=ordenes_por_dia_semana,
                             ordenes_por_hora=ordenes_por_hora,
                             eficiencia_por_estado=eficiencia_por_estado,
                             costos_mano_obra=costos_mano_obra,
                             costos_piezas=costos_piezas,
                             costos_totales=costos_totales,
                             meses_ordenados=meses_ordenados,
                             semanas_ordenadas=semanas_ordenadas,
                             max_problemas=max_problemas,
                             max_equipos=max_equipos,
                             max_meses=max_meses,
                             max_semanas=max_semanas,
                             tiempo_promedio=tiempo_promedio,
                             config=config)
        
    except Exception as e:
        print(f"Error en reportes_servicio_tecnico: {str(e)}")
        flash(f'Error cargando reportes: {str(e)}', 'danger')
        return render_template('servicio_tecnico/reportes.html', 
                             total_ordenes=0,
                             ordenes_por_estado={},
                             ordenes_por_mes={},
                             ordenes_por_semana={},
                             problemas_comunes={},
                             problemas_ordenados=[],
                             problemas_detallados={},
                             problemas_detallados_ordenados=[],
                             equipos_por_tipo={},
                             equipos_ordenados=[],
                             equipos_por_modelo={},
                             modelos_ordenados=[],
                             clientes_activos={},
                             clientes_ordenados=[],
                             tiempos_promedio_mes={},
                             tiempos_promedio_semana={},
                             costos_mano_obra=[],
                             costos_piezas=[],
                             costos_totales=[],
                             meses_ordenados=[],
                             semanas_ordenadas=[],
                             max_problemas=0,
                             max_equipos=0,
                             max_meses=0,
                             max_semanas=0,
                             tiempo_promedio=0,
                             config={'estados_servicio': {}})

@app.route('/servicio-tecnico/orden/<id>/editar', methods=['GET', 'POST'])
@login_required
def editar_orden_servicio(id):
    """Editar una orden de servicio existente"""
    try:
        ordenes = cargar_datos('ordenes_servicio.json')
        
        if id not in ordenes:
            flash('Orden de servicio no encontrada', 'danger')
            return redirect(url_for('servicio_tecnico'))
        
        orden = ordenes[id]
        
        if request.method == 'POST':
            # Actualizar información general
            orden['estado'] = request.form.get('estado', orden['estado'])
            orden['prioridad'] = request.form.get('prioridad', orden.get('prioridad', 'media'))
            orden['fecha_recepcion'] = request.form.get('fecha_recepcion', orden['fecha_recepcion'])
            orden['fecha_entrega_estimada'] = request.form.get('fecha_entrega_estimada', orden.get('fecha_entrega_estimada', ''))
            orden['tecnico_asignado'] = request.form.get('tecnico_asignado', orden.get('tecnico_asignado', ''))
            orden['costo_estimado'] = safe_float(request.form.get('costo_estimado', 0)) if request.form.get('costo_estimado') else 0.0
            orden['tipo_servicio'] = request.form.get('tipo_servicio', orden.get('tipo_servicio', ''))
            
            # Actualizar datos del cliente
            if 'cliente' not in orden:
                orden['cliente'] = {}
            
            # Asegurar que el cliente tenga todos los campos necesarios
            if 'cedula_rif' not in orden['cliente']:
                orden['cliente']['cedula_rif'] = ''
            if 'nombre' not in orden['cliente']:
                orden['cliente']['nombre'] = ''
            if 'telefono' not in orden['cliente']:
                orden['cliente']['telefono'] = ''
            if 'telefono2' not in orden['cliente']:
                orden['cliente']['telefono2'] = ''
            if 'email' not in orden['cliente']:
                orden['cliente']['email'] = ''
            if 'direccion' not in orden['cliente']:
                orden['cliente']['direccion'] = ''
            
            orden['cliente']['nombre'] = request.form.get('cliente_nombre', orden['cliente'].get('nombre', ''))
            orden['cliente']['cedula_rif'] = request.form.get('cliente_cedula', orden['cliente'].get('cedula_rif', ''))
            orden['cliente']['telefono'] = request.form.get('cliente_telefono', orden['cliente'].get('telefono', ''))
            orden['cliente']['telefono2'] = request.form.get('cliente_telefono2', orden['cliente'].get('telefono2', ''))
            orden['cliente']['email'] = request.form.get('cliente_email', orden['cliente'].get('email', ''))
            orden['cliente']['direccion'] = request.form.get('cliente_direccion', orden['cliente'].get('direccion', ''))
            
            # Actualizar datos del equipo
            if 'equipo' not in orden:
                orden['equipo'] = {}
            
            orden['equipo']['marca'] = request.form.get('equipo_marca', orden['equipo'].get('marca', ''))
            orden['equipo']['modelo'] = request.form.get('equipo_modelo', orden['equipo'].get('modelo', ''))
            orden['equipo']['imei'] = request.form.get('equipo_imei1', orden['equipo'].get('imei', ''))
            orden['equipo']['imei2'] = request.form.get('equipo_imei2', orden['equipo'].get('imei2', ''))
            orden['equipo']['color'] = request.form.get('equipo_color', orden['equipo'].get('color', ''))
            orden['equipo']['numero_serie'] = request.form.get('equipo_serial', orden['equipo'].get('numero_serie', ''))
            
            # Actualizar problema reportado
            orden['problema_reportado'] = request.form.get('problema_reportado', orden.get('problema_reportado', ''))
            
            # Actualizar observaciones internas
            orden['observaciones_internas'] = request.form.get('observaciones_internas', orden.get('observaciones_internas', ''))
            orden['cliente_notificado'] = 'cliente_notificado' in request.form
            orden['atendido_por'] = request.form.get('atendido_por', orden.get('atendido_por', ''))
            
            # Actualizar configuración de desbloqueo
            if 'desbloqueo' not in orden:
                orden['desbloqueo'] = {}
            
            tipo_desbloqueo = request.form.get('tipo_desbloqueo', '')
            estado_desbloqueo = request.form.get('estado_desbloqueo', '')
            clave_desbloqueo = request.form.get('clave_desbloqueo', '')
            notas_desbloqueo = request.form.get('notas_desbloqueo', '')
            
            print(f"DEBUG: Datos de desbloqueo recibidos:")
            print(f"  - Tipo: '{tipo_desbloqueo}'")
            print(f"  - Estado: '{estado_desbloqueo}'")
            print(f"  - Clave: '{clave_desbloqueo[:20]}...' (truncado)")
            print(f"  - Notas: '{notas_desbloqueo}'")
            
            orden['desbloqueo']['tipo'] = tipo_desbloqueo
            orden['desbloqueo']['estado'] = estado_desbloqueo
            orden['desbloqueo']['clave'] = clave_desbloqueo
            orden['desbloqueo']['notas'] = notas_desbloqueo
            
            print(f"DEBUG: Datos de desbloqueo guardados en orden:")
            print(f"  - Tipo: '{orden['desbloqueo']['tipo']}'")
            print(f"  - Estado: '{orden['desbloqueo']['estado']}'")
            print(f"  - Clave: '{orden['desbloqueo']['clave'][:20]}...' (truncado)")
            print(f"  - Notas: '{orden['desbloqueo']['notas']}'")
            
            # Agregar entrada al historial si el estado cambió
            estado_anterior = orden.get('estado_anterior', orden['estado'])
            if estado_anterior != orden['estado']:
                if 'historial_estados' not in orden:
                    orden['historial_estados'] = []
                
                orden['historial_estados'].append({
                    'estado': orden['estado'],
                    'fecha': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'usuario': session.get('usuario', 'Sistema'),
                    'comentarios': f'Estado cambiado de {estado_anterior} a {orden["estado"]}'
                })
            
            # Actualizar fecha de modificación
            orden['fecha_actualizacion'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # Guardar cambios
            guardar_datos('ordenes_servicio.json', ordenes)
            flash('Orden de servicio actualizada correctamente', 'success')
            return redirect(url_for('ver_orden_servicio', id=id))
        
        return render_template('servicio_tecnico/editar_orden.html', orden=orden)
        
    except Exception as e:
        print(f"Error editando orden de servicio: {e}")
        flash(f'Error al editar la orden de servicio: {str(e)}', 'danger')
        return redirect(url_for('servicio_tecnico'))

@app.route('/servicio-tecnico/orden/<id>/completar', methods=['POST'])
@login_required
def completar_borrador_servicio(id):
    """Completar un borrador y convertirlo en orden activa"""
    try:
        ordenes = cargar_datos('ordenes_servicio.json')
        
        if id not in ordenes:
            return jsonify({'success': False, 'message': 'Orden no encontrada'})
        
        orden = ordenes[id]
        
        if not orden.get('es_borrador'):
            return jsonify({'success': False, 'message': 'Esta orden no es un borrador'})
        
        # Cambiar estado a activo
        orden['estado'] = 'en_espera_revision'
        orden['es_borrador'] = False
        orden['fecha_actualizacion'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Agregar entrada al historial
        if 'historial_estados' not in orden:
            orden['historial_estados'] = []
        
        orden['historial_estados'].append({
            'estado': 'en_espera_revision',
            'fecha': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'usuario': session.get('usuario', 'Sistema'),
            'comentarios': 'Borrador completado y convertido en orden activa'
        })
        
        # Guardar cambios
        guardar_datos('ordenes_servicio.json', ordenes)
        
        return jsonify({'success': True, 'message': 'Borrador completado correctamente'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error al completar el borrador: {str(e)}'})

@app.route('/servicio-tecnico/orden/<id>/eliminar', methods=['DELETE'])
@login_required
def eliminar_orden_servicio(id):
    """Eliminar una orden de servicio"""
    try:
        ordenes = cargar_datos('ordenes_servicio.json')
        
        if id not in ordenes:
            return jsonify({'success': False, 'message': 'Orden de servicio no encontrada'}), 404
        
        # Eliminar la orden
        del ordenes[id]
        guardar_datos('ordenes_servicio.json', ordenes)
        
        return jsonify({'success': True, 'message': 'Orden de servicio eliminada correctamente'})
        
    except Exception as e:
        print(f"Error eliminando orden de servicio: {e}")
        return jsonify({'success': False, 'message': 'Error al eliminar la orden de servicio'}), 500

@app.route('/servicio-tecnico/reportes/pdf')
@login_required
def reportes_servicio_tecnico_pdf():
    """Genera un reporte en PDF del servicio técnico"""
    try:
        # Reutilizar la misma lógica de reportes pero para PDF
        
        ordenes = cargar_datos('ordenes_servicio.json')
        config = cargar_datos('config_servicio_tecnico.json')
        
        if not isinstance(ordenes, dict):
            ordenes = {}
        if not isinstance(config, dict):
            config = {'estados_servicio': {}}
        
        # Estadísticas básicas para PDF
        total_ordenes = len(ordenes)
        ordenes_por_estado = {}
        
        if 'estados_servicio' in config:
            for estado_id in config['estados_servicio']:
                ordenes_por_estado[estado_id] = 0
        
        for orden in ordenes.values():
            if isinstance(orden, dict) and 'estado' in orden:
                estado = orden['estado']
                if estado in ordenes_por_estado:
                    ordenes_por_estado[estado] += 1
        
        # Problemas comunes
        problemas_comunes = {}
        for orden in ordenes.values():
            if isinstance(orden, dict) and 'problema_reportado' in orden:
                problema = str(orden['problema_reportado']).lower()
                if 'pantalla' in problema:
                    problemas_comunes['Pantalla'] = problemas_comunes.get('Pantalla', 0) + 1
                elif 'bateria' in problema or 'batería' in problema:
                    problemas_comunes['Batería'] = problemas_comunes.get('Batería', 0) + 1
                elif 'carga' in problema:
                    problemas_comunes['Problemas de Carga'] = problemas_comunes.get('Problemas de Carga', 0) + 1
                elif 'no enciende' in problema:
                    problemas_comunes['No Enciende'] = problemas_comunes.get('No Enciende', 0) + 1
                else:
                    problemas_comunes['Otros'] = problemas_comunes.get('Otros', 0) + 1
        
        problemas_ordenados = sorted(problemas_comunes.items(), key=lambda x: x[1], reverse=True)
        
        return render_template('servicio_tecnico/reportes_pdf.html',
                             total_ordenes=total_ordenes,
                             ordenes_por_estado=ordenes_por_estado,
                             problemas_ordenados=problemas_ordenados,
                             config=config,
                             fecha_generacion=datetime.now().strftime('%d/%m/%Y %H:%M'))
        
    except Exception as e:
        print(f"Error generando PDF: {str(e)}")
        flash(f'Error generando PDF: {str(e)}', 'danger')
        return redirect(url_for('reportes_servicio_tecnico'))

# Ruta de prueba específica para WhatsApp
@app.route('/test-whatsapp-simple/<path:cliente_id>')
def test_whatsapp_simple(cliente_id):
    """Ruta de prueba simple para verificar que la ruta funciona"""
    try:
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        if cliente_id not in clientes:
            return jsonify({'error': 'Cliente no encontrado'}), 404
        
        cliente = clientes[cliente_id]
        return jsonify({
            'success': True,
            'cliente_id': cliente_id,
            'cliente_nombre': cliente.get('nombre', 'N/A'),
            'telefono': cliente.get('telefono', 'N/A')
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Ruta de debug para ver qué está pasando (sin login para pruebas)
@app.route('/debug-whatsapp/<path:cliente_id>')
def debug_whatsapp(cliente_id):
    """Ruta de debug para diagnosticar problemas con WhatsApp"""
    try:
        print(f"🔍 DEBUG WhatsApp para cliente: {cliente_id}")
        
        # Cargar datos
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        
        print(f"📊 Clientes cargados: {len(clientes)}")
        print(f"📊 Facturas cargadas: {len(facturas)}")
        
        if cliente_id not in clientes:
            return jsonify({'error': 'Cliente no encontrado'}), 404
        
        cliente = clientes[cliente_id]
        telefono = cliente.get('telefono', '')
        
        notas_cliente = []
        for nota_id, nota in notas.items():
            if nota.get('cliente_id') == cliente_id:
                notas_cliente.append({
                    'id': factura_id,
                    'numero': nota.get('numero', 'N/A'),
                    'total_usd': nota.get('total_usd', 0),
                    'total_abonado': nota.get('total_abonado', 0)
                })
        
        debug_info = {
            'cliente_id': cliente_id,
            'cliente_nombre': cliente.get('nombre', 'N/A'),
            'telefono_original': telefono,
            'telefono_tipo': str(type(telefono)),
            'facturas_encontradas': len(notas_cliente),
            'tiene_telefono': bool(telefono and str(telefono).strip()),
            'longitud_telefono': len(str(telefono)) if telefono else 0
        }
        
        print(f"🔍 Debug info: {debug_info}")
        return jsonify(debug_info)
        
    except Exception as e:
        print(f"❌ Error en debug: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# Ruta para servir la página de prueba
@app.route('/test-whatsapp-routes')
def test_whatsapp_routes():
    """Página de prueba para verificar que las rutas de WhatsApp funcionan"""
    return render_template('test_whatsapp.html')



# Ruta de prueba que funciona exactamente como la principal pero sin autenticación
@app.route('/test-whatsapp-working/<path:cliente_id>', methods=['POST'])
@csrf.exempt
def test_whatsapp_working(cliente_id):
    """Ruta de prueba que funciona exactamente como la principal pero sin autenticación"""
    try:
        print(f"🔍 TEST WhatsApp WORKING para cliente: {cliente_id}")
        
        # Cargar datos
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        
        if cliente_id not in clientes:
            return jsonify({
                'error': 'Cliente no encontrado',
                'cliente_id_buscado': cliente_id,
                'clientes_disponibles': list(clientes.keys())[:10]
            }), 404
        
        cliente = clientes[cliente_id]
        telefono = cliente.get('telefono', '')
        
        if not telefono or str(telefono).strip() == '':
            return jsonify({
                'error': 'Cliente sin teléfono',
                'cliente_id': cliente_id,
                'cliente_nombre': cliente.get('nombre', 'N/A'),
                'telefono': telefono
            }), 400
        
        facturas_pendientes = []
        total_pendiente = 0.0
        
        for nota_id, nota in notas.items():
            if nota.get('cliente_id') == cliente_id:
                total_nota = safe_float(nota.get('total_usd', 0))
                total_abonado = safe_float(nota.get('total_abonado', 0))
                saldo_pendiente = max(0, total_nota - total_abonado)
                
                if saldo_pendiente > 0:
                    facturas_pendientes.append({
                        'id': factura_id,
                        'numero': nota.get('numero', 'N/A'),
                        'saldo': saldo_pendiente
                    })
                    total_pendiente += saldo_pendiente
        
        # Crear mensaje simple
        mensaje = f"Hola {cliente.get('nombre', 'Cliente')}, tienes {len(facturas_pendientes)} facturas pendientes por un total de ${total_pendiente:.2f} USD. Por favor contacta para coordinar el pago."
        
        # Generar enlace simple
        telefono_limpio = str(telefono).replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        if not telefono_limpio.startswith('58'):
            telefono_limpio = '58' + telefono_limpio.lstrip('0')
        enlace_whatsapp = f"https://wa.me/{telefono_limpio}?text={mensaje.replace(' ', '%20')}"
        
        return jsonify({
            'success': True,
            'cliente_id': cliente_id,
            'cliente_nombre': cliente.get('nombre', 'N/A'),
            'telefono': telefono,
            'telefono_formateado': telefono_limpio,
            'facturas_pendientes': len(facturas_pendientes),
            'total_pendiente': total_pendiente,
            'mensaje': mensaje,
            'enlace_whatsapp': enlace_whatsapp
        })
        
    except Exception as e:
        print(f"❌ Error en test working: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# Ruta de prueba que simula el botón de WhatsApp (sin login)
@app.route('/test-whatsapp-button/<path:cliente_id>')
def test_whatsapp_button(cliente_id):
    """Ruta de prueba que simula exactamente lo que hace el botón de WhatsApp"""
    try:
        print(f"🔍 TEST WhatsApp Button para cliente: {cliente_id}")
        
        # Cargar datos
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        
        if cliente_id not in clientes:
            return jsonify({'error': 'Cliente no encontrado'}), 404
        
        cliente = clientes[cliente_id]
        telefono = cliente.get('telefono', '')
        
        # Simular el mismo flujo que la función principal
        if not telefono or str(telefono).strip() == '':
            return jsonify({
                'error': 'Cliente sin teléfono',
                'cliente_id': cliente_id,
                'cliente_nombre': cliente.get('nombre', 'N/A'),
                'telefono': telefono
            }), 400
        
        facturas_pendientes = []
        total_pendiente = 0.0
        
        for nota_id, nota in notas.items():
            if nota.get('cliente_id') == cliente_id:
                total_nota = safe_float(nota.get('total_usd', 0))
                total_abonado = safe_float(nota.get('total_abonado', 0))
                saldo_pendiente = max(0, total_nota - total_abonado)
                
                if saldo_pendiente > 0:
                    facturas_pendientes.append({
                        'id': factura_id,
                        'numero': nota.get('numero', 'N/A'),
                        'saldo': saldo_pendiente
                    })
                    total_pendiente += saldo_pendiente
        
        return jsonify({
            'success': True,
            'cliente_id': cliente_id,
            'cliente_nombre': cliente.get('nombre', 'N/A'),
            'telefono': telefono,
            'facturas_pendientes': len(facturas_pendientes),
            'total_pendiente': total_pendiente,
        })
        
    except Exception as e:
        print(f"❌ Error en test: {e}")
        return jsonify({'error': str(e)}), 500

# Ruta de prueba sin login para diagnosticar problemas
@app.route('/test-whatsapp-no-login/<path:cliente_id>', methods=['POST'])
@csrf.exempt
def test_whatsapp_no_login(cliente_id):
    """Ruta de prueba sin login para diagnosticar problemas de WhatsApp"""
    try:
        print(f"🔍 TEST WhatsApp NO LOGIN para cliente: {cliente_id}")
        
        # Cargar datos
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        
        if cliente_id not in clientes:
            return jsonify({
                'error': 'Cliente no encontrado',
                'cliente_id_buscado': cliente_id,
                'clientes_disponibles': list(clientes.keys())[:10]
            }), 404
        
        cliente = clientes[cliente_id]
        telefono = cliente.get('telefono', '')
        
        # Simular el mismo flujo que la función principal
        if not telefono or str(telefono).strip() == '':
            return jsonify({
                'error': 'Cliente sin teléfono',
                'cliente_id': cliente_id,
                'cliente_nombre': cliente.get('nombre', 'N/A'),
                'telefono': telefono
            }), 400
        
        facturas_pendientes = []
        total_pendiente = 0.0
        
        for nota_id, nota in notas.items():
            if nota.get('cliente_id') == cliente_id:
                total_nota = safe_float(nota.get('total_usd', 0))
                total_abonado = safe_float(nota.get('total_abonado', 0))
                saldo_pendiente = max(0, total_nota - total_abonado)
                
                if saldo_pendiente > 0:
                    facturas_pendientes.append({
                        'id': factura_id,
                        'numero': nota.get('numero', 'N/A'),
                        'saldo': saldo_pendiente
                    })
                    total_pendiente += saldo_pendiente
        
        return jsonify({
            'success': True,
            'cliente_id': cliente_id,
            'cliente_nombre': cliente.get('nombre', 'N/A'),
            'telefono': telefono,
            'facturas_pendientes': len(facturas_pendientes),
            'total_pendiente': total_pendiente,
        })
        
    except Exception as e:
        print(f"❌ Error en test no login: {e}")
        return jsonify({'error': str(e)}), 500

# RUTA CON PARÁMETROS - COMENTADA Y ELIMINADA PARA EVITAR ERRORES DE SINTAXIS
# Esta ruta estaba comentada pero contenía código ejecutable que causaba errores.
# Si se necesita en el futuro, debe reescribirse correctamente.
# @app.route('/cuentas-por-cobrar/<path:cliente_id>/enviar_recordatorio_whatsapp', methods=['POST'])
# def enviar_recordatorio_cuentas_por_cobrar_con_parametros(cliente_id):
#     # Código eliminado - estaba causando errores de sintaxis

# Función auxiliar para enviar recordatorios
def enviar_recordatorio_cuentas_por_cobrar(cliente_id):
    try:
        # Verificar autenticación manualmente para mejor manejo de errores
        if 'usuario' not in session:
            print("❌ Usuario no autenticado")
            return jsonify({
                'error': 'Usuario no autenticado',
                'redirect': url_for('login')
            }), 401
        
        print(f"🔍 Iniciando envío de recordatorio WhatsApp para cliente: {cliente_id}")
        
        # Cargar datos necesarios
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        
        print(f"📊 Facturas cargadas: {len(facturas)}")
        print(f"👥 Clientes cargados: {len(clientes)}")
        
        if cliente_id not in clientes:
            print(f"❌ Cliente {cliente_id} no encontrado")
            return jsonify({
                'error': 'Cliente no encontrado',
                'debug_info': {
                    'cliente_id_buscado': cliente_id,
                    'clientes_disponibles': list(clientes.keys())[:10]
                }
            }), 404
        
        cliente = clientes[cliente_id]
        telefono = cliente.get('telefono', '')
        
        print(f"👤 Cliente: {cliente.get('nombre', 'N/A')}")
        print(f"📱 Teléfono: '{telefono}' (tipo: {type(telefono)})")
        
        if not telefono or str(telefono).strip() == '':
            print(f"❌ Cliente {cliente_id} no tiene teléfono o está vacío")
            return jsonify({
                'error': 'El cliente no tiene número de teléfono registrado o está vacío',
                'debug_info': {
                    'cliente_id': cliente_id,
                    'cliente_nombre': cliente.get('nombre', 'N/A'),
                    'telefono_valor': telefono,
                    'telefono_tipo': str(type(telefono))
                }
            }), 400
        
        facturas_pendientes = []
        total_pendiente = 0.0
        
        for nota_id, nota in notas.items():
            if nota.get('cliente_id') == cliente_id:
                # Calcular saldo pendiente
                total_nota = safe_float(nota.get('total_usd', 0))
                total_abonado = safe_float(nota.get('total_abonado', 0))
                saldo_pendiente = max(0, total_nota - total_abonado)
                
                if saldo_pendiente > 0:
                    facturas_pendientes.append({
                        'id': factura_id,
                        'numero': nota.get('numero', 'N/A'),
                        'fecha': nota.get('fecha', 'N/A'),
                        'total': total_nota,
                        'abonado': total_abonado,
                        'saldo': saldo_pendiente,
                        'vencimiento': nota.get('fecha_vencimiento', 'No especificado')
                    })
                    total_pendiente += saldo_pendiente
        
        if not facturas_pendientes:
            print(f"✅ Cliente {cliente_id} no tiene facturas pendientes")
            return jsonify({
                'success': True,
                'message': 'El cliente no tiene facturas pendientes de pago',
                'facturas_pendientes': 0,
                'total_pendiente': 0
            })
        
        print(f"📋 Facturas pendientes encontradas: {len(facturas_pendientes)}")
        print(f"💰 Total pendiente: ${total_pendiente:.2f}")
        
        # Limpiar y formatear el número de teléfono
        telefono_original = telefono
        print(f"📱 Teléfono original recibido: '{telefono}' (tipo: {type(telefono)})")
        
        try:
            # Formateo simple y directo
            telefono = str(telefono).replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
            if not telefono.startswith('58'):
                telefono = '58' + telefono.lstrip('0')
            print(f"📱 Teléfono formateado exitosamente: {telefono}")
        except Exception as e:
            print(f"❌ Error formateando teléfono: {e}")
            return jsonify({
                'error': f'Error formateando número de teléfono: {str(e)}',
                'debug_info': {
                    'telefono_original': telefono_original,
                    'tipo_telefono': str(type(telefono_original)),
                    'cliente_id': cliente_id,
                    'cliente_nombre': cliente.get('nombre', 'N/A')
                }
            }), 400
        
        if not telefono or len(str(telefono)) < 8:
            print(f"❌ Teléfono formateado no válido: {telefono}")
            return jsonify({
                'error': 'El número de teléfono no es válido después del formateo',
                'debug_info': {
                    'telefono_formateado': telefono,
                    'longitud': len(str(telefono)) if telefono else 0,
                    'cliente_id': cliente_id
                }
            }), 400
        
        # Crear mensaje personalizado para cuentas por cobrar
        try:
            # Mensaje simple y directo
            mensaje = f"Hola {cliente.get('nombre', 'Cliente')}, tienes {len(facturas_pendientes)} facturas pendientes por un total de ${total_pendiente:.2f} USD. Por favor contacta para coordinar el pago."
            print(f"💬 Mensaje creado exitosamente: {len(mensaje)} caracteres")
            print(f"💬 Mensaje completo: {mensaje}")
        except Exception as e:
            print(f"❌ Error creando mensaje: {e}")
            return jsonify({'error': f'Error creando mensaje: {str(e)}'}), 400
        
        # Generar enlace de WhatsApp
        try:
            # Enlace simple y directo
            telefono_limpio = str(telefono).replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
            print(f"🔗 Teléfono limpio: {telefono_limpio}")
            if not telefono_limpio.startswith('58'):
                telefono_limpio = '58' + telefono_limpio.lstrip('0')
                print(f"🔗 Teléfono con prefijo 58: {telefono_limpio}")
            # Usar urllib.parse.quote para codificar el mensaje correctamente
            mensaje_codificado = urllib.parse.quote(mensaje)
            enlace_whatsapp = f"https://wa.me/{telefono_limpio}?text={mensaje_codificado}"
            enlace_web = f"https://web.whatsapp.com/send?phone={telefono_limpio}&text={mensaje_codificado}"
            print(f"🔗 Enlace WhatsApp generado exitosamente: {enlace_whatsapp}")
            print(f"🔗 Enlace Web generado exitosamente: {enlace_web}")
        except Exception as e:
            print(f"❌ Error generando enlace: {e}")
            return jsonify({'error': f'Error generando enlace: {str(e)}'}), 400
        
        # Registrar en la bitácora (opcional, no fallar si hay error)
        try:
            # Registro simple en consola
            print(f"📝 REGISTRO: Usuario {session.get('usuario', 'Sistema')} envió recordatorio WhatsApp a {cliente.get('nombre', 'N/A')} - {len(facturas_pendientes)} facturas pendientes - Total: ${total_pendiente:.2f}")
        except Exception as e:
            print(f"WARNING Error registrando en bitácora (no crítico): {e}")
        
        resultado = {
            'success': True,
            'message': 'Recordatorio de cuentas por cobrar preparado para WhatsApp',
            'enlace_whatsapp': enlace_whatsapp,
            'enlace_web': enlace_web,
            'telefono': telefono,
            'mensaje': mensaje,
            'cliente_nombre': cliente.get('nombre', 'N/A'),
            'total_notas_entrega': len(facturas_pendientes),
            'total_facturado': sum(f['total'] for f in facturas_pendientes),
            'total_abonado': sum(f['abonado'] for f in facturas_pendientes),
            'total_pendiente': total_pendiente,
        }
        
        print(f"✅ Recordatorio preparado exitosamente para {cliente.get('nombre', 'N/A')}")
        print(f"📱 Teléfono: {telefono}")
        print(f"🔗 Enlace: {enlace_whatsapp}")
        
        return jsonify(resultado)
        
    except Exception as e:
        error_msg = f"Error al enviar recordatorio de cuentas por cobrar: {str(e)}"
        print(f"❌ {error_msg}")
        import traceback
        print(f"🔍 Traceback completo:")
        traceback.print_exc()
        
        return jsonify({
            'success': False,
            'error': f'Error al preparar el recordatorio: {str(e)}',
            'debug_info': {
                'cliente_id': cliente_id,
                'error_type': type(e).__name__,
                'error_details': str(e)
            }
        }), 500

# Ruta de prueba para verificar que funciona
@app.route('/test-recordatorio', methods=['GET'])
def test_recordatorio():
    return jsonify({'message': 'Ruta de prueba funcionando', 'status': 'success'})

# Ruta de prueba para enlaces de WhatsApp mejorados
@app.route('/test-whatsapp-enlaces/<telefono>', methods=['GET'])
def test_whatsapp_enlaces(telefono):
    """Prueba la generación de enlaces de WhatsApp con diferentes formatos."""
    try:
        mensaje_prueba = "Hola, este es un mensaje de prueba desde la empresa 🚀"
        enlaces = generar_enlaces_whatsapp_completos(telefono, mensaje_prueba)
        
        return jsonify({
            'success': True,
            'telefono': telefono,
            'mensaje': mensaje_prueba,
            'enlaces': enlaces,
            'recomendaciones': {
                'app_movil': 'Para dispositivos móviles - más confiable',
                'web_whatsapp': 'Para WhatsApp Web - puede fallar en algunos navegadores',
                'web_whatsapp_alt': 'Alternativa para WhatsApp Web con parámetros adicionales',
                'fallback': 'Solo abre el chat sin mensaje - último recurso'
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# Ruta de prueba para verificar que funciona
@app.route('/test-simple', methods=['GET'])
def test_simple():
    return jsonify({'message': 'Ruta simple funcionando', 'status': 'success'})

# Ruta de prueba para verificar que funciona
@app.route('/test-post', methods=['POST'])
def test_post():
    return jsonify({'message': 'Ruta POST funcionando', 'status': 'success'})


# ===== MÓDULO DE EQUIPOS DE CLIENTES =====

@app.route('/clientes/<path:cliente_id>/equipos', methods=['GET', 'POST'])
@login_required
def gestionar_equipos_cliente(cliente_id):
    """Gestionar equipos de un cliente"""
    try:
        clientes = cargar_datos(ARCHIVO_CLIENTES)
        
        if cliente_id not in clientes:
            flash('Cliente no encontrado', 'error')
            return redirect(url_for('mostrar_clientes'))
        
        cliente = clientes[cliente_id]
        
        # Inicializar lista de equipos si no existe
        if 'equipos' not in cliente:
            cliente['equipos'] = []
        
        if request.method == 'POST':
            accion = request.form.get('accion')
            
            if accion == 'agregar':
                nuevo_equipo = {
                    'id': f"EQU-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                    'marca': request.form.get('marca', ''),
                    'modelo': request.form.get('modelo', ''),
                    'imei': request.form.get('imei', ''),
                    'imei2': request.form.get('imei2', ''),
                    'numero_serie': request.form.get('numero_serie', ''),
                    'color': request.form.get('color', ''),
                    'capacidad_almacenamiento': request.form.get('capacidad_almacenamiento', ''),
                    'version_sistema': request.form.get('version_sistema', ''),
                    'numero_telefono': request.form.get('numero_telefono', ''),
                    'fecha_entrega': request.form.get('fecha_entrega', ''),
                    'estado': request.form.get('estado', 'Funcional'),
                    'condicion_fisica': request.form.get('condicion_fisica', 'Bueno'),
                    'observaciones': request.form.get('observaciones', ''),
                    'orden_asociada': request.form.get('orden_asociada', ''),
                    'fecha_creacion': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                cliente['equipos'].append(nuevo_equipo)
                clientes[cliente_id] = cliente
                
                # Guardar datos
                if guardar_datos(ARCHIVO_CLIENTES, clientes):
                    flash('Equipo agregado exitosamente', 'success')
                else:
                    flash('Error al guardar el equipo', 'danger')
                
                return redirect(url_for('gestionar_equipos_cliente', cliente_id=cliente_id))
            
            elif accion == 'editar':
                equipo_id = request.form.get('equipo_id')
                equipo_encontrado = False
                for equipo in cliente['equipos']:
                    if equipo.get('id') == equipo_id:
                        equipo['marca'] = request.form.get('marca', '')
                        equipo['modelo'] = request.form.get('modelo', '')
                        equipo['imei'] = request.form.get('imei', '')
                        equipo['imei2'] = request.form.get('imei2', '')
                        equipo['numero_serie'] = request.form.get('numero_serie', '')
                        equipo['color'] = request.form.get('color', '')
                        equipo['capacidad_almacenamiento'] = request.form.get('capacidad_almacenamiento', '')
                        equipo['version_sistema'] = request.form.get('version_sistema', '')
                        equipo['numero_telefono'] = request.form.get('numero_telefono', '')
                        equipo['fecha_entrega'] = request.form.get('fecha_entrega', '')
                        equipo['estado'] = request.form.get('estado', '')
                        equipo['condicion_fisica'] = request.form.get('condicion_fisica', 'Bueno')
                        equipo['observaciones'] = request.form.get('observaciones', '')
                        equipo['orden_asociada'] = request.form.get('orden_asociada', '')
                        equipo['fecha_actualizacion'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        equipo_encontrado = True
                        break
                
                if equipo_encontrado:
                    clientes[cliente_id] = cliente
                    if guardar_datos(ARCHIVO_CLIENTES, clientes):
                        flash('Equipo actualizado exitosamente', 'success')
                    else:
                        flash('Error al guardar los cambios', 'danger')
                else:
                    flash('Equipo no encontrado', 'danger')
                
                return redirect(url_for('gestionar_equipos_cliente', cliente_id=cliente_id))
            
            elif accion == 'eliminar':
                equipo_id = request.form.get('equipo_id')
                equipos_originales = len(cliente['equipos'])
                cliente['equipos'] = [e for e in cliente['equipos'] if e.get('id') != equipo_id]
                
                if len(cliente['equipos']) < equipos_originales:
                    clientes[cliente_id] = cliente
                    if guardar_datos(ARCHIVO_CLIENTES, clientes):
                        flash('Equipo eliminado exitosamente', 'success')
                    else:
                        flash('Error al eliminar el equipo', 'danger')
                else:
                    flash('Equipo no encontrado', 'danger')
                
                return redirect(url_for('gestionar_equipos_cliente', cliente_id=cliente_id))
        
        # Cargar configuración de equipos
        config = cargar_configuracion()
        config_equipos = config.get('equipos_clientes', {})
        modelos_disponibles = config_equipos.get('modelos_disponibles', [])
        estados_disponibles = config_equipos.get('estados_equipos', ['Funcional', 'En Reparación', 'Reparado', 'Entregado', 'Sin Arreglo'])
        colores_disponibles = config_equipos.get('colores_disponibles', ['Negro', 'Blanco', 'Azul', 'Rojo', 'Dorado', 'Plateado'])
        condicion_fisica_opciones = config_equipos.get('condicion_fisica_opciones', ['Excelente', 'Bueno', 'Regular', 'Malo', 'Muy Malo'])
        
        # Buscar órdenes de servicio del cliente
        ordenes = cargar_datos('ordenes_servicio.json')
        ordenes_cliente = [o for o in ordenes.values() if o.get('cliente', {}).get('id') == cliente_id]
        
        # Asegurar que equipos es una lista válida
        equipos_lista = cliente.get('equipos', [])
        if not isinstance(equipos_lista, list):
            equipos_lista = []
            cliente['equipos'] = []
            clientes[cliente_id] = cliente
            guardar_datos(ARCHIVO_CLIENTES, clientes)
        
        # Debug: imprimir información de equipos
        print(f"DEBUG - Cliente ID: {cliente_id}")
        print(f"DEBUG - Número de equipos: {len(equipos_lista)}")
        print(f"DEBUG - Equipos: {equipos_lista}")
        
        return render_template('equipos_cliente.html', 
                             cliente=cliente,
                             equipos=equipos_lista,
                             modelos_disponibles=modelos_disponibles,
                             estados_disponibles=estados_disponibles,
                             ordenes_cliente=ordenes_cliente,
                             config_equipos=config_equipos,
                             colores_disponibles=colores_disponibles,
                             condicion_fisica_opciones=condicion_fisica_opciones)
    
    except Exception as e:
        print(f"Error gestionando equipos: {e}")
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('mostrar_clientes'))

# ===== SISTEMA DE ROLES Y PERMISOS =====

ARCHIVO_ROLES = 'roles_usuarios.json'

def cargar_roles():
    """Carga los roles de usuarios"""
    try:
        if not os.path.exists(ARCHIVO_ROLES):
            roles_default = {
                'roles_disponibles': ['Administrador', 'Administrador Principal', 'Técnico', 'Vendedor', 'Cajero', 'Solo Lectura'],
                'permisos_por_rol': {
                    'Administrador Principal': {
                        'configuracion_sistema': True,
                        'eliminar_ordenes': True,
                        'ver_reportes': True,
                        'modificar_precios': True,
                        'gestionar_usuarios': True,
                        'gestionar_clientes': True,
                        'gestionar_inventario': True,
                        'gestionar_pagos': True,
                        'ver_bitacora': True,
                        'backup': True
                    },
                    'Administrador': {
                        'configuracion_sistema': False,  # Solo Admin Principal
                        'eliminar_ordenes': True,
                        'ver_reportes': True,
                        'modificar_precios': True,
                        'gestionar_usuarios': True,
                        'gestionar_clientes': True,
                        'gestionar_inventario': True,
                        'gestionar_pagos': True,
                        'ver_bitacora': True,
                        'backup': False
                    },
                    'Técnico': {
                        'configuracion_sistema': False,
                        'eliminar_ordenes': False,
                        'ver_reportes': False,
                        'modificar_precios': False,
                        'gestionar_usuarios': False,
                        'gestionar_clientes': True,
                        'gestionar_inventario': True,
                        'gestionar_pagos': False,
                        'ver_bitacora': False,
                        'backup': False
                    },
                    'Vendedor': {
                        'configuracion_sistema': False,
                        'eliminar_ordenes': False,
                        'ver_reportes': False,
                        'modificar_precios': True,
                        'gestionar_usuarios': False,
                        'gestionar_clientes': True,
                        'gestionar_inventario': False,
                        'gestionar_pagos': True,
                        'ver_bitacora': False,
                        'backup': False
                    },
                    'Cajero': {
                        'configuracion_sistema': False,
                        'eliminar_ordenes': False,
                        'ver_reportes': False,
                        'modificar_precios': False,
                        'gestionar_usuarios': False,
                        'gestionar_clientes': False,
                        'gestionar_inventario': False,
                        'gestionar_pagos': True,
                        'ver_bitacora': False,
                        'backup': False
                    },
                    'Solo Lectura': {
                        'configuracion_sistema': False,
                        'eliminar_ordenes': False,
                        'ver_reportes': False,
                        'modificar_precios': False,
                        'gestionar_usuarios': False,
                        'gestionar_clientes': False,
                        'gestionar_inventario': False,
                        'gestionar_pagos': False,
                        'ver_bitacora': False,
                        'backup': False
                    }
                }
            }
            guardar_roles(roles_default)
            return roles_default
        
        with open(ARCHIVO_ROLES, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error cargando roles: {e}")
        return {}

def guardar_roles(roles):
    """Guarda los roles de usuarios"""
    try:
        with open(ARCHIVO_ROLES, 'w', encoding='utf-8') as f:
            json.dump(roles, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error guardando roles: {e}")
        return False

def asignar_rol_usuario(username, rol):
    """Asigna un rol a un usuario"""
    try:
        roles = cargar_roles()
        if 'usuarios' not in roles:
            roles['usuarios'] = {}
        roles['usuarios'][username] = rol
        guardar_roles(roles)
        return True
    except Exception as e:
        print(f"Error asignando rol: {e}")
        return False

def obtener_rol_usuario(username):
    """Obtiene el rol de un usuario"""
    try:
        # Primero verificar en usuarios.json (formato nuevo)
        usuarios = cargar_datos('usuarios.json')
        if 'usuarios' in usuarios and username in usuarios['usuarios']:
            return usuarios['usuarios'][username].get('rol', 'Técnico')
        
        # Verificar formato antiguo de usuarios.json (directo)
        if username in usuarios and 'role' in usuarios[username]:
            # Convertir rol antiguo al nuevo formato
            roles_antiguos = {'admin': 'Administrador Principal', 'tecnico': 'Técnico'}
            rol_antiguo = usuarios[username].get('role', 'tecnico')
            return roles_antiguos.get(rol_antiguo, 'Técnico')
        
        # Luego verificar en roles_usuarios.json
        roles = cargar_roles()
        if 'usuarios' in roles and username in roles['usuarios']:
            return roles['usuarios'][username]
        
        return 'Técnico'  # Rol por defecto
    except Exception as e:
        print(f"Error obteniendo rol de usuario: {e}")
        return 'Técnico'

def tiene_permiso(username, permiso):
    """Verifica si un usuario tiene un permiso"""
    try:
        rol = obtener_rol_usuario(username)
        roles = cargar_roles()
        permisos = roles.get('permisos_por_rol', {}).get(rol, {})
        return permisos.get(permiso, False)
    except:
        return False

def es_administrador_principal(username):
    """Verifica si el usuario es Administrador Principal"""
    return obtener_rol_usuario(username) == 'Administrador Principal'

# ===== MÓDULO DE CONFIGURACIÓN DEL SISTEMA =====

ARCHIVO_CONFIG_SISTEMA = 'config_sistema.json'

def cargar_configuracion():
    """Carga la configuración del sistema"""
    try:
        if not os.path.exists(ARCHIVO_CONFIG_SISTEMA):
            # Crear configuración por defecto
            config_default = {
                'empresa': {
                    'nombre': '',
                    'rif': '',
                    'direccion': '',
                    'ciudad': '',
                    'estado': '',
                    'pais': 'Venezuela',
                    'telefono': '',
                    'whatsapp': '',
                    'email': '',
                    'website': '',
                    'instagram': '',
                    'descripcion': '',
                    'horario': '',
                    'logo_path': 'static/logo.png'
                },
                'tasas': {
                    'actualizacion_automatica': True,
                    'intervalo_actualizacion': 3600,
                    'tasa_usd_defecto': 216.37,
                    'fuente_tasa': 'bcv',
                    'notificar_cambios': True
                },
                'notificaciones': {
                    'whatsapp_habilitado': False,
                    'whatsapp_api_key': '',
                    'email_habilitado': False,
                    'email_smtp_server': '',
                    'email_smtp_port': 587,
                    'email_usuario': '',
                    'email_password': '',
                    'email_remitente': ''
                },
                'alertas': {
                    'vencimiento_notas_entrega': False,
                    'stock_minimo': False,
                    'cuotas_vencidas': False,
                    'pagos_pendientes': False,
                    'productos_agotados': False,
                    'productos_caducando': False,
                    'ordenes_pendientes': False,
                    'ordenes_urgentes': False,
                    'cumpleanos_clientes': False,
                    'clientes_nuevos': False,
                    'estadisticas_semanales': False,
                    'estadisticas_mensuales': False,
                    'canal_notificacion': 'email',
                    'horario_alertas': '08:00'
                },
                'documentos': {
                    'formato_numero_orden': 'OS-{YYYYMMDD}{####}',
                    'formato_numero_factura': 'FAC-{YYYYMMDD}{####}',
                    'formato_numero_nota': 'NE-{####}',
                    'prefijo_factura': 'FAC-',
                    'prefijo_nota': 'NE-',
                    'prefijo_orden': 'OS-',
                    'mostrar_logo': True,
                    'mostrar_codigo_barras': False
                },
                'estados_ordenes': {
                    'recibido': {
                        'tiempo_maximo': 24,
                        'campos_obligatorios': ['equipo', 'cliente'],
                        'notificar_cliente': True
                    },
                    'diagnostico': {
                        'tiempo_maximo': 72,
                        'campos_obligatorios': ['diagnostico'],
                        'notificar_cliente': True
                    },
                    'en_reparacion': {
                        'tiempo_maximo': 168,
                        'requiere_admin': False,
                        'comentario_obligatorio': False
                    },
                    'reparado': {
                        'tiempo_maximo': 48,
                        'requiere_aprobacion': True,
                        'notificar_cliente': True
                    },
                    'entregado': {
                        'requiere_admin': True,
                        'requiere_firma': True,
                        'notificar_cliente': True
                    }
                },
                'metodos_pago': {
                    'efectivo': {'habilitado': True},
                    'transferencia': {'habilitado': True},
                    'pago_movil': {'habilitado': True},
                    'zelle': {'habilitado': True},
                    'paypal': {'habilitado': False},
                    'binance': {'habilitado': False},
                    'banco_nombre': '',
                    'tipo_cuenta': 'corriente',
                    'numero_cuenta': '',
                    'titular_cuenta': '',
                    'telefono_pago_movil': '',
                    'cedula_pago_movil': '',
                    'email_zelle': '',
                    'email_binance': '',
                    'aceptar_efectivo_usd': True,
                    'aceptar_efectivo_bs': True,
                    'notificar_pago_cliente': True,
                    'notificar_nota_entregada': True
                },
                'categorias': {
                    'productos': [],
                    'tipos_clientes': [
                        {'nombre': 'VIP', 'color': '#6f42c1', 'icono': 'fas fa-crown'},
                        {'nombre': 'Regular', 'color': '#007bff', 'icono': 'fas fa-user'},
                        {'nombre': 'Corporativo', 'color': '#28a745', 'icono': 'fas fa-building'}
                    ],
                    'zonas_cobertura': [],
                    'prioridades': [
                        {'nombre': 'Baja', 'color': '#17a2b8', 'icono': 'fas fa-flag'},
                        {'nombre': 'Media', 'color': '#ffc107', 'icono': 'fas fa-clock'},
                        {'nombre': 'Alta', 'color': '#fd7e14', 'icono': 'fas fa-fire'},
                        {'nombre': 'Urgente', 'color': '#dc3545', 'icono': 'fas fa-bolt'}
                    ]
                },
                'seguridad': {
                    'tiempo_sesion': 60,
                    'sesiones_concurrentes_max': 2,
                    'intentos_login': 5,
                    'tiempo_bloqueo_ip': 15,
                    'cerrar_sesiones_concurrentes': True,
                    'longitud_min_contraseña': 8,
                    'dias_expira_contraseña': 90,
                    'complejidad_contraseña': True,
                    'no_reusar_contraseñas': True,
                    'expira_contraseña': False,
                    'autenticacion_2fa': False,
                    '2fa_sms': True,
                    '2fa_email': True,
                    'registro_actividades': True,
                    'retencion_logs': 90,
                    'cifrar_datos_sensibles': True,
                    'backups_cifrados': True,
                    'exportaciones_cifradas': True,
                    'backups_automaticos_seguridad': True,
                    'dias_retencion_backups': 30,
                    'bloqueo_ip_activo': False,
                    'ips_permitidas': '',
                    'alertar_login_nuevo': True,
                    'alertar_cambios_permisos': True,
                    'alertas_email': True,
                    'alertas_sms': False,
                    'alertas_whatsapp': False
                },
                'visual': {
                    'tema': 'automatico',
                    'color_primario': '#4f46e5',
                    'color_secundario': '#7c3aed',
                    'color_acentos': '#10b981',
                    'color_fondo': '#f9fafb',
                    'preview_tiempo_real': True,
                    'familia_fuente': 'poppins',
                    'tamano_fuente_base': 16,
                    'escala_movil': 1.0,
                    'escala_tablet': 1.1,
                    'escala_desktop': 1.2,
                    'densidad': 'normal',
                    'altura_filas': 48,
                    'padding_general': 16,
                    'gap_cards': 16,
                    'estilo_bordes': 'redondeado',
                    'estilo_botones': 'filled',
                    'estilo_tarjetas': 'sombra',
                    'ancho_sidebar': 'normal',
                    'posicion_sidebar': 'izquierda',
                    'sidebar_colapsable': True,
                    'sidebar_movil': True,
                    'breakpoint_desktop': 1024,
                    'animaciones_habilitadas': True,
                    'velocidad_animacion': 'normal',
                    'tipo_carga': 'spinner',
                    'alto_contraste': False,
                    'reducir_movimiento': False,
                    'idioma': 'es',
                    'posicion_logo': 'esquina',
                    'tamano_logo': 100,
                    'gradiente_fondo': False,
                    'gradiente_color_inicio': '#667eea',
                    'gradiente_color_fin': '#764ba2',
                    'gradiente_direccion': 'vertical',
                    'efecto_glassmorphism': False,
                    'nombre_tema': 'Mi Tema Personalizado'
                },
                'inventario': {
                    'control_stock': True,
                    'stock_minimo_default': 5,
                    'stock_maximo_default': 100,
                    'punto_reorden_default': 10,
                    'alertas_stock_critico': True,
                    'codigos_barras': False,
                    'formato_codigo_barras': 'Code128',
                    'generacion_automatica_codigos': True,
                    'impresion_masiva_etiquetas': False,
                    'seriales': True,
                    'control_lotes': False,
                    'trazabilidad_completa': True,
                    'ubicaciones_multiples': False,
                    'almacenes_default': '',
                    'transferencias_entre_ubicaciones': True,
                    'catalogo_proveedores': False,
                    'tiempo_entrega_promedio': 7,
                    'evaluacion_proveedores': False,
                    'control_caducidad': False,
                    'dias_alerta_caducidad': 30,
                    'metodo_rotacion': 'FIFO',
                    'causas_movimiento': True,
                    'aprobaciones_movimiento': False,
                    'historial_detallado': True,
                    'metodo_costeo': 'promedio_ponderado',
                    'precios_por_cliente': False,
                    'alertas_stock_minimo': True,
                    'alertas_caducidad': True,
                    'alertas_movimientos_inusuales': False,
                    'reportes_automaticos': False,
                    'ordenes_compra_automaticas': False,
                    'sugerencias_reposicion': True,
                    'comparacion_precios': False,
                    'rotacion_inventario': True,
                    'analisis_abc': True,
                    'tendencias_inventario': False,
                    'exportacion_reportes': True,
                    'categorias_personalizables': True,
                    'subcategorias': False,
                    'plantillas_productos': False,
                    'inspecciones_recepcion': False,
                    'certificados_calidad': False,
                    'productos_defectuosos': True,
                    'conteos_ciclicos': False,
                    'auditorias_programadas': False,
                    'ajustes_automaticos': False,
                    'unidades_multiples': False,
                    'conversiones_automaticas': True,
                    'empaques_presentaciones': False,
                    'etiquetas_personalizables': False,
                    'codigos_qr_informacion': False,
                    'etiquetas_ubicacion': False,
                    'backups_automaticos_inventario': True,
                    'sincronizacion_nube': False,
                    'historial_cambios': True,
                    'acceso_por_modulo': True,
                    'aprobaciones_requeridas': False,
                    'roles_inventario': True,
                    'auditoria_cambios': True,
                    'reserva_stock': True,
                    'backorders': False,
                    'disponibilidad_tiempo_real': True,
                    'sincronizacion_automatica': True
                },
                'proveedores': {
                    'habilitado': False,
                    'terminos_pago': 30,
                    'plazos_entrega': 7,
                    'costo_envio': 0
                },
                'calendario': {
                    'horarios_atencion': {'inicio': '08:00', 'fin': '17:00'},
                    'dias_laborables': ['lunes', 'martes', 'miercoles', 'jueves', 'viernes'],
                    'festivos': [],
                    'agenda_habilitada': False
                },
                'contadores': {
                    'reset_anual': True,
                    'prefijo_ano': True,
                    'validacion_secuencial': True
                },
                'reportes': {
                    'habilitados': True,
                    'exportacion_excel': True,
                    'exportacion_pdf': True,
                    'envio_automatico': False
                },
                'integraciones': {
                    'api_externas': False,
                    'bases_datos': False,
                    'sincronizacion_nube': False,
                    'webhooks': False
                },
                'usuarios': {
                    'permiso_eliminar_ordenes': 'admin',
                    'permiso_ver_reportes': 'admin',
                    'permiso_modificar_precios': 'admin'
                },
                'backup': {
                    'automatico': False,
                    'intervalo_horas': 24,
                    'mantener_backups_dias': 30,
                    'compresion': True
                },
                'equipos_clientes': {
                    'habilitado': True,
                    'modelos_disponibles': ['iPhone', 'Samsung', 'Xiaomi', 'Huawei', 'LG', 'Motorola', 'Sony'],
                    'estados_equipos': ['Funcional', 'Reparado', 'Entregado', 'En Reparación']
                }
            }
            guardar_configuracion(config_default)
            return config_default
        
        with open(ARCHIVO_CONFIG_SISTEMA, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error cargando configuración: {e}")
        return cargar_configuracion()  # Recursivo para crear default

def guardar_configuracion(config):
    """Guarda la configuración del sistema"""
    try:
        with open(ARCHIVO_CONFIG_SISTEMA, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error guardando configuración: {e}")
        return False

@app.route('/configuracion', methods=['GET', 'POST'])
@login_required
def configuracion_sistema():
    """Página de configuración del sistema"""
    if request.method == 'POST':
        print("\n" + "="*60)
        print("🔧 RECIBIENDO FORMULARIO DE CONFIGURACIÓN")
        print("="*60)
        print(f"📝 Datos recibidos: {len(request.form)} campos")
        print(f"📎 Archivos recibidos: {len(request.files)} archivo(s)")
        
        try:
            # Obtener configuración actual
            config = cargar_configuracion()
            print("✅ Configuración cargada correctamente")
            
            # Actualizar sección empresa
            if 'empresa_nombre' in request.form:
                config['empresa']['nombre'] = request.form.get('empresa_nombre', '')
                config['empresa']['rif'] = request.form.get('empresa_rif', '')
                config['empresa']['direccion'] = request.form.get('empresa_direccion', '')
                config['empresa']['ciudad'] = request.form.get('empresa_ciudad', '')
                config['empresa']['estado'] = request.form.get('empresa_estado', '')
                config['empresa']['pais'] = request.form.get('empresa_pais', 'Venezuela')
                config['empresa']['telefono'] = request.form.get('empresa_telefono', '')
                config['empresa']['whatsapp'] = request.form.get('empresa_whatsapp', '')
                config['empresa']['email'] = request.form.get('empresa_email', '')
                config['empresa']['website'] = request.form.get('empresa_website', '')
                config['empresa']['instagram'] = request.form.get('empresa_instagram', '')
                config['empresa']['descripcion'] = request.form.get('empresa_descripcion', '')
                config['empresa']['horario'] = request.form.get('empresa_horario', '')
                
                # Manejar subida de logo
                if 'empresa_logo' in request.files:
                    logo_file = request.files['empresa_logo']
                    if logo_file and logo_file.filename != '':
                        # Validar extensión
                        allowed_extensions = {'png', 'jpg', 'jpeg', 'svg', 'gif', 'webp'}
                        if '.' in logo_file.filename and logo_file.filename.rsplit('.', 1)[1].lower() in allowed_extensions:
                            # Crear carpeta para logos si no existe
                            upload_folder = 'static/uploads/logos'
                            os.makedirs(upload_folder, exist_ok=True)
                            
                            # Generar nombre único
                            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                            filename = f'logo_{timestamp}.{logo_file.filename.rsplit(".", 1)[1].lower()}'
                            filepath = os.path.join(upload_folder, filename)
                            
                            # Guardar archivo
                            logo_file.save(filepath)
                            
                            # Actualizar configuración con la ruta del logo
                            config['empresa']['logo_path'] = filepath.replace('\\', '/')
                            flash('Logo subido exitosamente', 'success')
                        else:
                            flash('Formato de archivo no válido. Use: PNG, JPG, SVG, GIF o WEBP', 'warning')
            
            # Actualizar sección tasas
            if 'tasa_usd_defecto' in request.form:
                config['tasas']['tasa_usd_defecto'] = float(request.form.get('tasa_usd_defecto', 216.37))
                config['tasas']['actualizacion_automatica'] = request.form.get('actualizacion_automatica') == 'on'
                config['tasas']['intervalo_actualizacion'] = int(request.form.get('intervalo_actualizacion', 3600))
                config['tasas']['fuente_tasa'] = request.form.get('fuente_tasa', 'bcv')
                config['tasas']['notificar_cambios'] = request.form.get('notificar_cambios') == 'on'
            
            # Actualizar sección notificaciones
            if 'whatsapp_habilitado' in request.form:
                config['notificaciones']['whatsapp_habilitado'] = request.form.get('whatsapp_habilitado') == 'on'
                config['notificaciones']['whatsapp_api_key'] = request.form.get('whatsapp_api_key', '')
                config['notificaciones']['email_habilitado'] = request.form.get('email_habilitado') == 'on'
                config['notificaciones']['email_smtp_server'] = request.form.get('email_smtp_server', '')
                config['notificaciones']['email_smtp_port'] = int(request.form.get('email_smtp_port', 587))
                config['notificaciones']['email_usuario'] = request.form.get('email_usuario', '')
                config['notificaciones']['email_password'] = request.form.get('email_password', '')
                config['notificaciones']['email_remitente'] = request.form.get('email_remitente', '')
            
            # Actualizar sección documentos
            if 'formato_numero_orden' in request.form:
                config['documentos']['formato_numero_orden'] = request.form.get('formato_numero_orden', '')
                config['documentos']['formato_numero_factura'] = request.form.get('formato_numero_factura', '')
                config['documentos']['formato_numero_nota'] = request.form.get('formato_numero_nota', '')
                config['documentos']['mostrar_logo'] = request.form.get('mostrar_logo') == 'on'
                config['documentos']['mostrar_codigo_barras'] = request.form.get('mostrar_codigo_barras') == 'on'
            
            # Actualizar sección alertas
            if 'vencimiento_notas_entrega' in request.form or 'stock_minimo' in request.form:
                config['alertas']['vencimiento_notas_entrega'] = request.form.get('vencimiento_notas_entrega') == 'on'
                config['alertas']['stock_minimo'] = request.form.get('stock_minimo') == 'on'
                config['alertas']['cuotas_vencidas'] = request.form.get('cuotas_vencidas') == 'on'
                config['alertas']['pagos_pendientes'] = request.form.get('pagos_pendientes') == 'on'
                config['alertas']['productos_agotados'] = request.form.get('productos_agotados') == 'on'
                config['alertas']['productos_caducando'] = request.form.get('productos_caducando') == 'on'
                config['alertas']['ordenes_pendientes'] = request.form.get('ordenes_pendientes') == 'on'
                config['alertas']['ordenes_urgentes'] = request.form.get('ordenes_urgentes') == 'on'
                config['alertas']['cumpleanos_clientes'] = request.form.get('cumpleanos_clientes') == 'on'
                config['alertas']['clientes_nuevos'] = request.form.get('clientes_nuevos') == 'on'
                config['alertas']['estadisticas_semanales'] = request.form.get('estadisticas_semanales') == 'on'
                config['alertas']['estadisticas_mensuales'] = request.form.get('estadisticas_mensuales') == 'on'
                config['alertas']['canal_notificacion'] = request.form.get('canal_notificacion', 'email')
                config['alertas']['horario_alertas'] = request.form.get('horario_alertas', '08:00')
                
                # Agregar alertas para estados
                config['alertas']['estados_vencidos'] = request.form.get('alertas_estados_vencidos') == 'on'
                config['alertas']['estados_pendientes'] = request.form.get('alertas_estados_pendientes') == 'on'
            
            # Actualizar sección estados de órdenes
            if 'estado_recibido_tiempo_max' in request.form:
                if 'estados_ordenes' not in config:
                    config['estados_ordenes'] = {}
                
                # Configurar estado Recibido
                config['estados_ordenes']['recibido'] = {
                    'tiempo_maximo': int(request.form.get('estado_recibido_tiempo_max', 24)),
                    'campos_obligatorios': request.form.get('estado_recibido_campos', 'equipo,cliente').split(','),
                    'notificar_cliente': request.form.get('estado_recibido_notificar') == 'on'
                }
                
                # Configurar estado Diagnóstico
                config['estados_ordenes']['diagnostico'] = {
                    'tiempo_maximo': int(request.form.get('estado_diagnostico_tiempo_max', 72)),
                    'campos_obligatorios': request.form.get('estado_diagnostico_campos', 'diagnostico').split(','),
                    'notificar_cliente': request.form.get('estado_diagnostico_notificar') == 'on'
                }
                
                # Configurar estado En Reparación
                config['estados_ordenes']['en_reparacion'] = {
                    'tiempo_maximo': int(request.form.get('estado_reparacion_tiempo_max', 168)),
                    'requiere_admin': request.form.get('estado_reparacion_requiere_admin') == 'true',
                    'comentario_obligatorio': request.form.get('estado_reparacion_comentario_obligatorio') == 'on'
                }
                
                # Configurar estado Reparado
                config['estados_ordenes']['reparado'] = {
                    'tiempo_maximo': int(request.form.get('estado_reparado_tiempo_max', 48)),
                    'requiere_aprobacion': request.form.get('estado_reparado_requiere_aprobacion') == 'true',
                    'notificar_cliente': request.form.get('estado_reparado_notificar') == 'on'
                }
                
                # Configurar estado Entregado
                config['estados_ordenes']['entregado'] = {
                    'requiere_admin': request.form.get('estado_entregado_requiere_admin') == 'true',
                    'requiere_firma': request.form.get('estado_entregado_requiere_firma') == 'on',
                    'notificar_cliente': request.form.get('estado_entregado_notificar') == 'on'
                }
                
                print("✅ Configuración de estados de órdenes actualizada")
            
            # Actualizar sección métodos de pago
            if 'pago_efectivo' in request.form or 'banco_nombre' in request.form:
                if 'metodos_pago' not in config:
                    config['metodos_pago'] = {}
                
                config['metodos_pago']['efectivo'] = {'habilitado': request.form.get('pago_efectivo') == 'on'}
                config['metodos_pago']['transferencia'] = {'habilitado': request.form.get('pago_transferencia') == 'on'}
                config['metodos_pago']['pago_movil'] = {'habilitado': request.form.get('pago_pago_movil') == 'on'}
                config['metodos_pago']['zelle'] = {'habilitado': request.form.get('pago_zelle') == 'on'}
                config['metodos_pago']['paypal'] = {'habilitado': request.form.get('pago_paypal') == 'on'}
                config['metodos_pago']['binance'] = {'habilitado': request.form.get('pago_binance') == 'on'}
                
                config['metodos_pago']['banco_nombre'] = request.form.get('banco_nombre', '')
                config['metodos_pago']['tipo_cuenta'] = request.form.get('tipo_cuenta', 'corriente')
                config['metodos_pago']['numero_cuenta'] = request.form.get('numero_cuenta', '')
                config['metodos_pago']['titular_cuenta'] = request.form.get('titular_cuenta', '')
                config['metodos_pago']['telefono_pago_movil'] = request.form.get('telefono_pago_movil', '')
                config['metodos_pago']['cedula_pago_movil'] = request.form.get('cedula_pago_movil', '')
                config['metodos_pago']['email_zelle'] = request.form.get('email_zelle', '')
                config['metodos_pago']['email_binance'] = request.form.get('email_binance', '')
                config['metodos_pago']['aceptar_efectivo_usd'] = request.form.get('aceptar_efectivo_usd') == 'on'
                config['metodos_pago']['aceptar_efectivo_bs'] = request.form.get('aceptar_efectivo_bs') == 'on'
                config['metodos_pago']['notificar_pago_cliente'] = request.form.get('notificar_pago_cliente') == 'on'
                config['metodos_pago']['notificar_nota_entregada'] = request.form.get('notificar_nota_entregada') == 'on'
            
            # Actualizar sección inventario
            if 'control_stock' in request.form:
                if 'inventario' not in config:
                    config['inventario'] = {}
                
                # Control de Stock Avanzado (1)
                config['inventario']['control_stock'] = request.form.get('control_stock') == 'on'
                config['inventario']['stock_minimo_default'] = int(request.form.get('stock_minimo_default', 5))
                config['inventario']['stock_maximo_default'] = int(request.form.get('stock_maximo_default', 100))
                config['inventario']['punto_reorden_default'] = int(request.form.get('punto_reorden_default', 10))
                config['inventario']['alertas_stock_critico'] = request.form.get('alertas_stock_critico') == 'on'
                
                # Códigos de Barras y QR (2)
                config['inventario']['codigos_barras'] = request.form.get('codigos_barras') == 'on'
                config['inventario']['formato_codigo_barras'] = request.form.get('formato_codigo_barras', 'Code128')
                config['inventario']['generacion_automatica_codigos'] = request.form.get('generacion_automatica_codigos') == 'on'
                config['inventario']['impresion_masiva_etiquetas'] = request.form.get('impresion_masiva_etiquetas') == 'on'
                
                # Control de Seriales y Lotes (3)
                config['inventario']['seriales'] = request.form.get('seriales') == 'on'
                config['inventario']['control_lotes'] = request.form.get('control_lotes') == 'on'
                config['inventario']['trazabilidad_completa'] = request.form.get('trazabilidad_completa') == 'on'
                
                # Ubicaciones Múltiples (4)
                config['inventario']['ubicaciones_multiples'] = request.form.get('ubicaciones_multiples') == 'on'
                config['inventario']['almacenes_default'] = request.form.get('almacenes_default', '')
                config['inventario']['transferencias_entre_ubicaciones'] = request.form.get('transferencias_entre_ubicaciones') == 'on'
                
                # Gestión de Proveedores (5)
                config['inventario']['catalogo_proveedores'] = request.form.get('catalogo_proveedores') == 'on'
                config['inventario']['tiempo_entrega_promedio'] = int(request.form.get('tiempo_entrega_promedio', 7))
                config['inventario']['evaluacion_proveedores'] = request.form.get('evaluacion_proveedores') == 'on'
                
                # Control de Caducidad (6)
                config['inventario']['control_caducidad'] = request.form.get('control_caducidad') == 'on'
                config['inventario']['dias_alerta_caducidad'] = int(request.form.get('dias_alerta_caducidad', 30))
                config['inventario']['metodo_rotacion'] = request.form.get('metodo_rotacion', 'FIFO')
                
                # Movimientos de Inventario (7)
                config['inventario']['causas_movimiento'] = request.form.get('causas_movimiento') == 'on'
                config['inventario']['aprobaciones_movimiento'] = request.form.get('aprobaciones_movimiento') == 'on'
                config['inventario']['historial_detallado'] = request.form.get('historial_detallado') == 'on'
                
                # Costos y Precios (8)
                config['inventario']['metodo_costeo'] = request.form.get('metodo_costeo', 'promedio_ponderado')
                config['inventario']['precios_por_cliente'] = request.form.get('precios_por_cliente') == 'on'
                
                # Alertas y Notificaciones (9)
                config['inventario']['alertas_stock_minimo'] = request.form.get('alertas_stock_minimo') == 'on'
                config['inventario']['alertas_caducidad'] = request.form.get('alertas_caducidad') == 'on'
                config['inventario']['alertas_movimientos_inusuales'] = request.form.get('alertas_movimientos_inusuales') == 'on'
                config['inventario']['reportes_automaticos'] = request.form.get('reportes_automaticos') == 'on'
                
                # Integración con Compras (10)
                config['inventario']['ordenes_compra_automaticas'] = request.form.get('ordenes_compra_automaticas') == 'on'
                config['inventario']['sugerencias_reposicion'] = request.form.get('sugerencias_reposicion') == 'on'
                config['inventario']['comparacion_precios'] = request.form.get('comparacion_precios') == 'on'
                
                # Reportes Avanzados (11)
                config['inventario']['rotacion_inventario'] = request.form.get('rotacion_inventario') == 'on'
                config['inventario']['analisis_abc'] = request.form.get('analisis_abc') == 'on'
                config['inventario']['tendencias_inventario'] = request.form.get('tendencias_inventario') == 'on'
                config['inventario']['exportacion_reportes'] = request.form.get('exportacion_reportes') == 'on'
                
                # Configuración de Categorías (12)
                config['inventario']['categorias_personalizables'] = request.form.get('categorias_personalizables') == 'on'
                config['inventario']['subcategorias'] = request.form.get('subcategorias') == 'on'
                config['inventario']['plantillas_productos'] = request.form.get('plantillas_productos') == 'on'
                
                # Control de Calidad (13)
                config['inventario']['inspecciones_recepcion'] = request.form.get('inspecciones_recepcion') == 'on'
                config['inventario']['certificados_calidad'] = request.form.get('certificados_calidad') == 'on'
                config['inventario']['productos_defectuosos'] = request.form.get('productos_defectuosos') == 'on'
                
                # Inventario Físico (14)
                config['inventario']['conteos_ciclicos'] = request.form.get('conteos_ciclicos') == 'on'
                config['inventario']['auditorias_programadas'] = request.form.get('auditorias_programadas') == 'on'
                config['inventario']['ajustes_automaticos'] = request.form.get('ajustes_automaticos') == 'on'
                
                # Configuración de Unidades (15)
                config['inventario']['unidades_multiples'] = request.form.get('unidades_multiples') == 'on'
                config['inventario']['conversiones_automaticas'] = request.form.get('conversiones_automaticas') == 'on'
                config['inventario']['empaques_presentaciones'] = request.form.get('empaques_presentaciones') == 'on'
                
                # Etiquetas y Códigos (16)
                config['inventario']['etiquetas_personalizables'] = request.form.get('etiquetas_personalizables') == 'on'
                config['inventario']['codigos_qr_informacion'] = request.form.get('codigos_qr_informacion') == 'on'
                config['inventario']['etiquetas_ubicacion'] = request.form.get('etiquetas_ubicacion') == 'on'
                
                # Backup de Inventario (17)
                config['inventario']['backups_automaticos_inventario'] = request.form.get('backups_automaticos_inventario') == 'on'
                config['inventario']['sincronizacion_nube'] = request.form.get('sincronizacion_nube') == 'on'
                config['inventario']['historial_cambios'] = request.form.get('historial_cambios') == 'on'
                
                # Permisos por Usuario (18)
                config['inventario']['acceso_por_modulo'] = request.form.get('acceso_por_modulo') == 'on'
                config['inventario']['aprobaciones_requeridas'] = request.form.get('aprobaciones_requeridas') == 'on'
                config['inventario']['roles_inventario'] = request.form.get('roles_inventario') == 'on'
                config['inventario']['auditoria_cambios'] = request.form.get('auditoria_cambios') == 'on'
                
                # Integración con Ventas (19)
                config['inventario']['reserva_stock'] = request.form.get('reserva_stock') == 'on'
                config['inventario']['backorders'] = request.form.get('backorders') == 'on'
                config['inventario']['disponibilidad_tiempo_real'] = request.form.get('disponibilidad_tiempo_real') == 'on'
                config['inventario']['sincronizacion_automatica'] = request.form.get('sincronizacion_automatica') == 'on'
                
                print("✅ Configuración avanzada de inventario actualizada correctamente")
            
            # Actualizar sección categorías desde el JSON que viene en el request
            if 'categorias_data' in request.form:
                try:
                    categorias_data = json.loads(request.form.get('categorias_data', '{}'))
                    if 'tipos_clientes' in categorias_data or 'prioridades' in categorias_data:
                        if 'categorias' not in config:
                            config['categorias'] = {}
                        
                        if 'tipos_clientes' in categorias_data:
                            config['categorias']['tipos_clientes'] = categorias_data['tipos_clientes']
                        if 'prioridades' in categorias_data:
                            config['categorias']['prioridades'] = categorias_data['prioridades']
                        
                        print("✅ Categorías actualizadas correctamente")
                except Exception as e:
                    print(f"⚠️ Error procesando categorías: {e}")
            
            # Actualizar sección proveedores
            if 'proveedores_habilitado' in request.form:
                if 'proveedores' not in config:
                    config['proveedores'] = {}
                
                # Configuración General
                config['proveedores']['habilitado'] = request.form.get('proveedores_habilitado') == 'on'
                config['proveedores']['proveedor_requerido'] = request.form.get('proveedores_requerido') == 'on'
                config['proveedores']['codigo_propio_requerido'] = request.form.get('proveedores_codigo_propio') == 'on'
                
                # Términos de Pago
                config['proveedores']['terminos_pago'] = int(request.form.get('proveedores_terminos_pago', 30))
                config['proveedores']['descuento_pronto_pago'] = float(request.form.get('proveedores_descuento_pronto_pago', 0))
                config['proveedores']['recargo_tardio'] = float(request.form.get('proveedores_recargo_tardio', 0))
                config['proveedores']['forma_pago'] = request.form.get('proveedores_forma_pago', 'transferencia')
                
                # Plazos de Entrega
                config['proveedores']['plazos_entrega'] = int(request.form.get('proveedores_plazos_entrega', 7))
                config['proveedores']['entrega_urgente'] = int(request.form.get('proveedores_entrega_urgente', 2))
                config['proveedores']['costo_envio'] = float(request.form.get('proveedores_costo_envio', 0))
                
                # Evaluación de Proveedores
                config['proveedores']['evaluacion_automatica'] = request.form.get('proveedores_evaluacion_automatica') == 'on'
                config['proveedores']['umbral_calificacion'] = float(request.form.get('proveedores_umbral_calificacion', 3))
                config['proveedores']['puntualidad_min'] = int(request.form.get('proveedores_puntualidad_min', 80))
                config['proveedores']['calidad_min'] = int(request.form.get('proveedores_calidad_min', 85))
                
                # Políticas de Compra
                config['proveedores']['cotizaciones_multiples'] = request.form.get('proveedores_cotizaciones_multiples') == 'on'
                config['proveedores']['aprobacion_compras'] = request.form.get('proveedores_aprobacion_compras') == 'on'
                config['proveedores']['monto_min_cotizacion'] = float(request.form.get('proveedores_monto_min_cotizacion', 100))
                config['proveedores']['monto_max_sin_aprobacion'] = float(request.form.get('proveedores_monto_max_sin_aprobacion', 500))
                
                # Garantías y Devoluciones
                config['proveedores']['politica_garantia'] = int(request.form.get('proveedores_politica_garantia', 30))
                config['proveedores']['plazo_devolucion'] = int(request.form.get('proveedores_plazo_devolucion', 7))
                config['proveedores']['reembolso_automatico'] = request.form.get('proveedores_reembolso') == 'on'
                
                # Comunicación
                config['proveedores']['notificaciones_email'] = request.form.get('proveedores_notificaciones_email') == 'on'
                config['proveedores']['notificaciones_whatsapp'] = request.form.get('proveedores_notificaciones_whatsapp') == 'on'
                config['proveedores']['alertas_stock_bajo'] = request.form.get('proveedores_alertas_stock') == 'on'
                
                # Reportes y Analíticas
                config['proveedores']['reportes_compras'] = request.form.get('proveedores_reportes_compras') == 'on'
                config['proveedores']['analisis_rendimiento'] = request.form.get('proveedores_analisis_rendimiento') == 'on'
                config['proveedores']['ranking_proveedores'] = request.form.get('proveedores_ranking_proveedores') == 'on'
                config['proveedores']['comparacion_precios'] = request.form.get('proveedores_comparacion_precios') == 'on'
                
                # Catálogo de Proveedores
                config['proveedores']['catalogo_publico'] = request.form.get('proveedores_catalogo_publico') == 'on'
                config['proveedores']['sincronizacion_precios'] = request.form.get('proveedores_sincronizacion_precios') == 'on'
                config['proveedores']['actualizacion_stock_automatica'] = request.form.get('proveedores_actualizacion_stock') == 'on'
                
                print("✅ Configuración de proveedores actualizada correctamente")
            
            # Actualizar sección calendario
            if 'calendario_inicio' in request.form:
                if 'calendario' not in config:
                    config['calendario'] = {}
                
                if 'horarios_atencion' not in config['calendario']:
                    config['calendario']['horarios_atencion'] = {}
                
                config['calendario']['horarios_atencion']['inicio'] = request.form.get('calendario_inicio', '08:00')
                config['calendario']['horarios_atencion']['fin'] = request.form.get('calendario_fin', '17:00')
                config['calendario']['horario_extendido'] = request.form.get('calendario_horario_extendido') == 'on'
                
                # Días laborables
                dias_laborables = []
                if request.form.get('calendario_lunes') == 'on':
                    dias_laborables.append('lunes')
                if request.form.get('calendario_martes') == 'on':
                    dias_laborables.append('martes')
                if request.form.get('calendario_miercoles') == 'on':
                    dias_laborables.append('miercoles')
                if request.form.get('calendario_jueves') == 'on':
                    dias_laborables.append('jueves')
                if request.form.get('calendario_viernes') == 'on':
                    dias_laborables.append('viernes')
                if request.form.get('calendario_sabado') == 'on':
                    dias_laborables.append('sabado')
                if request.form.get('calendario_domingo') == 'on':
                    dias_laborables.append('domingo')
                
                config['calendario']['dias_laborables'] = dias_laborables
                
                # Agenda y citas
                config['calendario']['agenda_habilitada'] = request.form.get('calendario_agenda_habilitada') == 'on'
                config['calendario']['citas_automaticas'] = request.form.get('calendario_citas_automaticas') == 'on'
                config['calendario']['duracion_cita'] = int(request.form.get('calendario_duracion_cita', 30))
                config['calendario']['intervalo_citas'] = int(request.form.get('calendario_intervalo_citas', 15))
                
                # Recordatorios
                config['calendario']['recordatorios_citas'] = request.form.get('calendario_recordatorios_citas') == 'on'
                config['calendario']['recordatorio_horas'] = int(request.form.get('calendario_recordatorio_horas', 24))
                config['calendario']['medio_recordatorio'] = request.form.get('calendario_medio_recordatorio', 'email')
                
                # Festivos
                festivos_text = request.form.get('calendario_festivos', '')
                if festivos_text:
                    config['calendario']['festivos'] = [d.strip() for d in festivos_text.split(',') if d.strip()]
                else:
                    config['calendario']['festivos'] = []
                
                config['calendario']['vacaciones_habilitadas'] = request.form.get('calendario_vacaciones_habilitadas') == 'on'
                
                # Horarios especiales
                config['calendario']['horarios_especiales'] = request.form.get('calendario_horarios_especiales') == 'on'
                config['calendario']['hora_almuerzo_inicio'] = request.form.get('calendario_hora_almuerzo_inicio', '12:00')
                config['calendario']['hora_almuerzo_fin'] = request.form.get('calendario_hora_almuerzo_fin', '13:00')
                
                # Capacidad
                config['calendario']['max_citas_dia'] = int(request.form.get('calendario_max_citas_dia', 10))
                config['calendario']['tecnicos_simultaneos'] = int(request.form.get('calendario_tecnicos_simultaneos', 2))
                
                # Sincronización
                config['calendario']['sincronizacion_google'] = request.form.get('calendario_sincronizacion_google') == 'on'
                config['calendario']['sincronizacion_outlook'] = request.form.get('calendario_sincronizacion_outlook') == 'on'
                config['calendario']['exportar_calendario'] = request.form.get('calendario_exportar_calendario') == 'on'
                
                # Zona horaria
                config['calendario']['zona_horaria'] = request.form.get('calendario_zona_horaria', 'America/Caracas')
                
                print("✅ Configuración de calendario actualizada correctamente")
            
            # Actualizar sección equipos clientes
            if 'equipos_habilitado' in request.form:
                if 'equipos_clientes' not in config:
                    config['equipos_clientes'] = {}
                
                # Configuración General
                config['equipos_clientes']['habilitado'] = request.form.get('equipos_habilitado') == 'on'
                config['equipos_clientes']['trazabilidad_completa'] = request.form.get('equipos_trazabilidad_completa') == 'on'
                config['equipos_clientes']['historial_detallado'] = request.form.get('equipos_historial_detallado') == 'on'
                
                # Tipos y Marcas
                marcas_text = request.form.get('equipos_marcas_permitidas', '')
                if marcas_text:
                    config['equipos_clientes']['marcas_permitidas'] = [m.strip() for m in marcas_text.split(',') if m.strip()]
                else:
                    config['equipos_clientes']['marcas_permitidas'] = []
                
                modelos_text = request.form.get('modelos_disponibles', '')
                if modelos_text:
                    config['equipos_clientes']['modelos_disponibles'] = [m.strip() for m in modelos_text.split(',') if m.strip()]
                else:
                    config['equipos_clientes']['modelos_disponibles'] = []
                
                config['equipos_clientes']['personalizar_modelos'] = request.form.get('equipos_personalizar_modelos') == 'on'
                
                # Estados de Equipos
                estados_text = request.form.get('estados_equipos', '')
                if estados_text:
                    config['equipos_clientes']['estados_equipos'] = [e.strip() for e in estados_text.split(',') if e.strip()]
                else:
                    config['equipos_clientes']['estados_equipos'] = []
                
                config['equipos_clientes']['notificar_cambio_estado'] = request.form.get('equipos_notificar_cambio_estado') == 'on'
                config['equipos_clientes']['auto_cambiar_entregado'] = request.form.get('equipos_auto_entregado') == 'on'
                
                # Condición Física
                condicion_text = request.form.get('equipos_condicion_fisica', '')
                if condicion_text:
                    config['equipos_clientes']['condicion_fisica_opciones'] = [c.strip() for c in condicion_text.split(',') if c.strip()]
                else:
                    config['equipos_clientes']['condicion_fisica_opciones'] = []
                
                config['equipos_clientes']['fotos_condicion'] = request.form.get('equipos_fotos_condicion') == 'on'
                config['equipos_clientes']['descripcion_danos'] = request.form.get('equipos_descripcion_danos') == 'on'
                
                # Accesorios Entregados
                accesorios_text = request.form.get('equipos_tipos_accesorios', '')
                if accesorios_text:
                    config['equipos_clientes']['tipos_accesorios'] = [a.strip() for a in accesorios_text.split(',') if a.strip()]
                else:
                    config['equipos_clientes']['tipos_accesorios'] = []
                
                config['equipos_clientes']['registrar_accesorios_entregados'] = request.form.get('equipos_registrar_accesorios') == 'on'
                config['equipos_clientes']['alertar_accesorios_faltantes'] = request.form.get('equipos_alertar_accesorios_faltantes') == 'on'
                
                # Características Técnicas
                config['equipos_clientes']['registrar_imei'] = request.form.get('equipos_registrar_imei') == 'on'
                config['equipos_clientes']['registrar_serial'] = request.form.get('equipos_registrar_serial') == 'on'
                config['equipos_clientes']['especificaciones_completas'] = request.form.get('equipos_especificaciones') == 'on'
                config['equipos_clientes']['codigo_barras'] = request.form.get('equipos_codigo_barras') == 'on'
                
                # Datos Adicionales
                colores_text = request.form.get('equipos_colores_disponibles', '')
                if colores_text:
                    config['equipos_clientes']['colores_disponibles'] = [c.strip() for c in colores_text.split(',') if c.strip()]
                else:
                    config['equipos_clientes']['colores_disponibles'] = []
                
                config['equipos_clientes']['registrar_capacidad_almacenamiento'] = request.form.get('equipos_capacidad_almacenamiento') == 'on'
                config['equipos_clientes']['registrar_version_sistema'] = request.form.get('equipos_version_sistema') == 'on'
                config['equipos_clientes']['registrar_numero_telefono'] = request.form.get('equipos_numero_telefono') == 'on'
                
                # Garantías y Reparaciones
                config['equipos_clientes']['garantia_estandar'] = int(request.form.get('equipos_garantia_estandar', 30))
                config['equipos_clientes']['alerta_garantia'] = int(request.form.get('equipos_alerta_garantia', 7))
                config['equipos_clientes']['validar_garantia'] = request.form.get('equipos_validar_garantia') == 'on'
                config['equipos_clientes']['reparaciones_multiples'] = request.form.get('equipos_reparaciones_multiples') == 'on'
                
                # Inventario de Equipos
                config['equipos_clientes']['inventario_en_lugar'] = request.form.get('equipos_inventario_en_lugar') == 'on'
                config['equipos_clientes']['alertar_equipos_largos'] = request.form.get('equipos_alertar_equipos_largos') == 'on'
                config['equipos_clientes']['tiempo_max_entrega'] = int(request.form.get('equipos_tiempo_max_entrega', 30))
                config['equipos_clientes']['revision_periodica'] = int(request.form.get('equipos_revision_periodica', 7))
                
                # Valoración y Precios
                config['equipos_clientes']['valor_mercado'] = request.form.get('equipos_valor_mercado') == 'on'
                config['equipos_clientes']['valor_reparacion'] = request.form.get('equipos_valor_reparacion') == 'on'
                config['equipos_clientes']['comparar_precios_reparacion'] = request.form.get('equipos_comparar_precios') == 'on'
                
                # Servicios Adicionales
                servicios_text = request.form.get('equipos_servicios_disponibles', '')
                if servicios_text:
                    config['equipos_clientes']['servicios_disponibles'] = [s.strip() for s in servicios_text.split(',') if s.strip()]
                else:
                    config['equipos_clientes']['servicios_disponibles'] = []
                
                config['equipos_clientes']['registrar_costos_adicionales'] = request.form.get('equipos_costos_adicionales') == 'on'
                
                # Estadísticas y Reportes
                config['equipos_clientes']['reportes_frecuencia_equipos'] = request.form.get('equipos_reportes_frecuencia') == 'on'
                config['equipos_clientes']['estadisticas_marcas'] = request.form.get('equipos_estadisticas_marcas') == 'on'
                config['equipos_clientes']['estadisticas_modelos'] = request.form.get('equipos_estadisticas_modelos') == 'on'
                config['equipos_clientes']['reportes_reparaciones'] = request.form.get('equipos_reportes_reparaciones') == 'on'
                
                print("✅ Configuración de equipos clientes actualizada correctamente")
            
            # Actualizar sección visual
            if 'tema' in request.form or 'color_primario' in request.form:
                if 'visual' not in config:
                    config['visual'] = {}
                
                # Temas y colores
                config['visual']['tema'] = request.form.get('tema', 'automatico')
                config['visual']['color_primario'] = request.form.get('color_primario', '#4f46e5')
                config['visual']['color_secundario'] = request.form.get('color_secundario', '#7c3aed')
                config['visual']['color_acentos'] = request.form.get('color_acentos', '#10b981')
                config['visual']['color_fondo'] = request.form.get('color_fondo', '#f9fafb')
                config['visual']['preview_tiempo_real'] = request.form.get('preview_tiempo_real') == 'on'
                
                # Tipografía
                config['visual']['familia_fuente'] = request.form.get('familia_fuente', 'poppins')
                config['visual']['tamano_fuente_base'] = int(request.form.get('tamano_fuente_base', 16))
                config['visual']['escala_movil'] = float(request.form.get('escala_movil', 1.0))
                config['visual']['escala_tablet'] = float(request.form.get('escala_tablet', 1.1))
                config['visual']['escala_desktop'] = float(request.form.get('escala_desktop', 1.2))
                
                # Densidad
                config['visual']['densidad'] = request.form.get('densidad', 'normal')
                config['visual']['altura_filas'] = int(request.form.get('altura_filas', 48))
                config['visual']['padding_general'] = int(request.form.get('padding_general', 16))
                config['visual']['gap_cards'] = int(request.form.get('gap_cards', 16))
                
                # Estilos
                config['visual']['estilo_bordes'] = request.form.get('estilo_bordes', 'redondeado')
                config['visual']['estilo_botones'] = request.form.get('estilo_botones', 'filled')
                config['visual']['estilo_tarjetas'] = request.form.get('estilo_tarjetas', 'sombra')
                
                # Sidebar
                config['visual']['ancho_sidebar'] = request.form.get('ancho_sidebar', 'normal')
                config['visual']['posicion_sidebar'] = request.form.get('posicion_sidebar', 'izquierda')
                config['visual']['sidebar_colapsable'] = request.form.get('sidebar_colapsable') == 'on'
                
                # Animaciones
                config['visual']['animaciones_habilitadas'] = request.form.get('animaciones_habilitadas') == 'on'
                config['visual']['velocidad_animacion'] = request.form.get('velocidad_animacion', 'normal')
                config['visual']['tipo_carga'] = request.form.get('tipo_carga', 'spinner')
                
                # Accesibilidad
                config['visual']['alto_contraste'] = request.form.get('alto_contraste') == 'on'
                config['visual']['reducir_movimiento'] = request.form.get('reducir_movimiento') == 'on'
                
                # Idioma
                config['visual']['idioma'] = request.form.get('idioma', 'es')
                
                # Logo
                config['visual']['posicion_logo'] = request.form.get('posicion_logo', 'esquina')
                config['visual']['tamano_logo'] = int(request.form.get('tamano_logo', 100))
                
                # Responsive
                config['visual']['sidebar_movil'] = request.form.get('sidebar_movil') == 'on'
                config['visual']['breakpoint_desktop'] = int(request.form.get('breakpoint_desktop', 1024))
                
                # Gradientes
                config['visual']['gradiente_fondo'] = request.form.get('gradiente_fondo') == 'on'
                config['visual']['gradiente_color_inicio'] = request.form.get('gradiente_color_inicio', '#667eea')
                config['visual']['gradiente_color_fin'] = request.form.get('gradiente_color_fin', '#764ba2')
                config['visual']['gradiente_direccion'] = request.form.get('gradiente_direccion', 'vertical')
                config['visual']['efecto_glassmorphism'] = request.form.get('efecto_glassmorphism') == 'on'
                
                # Guardar y exportar
                config['visual']['nombre_tema'] = request.form.get('nombre_tema', 'Mi Tema Personalizado')
                
                print("✅ Configuración visual actualizada correctamente")
            
            # Actualizar sección seguridad
            if 'tiempo_sesion' in request.form:
                if 'seguridad' not in config:
                    config['seguridad'] = {}
                
                # Autenticación y Sesiones
                config['seguridad']['tiempo_sesion'] = int(request.form.get('tiempo_sesion', 60))
                config['seguridad']['sesiones_concurrentes_max'] = int(request.form.get('sesiones_concurrentes_max', 2))
                config['seguridad']['intentos_login'] = int(request.form.get('intentos_login', 5))
                config['seguridad']['tiempo_bloqueo_ip'] = int(request.form.get('tiempo_bloqueo_ip', 15))
                config['seguridad']['cerrar_sesiones_concurrentes'] = request.form.get('cerrar_sesiones_concurrentes') == 'on'
                
                # Políticas de Contraseñas
                config['seguridad']['longitud_min_contraseña'] = int(request.form.get('longitud_min_contraseña', 8))
                config['seguridad']['dias_expira_contraseña'] = int(request.form.get('dias_expira_contraseña', 90))
                config['seguridad']['complejidad_contraseña'] = request.form.get('complejidad_contraseña') == 'on'
                config['seguridad']['no_reusar_contraseñas'] = request.form.get('no_reusar_contraseñas') == 'on'
                config['seguridad']['expira_contraseña'] = request.form.get('expira_contraseña') == 'on'
                
                # Autenticación 2FA
                config['seguridad']['autenticacion_2fa'] = request.form.get('autenticacion_2fa') == 'on'
                config['seguridad']['2fa_sms'] = request.form.get('2fa_sms') == 'on'
                config['seguridad']['2fa_email'] = request.form.get('2fa_email') == 'on'
                
                # Registro de Actividades
                config['seguridad']['registro_actividades'] = request.form.get('registro_actividades') == 'on'
                config['seguridad']['retencion_logs'] = int(request.form.get('retencion_logs', 90))
                
                # Cifrado de Datos
                config['seguridad']['cifrar_datos_sensibles'] = request.form.get('cifrar_datos_sensibles') == 'on'
                config['seguridad']['backups_cifrados'] = request.form.get('backups_cifrados') == 'on'
                config['seguridad']['exportaciones_cifradas'] = request.form.get('exportaciones_cifradas') == 'on'
                
                # Backups Automáticos
                config['seguridad']['backups_automaticos_seguridad'] = request.form.get('backups_automaticos_seguridad') == 'on'
                config['seguridad']['dias_retencion_backups'] = int(request.form.get('dias_retencion_backups', 30))
                
                # Control de Acceso
                config['seguridad']['bloqueo_ip_activo'] = request.form.get('bloqueo_ip_activo') == 'on'
                config['seguridad']['ips_permitidas'] = request.form.get('ips_permitidas', '')
                
                # Alertas de Seguridad
                config['seguridad']['alertar_login_nuevo'] = request.form.get('alertar_login_nuevo') == 'on'
                config['seguridad']['alertar_cambios_permisos'] = request.form.get('alertar_cambios_permisos') == 'on'
                config['seguridad']['alertas_email'] = request.form.get('alertas_email') == 'on'
                config['seguridad']['alertas_sms'] = request.form.get('alertas_sms') == 'on'
                config['seguridad']['alertas_whatsapp'] = request.form.get('alertas_whatsapp') == 'on'
                
                print("✅ Configuración de seguridad actualizada")
            
            # Guardar configuración
            print("\n💾 Intentando guardar configuración...")
            if guardar_configuracion(config):
                print("✅ CONFIGURACIÓN GUARDADA EXITOSAMENTE")
                print("="*60 + "\n")
                flash('Configuración guardada exitosamente', 'success')
                registrar_bitacora(session.get('username', 'Sistema'), 'Configuración', 'Configuración del sistema actualizada')
                return redirect(url_for('configuracion_sistema') + '?config_saved=1')
            else:
                print("❌ ERROR: No se pudo guardar la configuración")
                print("="*60 + "\n")
                flash('Error guardando la configuración', 'danger')
            
            return redirect(url_for('configuracion_sistema'))
        except Exception as e:
            print(f"❌ ERROR actualizando configuración: {e}")
            print(traceback.format_exc())
            print("="*60 + "\n")
            flash(f'Error actualizando configuración: {str(e)}', 'danger')
            return redirect(url_for('configuracion_sistema'))
    
    # GET - Mostrar configuración
    config = cargar_configuracion()
    return render_template('configuracion_sistema.html', config=config)

@app.route('/usuarios/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo_usuario():
    """Crear nuevo usuario con contraseña"""
    if request.method == 'POST':
        try:
            username = request.form.get('username')
            password = request.form.get('password')
            rol = request.form.get('rol', 'Técnico')
            
            if not username or not password:
                flash('Username y contraseña son requeridos', 'danger')
                return redirect(url_for('nuevo_usuario'))
            
            # Leer usuarios existentes
            if os.path.exists('usuarios.json'):
                with open('usuarios.json', 'r', encoding='utf-8') as f:
                    usuarios = json.load(f)
            else:
                usuarios = {'usuarios': {}}
            
            # Verificar si el usuario ya existe
            if username in usuarios.get('usuarios', {}):
                flash(f'El usuario {username} ya existe', 'danger')
                return redirect(url_for('nuevo_usuario'))
            
            # Crear nuevo usuario con hash de contraseña
            import hashlib
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            
            if 'usuarios' not in usuarios:
                usuarios['usuarios'] = {}
            
            usuarios['usuarios'][username] = {
                'password_hash': password_hash,
                'rol': rol,
                'fecha_creacion': datetime.now().isoformat(),
                'activo': True
            }
            
            # Asignar rol en el sistema de roles
            asignar_rol_usuario(username, rol)
            
            # Guardar usuarios
            with open('usuarios.json', 'w', encoding='utf-8') as f:
                json.dump(usuarios, f, indent=4, ensure_ascii=False)
            
            flash(f'Usuario {username} creado exitosamente con rol {rol}', 'success')
            return redirect(url_for('gestionar_usuarios'))
        
        except Exception as e:
            flash(f'Error creando usuario: {str(e)}', 'danger')
            return redirect(url_for('nuevo_usuario'))
    
    # GET - Mostrar formulario
    roles = cargar_roles()
    return render_template('nuevo_usuario.html', roles=roles)

@app.route('/usuarios/gestion', methods=['GET', 'POST'])
@login_required
def gestionar_usuarios():
    """Gestión de usuarios y roles"""
    if request.method == 'POST':
        try:
            accion = request.form.get('accion')
            username = request.form.get('username')
            rol = request.form.get('rol')
            
            if accion == 'asignar_rol':
                if asignar_rol_usuario(username, rol):
                    flash(f'Rol {rol} asignado a {username}', 'success')
                else:
                    flash(f'Error asignando rol', 'danger')
            elif accion == 'eliminar_usuario':
                # Leer y eliminar usuario
                if os.path.exists('usuarios.json'):
                    with open('usuarios.json', 'r', encoding='utf-8') as f:
                        usuarios = json.load(f)
                    
                    if 'usuarios' in usuarios and username in usuarios['usuarios']:
                        del usuarios['usuarios'][username]
                        
                        with open('usuarios.json', 'w', encoding='utf-8') as f:
                            json.dump(usuarios, f, indent=4, ensure_ascii=False)
                        
                        flash(f'Usuario {username} eliminado', 'success')
            
            return redirect(url_for('gestionar_usuarios'))
        
        except Exception as e:
            flash(f'Error: {str(e)}', 'danger')
            return redirect(url_for('gestionar_usuarios'))
    
    # GET - Mostrar usuarios y roles
    try:
        roles = cargar_roles()
        
        # Cargar usuarios con contraseñas
        usuarios_con_password = {}
        if os.path.exists('usuarios.json'):
            with open('usuarios.json', 'r', encoding='utf-8') as f:
                usuarios_data = json.load(f)
                usuarios_con_password = usuarios_data.get('usuarios', {})
        
        return render_template('gestion_usuarios.html', roles=roles, usuarios=usuarios_con_password)
    except Exception as e:
        flash(f'Error cargando usuarios: {str(e)}', 'danger')
        return redirect(url_for('index'))

@app.route('/api/mi-rol')
@login_required
def api_mi_rol():
    """API para obtener el rol del usuario actual"""
    try:
        username = session.get('usuario', '')
        rol = obtener_rol_usuario(username)
        return jsonify({'rol': rol, 'username': username})
    except Exception as e:
        return jsonify({'error': str(e), 'rol': 'Técnico'}), 500

@app.route('/api/configuracion', methods=['GET'])
@login_required
def api_configuracion():
    """API para obtener configuración"""
    try:
        config = cargar_configuracion()
        return jsonify(config)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/configuracion', methods=['POST'])
@login_required
def api_configuracion_update():
    """API para actualizar configuración"""
    try:
        data = request.get_json()
        config = cargar_configuracion()
        
        # Actualizar configuración
        for seccion, valores in data.items():
            if seccion in config:
                config[seccion].update(valores)
        
        if guardar_configuracion(config):
            return jsonify({'success': True, 'message': 'Configuración actualizada'})
        else:
            return jsonify({'success': False, 'error': 'Error guardando configuración'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/test-notificaciones')
@login_required
def test_notificaciones():
    """Endpoint para probar las notificaciones del sistema"""
    try:
        config = cargar_configuracion()
        notificaciones = config.get('notificaciones', {})
        empresa = config.get('empresa', {})
        
        # Verificar configuración
        whatsapp_habilitado = notificaciones.get('whatsapp_habilitado', False)
        email_habilitado = notificaciones.get('email_habilitado', False)
        email_configurado = bool(
            notificaciones.get('email_smtp_server') and 
            notificaciones.get('email_usuario') and 
            notificaciones.get('email_password')
        )
        
        # Datos de prueba
        telefono_prueba = empresa.get('whatsapp', '') or '584241234567'
        email_prueba = empresa.get('email', '') or notificaciones.get('email_usuario', '')
        
        resultado = {
            'success': True,
            'configuracion': {
                'whatsapp_habilitado': whatsapp_habilitado,
                'email_habilitado': email_habilitado,
                'email_configurado': email_configurado,
                'smtp_server': notificaciones.get('email_smtp_server', ''),
                'email_usuario': notificaciones.get('email_usuario', ''),
                'empresa_whatsapp': empresa.get('whatsapp', ''),
                'empresa_email': empresa.get('email', '')
            },
            'pruebas': {}
        }
        
        # Probar WhatsApp
        if whatsapp_habilitado:
            mensaje_prueba = f"🔧 *PRUEBA DE NOTIFICACIÓN*\n\nEsta es una notificación de prueba del sistema.\n\n*Empresa:* {empresa.get('nombre', 'Servicio Técnico')}"
            enlace_whatsapp = enviar_whatsapp_reportes(telefono_prueba, mensaje_prueba)
            resultado['pruebas']['whatsapp'] = {
                'exito': bool(enlace_whatsapp),
                'enlace': enlace_whatsapp,
                'telefono': telefono_prueba
            }
        else:
            resultado['pruebas']['whatsapp'] = {
                'exito': False,
                'mensaje': 'WhatsApp no está habilitado en la configuración'
            }
        
        # Probar Email (solo verificar configuración, no enviar realmente)
        if email_habilitado and email_configurado:
            resultado['pruebas']['email'] = {
                'exito': True,
                'mensaje': 'Configuración de email correcta',
                'destinatario': email_prueba,
                'nota': 'Para probar el envío real, use la función de notificar cliente'
            }
        else:
            resultado['pruebas']['email'] = {
                'exito': False,
                'mensaje': 'Email no está habilitado o la configuración está incompleta',
                'configuracion_faltante': {
                    'smtp_server': not notificaciones.get('email_smtp_server'),
                    'email_usuario': not notificaciones.get('email_usuario'),
                    'email_password': not notificaciones.get('email_password')
                }
            }
        
        return jsonify(resultado)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/alertas')
@login_required
def api_alertas():
    """Endpoint API para obtener alertas activas"""
    try:
        alertas_activas = verificar_alertas()
        return jsonify({
            'success': True,
            'alertas': alertas_activas,
            'total': len(alertas_activas),
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'alertas': [],
            'total': 0
        }), 500

def enviar_alertas_automaticas():
    """Envía alertas automáticamente por WhatsApp/Email según la configuración"""
    try:
        config = cargar_configuracion()
        alertas_config = config.get('alertas', {})
        
        # Verificar si hay alertas habilitadas
        alertas_habilitadas = [
            k for k, v in alertas_config.items() 
            if isinstance(v, bool) and v and k not in ['canal_notificacion', 'horario_alertas']
        ]
        
        if not alertas_habilitadas:
            print("ℹ️ No hay alertas habilitadas para enviar")
            return {'success': False, 'message': 'No hay alertas habilitadas'}
        
        # Obtener alertas activas
        alertas_activas = verificar_alertas()
        
        if not alertas_activas:
            print("✅ No hay alertas activas para enviar")
            return {'success': True, 'message': 'No hay alertas activas', 'enviadas': 0}
        
        # Obtener configuración de notificaciones
        canal_notificacion = alertas_config.get('canal_notificacion', 'email')
        notificaciones_sistema = config.get('notificaciones', {})
        whatsapp_habilitado = notificaciones_sistema.get('whatsapp_habilitado', False)
        email_habilitado = notificaciones_sistema.get('email_habilitado', False)
        
        # Obtener datos de empresa
        empresa = config.get('empresa', {})
        email_empresa = empresa.get('email', '')
        whatsapp_empresa = empresa.get('whatsapp', '')
        
        resultados = {'whatsapp': False, 'email': False, 'enviadas': 0}
        
        # Construir mensaje de alertas
        mensaje_texto = f"🔔 *ALERTAS DEL SISTEMA*\n\n"
        mensaje_texto += f"Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n"
        
        for alerta in alertas_activas:
            mensaje_texto += f"{alerta.get('icono', '📌')} *{alerta.get('titulo', 'Alerta')}*\n"
            mensaje_texto += f"   {alerta.get('mensaje', '')}\n"
            if alerta.get('total'):
                mensaje_texto += f"   Total: ${alerta.get('total', 0):.2f}\n"
            mensaje_texto += "\n"
        
        mensaje_texto += f"\n---\n*{empresa.get('nombre', 'Sistema')}*"
        
        # Enviar por Email
        if email_habilitado and email_empresa and (canal_notificacion in ['email', 'ambos']):
            try:
                asunto = f"🔔 Alertas del Sistema - {datetime.now().strftime('%d/%m/%Y')}"
                resultado_email = enviar_email_reporte(asunto, mensaje_texto, email_empresa, config)
                if resultado_email:
                    resultados['email'] = True
                    resultados['enviadas'] += 1
                    print(f"✅ Email de alertas enviado a {email_empresa}")
                else:
                    print(f"⚠️ Error al enviar email de alertas a {email_empresa}")
            except Exception as e:
                print(f"❌ Error enviando email de alertas: {e}")
        
        # Enviar por WhatsApp (generar enlace)
        if whatsapp_habilitado and whatsapp_empresa and (canal_notificacion in ['whatsapp', 'ambos']):
            try:
                # Limpiar número de WhatsApp
                telefono_limpio = str(whatsapp_empresa).replace('+', '').replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
                if not telefono_limpio.startswith('58'):
                    if telefono_limpio.startswith('0'):
                        telefono_limpio = '58' + telefono_limpio[1:]
                    else:
                        telefono_limpio = '58' + telefono_limpio
                
                from urllib.parse import quote
                mensaje_codificado = quote(mensaje_texto)
                enlace_whatsapp = f"https://wa.me/{telefono_limpio}?text={mensaje_codificado}"
                
                resultados['whatsapp'] = True
                resultados['enviadas'] += 1
                resultados['enlace_whatsapp'] = enlace_whatsapp
                print(f"✅ Enlace WhatsApp de alertas generado: {enlace_whatsapp}")
            except Exception as e:
                print(f"❌ Error generando WhatsApp de alertas: {e}")
        
        if resultados['enviadas'] > 0:
            print(f"✅ Alertas enviadas: {resultados['enviadas']} canal(es)")
        
        return {
            'success': True,
            'alertas_enviadas': len(alertas_activas),
            'canales': resultados,
            'mensaje': f"Alertas enviadas a {resultados['enviadas']} canal(es)"
        }
        
    except Exception as e:
        print(f"❌ Error en envío automático de alertas: {e}")
        import traceback
        traceback.print_exc()
        return {'success': False, 'error': str(e)}

@app.route('/api/alertas/enviar', methods=['POST'])
@login_required
def api_enviar_alertas():
    """Endpoint para enviar alertas manualmente"""
    try:
        resultado = enviar_alertas_automaticas()
        return jsonify(resultado)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/test-alertas')
@login_required
def test_alertas():
    """Endpoint para probar las alertas y reportes"""
    try:
        config = cargar_configuracion()
        alertas_config = config.get('alertas', {})
        
        # Verificar estado de las alertas
        estado = {
            'alertas_activas': verificar_alertas(),
            'estadisticas_semanales': alertas_config.get('estadisticas_semanales', False),
            'estadisticas_mensuales': alertas_config.get('estadisticas_mensuales', False),
            'configuracion': {
                'email_empresa': config.get('empresa', {}).get('email', 'No configurado'),
                'whatsapp_empresa': config.get('empresa', {}).get('whatsapp', 'No configurado'),
                'canal_notificacion': alertas_config.get('canal_notificacion', 'email'),
                'horario_alertas': alertas_config.get('horario_alertas', '08:00')
            }
        }
        
        return jsonify(estado)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/generar-reporte-semanal', methods=['POST'])
@login_required
def generar_reporte_semanal_endpoint():
    """Endpoint para generar reporte semanal manualmente"""
    try:
        resultado = generar_reporte_semanal(manual=True)
        if resultado:
            # Verificar si el resultado es un enlace de WhatsApp o un mensaje de texto
            if isinstance(resultado, str) and resultado.startswith('https://wa.me/'):
                return jsonify({
                    'success': True,
                    'tipo': 'whatsapp',
                    'enlace': resultado
                })
            else:
                return jsonify({
                    'success': True,
                    'tipo': 'texto',
                    'mensaje': resultado
                })
        else:
            return jsonify({'success': False, 'error': 'No se pudo generar el reporte'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/generar-reporte-mensual', methods=['POST'])
@login_required
def generar_reporte_mensual_endpoint():
    """Endpoint para generar reporte mensual manualmente"""
    try:
        resultado = generar_reporte_mensual(manual=True)
        if resultado:
            # Verificar si el resultado es un enlace de WhatsApp o un mensaje de texto
            if isinstance(resultado, str) and resultado.startswith('https://wa.me/'):
                return jsonify({
                    'success': True,
                    'tipo': 'whatsapp',
                    'enlace': resultado
                })
            else:
                return jsonify({
                    'success': True,
                    'tipo': 'texto',
                    'mensaje': resultado
                })
        else:
            return jsonify({'success': False, 'error': 'No se pudo generar el reporte'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500




# ===========================
# SISTEMA DE ALERTAS Y REPORTES AUTOMÁTICOS
# ===========================

def enviar_whatsapp_reportes(telefono, mensaje):
    """Genera enlace de WhatsApp para enviar reportes/alertas"""
    try:
        # Limpiar teléfono
        telefono_limpio = str(telefono).replace(' ', '').replace('-', '').replace('(', '').replace(')', '').replace('+', '')
        
        # Agregar código de país si no lo tiene
        if not telefono_limpio.startswith('58'):
            telefono_limpio = '58' + telefono_limpio.lstrip('0')
        
        # Codificar mensaje para URL
        mensaje_codificado = urllib.parse.quote(mensaje)
        
        # Generar enlace
        enlace = f"https://wa.me/{telefono_limpio}?text={mensaje_codificado}"
        
        print(f"📱 Enlace WhatsApp generado para reporte: {enlace[:100]}...")
        
        return enlace
        
    except Exception as e:
        print(f"❌ Error generando enlace WhatsApp: {e}")
        return None

def enviar_email_reporte(asunto, mensaje, destinatario, config):
    """Envía un reporte por email"""
    try:
        # Obtener configuración SMTP
        email_habilitado = config.get('notificaciones', {}).get('email_habilitado', False)
        
        if not email_habilitado:
            print("📧 Envío de email deshabilitado en configuración")
            return False
        
        smtp_server = config.get('notificaciones', {}).get('email_smtp_server', '')
        smtp_port = config.get('notificaciones', {}).get('email_smtp_port', 587)
        email_usuario = config.get('notificaciones', {}).get('email_usuario', '')
        email_password = config.get('notificaciones', {}).get('email_password', '')
        email_remitente = config.get('notificaciones', {}).get('email_remitente', email_usuario)
        
        if not all([smtp_server, email_usuario, email_password, destinatario]):
            print("❌ Configuración de email incompleta")
            return False
        
        # Crear mensaje
        msg = MIMEMultipart()
        msg['From'] = email_remitente
        msg['To'] = destinatario
        msg['Subject'] = asunto
        
        # Convertir mensaje de texto plano a HTML básico
        mensaje_html = mensaje.replace('\n', '<br>').replace('*', '<strong>', 1).replace('*', '</strong>', 1)
        msg.attach(MIMEText(mensaje, 'plain', 'utf-8'))
        
        # Enviar email
        print(f"📧 Enviando email a {destinatario}...")
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(email_usuario, email_password)
        server.send_message(msg)
        server.quit()
        
        print(f"✅ Email enviado exitosamente a {destinatario}")
        return True
        
    except Exception as e:
        print(f"❌ Error enviando email: {e}")
        import traceback
        traceback.print_exc()
        return False

def notificar_cliente(cliente_email, cliente_telefono, asunto, mensaje_txt, tipo='nota_entrega'):
    """Notifica a un cliente por email y WhatsApp si está configurado"""
    try:
        config = cargar_configuracion()
        notificaciones = config.get('notificaciones', {})
        empresa = config.get('empresa', {})
        
        # Preparar mensaje
        mensaje = f"""
*{asunto}*

{mensaje_txt}

---
*{empresa.get('nombre', 'Servicio Técnico')}*
📱 WhatsApp: {empresa.get('whatsapp', '')}
📧 Email: {empresa.get('email', '')}
        """
        
        resultados = {'whatsapp': False, 'email': False}
        
        # Enviar por WhatsApp si está configurado y el cliente tiene teléfono
        if cliente_telefono and notificaciones.get('whatsapp_habilitado', False):
            try:
                enlace_whatsapp = enviar_whatsapp_reportes(cliente_telefono, mensaje)
                if enlace_whatsapp:
                    print(f"📱 Enlace WhatsApp generado para {cliente_telefono}")
                    resultados['whatsapp'] = True
                    resultados['enlace_whatsapp'] = enlace_whatsapp
            except Exception as e:
                print(f"❌ Error generando WhatsApp: {e}")
        
        # Enviar por email si está configurado y el cliente tiene email
        if cliente_email and notificaciones.get('email_habilitado', False):
            try:
                resultado_email = enviar_email_reporte(asunto, mensaje, cliente_email, config)
                if resultado_email:
                    print(f"📧 Email enviado a {cliente_email}")
                    resultados['email'] = True
            except Exception as e:
                print(f"❌ Error enviando email al cliente: {e}")
        
        return resultados
        
    except Exception as e:
        print(f"❌ Error notificando al cliente: {e}")
        import traceback
        traceback.print_exc()
        return {'whatsapp': False, 'email': False, 'error': str(e)}

def generar_reporte_semanal(manual=False):
    """Genera y envía reporte semanal de estadísticas"""
    try:
        config = cargar_configuracion()
        alertas = config.get('alertas', {})
        
        # Si se llama manualmente, no verificar si está habilitado
        if not manual and not alertas.get('estadisticas_semanales', False):
            print("📊 Reporte semanal deshabilitado en configuración")
            return None
        
        print("📊 Iniciando generación de reporte semanal...")
        
        # Obtener datos
        ordenes = cargar_datos('ordenes_servicio.json')
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        pagos = cargar_datos('pagos_recibidos.json')
        
        # Calcular estadísticas semanales
        fecha_inicio = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        ordenes_semana = {k: v for k, v in ordenes.items() if v.get('fecha_recepcion', '') >= fecha_inicio}
        notas_semana = {k: v for k, v in notas.items() if v.get('fecha', '') >= fecha_inicio}
        pagos_semana = {k: v for k, v in pagos.items() if v.get('fecha', '') >= fecha_inicio}
        
        total_ordenes = len(ordenes_semana)
        total_notas = len(notas_semana)
        total_pagos = sum(float(p.get('monto_usd', 0)) for p in pagos_semana.values())
        
        # Generar mensaje
        mensaje = f"""
📊 *Reporte Semanal de Negocio*

📋 *Periodo:* Últimos 7 días
📅 *Fecha:* {datetime.now().strftime('%d/%m/%Y')}

🔧 *Órdenes de Servicio:*
• Total: {total_ordenes}

📦 *Notas de Entrega:*
• Total: {total_notas}

💰 *Pagos Recibidos:*
• Total: ${total_pagos:.2f} USD

---
Generado automáticamente por el Sistema de Gestión Técnica
        """
        
        print(f"✅ Reporte semanal generado: {total_ordenes} órdenes, {total_notas} notas, ${total_pagos:.2f} pagos")
        
        # Si es manual, siempre generar enlace WhatsApp si está configurado y enviar por email
        if manual:
            notificaciones_sistema = config.get('notificaciones', {})
            whatsapp_habilitado = notificaciones_sistema.get('whatsapp_habilitado', False)
            email_habilitado = notificaciones_sistema.get('email_habilitado', False)
            whatsapp_empresa = config.get('empresa', {}).get('whatsapp', '')
            email_empresa = config.get('empresa', {}).get('email', '')
            
            enlace_whatsapp = None
            
            # Generar enlace WhatsApp si está configurado
            if whatsapp_habilitado and whatsapp_empresa:
                try:
                    # Limpiar número de WhatsApp
                    telefono_limpio = str(whatsapp_empresa).replace('+', '').replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
                    if not telefono_limpio.startswith('58'):
                        if telefono_limpio.startswith('0'):
                            telefono_limpio = '58' + telefono_limpio[1:]
                        else:
                            telefono_limpio = '58' + telefono_limpio
                    
                    from urllib.parse import quote
                    mensaje_codificado = quote(mensaje.strip())
                    enlace_whatsapp = f"https://wa.me/{telefono_limpio}?text={mensaje_codificado}"
                    print(f"📱 Enlace WhatsApp generado: {enlace_whatsapp}")
                except Exception as e:
                    print(f"❌ Error generando enlace WhatsApp: {e}")
            
            # Enviar por email si está configurado
            if email_habilitado and email_empresa:
                try:
                    # Determinar el tipo de reporte según la función
                    tipo_reporte = "Reporte Semanal de Negocio" if "Semanal" in mensaje else "Reporte Mensual de Negocio"
                    resultado_email = enviar_email_reporte(
                        f"📊 {tipo_reporte}",
                        mensaje,
                        email_empresa,
                        config
                    )
                    if resultado_email:
                        print(f"✅ Email enviado exitosamente a: {email_empresa}")
                    else:
                        print(f"⚠️ No se pudo enviar el email a: {email_empresa}")
                except Exception as e:
                    print(f"❌ Error enviando email: {e}")
            
            # Retornar enlace WhatsApp si existe, sino el mensaje de texto
            return enlace_whatsapp if enlace_whatsapp else mensaje.strip()
        
        # Para envío automático, seguir lógica original
        canal = alertas.get('canal_notificacion', 'email')
        whatsapp_empresa = config.get('empresa', {}).get('whatsapp', '')
        email_empresa = config.get('empresa', {}).get('email', '')
        
        # Enviar según canal configurado
        if canal in ['whatsapp', 'ambos'] and whatsapp_empresa:
            enlace_whatsapp = enviar_whatsapp_reportes(whatsapp_empresa, mensaje)
            print(f"📱 Enlace WhatsApp para envío manual: {enlace_whatsapp}")
        
        if canal in ['email', 'ambos'] and email_empresa:
            resultado = enviar_email_reporte(
                "📊 Reporte Semanal de Negocio",
                mensaje,
                email_empresa,
                config
            )
            if resultado:
                print(f"✅ Email enviado exitosamente a: {email_empresa}")
        
        return mensaje.strip()
        
    except Exception as e:
        print(f"❌ Error generando reporte semanal: {e}")

def generar_reporte_mensual(manual=False):
    """Genera y envía reporte mensual de estadísticas"""
    try:
        config = cargar_configuracion()
        alertas = config.get('alertas', {})
        
        # Si se llama manualmente, no verificar si está habilitado
        if not manual and not alertas.get('estadisticas_mensuales', False):
            print("📊 Reporte mensual deshabilitado en configuración")
            return None
        
        print("📊 Iniciando generación de reporte mensual...")
        
        # Obtener datos
        ordenes = cargar_datos('ordenes_servicio.json')
        notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
        pagos = cargar_datos('pagos_recibidos.json')
        
        # Calcular estadísticas mensuales
        fecha_inicio = datetime.now().replace(day=1).strftime('%Y-%m-%d')
        ordenes_mes = {k: v for k, v in ordenes.items() if v.get('fecha_recepcion', '') >= fecha_inicio}
        notas_mes = {k: v for k, v in notas.items() if v.get('fecha', '') >= fecha_inicio}
        pagos_mes = {k: v for k, v in pagos.items() if v.get('fecha', '') >= fecha_inicio}
        
        total_ordenes = len(ordenes_mes)
        total_notas = len(notas_mes)
        total_pagos_usd = sum(float(p.get('monto_usd', 0)) for p in pagos_mes.values())
        
        # Generar mensaje
        mensaje = f"""
📊 *Reporte Mensual de Negocio*

📋 *Periodo:* Mes actual
📅 *Fecha:* {datetime.now().strftime('%d/%m/%Y')}

🔧 *Órdenes de Servicio:*
• Total: {total_ordenes}

📦 *Notas de Entrega:*
• Total: {total_notas}

💰 *Pagos Recibidos:*
• Total: ${total_pagos_usd:.2f} USD

---
Generado automáticamente por el Sistema de Gestión Técnica
        """
        
        print(f"✅ Reporte mensual generado: {total_ordenes} órdenes, {total_notas} notas, ${total_pagos_usd:.2f} pagos")
        
        # Si es manual, siempre generar enlace WhatsApp si está configurado y enviar por email
        if manual:
            notificaciones_sistema = config.get('notificaciones', {})
            whatsapp_habilitado = notificaciones_sistema.get('whatsapp_habilitado', False)
            email_habilitado = notificaciones_sistema.get('email_habilitado', False)
            whatsapp_empresa = config.get('empresa', {}).get('whatsapp', '')
            email_empresa = config.get('empresa', {}).get('email', '')
            
            enlace_whatsapp = None
            
            # Generar enlace WhatsApp si está configurado
            if whatsapp_habilitado and whatsapp_empresa:
                try:
                    # Limpiar número de WhatsApp
                    telefono_limpio = str(whatsapp_empresa).replace('+', '').replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
                    if not telefono_limpio.startswith('58'):
                        if telefono_limpio.startswith('0'):
                            telefono_limpio = '58' + telefono_limpio[1:]
                        else:
                            telefono_limpio = '58' + telefono_limpio
                    
                    from urllib.parse import quote
                    mensaje_codificado = quote(mensaje.strip())
                    enlace_whatsapp = f"https://wa.me/{telefono_limpio}?text={mensaje_codificado}"
                    print(f"📱 Enlace WhatsApp generado: {enlace_whatsapp}")
                except Exception as e:
                    print(f"❌ Error generando enlace WhatsApp: {e}")
            
            # Enviar por email si está configurado
            if email_habilitado and email_empresa:
                try:
                    # Determinar el tipo de reporte según la función
                    tipo_reporte = "Reporte Semanal de Negocio" if "Semanal" in mensaje else "Reporte Mensual de Negocio"
                    resultado_email = enviar_email_reporte(
                        f"📊 {tipo_reporte}",
                        mensaje,
                        email_empresa,
                        config
                    )
                    if resultado_email:
                        print(f"✅ Email enviado exitosamente a: {email_empresa}")
                    else:
                        print(f"⚠️ No se pudo enviar el email a: {email_empresa}")
                except Exception as e:
                    print(f"❌ Error enviando email: {e}")
            
            # Retornar enlace WhatsApp si existe, sino el mensaje de texto
            return enlace_whatsapp if enlace_whatsapp else mensaje.strip()
        
        # Para envío automático, seguir lógica original
        canal = alertas.get('canal_notificacion', 'email')
        whatsapp_empresa = config.get('empresa', {}).get('whatsapp', '')
        email_empresa = config.get('empresa', {}).get('email', '')
        
        # Enviar según canal configurado
        if canal in ['whatsapp', 'ambos'] and whatsapp_empresa:
            enlace_whatsapp = enviar_whatsapp_reportes(whatsapp_empresa, mensaje)
            print(f"📱 Enlace WhatsApp para envío manual: {enlace_whatsapp}")
        
        if canal in ['email', 'ambos'] and email_empresa:
            resultado = enviar_email_reporte(
                "📊 Reporte Mensual de Negocio",
                mensaje,
                email_empresa,
                config
            )
            if resultado:
                print(f"✅ Email enviado exitosamente a: {email_empresa}")
        
        return mensaje
        
    except Exception as e:
        print(f"❌ Error generando reporte mensual: {e}")

def verificar_alertas():
    """Verifica y muestra alertas configuradas - VERSIÓN COMPLETA"""
    try:
        config = cargar_configuracion()
        alertas = config.get('alertas', {})
        
        alertas_activas = []
        detalles_alertas = {}  # Para almacenar detalles de cada alerta
        
        ahora = datetime.now()
        
        # 1. Verificar stock mínimo
        if alertas.get('stock_minimo', False):
            try:
                inventario = cargar_datos(ARCHIVO_INVENTARIO)
                productos_bajo_minimo = []
                for prod_id, prod in inventario.items():
                    stock_actual = int(prod.get('stock_actual', prod.get('cantidad', 0)))
                    stock_minimo = int(prod.get('stock_minimo', 5))
                    if stock_actual <= stock_minimo and stock_actual > 0:
                        productos_bajo_minimo.append({
                            'id': prod_id,
                            'nombre': prod.get('nombre', 'Desconocido'),
                            'stock': stock_actual,
                            'minimo': stock_minimo
                        })
            
                if productos_bajo_minimo:
                    alertas_activas.append({
                        'tipo': 'warning',
                        'titulo': 'Stock Mínimo',
                        'mensaje': f"{len(productos_bajo_minimo)} producto(s) bajo nivel mínimo",
                        'icono': 'fas fa-box',
                        'cantidad': len(productos_bajo_minimo),
                        'detalles': productos_bajo_minimo[:5]  # Primeros 5
                    })
            except Exception as e:
                print(f"Error verificando stock mínimo: {e}")
        
        # 2. Verificar productos agotados
        if alertas.get('productos_agotados', False):
            try:
                inventario = cargar_datos(ARCHIVO_INVENTARIO)
                productos_agotados = []
                for prod_id, prod in inventario.items():
                    stock_actual = int(prod.get('stock_actual', prod.get('cantidad', 0)))
                    if stock_actual == 0:
                        productos_agotados.append({
                            'id': prod_id,
                            'nombre': prod.get('nombre', 'Desconocido')
                        })
                
                if productos_agotados:
                    alertas_activas.append({
                        'tipo': 'danger',
                        'titulo': 'Productos Agotados',
                        'mensaje': f"{len(productos_agotados)} producto(s) sin stock",
                        'icono': 'fas fa-exclamation-circle',
                        'cantidad': len(productos_agotados),
                        'detalles': productos_agotados[:5]
                    })
            except Exception as e:
                print(f"Error verificando productos agotados: {e}")
        
        # 3. Verificar productos próximos a caducar (si tienen fecha de vencimiento)
        if alertas.get('productos_caducando', False):
            try:
                inventario = cargar_datos(ARCHIVO_INVENTARIO)
                productos_caducando = []
                dias_antes = 30  # Alertar 30 días antes
                
                for prod_id, prod in inventario.items():
                    fecha_vencimiento = prod.get('fecha_vencimiento') or prod.get('fecha_caducidad')
                    if fecha_vencimiento:
                        try:
                            fecha_venc = datetime.strptime(fecha_vencimiento, '%Y-%m-%d')
                            dias_restantes = (fecha_venc - ahora).days
                            if 0 <= dias_restantes <= dias_antes:
                                productos_caducando.append({
                                    'id': prod_id,
                                    'nombre': prod.get('nombre', 'Desconocido'),
                                    'dias_restantes': dias_restantes,
                                    'fecha': fecha_vencimiento
                                })
                        except:
                            continue
                
                if productos_caducando:
                    alertas_activas.append({
                        'tipo': 'warning',
                        'titulo': 'Productos Próximos a Caducar',
                        'mensaje': f"{len(productos_caducando)} producto(s) caducando en los próximos {dias_antes} días",
                        'icono': 'fas fa-clock',
                        'cantidad': len(productos_caducando),
                        'detalles': productos_caducando[:5]
                    })
            except Exception as e:
                print(f"Error verificando productos caducando: {e}")
        
        # 4. Verificar pagos pendientes
        if alertas.get('pagos_pendientes', False):
            try:
                notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
                pagos_pendientes = []
                for nota_id, nota in notas.items():
                    estado = nota.get('estado', '')
                    if estado in ['PENDIENTE_ENTREGA', 'PENDIENTE_PAGO']:
                        cliente_nombre = nota.get('cliente', {}).get('nombre', 'Sin nombre') if isinstance(nota.get('cliente'), dict) else nota.get('cliente', 'Sin nombre')
                        total = float(nota.get('total', 0))
                        pagos_pendientes.append({
                            'id': nota_id,
                            'cliente': cliente_nombre,
                            'total': total,
                            'estado': estado
                        })
                
                if pagos_pendientes:
                    total_pendiente = sum(p['total'] for p in pagos_pendientes)
                    alertas_activas.append({
                        'tipo': 'warning',
                        'titulo': 'Pagos Pendientes',
                        'mensaje': f"{len(pagos_pendientes)} nota(s) con pagos pendientes",
                        'icono': 'fas fa-money-bill-wave',
                        'cantidad': len(pagos_pendientes),
                        'total': total_pendiente,
                        'detalles': pagos_pendientes[:5]
                    })
            except Exception as e:
                print(f"Error verificando pagos pendientes: {e}")
        
        # 5. Verificar vencimiento de notas de entrega
        if alertas.get('vencimiento_notas_entrega', False):
            try:
                notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
                notas_vencidas = []
                notas_por_vencer = []
                
                for nota_id, nota in notas.items():
                    fecha_vencimiento = nota.get('fecha_vencimiento')
                    if fecha_vencimiento:
                        try:
                            fecha_venc = datetime.strptime(fecha_vencimiento, '%Y-%m-%d')
                            dias_restantes = (fecha_venc - ahora).days
                            cliente_nombre = nota.get('cliente', {}).get('nombre', 'Sin nombre') if isinstance(nota.get('cliente'), dict) else nota.get('cliente', 'Sin nombre')
                            
                            if dias_restantes < 0:
                                notas_vencidas.append({
                                    'id': nota_id,
                                    'cliente': cliente_nombre,
                                    'dias_vencida': abs(dias_restantes)
                                })
                            elif dias_restantes <= 3:  # Por vencer en 3 días
                                notas_por_vencer.append({
                                    'id': nota_id,
                                    'cliente': cliente_nombre,
                                    'dias_restantes': dias_restantes
                                })
                        except:
                            continue
                
                if notas_vencidas:
                    alertas_activas.append({
                        'tipo': 'danger',
                        'titulo': 'Notas de Entrega Vencidas',
                        'mensaje': f"{len(notas_vencidas)} nota(s) vencida(s)",
                        'icono': 'fas fa-calendar-times',
                        'cantidad': len(notas_vencidas),
                        'detalles': notas_vencidas[:5]
                    })
                
                if notas_por_vencer:
                    alertas_activas.append({
                        'tipo': 'warning',
                        'titulo': 'Notas por Vencer',
                        'mensaje': f"{len(notas_por_vencer)} nota(s) por vencer en los próximos 3 días",
                        'icono': 'fas fa-calendar-check',
                        'cantidad': len(notas_por_vencer),
                        'detalles': notas_por_vencer[:5]
                    })
            except Exception as e:
                print(f"Error verificando vencimiento notas: {e}")
        
        # 6. Verificar cuotas vencidas (en pagos a plazos)
        if alertas.get('cuotas_vencidas', False):
            try:
                notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
                cuotas_vencidas = []
                
                for nota_id, nota in notas.items():
                    pagos_programados = nota.get('pagos_programados', [])
                    if isinstance(pagos_programados, list):
                        for cuota in pagos_programados:
                            if isinstance(cuota, dict):
                                fecha_cuota = cuota.get('fecha')
                                pagado = cuota.get('pagado', False)
                                if fecha_cuota and not pagado:
                                    try:
                                        fecha_cuota_dt = datetime.strptime(fecha_cuota, '%Y-%m-%d')
                                        if fecha_cuota_dt < ahora:
                                            cliente_nombre = nota.get('cliente', {}).get('nombre', 'Sin nombre') if isinstance(nota.get('cliente'), dict) else nota.get('cliente', 'Sin nombre')
                                            cuotas_vencidas.append({
                                                'nota_id': nota_id,
                                                'cliente': cliente_nombre,
                                                'fecha': fecha_cuota,
                                                'monto': float(cuota.get('monto', 0))
                                            })
                                    except:
                                        continue
                
                if cuotas_vencidas:
                    total_vencido = sum(c['monto'] for c in cuotas_vencidas)
                    alertas_activas.append({
                        'tipo': 'danger',
                        'titulo': 'Cuotas Vencidas',
                        'mensaje': f"{len(cuotas_vencidas)} cuota(s) vencida(s)",
                        'icono': 'fas fa-calendar-exclamation',
                        'cantidad': len(cuotas_vencidas),
                        'total': total_vencido,
                        'detalles': cuotas_vencidas[:5]
                    })
            except Exception as e:
                print(f"Error verificando cuotas vencidas: {e}")
        
        # 7. Verificar órdenes pendientes
        if alertas.get('ordenes_pendientes', False):
            try:
                ordenes = cargar_datos('ordenes_servicio.json')
                ordenes_pend = []
                for orden_id, orden in ordenes.items():
                    estado = orden.get('estado', '')
                    if estado in ['recibida', 'en_diagnostico', 'pendiente']:
                        cliente_nombre = orden.get('cliente', {}).get('nombre', 'Sin nombre') if isinstance(orden.get('cliente'), dict) else 'Sin nombre'
                        ordenes_pend.append({
                            'id': orden_id,
                            'cliente': cliente_nombre,
                            'estado': estado,
                            'numero_orden': orden.get('numero_orden', orden_id)
                        })
                
                if ordenes_pend:
                    alertas_activas.append({
                        'tipo': 'info',
                        'titulo': 'Órdenes Pendientes',
                        'mensaje': f"{len(ordenes_pend)} orden(es) en espera",
                        'icono': 'fas fa-tools',
                        'cantidad': len(ordenes_pend),
                        'detalles': ordenes_pend[:5]
                    })
            except Exception as e:
                print(f"Error verificando órdenes pendientes: {e}")
        
        # 8. Verificar órdenes urgentes
        if alertas.get('ordenes_urgentes', False):
            try:
                ordenes = cargar_datos('ordenes_servicio.json')
                ordenes_urgentes = []
                for orden_id, orden in ordenes.items():
                    if orden.get('urgente', False) or orden.get('prioridad') == 'urgente':
                        cliente_nombre = orden.get('cliente', {}).get('nombre', 'Sin nombre') if isinstance(orden.get('cliente'), dict) else 'Sin nombre'
                        ordenes_urgentes.append({
                            'id': orden_id,
                            'cliente': cliente_nombre,
                            'numero_orden': orden.get('numero_orden', orden_id)
                        })
                
                if ordenes_urgentes:
                    alertas_activas.append({
                        'tipo': 'danger',
                        'titulo': 'Órdenes Urgentes',
                        'mensaje': f"{len(ordenes_urgentes)} orden(es) marcada(s) como urgente(s)",
                        'icono': 'fas fa-exclamation-triangle',
                        'cantidad': len(ordenes_urgentes),
                        'detalles': ordenes_urgentes[:5]
                    })
            except Exception as e:
                print(f"Error verificando órdenes urgentes: {e}")
        
        # 9. Verificar estados vencidos (órdenes que exceden tiempo máximo)
        if alertas.get('estados_vencidos', False):
            try:
                ordenes_vencidas = obtener_ordenes_estados_vencidos()
                if ordenes_vencidas:
                    alertas_activas.append({
                        'tipo': 'danger',
                        'titulo': 'Estados Vencidos',
                        'mensaje': f"{len(ordenes_vencidas)} orden(es) con estado vencido",
                        'icono': 'fas fa-hourglass-end',
                        'cantidad': len(ordenes_vencidas),
                        'detalles': ordenes_vencidas[:5]
                    })
            except Exception as e:
                print(f"Error verificando estados vencidos: {e}")
        
        # 10. Verificar cumpleaños de clientes (próximos 7 días)
        if alertas.get('cumpleanos_clientes', False):
            try:
                clientes = cargar_datos(ARCHIVO_CLIENTES)
                cumpleanos_proximos = []
                hoy = ahora.date()
                
                for cliente_id, cliente in clientes.items():
                    fecha_nacimiento = cliente.get('fecha_nacimiento') or cliente.get('cumpleanos')
                    if fecha_nacimiento:
                        try:
                            # Intentar diferentes formatos
                            try:
                                fecha_nac = datetime.strptime(fecha_nacimiento, '%Y-%m-%d').date()
                            except:
                                fecha_nac = datetime.strptime(fecha_nacimiento, '%d-%m-%Y').date()
                            
                            # Calcular cumpleaños este año
                            cumple_este_ano = fecha_nac.replace(year=hoy.year)
                            if cumple_este_ano < hoy:
                                cumple_este_ano = fecha_nac.replace(year=hoy.year + 1)
                            
                            dias_restantes = (cumple_este_ano - hoy).days
                            if 0 <= dias_restantes <= 7:
                                cumpleanos_proximos.append({
                                    'id': cliente_id,
                                    'nombre': cliente.get('nombre', 'Sin nombre'),
                                    'dias_restantes': dias_restantes,
                                    'fecha': cumple_este_ano.strftime('%Y-%m-%d')
                                })
                        except:
                            continue
                
                if cumpleanos_proximos:
                    alertas_activas.append({
                        'tipo': 'info',
                        'titulo': 'Cumpleaños Próximos',
                        'mensaje': f"{len(cumpleanos_proximos)} cliente(s) cumplen años en los próximos 7 días",
                        'icono': 'fas fa-birthday-cake',
                        'cantidad': len(cumpleanos_proximos),
                        'detalles': cumpleanos_proximos[:5]
                    })
            except Exception as e:
                print(f"Error verificando cumpleaños: {e}")
        
        # 11. Verificar clientes nuevos (últimos 7 días)
        if alertas.get('clientes_nuevos', False):
            try:
                clientes = cargar_datos(ARCHIVO_CLIENTES)
                clientes_nuevos = []
                hace_7_dias = ahora - timedelta(days=7)
                
                for cliente_id, cliente in clientes.items():
                    fecha_registro = cliente.get('fecha_registro') or cliente.get('fecha_creacion')
                    if fecha_registro:
                        try:
                            fecha_reg = datetime.strptime(fecha_registro, '%Y-%m-%d %H:%M:%S')
                            if fecha_reg >= hace_7_dias:
                                clientes_nuevos.append({
                                    'id': cliente_id,
                                    'nombre': cliente.get('nombre', 'Sin nombre'),
                                    'fecha': fecha_registro
                                })
                        except:
                            continue
                
                if clientes_nuevos:
                    alertas_activas.append({
                        'tipo': 'success',
                        'titulo': 'Clientes Nuevos',
                        'mensaje': f"{len(clientes_nuevos)} cliente(s) nuevo(s) en los últimos 7 días",
                        'icono': 'fas fa-user-plus',
                        'cantidad': len(clientes_nuevos),
                        'detalles': clientes_nuevos[:5]
                    })
            except Exception as e:
                print(f"Error verificando clientes nuevos: {e}")
        
        if alertas_activas:
            print("🔔 ALERTAS ACTIVAS:")
            for alerta in alertas_activas:
                print(f"  {alerta.get('icono', '📌')} {alerta.get('titulo', 'Alerta')}: {alerta.get('mensaje', '')}")
        else:
            print("✅ No hay alertas activas")
        
        return alertas_activas
        
    except Exception as e:
        print(f"❌ Error verificando alertas: {e}")
        import traceback
        traceback.print_exc()
        return []

if __name__ == '__main__':
    # Crear directorios necesarios
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(IMAGENES_PRODUCTOS_FOLDER, exist_ok=True)
    os.makedirs('facturas_json', exist_ok=True)
    os.makedirs('cotizaciones_json', exist_ok=True)
    os.makedirs('cotizaciones_pdf', exist_ok=True)
    os.makedirs('facturas_pdf', exist_ok=True)
    os.makedirs('documentos_fiscales', exist_ok=True)
    os.makedirs('exportaciones_seniat', exist_ok=True)
    os.makedirs('reportes_clientes', exist_ok=True)
    os.makedirs('reportes_cuentas', exist_ok=True)
    os.makedirs('logs', exist_ok=True)
    
    # Mostrar todas las rutas registradas
    print("Rutas disponibles:")
    for rule in app.url_map.iter_rules():
        print(f"  {rule.rule} -> {rule.endpoint}")
    print("Aplicacion iniciada correctamente")
    
    # Configuración para desarrollo local y producción en Render
    is_production = os.environ.get('FLASK_ENV') == 'production'
    
    if is_production:
        # Configuración para Render (producción)
        port = int(os.environ.get('PORT', 10000))
        host = '0.0.0.0'
        debug = False
        print(f"Iniciando servidor web en puerto {port} (Render)")
        app.run(host=host, port=port, debug=debug)
    else:
        # Configuración para desarrollo local
        print("Iniciando servidor web en http://127.0.0.1:5000")
        print("Presiona CTRL+C para detener el servidor")
        app.run(debug=True, host='127.0.0.1', port=5000)
