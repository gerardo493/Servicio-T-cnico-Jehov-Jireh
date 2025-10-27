// ===== SISTEMA DE VALIDACIÓN ROBUSTA =====
class PaymentValidator {
    constructor() {
        this.errors = new Map();
        this.validationRules = {
            amount: {
                required: true,
                min: 0.01,
                max: null, // Se establece dinámicamente
                pattern: /^\d+(\.\d{1,2})?$/,
                message: 'El monto debe ser un número positivo válido'
            }
        };
    }

    validateAmount(value, maxAmount) {
        const errors = [];
        const numValue = parseFloat(value);

        // Validar que sea un número
        if (isNaN(numValue)) {
            errors.push('El monto debe ser un número válido');
            return errors;
        }

        // Validar que sea positivo
        if (numValue <= 0) {
            errors.push('El monto debe ser mayor a 0');
        }

        // Validar que no exceda el máximo
        if (maxAmount && numValue > maxAmount) {
            errors.push(`El monto no puede exceder $${maxAmount.toFixed(2)}`);
        }

        // Validar formato decimal
        if (!this.validationRules.amount.pattern.test(value)) {
            errors.push('Formato de monto inválido (use punto para decimales)');
        }

        return errors;
    }

    showFieldError(fieldId, errors) {
        const field = document.getElementById(fieldId);
        const errorElement = document.getElementById(`${fieldId}_error`);
        
        if (errors.length > 0) {
            field.classList.add('is-invalid');
            if (errorElement) {
                errorElement.textContent = errors[0];
                errorElement.style.display = 'block';
            }
        } else {
            field.classList.remove('is-invalid');
            if (errorElement) {
                errorElement.style.display = 'none';
            }
        }
    }

    clearAllErrors() {
        document.querySelectorAll('.is-invalid').forEach(field => {
            field.classList.remove('is-invalid');
        });
        document.querySelectorAll('[id$="_error"]').forEach(error => {
            error.style.display = 'none';
        });
    }
}

// Instancia global del validador
const paymentValidator = new PaymentValidator();

// ===== FUNCIONES REFACTORIZADAS =====
function abrirModalPago() {
    // Validaciones iniciales
    if (!notaActual) {
        showNotification('Debe guardar la nota primero', 'error');
        return;
    }
    
    if (!notaActual.subtotal_usd || notaActual.subtotal_usd <= 0) {
        showNotification('La nota no tiene un total válido', 'error');
        return;
    }
    
    // Limpiar errores previos
    paymentValidator.clearAllErrors();
    
    // Calcular datos financieros
    const totalNota = parseFloat(notaActual.subtotal_usd || 0);
    const pagadoActual = calcularPagadoActual();
    const saldoPendiente = totalNota - pagadoActual;
    
    // Actualizar metadatos
    actualizarMetadatosNota(pagadoActual, saldoPendiente);
    
    // Llenar información del modal
    llenarInformacionModal(totalNota, pagadoActual, saldoPendiente);
    
    // Configurar validación del monto
    configurarValidacionMonto(saldoPendiente);
    
    // Mostrar modal
    const modal = new bootstrap.Modal(document.getElementById('modalPago'));
    modal.show();
}

function calcularPagadoActual() {
    if (!notaActual.pagos || !Array.isArray(notaActual.pagos)) {
        return 0;
    }
    return notaActual.pagos.reduce((sum, pago) => {
        const monto = parseFloat(pago.monto || 0);
        return sum + (isNaN(monto) ? 0 : monto);
    }, 0);
}

function actualizarMetadatosNota(pagadoActual, saldoPendiente) {
    notaActual.pagado_usd = pagadoActual;
    notaActual.saldo_pendiente_usd = saldoPendiente;
    
    if (saldoPendiente <= 0) {
        notaActual.estado_cobro = 'COBRO_TOTAL';
    } else if (pagadoActual > 0) {
        notaActual.estado_cobro = 'COBRO_PARCIAL';
    } else {
        notaActual.estado_cobro = 'COBRO_PENDIENTE';
    }
}

function llenarInformacionModal(totalNota, pagadoActual, saldoPendiente) {
    // Información básica
    document.getElementById('nota_id_pago').value = notaActual.numero || '';
    document.getElementById('nota_numero_pago').textContent = notaActual.numero || 'N/A';
    document.getElementById('nota_numero_header').textContent = notaActual.numero || 'N/A';
    document.getElementById('cliente_nombre_pago').textContent = notaActual.cliente_nombre || 'N/A';
    document.getElementById('fecha_nota_pago').textContent = notaActual.fecha || 'N/A';
    
    // Información financiera
    document.getElementById('total_pagar_pago').textContent = `$${totalNota.toFixed(2)}`;
    document.getElementById('resumen_pagado').textContent = `$${pagadoActual.toFixed(2)}`;
    document.getElementById('resumen_saldo_restante').textContent = `$${saldoPendiente.toFixed(2)}`;
    
    // Estado
    const estadoElement = document.getElementById('estado_actual_pago');
    estadoElement.textContent = notaActual.estado_cobro || 'COBRO_PENDIENTE';
    estadoElement.className = `badge bg-${getEstadoColor(notaActual.estado_cobro)}`;
    
    // Tasa BCV
    const tasaBcv = parseFloat(notaActual.tasa_bcv || 1);
    document.getElementById('tasa_bcv').textContent = tasaBcv.toFixed(4);
    document.getElementById('tasa_bcv_display').textContent = tasaBcv.toFixed(4);
}

function configurarValidacionMonto(saldoPendiente) {
    const montoInput = document.getElementById('monto_pago');
    const montoMaximoText = document.getElementById('monto_maximo_text');
    
    if (saldoPendiente <= 0) {
        montoInput.disabled = true;
        montoInput.value = '0';
        montoMaximoText.textContent = 'Nota completamente pagada';
        showNotification('Esta nota ya está completamente pagada', 'info');
    } else {
        montoInput.disabled = false;
        montoInput.value = '';
        montoInput.max = saldoPendiente;
        montoInput.setAttribute('max', saldoPendiente);
        montoMaximoText.textContent = `Máximo: $${saldoPendiente.toFixed(2)} USD`;
        showNotification(`Ingresa el monto que deseas abonar (máximo: $${saldoPendiente.toFixed(2)})`, 'info');
    }
}

function procesarPago() {
    const form = document.getElementById('formPago');
    const formData = new FormData(form);
    
    // Limpiar errores previos
    paymentValidator.clearAllErrors();
    
    // Validar formulario
    if (!form.checkValidity()) {
        form.reportValidity();
        return;
    }
    
    // Obtener datos del formulario
    const monto = parseFloat(formData.get('monto'));
    const totalNota = parseFloat(notaActual.subtotal_usd || 0);
    const pagadoActual = calcularPagadoActual();
    const saldoPendiente = totalNota - pagadoActual;
    
    // Validar monto con el validador robusto
    const montoErrors = paymentValidator.validateAmount(monto, saldoPendiente);
    if (montoErrors.length > 0) {
        paymentValidator.showFieldError('monto_pago', montoErrors);
        return;
    }
    
    // Validaciones adicionales de negocio
    if (monto > saldoPendiente) {
        const errorMsg = `El monto no puede ser mayor al saldo pendiente ($${saldoPendiente.toFixed(2)})`;
        paymentValidator.showFieldError('monto_pago', [errorMsg]);
        return;
    }

    if (monto <= 0) {
        paymentValidator.showFieldError('monto_pago', ['El monto debe ser mayor a 0']);
        return;
    }
    
    // Mostrar loading
    const btnProcesar = document.querySelector('#modalPago .btn-success');
    const originalText = btnProcesar.innerHTML;
    btnProcesar.innerHTML = '<div class="spinner-border spinner-border-sm me-2"></div>Procesando...';
    btnProcesar.disabled = true;
    
    // Enviar pago
    fetch(`/notas-entrega/${notaActual.numero}/procesar-pago`, {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showNotification('Pago procesado exitosamente', 'success');
            
            // Cerrar modal
            const modal = bootstrap.Modal.getInstance(document.getElementById('modalPago'));
            modal.hide();
            
            // Actualizar estado de la nota
            if (data.nota) {
                notaActual = data.nota;
                actualizarEstadoNota();
            }
            
            // Recargar página después de un momento
            setTimeout(() => {
                window.location.reload();
            }, 1500);
        } else {
            throw new Error(data.message || 'Error procesando pago');
        }
    })
    .catch(error => {
        console.error('Error procesando pago:', error);
        showNotification('Error procesando pago: ' + error.message, 'error');
    })
    .finally(() => {
        btnProcesar.innerHTML = originalText;
        btnProcesar.disabled = false;
    });
}

// Event listeners refactorizados
function setupPaymentEventListeners() {
    // Validación en tiempo real del monto
    document.getElementById('monto_pago').addEventListener('input', function() {
        const monto = this.value;
        const maxAmount = parseFloat(this.getAttribute('max')) || 0;
        
        if (monto) {
            const errors = paymentValidator.validateAmount(monto, maxAmount);
            paymentValidator.showFieldError('monto_pago', errors);
        } else {
            paymentValidator.showFieldError('monto_pago', []);
        }
        
        // Actualizar resumen
        actualizarResumenPago();
    });
    
    // Actualizar resumen cuando cambie la moneda
    document.getElementById('moneda_pago').addEventListener('change', function() {
        const monto = parseFloat(document.getElementById('monto_pago').value) || 0;
        calcularEquivalenteBolivares(monto);
    });
    
    // Manejar selección de banco
    document.getElementById('banco_pago').addEventListener('change', function() {
        const bancoOtro = document.getElementById('banco_otro');
        const labelBancoOtro = document.getElementById('label_banco_otro');
        
        if (this.value === 'otro') {
            bancoOtro.style.display = 'block';
            labelBancoOtro.style.display = 'block';
            bancoOtro.required = true;
        } else {
            bancoOtro.style.display = 'none';
            labelBancoOtro.style.display = 'none';
            bancoOtro.required = false;
            bancoOtro.value = '';
        }
    });
    
    // Limpiar formulario cuando se cierre el modal
    document.getElementById('modalPago').addEventListener('hidden.bs.modal', function() {
        document.getElementById('formPago').reset();
        paymentValidator.clearAllErrors();
        // Ocultar campo "Otro" al cerrar
        document.getElementById('banco_otro').style.display = 'none';
        document.getElementById('label_banco_otro').style.display = 'none';
    });
}


