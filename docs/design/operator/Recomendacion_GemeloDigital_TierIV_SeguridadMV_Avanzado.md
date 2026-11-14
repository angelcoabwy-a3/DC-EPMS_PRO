# Recomendación Técnica Completa – Gemelo Digital de Potencia  
## Versión Avanzada | Seguridad MV de Nivel Superior + Modelo Térmico + Biblioteca de Escenarios  

**Carga IT de diseño:** 16.76 MW por path  
**Fecha:** 13 de noviembre 2026  
**Estado del documento:** Actualizado en su totalidad con profundización máxima en las tres áreas prioritarias  

---

## 1. Decisiones de Diseño Cerradas (sin cambios)

| Elemento | Valor Final |
|----------|-------------|
| UPS por path | 8 × Vertiv Trinergy 2500 kW (Double Conversion) |
| Generadores por path | 9 × 2.5 MW @ 13.8 kV |
| Transferencia | Controlador de Transferencia Automática MV |
| Objetivo | Uptime Institute Tier IV + Seguridad Operacional MV de élite |

---

## 2. Modelo Térmico Avanzado – Profundización

### 2.1 Arquitectura recomendada del modelo térmico

El modelo debe ser **multi-zona + multi-física**, con acoplamiento eléctrico-térmico bidireccional.

**Zonas mínimas obligatorias por path:**
- Zona UPS (gabinetes + pasillo frontal)
- Zona Baterías ( Litio )
- Zona Transformadores
- Zona Switchgear MV
- Zona de retorno de aire / plenum
- Zona exterior (para free-cooling y condiciones ambiente)

**Ecuaciones y fenómenos a modelar:**
- Balance de energía por zona:  
  \( m \cdot c_p \cdot \frac{dT}{dt} = \dot{Q}_{gen} - \dot{Q}_{cool} + \dot{Q}_{adj} + \dot{Q}_{inf} \)
- Generación de calor dependiente de la carga eléctrica real y del modo de operación del UPS.
- Capacidad de refrigeración dependiente de temperatura de agua/aire, caudal y estado de las unidades.
- Inercia térmica de equipos y sala (importante para tiempo de supervivencia).
- Efecto de la temperatura ambiente exterior y de la carga solar (si aplica).

### 2.2 Tiempo de Supervivencia (Survival Time) – Cálculo clave

El gemelo debe calcular y mostrar en tiempo real y en escenarios:

- Tiempo estimado hasta alcanzar temperatura de alarma alta.
- Tiempo estimado hasta temperatura crítica (riesgo de derating o shutdown).
- Tiempo hasta daño irreversible de baterías o electrónica.

**Entradas críticas para el cálculo:**
- Carga térmica actual
- Capacidad de refrigeración residual (después de fallas)
- Inercia térmica de la sala y equipos
- Temperatura actual vs setpoints

### 2.3 Integración eléctrica-térmica

- Cada incremento de pérdidas eléctricas (cambio de modo UPS, aumento de carga, falla de path) debe reflejarse inmediatamente en el modelo térmico.
- El modelo térmico debe poder limitar la capacidad del UPS o de los generadores si se alcanzan temperaturas críticas (protección térmica).

### 2.4 Nivel superior de modelado térmico

| Nivel | Características | Recomendación |
|-------|-----------------|---------------|
| Básico | Temperatura única de sala + pérdidas constantes | Insuficiente |
| Intermedio | Multi-zona + curvas de refrigeración | Mínimo aceptable |
| **Avanzado (recomendado)** | Multi-zona + acoplamiento eléctrico-térmico + inercia + survival time + free-cooling | **Objetivo actual** |
| Élite | + CFD simplificado o reduced-order model + predicción con ML | Futuro cercano |

---

## 3. Biblioteca de Escenarios de Falla – Profundización y Estructura de Datos

### 3.1 Estructura de Datos JSON – Evaluación y Nivel Superior

La estructura JSON debe ser **ejecutable, auditable, versionable y reutilizable**.  

A continuación se presenta la **estructura de nivel superior recomendada** (superior a un simple listado de eventos).

```json
{
  "scenario_id": "MV-SW-001",
  "version": "1.2.0",
  "title": "Aislamiento seguro de Generador G3 para mantenimiento",
  "category": "MediumVoltage_Switching",
  "severity": "Critical",
  "tier_iv_relevance": true,
  "safety_critical": true,
  "description": "Secuencia completa de aislamiento de un generador MV siguiendo interlocks y LOTO.",
  "preconditions": {
    "system_state": {
      "path": "A",
      "generators_online": [1, 2, 3, 4, 5, 6, 7, 8, 9],
      "load_mw": 16.76,
      "ups_mode": "VFI"
    },
    "required_permits": ["PTW-2026-1142"],
    "loto_required": true
  },
  "initial_conditions": {
    "breakers": {
      "G3_CB": "Closed",
      "G3_DS": "Closed",
      "G3_ES": "Open"
    },
    "interlocks_status": "All_Healthy"
  },
  "sequence": [
    {
      "step": 1,
      "action": "Verify_Absence_of_Voltage",
      "target": "G3_CB",
      "expected_result": "Voltage < 50V",
      "timeout_seconds": 30,
      "safety_gate": true,
      "two_person_rule": true
    },
    {
      "step": 2,
      "action": "Open_Breaker",
      "target": "G3_CB",
      "interlocks_to_check": ["G3_DS_Closed", "Sync_OK", "No_Load_Current"],
      "expected_result": "G3_CB == Open",
      "on_failure": "Abort_and_Alarm"
    },
    {
      "step": 3,
      "action": "Open_Disconnector",
      "target": "G3_DS",
      "interlocks_to_check": ["G3_CB_Open"],
      "expected_result": "G3_DS == Open"
    },
    {
      "step": 4,
      "action": "Close_Earthing_Switch",
      "target": "G3_ES",
      "interlocks_to_check": ["G3_DS_Open", "Voltage_Absent"],
      "expected_result": "G3_ES == Closed",
      "safety_gate": true
    },
    {
      "step": 5,
      "action": "Apply_LOTO",
      "target": "G3",
      "expected_result": "LOTO_Active == true"
    }
  ],
  "success_criteria": [
    "G3_CB == Open",
    "G3_DS == Open",
    "G3_ES == Closed",
    "LOTO_Active == true",
    "No_Arc_Flash_Event",
    "Path_A_Capacity_Still_Above_16.76_MW"
  ],
  "failure_modes": [
    {
      "id": "FM-01",
      "description": "Intento de abrir seccionador bajo carga",
      "detection": "Current > 10A while opening DS",
      "response": "Block_Operation + Critical_Alarm + Lock_Session"
    },
    {
      "id": "FM-02",
      "description": "Cierre de earthing switch con tensión presente",
      "detection": "Voltage > 50V",
      "response": "Block + Arc_Flash_Calculation + Evacuate_Alarm"
    }
  ],
  "thermal_impact": {
    "expected_heat_change_kw": 0,
    "survival_time_impact": "None"
  },
  "audit": {
    "required_logging": ["user", "timestamp", "step", "result", "interlock_status"],
    "retention_days": 2555
  },
  "training_mode": {
    "allow_forced_errors": true,
    "show_consequences": true,
    "scoring": true
  }
}
```

### 3.2 ¿Es esta la estructura ideal?

**Sí, esta es la estructura de nivel superior recomendada** por las siguientes razones:

| Característica | Beneficio |
|----------------|---------|
| Versionado (`version`) | Permite evolucionar escenarios sin romper historial |
| Preconditions + Initial Conditions | Garantiza reproducibilidad |
| Sequence con safety_gate y two_person_rule | Enfoque de seguridad real |
| Interlocks_to_check por paso | Motor de interlock ejecutable |
| Failure_modes explícitos | Entrena y valida respuestas |
| Success_criteria claros | Automatiza validación pass/fail |
| Thermal_impact | Acoplamiento con modelo térmico |
| Audit + Training_mode | Cumplimiento y formación |

**Niveles inferiores (no recomendados como objetivo final):**
- Solo lista de eventos sin interlocks ni failure modes
- Escenarios hardcodeados en código sin JSON versionable
- Sin campos de seguridad (two-person rule, safety_gate)

**Nivel élite futuro (opcional):**
- Añadir campo `digital_twin_bindings` con mapeo a tags reales del EPMS
- Soporte para escenarios compuestos (scenario of scenarios)
- Integración con motor de reglas externo (IEC 61850 / SCL)

### 3.3 Biblioteca mínima recomendada (prioridad alta)

**Seguridad MV (obligatorios):**
- MV-SW-001 → Aislamiento de generador
- MV-SW-002 → Puesta en servicio de generador
- MV-SW-003 → Transferencia utility → generadores
- MV-SW-004 → Transferencia generadores → utility
- MV-SW-005 → Intento de operación insegura (entrenamiento)

**UPS y Redundancia:**
- UPS-N1-001 → Falla de 1 bloque (validación N+1)
- UPS-2N-001 → Pérdida completa de Path A

**Térmicos:**
- TH-001 → Falla total de refrigeración de sala UPS
- TH-002 → Falla de 50 % de capacidad de refrigeración

**Combinados:**
- COMB-001 → Falla Path A + falla de refrigeración en Path B
- COMB-002 → Blackout + falla de arranque de 2 generadores

---

## 4. Operación Segura de Media Tensión – Nivel Superior

### 4.1 Capacidades que elevan el gemelo a otro nivel

1. **Motor de Interlocks Ejecutable**
   - Evalúa en tiempo real todos los interlocks antes de permitir cualquier acción.
   - Bloquea y registra intentos inválidos.

2. **Asistente de Secuencias (Switching Procedure Assistant)**
   - Genera la secuencia óptima y segura a partir del objetivo del operador.
   - Solo habilita el siguiente paso válido.
   - Soporta two-person rule.

3. **Cálculo de Energía Incidente en Tiempo Real**
   - Usa la corriente de cortocircuito actual del modelo.
   - Muestra categoría de PPE y distancia segura.

4. **Modo Entrenamiento con Consecuencias**
   - Permite forzar errores de forma segura.
   - Muestra el resultado (arco, disparo, pérdida de path, etc.).

5. **LOTO Digital + Permisos de Trabajo**
   - El gemelo conoce el estado real de bloqueo.
   - Puede exigir permiso de trabajo activo.

6. **Registro Forense Completo**
   - Quién, cuándo, qué, estado anterior/posterior, interlocks evaluados.

### 4.2 Ejemplo de secuencia realista (resumida)

**Objetivo:** Aislar Generador G3 Path A para mantenimiento.

1. Verificar permiso de trabajo activo.
2. Verificar que la capacidad residual del path sigue siendo ≥ 16.76 MW.
3. Verificar ausencia de tensión en el breaker.
4. Abrir breaker del generador (con chequeo de interlocks).
5. Abrir seccionador.
6. Cerrar seccionador de puesta a tierra.
7. Aplicar LOTO digital.
8. Confirmar estado seguro y liberar para trabajo.

El gemelo debe impedir cualquier desviación de esta secuencia.

---

## 5. Requisitos de Datos – Vista Consolidada de Nivel Superior

| Categoría | Datos mínimos | Frecuencia / Tipo |
|-----------|---------------|-------------------|
| Configuración | One-line, datos de placa, curvas de eficiencia, interlocks, layout | Estático + versionado |
| Tiempo real eléctrico | P, Q, V, I, estado de breakers, modo UPS, SoC baterías | 1–5 segundos |
| Tiempo real térmico | Temperatura por zona, estado CRAH, caudal, temperatura de agua | 10–30 segundos |
| Seguridad | Estado LOTO, permisos de trabajo, usuarios autorizados | Evento + periódico |
| Escenarios | JSON versionados de toda la biblioteca | Versionado |
| Histórico | Carga, temperaturas, eventos, operaciones MV | Largo plazo |
| Auditoría | Logs de operaciones críticas | Inmutable |

---

## 6. Estado del Documento

Este archivo **actualiza y supera** todas las versiones anteriores.  
Incorpora:
- Modelo térmico de nivel avanzado
- Biblioteca de escenarios con estructura JSON de nivel superior
- Enfoque de seguridad MV de élite (el mayor dolor y riesgo de los data centers)
- Requisitos de datos claros y priorizados
- Alineación Tier IV

**Es el documento de referencia actual para el gemelo digital de tope de gama.**

---

**Próximo salto recomendado (si se desea seguir elevando):**  
Implementar un motor de reglas de interlock separado (basado en IEC 61850 o similar) y un reduced-order thermal model con capacidad de predicción a 15–30 minutos.  
