# 📦 Guía para Construir el Ejecutable

Esta guía explica cómo crear un ejecutable standalone de la aplicación usando PyInstaller.

## 📋 Requisitos Previos

1. **Python 3.8+** instalado en tu PC de desarrollo
2. **Todas las dependencias** instaladas:
   ```bash
   pip install -r requirements.txt
   ```
   O instalar manualmente:
   ```bash
   pip install flask werkzeug flask-wtf qrcode pillow beautifulsoup4 requests pyinstaller
   ```

## 🚀 Método 1: Usar el Script de Build (Recomendado)

1. **Instalar PyInstaller**:
   ```bash
   pip install pyinstaller
   ```

2. **Ejecutar el script de build**:
   ```bash
   python build_exe.py
   ```

3. **El ejecutable estará en**: `dist/SistemaGestion/SistemaGestion.exe`

## 🛠️ Método 2: Usar el archivo .spec

1. **Instalar PyInstaller**:
   ```bash
   pip install pyinstaller
   ```

2. **Ejecutar PyInstaller con el archivo spec**:
   ```bash
   pyinstaller build.spec
   ```

3. **El ejecutable estará en**: `dist/SistemaGestion/SistemaGestion.exe`

## 📁 Estructura del Ejecutable

Después de construir, tendrás:

```
dist/
└── SistemaGestion/
    ├── SistemaGestion.exe  ← Ejecutable principal
    ├── templates/          ← Templates HTML
    ├── static/             ← Archivos estáticos (CSS, JS, imágenes)
    └── [otros archivos DLL y dependencias]
```

## ⚠️ IMPORTANTE: Archivos de Datos

**Los archivos JSON NO se incluyen en el ejecutable** (por diseño, para que sean modificables):

1. **Copia estos archivos** a la carpeta `dist/SistemaGestion/`:
   - `config_sistema.json`
   - `clientes.json` (si existe)
   - `inventario.json` (si existe)
   - `usuarios.json` (si existe)
   - `roles_usuarios.json` (si existe)
   - Cualquier otro archivo JSON que uses

2. **O déjalos vacíos**: El sistema los creará automáticamente cuando se ejecute por primera vez.

## 🎯 Distribución

Para distribuir la aplicación:

1. **Copia toda la carpeta** `dist/SistemaGestion/` a otra computadora
2. **Asegúrate de incluir**:
   - El ejecutable `SistemaGestion.exe`
   - La carpeta `templates/`
   - La carpeta `static/`
   - Los archivos JSON (o déjalos para que se creen automáticamente)

3. **Ejecuta** `SistemaGestion.exe` haciendo doble clic

## 🔧 Opciones de Build

### Modo con Consola (para debugging)
En `build.spec` o `build_exe.py`, cambia:
```python
console=True  # Muestra la consola al ejecutar
```

### Modo sin Consola (producción)
```python
console=False  # No muestra consola (recomendado para usuarios finales)
```

### Modo OneFile (un solo archivo)
En `build_exe.py`, cambia:
```python
'--onedir',  # Cambiar a:
'--onefile',  # Crea un solo .exe (más lento al iniciar)
```

## 📝 Notas

- **Primera ejecución**: Puede tardar 5-10 segundos en iniciar (PyInstaller descomprime en memoria)
- **Antivirus**: Algunos antivirus pueden marcar el .exe como sospechoso. Es normal, es un falso positivo.
- **Tamaño**: El ejecutable será grande (50-200 MB) porque incluye Python y todas las dependencias.
- **Rutas**: Los archivos JSON se guardan en la misma carpeta donde está el ejecutable.

## 🐛 Solución de Problemas

### Error: "No module named 'X'"
Agrega el módulo faltante a `hidden_imports` en `build.spec` o `build_exe.py`.

### Error: "Template not found"
Verifica que la carpeta `templates/` esté incluida con `--add-data`.

### Error: "Static files not found"
Verifica que la carpeta `static/` esté incluida con `--add-data`.

### El ejecutable no inicia
Ejecuta desde la consola para ver los errores:
```bash
cd dist/SistemaGestion
SistemaGestion.exe
```

## ✅ Verificación

Después de construir, verifica:

1. ✅ El ejecutable existe en `dist/SistemaGestion/`
2. ✅ Las carpetas `templates/` y `static/` están incluidas
3. ✅ Puedes ejecutar el .exe sin errores
4. ✅ La aplicación se abre en el navegador
5. ✅ Los archivos JSON se crean/leen correctamente

---

**¡Listo!** Tu aplicación está empaquetada y lista para distribuir. 🎉

