@echo off
echo ========================================
echo INSTALANDO DEPENDENCIAS PARA PDF
echo ========================================

echo.
echo Instalando weasyprint (recomendado para Windows)...
pip install weasyprint

echo.
echo Instalando dependencias adicionales...
pip install cffi
pip install cairocffi

echo.
echo ========================================
echo INSTALACION COMPLETADA
echo ========================================
echo.
echo Ahora puedes usar el comprobante PDF:
echo 1. Ve a cualquier orden de servicio
echo 2. Haz clic en "Generar Comprobante"
echo 3. Se abrira en el navegador listo para imprimir
echo.
pause
