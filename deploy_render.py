#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script de Deploy para Render
Guía rápida para subir el sistema a Render
"""

import os
import subprocess
import sys

def print_header(title):
    """Imprime un título bonito"""
    print("\n" + "="*60)
    print(f"  {title}")
    print("="*60 + "\n")

def ejecutar_comando(comando, descripcion):
    """Ejecuta un comando y muestra el resultado"""
    print(f"🚀 {descripcion}...")
    try:
        resultado = subprocess.run(comando, shell=True, capture_output=True, text=True)
        if resultado.returncode == 0:
            print(f"✅ {descripcion} completado")
            if resultado.stdout:
                print(resultado.stdout)
        else:
            print(f"❌ Error: {descripcion}")
            if resultado.stderr:
                print(resultado.stderr)
            return False
        return True
    except Exception as e:
        print(f"❌ Error ejecutando: {e}")
        return False

def verificar_git():
    """Verifica si Git está configurado"""
    print("🔍 Verificando Git...")
    resultado = subprocess.run("git --version", shell=True, capture_output=True, text=True)
    if resultado.returncode == 0:
        print(f"✅ Git instalado: {resultado.stdout.strip()}")
        return True
    else:
        print("❌ Git no está instalado. Descarga desde: https://git-scm.com")
        return False

def main():
    print_header("🚀 DEPLOY A RENDER - SISTEMA DE REPARACIONES")
    
    print("""
Este script te ayudará a subir tu sistema a Render.

Pasos que se ejecutarán:
1. ✅ Verificar Git
2. 📦 Agregar archivos al staging
3. 💾 Hacer commit
4. 📤 Subir a GitHub
5. 🌐 Deploy en Render (automático)

¿Deseas continuar? (s/n)
    """)
    
    respuesta = input().lower()
    if respuesta != 's':
        print("\n❌ Operación cancelada por el usuario")
        return
    
    # 1. Verificar Git
    if not verificar_git():
        sys.exit(1)
    
    # 2. Agregar archivos
    print_header("📦 AGREGANDO ARCHIVOS")
    if not ejecutar_comando("git add .", "Agregando archivos"):
        print("⚠️  No se pudo agregar archivos")
        return
    
    # 3. Verificar si hay cambios
    resultado = subprocess.run("git diff --cached --name-only", shell=True, capture_output=True, text=True)
    archivos_cambiados = resultado.stdout.strip()
    
    if not archivos_cambiados:
        print("\n✅ No hay cambios para subir")
        print("Todos los archivos ya están en el repositorio")
        return
    
    print(f"📝 Archivos a subir:\n{archivos_cambiados}\n")
    
    # 4. Hacer commit
    print_header("💾 CREANDO COMMIT")
    mensaje = input("Mensaje del commit (Enter para usar mensaje automático): ").strip()
    if not mensaje:
        from datetime import datetime
        mensaje = f"Deploy: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    
    if not ejecutar_comando(f'git commit -m "{mensaje}"', "Creando commit"):
        print("⚠️  No se pudo crear el commit")
        return
    
    # 5. Subir a GitHub
    print_header("📤 SUBIENDO A GITHUB")
    if not ejecutar_comando("git push", "Subiendo a GitHub"):
        print("⚠️  No se pudo subir a GitHub")
        print("Verifica que tengas el remote configurado:")
        print("  git remote add origin https://github.com/TU-USUARIO/TU-REPO.git")
        return
    
    print_header("✅ DEPLOY COMPLETO")
    print("""
🎉 ¡Tu sistema se ha subido exitosamente!

📋 Próximos pasos:
1. Ve a https://dashboard.render.com
2. Crea un nuevo Web Service
3. Conecta tu repositorio de GitHub
4. Render desplegará automáticamente

⏱️  Tiempo estimado de deploy: 2-5 minutos

📖 Guía completa en: GUIA_DEPLOY_RENDER.md

¡Éxito con tu deploy! 🚀
    """)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Operación cancelada por el usuario")
    except Exception as e:
        print(f"\n❌ Error inesperado: {e}")

