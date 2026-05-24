# MOP-010 — Busway: Instalación / Retiro de Tap-off Boxes (Trabajo en Vivo)

**Asset Category:** Busway / Tap-off Box · **Work Mode:** LIVE work
(busway energizado; NO LOTO sobre el busway). **Compliance:**
CSA Z462-24, NFPA 70E §130, IEC 61439-6 (busbar trunking systems).

---

## 1. Alcance y Objetivo

Operación de alto riesgo: enchufar o retirar una `tap-off box` (caja
de derivación) en un busway energizado. La inserción/extracción
mecánica de la garra sobre las barras vivas requiere postura corporal
disciplinada, PPE Cat 4 y herramientas aisladas certificadas.

**Equipo objetivo:** sector específico del busway + tap-off box (par
de garras + carcasa). **Ubicación:** pasillo de datos / techo del
white space.

---

## 2. Evaluación de Impacto y Riesgos

- **Impacto en carga IT:** ninguno si el tap-off es nuevo (no
  alimenta carga aún); si se retira uno activo, los racks aguas abajo
  pierden ese cordón y dependen del path redundante.
- **Nivel de energía incidente:** **Arc Flash Categoría 4 (peor caso
  de la planta)** — la energía incidente disponible en un busway
  energizado es máxima.
- **Dependencias aguas arriba:** breaker principal del busway + STS
  upstream.
- **Dependencias aguas abajo:** racks o equipo IT servido por el
  tap-off afectado.
- **Riesgo primario:** arc flash durante inserción/extracción
  mecánica si la garra no acopla limpio; quemaduras térmicas;
  proyección de metal fundido.

---

## 3. Requisitos Previos (Prerrequisitos)

- **LOTO NO aplica** (busway energizado por diseño durante esta
  maniobra); en su lugar:
  - Respetar **límite de aproximación restringida** per
    **CSA Z462-24** sección 130.4
  - **PPE Cat 4** completo: ropa ignífuga + guantes dieléctricos con
    protector de cuero + pantalla facial Arc Flash + balaclava +
    botas dieléctricas
  - **Postura corporal LATERAL** al busway (NUNCA frontal) durante
    la inserción mecánica para minimizar exposición del cuerpo a un
    arc flash potencial
- Herramientas aisladas certificadas para clase de tensión del
  busway.
- **Revisar historial de alarmas + estado caja SCR** del STS upstream
  (S-DISTRIBUTION-01) para confirmar que no hay condición
  pre-existente que pueda exacerbarse.
- **PTW especial para trabajo en vivo** firmado por el Manager on
  Duty + Engineering on-call presente o disponible inmediato.
- Personal: técnico calificado en racking de busway + supervisor
  (Maker + Checker — **Cuatro Ojos**); ambos con PPE Cat 4.

---

## 4. Lista de Pasos Secuenciales

> Cada paso requiere doble firma (Cuatro Ojos / Maker-Checker).

1. Notificar al NOC el inicio de la maniobra + verificar que
   Engineering on-call está disponible.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

2. Revisar historial de alarmas del busway + estado de la caja SCR
   del STS upstream; documentar pre-checks.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

3. Verificar que el sector del busway donde se va a operar NO tiene
   alarmas activas (sobre-temperatura, hot-spot termográfico
   reciente).
   `[ ] Técnico: __________  [ ] Supervisor: __________`

4. Ambos operadores inspeccionan + verifican PPE Cat 4 completo;
   establecer perímetro físico de exclusión + comunicar al área.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

5. Posicionarse **LATERAL al busway** (NUNCA frontal) +
   confirmar herramientas aisladas + breaker del tap-off OFF y
   bloqueado en posición OFF antes de la inserción mecánica.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

6. Inserción mecánica con presión NORMAL controlada (sin forzar):
   alinear garras + insertar hasta el tope mecánico de diseño +
   confirmar acople visual completo.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

7. Verificar **LEDs de estado** de la tap-off box (presencia de
   tensión, polaridad correcta, sin alarmas) DESDE FUERA del límite
   de aproximación restringida.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

8. Si todo OK: cerrar breaker del tap-off (controla la salida hacia
   el cable downstream) + verificar tensión nominal en bornes de
   salida.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

9. Documentar fotográficamente la instalación + retirar perímetro de
   exclusión + notificar al NOC la finalización.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

---

## 5. Plan de Reversión (Back-out Plan)

**Criterios de Aborto:**

- Si en el paso 6 la caja **NO inserta mecánicamente con presión
  normal** (resistencia anormal, desalineación, sonido metálico
  irregular) → **RETIRAR INMEDIATAMENTE** y NO insistir; NO FORZAR
  bajo ninguna circunstancia.
- Si durante o después de la inserción aparece un olor inusual,
  chispas visibles, o cualquier LED de alarma en la caja → retirar +
  evacuar el área + notificar a Engineering.
- Si los LEDs en el paso 7 no se iluminan correctamente → el acople
  eléctrico falló; retirar la caja.

**Secuencia de Reversión:**

1. Si la caja no acopla: retirar la box con presión inversa
   controlada + etiquetar como **"pending vendor inspection"**.
2. Mantener perímetro de exclusión hasta confirmar que el busway
   no exhibe daño post-intento.
3. Notificar al NOC + Manager on Duty + Engineering del aborto +
   causa preliminar.
4. La tap-off box queda fuera de uso hasta dictamen del fabricante;
   el sector del busway puede continuar en servicio si no hubo daño
   colateral verificado.

**Nota safety-critical:** un intento de "forzar" la inserción es la
causa raíz documentada de los arc flash más severos en busway de
data centers — la regla "no forzar" es **innegociable**.
