# 🧮 Calculadora Universal del Sistema

## 📋 Descripción

La Calculadora Universal es un componente reutilizable que permite convertir montos entre diferentes monedas (USD, EUR, BS) utilizando las tasas de cambio del BCV (Banco Central de Venezuela). Esta calculadora está disponible en todo el sistema a través de un botón flotante.

## ✨ Características

### 🎯 Funcionalidades Principales
- **Conversión Multi-Moneda**: USD ↔ EUR ↔ Bolívares (BS)
- **Tasas Actualizadas**: Obtiene tasas en tiempo real del BCV
- **Interfaz Moderna**: Diseño glassmorphism con animaciones suaves
- **Botón Flotante**: Acceso rápido desde cualquier página
- **Responsive**: Optimizada para móviles y escritorio

### 🔧 Características Técnicas
- **API Integration**: Conecta con `/api/tasas-actualizadas`
- **Fallback Local**: Carga tasas locales si la API falla
- **Auto-actualización**: Actualiza tasas cada 5 minutos
- **Formateo Inteligente**: Separadores de miles automáticos
- **Validación**: Verificación de montos y tasas válidas

## 🚀 Implementación

### 📁 Archivos Creados

```
templates/partials/
├── calculadora_modal.html      # Modal HTML de la calculadora
└── calculadora_includes.html   # Incluye CSS, JS y modal

static/
├── css/calculadora.css         # Estilos de la calculadora
└── js/calculadora.js          # Lógica JavaScript

CALCULADORA_UNIVERSAL.md       # Esta documentación
```

### 🔗 Integración en el Sistema

La calculadora se incluye automáticamente en todas las páginas a través del `base.html`:

```html
<!-- En templates/base.html -->
{% include 'partials/calculadora_includes.html' %}
```

## 🎨 Diseño y UX

### 🎭 Elementos Visuales
- **Botón Flotante**: Esquina inferior derecha, color verde degradado
- **Modal Glassmorphism**: Efectos de cristal translúcido
- **Animaciones**: Entrada suave, hover effects, transiciones
- **Iconografía**: Font Awesome para iconos consistentes
- **Colores**: Paleta verde/azul para confianza financiera

### 📱 Responsive Design
- **Mobile First**: Optimizado para pantallas pequeñas
- **Touch Friendly**: Botones y campos táctiles
- **Adaptive Layout**: Se ajusta automáticamente al tamaño

## 💻 Uso

### 🖱️ Acceso
1. **Botón Flotante**: Click en el ícono de calculadora (esquina inferior derecha)
2. **Automático**: Se abre en cualquier página del sistema

### 🔄 Funcionamiento
1. **Ingresar Monto**: Escribir cantidad a convertir
2. **Seleccionar Moneda**: Elegir moneda de origen (USD/EUR/BS)
3. **Ver Conversiones**: Resultados automáticos en tiempo real
4. **Actualizar Tasas**: Botón para refrescar tasas del BCV

### ⚙️ Controles
- **Monto**: Campo numérico con formateo automático
- **Moneda**: Dropdown con banderas y nombres
- **Tasas**: Campos editables para tasas personalizadas
- **Botones**: Actualizar, Limpiar, Cerrar

## 🔧 API y Backend

### 📡 Endpoints Utilizados
- `GET /api/tasas-actualizadas` - Tasas actualizadas del BCV
- `GET /api/tasa-bcv` - Tasa básica USD/BS

### 🔄 Flujo de Datos
1. **Carga Inicial**: Obtiene tasas al abrir el modal
2. **Actualización**: Refresh automático cada 5 minutos
3. **Fallback**: Usa tasas locales si falla la API
4. **Cálculo**: Conversiones en tiempo real

## 🎯 Casos de Uso

### 💼 En Facturas
- Convertir totales de facturas a diferentes monedas
- Verificar equivalencias para clientes internacionales
- Calcular comisiones en diferentes monedas

### 📦 En Inventario
- Convertir precios de productos
- Calcular costos en moneda local
- Actualizar precios según tasas

### 👥 En Clientes
- Mostrar saldos en diferentes monedas
- Calcular deudas en moneda preferida
- Generar reportes multi-moneda

### 🛠️ En Servicio Técnico
- Convertir costos de reparación
- Calcular presupuestos en moneda local
- Mostrar precios a clientes

## 🔧 Personalización

### 🎨 Estilos CSS
```css
/* Personalizar colores */
:root {
    --calc-primary: #28a745;
    --calc-secondary: #20c997;
    --calc-accent: #ffc107;
}

/* Personalizar botón flotante */
.btn-floating-calc {
    background: linear-gradient(135deg, var(--calc-primary) 0%, var(--calc-secondary) 100%);
}
```

### ⚙️ Configuración JavaScript
```javascript
// Cambiar intervalo de actualización (en milisegundos)
setInterval(actualizarTasas, 10 * 60 * 1000); // 10 minutos

// Personalizar monedas disponibles
const monedas = ['USD', 'EUR', 'BS', 'COP']; // Agregar más monedas
```

## 🐛 Solución de Problemas

### ❌ Problemas Comunes

#### **Tasas no se cargan**
- **Causa**: Error en API del BCV
- **Solución**: La calculadora usa fallback local automáticamente

#### **Botón no aparece**
- **Causa**: CSS no cargado
- **Solución**: Verificar que `calculadora.css` esté incluido

#### **Modal no se abre**
- **Causa**: JavaScript no cargado
- **Solución**: Verificar que `calculadora.js` esté incluido

#### **Cálculos incorrectos**
- **Causa**: Tasas inválidas
- **Solución**: Actualizar tasas manualmente con el botón

### 🔍 Debug
```javascript
// Verificar estado de la calculadora
console.log('Calculadora cargada:', typeof actualizarCalculadora);

// Verificar tasas cargadas
console.log('Tasa USD:', document.getElementById('calcTasaBCV').value);
console.log('Tasa EUR:', document.getElementById('calcTasaBCVEUR').value);
```

## 📈 Mejoras Futuras

### 🚀 Funcionalidades Planificadas
- **Historial de Conversiones**: Guardar conversiones recientes
- **Favoritos**: Monedas preferidas del usuario
- **Gráficos**: Visualización de tendencias de tasas
- **Exportar**: Guardar resultados en PDF/Excel
- **Notificaciones**: Alertas de cambios de tasas
- **Temas**: Modo oscuro/claro

### 🔧 Mejoras Técnicas
- **Service Worker**: Cache de tasas offline
- **WebSocket**: Actualizaciones en tiempo real
- **PWA**: Funcionalidad offline
- **Tests**: Suite de pruebas automatizadas

## 📚 Documentación Técnica

### 🏗️ Arquitectura
```
Frontend (HTML/CSS/JS)
    ↓
API Layer (Flask Routes)
    ↓
External APIs (BCV, Monitor Dólar)
    ↓
Data Processing & Caching
```

### 🔄 Flujo de Datos
1. **Usuario** abre calculadora
2. **Frontend** solicita tasas a API
3. **Backend** consulta fuentes externas
4. **API** retorna tasas formateadas
5. **Frontend** calcula conversiones
6. **UI** muestra resultados

### 📊 Estructura de Datos
```json
{
  "tasa_bcv": 197.2456,
  "tasa_bcv_eur": 226.8324,
  "fecha_actualizacion": "2025-01-13T21:49:05Z"
}
```

## 🎉 Conclusión

La Calculadora Universal es un componente esencial que mejora significativamente la experiencia del usuario al proporcionar conversiones de moneda rápidas, precisas y visualmente atractivas. Su implementación modular permite fácil mantenimiento y futuras mejoras.

### ✅ Beneficios
- **Productividad**: Conversiones instantáneas
- **Precisión**: Tasas actualizadas del BCV
- **Usabilidad**: Interfaz intuitiva y moderna
- **Confiabilidad**: Fallback automático
- **Escalabilidad**: Fácil de extender y personalizar

---

*Desarrollado con ❤️ para el Sistema de Reparaciones*















