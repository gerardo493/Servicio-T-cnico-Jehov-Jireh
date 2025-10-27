# 🚀 Deploy a Render - Guía Paso a Paso

## ✅ Tu Repositorio de GitHub:
🔗 https://github.com/gerardo493/Servicio-T-cnico-Jehov-Jireh

---

## 📝 PASO 1: Subir el Código a GitHub

### 1️⃣ Abre PowerShell en la carpeta del proyecto:

```powershell
cd C:\Users\G-FIVE\OneDrive\Escritorio\store
```

### 2️⃣ Configura Git (si no está configurado):

```bash
git config --global user.name "gerardo493"
git config --global user.email "tu-email@gmail.com"
```

### 3️⃣ Inicializa Git y Conecta con tu Repositorio:

```bash
# Inicializar Git
git init

# Agregar el remote (reemplaza con tu URL)
git remote add origin https://github.com/gerardo493/Servicio-T-cnico-Jehov-Jireh.git

# Verificar que está conectado
git remote -v
```

### 4️⃣ Agregar y Subir Archivos:

```bash
# Agregar todos los archivos
git add .

# Verificar qué archivos se agregaron
git status

# Crear commit inicial
git commit -m "Sistema completo de reparaciones - Deploy inicial"

# Subir a GitHub (reemplazar main por master si es necesario)
git branch -M main
git push -u origin main
```

**Si te pide credenciales:**
- Username: `gerardo493`
- Password: Usa un **Personal Access Token** (no tu contraseña normal)

**Para crear un Personal Access Token:**
1. Ve a: https://github.com/settings/tokens
2. Click "Generate new token (classic)"
3. Selecciona: `repo` (todos los permisos)
4. Genera y copia el token
5. Úsalo como contraseña al hacer push

---

## 🌐 PASO 2: Configurar Render

### 1️⃣ Ir a Render Dashboard:

🔗 https://dashboard.render.com

### 2️⃣ Crear Nuevo Web Service:

1. Click en **"New +"** (botón azul arriba)
2. Seleccionar **"Web Service"**

### 3️⃣ Conectar con GitHub:

1. Click **"Connect GitHub"**
2. Si es la primera vez:
   - Ingresa tus credenciales de GitHub
   - Autoriza a Render a acceder a tus repositorios
   - Acepta los permisos

### 4️⃣ Buscar tu Repositorio:

- En el buscador, escribe: `Servicio-T-cnico-Jehov-Jireh`
- O busca: `gerardo493`
- Selecciona: **`gerardo493/Servicio-T-cnico-Jehov-Jireh`**

### 5️⃣ Configurar el Servicio:

```
Name: servicio-tecnico-jehovah-jireh
Region: Oregon (US West)
Branch: main
Root Directory: (dejar vacío)
Runtime: Python 3
Build Command: pip install -r requirements.txt
Start Command: gunicorn app:app
```

### 6️⃣ Variables de Entorno:

Click en **"Advanced"** > **"Add Environment Variable"**

Agregar estas variables:

| Name | Value |
|------|-------|
| `FLASK_ENV` | `production` |
| `PORT` | `10000` |

### 7️⃣ Plan (Gratis):

- Seleccionar **"Free"**
- Scroll down
- Click **"Create Web Service"**

### 8️⃣ Esperar Deploy:

- ⏱️ Tiempo: 2-5 minutos
- Ver progreso en tiempo real en "Logs"
- Deberás ver:
  - ✅ `Build succeeded`
  - ✅ `Your service is live!`

---

## ✅ PASO 3: Verificar

### 1️⃣ URL de tu App:

```
https://servicio-tecnico-jehovah-jireh.onrender.com
```

*(El nombre exacto puede variar según lo que Render asigne)*

### 2️⃣ Probar:

1. Abre la URL en el navegador
2. Hacer login con tus credenciales
3. Verificar que todo funcione correctamente

---

## 🔄 ACTUALIZAR EN EL FUTURO

Cada vez que hagas cambios en tu código:

```bash
# En PowerShell (en la carpeta del proyecto)
git add .
git commit -m "Descripción de los cambios"
git push
```

Render detectará automáticamente los cambios y hará deploy en 2-5 minutos.

---

## ⚠️ IMPORTANTE: Sobre los Archivos JSON

### Problema:
Los archivos `.json` (clientes.json, inventario.json, etc.) **se perderán** cada vez que Render reinicie el servicio.

### Soluciones:

#### Opción 1: Base de Datos PostgreSQL (Recomendado)
- Render ofrece PostgreSQL gratuito
- Los datos se guardan permanentemente
- Mejor para producción

#### Opción 2: Persistir Archivos JSON
- Usar variables de entorno para credenciales
- Usar servicio de almacenamiento externo (S3, Dropbox, etc.)

#### Opción 3: Para Testing
- Puedes seguir usando archivos JSON
- Pero tendrás que re-cargar los datos cada vez que se reinicie

---

## 📞 Comandos Útiles

### Ver Logs en Render:
```
Dashboard > Logs (pestaña arriba)
```

### Reiniciar el Servicio:
```
Dashboard > Manual Deploy > Clear Build Cache & Deploy
```

### Ver Estado del Deploy:
```
Dashboard > Events (timeline de eventos)
```

---

## 🎯 RESUMEN DE PASOS

```
1. ✅ Abrir PowerShell en la carpeta
2. ✅ git init (si no existe)
3. ✅ git remote add origin [URL]
4. ✅ git add .
5. ✅ git commit -m "mensaje"
6. ✅ git push
7. ✅ Ir a dashboard.render.com
8. ✅ Crear Web Service
9. ✅ Conectar con GitHub
10. ✅ Seleccionar tu repo
11. ✅ Configurar variables
12. ✅ Deploy automático
13. ✅ ¡Listo!
```

---

## ✅ Verificación Final

- ✅ Código subido a GitHub
- ✅ Repositorio conectado con Render
- ✅ Build exitoso
- ✅ App funcionando
- ✅ Login funciona
- ✅ Todos los módulos funcionan

---

## 🚨 Si Algo Sale Mal

### Error de Autenticación Git:

```bash
# Crear Personal Access Token
1. https://github.com/settings/tokens
2. Generate new token
3. Seleccionar "repo"
4. Copiar el token
5. Usar como contraseña
```

### Build Falla en Render:

1. Ver logs en Render dashboard
2. Verificar que `requirements.txt` existe
3. Verificar que `Procfile` existe
4. Verificar que `app.py` existe

### App No Inicia:

1. Verificar variables de entorno
2. Ver logs para errores específicos
3. Verificar que no haya errores de código

---

## 🎉 ¡LISTO PARA DEPLOY!

Sigue estos pasos y tu sistema estará online en minutos.

**Tu URL será:**
```
https://servicio-tecnico-jehovah-jireh.onrender.com
```

*(O el nombre que Render asigne)*

¡Éxito con tu deploy! 🚀

