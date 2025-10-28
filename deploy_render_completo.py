#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script completo para subir cambios a Render
Realiza commit, push a GitHub y despliegue automático
"""

import subprocess
import sys
import os
from datetime import datetime

def ejecutar_comando(comando, descripcion):
    """Ejecuta un comando del sistema y muestra el resultado"""
    print(f"\n{'='*60}")
    print(f"🚀 {descripcion}")
    print('='*60)
    
    try:
        resultado = subprocess.run(
            comando, 
            shell=True, 
            check=True, 
            capture_output=True, 
            text=True,
            encoding='utf-8'
        )
        
        if resultado.stdout:
            print(resultado.stdout)
        if resultado.stderr:
            print(resultado.stderr)
        
        print(f"✅ {descripcion} completado exitosamente")
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Error ejecutando: {descripcion}")
        print(f"Código de error: {e.returncode}")
        if e.stdout:
            print(f"Salida: {e.stdout}")
        if e.stderr:
            print(f"Error: {e.stderr}")
        return False

def main():
    print("\n" + "="*80)
    print("🚀 DEPLOY AUTOMÁTICO A RENDER - TECNICEL")
    print("="*80)
    print(f"📅 Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Verificar que estamos en el directorio correcto
    if not os.path.exists('app.py'):
        print("❌ Error: No se encuentra app.py en el directorio actual")
        print("   Por favor, ejecuta este script desde el directorio del proyecto")
        sys.exit(1)
    
    # Verificar que git está disponible
    try:
        subprocess.run(['git', '--version'], capture_output=True, check=True)
    except:
        print("❌ Error: Git no está instalado o no está en el PATH")
        sys.exit(1)
    
    # Verificar estado de git
    print("\n📋 Estado actual del repositorio:")
    ejecutar_comando('git status', 'Verificando estado de Git')
    
    # Agregar todos los archivos
    print("\n📦 Agregando archivos al staging...")
    ejecutar_comando('git add .', 'Agregando cambios')
    
    # Crear commit
    mensaje_commit = f"Actualización del sistema: Mejoras en configuración de Proveedores, Calendario, Inventario y Equipos - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    
    print("\n💾 Creando commit...")
    if not ejecutar_comando(f'git commit -m "{mensaje_commit}"', 'Creando commit'):
        # Verificar si hay cambios para commitear
        resultado = subprocess.run('git status', shell=True, capture_output=True, text=True)
        if 'nothing to commit' in resultado.stdout:
            print("⚠️ No hay cambios para commitear")
        else:
            print("❌ Error al crear el commit")
            sys.exit(1)
    
    # Obtener la rama actual
    resultado = subprocess.run('git branch --show-current', shell=True, capture_output=True, text=True)
    rama_actual = resultado.stdout.strip() or 'main'
    
    print(f"\n📍 Rama actual: {rama_actual}")
    
    # Push a GitHub
    print("\n☁️ Subiendo cambios a GitHub...")
    if ejecutar_comando(f'git push origin {rama_actual}', 'Subiendo a GitHub'):
        print(f"\n✅ Cambios subidos a GitHub en la rama '{rama_actual}'")
    else:
        print("\n❌ Error al subir cambios a GitHub")
        sys.exit(1)
    
    # Verificar si está conectado a un repositorio remoto de Render
    resultado = subprocess.run('git remote -v', shell=True, capture_output=True, text=True)
    remotes = resultado.stdout.strip()
    
    print("\n🔗 Repositorios remotos configurados:")
    print(remotes)
    
    # Información final
    print("\n" + "="*80)
    print("✅ DEPLOY COMPLETADO EXITOSAMENTE")
    print("="*80)
    print("\n📝 Resumen:")
    print(f"   ✓ Cambios agregados al staging")
    print(f"   ✓ Commit creado: {mensaje_commit}")
    print(f"   ✓ Push realizado a: origin/{rama_actual}")
    print("\n⏰ Render detectará los cambios automáticamente")
    print("   y desplegará la nueva versión en breve.")
    print("\n🌐 Revisa el estado del deploy en:")
    print("   https://dashboard.render.com/")
    print("="*80)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️ Proceso cancelado por el usuario")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error inesperado: {e}")
        sys.exit(1)

