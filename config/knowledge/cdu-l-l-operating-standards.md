# Base de Conocimiento para Procedimientos de L-L CDU

**Status:** Operational knowledge — indexed by GraphRAG and surfaced to
the Procedure Architect agent when authoring SOP / MOP / EOP / EMP
documents for Liquid-to-Liquid Coolant Distribution Units.

**Source:** Vendor + ASHRAE TC 9.9 operational guidance for L-L CDUs in
Tier IV DLC deployments. Citations preserved as `[cite: NNN]` so the
LLM author can quote back the source. Mirrors the format of the other
`config/knowledge/*.md` documents (CSA Z462-24, OCP LVDC, etc.).

---

## 1. Standard Operating Procedures (SOP) — Operación Normal

Esta sección contiene los parámetros base para inspecciones rutinarias
y las condiciones normales de funcionamiento del equipo.

* **Condiciones Ambientales y Térmicas:** La temperatura de operación
  permitida es de 17 °C a 65 °C [cite: 92]. El fluido refrigerante debe
  suministrarse a los equipos de TI a una temperatura de al menos 2 °C
  por encima del punto de rocío del ambiente para evitar la
  condensación [cite: 92, 228].
* **Presión de Operación:** La presión máxima permitida que se
  suministra al sistema de refrigeración de tecnología (TCS) es de
  100 psi (690 kPa) [cite: 78].
* **Química y Calidad del Fluido:** Es obligatorio realizar un
  monitoreo periódico de la calidad del fluido para sostener una
  operación continua [cite: 167]. Se deben extraer muestras
  periódicamente de la trayectoria activa del flujo (por ejemplo, a
  los 0, 7 y 14 días) para analizar la química del fluido mediante
  técnicas como ICP-MS, GC-MS o LC-MS [cite: 371, 372].
* **Control de Parámetros Químicos:** El pH y la conductividad
  eléctrica del refrigerante deben mantenerse estrictamente dentro de
  los rangos recomendados por el proveedor del fluido [cite: 374].

## 2. Methods of Procedure (MOP) — Mantenimiento Planificado

Estos puntos establecen los lineamientos técnicos para el trabajo por
pasos durante ventanas de mantenimiento.

* **Reemplazo de Filtros:** El mantenimiento de filtros y bombas debe
  aprovechar las configuraciones intercambiables en caliente
  (hot swappable) cuando el diseño de la CDU lo permita [cite: 351].
  Los filtros deben mantener los estándares nominales: el filtro
  primario debe ser de ≤ 200 micrones y el filtro secundario de
  ≤ 50 micrones [cite: 92].
* **Servicio de Fluidos (Llenado y Purgado):** Cualquier fluido o
  químico que se utilice para limpiar o purgar el sistema debe ser
  compatible con el fluido refrigerante que se usa en operación
  [cite: 177, 178]. El purgado final siempre debe realizarse con el
  fluido refrigerante real antes de poner el sistema en línea, con el
  fin de reducir la dilución [cite: 179]. Se aconseja utilizar carros
  móviles de llenado y purgado para facilitar este procedimiento
  [cite: 180].
* **Limpieza de Componentes Internos:** Antes y durante los
  mantenimientos mecánicos mayores, todas las piezas deben estar
  libres de desechos de fabricación, aceites y objetos extraños (FOD)
  [cite: 162]. En componentes mecanizados se debe usar lavado a
  presión con vapor o baños ultrasónicos [cite: 165]. Si se utiliza
  aire comprimido para secar, este debe pasar por una configuración
  de filtro adecuada para entregar aire limpio [cite: 164].
* **Gestión de Tuberías y Cables:** Al ensamblar componentes, el
  enrutamiento eléctrico y de tuberías debe organizarse
  meticulosamente para no obstruir los accesos en futuros servicios
  de mantenimiento [cite: 204].

## 3. Emergency Operating Procedures (EOP) y Emergency Maintenance (EMP)

Información crítica para la detección, escalamiento y contención de
fallos inesperados.

* **Contención de Fugas de Fluido:** El controlador de la CDU cuenta
  con mecanismos de seguridad automatizados, los cuales pueden cortar
  la energía a las bombas o cerrar/abrir válvulas para proteger el
  equipo y a los operadores ante incidentes de fuga [cite: 144]. Las
  cuerdas de los sensores de fugas deben estar enrutadas en
  concordancia con la ruta del flujo de refrigerante para permitir
  una detección oportuna [cite: 206].
* **Respuesta a Alarmas del Sistema:** El sistema emitirá alarmas que
  requieren atención inmediata si el nivel de refrigerante es bajo,
  si se detecta una fuga, o si la presión, la temperatura o el flujo
  se desvían de los puntos de ajuste establecidos
  [cite: 142, 143, 168].
* **Gestión de Fallos en Bombas:** La infraestructura utiliza
  redundancia de bombas (N+1 o superior), la cual es esencial para
  mantener la refrigeración en la sala mientras se repara la bomba
  averiada [cite: 128].
* **Prevención de Condensación Anormal:** En caso de que se opere en
  condiciones de baja temperatura, se debe asegurar que el
  aislamiento de las tuberías y la circulación de derivación (bypass)
  funcionen correctamente para evitar la formación de condensación
  [cite: 229].

## 4. Verificación Post-Mantenimiento

* **Inspección Visual Requerida:** Todo trabajo mecánico o ajuste
  debe culminar con una inspección visual para verificar que la
  unidad cumpla con los estándares estéticos, no tenga escombros y
  esté libre de materiales peligrosos (FOD o químicos de limpieza)
  [cite: 191].
* **Prueba de Presión:** Cada vez que se realicen pruebas de
  rendimiento mecánico o térmico (o después de intervenir el lazo de
  tuberías), se debe realizar una prueba de presión hidrostática
  para validar que no haya fugas ni daños estructurales [cite: 357].

---

## Cross-references for the Procedure Architect

When generating procedures that touch CDU equipment, the Architect
should surface the relevant section verbatim (with the cite marker)
so the operator has the source of truth:

| Doc type | Touchpoints in this knowledge base |
|---|---|
| **SOP** | §1 (rounds, fluid sampling cadence, pH/conductivity bands) |
| **MOP** | §2 (filter swap, fluid service, FOD discipline, cable routing); §4 (post-maintenance visual + hydrostatic) |
| **EOP** | §3 (leak containment, alarm response, pump failover) |
| **EMP** | §3 (escalation matrix anchored on the CDU controller's automated safety mechanisms) |

The MOP audit gate (LOTO + PPE + CSA Z462-24) in
`backend/agents/procedure_architect.py` is the FIRST gate. The CDU
sections above add domain-specific operational depth — they do NOT
substitute for the safety gate. A MOP draft that names CDU filter
specs but omits LOTO still fails the audit and gets `hard_stop`.
