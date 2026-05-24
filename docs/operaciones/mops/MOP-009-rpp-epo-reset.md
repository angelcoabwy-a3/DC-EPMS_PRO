# MOP-009 — RPP: Restablecimiento Post-EPO (Humo / Fuego)

**Asset Category:** RPP · **Work Mode:** De-energizado total con
LOTO + inspección visual de daños térmicos. **Compliance:** CSA
Z462-24, NFPA 75 (Fire Protection for Information Technology
Equipment), NFPA 70E §130.

---

## 1. Alcance y Objetivo

Protocolo de restablecimiento post-EPO (Emergency Power Off) en un
RPP tras evento de humo o fuego. Incluye inspección visual de daños
térmicos en contactores y cableado, verificación de causa raíz vía
historial de alarmas, y restauración escalonada de la carga IT.

**Equipo objetivo:** RPP afectado + contactores + cableado interno +
loads aguas abajo. **Ubicación:** sala blanca / pasillo afectado.

---

## 2. Evaluación de Impacto y Riesgos

- **Impacto en carga IT:** completo (todos los racks alimentados por
  ese RPP perdieron path A o B según topología); los racks han estado
  en el path redundante mientras se ejecuta el reset.
- **Nivel de energía incidente:** Arc Flash Categoría 4 (peor caso —
  el evento puede haber degradado el aislamiento + se desconoce el
  estado interno hasta inspección).
- **Dependencias aguas arriba:** PDU upstream + breakers principales
  + sistema EPO (botón hardware).
- **Dependencias aguas abajo:** rPDUs + racks + servidores IT.
- **Riesgos primarios:** daño estructural por calor que comprometa
  el aislamiento; contactores soldados por arc; residuos de extinción
  (agente químico o polvo) en componentes eléctricos.

---

## 3. Requisitos Previos (Prerrequisitos)

- **Aprobación de bomberos / facility safety lead** confirmando que
  la escena está segura para entrar.
- **LOTO** completo en breaker upstream del RPP + **PPE Cat 4**
  contra Arc Flash per **CSA Z462-24** + **EPP químico** si hubo
  agente de extinción.
- **Revisar historial de alarmas + log de eventos del RPP** para
  identificar la causa raíz preliminar antes de cualquier reset
  (S-DISTRIBUTION-01).
- Verificar **estado de la caja SCR del STS upstream** antes de
  re-energizar el RPP — un evento de humo/fuego pudo haber estresado
  los tiristores aguas arriba; energizar con un SCR degradado podría
  cascadear la falla.
- Si el evento involucró sistema de extinción del Data Hall (agua,
  agente limpio): confirmar que el ambiente está ventilado +
  componentes secos.
- **Herramientas:** multímetro calibrado, megger, cámara
  termográfica, linterna de inspección, candados + tarjetas LOTO,
  documentación fotográfica del estado pre-reset.
- **PTW especial post-incidente** firmado por el Manager on Duty +
  Engineering.
- Personal: técnico ejecutante + supervisor (Maker + Checker —
  **Cuatro Ojos**) + Engineering on-call.

---

## 4. Lista de Pasos Secuenciales

> Cada paso requiere doble firma (Cuatro Ojos / Maker-Checker).

1. Confirmar autorización de bomberos / safety lead para acceso a
   la zona; documentar en el WO.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

2. Notificar al NOC + Engineering on-call + revisar log de alarmas
   + log de eventos del RPP para identificar causa raíz.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

3. Aplicar **LOTO** completo en breaker upstream del RPP + **PPE
   Cat 4** + verificar EPP químico si aplica.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

4. Documentación fotográfica del estado pre-reset (paneles cerrados +
   abiertos, contactores, cableado, evidencia de hollín / quemaduras /
   agente de extinción).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

5. Inspección visual interna: buscar **daño térmico** en contactores
   (deformación, contactos soldados, decoloración severa), aislamiento
   degradado, residuos de extinción.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

6. **Vivo-Muerto-Vivo** en bornes principales para confirmar ausencia
   de tensión + prueba **Megger** de aislamiento en cableado interno
   (umbral del fabricante; típico > 100 MΩ).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

7. Si la inspección + Megger son OK: limpiar residuos con productos
   compatibles + reemplazar contactores comprometidos + reset manual
   del sistema EPO con autorización de Engineering.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

8. Reinstalar paneles + retirar **LOTO** + energizar breaker upstream +
   verificar V/Hz en el RPP + escaneo termográfico inicial bajo
   carga mínima.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

9. Restaurar carga IT **escalonadamente** (racks en grupos pequeños,
   verificando estabilidad entre cada grupo) hasta el 100% nominal.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

---

## 5. Plan de Reversión (Back-out Plan)

**Criterios de Aborto:**

- Si la **inspección visual revela daño estructural** (carcasa
  deformada, aislamiento severamente degradado, evidencia de fuego
  sostenido) → **NO re-energizar**; mantener **LOTO** hasta
  inspección de bomberos / fabricante.
- Si la prueba **Megger reporta aislamiento < umbral del fabricante**
  → no re-energizar; reemplazar cableado / componentes afectados.
- Si en el paso 8 la termografía inicial revela hot-spots anómalos
  bajo carga mínima → re-aplicar **LOTO** + diagnóstico profundo
  antes de continuar.

**Secuencia de Reversión (estado seguro):**

1. Reinstalar paneles frontales del RPP.
2. Mantener **LOTO** en breaker upstream.
3. El RPP queda fuera de servicio hasta dictamen de Engineering o
   fabricante.
4. Documentar el WO con evidencia fotográfica + medidas Megger +
   próxima acción (inspección, reemplazo, certificación post-
   incidente).
5. Notificar al NOC + Manager on Duty + cliente / stakeholder según
   matriz de escalamiento del incidente original.

**Ventana de reversión bounded by:** los racks aguas abajo dependen
del path redundante; el reset debe completarse antes que ese path
único exhiba degradación (típicamente coordinar con CET para no
exceder 4 h en single-path).
