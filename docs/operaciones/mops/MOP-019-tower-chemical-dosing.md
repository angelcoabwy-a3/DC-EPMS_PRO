# MOP-019 — Cooling Tower: Dosificación Química Dinámica + Control de Legionella

**Asset Category:** Cooling Tower · **Work Mode:** Live chemical
dosing (torre operativa; intervención en sistema químico). **Compliance:**
CSA Z462-24, NFPA 70E, CTI ATC-105, ASHRAE 188 (Legionella),
ANSI/AIHA Z9.5.

---

## 1. Alcance y Objetivo

Inyectar biocidas (oxidantes + no oxidantes) y anti-incrustantes en
las torres de enfriamiento basándose en mediciones en tiempo real
del **Índice de Saturación de Langelier (LSI)** y de los **Ciclos
de Concentración (CoC)**. Incluye toma de muestras físicas para
laboratorio certificado en bioseguridad (control de Legionella per
ASHRAE 188).

**Equipo objetivo:** Torre de enfriamiento + sistema de dosificación
química + bombas dosificadoras. **Ubicación:** Planta Mecánica / techo.

---

## 2. Evaluación de Impacto y Riesgos Térmicos

- **Impacto en carga IT:** ninguno directo (la dosificación no
  interrumpe el flujo); INdirecto si LSI fuera de banda causa
  incrustación severa que degrada el rechazo térmico → `Q_rej` cae.
- **Tiempo de Tolerancia Térmica:** la degradación química es
  lenta (días/semanas); no hay timer agudo, pero `LSI > 1.0`
  sostenido reduce COP del Chiller en ≈ 5-10% por mes.
- **Riesgos químicos:** biocidas oxidantes (ej. ácido hipocloroso)
  son corrosivos + producen vapores tóxicos en contacto con ácidos;
  EPP químico completo es innegociable.
- **Riesgo de Legionella:** crecimiento microbiológico en biofilm
  puede causar enfermedad legionarios + cierre regulatorio del
  sitio (ASHRAE 188, CTI ATC-105 microbiological quality).
- **Nivel de energía incidente:** Arc Flash Categoría 2 en panel de
  bombas dosificadoras (motor de bomba peristáltica).

---

## 3. Parámetros Físicos de Referencia (Prerrequisitos)

- **LSI objetivo:** banda segura **0.2 a 0.5**.
  - `LSI < 0` → corrosiva (destruye tubos del condensador del
    Chiller).
  - `LSI > 0.5` → incrustante (capas de carbonato de calcio aíslan
    térmicamente).
- **CoC máximo:** `CoC = conductividad_agua_torre /
  conductividad_agua_reposición`; típicamente **≤ 5** para evitar
  saturación de minerales.
- **Cultivo bacteriológico de Legionella:** muestras periódicas
  (cada 30 días + post-dosificación de choque) analizadas en
  laboratorio certificado; umbral de acción **≥ 100 CFU/mL**
  → escalar a tratamiento de choque + notificación regulatoria.
- **Mechanical LOTO** en válvulas del sistema de dosificación
  cuando se interviene físicamente + alivio de presión + descarga
  segura de residuos químicos.
- **Motor LOTO eléctrico** en bombas dosificadoras + **Vivo-Muerto-
  Vivo** en bornes del motor antes de cualquier intervención;
  **CSA Z462-24**, **PPE Cat 2** (eléctrico) + **EPP químico
  completo** (delantal ácido-resistente + guantes nitrilo + careta
  facial + respirador con filtros para vapores ácidos).
- **PTW especial** firmado por el Manager on Duty + Safety
  Officer (riesgo químico).
- Personal: técnico químico calificado + supervisor (Maker +
  Checker — **Cuatro Ojos**).

---

## 4. Lista de Pasos Secuenciales

> Cada paso requiere doble firma (Cuatro Ojos / Maker-Checker).

1. Notificar al NOC + capturar lecturas baseline: pH, conductividad,
   temperatura, dureza cálcica, alcalinidad → calcular LSI + CoC.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

2. Si `LSI < 0` (corrosiva): preparar dosis de **anti-corrosivo**
   (fosfonato típico). Si `LSI > 0.5` (incrustante): preparar
   dosis de **anti-incrustante** (polímero acrílico). Si `CoC > 5`:
   incrementar **blowdown** + agua de reposición.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

3. Tomar muestra física para análisis microbiológico (Legionella +
   conteo bacteriano total); etiquetar + enviar a laboratorio
   certificado.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

4. Verter productos químicos en tanque de dosificación con **EPP
   químico completo** + ventilación adecuada; verificar etiquetas
   de compatibilidad para evitar reacciones peligrosas.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

5. Si se interviene físicamente el sistema (cambio de manguera,
   válvula): aplicar **Mechanical LOTO** + alivio de presión +
   descarga de residuo a contenedor de neutralización; aplicar
   **Motor LOTO** + **Vivo-Muerto-Vivo** en bombas dosificadoras
   antes de cualquier desconexión eléctrica.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

6. Programar la tasa de dosificación en el controlador automatizado
   (mL/min basado en CoC + conductividad de reposición); verificar
   inyección + mezcla.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

7. Monitorear pH + conductividad + LSI durante 60 min post-
   dosificación; verificar convergencia hacia el rango objetivo.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

8. Documentar nuevas tasas de dosificación + muestra enviada al
   laboratorio + resultados psicrométricos + notificar al NOC la
   finalización.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

---

## 5. Plan de Reversión (Back-out Plan)

**Criterios de Aborto (umbrales químicos):**

- Si `LSI > 1.0` o `LSI < -0.5` después de la dosificación →
  **blowdown de emergencia** + reposición masiva de agua fresca;
  re-calcular dosis.
- Si el laboratorio reporta **Legionella ≥ 100 CFU/mL**: ejecutar
  **dosificación de choque** (cloración a 5-10 ppm sostenida por
  6-8 h) + notificación al Manager on Duty + Safety Officer +
  considerar restricción del uso de la torre hasta confirmar
  eliminación.
- Si durante el paso 4 hay derrame químico o reacción no esperada:
  evacuar el área + activar protocolo HAZMAT + notificar a
  bomberos / emergency response.
- Si **vapores tóxicos** detectados (olor severo, irritación
  ocular/respiratoria): evacuar + ventilar + EPP respiratorio
  upgrade a SCBA.

**Secuencia de Reversión:**

1. Detener dosificación; cerrar válvulas del tanque químico
   (**Mechanical LOTO**).
2. Si blowdown emergencia: abrir purga + reponer agua fresca hasta
   normalizar conductividad / LSI.
3. Documentar el incidente + análisis de causa raíz + escalar a
   Engineering + Safety Officer.

**Ventana de acción:** la dosificación química no tiene timer
agudo (degradación lenta), PERO un evento Legionella positivo +
sintomatología cliente requiere notificación regulatoria en
**< 24 h** (ASHRAE 188 + jurisdiccional).
