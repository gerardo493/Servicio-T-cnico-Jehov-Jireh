@echo off
echo ============================================================
echo    DEPLOY A RENDER - Sistema Jehovah Jireh
echo ============================================================
echo.

echo [1/6] Verificando Git...
git --version
if %errorlevel% neq 0 (
    echo ERROR: Git no esta instalado
    pause
    exit /b 1
)
echo OK: Git instalado
echo.

echo [2/6] Cambiando remote a Jehovah Jireh...
git remote remove origin
git remote add origin https://github.com/gerardo493/Servicio-T-cnico-Jehov-Jireh.git
echo OK: Remote configurado
echo.

echo [3/6] Agregando archivos nuevos...
git add .
echo OK: Archivos agregados
echo.

echo [4/6] Verificando estado...
git status
echo.

echo ============================================================
echo    Preparado para hacer commit y push
echo ============================================================
echo.
echo PRÓXIMOS PASOS:
echo.
echo 1. Hacer commit:
echo    git commit -m "Sistema completo Jehovah Jireh"
echo.
echo 2. Subir a GitHub:
echo    git push -u origin main
echo.
echo 3. Si aparece error de rama:
echo    git branch -M main
echo    git push -u origin main
echo.
echo 4. Ir a Render:
echo    https://dashboard.render.com
echo.
echo 5. Crear nuevo Web Service
echo.
echo Presiona cualquier tecla para continuar...
pause
echo.

echo [5/6] Creando commit...
set /p commit_msg="Mensaje del commit (Enter para automatico): "
if "%commit_msg%"=="" (
    set commit_msg=Sistema completo Jehovah Jireh - Deploy inicial
)
git commit -m "%commit_msg%"
echo.

echo [6/6] Subiendo a GitHub...
git branch -M main 2>nul
git push -u origin main
echo.

echo ============================================================
echo    DEPLOY COMPLETADO
echo ============================================================
echo.
echo Siguiente paso:
echo 1. Ir a: https://dashboard.render.com
echo 2. Crear nuevo Web Service
echo 3. Conectar con GitHub
echo 4. Seleccionar: Servicio-T-cnico-Jehov-Jireh
echo.
echo Documentacion completa en:
echo - deploy_github_render.md
echo - GUIA_DEPLOY_RENDER.md
echo.
pause

