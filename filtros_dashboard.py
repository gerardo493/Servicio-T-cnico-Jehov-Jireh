from datetime import datetime
import json
import os

# Constantes del sistema
ARCHIVO_CLIENTES = 'clientes.json'
ARCHIVO_INVENTARIO = 'inventario.json'
ARCHIVO_NOTAS_ENTREGA = 'notas_entrega_json/notas_entrega.json'
ULTIMA_TASA_BCV_FILE = 'ultima_tasa_bcv.json'

def cargar_datos(archivo):
    """Carga datos desde un archivo JSON."""
    try:
        if os.path.exists(archivo):
            with open(archivo, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    except Exception as e:
        print(f"Error cargando {archivo}: {e}")
        return {}

def obtener_tasa_bcv():
    """Obtiene la tasa BCV actual."""
    try:
        if not os.path.exists(ULTIMA_TASA_BCV_FILE):
            return 36.0  # Tasa por defecto
        
        with open(ULTIMA_TASA_BCV_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            tasa = float(data.get('tasa', 36.0))
            return tasa if tasa > 10 else 36.0
    except Exception:
        return 36.0

def obtener_estadisticas_filtradas(filtro_tipo=None, filtro_valor=None, tarjeta=None):
    """Obtiene estadísticas para el dashboard con filtros opcionales por tarjeta."""
    clientes = cargar_datos(ARCHIVO_CLIENTES)
    inventario = cargar_datos(ARCHIVO_INVENTARIO)
    notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
    
    # Aplicar filtros de fecha si se especifican
    notas_filtradas = notas
    if filtro_tipo and filtro_valor:
        notas_filtradas = {}
        try:
            for nota_id, nota in notas.items():
                fecha_nota = datetime.strptime(nota['fecha'], '%Y-%m-%d')
                hoy = datetime.now()
                
                if filtro_tipo == 'año' and fecha_nota.year == int(filtro_valor):
                    notas_filtradas[nota_id] = nota
                elif filtro_tipo == 'mes' and fecha_nota.month == int(filtro_valor) and fecha_nota.year == datetime.now().year:
                    notas_filtradas[nota_id] = nota
                elif filtro_tipo == 'dia' and fecha_nota.day == int(filtro_valor):
                    notas_filtradas[nota_id] = nota
                elif filtro_tipo == 'hoy' and fecha_nota.date() == hoy.date():
                    notas_filtradas[nota_id] = nota
                elif filtro_tipo == 'fecha_especifica' and fecha_nota.date() == datetime.strptime(filtro_valor, '%Y-%m-%d').date():
                    notas_filtradas[nota_id] = nota
        except (ValueError, KeyError) as e:
            print(f"Error aplicando filtro: {e}")
            notas_filtradas = notas
    
    mes_actual = datetime.now().month
    total_clientes = len(clientes)
    total_productos = len(inventario)
    # Usar las notas filtradas en lugar del mes actual
    notas_mes = len(notas_filtradas)
    
    # Calcular cuentas por cobrar
    total_cobrar_usd = 0
    for n in notas_filtradas.values():
        total_nota = float(n.get('total_usd', 0))
        total_abonado = float(n.get('total_abonado', 0))
        saldo = max(0, total_nota - total_abonado)
        if saldo > 0:  # Considerar cualquier saldo mayor a 0
            total_cobrar_usd += saldo
    
    # Obtener tasa BCV
    tasa_bcv = obtener_tasa_bcv()
    total_cobrar_bs = total_cobrar_usd * tasa_bcv
    
    # Crear lista de notas con ID incluido para el dashboard
    notas_con_id = []
    for nota_id, nota in notas_filtradas.items():
        nota_copia = nota.copy()
        nota_copia['id'] = nota_id  # Agregar el ID a la nota
        notas_con_id.append(nota_copia)
    
    ultimas_notas = sorted(notas_con_id, key=lambda x: datetime.strptime(x['fecha'], '%Y-%m-%d'), reverse=True)[:5]
    productos_bajo_stock = [p for p in inventario.values() if int(p.get('cantidad', p.get('stock', 0))) < 10]
    
    # Calcular pagos recibidos
    total_pagos_recibidos_usd = 0
    total_pagos_recibidos_bs = 0
    for n in notas_filtradas.values():
        if 'pagos' in n and n['pagos']:
            for pago in n['pagos']:
                fecha_nota = n.get('fecha', '')
                try:
                    if fecha_nota and datetime.strptime(fecha_nota, '%Y-%m-%d').month == mes_actual:
                        monto = float(pago.get('monto', 0))
                        total_pagos_recibidos_usd += monto
                        total_pagos_recibidos_bs += monto * float(n.get('tasa_bcv', tasa_bcv))
                except Exception:
                    continue
    
    # Calcular total facturado
    total_facturado_usd = sum(float(n.get('total_usd', 0)) for n in notas_filtradas.values())
    cantidad_notas = len(notas_filtradas)
    promedio_nota_usd = total_facturado_usd / cantidad_notas if cantidad_notas > 0 else 0
    
    return {
        'total_clientes': total_clientes,
        'total_productos': total_productos,
        'notas_mes': notas_mes,
        'total_cobrar': f"{total_cobrar_usd:,.2f}",
        'total_cobrar_usd': total_cobrar_usd,
        'total_cobrar_bs': total_cobrar_bs,
        'tasa_bcv': tasa_bcv,
        'ultimas_notas': ultimas_notas,
        'productos_bajo_stock': productos_bajo_stock,
        'total_pagos_recibidos_usd': total_pagos_recibidos_usd,
        'total_pagos_recibidos_bs': total_pagos_recibidos_bs,
        'total_facturado_usd': total_facturado_usd,
        'promedio_nota_usd': promedio_nota_usd,
        'cantidad_notas': cantidad_notas,
        'filtro_aplicado': {
            'tipo': filtro_tipo,
            'valor': filtro_valor
        } if filtro_tipo else None
    }

def obtener_metricas_tarjeta(tarjeta, filtro_tipo=None, filtro_valor=None):
    """Obtiene métricas específicas para una tarjeta individual."""
    notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
    tasa_bcv = obtener_tasa_bcv()
    
    # Aplicar filtros de fecha si se especifican
    notas_filtradas = notas
    if filtro_tipo and filtro_valor:
        notas_filtradas = {}
        try:
            for nota_id, nota in notas.items():
                fecha_nota = datetime.strptime(nota['fecha'], '%Y-%m-%d')
                hoy = datetime.now()
                
                if filtro_tipo == 'año' and fecha_nota.year == int(filtro_valor):
                    notas_filtradas[nota_id] = nota
                elif filtro_tipo == 'mes' and fecha_nota.month == int(filtro_valor):
                    notas_filtradas[nota_id] = nota
                elif filtro_tipo == 'hoy' and fecha_nota.date() == hoy.date():
                    notas_filtradas[nota_id] = nota
                elif filtro_tipo == 'semana' and fecha_nota.isocalendar()[1] == int(filtro_valor):
                    notas_filtradas[nota_id] = nota
                elif filtro_tipo == 'mes_especifico' and fecha_nota.month == int(filtro_valor) and fecha_nota.year == datetime.now().year:
                    notas_filtradas[nota_id] = nota
                elif filtro_tipo == 'fecha_especifica' and fecha_nota.date() == datetime.strptime(filtro_valor, '%Y-%m-%d').date():
                    notas_filtradas[nota_id] = nota
        except (ValueError, KeyError) as e:
            print(f"Error aplicando filtro: {e}")
            notas_filtradas = notas
    
    if tarjeta == 'cobranza':
        # Calcular cuentas por cobrar
        total_cobrar_usd = 0
        for n in notas_filtradas.values():
            total_nota = float(n.get('total_usd', 0))
            total_abonado = float(n.get('total_abonado', 0))
            saldo = max(0, total_nota - total_abonado)
            if saldo > 0:
                total_cobrar_usd += saldo
        
        total_cobrar_bs = total_cobrar_usd * tasa_bcv
        return {
            'total_cobrar_usd': total_cobrar_usd,
            'total_cobrar_bs': total_cobrar_bs,
            'cantidad_notas': len(notas_filtradas)
        }
    
    elif tarjeta == 'pagos':
        # Calcular pagos recibidos
        total_pagos_recibidos_usd = 0
        total_pagos_recibidos_bs = 0
        for n in notas_filtradas.values():
            if 'pagos' in n and n['pagos']:
                for pago in n['pagos']:
                    monto = float(pago.get('monto', 0))
                    total_pagos_recibidos_usd += monto
                    total_pagos_recibidos_bs += monto * float(n.get('tasa_bcv', tasa_bcv))
        
        return {
            'total_pagos_recibidos_usd': total_pagos_recibidos_usd,
            'total_pagos_recibidos_bs': total_pagos_recibidos_bs,
            'cantidad_notas': len(notas_filtradas)
        }
    
    elif tarjeta == 'facturado':
        # Calcular total facturado
        total_facturado_usd = sum(float(n.get('total_usd', 0)) for n in notas_filtradas.values())
        cantidad_notas = len(notas_filtradas)
        promedio_nota_usd = total_facturado_usd / cantidad_notas if cantidad_notas > 0 else 0
        
        return {
            'total_facturado_usd': total_facturado_usd,
            'promedio_nota_usd': promedio_nota_usd,
            'cantidad_notas': cantidad_notas
        }
    
    return {}

def obtener_opciones_filtro():
    """Obtiene las opciones disponibles para los filtros."""
    notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
    
    años = set()
    meses = set()
    dias = set()
    semanas = set()
    
    for nota in notas.values():
        try:
            fecha = datetime.strptime(nota['fecha'], '%Y-%m-%d')
            años.add(fecha.year)
            meses.add(fecha.month)
            dias.add(fecha.day)
            semanas.add(fecha.isocalendar()[1])  # Número de semana
        except (ValueError, KeyError):
            continue
    
    return {
        'años': sorted(list(años), reverse=True),
        'meses': sorted(list(meses)),
        'dias': sorted(list(dias)),
        'semanas': sorted(list(semanas))
    }

def obtener_opciones_filtro_avanzado():
    """Obtiene las opciones para filtros avanzados con menús anidados."""
    notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)
    
    # Obtener semanas del año actual
    semanas_actuales = set()
    for nota in notas.values():
        try:
            fecha = datetime.strptime(nota['fecha'], '%Y-%m-%d')
            if fecha.year == datetime.now().year:
                semanas_actuales.add(fecha.isocalendar()[1])
        except (ValueError, KeyError):
            continue
    
    # Obtener meses con datos
    meses_con_datos = set()
    for nota in notas.values():
        try:
            fecha = datetime.strptime(nota['fecha'], '%Y-%m-%d')
            meses_con_datos.add(fecha.month)
        except (ValueError, KeyError):
            continue
    
    # Generar opciones de semanas
    opciones_semanas = []
    for semana in sorted(semanas_actuales):
        opciones_semanas.append({
            'valor': semana,
            'texto': f'Semana {semana}'
        })
    
    # Generar opciones de meses
    nombres_meses = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
                    'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
    
    opciones_meses = []
    for mes in sorted(meses_con_datos):
        opciones_meses.append({
            'valor': mes,
            'texto': nombres_meses[mes]
        })
    
    return {
        'semanas': opciones_semanas,
        'meses': opciones_meses
    }



def obtener_opciones_filtro():

    """Obtiene las opciones disponibles para los filtros."""

    notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)

    

    años = set()

    meses = set()

    dias = set()

    semanas = set()

    

    for nota in notas.values():

        try:

            fecha = datetime.strptime(nota['fecha'], '%Y-%m-%d')

            años.add(fecha.year)

            meses.add(fecha.month)

            dias.add(fecha.day)

            semanas.add(fecha.isocalendar()[1])  # Número de semana

        except (ValueError, KeyError):

            continue

    

    return {

        'años': sorted(list(años), reverse=True),

        'meses': sorted(list(meses)),

        'dias': sorted(list(dias)),

        'semanas': sorted(list(semanas))

    }



def obtener_opciones_filtro_avanzado():

    """Obtiene las opciones para filtros avanzados con menús anidados."""

    notas = cargar_datos(ARCHIVO_NOTAS_ENTREGA)

    

    # Obtener semanas del año actual

    semanas_actuales = set()

    for nota in notas.values():

        try:

            fecha = datetime.strptime(nota['fecha'], '%Y-%m-%d')

            if fecha.year == datetime.now().year:

                semanas_actuales.add(fecha.isocalendar()[1])

        except (ValueError, KeyError):

            continue

    

    # Obtener meses con datos

    meses_con_datos = set()

    for nota in notas.values():

        try:

            fecha = datetime.strptime(nota['fecha'], '%Y-%m-%d')

            meses_con_datos.add(fecha.month)

        except (ValueError, KeyError):

            continue

    

    # Generar opciones de semanas

    opciones_semanas = []

    for semana in sorted(semanas_actuales):

        opciones_semanas.append({

            'valor': semana,

            'texto': f'Semana {semana}'

        })

    

    # Generar opciones de meses

    nombres_meses = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',

                    'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']

    

    opciones_meses = []

    for mes in sorted(meses_con_datos):

        opciones_meses.append({

            'valor': mes,

            'texto': nombres_meses[mes]

        })

    

    return {

        'semanas': opciones_semanas,

        'meses': opciones_meses

    }
