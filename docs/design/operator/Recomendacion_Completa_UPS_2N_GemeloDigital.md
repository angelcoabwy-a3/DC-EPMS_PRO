# Recomendación Técnica Completa – Gemelo Digital de Potencia  
## UPS Double Conversion 2N + Generación MV  
**Carga IT de diseño:** 16.76 MW por path  
**Fecha:** 13 de noviembre de 2026  
**Objetivo:** Diseño listo para modelado de alta fidelidad (tope de gama del gemelo digital)

---

## 1. Decisiones Cerradas (Listas para el Modelo)

| # | Decisión | Valor Final | Justificación |
|---|----------|-------------|---------------|
| 1 | Bloques UPS por path | **8 × Vertiv Trinergy 2500** | Permite N+1 real dentro del path (7 × 2.5 MW = 17.5 MW > 16.76 MW) |
| 2 | Nombre del UPS | **Vertiv Trinergy 2500 kW** (Double Conversion / VFI) | Producto real, modular (núcleos 500 kW), eficiencia alta |
| 3 | Voltaje de generación | **13.8 kV** | Estándar Norteamérica, menor corriente, óptimo a esta escala |
| 4 | Generadores por path | **9 × 2.5 MW** (o 8 × 2.75 MW) | Cubre IT + refrigeración + pérdidas + margen + N+1 |
| 5 | Transferencia | **Controlador de transferencia MV** (no ATS de 480 V) | Compatible con generación y distribución en 13.8 kV |

**Total sistema 2N:**
- UPS: 16 × Vertiv Trinergy 2500
- Generadores: 18 × 2.5 MW (9 por path)

---

## 2. Corrección de Pérdidas UPS (Eficiencia Energética)

### 2.1 Cálculo correcto de pérdidas

Eficiencia Double Conversion típica Vertiv Trinergy 2500: **96.8 – 97.5 %** (usamos 97.0 % promedio).

Fórmula de pérdidas:
\[
P_{\text{pérdidas}} = P_{\text{salida}} \times \left( \frac{1}{\eta} - 1 \right)
\]

| Escenario | Carga por path | Eficiencia | Pérdidas correctas | Comentario |
|-----------|----------------|------------|--------------------|----------|
| Operación normal 2N (50 %) | 8.38 MW | 97.0 % | **≈ 259 kW** | Valor realista |
| Un path lleva 100 % (falla del otro) | 16.76 MW | 97.0 % | **≈ 518 kW** | Coincide con el rango alto anterior |
| Modo Dynamic Online / ECO | 8.38 MW | 99.0 % | **≈ 85 kW** | Gran ahorro |

**Corrección aplicada:**  
Los 450–520 kW anteriores correspondían al escenario de **100 % de carga**, no al 50 %. En operación normal 2N las pérdidas por path son **≈ 250–280 kW**.

### 2.2 Análisis de eficiencia energética del sistema completo

| Componente | Pérdidas estimadas (operación normal 2N) | % del total |
|------------|------------------------------------------|-------------|
| UPS Double Conversion (ambas rutas) | 500–560 kW | 40–45 % |
| Transformadores step-down (MV→480 V) | 250–350 kW | 20–25 % |
| Cables / busways MV + LV | 80–120 kW | 7–10 % |
| Switchgear + protecciones | 40–60 kW | 3–5 % |
| Generadores (en standby / test) | Variable | — |
| **Total pérdidas eléctricas estimadas** | **≈ 900–1.100 kW** | — |

**Impacto en PUE:**  
Estas pérdidas deben sumarse a la carga de refrigeración de salas eléctricas. Un diseño con modo Dynamic Online habilitado puede reducir 300–400 kW de pérdidas permanentes.

**Recomendación de modelado:**  
- Modelar dos curvas de eficiencia: VFI (Double Conversion) y Dynamic Online.  
- Incluir derating por temperatura y envejecimiento.  
- Permitir simulación de conmutación automática entre modos según calidad de red.

---

## 3. Redundancia UPS – Corrección Importante

| Configuración | Capacidad con N-1 | ¿Cubre 16.76 MW? | Comentario |
|---------------|-------------------|------------------|------------|
| 7 × 2.5 MW | 15.0 MW | **No** | Insuficiente para N+1 dentro del path |
| **8 × 2.5 MW** | **17.5 MW** | **Sí** | **Recomendado** – permite sacar 1 bloque a mantenimiento |
| 9 × 2.5 MW | 20.0 MW | Sí | Solo si se busca crecimiento agresivo |

**Decisión final:** **8 × Vertiv Trinergy 2500 por path**.

Esto da:
- Capacidad instalada por path: **20.0 MW**
- Capacidad N+1 (7 bloques): **17.5 MW** (> 16.76 MW)
- Headroom N: +19.3 %
- Headroom N+1: +4.4 %

---

## 4. Dimensionamiento de Generadores (Completo)

La carga de generación **no es solo la carga IT**.

### 4.1 Carga real que deben cubrir los generadores (por path)

| Concepto | Valor estimado | Notas |
|----------|----------------|-------|
| Carga IT | 16.76 MW | Base |
| Pérdidas UPS (100 % path) | 0.52 MW | Al fallar el otro path |
| Refrigeración de salas eléctricas + UPS | 0.4–0.6 MW | Aproximado |
| Carga de chilling / CRAH / CDUs (si están en UPS) | Variable | Crítico definir |
| Margen de arranque + crecimiento | 15–25 % | Estándar |
| **Carga total de generación por path** | **≈ 20.5 – 23 MW** | Valor de diseño |

### 4.2 Configuración recomendada de generadores

| Parámetro | Valor Recomendado |
|-----------|-------------------|
| Tamaño unitario | **2.5 MW** (rating Data Center Continuous / Prime) |
| Unidades por path | **9** |
| Configuración | N+1 dentro de cada path de 2N |
| Capacidad N (8 unidades) | 20.0 MW |
| Capacidad N+1 (9 unidades) | 22.5 MW |
| Voltaje | **13.8 kV** |
| Total sistema 2N | **18 generadores** |

**Alternativa de alta densidad:** 8 × 2.75–3.0 MW por path (si el fabricante lo ofrece con buen rating continuo).

### 4.3 Rango de tamaños de generadores a considerar en el gemelo

Para flexibilidad del modelo digital se recomienda soportar el siguiente rango de bloques de generación:

| Rango | Uso típico | Comentario |
|-------|------------|----------|
| 1.5 – 2.0 MW | Bloques pequeños / faseado | Más unidades, mayor modularidad |
| **2.25 – 2.75 MW** | **Rango óptimo** | Mejor equilibrio actual |
| 3.0 – 3.5 MW | Alta densidad | Menos unidades, mayor impacto de falla unitaria |

---

## 5. Transferencia y Controles

- **No existe ATS de 480 V** cuando la generación y la transferencia principal están en media tensión.
- El “panel del ATS” se convierte en un **Controlador de Transferencia Automática de Media Tensión** (o lógica de breakers con sincronización).
- Fabricantes típicos a modelar: ASCO, Russelectric, Cummins (con sus controladores MV), Schneider, ABB, Eaton.
- El modelo debe incluir:
  - Secuencia de arranque de generadores
  - Sincronización y cierre de breakers MV
  - Transferencia abierta / cerrada (si se permite)
  - Black-start y recuperación

---

## 6. Elementos Adicionales para el Tope de Gama del Gemelo Digital

Para llevar el gemelo al máximo nivel de fidelidad se recomienda incorporar:

### 6.1 Modelado de potencia
- Curvas de eficiencia reales de Vertiv Trinergy (VFI y Dynamic Online)
- Curvas de carga de baterías (Litio preferido) con DoD, temperatura y envejecimiento
- Modelo térmico de salas de UPS y baterías
- Pérdidas I²R de cables MV y LV según longitud real
- Comportamiento de transformadores (pérdidas en vacío y en carga)

### 6.2 Controles y secuencia
- Lógica completa de transferencia MV
- Secuencia de paralleling de generadores
- Gestión de modo ECO / Dynamic Online con retorno automático
- Limitación de rampa de carga (soft-start de UPS y generadores)

### 6.3 Redundancia y fallas
- Simulación de falla de 1 bloque UPS (N+1)
- Falla completa de un path (2N)
- Falla de generador individual + arranque del spare
- Escenarios de mantenimiento concurrente

### 6.4 Integración y superficie OT
- Inventario completo de activos (resuelve DC-EPMS-063)
- API segura de escritura BMS (resuelve -065)
- Interfaz usable en móvil / tablet (resuelve -064)
- Conectores reales o emulados de Cummins / ASCO / Russelectric

### 6.5 KPIs y analítica
- PUE en tiempo real y proyectado
- Eficiencia energética por modo de operación
- Disponibilidad (SLA) calculada
- Coste de energía y de combustible simulado
- Alertas predictivas de baterías y generadores

---

## 7. Resumen Ejecutivo de Cambios Respecto a Versiones Anteriores

| Tema | Versión anterior | Versión actual (corregida) |
|------|------------------|----------------------------|
| Bloques UPS por path | 7 | **8 × Vertiv Trinergy 2500** |
| Pérdidas a 50 % | 450–520 kW (incorrecto) | **≈ 250–280 kW** |
| N+1 dentro del path | No garantizado | **Sí (17.5 MW)** |
| Generadores | No dimensionados | **9 × 2.5 MW por path @ 13.8 kV** |
| Transferencia | Mencionada genérica | **Controlador MV (sin ATS 480 V)** |
| Eficiencia | Básica | Análisis completo + modos |

---

## 8. Próximos Pasos Inmediatos para el Modelo

1. Actualizar one-line y inventario de activos a 8 × Trinergy 2500 por path.
2. Incorporar 9 generadores de 2.5 MW @ 13.8 kV por path.
3. Corregir el modelo de pérdidas UPS (usar fórmula correcta).
4. Sustituir “panel ATS” por controlador de transferencia MV.
5. Definir si la carga de chilling/CDUs entra en el UPS o no (impacto grande en generadores).
6. Implementar las tres pendientes registradas (OT Security, usabilidad móvil, API BMS).
7. Validar conectores de generadores/transferencia contra hardware real o emuladores de alta fidelidad.

---

**Documento listo para implementación en el gemelo digital de tope de gama.**  
Todas las observaciones técnicas han sido incorporadas y corregidas.  
