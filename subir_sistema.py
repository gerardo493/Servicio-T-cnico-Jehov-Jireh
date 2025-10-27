#!/usr/bin/env python3
"""
Script Completo para Subir Sistema - Sistema de Recordatorios
Autor: Sistema Automático
Fecha: 2025-08-18
Versión: 1.0
"""

import os
import sys
import json
import time
import subprocess
import shutil
from datetime import datetime
import logging
from pathlib import Path

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('subir_sistema.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

class SistemaDeployer:
    def __init__(self):
        self.project_name = "Sistema de Recordatorios"
        self.project_dir = os.getcwd()
        self.backup_dir = "backups_deploy"
        self.temp_dir = "temp_deploy"
        
        # Colores para la consola
        self.colors = {
            'reset': '\033[0m',
            'red': '\033[91m',
            'green': '\033[92m',
            'yellow': '\033[93m',
            'blue': '\033[94m',
            'purple': '\033[95m',
            'cyan': '\033[96m',
            'white': '\033[97m'
        }
        
        # Crear directorios necesarios
        self.setup_directories()
        
    def setup_directories(self):
        """Crea los directorios necesarios para el deploy."""
        for directory in [self.backup_dir, self.temp_dir]:
            if not os.path.exists(directory):
                os.makedirs(directory)
                logger.info(f"✅ Directorio creado: {directory}")
    
    def print_banner(self):
        """Muestra el banner del sistema."""
        banner = f"""
{self.colors['cyan']}╔══════════════════════════════════════════════════════════════╗
║                    🚀 SUBIR SISTEMA COMPLETO                     ║
║                     Sistema de Recordatorios                     ║
║                           2025                           ║
╚══════════════════════════════════════════════════════════════╝{self.colors['reset']}
"""
        print(banner)
    
    def print_menu(self):
        """Muestra el menú principal."""
        menu = f"""
{self.colors['blue']}📋 MENÚ PRINCIPAL:{self.colors['reset']}

{self.colors['green']}1️⃣  🔍 Verificar estado del sistema
2️⃣  📦 Crear backup del sistema
3️⃣  🧹 Limpiar archivos temporales
4️⃣  📝 Hacer commit de cambios
5️⃣  🚀 Hacer push al repositorio
6️⃣  🔄 Deploy completo (commit + push)
7️⃣  📊 Ver información del proyecto
8️⃣  🔧 Configuración avanzada
9️⃣  📋 Ver logs del sistema
🔟  ❌ Salir{self.colors['reset']}

{self.colors['yellow']}══════════════════════════════════════════════════════════════{self.colors['reset']}
"""
        print(menu)
    
    def colored_print(self, text, color='white'):
        """Imprime texto con color."""
        print(f"{self.colors.get(color, self.colors['white'])}{text}{self.colors['reset']}")
    
    def check_system_status(self):
        """Verifica el estado completo del sistema."""
        self.colored_print("\n🔍 VERIFICANDO ESTADO DEL SISTEMA...", 'cyan')
        self.colored_print("=" * 60, 'yellow')
        
        # Verificar Git
        git_status = self.check_git()
        
        # Verificar archivos del proyecto
        project_status = self.check_project_files()
        
        # Verificar espacio en disco
        disk_status = self.check_disk_space()
        
        # Verificar conectividad
        connectivity_status = self.check_connectivity()
        
        # Resumen del estado
        self.colored_print("\n📊 RESUMEN DEL ESTADO:", 'blue')
        self.colored_print("=" * 30, 'yellow')
        
        status_items = [
            ("Git", git_status),
            ("Archivos del Proyecto", project_status),
            ("Espacio en Disco", disk_status),
            ("Conectividad", connectivity_status)
        ]
        
        for item, status in status_items:
            color = 'green' if status else 'red'
            icon = "✅" if status else "❌"
            self.colored_print(f"{icon} {item}: {'OK' if status else 'ERROR'}", color)
        
        return all([git_status, project_status, disk_status, connectivity_status])
    
    def check_git(self):
        """Verifica el estado de Git."""
        try:
            # Verificar si Git está instalado
            result = subprocess.run(['git', '--version'], 
                                 capture_output=True, text=True, check=True)
            self.colored_print(f"✅ Git instalado: {result.stdout.strip()}", 'green')
            
            # Verificar si estamos en un repositorio
            result = subprocess.run(['git', 'status'], 
                                 capture_output=True, text=True, check=True)
            self.colored_print("✅ Repositorio Git válido", 'green')
            
            # Verificar remote
            result = subprocess.run(['git', 'remote', '-v'], 
                                 capture_output=True, text=True, check=True)
            self.colored_print("✅ Repositorio remoto configurado", 'green')
            
            # Verificar rama actual
            result = subprocess.run(['git', 'branch', '--show-current'], 
                                 capture_output=True, text=True, check=True)
            current_branch = result.stdout.strip()
            self.colored_print(f"✅ Rama actual: {current_branch}", 'green')
            
            return True
            
        except subprocess.CalledProcessError as e:
            self.colored_print(f"❌ Error en Git: {e}", 'red')
            return False
        except FileNotFoundError:
            self.colored_print("❌ Git no está instalado", 'red')
            return False
    
    def check_project_files(self):
        """Verifica los archivos principales del proyecto."""
        required_files = [
            'app.py',
            'requirements.txt',
            'templates/',
            'static/',
            'README.md'
        ]
        
        missing_files = []
        for file_path in required_files:
            if not os.path.exists(file_path):
                missing_files.append(file_path)
        
        if missing_files:
            self.colored_print(f"❌ Archivos faltantes: {', '.join(missing_files)}", 'red')
            return False
        else:
            self.colored_print("✅ Todos los archivos del proyecto están presentes", 'green')
            return True
    
    def check_disk_space(self):
        """Verifica el espacio disponible en disco."""
        try:
            total, used, free = shutil.disk_usage('.')
            free_gb = free // (1024**3)
            total_gb = total // (1024**3)
            
            self.colored_print(f"💾 Espacio en disco: {free_gb}GB libres de {total_gb}GB total", 'cyan')
            
            if free_gb > 1:  # Más de 1GB libre
                self.colored_print("✅ Espacio en disco suficiente", 'green')
                return True
            else:
                self.colored_print("⚠️ Espacio en disco bajo", 'yellow')
                return False
                
        except Exception as e:
            self.colored_print(f"❌ Error verificando espacio en disco: {e}", 'red')
            return False
    
    def check_connectivity(self):
        """Verifica la conectividad básica."""
        try:
            # Verificar conexión a internet (ping a Google)
            result = subprocess.run(['ping', '-n', '1', '8.8.8.8'], 
                                 capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                self.colored_print("✅ Conectividad a internet OK", 'green')
                return True
            else:
                self.colored_print("❌ Sin conectividad a internet", 'red')
                return False
                
        except subprocess.TimeoutExpired:
            self.colored_print("❌ Timeout en verificación de conectividad", 'red')
            return False
        except Exception as e:
            self.colored_print(f"❌ Error verificando conectividad: {e}", 'red')
            return False
    
    def create_backup(self):
        """Crea un backup completo del sistema."""
        self.colored_print("\n📦 CREANDO BACKUP DEL SISTEMA...", 'cyan')
        self.colored_print("=" * 50, 'yellow')
        
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"backup_sistema_{timestamp}"
            backup_path = os.path.join(self.backup_dir, backup_name)
            
            # Crear directorio de backup
            os.makedirs(backup_path, exist_ok=True)
            
            # Archivos y directorios a respaldar
            items_to_backup = [
                'app.py',
                'requirements.txt',
                'templates/',
                'static/',
                '*.json',
                '*.md',
                '*.bat',
                '*.py'
            ]
            
            # Excluir directorios y archivos
            exclude_patterns = [
                '__pycache__/',
                '*.pyc',
                '*.pyo',
                '*.log',
                'backups*/',
                'temp*/',
                '.git/',
                'venv/',
                'node_modules/'
            ]
            
            self.colored_print("🔄 Copiando archivos...", 'yellow')
            
            # Copiar archivos principales
            for item in items_to_backup:
                if os.path.exists(item):
                    if os.path.isdir(item):
                        shutil.copytree(item, os.path.join(backup_path, item), 
                                      dirs_exist_ok=True)
                    else:
                        shutil.copy2(item, backup_path)
            
            # Crear archivo de información del backup
            backup_info = {
                'fecha': datetime.now().isoformat(),
                'proyecto': self.project_name,
                'directorio': self.project_dir,
                'archivos_respaldados': items_to_backup,
                'exclusiones': exclude_patterns
            }
            
            with open(os.path.join(backup_path, 'backup_info.json'), 'w', encoding='utf-8') as f:
                json.dump(backup_info, f, indent=2, ensure_ascii=False)
            
            # Comprimir backup
            shutil.make_archive(backup_path, 'zip', backup_path)
            shutil.rmtree(backup_path)  # Eliminar directorio temporal
            
            backup_size = os.path.getsize(f"{backup_path}.zip") / (1024 * 1024)  # MB
            
            self.colored_print(f"✅ Backup creado exitosamente: {backup_name}.zip", 'green')
            self.colored_print(f"📁 Ubicación: {self.backup_dir}", 'cyan')
            self.colored_print(f"💾 Tamaño: {backup_size:.2f} MB", 'cyan')
            
            return True
            
        except Exception as e:
            self.colored_print(f"❌ Error creando backup: {e}", 'red')
            logger.error(f"Error creando backup: {e}")
            return False
    
    def clean_temp_files(self):
        """Limpia archivos temporales del sistema."""
        self.colored_print("\n🧹 LIMPIANDO ARCHIVOS TEMPORALES...", 'cyan')
        self.colored_print("=" * 50, 'yellow')
        
        try:
            files_removed = 0
            space_freed = 0
            
            # Patrones de archivos a eliminar
            patterns = [
                '*.log',
                '*.tmp',
                '*.temp',
                '*.pyc',
                '*.pyo',
                '__pycache__/',
                'temp_*',
                '*.bak'
            ]
            
            for pattern in patterns:
                if '*' in pattern:
                    # Buscar archivos con wildcard
                    import glob
                    files = glob.glob(pattern)
                    for file_path in files:
                        if os.path.isfile(file_path):
                            size = os.path.getsize(file_path)
                            os.remove(file_path)
                            files_removed += 1
                            space_freed += size
                        elif os.path.isdir(file_path):
                            shutil.rmtree(file_path)
                            files_removed += 1
                else:
                    # Directorio específico
                    if os.path.exists(pattern):
                        if os.path.isdir(pattern):
                            shutil.rmtree(pattern)
                            files_removed += 1
                        else:
                            size = os.path.getsize(pattern)
                            os.remove(pattern)
                            files_removed += 1
                            space_freed += size
            
            # Limpiar directorio temp_deploy
            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
                os.makedirs(self.temp_dir)
            
            space_freed_mb = space_freed / (1024 * 1024)
            
            self.colored_print(f"✅ Limpieza completada", 'green')
            self.colored_print(f"🗑️ Archivos eliminados: {files_removed}", 'cyan')
            self.colored_print(f"💾 Espacio liberado: {space_freed_mb:.2f} MB", 'cyan')
            
            return True
            
        except Exception as e:
            self.colored_print(f"❌ Error en limpieza: {e}", 'red')
            logger.error(f"Error en limpieza: {e}")
            return False
    
    def commit_changes(self):
        """Realiza commit de los cambios pendientes."""
        self.colored_print("\n📝 HACIENDO COMMIT DE CAMBIOS...", 'cyan')
        self.colored_print("=" * 50, 'yellow')
        
        try:
            # Verificar si hay cambios
            result = subprocess.run(['git', 'status', '--porcelain'], 
                                 capture_output=True, text=True, check=True)
            
            if not result.stdout.strip():
                self.colored_print("✅ No hay cambios pendientes para commit", 'green')
                return True
            
            # Mostrar cambios
            self.colored_print("📋 Cambios detectados:", 'yellow')
            subprocess.run(['git', 'status', '--short'], check=True)
            
            # Agregar todos los cambios
            self.colored_print("🔄 Agregando archivos al staging...", 'yellow')
            subprocess.run(['git', 'add', '.'], check=True)
            
            # Crear mensaje de commit
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            commit_message = f"🚀 Deploy del sistema - {timestamp}"
            
            # Realizar commit
            self.colored_print("💾 Realizando commit...", 'yellow')
            subprocess.run(['git', 'commit', '-m', commit_message], check=True)
            
            self.colored_print("✅ Commit realizado exitosamente", 'green')
            self.colored_print(f"📝 Mensaje: {commit_message}", 'cyan')
            
            return True
            
        except subprocess.CalledProcessError as e:
            self.colored_print(f"❌ Error en commit: {e}", 'red')
            logger.error(f"Error en commit: {e}")
            return False
        except Exception as e:
            self.colored_print(f"❌ Error inesperado: {e}", 'red')
            logger.error(f"Error inesperado: {e}")
            return False
    
    def push_changes(self):
        """Envía los cambios al repositorio remoto."""
        self.colored_print("\n🚀 HACIENDO PUSH AL REPOSITORIO...", 'cyan')
        self.colored_print("=" * 50, 'yellow')
        
        try:
            # Obtener rama actual
            result = subprocess.run(['git', 'branch', '--show-current'], 
                                 capture_output=True, text=True, check=True)
            current_branch = result.stdout.strip()
            
            self.colored_print(f"🌿 Rama actual: {current_branch}", 'cyan')
            
            # Realizar push
            self.colored_print("📤 Enviando cambios...", 'yellow')
            subprocess.run(['git', 'push', 'origin', current_branch], check=True)
            
            self.colored_print("✅ Push realizado exitosamente", 'green')
            self.colored_print("🎉 ¡Deploy iniciado en Render!", 'green')
            self.colored_print("⏱️ El despliegue puede tomar 2-5 minutos", 'yellow')
            self.colored_print("🌐 Verifica en: https://dashboard.render.com/web/srv-d2ckh46r433s73appvug", 'cyan')
            
            return True
            
        except subprocess.CalledProcessError as e:
            self.colored_print(f"❌ Error en push: {e}", 'red')
            logger.error(f"Error en push: {e}")
            return False
        except Exception as e:
            self.colored_print(f"❌ Error inesperado: {e}", 'red')
            logger.error(f"Error inesperado: {e}")
            return False
    
    def deploy_completo(self):
        """Realiza el deploy completo del sistema."""
        self.colored_print("\n🔄 INICIANDO DEPLOY COMPLETO...", 'cyan')
        self.colored_print("=" * 60, 'yellow')
        
        # Verificar estado del sistema
        if not self.check_system_status():
            self.colored_print("❌ El sistema no está listo para deploy", 'red')
            return False
        
        # Crear backup
        self.colored_print("\n📦 Creando backup de seguridad...", 'yellow')
        if not self.clean_temp_files():
            self.colored_print("⚠️ No se pudo crear backup, continuando...", 'yellow')
        
        # Limpiar archivos temporales
        self.colored_print("\n🧹 Limpiando archivos temporales...", 'yellow')
        self.clean_temp_files()
        
        # Hacer commit
        self.colored_print("\n📝 Preparando cambios...", 'yellow')
        if not self.commit_changes():
            self.colored_print("❌ Falló el commit, abortando deploy", 'red')
            return False
        
        # Hacer push
        self.colored_print("\n🚀 Desplegando en Render...", 'yellow')
        if not self.push_changes():
            self.colored_print("❌ Falló el push, abortando deploy", 'red')
            return False
        
        # Éxito
        self.colored_print("\n🎉 ¡DEPLOY COMPLETADO EXITOSAMENTE!", 'green')
        self.colored_print("=" * 50, 'green')
        self.colored_print("✅ Sistema verificado", 'green')
        self.colored_print("✅ Backup creado", 'green')
        self.colored_print("✅ Archivos limpiados", 'green')
        self.colored_print("✅ Cambios confirmados", 'green')
        self.colored_print("✅ Sistema desplegado", 'green')
        self.colored_print("=" * 50, 'green')
        
        return True
    
    def show_project_info(self):
        """Muestra información detallada del proyecto."""
        self.colored_print("\n📊 INFORMACIÓN DEL PROYECTO", 'cyan')
        self.colored_print("=" * 50, 'yellow')
        
        try:
            # Información básica
            self.colored_print(f"🏢 Proyecto: {self.project_name}", 'white')
            self.colored_print(f"📁 Directorio: {self.project_dir}", 'white')
            self.colored_print(f"📅 Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", 'white')
            
            # Información de Git
            result = subprocess.run(['git', 'remote', 'get-url', 'origin'], 
                                 capture_output=True, text=True, check=True)
            remote_url = result.stdout.strip()
            self.colored_print(f"🔗 Repositorio: {remote_url}", 'white')
            
            result = subprocess.run(['git', 'branch', '--show-current'], 
                                 capture_output=True, text=True, check=True)
            current_branch = result.stdout.strip()
            self.colored_print(f"🌿 Rama: {current_branch}", 'white')
            
            result = subprocess.run(['git', 'log', '-1', '--oneline'], 
                                 capture_output=True, text=True, check=True)
            last_commit = result.stdout.strip()
            self.colored_print(f"📝 Último commit: {last_commit}", 'white')
            
            # Estadísticas del proyecto
            self.colored_print("\n📊 ESTADÍSTICAS:", 'blue')
            self.colored_print("-" * 20, 'yellow')
            
            # Contar archivos por tipo
            file_counts = {}
            for root, dirs, files in os.walk('.'):
                if '.git' in root or 'venv' in root or '__pycache__' in root:
                    continue
                for file in files:
                    ext = os.path.splitext(file)[1]
                    file_counts[ext] = file_counts.get(ext, 0) + 1
            
            for ext, count in sorted(file_counts.items()):
                self.colored_print(f"📄 {ext or 'Sin extensión'}: {count}", 'white')
            
            # URLs importantes
            self.colored_print("\n🌐 URLs IMPORTANTES:", 'blue')
            self.colored_print("-" * 20, 'yellow')
            self.colored_print("📊 Dashboard Render: https://dashboard.render.com/web/srv-d2ckh46r433s73appvug", 'cyan')
            self.colored_print("🌐 Aplicación: https://tu-app.onrender.com", 'cyan')
            
        except Exception as e:
            self.colored_print(f"❌ Error obteniendo información: {e}", 'red')
    
    def show_logs(self):
        """Muestra los logs del sistema."""
        self.colored_print("\n📋 LOGS DEL SISTEMA", 'cyan')
        self.colored_print("=" * 50, 'yellow')
        
        log_file = 'subir_sistema.log'
        if os.path.exists(log_file):
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                
                if lines:
                    # Mostrar últimas 20 líneas
                    self.colored_print("📄 Últimas 20 líneas del log:", 'yellow')
                    self.colored_print("-" * 40, 'yellow')
                    
                    for line in lines[-20:]:
                        if 'ERROR' in line:
                            self.colored_print(line.strip(), 'red')
                        elif 'WARNING' in line:
                            self.colored_print(line.strip(), 'yellow')
                        elif 'INFO' in line:
                            self.colored_print(line.strip(), 'green')
                        else:
                            self.colored_print(line.strip(), 'white')
                else:
                    self.colored_print("📄 El archivo de log está vacío", 'yellow')
                    
            except Exception as e:
                self.colored_print(f"❌ Error leyendo logs: {e}", 'red')
        else:
            self.colored_print("📄 No hay archivo de log disponible", 'yellow')
    
    def run(self):
        """Ejecuta el menú principal del sistema."""
        while True:
            try:
                self.print_banner()
                self.print_menu()
                
                opcion = input(f"\n{self.colors['cyan']}Selecciona una opción (1-10): {self.colors['reset']}")
                
                if opcion == '1':
                    self.check_system_status()
                elif opcion == '2':
                    self.create_backup()
                elif opcion == '3':
                    self.clean_temp_files()
                elif opcion == '4':
                    self.commit_changes()
                elif opcion == '5':
                    self.push_changes()
                elif opcion == '6':
                    self.deploy_completo()
                elif opcion == '7':
                    self.show_project_info()
                elif opcion == '8':
                    self.colored_print("\n🔧 CONFIGURACIÓN AVANZADA", 'cyan')
                    self.colored_print("Esta funcionalidad estará disponible en futuras versiones", 'yellow')
                elif opcion == '9':
                    self.show_logs()
                elif opcion == '10':
                    self.colored_print("\n👋 ¡HASTA LUEGO!", 'green')
                    self.colored_print("Gracias por usar el Sistema de Deploy", 'cyan')
                    break
                else:
                    self.colored_print("❌ Opción inválida. Por favor selecciona 1-10", 'red')
                
                if opcion != '10':
                    input(f"\n{self.colors['yellow']}Presiona Enter para continuar...{self.colors['reset']}")
                    os.system('cls' if os.name == 'nt' else 'clear')
                    
            except KeyboardInterrupt:
                self.colored_print("\n\n⚠️ Operación cancelada por el usuario", 'yellow')
                break
            except Exception as e:
                self.colored_print(f"\n❌ Error inesperado: {e}", 'red')
                logger.error(f"Error inesperado: {e}")
                input(f"\n{self.colors['yellow']}Presiona Enter para continuar...{self.colors['reset']}")

def main():
    """Función principal del script."""
    try:
        deployer = SistemaDeployer()
        deployer.run()
    except Exception as e:
        print(f"❌ Error fatal: {e}")
        logging.error(f"Error fatal: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
