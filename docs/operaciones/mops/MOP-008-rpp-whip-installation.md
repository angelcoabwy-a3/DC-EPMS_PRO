# MOP-008 — RPP: Instalación de Látigos (Whips) Bajo Piso Falso / Bandeja Aérea

**Asset Category:** RPP / Whip · **Work Mode:** De-energizado del
breaker aguas arriba con LOTO. **Compliance:** CSA Z462-24, NEC
Article 645 (Information Technology Equipment), IEC 60309 / NEMA
connector standards.

---

## 1. Alcance y Objetivo

Despliegue de cables de potencia (whips) desde el RPP hacia los racks
nuevos, ya sea bajo piso falso o en bandeja aérea, garantizando
radios de curvatura, etiquetado normativo + conectores IEC 309 /
NEMA correctos para la corriente nominal.

**Equipo objetivo:** RPP (`rpp_a1` / etc.) + cable run + rack
destino. **Ubicación:** sala blanca / pasillo frío.

---

## 2. Evaluación de Impacto y Riesgos

- **Impacto en carga IT:** ninguno directo si el circuito es nuevo
  (el rack aún no recibe esa rama); si se trata de un cordón existente
  bajo modificación, el rack pierde un path.
- **Nivel de energía incidente:** Arc Flash Categoría 2 en el RPP
  durante la conexión final del whip.
- **Dependencias aguas arriba:** breaker del RPP que servirá al whip.
- **Dependencias aguas abajo:** rack + rPDU destino.
- **Riesgos físicos:** radio de curvatura insuficiente daña el
  aislamiento; tray overloading; obstrucción de pasillos / accesos
  para futuros servicios.

---

## 3. Requisitos Previos (Prerrequisitos)

- Diseño del run aprobado (longitud, bandeja, radio de curvatura,
  conectores) + cable verificado por calibre + corriente nominal.
- **LOTO** en breaker upstream del RPP + **PPE Cat 2** per
  **CSA Z462-24**.
- **PRE-CHECK** (S-DISTRIBUTION-01): revisar **historial de alarmas**
  del RPP de los últimos 30 días + verificar **estado de la caja
  SCR del STS upstream** (la nueva conexión del whip implica un
  transitorio inicial sobre la rama; el STS debe estar sano).
- **Herramientas:** crimpadora calibrada para los conectores
  específicos, megger (1 kV típico), multímetro calibrado, etiquetadora
  + códigos de colores IEC 60446, candados + tarjetas LOTO.
- **PTW** firmado por el Manager on Duty.
- Personal: técnico ejecutante + supervisor (Maker + Checker —
  **Cuatro Ojos**) + responsable de bandeja/piso falso.

---

## 4. Lista de Pasos Secuenciales

> Cada paso requiere doble firma (Cuatro Ojos / Maker-Checker).

1. Notificar al NOC + verificar que el breaker objetivo del RPP NO
   está alimentando carga IT (debe estar abierto + sin uso).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

2. Aplicar **LOTO** en breaker objetivo (candado + tarjeta
   personalizados) + Vivo-Muerto-Vivo en bornes para confirmar.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

3. Stage el cable + verificar contra plan de diseño (calibre,
   longitud, corriente nominal).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

4. Tender el cable respetando **radios de curvatura** del fabricante
   + organizando en bandeja sin obstruir accesos.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

5. Terminar conector lado rack (IEC 309 o NEMA según diseño);
   crimpear con herramienta calibrada.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

6. Terminar conector lado RPP; reapretar a torque del fabricante.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

7. **Prueba de continuidad** (multímetro) + **prueba de
   aislamiento Megger** (1 kV típico, > 100 MΩ aceptable) + verificar
   correcta polaridad / secuencia de fases.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

8. Etiquetar el cable en ambos extremos con código de colores
   IEC 60446 + ID del circuito + retirar **LOTO** + cerrar breaker +
   verificar tensión en conector del rack (sin conectar rPDU aún).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

---

## 5. Plan de Reversión (Back-out Plan)

**Criterios de Aborto:**

- Si la **prueba de continuidad falla** o la prueba Megger reporta
  aislamiento < 100 MΩ → dejar el whip **aislado y etiquetado**;
  no energizar; reemplazar el cable.
- Si la polaridad / secuencia de fases es incorrecta → no energizar;
  re-terminar con la corrección.
- Si el radio de curvatura del run real viola la spec del fabricante
  → desinstalar + replantear el ruteo.

**Secuencia de Reversión:**

1. Abrir breaker + re-aplicar **LOTO**.
2. Desconectar el whip de ambos extremos.
3. Etiquetar el cable como "pending re-test" + dejarlo aislado o
   removerlo del run.
4. Documentar el aborto + causa en el WO.

**Ventana de reversión bounded by:** la maniobra es de instalación,
no de servicio activo; no hay deadline crítico por autonomía de
baterías ya que el rack destino aún no depende del nuevo whip.
