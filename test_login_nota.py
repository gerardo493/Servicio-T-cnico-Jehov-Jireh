import requests
import json

# URL base
base_url = "http://127.0.0.1:5000"

# Crear sesión
session = requests.Session()

# 1. Hacer login
login_data = {
    'username': 'administrador',
    'password': 'gerardo123*'
}

print("🔐 Haciendo login...")
login_response = session.post(f"{base_url}/login", data=login_data)

if login_response.status_code == 200:
    print("✅ Login exitoso")
    
    # 2. Intentar acceder a nueva nota de entrega
    print("📝 Accediendo a nueva nota de entrega...")
    nota_response = session.get(f"{base_url}/notas-entrega/nueva")
    
    print(f"Status Code: {nota_response.status_code}")
    
    if nota_response.status_code == 200:
        print("✅ Acceso exitoso a nueva nota de entrega")
        
        # Verificar si es la página profesional
        if "PRODUCTOS NATURALES KISVIC 1045" in nota_response.text:
            print("✅ Template profesional detectado")
        else:
            print("❌ Template profesional NO detectado")
            print("Contenido de la página:")
            print(nota_response.text[:500])
    else:
        print(f"❌ Error accediendo a nueva nota: {nota_response.status_code}")
        print(nota_response.text[:500])
else:
    print(f"❌ Error en login: {login_response.status_code}")
    print(login_response.text[:500])






