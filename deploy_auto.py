#!/usr/bin/env python3
"""
Script de Despliegue Automático 2025
Automatiza el proceso de Git y despliegue a Render
"""

import os
import sys
import subprocess
import time
from datetime import datetime
from pathlib import Path

class AutoDeployer:
    def __init__(self):
        self.project_root = Path.cwd()
        self.git_status = None
        
    def run_command(self, command, description=""):
        """Ejecuta un comando y maneja errores"""
        print(f"\n🔄 {description}")
        print(f"   Comando: {command}")
        
        try:
            result = subprocess.run(
                command, 
                shell=True, 
                capture_output=True, 
                text=True, 
                cwd=self.project_root
            )
            
            if result.returncode == 0:
                print(f"   ✅ {description} completado exitosamente")
                if result.stdout.strip():
                    print(f"   Salida: {result.stdout.strip()}")
                return True, result.stdout
            else:
                print(f"   ❌ Error en {description}")
                print(f"   Error: {result.stderr.strip()}")
                return False, result.stderr
                
        except Exception as e:
            print(f"   ❌ Excepción en {description}: {e}")
            return False, str(e)
    
    def check_git_status(self):
        """Verifica el estado del repositorio Git"""
        print("\n📊 VERIFICANDO ESTADO DEL REPOSITORIO")
        print("=" * 50)
        
        # Verificar si estamos en un repositorio Git
        success, output = self.run_command("git status", "Verificando estado de Git")
        if not success:
            return False
            
        self.git_status = output
        
        # Verificar si hay cambios pendientes
        if "nothing to commit, working tree clean" in output:
            print("   ℹ️  No hay cambios pendientes para commit")
            return False
        elif "Changes not staged for commit" in output or "Untracked files" in output:
            print("   ✅ Hay cambios pendientes para commit")
            return True
        else:
            print("   ⚠️  Estado de Git no reconocido")
            return False
    
    def add_changes(self):
        """Agrega todos los cambios al staging area"""
        print("\n📁 AGREGANDO CAMBIOS")
        print("=" * 50)
        
        success, output = self.run_command("git add .", "Agregando todos los archivos")
        return success
    
    def commit_changes(self, message=None):
        """Hace commit de los cambios"""
        print("\n💾 HACIENDO COMMIT")
        print("=" * 50)
        
        if not message:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            message = f"Actualización automática - {timestamp}"
        
        success, output = self.run_command(
            f'git commit -m "{message}"', 
            "Haciendo commit de los cambios"
        )
        return success
    
    def push_to_github(self):
        """Sube los cambios a GitHub"""
        print("\n☁️  SUBIENDO A GITHUB")
        print("=" * 50)
        
        success, output = self.run_command("git push origin main", "Subiendo a GitHub")
        return success
    
    def check_render_status(self):
        """Verifica el estado del servicio en Render"""
        print("\n🌐 VERIFICANDO ESTADO DE RENDER")
        print("=" * 50)
        
        print("   ℹ️  Para verificar el estado del despliegue:")
        print("   1. Ve a: https://dashboard.render.com/web/srv-d2ckh46r433s73appvug")
        print("   2. Revisa la sección 'Events'")
        print("   3. El despliegue debería comenzar automáticamente")
        
        return True
    
    def show_deployment_info(self):
        """Muestra información del despliegue"""
        print("\n📋 INFORMACIÓN DEL DESPLIEGUE")
        print("=" * 50)
        print("   🌐 URL de tu aplicación: https://tu-app.onrender.com")
        print("   📊 Dashboard de Render: https://dashboard.render.com/web/srv-d2ckh46r433s73appvug")
        print("   📚 Repositorio GitHub: https://github.com/tu-usuario/tu-repo")
        print("   ⏱️  Tiempo estimado de despliegue: 2-5 minutos")
    
    def deploy(self, commit_message=None):
        """Ejecuta el proceso completo de despliegue"""
        print("🚀 DESPLEGADOR AUTOMÁTICO 2025")
        print("=" * 60)
        print(f"📁 Directorio: {self.project_root}")
        print(f"⏰ Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # 1. Verificar estado de Git
        if not self.check_git_status():
            print("\n❌ No hay cambios para desplegar")
            return False
        
        # 2. Agregar cambios
        if not self.add_changes():
            print("\n❌ Error al agregar cambios")
            return False
        
        # 3. Hacer commit
        if not self.commit_changes(commit_message):
            print("\n❌ Error al hacer commit")
            return False
        
        # 4. Subir a GitHub
        if not self.push_to_github():
            print("\n❌ Error al subir a GitHub")
            return False
        
        # 5. Verificar estado de Render
        self.check_render_status()
        
        # 6. Mostrar información
        self.show_deployment_info()
        
        print(f"\n✅ DESPLIEGUE INICIADO EXITOSAMENTE!")
        print(f"⏰ Fin: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        return True
    
    def quick_deploy(self):
        """Despliegue rápido con mensaje automático"""
        return self.deploy()
    
    def custom_deploy(self, message):
        """Despliegue con mensaje personalizado"""
        return self.deploy(message)

def main():
    """Función principal"""
    deployer = AutoDeployer()
    
    if len(sys.argv) > 1:
        # Despliegue con mensaje personalizado
        message = " ".join(sys.argv[1:])
        deployer.custom_deploy(message)
    else:
        # Despliegue rápido
        print("¿Quieres hacer un despliegue rápido o personalizado?")
        print("1. Despliegue rápido (mensaje automático)")
        print("2. Despliegue personalizado (con mensaje)")
        
        choice = input("\nSelecciona una opción (1 o 2): ").strip()
        
        if choice == "2":
            message = input("Ingresa el mensaje del commit: ").strip()
            if message:
                deployer.custom_deploy(message)
            else:
                deployer.quick_deploy()
        else:
            deployer.quick_deploy()

if __name__ == "__main__":
    main()
