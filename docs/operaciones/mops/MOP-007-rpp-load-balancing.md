# MOP-007 — RPP: Balanceo de Carga de Fases A/B/C

**Asset Category:** RPP (Remote Power Panel) · **Work Mode:**
De-energizado por circuito (per-breaker LOTO). **Compliance:**
CSA Z462-24, NFPA 70E, NEC 220.61 (neutral conductor load balance).

---

## 1. Alcance y Objetivo


* **Identificador (Tag):** RPP-A1 / RPP-A2 / RPP-B1 / RPP-B2
* **Estado Final Esperado:** Fases A/B/C balanceadas (ninguna > 80% nominal); breakers cerrados + circuitos re-asignados según plan

Re-balancear las fases A, B y C en un RPP al instalar nuevos circuitos
de rack, asegurando que ninguna línea supere el 80% de su capacidad
nominal y previniendo disparos térmicos por desequilibrio.

**Equipo objetivo:** RPP identificado (`rpp_a1` / `rpp_a2` / etc.) +
circuitos individuales bajo intervención. **Ubicación:** sala blanca.

---

## 2. Evaluación de Impacto y Riesgos


- **Vector Eléctrico (Arc Flash Cat 2 en breakers individuales; sobre-corriente en neutro NEC 220.61 si desbalance > 10%)**

- **Impacto en carga IT:** los racks afectados por el reruteo de
  circuitos pierden uno de sus dos cordones de alimentación durante
  el cambio; el cordón redundante (path B) DEBE estar verificado
  como sano antes de iniciar.
- **Nivel de energía incidente:** Arc Flash Categoría 2 en breakers
  individuales del RPP.
- **Dependencias aguas arriba:** PDU que alimenta el RPP.
- **Dependencias aguas abajo:** rPDUs (regletas) en los racks
  afectados + servidores IT.
- **Riesgo crítico de desbalance:** desbalance > 10% sostenido causa
  sobre-corriente en el neutro (NEC 220.61) + disparo térmico de
  breaker principal.

---

## 3. Requisitos Previos (Prerrequisitos)

- Cálculo previo del balance objetivo (mediciones de corriente
  fase-por-fase antes del cambio + plan de re-asignación).
- **LOTO** por circuito en los breakers afectados + **PPE Cat 2**
  per **CSA Z462-24**.
- **PRE-CHECK** (S-DISTRIBUTION-01): revisar **historial de alarmas**
  del RPP de los últimos 30 días para descartar overload latente
  en alguna fase, **+ verificar estado de la caja SCR del STS
  upstream** (la rama del RPP depende del STS aguas arriba; un SCR
  degradado puede no soportar el transitorio de cualquier breaker
  reapretado).
- **Herramientas:** pinza amperimétrica calibrada, multímetro
  calibrado, etiquetas normativas (IEC 60446 código de colores),
  candados + tarjetas LOTO por circuito.
- **PTW** firmado por el Manager on Duty.
- Personal: técnico ejecutante + supervisor (Maker + Checker —
  **Cuatro Ojos**).

- **Operabilidad de Agentes (Health Check):** confirmar que el Agente Revisor (Checker) y los Discipline AIs (HVAC AI / Electrical AI según vector) están `ONLINE` y reportando telemetría vía **MCP** antes de iniciar la maniobra.

---

## 4. Lista de Pasos Secuenciales

> Cada paso requiere doble firma (Cuatro Ojos / Maker-Checker).

1. Notificar al NOC + revisar historial de alarmas del RPP.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

2. Medir corrientes baseline en cada fase (A/B/C) con pinza
   amperimétrica; documentar en el WO.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

3. Calcular el plan de re-asignación de circuitos al/desde cada
   fase para que ninguna fase exceda el 80% de su capacidad nominal;
   adjuntar al WO.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

4. Confirmar con el CET de turno que cada rack afectado tiene su
   cordón redundante (path B) sano y absorbiendo carga.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

5. Abrir el primer breaker objetivo + aplicar **LOTO** (candado +
   tarjeta personalizados) + **Vivo-Muerto-Vivo** en bornes de salida.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

   > [HOLD POINT] Confirmar ausencia de tensión en bornes del breaker + redundancia path B activa antes de re-conectar circuito.

6. Reconectar el circuito a la fase nueva según plan; reapretar a
   torque del fabricante.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

7. Retirar **LOTO** + cerrar breaker + medir corriente nueva con
   pinza amperimétrica.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

8. Repetir pasos 5-7 para cada circuito en el plan; documentar el
   nuevo balance fase-por-fase al final.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

---

## 5. Plan de Reversión (Back-out Plan)

**Criterios de Aborto:**

- Si tras un cambio el desbalance entre fases > 10% se mantiene →
  restaurar el ruteo previo del circuito que generó el desequilibrio
  antes de cargar IT en el nuevo ruteo.
- Si en el paso 4 algún rack no tiene cordón redundante sano →
  **abortar** el cambio en ese circuito; programar ventana específica
  cuando el path B esté disponible.
- Si en el paso 5 la prueba Vivo-Muerto-Vivo detecta tensión residual
  → **detener** + investigar.

**Secuencia de Reversión (por circuito):**

1. Abrir breaker afectado + aplicar **LOTO**.
2. Reconectar a la fase original.
3. Cerrar breaker + verificar corriente.
4. Documentar el aborto + causa en el WO.

**Ventana de reversión bounded by:** la maniobra completa debe
realizarse en una ventana < 4 h; cada circuito individual se reabre
en < 5 min para minimizar la exposición del rack al path B único.
