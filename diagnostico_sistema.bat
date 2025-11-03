@echo off
echo ========================================
echo  DIAGNOSTICO DEL SISTEMA
echo ========================================
echo.

python diagnostico_sistema.py

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ========================================
    echo  DIAGNOSTICO COMPLETADO
    echo ========================================
    echo.
    echo Todo esta correcto. Puedes ejecutar la aplicacion.
    echo.
) else (
    echo.
    echo ========================================
    echo  PROBLEMAS ENCONTRADOS
    echo ========================================
    echo.
    echo Revisa los mensajes arriba y corrige los problemas.
    echo Consulta GUIA_MIGRACION_PC.md para ayuda.
    echo.
)

pause

