# 🚀 INSTRUCCIONES PARA SUBIR A RENDER

## 📋 ANTES DE COMENZAR

### ✅ Requisitos:
1. ✅ Cuenta en GitHub (https://github.com)
2. ✅ Cuenta en Render (https://render.com) 
3. ✅ Git instalado en tu PC

---

## 🔧 PASO 1: Preparar GitHub

### 1️⃣ Crear Repositorio en GitHub:

1. Ve a: https://github.com/new
2. Nombre: `sistema-reparaciones` (o el que prefieras)
3. **Descripción**: Sistema de Gestión de Reparaciones
4. ✅ Marcar **Public** (para el plan gratis)
5. ✅ Marcar **Add README**
6. Click **"Create repository"**

### 2️⃣ Subir tu Código Local a GitHub:

**Abre PowerShell o CMD en la carpeta del proyecto:**

```bash
# Inicializar Git (si no está iniciado)
git init

# Agregar todos los archivos
git add .

# Crear commit inicial
git commit -m "Sistema de reparaciones completo"

# Conectar con GitHub (reemplaza TU-USUARIO con tu usuario)
git remote add origin https://github.com/TU-USUARIO/sistema-reparaciones.git

# Cambiar a rama main
git branch -M main

# Subir a GitHub
git push -u origin main
```

---

## 🌐 PASO 2: Configurar en Render

### 1️⃣ Ir a Render:

- URL: https://dashboard.render.com
- Hacer login o crear cuenta

### 2️⃣ Crear Nuevo Servicio:

1. Click en **"New +"** (parte superior)
2. Seleccionar **"Web Service"**

### 3️⃣ Conectar GitHub:

1. Click en **"Connect account"**
2. Ingresa tus credenciales de GitHub
3. Autoriza a Render
4. Regresar a Render dashboard

### 4️⃣ Seleccionar Repositorio:

1. Click en **"Web Service"**
2. En "Repository", seleccionar tu repo: `sistema-reparaciones`
3. Auto-fill correcto:
   - **Name**: `sistema-reparaciones`
   - **Region**: `Oregon (US West)`
   - **Branch**: `main`
   - **Root Directory**: *(vacío)*
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`

### 5️⃣ Configurar Variables de Entorno:

Click en **"Add Environment Variable"** y agrega:

```
Name: FLASK_ENV
Value: production

Name: PORT  
Value: 10000
```

### 6️⃣ Deploy:

1. Scroll down
2. Click **"Create Web Service"**
3. **Esperar 2-5 minutos** mientras construye
4. Ver progreso en tiempo real en la pestaña "Logs"

---

## ✅ PASO 3: Verificar Deploy

### 1️⃣ Esperar Build Exitoso:

- Deberás ver: `✅ Build succeeded`
- Deberás ver: `Your service is live!`
- URL será: `https://sistema-reparaciones.onrender.com`

### 2️⃣ Probar la Aplicación:

1. Abrir la URL en el navegador
2. Hacer login con tus credenciales
3. Verificar que todo funcione

---

## 🔄 ACTUALIZAR EN EL FUTURO

Cada vez que hagas cambios:

```bash
# En la carpeta del proyecto
git add .
git commit -m "Descripción de cambios"
git push
```

Render detectará los cambios y hará deploy automáticamente.

---

## ⚙️ CONFIGURACIONES IMPORTANTES

### Para Cambiar Variables:

1. Dashboard > Web Service > Environment
2. Click en las variables para editarlas
3. Guardar cambios

### Para Ver Logs:

1. Dashboard > Web Service > Logs
2. Ver logs en tiempo real

### Para Reiniciar:

1. Dashboard > Web Service > Manual Deploy
2. Click "Clear Build Cache & Deploy"

---

## 📝 NOTAS IMPORTANTES

### ⚠️ Archivos JSON en Render:

- Los archivos `.json` se perderán cuando el servicio se reinicie
- **Solución**: Usar base de datos PostgreSQL (plan pago) o Redis
- Para testing, puedes seguir usando archivos JSON

### ⚠️ Plan Gratuito:

- El servicio entra en "sleep" después de 15 minutos sin uso
- Primer request despierta el servicio en ~30 segundos
- Plan pago ($7/mes) mantiene el servicio activo 24/7

### ⚠️ Límites del Plan Gratuito:

- 750 horas/mes de ejecución
- 100GB de ancho de banda
- Memoria: 512MB RAM
- Sufficient para este sistema

---

## 🎯 RESUMEN RÁPIDO

```
1. Crear repo en GitHub
2. git push (subir código)
3. Ir a Render dashboard
4. Crear Web Service
5. Conectar con GitHub
6. Configurar variables
7. Deploy automático
8. Esperar 2-5 minutos
9. ¡Listo! 🎉
```

---

## 📞 AYUDA

### Problemas Comunes:

**Build Fallando:**
- Verificar que `requirements.txt` exista
- Verificar que `Procfile` exista
- Ver logs en Render dashboard

**App no inicia:**
- Verificar variables de entorno
- Ver logs para errores específicos
- Verificar que `app.py` tenga la configuración correcta

**Archivos no se guardan:**
- Usar PostgreSQL para producción
- Los archivos `.json` se pierden con cada deploy

---

## 🚀 ¡LISTO PARA DEPLOY!

Sigue estos pasos y tu sistema estará online en minutos.

**¿Dudas?** Revisa los logs en Render dashboard.

**¡Éxito con tu deploy! 🎉**

