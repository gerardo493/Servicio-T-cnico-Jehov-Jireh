# 📦 Guía Completa para Migrar el Sistema a Otra PC

## 🎯 Problemas Comunes al Copiar el Sistema

Cuando copias los archivos del sistema a otra PC, generalmente falla porque:

1. ❌ **Dependencias no instaladas** - Python no tiene los paquetes necesarios
2. ❌ **Directorios faltantes** - Carpetas necesarias no existen
3. ❌ **Archivos JSON corruptos o faltantes** - Datos de configuración ausentes
4. ❌ **Python no instalado o versión incorrecta** - Requiere Python 3.8+
5. ❌ **Variables de entorno** - Configuraciones específicas del sistema
6. ❌ **Permisos de archivos** - Problemas de escritura/lectura

## ✅ Solución Rápida (Automática)

### Paso 1: Copiar TODOS los archivos

Asegúrate de copiar **TODA** la carpeta del proyecto, incluyendo:
```
store/
├── app.py
├── requirements.txt
├── templates/
├── static/
├── *.json (todos los archivos JSON)
├── *.py (todos los scripts Python)
└── ... (TODO el contenido)
```

### Paso 2: Ejecutar el Script de Instalación

#### En Windows:
```bash
# Opción 1: Doble clic
instalar_sistema.bat

# Opción 2: Desde PowerShell/CMD
python instalar_sistema.py
```

#### En Linux/Mac:
```bash
python3 instalar_sistema.py
```

### Paso 3: Verificar con Diagnóstico

```bash
# Verifica que todo esté correcto
python diagnostico_sistema.py
```

### Paso 4: Iniciar la Aplicación

```bash
python app.py
```

Luego abre: `http://localhost:5000`

---

## 📋 Solución Manual (Paso a Paso)

Si prefieres hacerlo manualmente o el script automático falla:

### 1. Verificar Python

```bash
python --version
# Debe ser Python 3.8 o superior
```

Si no tienes Python:
- **Windows**: https://www.python.org/downloads/
- **Linux**: `sudo apt install python3 python3-pip` (Ubuntu/Debian)
- **Mac**: Ya viene instalado, o usa Homebrew: `brew install python3`

### 2. Instalar Dependencias

```bash
# Actualizar pip
python -m pip install --upgrade pip

# Instalar todas las dependencias
pip install -r requirements.txt
```

Si hay errores, instala una por una:
```bash
pip install Flask==3.0.0
pip install Werkzeug==3.0.1
pip install requests==2.31.0
pip install beautifulsoup4==4.12.2
# ... etc
```

### 3. Crear Directorios Necesarios

```bash
# Windows (PowerShell)
mkdir static, static\uploads, static\imagenes_productos, templates, facturas_json, facturas_pdf, cotizaciones_json, cotizaciones_pdf, documentos_fiscales, uploads, logs, backups

# Linux/Mac
mkdir -p static/uploads static/imagenes_productos templates facturas_json facturas_pdf cotizaciones_json cotizaciones_pdf documentos_fiscales uploads logs backups
```

### 4. Crear Archivos JSON Faltantes

Si faltan archivos JSON, créalos con este contenido:

**clientes.json**
```json
{}
```

**inventario.json**
```json
{}
```

**usuarios.json**
```json
{}
```

**config_sistema.json** (si no existe)
```json
{
    "nombre_sistema": "Sistema de Gestión Técnica",
    "moneda_sistema": "USD",
    "tasa_actual_usd": 36.00,
    "tasa_actual_eur": 39.00,
    "ultima_actualizacion": "",
    "impuestos": {
        "iva": 16.0,
        "retencion_iva": 75.0
    }
}
```

**facturas_json/facturas.json**
```json
{}
```

**cotizaciones_json/cotizaciones.json**
```json
{}
```

**notas_entrega.json**
```json
{}
```

**proveedores.json**
```json
{}
```

### 5. Verificar Permisos (Linux/Mac)

```bash
# Dar permisos de lectura/escritura
chmod -R 755 .
chmod -R 777 uploads/ static/uploads/ logs/
```

### 6. Probar la Aplicación

```bash
python app.py
```

Deberías ver:
```
 * Running on http://127.0.0.1:5000
```

---

## 🔍 Diagnóstico de Problemas

### Error: "ModuleNotFoundError: No module named 'flask'"

**Solución:**
```bash
pip install Flask
# O reinstalar todas las dependencias
pip install -r requirements.txt
```

### Error: "FileNotFoundError: [Errno 2] No such file or directory: 'clientes.json'"

**Solución:**
- Ejecuta `instalar_sistema.py` para crear todos los archivos faltantes
- O crea manualmente los archivos JSON mencionados arriba

### Error: "Permission denied" (Linux/Mac)

**Solución:**
```bash
chmod -R 755 .
chmod -R 777 uploads/ logs/
```

### Error: "Address already in use" (Puerto 5000 ocupado)

**Solución:**
```bash
# Cambiar puerto
python app.py --port 5001

# O en Windows, matar el proceso que usa el puerto
netstat -ano | findstr :5000
taskkill /PID <PID> /F

# O en Linux/Mac
lsof -ti:5000 | xargs kill
```

### Error: "JSON decode error"

**Solución:**
- El archivo JSON está corrupto
- Elimínalo y ejecuta `instalar_sistema.py` para recrearlo
- O restáuralo desde un backup

### La aplicación inicia pero muestra errores en la interfaz

**Solución:**
1. Verifica que `templates/` y `static/` estén presentes
2. Verifica permisos de lectura en esos directorios
3. Revisa los logs: `logs/` o la consola donde ejecutaste `python app.py`

---

## 📦 Qué Archivos NO Necesitas Copiar

Estos archivos se generan automáticamente:

- ❌ `__pycache__/` - Caché de Python (se regenera)
- ❌ `*.pyc` - Archivos compilados de Python
- ❌ `venv/` o `env/` - Entorno virtual (instalar nuevo)
- ❌ `.git/` - Control de versiones (opcional)
- ❌ `logs/*.log` - Archivos de log (se regeneran)
- ❌ Archivos temporales

## ✅ Qué Archivos SÍ Debes Copiar

- ✅ `app.py` - Aplicación principal
- ✅ `requirements.txt` - Dependencias
- ✅ `templates/` - Plantillas HTML (TODO)
- ✅ `static/` - Archivos estáticos (TODO)
- ✅ `*.json` - Todos los archivos de datos
- ✅ `*.py` - Todos los scripts Python (excepto `__pycache__`)
- ✅ `Procfile` - Configuración para Render
- ✅ `config_sistema.json` - Configuración del sistema

---

## 🚀 Scripts de Ayuda Incluidos

### 1. `instalar_sistema.py`
Instalación automática completa:
- Crea directorios
- Crea archivos JSON
- Instala dependencias
- Verifica configuración

### 2. `diagnostico_sistema.py`
Diagnóstico completo del sistema:
- Verifica Python
- Verifica dependencias
- Verifica archivos y directorios
- Verifica configuración
- Muestra problemas encontrados

### 3. `deploy_render_completo.py`
Para subir cambios a Render (producción)

---

## 📝 Checklist de Migración

- [ ] Python 3.8+ instalado
- [ ] Todos los archivos del proyecto copiados
- [ ] Ejecutado `instalar_sistema.py`
- [ ] Ejecutado `diagnostico_sistema.py` (todo OK)
- [ ] Dependencias instaladas (`pip install -r requirements.txt`)
- [ ] Directorios creados
- [ ] Archivos JSON creados/verificados
- [ ] `config_sistema.json` existe y es válido
- [ ] La aplicación inicia sin errores
- [ ] Puedo acceder a `http://localhost:5000`
- [ ] Puedo crear un usuario administrador

---

## 💡 Recomendaciones

1. **Siempre usa el script de instalación** cuando copies a una nueva PC
2. **Mantén backups** de tus archivos JSON importantes
3. **Verifica con el diagnóstico** antes de usar el sistema
4. **Usa un entorno virtual** para evitar conflictos (opcional pero recomendado):
   ```bash
   python -m venv venv
   # Windows
   venv\Scripts\activate
   # Linux/Mac
   source venv/bin/activate
   pip install -r requirements.txt
   ```

---

## 🆘 Si Nada Funciona

1. Ejecuta el diagnóstico: `python diagnostico_sistema.py`
2. Revisa los errores mostrados
3. Compara con esta guía
4. Verifica que copiaste TODOS los archivos
5. Asegúrate de tener Python 3.8+
6. Reinstala las dependencias: `pip install -r requirements.txt --force-reinstall`

---

## 📞 Información Útil

**Estructura mínima requerida:**
```
tu-proyecto/
├── app.py                    ← OBLIGATORIO
├── requirements.txt          ← OBLIGATORIO
├── config_sistema.json       ← OBLIGATORIO
├── templates/               ← OBLIGATORIO
│   └── base.html
├── static/                  ← OBLIGATORIO
│   ├── css/
│   ├── js/
│   └── uploads/
├── clientes.json            ← Se crea automáticamente si falta
├── inventario.json          ← Se crea automáticamente si falta
└── usuarios.json            ← Se crea automáticamente si falta
```

**Comandos esenciales:**
```bash
# Instalación
python instalar_sistema.py

# Diagnóstico
python diagnostico_sistema.py

# Ejecutar aplicación
python app.py

# Instalar dependencias manualmente
pip install -r requirements.txt
```

---

**¡Listo! Con esta guía deberías poder migrar tu sistema a cualquier PC sin problemas. 🎉**

