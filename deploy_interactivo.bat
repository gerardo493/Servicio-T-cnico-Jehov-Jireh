@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

:menu_principal
cls
echo.
echo ╔══════════════════════════════════════════════════════════════╗
echo ║                    🚀 DEPLOY INTERACTIVO                     ║
echo ║                     Sistema de Recordatorios                 ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.
echo 📁 Directorio actual: %CD%
echo.
echo 🔍 Verificando estado del sistema...
echo.

REM Verificar Git
git --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Git no está instalado
    echo    Por favor instala Git desde: https://git-scm.com/
    pause
    exit /b 1
)

REM Verificar si estamos en un repositorio Git
git status >nul 2>&1
if errorlevel 1 (
    echo ❌ No estás en un repositorio Git
    echo    Navega al directorio de tu proyecto Git
    pause
    exit /b 1
)

REM Verificar repositorio remoto
git remote get-url origin >nul 2>&1
if errorlevel 1 (
    echo ❌ No hay repositorio remoto configurado
    echo    Configura con: git remote add origin URL
    pause
    exit /b 1
)

echo ✅ Sistema verificado correctamente
echo.

:menu_opciones
echo ╔══════════════════════════════════════════════════════════════╗
echo ║                        📋 OPCIONES                           ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.
echo 1️⃣  🔍 Ver estado del repositorio
echo 2️⃣  📝 Hacer commit de cambios
echo 3️⃣  🚀 Hacer push al repositorio
echo 4️⃣  🔄 Deploy completo (commit + push)
echo 5️⃣  📊 Ver información del proyecto
echo 6️⃣  🧹 Limpiar archivos temporales
echo 7️⃣  🔧 Configuración avanzada
echo 8️⃣  ❌ Salir
echo.
echo ═══════════════════════════════════════════════════════════════
echo.

set /p opcion="Selecciona una opción (1-8): "

if "%opcion%"=="1" goto ver_estado
if "%opcion%"=="2" goto hacer_commit
if "%opcion%"=="3" goto hacer_push
if "%opcion%"=="4" goto deploy_completo
if "%opcion%"=="5" goto ver_informacion
if "%opcion%"=="6" goto limpiar_temporales
if "%opcion%"=="7" goto configuracion_avanzada
if "%opcion%"=="8" goto salir
goto opcion_invalida

:ver_estado
cls
echo.
echo ╔══════════════════════════════════════════════════════════════╗
echo ║                    🔍 ESTADO DEL REPOSITORIO                 ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.

echo 📊 Estado general:
git status
echo.

echo 📋 Cambios detallados:
git status --porcelain
echo.

echo 🌿 Rama actual:
git branch --show-current
echo.

echo 🔗 Repositorio remoto:
git remote -v
echo.

echo 📝 Últimos commits:
git log --oneline -5
echo.

echo ═══════════════════════════════════════════════════════════════
echo.
set /p continuar="Presiona Enter para continuar..."
goto menu_principal

:hacer_commit
cls
echo.
echo ╔══════════════════════════════════════════════════════════════╗
echo ║                    📝 HACER COMMIT                           ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.

REM Verificar si hay cambios
git status --porcelain > temp_status.txt
set /p status_content=<temp_status.txt
del temp_status.txt

if "%status_content%"=="" (
    echo ✅ No hay cambios pendientes para hacer commit
    echo.
    set /p continuar="Presiona Enter para continuar..."
    goto menu_principal
)

echo 📝 Cambios detectados:
git status --short
echo.

echo ═══════════════════════════════════════════════════════════════
echo.

:seleccionar_archivos
echo 🔍 ¿Qué archivos quieres incluir en el commit?
echo.
echo 1️⃣  📁 Todos los archivos modificados
echo 2️⃣  📄 Seleccionar archivos específicos
echo 3️⃣  🔙 Volver al menú principal
echo.
set /p seleccion="Selecciona opción (1-3): "

if "%seleccion%"=="1" goto commit_todos
if "%seleccion%"=="2" goto commit_selectivo
if "%seleccion%"=="3" goto menu_principal
goto seleccion_invalida

:commit_todos
echo.
echo 🔄 Agregando todos los archivos...
git add .
echo ✅ Archivos agregados al staging
goto mensaje_commit

:commit_selectivo
echo.
echo 📄 Archivos disponibles:
git status --short
echo.
echo 💡 Escribe los nombres de los archivos separados por espacios
echo    Ejemplo: app.py templates/factura_dashboard.html
echo.
set /p archivos="Archivos a incluir: "
if "%archivos%"=="" (
    echo ❌ No se especificaron archivos
    goto commit_selectivo
)
git add %archivos%
echo ✅ Archivos agregados al staging

:mensaje_commit
echo.
echo ═══════════════════════════════════════════════════════════════
echo.
echo 📝 TIPO DE COMMIT:
echo.
echo 1️⃣  🆕 Nueva funcionalidad
echo 2️⃣  🐛 Corrección de bug
echo 3️⃣  📚 Documentación
echo 4️⃣  🎨 Mejoras en interfaz
echo 5️⃣  ⚡ Optimización
echo 6️⃣  🔧 Mantenimiento
echo 7️⃣  📝 Mensaje personalizado
echo.
set /p tipo_commit="Selecciona tipo (1-7): "

if "%tipo_commit%"=="1" set prefix=🆕
if "%tipo_commit%"=="2" set prefix=🐛
if "%tipo_commit%"=="3" set prefix=📚
if "%tipo_commit%"=="4" set prefix=🎨
if "%tipo_commit%"=="5" set prefix=⚡
if "%tipo_commit%"=="6" set prefix=🔧
if "%tipo_commit%"=="7" set prefix=📝

if "%tipo_commit%"=="7" (
    echo.
    set /p mensaje_personal="Escribe tu mensaje personalizado: "
    set commit_message=!mensaje_personal!
) else (
    echo.
    set /p descripcion="Describe brevemente los cambios: "
    set commit_message=!prefix! !descripcion!
)

echo.
echo 📝 Mensaje del commit: !commit_message!
echo.
set /p confirmar="¿Confirmar commit? (s/n): "
if /i "!confirmar!"=="s" (
    git commit -m "!commit_message!"
    if errorlevel 1 (
        echo ❌ Error realizando commit
    ) else (
        echo ✅ Commit realizado exitosamente
    )
) else (
    echo ❌ Commit cancelado
)

echo.
set /p continuar="Presiona Enter para continuar..."
goto menu_principal

:hacer_push
cls
echo.
echo ╔══════════════════════════════════════════════════════════════╗
echo ║                    🚀 HACER PUSH                             ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.

echo 🌿 Rama actual:
git branch --show-current
echo.

echo 🔗 Repositorio remoto:
git remote -v
echo.

echo ═══════════════════════════════════════════════════════════════
echo.

echo 🚀 ¿A qué rama quieres hacer push?
echo.
echo 1️⃣  🌿 Rama actual (recomendado)
echo 2️⃣  🆕 Rama específica
echo 3️⃣  🔙 Volver al menú principal
echo.
set /p push_opcion="Selecciona opción (1-3): "

if "%push_opcion%"=="1" goto push_rama_actual
if "%push_opcion%"=="2" goto push_rama_especifica
if "%push_opcion%"=="3" goto menu_principal
goto opcion_invalida

:push_rama_actual
for /f "tokens=*" %%i in ('git branch --show-current') do set current_branch=%%i
echo.
echo 🚀 Haciendo push a la rama: !current_branch!
echo.
git push origin !current_branch!
if errorlevel 1 (
    echo ❌ Error en el push
    echo 💡 Intenta hacer pull primero: git pull origin !current_branch!
) else (
    echo ✅ Push realizado exitosamente
    echo.
    echo 🎉 ¡Deploy iniciado en Render!
    echo ⏱️  El despliegue puede tomar 2-5 minutos
    echo 🌐 Verifica en: https://dashboard.render.com/web/srv-d2ckh46r433s73appvug
)
goto continuar_push

:push_rama_especifica
echo.
set /p rama_especifica="Nombre de la rama: "
if "!rama_especifica!"=="" (
    echo ❌ No se especificó rama
    goto hacer_push
)
echo.
echo 🚀 Haciendo push a la rama: !rama_especifica!
echo.
git push origin !rama_especifica!
if errorlevel 1 (
    echo ❌ Error en el push
) else (
    echo ✅ Push realizado exitosamente
)

:continuar_push
echo.
set /p continuar="Presiona Enter para continuar..."
goto menu_principal

:deploy_completo
cls
echo.
echo ╔══════════════════════════════════════════════════════════════╗
echo ║                    🔄 DEPLOY COMPLETO                        ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.

echo 🔍 Verificando cambios pendientes...
git status --porcelain > temp_status.txt
set /p status_content=<temp_status.txt
del temp_status.txt

if "%status_content%"=="" (
    echo ✅ No hay cambios pendientes
    echo.
    set /p continuar="Presiona Enter para continuar..."
    goto menu_principal
)

echo 📝 Cambios detectados:
git status --short
echo.

echo ═══════════════════════════════════════════════════════════════
echo.

echo 🚀 ¿Quieres proceder con el deploy completo?
echo.
echo 1️⃣  ✅ Sí, hacer deploy completo
echo 2️⃣  ❌ No, cancelar
echo.
set /p confirmar_deploy="Selecciona opción (1-2): "

if "%confirmar_deploy%"=="1" (
    echo.
    echo 🔄 Iniciando deploy completo...
    echo.
    
    REM Hacer commit automático
    echo 📝 Haciendo commit automático...
    git add .
    git commit -m "🚀 Deploy automático - %date% %time%"
    if errorlevel 1 (
        echo ❌ Error en commit automático
        goto continuar_deploy
    )
    echo ✅ Commit realizado
    
    REM Hacer push
    echo 🚀 Haciendo push...
    for /f "tokens=*" %%i in ('git branch --show-current') do set current_branch=%%i
    git push origin !current_branch!
    if errorlevel 1 (
        echo ❌ Error en push
    ) else (
        echo ✅ Push realizado exitosamente
        echo.
        echo 🎉 ¡Deploy completado exitosamente!
        echo ⏱️  Render se está desplegando (2-5 minutos)
        echo 🌐 Verifica en: https://dashboard.render.com/web/srv-d2ckh46r433s73appvug
    )
) else (
    echo ❌ Deploy cancelado
)

:continuar_deploy
echo.
set /p continuar="Presiona Enter para continuar..."
goto menu_principal

:ver_informacion
cls
echo.
echo ╔══════════════════════════════════════════════════════════════╗
echo ║                    📊 INFORMACIÓN DEL PROYECTO               ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.

echo 🏢 Nombre del proyecto: Sistema de Recordatorios
echo 📁 Directorio: %CD%
echo.

echo 🔗 Repositorio:
git remote get-url origin
echo.

echo 🌿 Rama actual:
git branch --show-current
echo.

echo 📝 Último commit:
git log -1 --oneline
echo.

echo 📅 Fecha del último commit:
git log -1 --format="%cd" --date=short
echo.

echo 👤 Autor del último commit:
git log -1 --format="%an"
echo.

echo 📊 Estadísticas del repositorio:
echo    - Total de commits: 
git rev-list --count HEAD
echo    - Archivos modificados: 
git status --porcelain | find /c /v ""
echo.

echo 🌐 URLs importantes:
echo    - Dashboard Render: https://dashboard.render.com/web/srv-d2ckh46r433s73appvug
echo    - Aplicación: https://tu-app.onrender.com
echo.

echo ═══════════════════════════════════════════════════════════════
echo.
set /p continuar="Presiona Enter para continuar..."
goto menu_principal

:limpiar_temporales
cls
echo.
echo ╔══════════════════════════════════════════════════════════════╗
echo ║                    🧹 LIMPIAR TEMPORALES                     ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.

echo 🗑️ Archivos temporales detectados:
echo.

if exist "*.log" (
    echo 📄 Archivos de log:
    dir *.log /b
    echo.
)

if exist "__pycache__" (
    echo 🐍 Directorios Python:
    dir __pycache__ /s /b
    echo.
)

if exist "*.pyc" (
    echo 🐍 Archivos Python compilados:
    dir *.pyc /b
    echo.
)

if exist "temp_status.txt" (
    echo 📝 Archivos de estado:
    dir temp_status.txt /b
    echo.
)

echo ═══════════════════════════════════════════════════════════════
echo.

echo 🧹 ¿Quieres limpiar estos archivos?
echo.
echo 1️⃣  ✅ Sí, limpiar todo
echo 2️⃣  📄 Solo archivos de log
echo 3️⃣  🐍 Solo archivos Python
echo 4️⃣  ❌ No limpiar
echo.
set /p limpiar_opcion="Selecciona opción (1-4): "

if "%limpiar_opcion%"=="1" (
    echo.
    echo 🧹 Limpiando todos los archivos temporales...
    if exist "*.log" del *.log
    if exist "__pycache__" rmdir /s /q __pycache__
    if exist "*.pyc" del *.pyc
    if exist "temp_status.txt" del temp_status.txt
    echo ✅ Limpieza completada
) else if "%limpiar_opcion%"=="2" (
    echo.
    echo 📄 Limpiando archivos de log...
    if exist "*.log" del *.log
    echo ✅ Archivos de log eliminados
) else if "%limpiar_opcion%"=="3" (
    echo.
    echo 🐍 Limpiando archivos Python...
    if exist "__pycache__" rmdir /s /q __pycache__
    if exist "*.pyc" del *.pyc
    echo ✅ Archivos Python eliminados
) else (
    echo ❌ Limpieza cancelada
)

echo.
set /p continuar="Presiona Enter para continuar..."
goto menu_principal

:configuracion_avanzada
cls
echo.
echo ╔══════════════════════════════════════════════════════════════╗
echo ║                    🔧 CONFIGURACIÓN AVANZADA                 ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.

echo 🔧 Opciones avanzadas:
echo.
echo 1️⃣  📋 Ver configuración de Git
echo 2️⃣  🔄 Cambiar rama
echo 3️⃣  📥 Hacer pull del repositorio
echo 4️⃣  🔀 Ver historial de commits
echo 5️⃣  🗑️ Resetear último commit
echo 6️⃣  🔙 Volver al menú principal
echo.
set /p config_opcion="Selecciona opción (1-6): "

if "%config_opcion%"=="1" goto ver_config_git
if "%config_opcion%"=="2" goto cambiar_rama
if "%config_opcion%"=="3" goto hacer_pull
if "%config_opcion%"=="4" goto ver_historial
if "%config_opcion%"=="5" goto resetear_commit
if "%config_opcion%"=="6" goto menu_principal
goto opcion_invalida

:ver_config_git
echo.
echo 📋 Configuración de Git:
echo.
git config --list
echo.
set /p continuar="Presiona Enter para continuar..."
goto configuracion_avanzada

:cambiar_rama
echo.
echo 🌿 Ramas disponibles:
git branch -a
echo.
set /p nueva_rama="Nombre de la rama a cambiar: "
if "!nueva_rama!"=="" (
    echo ❌ No se especificó rama
    goto configuracion_avanzada
)
git checkout !nueva_rama!
if errorlevel 1 (
    echo ❌ Error cambiando rama
) else (
    echo ✅ Rama cambiada a: !nueva_rama!
)
echo.
set /p continuar="Presiona Enter para continuar..."
goto configuracion_avanzada

:hacer_pull
echo.
echo 📥 Haciendo pull del repositorio...
git pull
if errorlevel 1 (
    echo ❌ Error en pull
) else (
    echo ✅ Pull realizado exitosamente
)
echo.
set /p continuar="Presiona Enter para continuar..."
goto configuracion_avanzada

:ver_historial
echo.
echo 🔀 Historial de commits (últimos 10):
echo.
git log --oneline -10
echo.
set /p continuar="Presiona Enter para continuar..."
goto configuracion_avanzada

:resetear_commit
echo.
echo ⚠️  ADVERTENCIA: Esto eliminará el último commit
echo.
set /p confirmar_reset="¿Estás seguro? (s/n): "
if /i "!confirmar_reset!"=="s" (
    git reset --soft HEAD~1
    echo ✅ Último commit reseteado
) else (
    echo ❌ Reset cancelado
)
echo.
set /p continuar="Presiona Enter para continuar..."
goto configuracion_avanzada

:opcion_invalida
echo.
echo ❌ Opción inválida. Por favor selecciona una opción válida.
echo.
set /p continuar="Presiona Enter para continuar..."
goto menu_principal

:seleccion_invalida
echo.
echo ❌ Selección inválida. Por favor selecciona una opción válida.
echo.
set /p continuar="Presiona Enter para continuar..."
goto hacer_commit

:salir
cls
echo.
echo ╔══════════════════════════════════════════════════════════════╗
echo ║                        👋 ¡HASTA LUEGO!                      ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.
echo 🎉 Gracias por usar el Deploy Interactivo
echo 🚀 ¡Que tengas un excelente deploy!
echo.
echo 🌐 Recuerda verificar tu aplicación en:
echo    https://tu-app.onrender.com
echo.
pause
exit /b 0
