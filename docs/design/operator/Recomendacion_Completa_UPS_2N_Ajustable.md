# Recomendación Técnica Completa y Ajustable  
## UPS Double Conversion + Generación en Configuración 2N  

**Documento de Diseño Base**  
**Fecha:** 13 de noviembre de 2026  
**Configuración objetivo:** 2N (doble ruta completamente independiente) + UPS Double Conversion (VFI / Online)  

---

## 1. Resumen Ejecutivo – Opción Recomendada Base

| Parámetro | Valor Recomendado |
|-----------|-------------------|
| **Carga de diseño por ruta** | 16.76 MW (ajustable) |
| **Bloques UPS** | 7 × 2.5 MW Double Conversion por ruta |
| **Total unidades UPS (2N)** | 14 |
| **Capacidad instalada por ruta** | 17.5 MW (+4.4 % headroom) |
| **Topología UPS** | Double Conversion (Online / VFI) |
| **Generación** | Media Tensión (13.8 kV o 4.16 kV) |
| **Transferencia** | En Media Tensión |
| **Baterías** | Independientes por ruta (Litio preferido) |
| **Runtime objetivo** | 8–12 minutos a carga plena |

---

## 2. Dimensionamiento UPS Flexible (Ajustable por Carga)

### 2.1 Fórmula general de dimensionamiento

```
Unidades por ruta = CEILING( Carga_por_ruta_MW / Tamaño_bloque_MW )
Capacidad_instalada = Unidades × Tamaño_bloque
Headroom_% = ((Capacidad_instalada / Carga_por_ruta) - 1) × 100
```

### 2.2 Tabla de dimensionamiento según carga requerida

| Carga por ruta (MW) | Bloque 2.5 MW | Bloque 2.0 MW | Bloque 1.5 MW | Bloque 3.0 MW | Recomendación |
|---------------------|---------------|---------------|---------------|---------------|---------------|
| **12.0** | 5 uds (12.5 MW) | 6 uds (12.0 MW) | 8 uds (12.0 MW) | 4 uds (12.0 MW) | 5 × 2.5 MW |
| **14.0** | 6 uds (15.0 MW) | 7 uds (14.0 MW) | 10 uds (15.0 MW) | 5 uds (15.0 MW) | 6 × 2.5 MW |
| **16.0** | 7 uds (17.5 MW) | 8 uds (16.0 MW) | 11 uds (16.5 MW) | 6 uds (18.0 MW) | 7 × 2.5 MW |
| **16.76** | **7 uds (17.5 MW)** | 9 uds (18.0 MW) | 12 uds (18.0 MW) | 6 uds (18.0 MW) | **7 × 2.5 MW** |
| **18.0** | 8 uds (20.0 MW) | 9 uds (18.0 MW) | 12 uds (18.0 MW) | 6 uds (18.0 MW) | 8 × 2.5 MW o 6 × 3.0 MW |
| **20.0** | 8 uds (20.0 MW) | 10 uds (20.0 MW) | 14 uds (21.0 MW) | 7 uds (21.0 MW) | 8 × 2.5 MW |
| **22.0** | 9 uds (22.5 MW) | 11 uds (22.0 MW) | 15 uds (22.5 MW) | 8 uds (24.0 MW) | 9 × 2.5 MW |
| **25.0** | 10 uds (25.0 MW) | 13 uds (26.0 MW) | 17 uds (25.5 MW) | 9 uds (27.0 MW) | 10 × 2.5 MW |

> **Nota:** Se recomienda mantener headroom mínimo de **+3 % a +8 %**. Headroom superior a 15 % suele indicar sobredimensionamiento innecesario.

### 2.3 Comparativa de tamaños de bloque (para 16.76 MW)

| Tamaño de bloque | Unidades/ruta | Capacidad | Headroom | Ventajas | Desventajas | Recomendado |
|------------------|---------------|-----------|----------|----------|-------------|-------------|
| **2.5 MW** | **7** | **17.5 MW** | **+4.4 %** | Mejor equilibrio, alta disponibilidad de mercado | — | **Sí** |
| 2.0 MW | 9 | 18.0 MW | +7.4 % | Más modular, mejor para crecimiento incremental | Más espacio y complejidad | Alternativa |
| 1.25–1.5 MW | 12–14 | 17.5–18 MW | +4–7 % | Máxima modularidad y mantenibilidad | Demasiados módulos, más puntos de falla | Solo si se prioriza modularidad extrema |
| 3.0–3.4 MW | 5–6 | 15–20.4 MW | Variable | Menos unidades, menor footprint | Menor flexibilidad, menos opciones de mercado | Solo si el fabricante lo garantiza |

---

## 3. Ajuste según Capacidad de la Utility

La capacidad de interconexión con la utility puede limitar o condicionar el diseño. A continuación se presentan escenarios típicos:

| Capacidad Utility disponible (por ruta o total) | Impacto en el diseño | Recomendación de ajuste |
|------------------------------------------------|----------------------|--------------------------|
| **≥ 20 MW por ruta** | Sin restricción | Mantener 7 × 2.5 MW |
| **18–20 MW por ruta** | Headroom limitado | Mantener 7 × 2.5 MW o bajar a 6 × 2.5 MW + crecimiento futuro |
| **16–18 MW por ruta** | Ajuste necesario | Reducir a 6 × 2.5 MW (15.0 MW) o usar bloques de 2.0 MW |
| **< 16 MW por ruta** | Limitación fuerte | Redimensionar carga IT o implementar faseado (crecimiento por etapas) |
| Utility entrega en **Media Tensión** | Favorece diseño MV | Generación y transferencia en MV (recomendado) |
| Utility entrega en **Baja Tensión** | Complica diseño | Evaluar transformadores de elevación o aceptar LV generation (no óptimo) |
| Utility con **restricción de rampa / inrush** | Impacta arranque de generadores y UPS | Usar soft-start, limitadores de corriente y modo de alta eficiencia controlado |

### 3.1 Estrategia de faseado (crecimiento por etapas)

Si la utility o el presupuesto limitan la capacidad inicial:

| Fase | Carga objetivo | UPS recomendado | Generación |
|------|----------------|------------------|------------|
| Fase 1 | 8–10 MW | 4 × 2.5 MW por ruta | 50–60 % de la capacidad final |
| Fase 2 | 14–16 MW | 6 × 2.5 MW por ruta | 80–90 % de la capacidad final |
| Fase 3 (Final) | 16.76–18 MW | 7 × 2.5 MW por ruta | 100 % |

---

## 4. Baterías (Detalle Completo)

| Parámetro | Recomendación |
|-----------|---------------|
| **Arquitectura** | Independiente por ruta (2N estricto) |
| **Química preferida** | **Litio (Li-ion / LFP)** |
| **Alternativa** | VRLA (más económica, mayor footprint y mantenimiento) |
| **Runtime objetivo** | 8–12 minutos a carga plena (16.76 MW) |
| **Runtime mínimo aceptable** | 5 minutos (solo si generadores arrancan en < 10 s y estabilizan rápido) |
| **Temperatura de operación** | 20–25 °C (crítico para vida útil) |
| **Monitoreo** | BMS individual + integración a DCIM / BMS del edificio |
| **Fin de vida** | Diseñar a 80 % de capacidad residual |

**Estimación orientativa de energía de batería (Litio):**  
- Para 16.76 MW × 10 minutos ≈ **2.800–3.100 kWh por ruta** (dependiendo de eficiencia del inversor y DoD).

---

## 5. Pérdidas Totales del Sistema (Estimación)

| Componente | Pérdidas aproximadas (operación normal 2N) | Notas |
|------------|--------------------------------------------|-------|
| UPS Double Conversion (50 % carga) | 450–520 kW por ruta | Principal fuente de calor en sala eléctrica |
| Transformadores step-down | 0.8–1.2 % | Depende de eficiencia y carga |
| Cables y busways (MV) | Bajas | Ventaja del diseño MV |
| Switchgear y protecciones | < 0.3 % | — |
| **Total estimado por ruta** | **≈ 550–700 kW** | Incluye UPS + transformadores |
| **Total 2N (ambas rutas)** | **≈ 1.1–1.4 MW** | Calor a disipar en salas eléctricas |

> **Importante:** Estas pérdidas deben incluirse en el cálculo de refrigeración de las salas de UPS y en el PUE del data center.

---

## 6. Estimación de Espacio (Salas Eléctricas)

| Elemento | Espacio estimado por ruta | Notas |
|----------|---------------------------|-------|
| 7 × UPS 2.5 MW | 80–110 m² | Incluye clearance frontal y lateral |
| Baterías Litio (10 min) | 40–60 m² | Significativamente menor que VRLA |
| Switchgear LV + transformadores | 50–80 m² | Depende de configuración |
| Pasillos y mantenimiento | 30–40 % adicional | Según códigos locales |
| **Total estimado por ruta** | **180–280 m²** | Valor orientativo |
| **Total 2N** | **360–560 m²** | Dos salas independientes preferibles |

---

## 7. Generación y Transferencia (Detalle)

### 7.1 Decisión recomendada

**Generación en Media Tensión + Transferencia en MV**

| Criterio | 480 V + ATS | Media Tensión (recomendado) |
|----------|-------------|-----------------------------|
| Corriente a 16.76 MW | > 20 kA | 700–2.300 A |
| Cables / busbars | Muy grandes y costosos | Compactos |
| Pérdidas | Altas | Bajas |
| Paralleling | Limitado | Excelente |
| Escalabilidad | Media | Alta |
| **Recomendación** | No óptimo a esta escala | **Sí** |

### 7.2 Configuración recomendada

- Voltaje de generación: **13.8 kV** (Norteamérica) o **4.16 kV** (según utility y preferencia).
- Arquitectura: Generadores en paralelo sobre switchgear MV.
- Transferencia: Automática en media tensión.
- Redundancia: **2N** (cada ruta tiene su propio banco de generadores dimensionado al 100 % de la carga de esa ruta).
- Transformadores step-down: Cerca de las salas de UPS.

---

## 8. Elementos Adicionales No Contemplados Inicialmente (Ahora Incluidos)

| Elemento | Recomendación / Consideración |
|----------|-------------------------------|
| **Factor de potencia de la carga IT** | Asumir 0.95–1.0 (fuentes modernas con PFC activo) |
| **PUE y carga de refrigeración** | Incluir potencia de chilling / CRAH / CDUs en el dimensionamiento de generadores si están en UPS |
| **Crecimiento futuro** | Dejar espacio físico y capacidad de paralleling para +1 o +2 bloques por ruta |
| **Modo de alta eficiencia** | Habilitar (Dynamic Online / ECO) con retorno automático a Double Conversion |
| **Calidad de energía de la utility** | Evaluar THDi, sags y frecuencia antes de decidir modo ECO permanente |
| **Normativa local** | Verificar códigos de baterías (Litio), ventilación, detección de incendios y clearances |
| **Mantenimiento concurrente** | Confirmar que el diseño permite sacar 1 bloque de servicio sin afectar la capacidad de diseño |
| **Sincronización y black-start** | Definir secuencia de arranque de generadores y transferencia |
| **Monitoreo y DCIM** | Integración completa de UPS, baterías, generadores y switchgear |
| **Cybersecurity** | Segmentación de redes de control de potencia |

---

## 9. Resumen de Decisiones Clave (Listas para Ejecutar)

| # | Decisión | Valor Base | Ajustable según |
|---|----------|------------|-----------------|
| 1 | Tamaño de bloque UPS | **2.5 MW** | Disponibilidad de fabricante / preferencia |
| 2 | Cantidad de bloques por ruta | **7** | Carga real y capacidad utility |
| 3 | Total unidades (2N) | **14** | — |
| 4 | Topología UPS | **Double Conversion** | Fijo |
| 5 | Generación | **Media Tensión** | Capacidad y voltaje de utility |
| 6 | Punto de transferencia | **Media Tensión** | — |
| 7 | Química de baterías | **Litio (preferido)** | Presupuesto / espacio |
| 8 | Runtime | **8–12 min** | Tiempo de arranque de generadores |
| 9 | Headroom mínimo | **+3 a +8 %** | Política de crecimiento |

---

## 10. Próximos Pasos Recomendados

1. Confirmar carga exacta de diseño y capacidad real de interconexión con la utility.
2. Seleccionar fabricante final de UPS y validar disponibilidad de bloques de 2.5 MW.
3. Definir voltaje de generación (13.8 kV vs 4.16 kV).
4. Realizar estudio de cortocircuito, coordinación de protecciones y análisis de armónicos.
5. Dimensionar baterías con runtime exacto y química definitiva.
6. Estimar espacio real de salas eléctricas y requisitos de refrigeración.
7. Definir estrategia de faseado si la capacidad utility o el presupuesto lo requieren.
8. Incorporar estos datos en el one-line diagram y memoria de cálculo.

---

**Documento preparado para decisión de diseño y ajuste flexible.**  
Puede utilizarse como base para especificaciones técnicas, RFQ a fabricantes y memoria de cálculo.  
