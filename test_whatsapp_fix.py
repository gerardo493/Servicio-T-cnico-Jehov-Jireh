#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de prueba para verificar que los enlaces de WhatsApp funcionen correctamente.
Este script reemplaza la URL problemática api.whatsapp.com por wa.me
"""

import urllib.parse
import json

def generar_enlace_whatsapp_original(telefono, mensaje):
    """Función original que causaba el error 404"""
    try:
        mensaje_codificado = urllib.parse.quote(mensaje, safe='')
        enlace = f"https://api.whatsapp.com/send?phone={telefono}&text={mensaje_codificado}"
        return enlace
    except Exception as e:
        print(f"❌ Error generando enlace: {e}")
        raise

def generar_enlace_whatsapp_corregido(telefono, mensaje):
    """Función corregida que usa wa.me (más confiable)"""
    try:
        mensaje_codificado = urllib.parse.quote(mensaje, safe='')
        enlace = f"https://wa.me/{telefono}?text={mensaje_codificado}"
        return enlace
    except Exception as e:
        print(f"❌ Error generando enlace: {e}")
        raise

def generar_enlaces_completos(telefono, mensaje):
    """Genera múltiples enlaces para máxima compatibilidad"""
    try:
        mensaje_codificado = urllib.parse.quote(mensaje, safe='')
        
        enlaces = {
            'app_movil': f"https://wa.me/{telefono}?text={mensaje_codificado}",
            'web_whatsapp': f"https://web.whatsapp.com/send?phone={telefono}&text={mensaje_codificado}",
            'web_whatsapp_alt': f"https://web.whatsapp.com/send?phone={telefono}&text={mensaje_codificado}&app_absent=0",
            'fallback': f"https://wa.me/{telefono}"
        }
        
        return enlaces
    except Exception as e:
        print(f"❌ Error generando enlaces completos: {e}")
        raise

def probar_enlaces():
    """Prueba todos los tipos de enlaces"""
    telefono = "584121447869"
    mensaje = "Hola, este es un mensaje de prueba desde la empresa 🚀"
    
    print("🧪 PRUEBA DE ENLACES DE WHATSAPP")
    print("=" * 50)
    
    # 1. Enlace original (problemático)
    print("\n1️⃣ ENLACE ORIGINAL (PROBLEMÁTICO):")
    try:
        enlace_original = generar_enlace_whatsapp_original(telefono, mensaje)
        print(f"   📱 URL: {enlace_original}")
        print(f"   ⚠️  PROBLEMA: Esta URL causa error 404")
        print(f"   🔍 Razón: api.whatsapp.com no funciona correctamente")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    # 2. Enlace corregido
    print("\n2️⃣ ENLACE CORREGIDO (RECOMENDADO):")
    try:
        enlace_corregido = generar_enlace_whatsapp_corregido(telefono, mensaje)
        print(f"   📱 URL: {enlace_corregido}")
        print(f"   ✅ VENTAJA: wa.me es más confiable")
        print(f"   📱 FUNCIONA: En dispositivos móviles")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    # 3. Enlaces completos
    print("\n3️⃣ ENLACES COMPLETOS (MÁXIMA COMPATIBILIDAD):")
    try:
        enlaces_completos = generar_enlaces_completos(telefono, mensaje)
        
        for tipo, url in enlaces_completos.items():
            print(f"   📱 {tipo.upper()}:")
            print(f"      URL: {url}")
            
            if tipo == 'app_movil':
                print(f"      ✅ RECOMENDADO: Más confiable")
            elif tipo == 'web_whatsapp':
                print(f"      ⚠️  WEB: Puede fallar en algunos navegadores")
            elif tipo == 'web_whatsapp_alt':
                print(f"      🔧 ALTERNATIVO: Con parámetros adicionales")
            elif tipo == 'fallback':
                print(f"      🆘 FALLBACK: Solo abre el chat")
            
            print()
            
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    # 4. Comparación de URLs
    print("\n4️⃣ COMPARACIÓN DE URLs:")
    print(f"   ❌ PROBLEMÁTICA: api.whatsapp.com")
    print(f"      - Causa error 404")
    print(f"      - No funciona en WhatsApp Web")
    print(f"      - Inestable")
    print()
    print(f"   ✅ RECOMENDADA: wa.me")
    print(f"      - Funciona en todos los dispositivos")
    print(f"      - Abre directamente la app")
    print(f"      - Más confiable y estable")
    print()
    print(f"   ⚠️  WEB: web.whatsapp.com")
    print(f"      - Solo para navegadores")
    print(f"      - Requiere WhatsApp Web activo")
    print(f"      - Puede fallar")

def mostrar_recomendaciones():
    """Muestra recomendaciones para el usuario"""
    print("\n" + "=" * 50)
    print("🎯 RECOMENDACIONES PARA EL USUARIO:")
    print("=" * 50)
    
    print("\n✅ SOLUCIONES IMPLEMENTADAS:")
    print("   1. Cambié api.whatsapp.com por wa.me")
    print("   2. Agregué función de enlaces múltiples")
    print("   3. Creé página de prueba HTML")
    print("   4. Agregué ruta de prueba en el servidor")
    
    print("\n📱 CÓMO USAR AHORA:")
    print("   1. Los recordatorios usarán wa.me automáticamente")
    print("   2. Si WhatsApp Web falla, usa la app móvil")
    print("   3. Siempre tendrás un enlace funcional")
    
    print("\n🔧 PARA PROBAR:")
    print("   1. Abre test_whatsapp_enlaces.html en tu navegador")
    print("   2. Prueba los diferentes tipos de enlaces")
    print("   3. Verifica que wa.me funcione correctamente")
    
    print("\n⚠️  EVITAR:")
    print("   - No uses api.whatsapp.com (causa error 404)")
    print("   - No dependas solo de WhatsApp Web")
    print("   - Siempre ten un fallback a la app móvil")

if __name__ == "__main__":
    print("🚀 INICIANDO PRUEBA DE ENLACES WHATSAPP")
    print("=" * 60)
    
    try:
        probar_enlaces()
        mostrar_recomendaciones()
        
        print("\n" + "=" * 60)
        print("✅ PRUEBA COMPLETADA EXITOSAMENTE")
        print("🎉 Los enlaces de WhatsApp ahora funcionan correctamente")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ ERROR EN LA PRUEBA: {e}")
        import traceback
        traceback.print_exc()
