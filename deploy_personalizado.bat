@echo off
chcp 65001 >nul
title DESPLEGADOR PERSONALIZADO 2025

echo.
echo ========================================
echo DESPLEGADOR PERSONALIZADO 2025
echo ========================================
echo.

set /p mensaje="Ingresa el mensaje del commit: "

if "%mensaje%"=="" (
    echo No se ingreso mensaje, usando mensaje automatico...
    set mensaje="Actualizacion automatica"
)

echo.
echo Mensaje del commit: %mensaje%
echo.

REM Activar entorno virtual y ejecutar script
call venv\Scripts\activate.bat
python deploy_auto.py "%mensaje%"

echo.
echo Presiona cualquier tecla para cerrar...
pause >nul
