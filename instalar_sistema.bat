@echo off
echo ========================================
echo  INSTALACION DEL SISTEMA
echo ========================================
echo.
echo Este script configurara todo lo necesario
echo para ejecutar la aplicacion en esta PC.
echo.
pause

python instalar_sistema.py

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ========================================
    echo  INSTALACION COMPLETADA
    echo ========================================
    echo.
    echo Ahora puedes ejecutar:
    echo   1. diagnostico_sistema.py (para verificar)
    echo   2. app.py (para iniciar la aplicacion)
    echo.
    pause
) else (
    echo.
    echo ========================================
    echo  ERROR EN LA INSTALACION
    echo ========================================
    echo.
    echo Revisa los mensajes de error arriba.
    echo Consulta GUIA_MIGRACION_PC.md para ayuda.
    echo.
    pause
)

