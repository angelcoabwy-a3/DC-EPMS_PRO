# Estructura de Repositorio + Resolución de Pendientes Críticos  
## DC-EPMS-066 | DC-EPMS-067 | DC-EPMS-068 + Esqueleto de Carpetas  

**Fecha:** 14 de noviembre 2026  
**Estado:** Documento de implementación listo para ejecutar  

---

## 1. Decisión sobre Generadores – DC-EPMS-066 (N+1 Real)

### Problema identificado
- Carga estimada por path (IT + enfriamiento + auxiliares): **20.5 – 23 MW**
- Con supuesto de 25 % de enfriamiento + auxiliares → **≈ 21.5 MW**
- 9 × 2.5 MW = 22.5 MW → con un generador fuera quedan **20.0 MW** → **no cubre 21.5 MW**
- Por tanto, **no existe N+1 real** en generación.

### Opciones evaluadas

| Opción | Configuración | Capacidad N | Capacidad N+1 (1 fuera) | ¿Cubre 21.5 MW? | Comentario |
|--------|---------------|-------------|--------------------------|------------------|------------|
| A | 10 × 2.5 MW | 25.0 MW | 22.5 MW | Sí | Más unidades, más espacio y mantenimiento |
| **B (Recomendada)** | **9 × 2.75 MW** | **24.75 MW** | **22.0 MW** | **Sí** | Mejor equilibrio capacidad / cantidad / footprint |
| C | 9 × 2.5 MW + limitar enfriamiento a 2.7 MW | 22.5 MW | 20.0 MW | Solo si se limita carga | Restringe operación, no ideal |

### Decisión oficial recomendada

**Adoptar Opción B: 9 × 2.75 MW por path @ 13.8 kV**

- Capacidad total por path: 24.75 MW
- Con 1 generador fuera: 22.0 MW → cubre holgadamente 21.5 MW
- Mantiene el número de máquinas en 9 (no se dispara a 10)
- Permite headroom razonable para crecimiento o peores condiciones de enfriamiento

**Totales 2N actualizados:**
- Generadores: **18 × 2.75 MW @ 13.8 kV**

---

## 2. Corrección de la Regla de Extracción de Generador – DC-EPMS-067

### Problema
La regla actual:
> “capacidad residual ≥ 16.76 MW”

Solo considera la carga IT. Por eso el panel muestra **“N: NOT MET”** correctamente según la regla escrita, pero la regla está incompleta.

### Nueva regla recomendada (ideal)

```text
Al sacar un generador del servicio:
  Capacidad residual del path ≥ Carga total actual del path
  (IT + Enfriamiento + Auxiliares + Pérdidas UPS)

  Y además:
  Capacidad residual ≥ 21.5 MW   (valor de diseño con 25 % de overhead)
```

**Implementación en el gemelo:**
- Calcular en tiempo real: `Carga_Total_Path = IT + Cooling + Aux + UPS_Losses`
- Evaluar: `Capacidad_Residual >= max(Carga_Total_Path, 21.5 MW)`
- Mostrar ambos valores en el panel (IT-only y Total)
- Cambiar el estado a **“N+1: MET / NOT MET”** usando la carga total

---

## 3. Plan de Actualización de site_model.yml – DC-EPMS-068

### Objetivo
Reemplazar el diseño viejo (1 UPS de 2.5 MW por path) por el diseño nuevo completo.

### Pasos de ejecución

1. **Congelar** el `site_model.yml` actual como `site_model_legacy.yml`
2. Crear `site_model_v2.yml` con la siguiente configuración:

```yaml
# site_model_v2.yml – Configuración objetivo
paths:
  path_A:
    ups:
      model: "Vertiv Trinergy 2500"
      quantity: 8
      rating_mw: 2.5
      topology: "Double Conversion"
    generators:
      model: "2.75 MW @ 13.8 kV"
      quantity: 9
      rating_mw: 2.75
      voltage_kv: 13.8
    transfer: "MV Automatic Transfer Controller"
    design_it_load_mw: 16.76
    design_total_load_mw: 21.5   # IT + 25% overhead

  path_B:
    # Idéntico a path_A (2N)
```

3. Actualizar el diagrama unifilar (one-line) para reflejar 8 UPS + 9 generadores por path.
4. Re-mapear toda la telemetría (puntos de potencia, estados de breakers, modos UPS, etc.).
5. Actualizar las reglas de capacidad residual (DC-EPMS-067).
6. Validar con escenarios N+1 de UPS y de generadores.
7. Actualizar los paneles para que dejen de usar el modelo viejo.

**Prioridad:** Máxima. Es el cimiento de todo el resto del gemelo.

---

## 4. Esqueleto de Carpetas / Estructura de Archivos del Repositorio

```text
digital-twin-power/
│
├── README.md
├── docs/
│   ├── design/
│   │   ├── R3_POWER_CONTROLS_EVALUATION.md
│   │   ├── Recomendacion_GemeloDigital_TierIV_SeguridadMV_Avanzado.md
│   │   ├── Analisis_Umbrales_Energia_Incidente.md
│   │   ├── Seccion_Energia_Incidente_IEEE1584.md
│   │   └── Estructura_Gemelo_Modular_Pendientes_DC-EPMS.md
│   └── decisions/
│       └── generator_n1_decision_DC-EPMS-066.md
│
├── models/
│   ├── site_model_legacy.yml              # Versión antigua (congelada)
│   ├── site_model_v2.yml                  # ← Nueva versión objetivo
│   ├── one_line/
│   │   ├── path_A.svg / .dxf
│   │   └── path_B.svg / .dxf
│   └── physics/
│       ├── electrical/
│       └── thermal/
│
├── modules/
│   ├── 01_core_model/
│   ├── 02_power_system/
│   │   ├── ups/
│   │   └── generators/
│   ├── 03_safety_mv_arcflash/             # Módulo independiente
│   │   ├── interlocks/
│   │   ├── incident_energy/
│   │   ├── thresholds/
│   │   ├── switching_assistant/
│   │   └── loto/
│   ├── 04_thermal_model/
│   ├── 05_scenarios_library/
│   │   └── scenarios/
│   ├── 06_ot_security_usability/          # DC-EPMS-063, 064, 065
│   └── 07_integration_layer/
│       ├── epms_adapters/
│       └── iec61850_prep/
│
├── telemetry/
│   └── mapping_v2.yaml
│
├── tests/
│   ├── test_n1_ups.py
│   ├── test_n1_generators.py
│   └── test_incident_energy_thresholds.py
│
└── scripts/
    ├── apply_release_r1.ps1               # (referencia)
    └── validate_site_model_v2.py
```

---

## 5. Instrucciones de Implementación Inmediata

1. Crear la estructura de carpetas anterior.
2. Mover los documentos `.md` existentes a `docs/design/`.
3. Crear `models/site_model_v2.yml` con la configuración de 8 UPS + 9 × 2.75 MW.
4. Actualizar la regla de capacidad residual de generadores (DC-EPMS-067) para usar carga total.
5. Implementar el cálculo de energía incidente como parte del módulo `03_safety_mv_arcflash`.
6. Marcar DC-EPMS-066 y DC-EPMS-067 como resueltos una vez aplicados los cambios.
7. Dejar DC-EPMS-068 como “En progreso” hasta que el one-line y la telemetría estén actualizados.

---

## 6. Resumen de Decisiones Cerradas en este Documento

| ID | Tema | Decisión |
|----|------|----------|
| DC-EPMS-066 | N+1 de generadores | **9 × 2.75 MW por path** |
| DC-EPMS-067 | Regla de extracción de generador | Usar **carga total** (IT + Cooling + Aux), no solo 16.76 MW |
| DC-EPMS-068 | site_model.yml | Crear **site_model_v2.yml** y migrar one-line + telemetría |
| Estructura | Arquitectura del repositorio | **Modular** con módulo independiente de Seguridad MV |

---

**Este documento es la guía de implementación lista para ejecutar.**  
Incluye la resolución de los tres hallazgos críticos y el esqueleto completo del repositorio.  
