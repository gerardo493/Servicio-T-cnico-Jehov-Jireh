#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RENDER CLOUD VS1 - Script de Automatización para Despliegue en Render
Sistema de Gestión Comercial
"""

import os
import sys
import subprocess
import json
import time
from pathlib import Path

class RenderCloudDeployer:
    def __init__(self):
        self.project_dir = Path.cwd()
        self.git_initialized = False
        self.remote_added = False
        
    def print_banner(self):
        """Imprime el banner del script"""
        print("=" * 60)
        print("🚀 RENDER CLOUD VS1 - DESPLIEGUE AUTOMÁTICO")
        print("=" * 60)
        print("Sistema de Gestión Comercial")
        print("Versión: 1.0")
        print("=" * 60)
        print()
        
    def check_git_installed(self):
        """Verifica si Git está instalado"""
        try:
            result = subprocess.run(['git', '--version'], 
                                  capture_output=True, text=True, check=True)
            print(f"✅ Git detectado: {result.stdout.strip()}")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("❌ Git no está instalado. Por favor instala Git primero.")
            print("Descarga desde: https://git-scm.com/downloads")
            return False
            
    def check_git_config(self):
        """Verifica la configuración actual de Git"""
        try:
            # Verificar nombre de usuario
            name_result = subprocess.run(['git', 'config', 'user.name'], 
                                       capture_output=True, text=True, check=True)
            email_result = subprocess.run(['git', 'config', 'user.email'], 
                                        capture_output=True, text=True, check=True)
            
            name = name_result.stdout.strip()
            email = email_result.stdout.strip()
            
            print(f"👤 Usuario Git configurado: {name}")
            print(f"📧 Email Git configurado: {email}")
            return True
            
        except subprocess.CalledProcessError:
            print("⚠️  Git no tiene configuración de usuario. Configurando...")
            return self.configure_git_user()
            
    def check_python_files(self):
        """Verifica que los archivos necesarios existan"""
        required_files = [
            'app.py',
            'requirements.txt',
            'Procfile',
            'runtime.txt',
            'start.sh'
        ]
        
        print("🔍 Verificando archivos necesarios...")
        missing_files = []
        
        for file in required_files:
            if Path(file).exists():
                print(f"✅ {file}")
            else:
                print(f"❌ {file} - NO ENCONTRADO")
                missing_files.append(file)
                
        if missing_files:
            print(f"\n⚠️  Archivos faltantes: {', '.join(missing_files)}")
            print("Por favor, asegúrate de que todos los archivos estén presentes.")
            return False
            
        print("✅ Todos los archivos necesarios están presentes")
        return True
        
    def init_git(self):
        """Inicializa Git en el proyecto"""
        if Path('.git').exists():
            print("✅ Git ya está inicializado en este proyecto")
            self.git_initialized = True
            return True
            
        try:
            print("🚀 Inicializando Git...")
            subprocess.run(['git', 'init'], check=True)
            self.git_initialized = True
            print("✅ Git inicializado correctamente")
            return True
        except subprocess.CalledProcessError as e:
            print(f"❌ Error al inicializar Git: {e}")
            return False
            
    def configure_git_user(self):
        """Configura el usuario de Git solo si es necesario"""
        print("👤 Configurando usuario de Git...")
        
        # Solicitar información del usuario
        name = input("Ingresa tu nombre completo: ").strip()
        email = input("Ingresa tu email: ").strip()
        
        if not name or not email:
            print("❌ Nombre y email son obligatorios")
            return False
            
        try:
            subprocess.run(['git', 'config', 'user.name', name], check=True)
            subprocess.run(['git', 'config', 'user.email', email], check=True)
            print("✅ Usuario de Git configurado correctamente")
            return True
        except subprocess.CalledProcessError as e:
            print(f"❌ Error al configurar usuario: {e}")
            return False
            
    def add_files_to_git(self):
        """Agrega todos los archivos a Git"""
        try:
            print("📁 Agregando archivos a Git...")
            subprocess.run(['git', 'add', '.'], check=True)
            print("✅ Archivos agregados al staging area")
            return True
        except subprocess.CalledProcessError as e:
            print(f"❌ Error al agregar archivos: {e}")
            return False
            
    def make_initial_commit(self):
        """Hace el primer commit"""
        try:
            print("💾 Haciendo commit inicial...")
            commit_message = "🚀 Configuración inicial para despliegue en Render - Sistema"
            subprocess.run(['git', 'commit', '-m', commit_message], check=True)
            print("✅ Commit inicial realizado correctamente")
            return True
        except subprocess.CalledProcessError as e:
            print(f"❌ Error al hacer commit: {e}")
            return False
            
    def check_existing_remote(self):
        """Verifica si ya existe un repositorio remoto"""
        try:
            result = subprocess.run(['git', 'remote', '-v'], 
                                  capture_output=True, text=True, check=True)
            if result.stdout.strip():
                print("✅ Repositorio remoto ya configurado:")
                print(result.stdout.strip())
                self.remote_added = True
                return True
            return False
        except subprocess.CalledProcessError:
            return False
            
    def add_remote_origin(self):
        """Agrega el repositorio remoto solo si es necesario"""
        if self.remote_added:
            print("✅ Repositorio remoto ya está configurado")
            return True
            
        print("🌐 Configurando repositorio remoto...")
        
        remote_url = input("Ingresa la URL de tu repositorio de GitHub: ").strip()
        
        if not remote_url:
            print("❌ URL del repositorio es obligatoria")
            return False
            
        try:
            subprocess.run(['git', 'remote', 'add', 'origin', remote_url], check=True)
            self.remote_added = True
            print("✅ Repositorio remoto agregado correctamente")
            return True
        except subprocess.CalledProcessError as e:
            print(f"❌ Error al agregar repositorio remoto: {e}")
            return False
            
    def push_to_github(self):
        """Hace push al repositorio de GitHub"""
        if not self.remote_added:
            print("❌ No se puede hacer push sin repositorio remoto")
            return False
            
        try:
            print("🚀 Haciendo push a GitHub...")
            # Intentar con 'main' primero, luego con 'master'
            try:
                subprocess.run(['git', 'push', '-u', 'origin', 'main'], check=True)
                print("✅ Push realizado correctamente a la rama 'main'")
            except subprocess.CalledProcessError:
                print("🔄 Intentando con la rama 'master'...")
                subprocess.run(['git', 'push', '-u', 'origin', 'master'], check=True)
                print("✅ Push realizado correctamente a la rama 'master'")
            return True
        except subprocess.CalledProcessError as e:
            print(f"❌ Error al hacer push: {e}")
            return False
            
    def show_render_instructions(self):
        """Muestra las instrucciones para Render"""
        print("\n" + "=" * 60)
        print("🎯 INSTRUCCIONES PARA RENDER")
        print("=" * 60)
        print("1. Ve a https://render.com")
        print("2. Crea una cuenta y conéctala con GitHub")
        print("3. Haz clic en 'New +' → 'Web Service'")
        print("4. Selecciona tu repositorio")
        print("5. Render detectará automáticamente que es Python")
        print("6. Haz clic en 'Create Web Service'")
        print("7. ¡Tu aplicación estará disponible en minutos!")
        print("=" * 60)
        
    def show_git_status(self):
        """Muestra el estado actual de Git"""
        try:
            print("\n📊 Estado actual de Git:")
            subprocess.run(['git', 'status'], check=True)
        except subprocess.CalledProcessError:
            pass
            
    def run_deployment(self):
        """Ejecuta todo el proceso de despliegue"""
        self.print_banner()
        
        # Verificaciones iniciales
        if not self.check_git_installed():
            return False
            
        if not self.check_python_files():
            return False
            
        # Verificar configuración de Git
        if not self.check_git_config():
            return False
            
        # Configuración de Git
        if not self.init_git():
            return False
            
        if not self.add_files_to_git():
            return False
            
        if not self.make_initial_commit():
            return False
            
        # Verificar repositorio remoto existente
        if not self.check_existing_remote():
            # Configuración del repositorio remoto solo si es necesario
            if not self.add_remote_origin():
                return False
        else:
            print("✅ Usando repositorio remoto existente")
            
        # Push a GitHub
        if not self.push_to_github():
            return False
            
        # Mostrar estado final
        self.show_git_status()
        self.show_render_instructions()
        
        print("\n🎉 ¡DESPLIEGUE COMPLETADO EXITOSAMENTE!")
        print("Tu aplicación está lista para ser desplegada en Render.")
        
        return True

def main():
    """Función principal"""
    try:
        deployer = RenderCloudDeployer()
        success = deployer.run_deployment()
        
        if success:
            print("\n✅ Proceso completado exitosamente")
        else:
            print("\n❌ Hubo errores durante el proceso")
            print("Revisa los mensajes de error arriba")
            
    except KeyboardInterrupt:
        print("\n\n⚠️  Proceso cancelado por el usuario")
    except Exception as e:
        print(f"\n❌ Error inesperado: {e}")
        
    input("\nPresiona Enter para salir...")

if __name__ == "__main__":
    main()
