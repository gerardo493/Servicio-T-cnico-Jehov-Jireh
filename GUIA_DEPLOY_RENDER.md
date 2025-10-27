# 🚀 Guía Completa para Subir a Render

## 📋 Requisitos Previos

1. **Cuenta en Render**: https://render.com
2. **Cuenta en GitHub**: https://github.com
3. **Git instalado** en tu computadora

---

## 🔧 PASO 1: Preparar Archivos para Render

### ✅ Archivos Necesarios (ya creados):

- ✅ `requirements.txt` - Dependencias de Python
- ✅ `Procfile` - Configuración de inicio
- ✅ `app.py` - Tu aplicación Flask
- ✅ `.gitignore` - Archivos a ignorar

### 📝 Verificar que app.py esté configurado para Render:

Agregar estas líneas al final de `app.py`:

```python
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
```

---

## 📤 PASO 2: Subir Código a GitHub

### 1️⃣ Inicializar Repositorio (si no existe):

```bash
git init
git add .
git commit -m "Deploy inicial a Render"
```

### 2️⃣ Crear Repositorio en GitHub:

1. Ve a https://github.com/new
2. Nombre: `tu-sistema-reparaciones` (o el que prefieras)
3. Clic en "Create repository"

### 3️⃣ Conectar y Subir:

```bash
git remote add origin https://github.com/TU-USUARIO/tu-sistema-reparaciones.git
git branch -M main
git push -u origin main
```

---

## 🌐 PASO 3: Crear Servicio en Render

### 1️⃣ Ir a Render Dashboard:

- URL: https://dashboard.render.com

### 2️⃣ Click en "New +"

- Seleccionar **"Web Service"**

### 3️⃣ Conectar GitHub:

- Click en **"Connect GitHub"**
- Autorizar Render a acceder a tus repositorios
- Seleccionar el repositorio: `tu-sistema-reparaciones`

### 4️⃣ Configurar el Servicio:

**Nombre:**
```
sistema-reparaciones
```

**Region:** 
```
Oregon (USA)
```

**Branch:**
```
main
```

**Root Directory:**
```
(Dejar vacío)
```

**Runtime:**
```
Python 3
```

**Build Command:**
```
pip install -r requirements.txt
```

**Start Command:**
```
gunicorn app:app
```

### 5️⃣ Variables de Entorno (Environment Variables):

Agregar estas variables (click en "Add Environment Variable"):

```
PORT=10000
FLASK_ENV=production
```

### 6️⃣ Deploy:

- Click en **"Create Web Service"**
- Esperar 2-5 minutos mientras construye
- Ver logs en tiempo real

---

## 🎯 PASO 4: Configurar para Producción

### 1️⃣ Cambiar app.py para Render:

En `app.py`, modifica el final:

```python
if __name__ == '__main__':
    # Configuración para Render
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') != 'production'
    
    app.run(
        host='0.0.0.0',
        port=port,
        debug=debug
    )
```

### 2️⃣ Agregar .gitignore (si no existe):

Crear archivo `.gitignore`:

```
__pycache__/
*.pyc
*.pyo
*.log
env/
venv/
.env
*.db
uploads/
backups/
*.zip
.DS_Store
```

---

## 🚀 PASO 5: Deploy Automático

Render detectará cambios automáticamente cuando hagas `git push`.

### Cada vez que actualices:

```bash
git add .
git commit -m "Descripción de cambios"
git push
```

Render desplegará automáticamente en 2-5 minutos.

---

## 🛠️ Comandos Útiles

### Ver logs en Render:
```
Dashboard > Web Service > Logs
```

### Redirigir dominio personalizado:
```
Dashboard > Web Service > Custom Domains
```

### Ver Estado del Deploy:
```
Dashboard > Web Service > Events
```

### Reiniciar el servicio:
```
Dashboard > Web Service > Manual Deploy > Clear Build Cache & Deploy
```

---

## ⚠️ Consideraciones Importantes

### 1️⃣ **Archivos JSON se guardan en memoria**:
- En Render, los archivos `.json` se reinician cada vez que se reinicia el servicio
- **Solución**: Usar base de datos (PostgreSQL) o servicio de almacenamiento

### 2️⃣ **Variación de tiempo esperado**:
- Render usa "sleep" después de 15 minutos de inactividad
- Tiempo de arranque: ~30 segundos
- Puedes usar plan pago para mantener activo 24/7

### 3️⃣ **Puerto dinámico**:
- Render asigna un puerto dinámico
- Usa `os.environ.get('PORT', 5000)`

### 4️⃣ **Archivos estáticos**:
- Render sirve archivos en `static/` automáticamente
- No necesitas configuración especial

---

## 🎯 Resumen Rápido

1. ✅ **Modifica app.py** (al final, agregar configuración de Render)
2. ✅ **Sube a GitHub** (`git push`)
3. ✅ **Crea servicio en Render** (conectar GitHub)
4. ✅ **Configura variables** (PORT, FLASK_ENV)
5. ✅ **Deploy automático** (cada push)

---

## 📞 URLs Finales

- **Dashboard**: https://dashboard.render.com
- **Tu App**: `https://sistema-reparaciones.onrender.com`
- **Logs**: Dashboard > Web Service > Logs

---

## ✅ Verificación Final

1. ✅ Código subido a GitHub
2. ✅ Servicio creado en Render
3. ✅ Build exitoso
4. ✅ App funcionando
5. ✅ Logs sin errores

