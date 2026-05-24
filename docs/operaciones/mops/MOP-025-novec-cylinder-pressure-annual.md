# MOP-025 — Novec/FM-200: Verificación Anual de Presión de Cilindro

**Asset Category:** Clean-Agent Suppression (Novec 1230 / HFC-227ea /
FM-200) · **Work Mode:** De-energizado parcial — panel en
**Maintenance Mode** + solenoides aislados + cilindro físicamente
intervenido. **Compliance:** NFPA 12 (Standard on Clean Agent Fire
Extinguishing Systems), NFPA 75, CSA Z462-24, ISO 14520, FM 7745.

---

## 1. Alcance y Objetivo

* **Identificador (Tag):** NOVEC-A (cilindro principal por zona) +
  cilindros redundantes si aplica (NOVEC-A1, NOVEC-A2 en banco N+1)
* **Estado Final Esperado:** presión documentada + recharge si
  < 90% nominal + solenoides re-conectados + panel re-armado +
  PTW cerrado con evidencia fotográfica

Verificación anual obligatoria de la presión interna del cilindro
de agente limpio (Novec 1230 típicamente 25 bar / 360 PSI a 21 °C
nominal). Cilindros con pérdida de presión > 10% requieren
recharge antes del próximo annual.

**Equipo objetivo:** cilindro de Novec/FM-200 + manómetro adjunto +
panel de control asociado. **Ubicación:** sala de cilindros de
supresión / fire suppression closet.

---

## 2. Evaluación de Impacto y Riesgos

- **Vector Life Safety:** riesgo de **descarga accidental durante
  manipulación**; un cilindro presurizado a 25 bar libera 50+ kg de
  Novec en < 10 segundos si el manómetro o la válvula se daña.
- **Vector Combustible (químico):** Novec 1230 es no-tóxico y
  no-conductivo, PERO en concentraciones > 10% causa hipoxia
  (riesgo asfixia en sala cerrada). FM-200 produce HF + fluoruro
  de carbonilo bajo descomposición térmica.
- **Impacto en carga IT:** ninguno si el panel se mantiene en
  Maintenance Mode + solenoides aislados. Riesgo INDIRECTO: si la
  presión queda mal documentada, una emergencia real puede no
  tener supresión adecuada.
- **Nivel de energía incidente:** Arc Flash Categoría 1 en el
  panel de control + Categoría 2 en el solenoide si se debe
  intervenir cableado.
- **Riesgos mecánicos:** cilindro caído desde altura es projectile
  letal (25 bar de almacenamiento); bonding del cilindro durante
  manipulación es obligatorio.

---

## 3. Prerrequisitos (Gatekeeper Universal)

- **Panel en Maintenance Mode** + solenoides eléctricamente
  aislados + cilindros físicamente asegurados con cadenas de
  retención per NFPA 12.
- **PPE Cat 2** per **CSA Z462-24** (manipulación de panel) +
  **PPE químico**: gafas selladas, guantes nitrilo, traje
  anti-químicos clase A si la sala carece de ventilación adecuada.
- **Respirador autónomo SCBA** disponible en el límite del cuarto
  para emergencia de descarga accidental.
- **LOTO eléctrico** en el solenoide de descarga + **LOTO
  mecánico** en la válvula manual del cilindro (cadena + candado
  + tarjeta) + **Vivo-Muerto-Vivo** en bornes del solenoide.
- **Bonding cable** entre cilindro y rack durante manipulación
  (prevención estática para entornos potencialmente explosivos).
- **Operabilidad de Agentes (Health Check):** Checker + HVAC AI
  (verificar ventilación post-intervención) `ONLINE` vía **MCP**.
- **PTW especial Life Safety** firmado por Manager on Duty +
  Safety Officer + Fire Marshal cuando aplique jurisdiccionalmente.
- **Herramientas:** manómetro calibrado de respaldo (verificación
  cruzada), torquímetro aislado, balanza para pesado del cilindro
  (validación cruzada de masa de agente), cámara fotográfica para
  evidencia, candados + tarjetas LOTO duales.
- Personal: técnico fire suppression certificado + supervisor
  (Maker + Checker — **Cuatro Ojos**) + observador exterior con
  SCBA listo.

---

## 4. Lista de Pasos Secuenciales

> Cada paso requiere doble firma (Cuatro Ojos / Maker-Checker).

1. Notificar al NOC + fire department + verificar historial de
   alarmas del panel de los últimos 365 días.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

2. Aplicar **Maintenance Mode** en el panel + confirmar en HMI
   "Discharge Inhibited" para la zona del cilindro objetivo.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

3. Aplicar **LOTO eléctrico** al solenoide de descarga +
   **Vivo-Muerto-Vivo** en bornes para confirmar 0 V.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

4. Aplicar **LOTO mecánico** en la válvula manual del cilindro
   (cadena + candado) + verificar cadena de retención
   estructural intacta.

   > `[HOLD POINT]` **CONFIRMAR FÍSICAMENTE** que ambos LOTOs están
   > aplicados + verificar bypass de solenoide en HMI antes de
   > tocar el cilindro. Sin esta confirmación dual, NO se procede.

   `[ ] Técnico: __________  [ ] Supervisor: __________`

5. Establecer **bonding cable** entre cilindro y rack metálico
   (verificar continuidad con multímetro: < 1 Ω).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

6. Leer manómetro adjunto del cilindro + capturar fotografía con
   resolución legible. Comparar contra manómetro calibrado de
   respaldo (deben coincidir ± 5%).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

7. Pesar el cilindro con balanza calibrada + comparar masa actual
   contra masa nominal stencil del cilindro. Diferencia debe
   estar dentro de ± 5% (validación cruzada de carga).

   > `[HOLD POINT]` Si la presión < 90% nominal Y/O la masa difiere
   > > 5% → el cilindro requiere recharge antes de re-armar.
   > Etiquetar como "PENDING RECHARGE" + escalar al vendor.

   `[ ] Técnico: __________  [ ] Supervisor: __________`

8. Documentar evidencia fotográfica (manómetro + balanza + sticker
   de fecha de inspección actualizado) + adjuntar al WO.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

9. Retirar **bonding cable** + retirar **LOTO mecánico** + retirar
   **LOTO eléctrico** + retirar Maintenance Mode + verificar panel
   muestra "Normal — Armed" durante 15 min.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

---

## 5. Plan de Reversión (Back-out Plan)

**Criterios de Aborto (parameterized triggers):**

- Si en el paso 4 los **LOTOs duales no se pueden aplicar** (cadena
  rota, candado defectuoso) → abortar; cilindro NO se manipula;
  programar maintenance de hardware de retención.
- Si en el paso 6 los **dos manómetros difieren > 10%** entre sí
  → el manómetro adjunto está derivado; etiquetar para reemplazo;
  documentar lectura del calibrado + reportar al fabricante.
- Si en el paso 6 la **presión < 85% nominal** (typically < 21
  bar para Novec 1230) → el cilindro NO satisface NFPA 12 §4.7.4;
  recharge obligatoria antes de re-armar. NO retirar LOTOs.
- Si en el paso 7 la **masa difiere > 10%** de stencil → pérdida
  significativa de agente; mismo trato que presión < 85%.
- Si durante CUALQUIER paso se detecta **olor químico, sonido de
  fuga, o aerosol visible** → evacuar la sala + activar SCBA +
  cerrar válvula manual remotamente si es posible + notificación
  HAZMAT inmediata.

**Secuencia de Restauración:**

1. Si cilindro requiere recharge: dejar en LOTO completo +
   etiquetar "OUT OF SERVICE PENDING RECHARGE" + actualizar
   sticker con fecha + escalar al fabricante con plazo < 30 días.
2. Si cilindro pasa todos los checks: retirar bonding, LOTOs,
   Maintenance Mode en orden inverso al de aplicación.
3. Confirmar el panel reporta "Normal — Armed" + cilindro
   pressurizado dentro de spec durante 15 min de monitoreo.
4. Notificar al NOC + fire department la finalización.
5. Documentar el WO con todas las lecturas + evidencias
   fotográficas + próxima fecha de inspección (= hoy + 365 días).

**Ventana de reversión bounded by:** si el cilindro queda fuera de
servicio sin reemplazo redundante, la zona pierde supresión
automática — el sitio depende de respuesta humana + agua de
sprinkler aguas abajo. Coordinar con fire department el plazo de
recharge si > 24 h.
