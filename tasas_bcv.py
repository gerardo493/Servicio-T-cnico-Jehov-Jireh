import requests
from bs4 import BeautifulSoup
import urllib3
from datetime import datetime

# Desactivar advertencias de SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def obtener_tasas_bcv():
    """Obtiene las tasas oficiales USD/BS y EUR/BS del BCV."""
    url = 'https://www.bcv.org.ve/'
    try:
        resp = requests.get(url, timeout=10, verify=False)
        if resp.status_code != 200:
            print("Error al conectar con BCV")
            return 201.4665, 220.1234  # Tasas más actuales por si falla
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        tasa_usd = None
        tasa_eur = None
        
        # Buscar todas las tasas en los elementos strong
        for strong in soup.find_all('strong'):
            txt = strong.text.strip().replace('.', '').replace(',', '.')
            try:
                posible = float(txt)
                # Rango más amplio para incluir tasas actuales
                if 1 < posible < 1000:
                    if tasa_usd is None:
                        tasa_usd = posible
                    elif tasa_eur is None and abs(posible - tasa_usd) > 1:
                        tasa_eur = posible
                        break
            except:
                continue
        
        # Si no se encontraron tasas, usar valores por defecto más actuales
        if tasa_usd is None:
            tasa_usd = 201.4665
        if tasa_eur is None:
            tasa_eur = 220.1234
            
        return tasa_usd, tasa_eur
    except Exception as e:
        print(f"Error obteniendo tasas BCV: {e}")
        return 201.4665, 220.1234  # Tasas más actuales por si falla

def obtener_tasa_euro():
    """Obtiene la tasa EUR/BS desde la página oficial del BCV."""
    url = 'https://www.bcv.org.ve/'
    try:
        resp = requests.get(url, timeout=10, verify=False)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            # Buscar todos los <strong> que contengan un número con coma decimal
            for strong in soup.find_all('strong'):
                txt = strong.get_text(strip=True)
                valor_limpio = txt.replace('.', '').replace(',', '.')
                try:
                    posible = float(valor_limpio)
                    if 10 < posible < 500:
                        return posible
                except:
                    continue
        return None
    except Exception as e:
        print(f"Error obteniendo tasa EUR: {e}")
        return None

def obtener_tasas_monitor_dolar():
    """Obtiene las tasas desde Monitor Dólar."""
    try:
        r = requests.get('https://s3.amazonaws.com/dolartoday/data.json', timeout=5)
        data = r.json()
        return {
            'tasa_bcv': float(data['USD']['bcv']) if 'USD' in data and 'bcv' in data['USD'] else None,
            'tasa_paralelo': float(data['USD']['promedio']) if 'USD' in data and 'promedio' in data['USD'] else None,
            'tasa_euro': float(data['EUR']['promedio']) if 'EUR' in data and 'promedio' in data['EUR'] else None
        }
    except Exception as e:
        print(f"Error obteniendo tasas de Monitor Dólar: {e}")
        return None

def calcular_conversion(monto, moneda_origen, tasa_usd, tasa_eur):
    """Calcula la conversión entre monedas."""
    try:
        monto = float(monto)
        if moneda_origen == 'USD':
            bs = monto * tasa_usd
            eur = bs / tasa_eur
            return {
                'USD': monto,
                'BS': bs,
                'EUR': eur
            }
        elif moneda_origen == 'EUR':
            bs = monto * tasa_eur
            usd = bs / tasa_usd
            return {
                'USD': usd,
                'BS': bs,
                'EUR': monto
            }
        elif moneda_origen == 'BS':
            usd = monto / tasa_usd
            eur = monto / tasa_eur
            return {
                'USD': usd,
                'BS': monto,
                'EUR': eur
            }
    except Exception as e:
        print(f"Error en el cálculo: {e}")
        return None

def obtener_tasa_bcv_actual():
    """Obtiene la tasa USD/BS actual del BCV."""
    try:
        tasa_usd, _ = obtener_tasas_bcv()
        return tasa_usd
    except Exception as e:
        print(f"Error obteniendo tasa BCV: {e}")
        return 201.4665  # Valor de fallback más actual

def main():
    print("\n=== TASAS DE CAMBIO BCV ===")
    print(f"Fecha y hora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 30)

    # Obtener tasas del BCV
    tasa_usd, tasa_eur = obtener_tasas_bcv()

    # Mostrar tasas actuales
    print("\nTasas Oficiales BCV:")
    print(f"USD/BS: {tasa_usd:.2f}")
    print(f"EUR/BS: {tasa_eur:.2f}")
    print("-" * 30)

    # Calculadora
    print("\n=== CALCULADORA DE CONVERSIÓN ===")
    while True:
        try:
            # Obtener monto y moneda
            monto = input("\nIngrese el monto (o 'q' para salir): ")
            if monto.lower() == 'q':
                break

            print("\nSeleccione la moneda de origen:")
            print("1. USD (Dólares)")
            print("2. EUR (Euros)")
            print("3. BS (Bolívares)")
            opcion = input("Opción (1-3): ")

            moneda_origen = None
            if opcion == '1':
                moneda_origen = 'USD'
            elif opcion == '2':
                moneda_origen = 'EUR'
            elif opcion == '3':
                moneda_origen = 'BS'
            else:
                print("Opción no válida")
                continue

            # Calcular conversión
            resultado = calcular_conversion(monto, moneda_origen, tasa_usd, tasa_eur)
            if resultado:
                print("\nResultados de la conversión:")
                print(f"USD: ${resultado['USD']:.2f}")
                print(f"EUR: €{resultado['EUR']:.2f}")
                print(f"BS: {resultado['BS']:.2f}")

        except ValueError:
            print("Por favor ingrese un monto válido")
        except Exception as e:
            print(f"Error: {e}")

    print("\n¡Gracias por usar la calculadora!")

if __name__ == "__main__":
    main() 