# Recomendación Técnica Completa – Gemelo Digital de Potencia  
## Tope de Gama + Seguridad Operacional en Media Tensión + Uptime Tier IV  

**Carga IT de diseño:** 16.76 MW por path  
**Fecha:** 13 de noviembre de 2026  
**Enfoque especial:** Operación segura de switchgear de Media Tensión (el dolor más frecuente y de mayor riesgo en data centers)

---

## 1. Decisiones de Diseño Cerradas

| Elemento | Valor Final |
|----------|-------------|
| UPS por path | **8 × Vertiv Trinergy 2500 kW** (Double Conversion) |
| Generadores por path | **9 × 2.5 MW @ 13.8 kV** |
| Transferencia | Controlador de Transferencia Automática de Media Tensión |
| Objetivo de certificación | **Uptime Institute Tier IV** |
| Total 2N | 16 UPS + 18 generadores |

---

## 2. Modelado Térmico Avanzado (Detalle Completo)

### 2.1 Objetivos del modelo térmico

- Predecir temperaturas en tiempo real y en escenarios what-if.
- Calcular carga térmica exacta para dimensionamiento y optimización de refrigeración.
- Determinar **tiempo de supervivencia** ante falla parcial o total de refrigeración.
- Evaluar impacto de modos de operación del UPS (VFI vs Dynamic Online).
- Soportar decisiones de free-cooling y setpoint dinámico.
- Integrarse con el modelo eléctrico (más pérdidas = más calor).

### 2.2 Fuentes de calor a modelar (por path)

| Fuente de calor | Valor normal (50 % carga) | Valor crítico (100 % path) | Notas de modelado |
|-----------------|---------------------------|----------------------------|-------------------|
| UPS Vertiv Trinergy (VFI) | 250–280 kW | 500–540 kW | Usar curva real de eficiencia vs carga y temperatura |
| UPS en Dynamic Online | 80–100 kW | 160–180 kW | Diferencia muy significativa |
| Baterías Litio (flotación + carga) | 15–35 kW | 40–70 kW | Depende de SoC, temperatura ambiente y química |
| Transformadores step-down | 120–180 kW | 180–250 kW | Pérdidas en vacío + carga (modelo IEEE) |
| Switchgear MV + busbars | 25–45 kW | 40–70 kW | Incluir conexiones y disyuntores |
| Cables MV y LV | 30–60 kW | 50–90 kW | Según longitud, sección y temperatura del conductor |
| **Total calor a disipar** | **≈ 520–680 kW** | **≈ 900–1.150 kW** | Valor de diseño de refrigeración por path |

### 2.3 Estructura del modelo térmico recomendado

1. **Modelo de zona / multi-zona**
   - Zona UPS
   - Zona baterías
   - Zona transformadores
   - Zona switchgear MV
   - Pasillos y retorno de aire

2. **Intercambios de calor**
   - Convección forzada (CRAH/CRAC/CDU)
   - Conducción a través de paredes y piso
   - Infiltración y presión de sala
   - Radiación (secundario)

3. **Equipos de refrigeración**
   - Curvas de capacidad vs temperatura de agua/aire y caudal
   - Consumo eléctrico de ventiladores y bombas (impacto en PUE)
   - Redundancia N+1 o 2N de unidades de refrigeración
   - Tiempo de arranque y respuesta

4. **Salidas del modelo**
   - Temperatura por zona en tiempo real
   - Gradiente térmico
   - Tiempo de supervivencia hasta temperatura crítica
   - Carga térmica total y por zona
   - Recomendación de setpoint óptimo

### 2.4 Setpoints y umbrales recomendados

| Zona | Objetivo | Alarma alta | Alarma crítica | Acción automática sugerida |
|------|----------|-------------|----------------|---------------------------|
| Sala UPS | 22–25 °C | 28 °C | 32 °C | Aumentar capacidad de refrigeración / alarmar |
| Sala baterías (Litio) | 20–25 °C | 30 °C | 35 °C | Reducir corriente de carga / alarmar |
| Switchgear MV | < 40 °C | 45 °C | 50 °C | Reducir carga / inspección prioritaria |
| Transformadores | < 85 °C (aceite) / < 110 °C (devanado) | Según fabricante | — | — |

---

## 3. Biblioteca de Escenarios de Falla (Para Entrenamiento, Validación y Certificación)

### 3.1 Categorías de escenarios

#### A. Escenarios de UPS
- Falla de 1 bloque UPS (validación N+1)
- Falla de 2 bloques UPS
- Falla completa de un path (2N)
- Transferencia a bypass estático
- Fallo de baterías (pérdida de autonomía)
- Cambio forzado de modo VFI ↔ Dynamic Online

#### B. Escenarios de Generación
- Falla de 1 generador + arranque del spare
- Falla de 2 generadores
- Fallo de arranque de generador
- Pérdida de combustible / bajo nivel
- Desincronización en paralleling

#### C. Escenarios de Transferencia y Media Tensión (críticos)
- Pérdida de utility + transferencia automática a generadores
- Fallo del controlador de transferencia MV
- Intento de cierre de breaker con desfase (anti-paralleling)
- Apertura inesperada de breaker MV bajo carga
- Fallo de interlock mecánico/eléctrico
- Operación manual en modo local vs remoto

#### D. Escenarios Térmicos / Refrigeración
- Falla de 1 unidad CRAH/CRAC
- Falla total de refrigeración de sala UPS
- Pérdida de agua helada
- Temperatura ambiente extrema

#### E. Escenarios Combinados (los más valiosos)
- Falla de path A + falla de refrigeración en path B
- Mantenimiento de bloque UPS + falla de generador
- Blackout + falla de arranque de parte de los generadores
- Operación MV incorrecta durante transferencia

### 3.2 Requisitos de cada escenario en el gemelo

Cada escenario debe tener:
- Condiciones iniciales definidas
- Secuencia de eventos (con timestamps)
- Comportamiento esperado del sistema
- Criterios de éxito / fallo
- Tiempo de detección y de recuperación
- Impacto en temperatura, SoC de baterías y disponibilidad
- Registro automático para auditoría y entrenamiento

---

## 4. Operación Segura de Switchgear de Media Tensión  
### (El dolor más frecuente y de mayor riesgo – puede costar vidas)

La operación de breakers y seccionadores de Media Tensión es históricamente una de las actividades de mayor riesgo en data centers. Errores de interlock, falta de verificación de ausencia de tensión, operaciones fuera de secuencia o trabajo en equipos energizados han causado arcos eléctricos graves y fatalidades.

### 4.1 Principios de diseño para llevar la seguridad MV a otro nivel en el gemelo

| Principio | Implementación recomendada en el gemelo |
|---------|-----------------------------------------|
| **Interlock digital completo** | Modelar todos los interlocks mecánicos, eléctricos y lógicos. El gemelo debe impedir operaciones inválidas. |
| **Verificación de ausencia de tensión** | Simular y exigir confirmación de ausencia de tensión antes de permitir apertura de seccionadores o cierre a tierra. |
| **Secuencia forzada (Procedure Enforcement)** | El operador solo puede ejecutar el siguiente paso válido de la secuencia. No se permiten atajos. |
| **Modo “Safety First”** | Modo de operación en el que cualquier acción MV requiere confirmación de dos personas (two-person rule) y checklist digital. |
| **Simulación de arco eléctrico** | Calcular y mostrar energía incidente y categoría de PPE requerida para cada posible operación. |
| **Entrenamiento inmersivo** | Permitir practicar operaciones MV en el gemelo sin riesgo real (incluyendo errores deliberados para aprender). |
| **Registro forense** | Toda operación MV (exitosa o fallida) se registra con usuario, timestamp, estado previo y posterior. |
| **Integración con LOTO digital** | El gemelo conoce el estado de bloqueo y etiquetado de cada equipo. |

### 4.2 Funcionalidades específicas a incluir en el gemelo para seguridad MV

1. **Motor de reglas de interlock**
   - Impide cierre de breaker si el seccionador de tierra está cerrado.
   - Impide apertura de seccionador bajo carga.
   - Valida sincronismo antes de permitir cierre en paralelo.
   - Detecta intentos de operación en modo local cuando está en remoto (y viceversa).

2. **Asistente de secuencia de operación (Switching Procedure Assistant)**
   - El operador selecciona el objetivo (ej. “aislar generador G3 para mantenimiento”).
   - El gemelo genera la secuencia paso a paso validada.
   - Cada paso se confirma y se registra.
   - Si se detecta desviación, se bloquea y se alerta.

3. **Cálculo de energía incidente en tiempo real**
   - Basado en la corriente de cortocircuito actual del modelo.
   - Muestra categoría de PPE requerida y distancia de aproximación segura.

4. **Modo de entrenamiento con errores controlados**
   - Permite al personal practicar operaciones incorrectas de forma segura.
   - Muestra las consecuencias (arco, disparo, pérdida de path, etc.).

5. **Dashboard de estado de seguridad MV**
   - Estado de todos los interlocks.
   - Equipos con LOTO activo.
   - Operaciones MV en curso.
   - Alertas de intento de operación insegura.

6. **Integración con procedimientos escritos y permisos de trabajo**
   - El gemelo puede exigir que exista un permiso de trabajo activo antes de habilitar ciertas operaciones.

### 4.3 Beneficio esperado

Llevar la operación de Media Tensión a este nivel en el gemelo convierte una de las mayores fuentes de riesgo y de “dolor” operativo en una ventaja competitiva de seguridad, entrenamiento y cumplimiento. Reduce drásticamente la probabilidad de error humano en la actividad que históricamente más vidas ha costado en instalaciones críticas.

---

## 5. Requisitos de Datos para el Gemelo Digital (Alta Fidelidad)

### 5.1 Datos de diseño y configuración (estáticos)

- One-line diagram completo y actualizado
- Datos de placa de todos los UPS, generadores, transformadores, breakers
- Curvas de eficiencia reales (UPS, transformadores)
- Curvas de capacidad de refrigeración
- Longitudes y secciones de cables
- Parámetros de interlocks y lógicas de transferencia
- Layout físico de salas eléctricas (para modelo térmico y de arco)

### 5.2 Datos en tiempo real (desde EPMS / BMS / SCADA)

- Potencia activa/reactiva por path y por bloque
- Tensiones y corrientes MV y LV
- Estado de todos los breakers y seccionadores
- Modo de operación de cada UPS (VFI / Dynamic Online / Bypass)
- SoC, SoH, temperatura y corriente de baterías
- Temperatura por zona de salas eléctricas
- Estado de unidades de refrigeración
- Nivel de combustible y autonomía estimada
- Alarmas y eventos

### 5.3 Datos de comportamiento y curvas

- Curvas de arranque de generadores
- Curvas de rampa de carga de UPS
- Curvas de eficiencia vs carga y temperatura
- Modelos térmicos de baterías
- Características de protección (relés)

### 5.4 Datos de operación y seguridad

- Procedimientos de switching aprobados
- Matriz de interlocks
- Historial de operaciones MV
- Permisos de trabajo activos
- Estado de LOTO

### 5.5 Datos para analítica y predicción

- Histórico de carga (mínimo 12 meses)
- Histórico de temperaturas y fallas
- Datos de envejecimiento de baterías y generadores
- Costes de energía y de combustible

---

## 6. Resumen de Capacidades del Gemelo de Tope de Gama

El gemelo debe ser capaz de:

- Simular y validar N+1 y 2N en tiempo real y en escenarios.
- Predecir comportamiento térmico y tiempo de supervivencia.
- Entrenar y validar operaciones seguras de Media Tensión con interlocks y procedimientos forzados.
- Ejecutar una biblioteca completa de escenarios de falla (simples y combinados).
- Generar evidencia para Uptime Tier IV.
- Proporcionar KPIs de disponibilidad, eficiencia, headroom y seguridad.
- Registrar de forma forense toda operación crítica.
- Integrarse de forma segura con la superficie OT real.

---

## 7. Próximos Pasos Prioritarios

1. Implementar el motor de interlocks y el asistente de secuencias de switching MV.
2. Desarrollar el modelo térmico multi-zona con cálculo de tiempo de supervivencia.
3. Construir la biblioteca de escenarios de falla (empezar por los de UPS, generación y MV).
4. Definir y conectar los puntos de datos en tiempo real necesarios.
5. Incorporar cálculo de energía incidente y requisitos de PPE.
6. Crear el modo de entrenamiento seguro para operaciones de Media Tensión.
7. Mapear requisitos Tier IV a escenarios ejecutables y reportables.

---

**Este documento eleva el gemelo digital de un modelo de potencia a una plataforma de operación segura, entrenamiento y certificación de nivel Tier IV, con énfasis especial en eliminar el riesgo mortal asociado a la operación de Media Tensión.**  
