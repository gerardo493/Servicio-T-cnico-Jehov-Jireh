@echo off
echo ========================================
echo  DEPLOY AUTOMATICO A RENDER
echo ========================================
echo.

python deploy_render_completo.py

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ========================================
    echo  DEPLOY COMPLETADO EXITOSAMENTE
    echo ========================================
    pause
) else (
    echo.
    echo ========================================
    echo  ERROR EN EL DEPLOY
    echo ========================================
    pause
)
