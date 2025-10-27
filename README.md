# Sistema de Gestión Comercial

## Despliegue en Render

### Pasos para subir a Render:

1. **Crear cuenta en Render.com**
   - Ve a [render.com](https://render.com)
   - Regístrate con tu cuenta de GitHub

2. **Conectar tu repositorio**
   - Haz clic en "New +"
   - Selecciona "Web Service"
   - Conecta tu repositorio de GitHub

3. **Configuración automática**
   - Render detectará automáticamente que es una aplicación Python
   - Usará el archivo `requirements.txt` para instalar dependencias
   - Usará `gunicorn app:app` como comando de inicio

4. **Variables de entorno (opcional)**
   - Si necesitas configurar variables de entorno, agrégalas en la sección "Environment Variables"

5. **Desplegar**
   - Haz clic en "Create Web Service"
   - Render construirá y desplegará tu aplicación automáticamente

### Estructura de archivos necesarios:

- `app.py` - Tu aplicación Flask principal
- `requirements.txt` - Dependencias de Python
- `Procfile` - Comando de inicio para Render
- `runtime.txt` - Versión de Python
- `start.sh` - Script de inicio alternativo

### Notas importantes:

- Asegúrate de que tu aplicación Flask esté configurada para usar `$PORT` como puerto
- Los archivos estáticos deben estar en la carpeta `static/`
- Las plantillas deben estar en la carpeta `templates/`
- Render asignará automáticamente una URL pública a tu aplicación

### Comando de inicio recomendado:

```bash
gunicorn app:app --bind 0.0.0.0:$PORT
```

### Soporte:

Si tienes problemas con el despliegue, consulta la documentación de Render o revisa los logs de construcción.