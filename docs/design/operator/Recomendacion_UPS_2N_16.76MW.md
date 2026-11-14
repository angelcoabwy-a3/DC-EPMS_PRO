# Recomendación Técnica Completa  
## UPS Double Conversion + Generación en Configuración 2N  
**Carga crítica:** 16.76 MW por ruta  

**Fecha:** 13 de noviembre de 2026  
**Configuración objetivo:** 2N (doble ruta completamente independiente) + UPS Double Conversion (VFI / Online)

---

## 1. Resumen Ejecutivo – Mejor Opción Recomendada

| Decisión | Opción Recomendada | Justificación |
|---------|--------------------|-------------|
| **Bloques UPS** | **7 × 2.5 MW Double Conversion por ruta** | Mejor equilibrio entre modularidad, densidad, disponibilidad de mercado y headroom |
| **Total UPS instalado** | 14 unidades (7 por ruta A + 7 por ruta B) | 35 MW totales instalados |
| **Capacidad por ruta** | 17.5 MW | Headroom de +4.4 % sobre 16.76 MW |
| **Generación** | **Media Tensión (13.8 kV o 4.16 kV) con transferencia en MV** | Óptimo a esta escala de potencia |
| **Topología UPS** | Double Conversion (Online / VFI) | Máximo aislamiento y calidad de energía |

---

## 2. Dimensionamiento UPS (Double Conversion – 2N)

### 2.1 Cálculo de bloques

- Carga por ruta: **16.76 MW**
- Tamaño de bloque seleccionado: **2.5 MW**
- Unidades necesarias por ruta:  
  \( \frac{16.76}{2.5} = 6.704 \) → **7 unidades**
- Capacidad instalada por ruta: **17.5 MW**
- Headroom: **+4.4 %**

### 2.2 Comparativa de alternativas evaluadas

| Tamaño de bloque | Unidades por ruta | Capacidad instalada | Headroom | Ventajas | Desventajas |
|------------------|-------------------|---------------------|----------|----------|-------------|
| **2.5 MW** | **7** | **17.5 MW** | **+4.4 %** | Mejor equilibrio, alta disponibilidad de mercado (Vertiv Trinergy, Schneider, Eaton, etc.) | — |
| 2.0 MW | 9 | 18.0 MW | +7.4 % | Más modular | Más unidades, más espacio y complejidad de paralleling |
| 1.25 MW | 14 | 17.5 MW | +4.4 % | Máxima modularidad | Demasiados módulos para esta escala |
| 3.0–3.4 MW | 5–6 | 15–20.4 MW | Variable | Menos unidades | Menor flexibilidad de crecimiento y menos opciones de mercado |

**Decisión final:** **Bloques de 2.5 MW × 7 por ruta**.

### 2.3 Características técnicas recomendadas

- Topología: **Double Conversion (Online / VFI)**
- Factor de potencia de salida: **1.0 (unity)**
- Eficiencia esperada (Double Conversion): **96.8 – 97.5 %** a carga nominal
- Modo de alta eficiencia opcional (Dynamic Online / eConversion / ECO): **98.5 – 99.1 %** (recomendado habilitar con retorno automático a Double Conversion)
- Baterías: **Independientes por ruta** (no compartidas)
- Runtime recomendado: **8–12 minutos** a carga plena (suficiente para arranque y estabilización de generadores)

### 2.4 Pérdidas estimadas (por ruta)

| Escenario | Pérdidas aproximadas |
|-----------|----------------------|
| Double Conversion a 50 % de carga (operación normal 2N) | ≈ 450–520 kW |
| Double Conversion a 100 % de carga (falla de la otra ruta) | ≈ 520–580 kW |
| Modo alta eficiencia (si se habilita) | ≈ 170–250 kW |

---

## 3. Generación y Transferencia

### 3.1 Decisión recomendada

**Generación en Media Tensión + Transferencia en MV**

| Criterio | 480 V + ATS aguas abajo | Media Tensión (recomendado) |
|----------|--------------------------|-----------------------------|
| Corriente por ruta (~16.76 MW) | > 20 kA | ~700–2.300 A (según voltaje) |
| Tamaño de cables / busbars | Muy grande | Significativamente menor |
| Pérdidas I²R | Altas | Bajas |
| Paralleling de generadores | Limitado | Excelente |
| Espacio requerido | Alto | Optimizado |
| Escalabilidad | Media | Alta |
| Complejidad de mantenimiento | Baja | Media (requiere personal calificado MV) |
| **Recomendación a 16.76 MW/ruta** | No óptimo | **Sí** |

### 3.2 Configuración recomendada de generación

- Voltaje de generación: **13.8 kV** (preferido en Norteamérica) o **4.16 kV** según preferencia del cliente y disponibilidad de equipos.
- Arquitectura: Generadores en paralelo en switchgear de media tensión.
- Transferencia: Automática en media tensión (breakers con control de sincronización o ATS de media tensión).
- Transformadores step-down: Ubicados cerca de las salas de UPS (o considerar UPS de media tensión si el diseño lo permite en el futuro).
- Redundancia de generación: **2N** (cada ruta tiene su propio banco de generadores dimensionado para el 100 % de la carga de esa ruta).

---

## 4. Resumen de Decisiones Clave (Listas para Ejecutar)

| # | Decisión | Valor Fijado |
|---|----------|--------------|
| 1 | Tamaño de bloque UPS | **2.5 MW** |
| 2 | Cantidad de bloques por ruta | **7** |
| 3 | Total de unidades UPS (2N) | **14** |
| 4 | Topología UPS | **Double Conversion (Online)** |
| 5 | Generación | **Media Tensión (13.8 kV o 4.16 kV)** |
| 6 | Punto de transferencia | **Media Tensión** |
| 7 | Baterías | Independientes por ruta |
| 8 | Runtime objetivo | 8–12 minutos |

---

## 5. Próximos Pasos Recomendados

1. Seleccionar fabricante final de UPS (Vertiv Trinergy 2.5 MW, Schneider Galaxy, Eaton, ABB, etc.).
2. Definir voltaje exacto de generación (13.8 kV vs 4.16 kV) según utility y preferencia de operación.
3. Realizar estudio de cortocircuito y coordinación de protecciones.
4. Definir runtime exacto de baterías y química (VRLA vs Litio).
5. Dimensionar transformadores step-down y switchgear MV/LV.
6. Estimar espacio de salas eléctricas y requisitos de refrigeración de UPS.

---

**Documento preparado para decisión de diseño.**  
Listo para incorporar en memoria de cálculo, one-line diagram y especificaciones técnicas.  
