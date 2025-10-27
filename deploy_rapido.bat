@echo off
chcp 65001 >nul
title DESPLEGADOR RAPIDO 2025

echo.
echo ========================================
echo    DESPLEGADOR RAPIDO 2025
echo ========================================
echo.

echo Iniciando despliegue automatico...
echo.

REM Activar entorno virtual y ejecutar script
call venv\Scripts\activate.bat
python deploy_auto.py

echo.
echo Presiona cualquier tecla para cerrar...
pause >nul
