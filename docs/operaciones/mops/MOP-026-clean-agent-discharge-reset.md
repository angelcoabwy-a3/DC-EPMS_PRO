# MOP-026 — Clean Agent: Restablecimiento Post-Discharge (Recovery)

**Asset Category:** Clean-Agent Suppression (Novec/FM-200) · **Work
Mode:** De-energizado completo del panel + inspección visual
forense + cilindro reemplazado + ventilación + re-armado.
**Compliance:** NFPA 12, NFPA 75, NFPA 70E §130, CSA Z462-24,
ASHRAE 188 (control microbiológico post-evento), ISO 14520.

---

## 1. Alcance y Objetivo

* **Identificador (Tag):** NOVEC-A (cilindro descargado, requiere
  reemplazo) + zona afectada
* **Estado Final Esperado:** panel reset + cilindro nuevo
  instalado a presión nominal + sala ventilada + sistema re-armado
  + log de evento + inspección de daño completada + cliente
  notificado

Recuperación post-descarga del sistema de supresión: tras un
disparo real (fire event) o accidental (false-positive), el agente
está agotado, el panel en estado de alarma latched, y la zona
sin protección activa. Este MOP guía la restauración completa.

**Equipo objetivo:** panel de supresión + cilindro descargado +
red de boquillas + sala afectada. **Ubicación:** sala de
cilindros + Data Hall afectado.

---

## 2. Evaluación de Impacto y Riesgos

- **Vector Life Safety:** PRIORIDAD MÁXIMA. Si el evento fue
  fuego real, hay riesgo de re-ignición + daño estructural +
  contaminación química residual.
- **Vector Combustible (químico):** Novec residual en concentraciones
  acumuladas en aire de la sala puede causar hipoxia hasta
  ventilarse. FM-200 + temperatura > 800 °C produce HF + fluoruro
  de carbonilo (altamente tóxico) — requiere análisis
  atmosférico antes de re-entrar.
- **Impacto en carga IT:** durante la descarga, racks pueden haber
  sido apagados por descarga eléctrica preventiva (EPO trigger
  asociado). Restauración eléctrica precede al re-armado de
  supresión.
- **Tiempo de Inercia:** N/A, pero la sala carece de protección
  activa hasta completar este MOP → urgencia operativa.
- **Nivel de energía incidente:** Arc Flash Categoría 4 si EPO se
  activó + paneles eléctricos requieren inspección. PPE Cat 4
  obligatorio en bus principal.
- **Riesgos estructurales:** equipo de detección puede estar
  dañado por temperatura del fuego + manguitos de aspiración
  pueden estar derretidos.

---

## 3. Prerrequisitos (Gatekeeper Universal)

- **AUTORIZACIÓN DE BOMBEROS / FIRE MARSHAL** confirmando que la
  escena está segura para entrar + el ambiente está ventilado +
  no hay riesgo de re-ignición.
- **Análisis atmosférico** con detector multi-gas (O2 ≥ 19.5%, CO
  < 35 ppm, HF < 3 ppm para FM-200, ausencia de combustibles) en
  cada punto cardinal de la sala.
- **LOTO completo** en alimentación del panel de supresión +
  alimentación del Data Hall afectado + cilindros remanentes en la
  zona + **Vivo-Muerto-Vivo** en cada disconnect.
- **PPE Cat 4** contra Arc Flash per **CSA Z462-24** +
  **PPE químico clase A** (Novec residual) + **respirador SCBA**
  obligatorio para primera entrada.
- **Operabilidad de Agentes (Health Check):** Checker + Discipline
  AIs (HVAC AI para ventilación, Electrical AI para EPO reset)
  `ONLINE` vía **MCP**.
- **PTW post-incident** firmado por Manager on Duty + Safety
  Officer + Fire Marshal + representante de seguros si aplica.
- **Documentación fotográfica** mandatoria pre-entrada para
  preservar evidencia (cause-of-loss + insurance).
- **Cilindro de reemplazo** verificado + presión nominal +
  certificado de carga reciente disponible.
- **Herramientas:** detector multi-gas calibrado, cámara
  fotográfica, multímetro, megger (1 kV), bonding cable, balanza,
  manómetro calibrado, EPP completo descrito arriba.
- Personal: equipo coordinado mínimo 4 personas (técnico fire
  suppression certificado + electricista certificado + safety
  officer + observador con SCBA) + supervisor remoto en HMI
  (Maker + Checker — **Cuatro Ojos**).

---

## 4. Lista de Pasos Secuenciales

> Cada paso requiere doble firma (Cuatro Ojos / Maker-Checker).
> El cronómetro arranca cuando bomberos autorizan el acceso.

1. Confirmar **autorización explícita de bomberos / Fire Marshal**
   + documentar firma con fecha/hora.

   > `[HOLD POINT]` **SIN AUTORIZACIÓN DE BOMBEROS, NO SE ENTRA.**
   > Este es un gate hard — no negociable.

   `[ ] Técnico: __________  [ ] Supervisor: __________`

2. Realizar **análisis atmosférico** desde el límite de la sala
   con detector multi-gas + confirmar lecturas dentro de
   tolerancia + documentar.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

3. Aplicar **LOTO completo** en panel de supresión + Data Hall
   feeder + cilindros remanentes + **Vivo-Muerto-Vivo** en cada
   disconnect.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

4. Documentación fotográfica integral del estado pre-restauración:
   panel HMI, área de cilindros, racks afectados, residuos
   visibles. Adjuntar al WO + al claim de insurance.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

5. Inspección visual estructural de la sala con **PPE Cat 4 +
   SCBA**: buscar daño térmico, derretimiento de tubería de
   aspiración VESDA, daño en racks IT, residuos.

   > `[HOLD POINT]` Si hay **evidencia de daño estructural** (
   > paneles deformados, aislamiento de cableado derretido) → NO
   > re-energizar; escalar a estructural engineer + dejar LOTO.

   `[ ] Técnico: __________  [ ] Supervisor: __________`

6. Remover cilindro descargado (peso significativamente menor +
   manómetro a 0) + transportar con bonding cable + etiquetar
   "DISCHARGED — PENDING DISPOSAL" + chain of custody documentada.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

7. Instalar cilindro de reemplazo verificado: bonding cable
   primero, luego conexión a manifold, **torque a spec del
   fabricante** con torquímetro aislado, **verificar presión
   nominal en manómetro adjunto** + cross-check con manómetro
   calibrado.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

8. Reset del panel de supresión (latched alarm clear) + ejecutar
   self-test del panel + verificar comunicación con VESDA + verificar
   solenoides responden a comando de test (en Maintenance Mode).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

9. Retirar LOTOs en orden inverso (paneles primero, luego cilindro,
   luego feeder Data Hall) + retirar Maintenance Mode + verificar
   panel reporta "Normal — Armed" durante 30 min de monitoreo
   continuo.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

---

## 5. Plan de Reversión (Back-out Plan)

**Criterios de Aborto (parameterized triggers):**

- Si en el paso 1 bomberos **NO autorizan acceso en < 4 h** del
  evento → escalar a Manager on Duty + considerar cierre temporal
  de la zona; NO entrar bajo ninguna circunstancia.
- Si en el paso 2 el análisis atmosférico detecta **O2 < 19.5%
  O HF > 3 ppm O CO > 35 ppm** → ventilar adicional 30 min +
  re-medir; si persiste, escalar a HAZMAT.
- Si en el paso 5 se detecta **daño estructural** (derretimiento,
  deformación severa) → NO re-energizar; convocar structural
  engineer + insurance adjuster antes de proceder.
- Si en el paso 7 el cilindro nuevo **NO alcanza presión nominal
  en 30 s** post-instalación → cilindro defectuoso; reemplazar
  con otra unidad antes de continuar.
- Si en el paso 9 el panel reporta **trouble alarm dentro de los
  30 min** de monitoreo → NO declarar operativo; diagnosticar
  before signing the WO closed.

**Secuencia de Restauración (estado seguro alternativo si full
restauración falla):**

1. Re-aplicar **LOTO** en panel + cilindros + feeder.
2. Etiquetar la zona "OUT OF SERVICE — NO FIRE SUPPRESSION" en
   gran cartel en cada acceso + notificar al fire department
   jurisdiccional.
3. Coordinar **fire watch humano** (24/7) hasta que la
   restauración complete + documentar shifts.
4. Escalar a fabricante de supresión + a Engineering para
   diagnóstico completo.
5. Re-armar la zona solo con autorización conjunta de Fire
   Marshal + Manager on Duty.

**Ventana de reversión bounded by:** la zona sin protección
activa de clean agent requiere **fire watch humano cada 30 min**
per NFPA 75 §11.2; restauración debe completarse en < 8 h o
escalar fire watch a continuo (24/7).
