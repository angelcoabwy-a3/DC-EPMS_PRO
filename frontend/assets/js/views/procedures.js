/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — views/procedures.js
 * ROADMAP V11 Epic 6 — Procedure Architect HMI.
 *
 * Operator-facing surface for the LLM-authored SOP / MOP / EOP / EMP
 * documents. Companion to the deterministic compiler view (already
 * exposed by the legacy MOP browser at /mops).
 *
 * Workflow:
 *   1. Operator picks a doc_type from the dropdown + describes the
 *      context in the textarea ("Replace UPS-B battery cabinet").
 *   2. Submit -> POST /api/procedures/architect/generate.
 *   3. The backend returns {draft, safety_audit}. We render the
 *      draft content (markdown -> safe HTML) and the audit verdict
 *      pill (approve / caution / hard_stop).
 *   4. Approve -> Sign-to-Ledger button is visible. Operator clicks
 *      -> POST /api/procedures/architect/sign -> ledger entry id is
 *      shown back to the operator as proof of approval.
 *   5. hard_stop -> the Sign button is HIDDEN; the audit findings
 *      list is rendered so the operator can re-prompt with the
 *      missing safety terms.
 *
 * Contracts preserved:
 *   - S-SEC-01: every rendered field goes through escapeHTML;
 *     sanitizeHTML wraps the assembled markup. No untrusted HTML
 *     ever lands in the DOM. The markdown renderer is a
 *     deliberately-minimal escape-then-pattern-substitute pass
 *     (headers, bold, italic, code-fence, lists) — NOT a full
 *     markdown library, which would expand the attack surface.
 *   - S-DET-02 binding (server-side): the Sign endpoint re-audits
 *     content. Even if the HMI tried to forge an approved verdict,
 *     a hard_stop content body returns HTTP 403.
 *
 * Test surface: __procedures_view_test__ exposes the pure render +
 * fetch helpers, and the click dispatcher.
 * ════════════════════════════════════════════════════════════════ */

import { registerRoute } from '../core/router.js';
import { escapeHTML, sanitizeHTML } from '../core/sanitize.js';
import { isSigningEnabled, getQkdGateState } from '../core/qkd_gate.js';

const $ = (id) => document.getElementById(id);

const DOC_TYPES = ['SOP', 'MOP', 'EOP', 'EMP'];
const VERDICT_APPROVE = 'approve';
const VERDICT_CAUTION = 'caution';
const VERDICT_HARD_STOP = 'hard_stop';

// ─── Pre-defined asset picker ────────────────────────────────────────
// Curated Path-C2 asset list (per CLAUDE.md "config/site_model.yml ←
// 91 components"). Grouped by domain for the optgroup labels. The
// operator can also pick "Custom…" to type any canonical_id manually,
// or leave it blank for a site-wide procedure.
//
// This list is intentionally hardcoded (not a /api/site/components
// fetch) — keeps the view network-independent at activation, and the
// operator's most common picks load instantly. Extension path: swap
// to a fetch on activate + cache. The Custom option always escapes.
const ASSET_PRESETS = [
    { group: 'Electrical — UPS / Transformers / Switchgear', items: [
        { id: 'ups_a',         label: 'UPS A (Path A)' },
        { id: 'ups_b',         label: 'UPS B (Path B)' },
        { id: 'xfmr_a',        label: 'Transformer A' },
        { id: 'xfmr_b',        label: 'Transformer B' },
        { id: 'utility_north', label: 'Utility North (Path A)' },
        { id: 'utility_south', label: 'Utility South (Path B)' },
    ] },
    { group: 'Electrical — Distribution', items: [
        { id: 'rpp_a1', label: 'RPP A1 (Path A)' },
        { id: 'rpp_a2', label: 'RPP A2 (Path A)' },
        { id: 'rpp_b1', label: 'RPP B1 (Path B)' },
        { id: 'rpp_b2', label: 'RPP B2 (Path B)' },
        { id: 'busway_a', label: 'Busway A' },
        { id: 'busway_b', label: 'Busway B' },
    ] },
    { group: 'Mechanical — Cooling', items: [
        { id: 'chiller_1',     label: 'Chiller 1 (York YZ)' },
        { id: 'chiller_2',     label: 'Chiller 2 (York YZ)' },
        { id: 'cdu_a',         label: 'CDU A (DLC primary)' },
        { id: 'cdu_b',         label: 'CDU B (DLC primary)' },
        { id: 'cooling_tower', label: 'Cooling Tower (N+1)' },
    ] },
    { group: 'IT Halls', items: [
        { id: 'hall_1', label: 'Hall 1 (Building A)' },
        { id: 'hall_2', label: 'Hall 2 (Building A)' },
        { id: 'hall_3', label: 'Hall 3 (Building B)' },
    ] },
];

const ASSET_CUSTOM_VALUE = '__custom__';
const ASSET_NONE_VALUE = '';

// ─── Pre-defined context templates per doc_type ──────────────────────
// Click a chip to pre-fill the textarea. `{asset}` is substituted with
// the currently selected asset_id (or "the affected asset" when none
// is picked — keeps the template grammatical without a server round-
// trip). Operator can edit after the auto-fill — the chip is a starter,
// not a lock-in.
//
// 3-5 templates per doc_type chosen to span the common operator
// playbook for each category. Free-form context still works — the
// chips are a UX accelerator, not a constraint.
// MOP categorías (Commit 4 — operator catalog 2026-05-23).
// 6 categorías × 3-4 chips = 21 chip starter templates aligned with the
// electrical-infrastructure + white-space-distribution catalogs in
// `config/knowledge/{electrical,distribution}-mop-catalog.md`.
//
// Each chip body MUST contain (audit-gate contract, S-SAFETY-01):
//   - `{asset}` substitution token
//   - LOTO (or 'LOTO no aplica' for live work) -- legacy regex requires
//     'LOTO' / 'Lockout' / 'Tagout' substring presence
//   - PPE category + CSA Z462-24 (or NFPA 70E)
//   - EITHER 'Vivo-Muerto-Vivo' (de-energized) OR 'límite de
//     aproximación restringida' (live)
//   - 'Back-out' / 'Reversión' bounded by a physical metric
// The 5 universal sections come from the system prompt template; the
// chip text only needs to seed the LLM with the safety vocabulary.
const MOP_CATEGORIES = {
    ups: [
        { label: 'Bypass de mantenimiento',
          text: 'Transferir la carga de {asset} al bypass de '
                + 'mantenimiento externo (make-before-break). LOTO + '
                + 'PPE Cat 2 per CSA Z462-24. Tras la transferencia y '
                + 'apertura del banco de baterías, aplicar la '
                + 'verificación Vivo-Muerto-Vivo en los bornes internos '
                + 'antes de cualquier manipulación física. Back-out: '
                + 'si el HMI indica bypass NO sincronizado, abortar; '
                + 'la ventana de reversión está acotada por '
                + 'battery_runtime_min del BMS bajo la carga actual.' },
        { label: 'Reemplazo de baterías',
          text: 'Reemplazo de banco de baterías en {asset} (VRLA o '
                + 'Litio) durante ventana de mantenimiento. LOTO en '
                + 'interruptor de banco + PPE Cat 2 per CSA Z462-24 '
                + '(EPP químico adicional para electrolito). '
                + 'Vivo-Muerto-Vivo en bornes antes de extraer celdas. '
                + 'Back-out: si las celdas nuevas no alcanzan voltaje '
                + 'de flotación, restaurar el banco antiguo antes que '
                + 'la autonomía de la cadena redundante caiga al 50%.' },
        { label: 'Prueba sincronización con generador',
          text: 'Prueba controlada de sincronización del UPS {asset} '
                + 'con el generador. LOTO no aplica (prueba '
                + 'operacional); respetar límite de aproximación '
                + 'restringida + PPE Cat 4 per CSA Z462-24 durante la '
                + 'conmutación. Verificar walk-in del rectificador '
                + 'para limitar la corriente de recarga sin sobrecargar '
                + 'el alternador. Back-out: si el rectificador no '
                + 'limita walk-in, abortar antes de los 15 s de '
                + 'asunción de carga.' },
        { label: 'Activación EPO (restablecimiento)',
          text: 'Protocolo de restablecimiento post-EPO en {asset} '
                + '(tras un disparo controlado). LOTO en alimentación '
                + 'principal + PPE Cat 4 per CSA Z462-24. Antes de '
                + 're-energizar, Vivo-Muerto-Vivo en barras + '
                + 'inspección de cableado por daño térmico. Back-out: '
                + 'si hay signos de arc-flash interno o cableado '
                + 'degradado, no re-energizar — escalar a Engineering '
                + 'antes de cualquier carga.' },
    ],
    transformer: [
        { label: 'Energización (gestión de inrush)',
          text: 'Energización del transformador {asset} tras '
                + 'mantenimiento. LOTO removido en interruptor aguas '
                + 'arriba + PPE Cat 3 per CSA Z462-24. Verificar '
                + 'ajustes de disparo aguas arriba para evitar que la '
                + 'corriente de magnetización (inrush) dispare la '
                + 'alimentación principal. Vivo-Muerto-Vivo previo a '
                + 'remover LOTO. Back-out: si el breaker aguas arriba '
                + 'dispara por inrush en el primer intento, re-aplicar '
                + 'LOTO antes de revisar ajustes — no insistir con '
                + 're-cierres consecutivos.' },
        { label: 'Inspección termográfica + limpieza',
          text: 'Mantenimiento preventivo anual de {asset} '
                + '(transformador seco): inspección termográfica + '
                + 'limpieza de devanados + reapriete de conexiones. '
                + 'LOTO en breaker principal + PPE contra Arc Flash '
                + 'per CSA Z462-24 categoría según etiqueta del '
                + 'equipo. Vivo-Muerto-Vivo en primario y secundario '
                + 'antes de retirar paneles. Back-out: si se detecta '
                + 'agrietamiento o decoloración severa en bobinas, no '
                + 're-energizar — mantener LOTO y escalar a '
                + 'Engineering para evaluación de RUL.' },
        { label: 'Ajuste de taps',
          text: 'Cambio de taps mecánicos en {asset} para corregir '
                + 'voltaje secundario. LOTO + PPE Cat 3 per CSA Z462-24. '
                + 'Aplicar Vivo-Muerto-Vivo en bornes antes de '
                + 'manipular las derivaciones físicas. Back-out: si el '
                + 'tap nuevo no produce el voltaje esperado tras '
                + 're-energizar, restaurar la posición original antes '
                + 'de cargar la rama; documentar la discrepancia en '
                + 'el WO.' },
        { label: 'Líquidos dieléctricos (DGA)',
          text: 'Toma de muestras + análisis DGA (gases disueltos) + '
                + 'rigidez dieléctrica + filtrado del aceite en '
                + '{asset}. LOTO completo + PPE Cat 4 per CSA Z462-24 '
                + '(riesgo químico adicional). Vivo-Muerto-Vivo previo '
                + 'a abrir cualquier válvula de muestreo. Back-out: '
                + 'si el DGA reporta concentraciones de acetileno por '
                + 'encima del umbral IEEE C57.104, no re-energizar — '
                + 'mantener LOTO hasta dictamen del laboratorio.' },
    ],
    utility: [
        { label: 'Prueba ATS conmutación',
          text: 'Prueba de conmutación en vacío y con carga del ATS '
                + 'asociado a {asset}. LOTO no aplica (prueba en vivo); '
                + 'personal fuera del límite de aproximación '
                + 'restringida durante conmutación mecánica + PPE Cat 4 '
                + 'per CSA Z462-24. Combustible del generador ≥ 80%. '
                + 'Back-out: si el generador no asume carga en ≤ 15 s, '
                + 'forzar retorno mecánico/eléctrico a Utility para '
                + 'restaurar flujo hacia los UPS antes que la '
                + 'autonomía de baterías caiga al 50%.' },
        { label: 'PM switchgear principal',
          text: 'Mantenimiento integral de tablero principal (LV/MV '
                + 'switchgear) que alimenta {asset}: racking-out de '
                + 'interruptores + torqueo de barras + pruebas Megger. '
                + 'LOTO + PPE Cat 4 contra Arc Flash per CSA Z462-24. '
                + 'Vivo-Muerto-Vivo obligatorio antes de cualquier '
                + 'manipulación. Back-out: si la resistencia de '
                + 'aislamiento cae bajo umbral del fabricante, no '
                + 're-energizar el feeder — escalar a Engineering '
                + 'antes de restaurar carga.' },
        { label: 'Restauración de servicio',
          text: 'Transferencia de carga de vuelta a la red comercial '
                + 'desde el generador en {asset}. LOTO no aplica '
                + '(maniobra operacional); respetar límite de '
                + 'aproximación restringida + PPE Cat 4 per CSA Z462-24. '
                + 'Cronometrar la estabilidad de la red (V + Hz) '
                + 'durante el período de espera previo a la '
                + 'transferencia. Back-out: si la red exhibe '
                + 'inestabilidad sostenida (sag > 5% o drift > 0.5 Hz), '
                + 'mantener carga en generador hasta el próximo '
                + 'período de prueba.' },
        { label: 'Respuesta anomalías de red',
          text: 'Protocolo de actuación frente a degradación '
                + 'sostenida de utility (sags severos, armónicos, '
                + 'frecuencia inestable) afectando {asset}. '
                + 'Aislamiento preventivo de la instalación. LOTO no '
                + 'aplica (maniobra operacional); respetar límite de '
                + 'aproximación restringida + PPE Cat 4 per CSA Z462-24. '
                + 'Back-out: una vez la red se estabilice por al '
                + 'menos 30 min, iniciar restauración cumpliendo el '
                + 'MOP de transferencia ordinaria.' },
    ],
    pdu_sts: [
        { label: 'Transferencia STS / bypass',
          text: 'Transferencia de carga del STS asociado a {asset} '
                + 'desde fuente preferida a alterna (o bypass de '
                + 'mantenimiento). PRE-TRANSFER OBLIGATORIO: revisar '
                + 'historial de alarmas + verificar estado de la caja '
                + 'SCR + sincronización de fuentes. LOTO no aplica '
                + '(maniobra en vivo); respetar límite de aproximación '
                + 'restringida + PPE Cat 3 per CSA Z462-24. Back-out: '
                + 'si los SCR reportan alarma de temperatura durante '
                + 'la conmutación, forzar retorno a la fuente '
                + 'preferida antes de los 100 ms de transferencia.' },
        { label: 'PM termografía y control',
          text: 'Mantenimiento preventivo de PDU/STS {asset}: '
                + 'termografía bajo Arc Flash, revisión de lógica de '
                + 'control, calibración de displays, limpieza de '
                + 'filtros. LOTO en alimentación primaria + PPE Cat 3 '
                + 'per CSA Z462-24. Vivo-Muerto-Vivo en barras antes '
                + 'de retirar paneles. Revisar historial de alarmas + '
                + 'estado de la caja SCR previo al inicio. Back-out: '
                + 'si la termografía revela hot-spots > 60 °C sobre '
                + 'ambiente en conexiones, no re-energizar — '
                + 'reapretar + medir post-reapriete antes del cierre.' },
        { label: 'Reemplazo de breakers',
          text: 'Reemplazo de interruptor principal o sub-alimentador '
                + 'en PDU {asset}. LOTO obligatorio + PPE Cat 4 per '
                + 'CSA Z462-24 + Vivo-Muerto-Vivo en bornes pre y post '
                + 'cambio físico. Revisar historial de alarmas + '
                + 'estado de la caja SCR del STS aguas arriba. '
                + 'Back-out: si el breaker nuevo no opera dentro de '
                + 'la curva de coordinación del fabricante en prueba '
                + 'secundaria, no re-energizar la rama — escalar a '
                + 'Engineering.' },
    ],
    rpp: [
        { label: 'Balanceo de carga',
          text: 'Re-balanceo de fases A/B/C en RPP {asset} al '
                + 'instalar nuevos circuitos. LOTO en circuitos '
                + 'afectados + PPE Cat 2 per CSA Z462-24 + '
                + 'Vivo-Muerto-Vivo en breakers individuales. Ninguna '
                + 'fase debe exceder el 80% de su capacidad nominal. '
                + 'Revisar historial de alarmas del RPP previo. '
                + 'Back-out: si tras el cambio el desbalance > 10% se '
                + 'mantiene, restaurar el ruteo previo antes de '
                + 'cargar IT en los nuevos circuitos.' },
        { label: 'Instalación de látigos (whips)',
          text: 'Despliegue de cables de potencia (whips) bajo piso '
                + 'falso o bandejas aéreas alimentando {asset}. LOTO '
                + 'en breaker aguas arriba + PPE Cat 2 per CSA Z462-24. '
                + 'Vivo-Muerto-Vivo en conector previo al manguito. '
                + 'Respetar radios de curvatura + etiquetado normativo '
                + '(IEC 309 / NEMA). Back-out: si la prueba de '
                + 'continuidad falla, dejar el whip aislado y '
                + 'etiquetado; no energizar.' },
        { label: 'EPO (restablecimiento post-evento)',
          text: 'Protocolo post-EPO en RPP {asset} tras evento '
                + 'humo/fuego. LOTO completo en alimentación + PPE '
                + 'Cat 4 per CSA Z462-24. Inspección visual de daños '
                + 'térmicos en contactores + Vivo-Muerto-Vivo previo a '
                + 'reset. Revisar historial de alarmas para identificar '
                + 'la causa raíz. Back-out: si hay evidencia de daño '
                + 'estructural, no re-energizar — mantener LOTO hasta '
                + 'inspección de bomberos o fabricante.' },
    ],
    busway: [
        { label: 'Instalación / retiro de tap-off boxes',
          text: 'Instalación o retiro de tap-off boxes en el busway '
                + 'alimentando {asset}. OPERACIÓN EN VIVO de alto '
                + 'riesgo: LOTO NO aplica (busway energizado); '
                + 'respetar límite de aproximación restringida + PPE '
                + 'Cat 4 per CSA Z462-24 + postura corporal lateral '
                + 'al insertar. Back-out: si la caja no inserta '
                + 'mecánicamente con presión normal, retirar '
                + 'inmediatamente — no forzar — y etiquetar como '
                + 'pending vendor inspection.' },
        { label: 'Mantenimiento de juntas y tapas',
          text: 'Mantenimiento de juntas mecánicas del busway que '
                + 'alimenta {asset}: reapriete + medición de '
                + 'resistencia de contacto + limpieza. LOTO en breaker '
                + 'aguas arriba del sector + PPE Cat 3 per CSA Z462-24. '
                + 'Vivo-Muerto-Vivo en las juntas antes de abrir tapas. '
                + 'Back-out: si la resistencia de contacto '
                + 'post-reapriete excede el umbral del fabricante, no '
                + 're-energizar el sector — escalar a Engineering.' },
        { label: 'Escaneo termográfico operativo',
          text: 'Escaneo termográfico bajo carga del busway '
                + 'alimentando {asset}: identificar gradientes '
                + 'térmicos inusuales en puntos de contacto con '
                + 'tap-off boxes. LOTO no aplica (inspección no '
                + 'invasiva); respetar límite de aproximación '
                + 'restringida + PPE Cat 3 per CSA Z462-24. Back-out: '
                + 'si se detecta hot-spot > 30 °C sobre vecindario, '
                + 'reducir carga sobre esa tap-off box + abrir WO de '
                + 'inspección mecánica antes que el ΔT escale.' },
    ],
    chiller: [
        { label: 'Staging / rotación secuencial',
          text: 'Arranque del Chiller standby {asset} + bombas '
                + 'asociadas con ecualización previa de presiones '
                + 'para prevenir golpes de ariete. Mechanical LOTO en '
                + 'válvulas motorizadas + Motor LOTO eléctrico + PPE '
                + 'Cat 3 per CSA Z462-24 + Vivo-Muerto-Vivo en motor '
                + 'disconnect del compresor a desactivar. Back-out: '
                + 'si T_suministro > 12 °C por más de 45 s o '
                + 'vibración anómala en válvulas, restaurar Chiller '
                + 'primario antes del Tiempo de Tolerancia Térmica '
                + '(~5 min ASHRAE A2 breach).' },
        { label: 'Trip response (emergencia)',
          text: 'Conmutación de emergencia a bypass + Chiller de '
                + 'respaldo tras trip del compresor en {asset}. '
                + 'Restauración debe completarse en < 90 s vs ~2 min '
                + 'Tiempo de Tolerancia Térmica crítica. LOTO '
                + 'mecánico + eléctrico aplicados post-trip + '
                + 'Vivo-Muerto-Vivo en motor disconnect del compresor '
                + 'fallido + PPE Cat 3 per CSA Z462-24. Back-out: si '
                + 'respaldo no asume en 90 s, escalar a IT Load '
                + 'Shedding (EOP separado).' },
        { label: 'Ride-through recovery',
          text: 'Reinicio escalonado de compresores del Chiller '
                + '{asset} post-transición a generador. Monitorear '
                + 'Lift (relación de presiones, P_cond/P_evap) ≤ 1.5x '
                + 'baseline y rampa de carga del generador. Motor '
                + 'LOTO eléctrico disponible para abort + PPE Cat 3 '
                + 'per CSA Z462-24 + Vivo-Muerto-Vivo si se aplica '
                + 'LOTO. Back-out: si Lift excede umbral, abortar '
                + 'arranque del compresor afectado y continuar con '
                + 'los demás (operación con menor N).' },
    ],
    crah: [
        { label: 'Reemplazo de filtros en caliente',
          text: 'Reemplazo de bancos de filtros de la CRAH {asset} '
                + 'sin apagar ventiladores; monitoreo de dP para no '
                + 'perder presión estática del piso falso. Mechanical '
                + 'LOTO en latch del banco + Motor LOTO eléctrico '
                + 'disponible para abort + PPE Cat 1 per CSA Z462-24. '
                + 'Durante el reemplazo, respetar límite de '
                + 'aproximación restringida al gabinete del VFD. '
                + 'Back-out: si T_inlet rack > 27 °C (ASHRAE A1) por '
                + '> 60 s o presión estática del piso cae > 15%, '
                + 'reinstalar filtros viejos temporalmente.' },
        { label: 'Calibración VFD + válvulas',
          text: 'Calibración dinámica de VFD + válvulas modulantes '
                + 'de la CRAH {asset} (Leyes de Afinidad P~N³: -10% '
                + 'RPM = -27% consumo). Motor LOTO eléctrico + '
                + 'Vivo-Muerto-Vivo en bornes del VFD si se abre '
                + 'panel + Mechanical LOTO en válvula si se '
                + 'interviene físicamente + PPE Cat 2 per CSA Z462-24. '
                + 'Back-out: walk-back automático del VFD a baseline '
                + 'si T_inlet > 27 °C o oscilación de la válvula '
                + '(hunting) por > 2 min.' },
        { label: 'Control psicrométrico (anti-condensación)',
          text: 'Ajuste de setpoints de la CRAH {asset} ante alta '
                + 'humedad relativa; mantener T_serpentin ≥ '
                + 'T_punto_de_rocio + 1.5 °C para prevenir '
                + 'condensación. PPE Cat 1 + CSA Z462-24 + Motor '
                + 'LOTO eléctrico si se abre VFD (Vivo-Muerto-Vivo en '
                + 'bornes) + Mechanical LOTO si se ajusta válvula '
                + 'modulante. Back-out: si HR > 55% por > 15 min o '
                + 'condensación visible, revertir setpoint y escalar '
                + 'a Engineering para evaluar carga latente externa.' },
    ],
    tower: [
        { label: 'Dosificación química + Legionella',
          text: 'Dosificación dinámica de biocidas (oxidantes / no '
                + 'oxidantes) y anti-incrustantes en la torre '
                + '{asset} según LSI (banda objetivo 0.2-0.5) y CoC. '
                + 'PPE químico completo + Motor LOTO eléctrico en '
                + 'bombas dosificadoras + Vivo-Muerto-Vivo en bornes '
                + '+ Mechanical LOTO en válvulas si se intervienen + '
                + 'PPE Cat 2 per CSA Z462-24. Muestra microbiológica '
                + 'a laboratorio certificado (ASHRAE 188 + CTI '
                + 'ATC-105). Back-out: si Legionella ≥ 100 CFU/mL, '
                + 'dosificación de choque + notificación regulatoria.' },
        { label: 'Limpieza de piletas (celda aislada)',
          text: 'Aislamiento hidráulico de una celda de la torre '
                + '{asset} para limpieza de piletas + rociadores; '
                + 'celdas remanentes a máxima velocidad sostienen '
                + 'Q_rej (Tiempo de Tolerancia Térmica ~6 min). '
                + 'Mechanical LOTO en válvulas de la celda + Motor '
                + 'LOTO eléctrico en ventilador + Vivo-Muerto-Vivo + '
                + 'PPE biológico + Cat 2 per CSA Z462-24. Back-out: '
                + 'si T_retorno sube > 3 °C sobre baseline, '
                + 're-conectar la celda inmediatamente.' },
        { label: 'Transición a Free Cooling',
          text: 'Transición de la torre {asset} a modo Free Cooling '
                + '(water-side economizer); apagado de compresores + '
                + 'redirección al intercambiador de placas cuando '
                + 'T_wb ≤ T_suministro - 5 °C. Motor LOTO eléctrico '
                + 'en compresores apagados + Vivo-Muerto-Vivo + '
                + 'Mechanical LOTO en válvulas de bypass + PPE Cat 3 '
                + 'per CSA Z462-24. Back-out: si T_suministro excede '
                + 'setpoint + 2 °C o T_wb se degrada, revertir a '
                + 'modo Chiller en < 60 s (Tiempo de Tolerancia '
                + 'Térmica ~5 min).' },
    ],
    global: [
        { label: 'IST (Integrated System Testing) plena carga',
          text: 'Prueba de Sistemas Integrados a plena carga del '
                + 'sitio completo (bancos de carga al 100% sobre '
                + '{asset} y su path). Simulación controlada de '
                + 'pérdida de utility; valida generadores + UPS + '
                + 'Chillers + envolvente ASHRAE. Mechanical LOTO + '
                + 'Motor LOTO eléctrico disponibles para abort + '
                + 'Vivo-Muerto-Vivo + PPE Cat 4 per CSA Z462-24 + '
                + 'CIO + Safety Officer en sala de control. '
                + 'Back-out: si generadores no arrancan en 15 s o '
                + 'T_inlet excede 30 °C, restaurar utility + escalar.' },
        { label: 'Aislamiento de anillo (Double Block and Bleed)',
          text: 'Aislamiento de tramo del anillo principal de agua '
                + 'helada que alimenta {asset} usando configuración '
                + 'Double Block and Bleed (Uptime Tier IV / '
                + 'Mantenibilidad Concurrente). Mechanical LOTO en '
                + 'ambas válvulas DBB + purga intermedia + Motor '
                + 'LOTO eléctrico en bombas asociadas + '
                + 'Vivo-Muerto-Vivo + PPE Cat 3 per CSA Z462-24. '
                + 'Back-out: si T_suministro CRAHs sube > setpoint + '
                + '2 °C o purga intermedia no detiene flujo (DBB no '
                + 'sella), restaurar tramo en < 5 min.' },
    ],
    life_safety: [
        { label: 'VESDA zone functional test',
          text: 'Prueba funcional anual de la zona VESDA {asset}: '
                + 'panel en Maintenance Mode + solenoides Novec '
                + 'aislados + LOTO eléctrico en bornes del solenoide + '
                + 'Vivo-Muerto-Vivo + PPE Cat 1 per CSA Z462-24. '
                + 'Generar humo de prueba en el punto de muestreo más '
                + 'lejano + cronometrar hasta Fire 2. Back-out: si '
                + 'sensitivity drift > 25% del baseline por > 60 s o '
                + 'time-to-Fire2 > 180 s, abortar y escalar a '
                + 'fabricante.' },
        { label: 'Cylinder pressure annual (Novec / FM-200)',
          text: 'Verificación anual de presión del cilindro de clean '
                + 'agent {asset}: panel en Maintenance Mode + LOTO '
                + 'eléctrico en solenoide + LOTO mecánico en válvula '
                + 'manual (cadena + candado) + Vivo-Muerto-Vivo + '
                + 'bonding cable + PPE químico + PPE Cat 2 per CSA '
                + 'Z462-24. Manómetro dual + balanza cross-check vs '
                + 'stencil. Back-out: si presión < 85% nominal o masa '
                + 'difiere > 10% del stencil, cilindro PENDING '
                + 'RECHARGE; no re-armar la zona.' },
        { label: 'Clean agent discharge reset (post-event)',
          text: 'Recovery post-discharge del sistema clean agent en '
                + 'la zona afectada por {asset}: bomberos clearance '
                + '+ análisis multi-gas + LOTO completo + PPE Cat 4 + '
                + 'SCBA + Vivo-Muerto-Vivo + Lockout/Tagout en panel '
                + 'de supresión per CSA Z462-24. Cilindro nuevo + '
                + 'self-test + 30 min monitoreo re-armado. Back-out: '
                + 'si daño estructural visible o panel reporta '
                + 'trouble dentro de los 30 min, mantener fire watch '
                + 'humano 24/7 hasta dictamen estructural.' },
    ],
    combustible: [
        { label: 'Day tank bulk fuel transfer',
          text: 'Reabastecimiento del day tank {asset} desde bulk '
                + 'tank: bonding cable < 1 Ω + spill containment + '
                + 'PPE químico + LOTO mecánico en válvula de bulk + '
                + 'LOTO eléctrico en motor de bomba + Vivo-Muerto-Vivo '
                + 'en bornes + PPE Cat 2 per CSA Z462-24. Stop al 95% '
                + 'target para overshoot prevention. Back-out: si '
                + 'nivel > 98% sin parar bomba, E-stop físico + '
                + 'cerrar válvulas manuales; si derrame > 1 galón, '
                + 'protocolo HAZMAT + notificación ambiental en < 2 h.' },
        { label: 'Fuel polishing (water removal ASTM D6304)',
          text: 'Polishing en circuit cerrado del day tank {asset}: '
                + 'sample S1 pre-polishing + Karl Fischer + LOTO '
                + 'mecánico en day-to-engine valve + LOTO eléctrico '
                + 'en bomba del skid + Vivo-Muerto-Vivo + bonding '
                + 'cable + PPE químico + respirador orgánico + PPE '
                + 'Cat 2 per CSA Z462-24. Bottom sediment drain a '
                + 'HAZMAT. Back-out: si water-cut sample S2 > 500 '
                + 'ppm tras 2 ciclos, escalar a tank cleaning (full '
                + 'drain + manual cleaning per ANSI/AIHA Z9.5).' },
        { label: 'Generator extended runtime (> 12 h)',
          text: 'Operación coordinada del generador {asset} bajo '
                + 'load IT del sitio durante outage extendido (NFPA '
                + '110 §A.5.6.4). Monitoreo continuo de winding '
                + 'temp (< 110 °C), oil pressure, fuel consumption + '
                + 'samples ASTM cada 24 h. LOTO mecánico/eléctrico '
                + 'disponible para abort + Vivo-Muerto-Vivo capacity '
                + 'confirmed + PPE Cat 3 per CSA Z462-24. Back-out: '
                + 'si winding > 110 °C por > 30 s, reducir IT load '
                + '25%; si oil pressure < 80% nominal por > 60 s, '
                + 'shutdown controlado + transfer a N+1 o utility.' },
    ],
};

const MOP_CATEGORY_KEYS = [
    'ups', 'transformer', 'utility',
    'pdu_sts', 'rpp', 'busway',
    'chiller', 'crah', 'tower', 'global',
    'life_safety', 'combustible',
];
const MOP_CATEGORY_LABELS = {
    ups:         'UPS',
    transformer: 'Transformer',
    utility:     'Utility / Switchgear / ATS',
    pdu_sts:     'PDU / STS',
    rpp:         'RPP',
    busway:      'Busway',
    chiller:     'Chiller',
    crah:        'CRAH',
    tower:       'Cooling Tower',
    global:      'Global / IST / Ring',
    life_safety: 'Life Safety (VESDA / Clean Agent)',
    combustible: 'Combustible (Day Tank / Generator)',
};
const MOP_CATEGORY_DEFAULT = 'ups';

// CONTEXT_TEMPLATES retained for SOP / EOP / EMP. The MOP entry is a
// FLATTENED union of every MOP_CATEGORIES bucket -- backward-compat
// with callers/tests that iterate the full set.
const CONTEXT_TEMPLATES = {
    SOP: [
        { label: 'Daily round',
          text: 'Daily round of {asset}. Verify BMS setpoints, '
                + 'inspect for alarms, log the reading.' },
        { label: 'Weekly preventive',
          text: 'Weekly preventive inspection of {asset}. Check '
                + 'physical condition, BMS trend, no off-nominal '
                + 'parameters in the EPMS.' },
        { label: 'Monthly PM',
          text: 'Monthly preventive maintenance of {asset}. Walk '
                + 'the unit, verify HMI states match physical state, '
                + 'record the closure.' },
        { label: 'Shift handover',
          text: 'Shift handover round including {asset}. Confirm '
                + 'BMS values, open incidents, pending MOPs are '
                + 'communicated to the incoming CET.' },
    ],
    MOP: MOP_CATEGORY_KEYS.flatMap((k) => MOP_CATEGORIES[k]),
    EOP: [
        { label: 'Loss of redundancy',
          text: 'Loss of redundancy event on {asset}. Confirm the '
                + 'alarm, isolate the affected component, escalate per '
                + 'the redundancy-violation matrix. Contain before '
                + 'further degradation.' },
        { label: 'Thermal event',
          text: 'Thermal event on {asset}. Containment: open the '
                + 'rack door, reduce IT load, escalate to mechanical '
                + 'lead. Isolate the affected cooling chain.' },
        { label: 'Electrical fault',
          text: 'Electrical fault detected on {asset}. Contention: '
                + 'isolate the affected bus, transfer load to the '
                + 'redundant path, halt any in-flight maintenance.' },
        { label: 'BMS comms loss',
          text: 'BMS comms loss to {asset}. Containment: fall back to '
                + 'local control panel, isolate the BMS write path, '
                + 'escalate to the controls vendor on-call.' },
    ],
    EMP: [
        { label: 'Site-wide power loss',
          text: 'Site-wide loss-of-utility event. Activate the '
                + 'incident command bridge; coordinate logistics, '
                + 'on-site escort, customer communications, vendor '
                + 'dispatch.' },
        { label: 'Multi-site coordination',
          text: 'Multi-site incident coordination. Designate the '
                + 'incident commander on each side; align customer '
                + 'communications and escalation paths.' },
        { label: 'Vendor escalation',
          text: 'Vendor escalation playbook. Define incident command '
                + 'authority, dispatch path for field engineers, '
                + 'access escort, stakeholder communication template.' },
    ],
};

let _routeRegistered = false;
let _viewWired = false;
let _currentDraft = null;   // last {draft, safety_audit} response

// Commit 4 -- which MOP category the chip row is showing right now.
// Only relevant when doc_type=MOP; SOP/EOP/EMP ignore this.
let _currentMopCategory = MOP_CATEGORY_DEFAULT;

// Epic 6 Sprint 3 Phase 2 — stale-verdict invalidation.
// Snapshot of the context the operator submitted to /generate. When
// the textarea diverges from this snapshot we mark the result card
// as stale, hide the Sign button, and surface a "Re-generate
// required" banner. Prevents the safety-critical class of bug where
// an operator edits the textarea after seeing APPROVE and then
// clicks Sign on a draft that doesn't match the current text.
let _lastGeneratedContext = null;
let _staleHandlerInstalled = false;


// ─── Form helpers — asset picker + context auto-fill ────────────────
/** Build the asset-id <select>'s inner markup. Includes a "(none)"
 *  option, the curated optgroups, and the trailing "Custom…" option
 *  that reveals the manual text input below. Every label + id flows
 *  through escapeHTML — defensive even though the source is a static
 *  module-level constant. */
function _renderAssetSelect() {
    const none = `<option value="${ASSET_NONE_VALUE}">`
        + '(none — site-wide procedure)</option>';
    const groups = ASSET_PRESETS.map((g) => {
        const opts = g.items.map(
            (it) => `<option value="${escapeHTML(it.id)}">`
                + `${escapeHTML(it.label)}</option>`,
        ).join('');
        return `<optgroup label="${escapeHTML(g.group)}">${opts}</optgroup>`;
    }).join('');
    const custom = `<option value="${ASSET_CUSTOM_VALUE}">`
        + '(Custom — type below)</option>';
    return none + groups + custom;
}

/** Resolve the effective asset id from the form (preset choice OR the
 *  custom text input when the picker is set to Custom). Returns "" for
 *  site-wide / unspecified. Trimmed; never returns the sentinel. */
function _resolveAssetId(root) {
    const sel = root.querySelector('[data-proc-asset-select]')?.value || '';
    if (sel === ASSET_CUSTOM_VALUE) {
        return (
            root.querySelector('[data-proc-asset-custom]')?.value?.trim() || ''
        );
    }
    return sel === ASSET_NONE_VALUE ? '' : sel;
}

/** Show / hide the Custom text input based on the picker selection.
 *  Hidden by default; revealed only when the operator picks the
 *  sentinel "(Custom)" option. */
function _syncCustomAssetVisibility(root) {
    const sel = root.querySelector('[data-proc-asset-select]')?.value || '';
    const wrap = root.querySelector('[data-proc-asset-custom-wrap]');
    if (!wrap) return;
    wrap.hidden = sel !== ASSET_CUSTOM_VALUE;
}

/** Re-render the context quick-pick chip row for the currently
 *  selected doc_type. Each chip is a <button data-action="ctx-fill"
 *  data-ctx-text="..."> — the click dispatcher routes it to
 *  _applyContextTemplate. */
function _renderContextChips(root) {
    const slot = root.querySelector('[data-proc-ctx-chips]');
    if (!slot) return;
    const docType = root.querySelector('[data-proc-doc-type]')?.value || 'SOP';

    // Commit 4 -- when authoring a MOP, the chip row is filtered by
    // _currentMopCategory (UPS / Transformer / Utility / PDU-STS /
    // RPP / Busway). SOP/EOP/EMP keep the legacy flat list.
    let templates;
    if (docType === 'MOP') {
        templates = MOP_CATEGORIES[_currentMopCategory] || MOP_CATEGORIES[MOP_CATEGORY_DEFAULT];
    } else {
        templates = CONTEXT_TEMPLATES[docType] || [];
    }
    if (!templates || templates.length === 0) {
        slot.innerHTML = '';
        return;
    }
    const chips = templates.map((t) => (
        '<button type="button" class="proc-chip" '
        + 'data-action="ctx-fill" '
        + `data-ctx-text="${escapeHTML(t.text)}">`
        + escapeHTML(t.label)
        + '</button>'
    )).join('');
    const hint = docType === 'MOP'
        ? `MOP starter (${escapeHTML(MOP_CATEGORY_LABELS[_currentMopCategory] || _currentMopCategory)}) — click to pre-fill:`
        : 'Quick context — click a template to pre-fill:';
    slot.innerHTML = `<span class="proc-chips-hint">${hint}</span> ${chips}`;
}

/** Show/hide the MOP-category select based on the current doc_type.
 *  Only visible for MOP; hidden for SOP/EOP/EMP. */
function _syncMopCategoryVisibility(root) {
    const docType = root.querySelector('[data-proc-doc-type]')?.value || 'SOP';
    const wrap = root.querySelector('[data-proc-mop-category-wrap]');
    if (!wrap) return;
    wrap.hidden = (docType !== 'MOP');
}

/** Apply a clicked chip's template to the textarea, substituting
 *  ``{asset}`` with the currently selected asset_id (or a neutral
 *  placeholder when none). Replaces existing textarea content —
 *  intentional, the operator can re-edit. */
function _applyContextTemplate(root, templateText) {
    const ta = root.querySelector('[data-proc-context]');
    if (!ta) return;
    const asset = _resolveAssetId(root);
    const replaced = String(templateText || '').replace(
        /\{asset\}/g,
        asset || 'the affected asset',
    );
    ta.value = replaced;
    // Visual feedback: focus the textarea so the operator sees the cursor.
    ta.focus();
}


// ─── Markdown -> safe HTML (deliberately minimal) ────────────────────
/**
 * Render a small, safe subset of markdown:
 *   - `# H1`, `## H2`, `### H3` headers
 *   - `**bold**` and `*italic*` emphasis
 *   - `` `code` `` inline code
 *   - `- item` unordered list
 *   - `1. item` ordered list (rendered as <li> inside <ol>)
 *   - paragraphs separated by blank lines
 *
 * The input is FIRST escapeHTML'd. The pattern substitutions then
 * operate on already-escaped text — so any HTML/JS the LLM emits is
 * neutered before any markup is generated. This is intentional: a
 * full markdown library would let `<` re-emerge via auto-linking or
 * raw-HTML support and reintroduce XSS.
 */
function _renderMarkdown(md) {
    if (typeof md !== 'string' || md.length === 0) return '';
    let html = escapeHTML(md);

    // Code fences (```...```) — preserve their content verbatim,
    // wrap in <pre><code>. Process FIRST so the content inside
    // doesn't get re-mangled by header / emphasis passes below.
    html = html.replace(
        /```([\s\S]*?)```/g,
        (_m, code) => `<pre class="proc-codeblock"><code>${code}</code></pre>`,
    );

    // Headers — anchored at line start.
    html = html.replace(/^### (.+)$/gm, '<h3 class="proc-h3">$1</h3>');
    html = html.replace(/^## (.+)$/gm, '<h2 class="proc-h2">$1</h2>');
    html = html.replace(/^# (.+)$/gm, '<h1 class="proc-h1">$1</h1>');

    // Inline code (after headers so backticks in headers stay literal).
    html = html.replace(
        /`([^`\n]+)`/g, '<code class="proc-code">$1</code>',
    );

    // Bold / italic — bold first so **x** doesn't match as italic *x*.
    html = html.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*([^*\n]+)\*/g, '<em>$1</em>');

    // Lists — line-by-line grouping pass.
    const lines = html.split('\n');
    const out = [];
    let inUl = false;
    let inOl = false;
    const closeLists = () => {
        if (inUl) { out.push('</ul>'); inUl = false; }
        if (inOl) { out.push('</ol>'); inOl = false; }
    };
    for (const ln of lines) {
        const ulMatch = ln.match(/^- (.+)$/);
        const olMatch = ln.match(/^\d+\. (.+)$/);
        if (ulMatch) {
            if (inOl) { out.push('</ol>'); inOl = false; }
            if (!inUl) { out.push('<ul class="proc-list">'); inUl = true; }
            out.push(`<li>${ulMatch[1]}</li>`);
        } else if (olMatch) {
            if (inUl) { out.push('</ul>'); inUl = false; }
            if (!inOl) { out.push('<ol class="proc-list">'); inOl = true; }
            out.push(`<li>${olMatch[1]}</li>`);
        } else {
            closeLists();
            out.push(ln);
        }
    }
    closeLists();

    // Paragraph wrapping for runs of plain text between block elements.
    // Cheap heuristic: split on blank lines, wrap chunks that aren't
    // already block-level (h*, ul/ol, pre).
    return out.join('\n')
        .split(/\n\s*\n/)
        .map((chunk) => {
            const t = chunk.trim();
            if (!t) return '';
            if (/^<(h\d|ul|ol|pre|li)/.test(t)) return t;
            return `<p class="proc-p">${t.replace(/\n/g, '<br>')}</p>`;
        })
        .join('\n');
}


// ─── Safety verdict pill ─────────────────────────────────────────────
function _verdictPill(verdict) {
    const v = String(verdict || 'unknown').toLowerCase();
    const cls = v === VERDICT_APPROVE
        ? 'proc-pill-approve'
        : v === VERDICT_CAUTION
            ? 'proc-pill-caution'
            : v === VERDICT_HARD_STOP
                ? 'proc-pill-veto'
                : 'proc-pill-unknown';
    const label = v === VERDICT_HARD_STOP ? 'SAFETY HARD_STOP' : v.toUpperCase();
    return `<span class="proc-pill ${escapeHTML(cls)}">`
        + `${escapeHTML(label)}</span>`;
}


// ─── Pre-pull telemetry (Epic 6 Sprint 3 Phase 3) ───────────────────
// Whitelist of telemetry keys that get packed into the Architect
// metadata block. Keep the set narrow on purpose -- the LLM author
// only benefits from grounding signals (load + thermal + PUE +
// scenario), not every column of the telemetry table. A larger set
// dilutes the prompt + costs tokens for no quality gain.
const _TELEMETRY_METADATA_KEYS = [
    'pue',
    'it_load_kw',
    'hall_temp_c',
    'delta_t_c',
    'scenario',
];

/** Fetch /api/telemetry/latest and reduce to the curated metadata
 *  whitelist. Returns ``{}`` on any failure (network down, endpoint
 *  503, payload missing the ``latest`` field) so the Generate flow
 *  never aborts on a telemetry hiccup -- the request still goes out,
 *  just without the LIVE OPERATING METADATA block. */
async function _fetchTelemetrySnapshot() {
    try {
        const resp = await fetch('/api/telemetry/latest');
        if (!resp.ok) return {};
        const data = await resp.json();
        const latest = data && data.latest;
        if (!latest || typeof latest !== 'object') return {};
        const out = {};
        for (const k of _TELEMETRY_METADATA_KEYS) {
            if (latest[k] !== undefined && latest[k] !== null) {
                out[k] = latest[k];
            }
        }
        // Tag the snapshot timestamp so the ledger entry can audit
        // which moment-in-time informed the document.
        if (typeof data.ts === 'number') out.snapshot_ts = data.ts;
        return out;
    } catch (_) {
        return {};
    }
}


// ─── Stale-verdict invalidation (Epic 6 Sprint 3 Phase 2) ──────────
/** True when the operator has edited the textarea AFTER the most
 *  recent successful generate. The Sign button must be hidden and
 *  the result card visually marked stale in that case. */
function _isStaleVsLastGenerate(root) {
    if (_lastGeneratedContext === null) return false;
    const ta = root.querySelector('[data-proc-context]');
    if (!ta) return false;
    return ta.value !== _lastGeneratedContext;
}

/** Mark the current result card as stale -- replaces the approve
 *  card UI with a "re-generate required" banner. Idempotent: calling
 *  twice in a row is a no-op (the marker is the dataset attr). */
function _markResultStale(root) {
    const slot = root.querySelector('[data-proc-result]');
    if (!slot) return;
    if (slot.dataset.stale === '1') return;
    slot.dataset.stale = '1';
    // Hide any Sign button that's still in the DOM (defence in depth
    // -- the next render will also drop it, but if the operator races
    // a click between input + re-render, this catches it).
    slot.querySelectorAll('.proc-btn-sign').forEach((b) => {
        b.disabled = true;
        b.hidden = true;
    });
    // Surface the stale banner above whatever's still rendered.
    if (!slot.querySelector('.proc-banner-stale')) {
        const banner = document.createElement('div');
        banner.className = 'proc-banner-stale';
        banner.textContent = (
            'The context has been edited since this draft was generated. '
            + 'The Safety Officer verdict above is STALE and the Sign '
            + 'button is disabled. Click Generate again to re-evaluate.'
        );
        slot.insertBefore(banner, slot.firstChild);
    }
}

/** Wire the textarea ``input`` listener once -- subsequent calls are
 *  no-ops. Each input event compares current text vs the snapshot
 *  taken at the last successful generate and marks the card stale
 *  when they diverge. */
function _installStaleHandler(root) {
    if (_staleHandlerInstalled) return;
    const ta = root.querySelector('[data-proc-context]');
    if (!ta) return;
    ta.addEventListener('input', () => {
        if (_isStaleVsLastGenerate(root)) _markResultStale(root);
    });
    _staleHandlerInstalled = true;
}


// ─── Result render ───────────────────────────────────────────────────
function _renderResult(payload) {
    const root = $('view-procedures-architect');
    if (!root) return;
    const slot = root.querySelector('[data-proc-result]');
    if (!slot) return;

    if (!payload || typeof payload !== 'object') {
        slot.innerHTML = sanitizeHTML(
            '<div class="proc-empty">No response yet.</div>',
        );
        return;
    }
    const draft = payload.draft || {};
    const audit = payload.safety_audit || {};
    const verdict = String(audit.verdict || 'unknown').toLowerCase();
    const findings = Array.isArray(audit.findings) ? audit.findings : [];
    const isApproved = verdict === VERDICT_APPROVE;
    const isHardStop = verdict === VERDICT_HARD_STOP;

    const findingsHtml = findings.length
        ? `<ul class="proc-findings">${
            findings.map((f) => `<li>${escapeHTML(String(f))}</li>`).join('')
          }</ul>`
        : '';

    // Markdown content is already escapeHTML'd inside _renderMarkdown
    // then markup-substituted by a deliberately-minimal pattern pass.
    // No raw HTML can leak through, so the result drops straight into
    // innerHTML — no sanitizeHTML wrap (which would strip the Sign
    // <button> below, by design — sanitize.js neuters interactive
    // elements). Same pattern as views/optimizer.js's proposal card.
    const contentHtml = _renderMarkdown(draft.content || '');

    const idEsc = escapeHTML(draft.draft_id || '');
    const docTypeEsc = escapeHTML(draft.doc_type || '?');
    const llmBadge = draft.llm_present
        ? '<span class="proc-badge proc-badge-llm">LLM-authored</span>'
        : '<span class="proc-badge proc-badge-skeleton">deterministic skeleton</span>';
    const signBtn = isApproved
        ? `<button class="proc-btn proc-btn-sign" data-action="sign"
                   data-draft-id="${idEsc}">Sign &amp; Save to Ledger</button>`
        : '';
    const hardStopBanner = isHardStop
        ? '<div class="proc-banner-hardstop">'
            + 'Safety Officer refused this draft. '
            + 'Re-prompt the Architect with the missing terms (see below) '
            + 'and try again. The Sign button is disabled.'
            + '</div>'
        : '';

    slot.innerHTML = `
        <div class="proc-card">
            <div class="proc-card-hdr">
                <span class="proc-doc-type">${docTypeEsc}</span>
                <span class="proc-draft-id">${escapeHTML(String(draft.draft_id || '').slice(0, 8))}</span>
                ${llmBadge}
                ${_verdictPill(verdict)}
            </div>
            ${hardStopBanner}
            ${findings.length ? `
                <div class="proc-audit">
                    <strong>Safety Officer audit findings:</strong>
                    ${findingsHtml}
                </div>` : ''}
            <div class="proc-content">${contentHtml}</div>
            <div class="proc-actions">${signBtn}</div>
            <div class="proc-sign-result"
                 data-draft-id="${idEsc}"></div>
        </div>
    `;
    // Clear any prior stale marker — a fresh render is by definition
    // not stale until the operator next edits the textarea.
    slot.dataset.stale = '';

    _currentDraft = payload;
}


// ─── Fetch — generate ────────────────────────────────────────────────
async function _submitGenerate() {
    const root = $('view-procedures-architect');
    if (!root) return;
    // Belt-and-suspenders — install the stale-detection listener on
    // every generate in case the view was mounted by a test path
    // that bypassed _wireProceduresView.
    _installStaleHandler(root);
    const docType = root.querySelector('[data-proc-doc-type]')?.value || '';
    const ctx = root.querySelector('[data-proc-context]')?.value?.trim() || '';
    const assetId = _resolveAssetId(root);
    const slot = root.querySelector('[data-proc-result]');

    if (!DOC_TYPES.includes(docType)) {
        slot.innerHTML = sanitizeHTML(
            '<div class="proc-empty proc-error">Pick a valid doc type.</div>',
        );
        return;
    }
    if (ctx.length < 10) {
        slot.innerHTML = sanitizeHTML(
            '<div class="proc-empty proc-error">Context must be at least 10 characters.</div>',
        );
        return;
    }

    slot.innerHTML = sanitizeHTML(
        '<div class="proc-empty">Pulling telemetry snapshot…</div>',
    );
    // Phase 3: pre-pull a curated telemetry snapshot so the Architect
    // grounds the document in current state. Failures here are
    // tolerated -- the Generate request still goes out without the
    // metadata block.
    const metadata = await _fetchTelemetrySnapshot();
    slot.innerHTML = sanitizeHTML(
        '<div class="proc-empty">Generating…</div>',
    );
    try {
        const resp = await fetch('/api/procedures/architect/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                doc_type: docType,
                context: ctx,
                asset_id: assetId || null,
                metadata: Object.keys(metadata).length > 0 ? metadata : null,
            }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
            slot.innerHTML = sanitizeHTML(
                `<div class="proc-empty proc-error">HTTP ${resp.status}: `
                + `${escapeHTML(data.detail || resp.statusText)}</div>`,
            );
            return;
        }
        // Snapshot the context that produced this result so the
        // stale-detection listener can compare against subsequent edits.
        _lastGeneratedContext = ctx;
        _renderResult(data);
    } catch (e) {
        slot.innerHTML = sanitizeHTML(
            `<div class="proc-empty proc-error">Network error: `
            + `${escapeHTML(e.message)}</div>`,
        );
    }
}


// ─── Fetch — sign ────────────────────────────────────────────────────
async function _submitSign(draftId) {
    const root = $('view-procedures-architect');
    if (!root || !_currentDraft) return;
    const draft = _currentDraft.draft || {};
    if (draft.draft_id !== draftId) return;   // staleness guard (race)

    const slot = root.querySelector(
        `.proc-sign-result[data-draft-id="${CSS.escape(draftId)}"]`,
    );
    if (!slot) return;
    // Epic 10 Batch 4 -- QKD gate. When the BB84 simulator surfaces
    // an above-threshold QBER (last_qber >= 11%), the global signing
    // gate is CLOSED and the Sign action refuses before it even
    // touches the network. The server re-checks via its own
    // mechanisms; this client gate is the explicit "Enlace
    // Interceptado" UX banner the operator was promised.
    if (!isSigningEnabled()) {
        const gate = getQkdGateState();
        const qberPct = (gate.qber !== null && gate.qber !== undefined)
            ? (gate.qber * 100).toFixed(2) + '%' : 'unknown';
        slot.innerHTML = sanitizeHTML(
            '<div class="proc-sign-fail">Firma Deshabilitada: Enlace '
            + 'Interceptado (QBER ' + escapeHTML(qberPct)
            + ' >= 11.0%). El pool QKD debe recuperarse antes de '
            + 'firmar este draft.</div>',
        );
        return;
    }

    // Phase 2 staleness gate: refuse to sign when the textarea has
    // drifted since the last generate. The server re-audits on /sign
    // and would also refuse a hard_stop, but this client-side block
    // is the safety-critical UX layer — the operator never even sees
    // a "sign in flight" spinner on stale content.
    if (_isStaleVsLastGenerate(root)) {
        slot.innerHTML = sanitizeHTML(
            '<div class="proc-sign-fail">Refusing to sign — context '
            + 'has been edited since this draft was generated. Click '
            + 'Generate again to re-evaluate.</div>',
        );
        return;
    }
    slot.innerHTML = sanitizeHTML(
        '<div class="proc-empty">Signing…</div>',
    );
    // Read the operator_id from the input the form exposes. Default
    // to 'wilmer.angel' when the input is missing (test paths that
    // mount a partial skeleton) so existing behaviour is back-compat.
    const opInput = root.querySelector('[data-proc-operator-id]');
    const operatorId = (opInput?.value || 'wilmer.angel').trim() || 'wilmer.angel';
    try {
        const resp = await fetch('/api/procedures/architect/sign', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                draft_id: draft.draft_id,
                doc_type: draft.doc_type,
                content: draft.content,
                asset_id: draft.asset_id || null,
                operator_id: operatorId,
                actor_role: 'SME_L6',
            }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
            slot.innerHTML = sanitizeHTML(
                `<div class="proc-sign-fail">HTTP ${resp.status}: `
                + `${escapeHTML(data.detail || resp.statusText)}</div>`,
            );
            return;
        }
        // Epic 6 Sprint 3 Phase 4 wire-level: the MOP Maker-Checker
        // backend returns HTTP 202 + ``status: awaiting_second_signature``
        // on the first MOP sign. Render an unmistakable badge + the
        // maker's name + the content sha so the next operator (the
        // checker) has the proof-of-context they need to corroborate.
        if (data.status === 'awaiting_second_signature') {
            const maker = escapeHTML(String(data.first_signer || 'unknown'));
            const makerRole = escapeHTML(
                String(data.first_signer_role || 'operator'),
            );
            const sha = escapeHTML(
                String(data.content_sha256 || '').slice(0, 16),
            );
            slot.innerHTML = sanitizeHTML(
                '<div class="proc-sign-awaiting">'
                + '<span class="proc-sign-awaiting-badge">'
                + 'AWAITING SECOND SIGNATURE</span>'
                + ` Maker: <code>${maker}</code>`
                + ` (${makerRole}) ·`
                + ` sha256 <code>${sha}…</code>`
                + '<div class="proc-sign-awaiting-hint">'
                + 'Tier IV Maker-Checker (CSA Z462-24 + Uptime '
                + 'Institute): a MOP requires two distinct operators. '
                + 'Change the <strong>Operator id</strong> above to a '
                + 'different name and click <strong>Sign</strong> again '
                + 'to seal the ledger entry. The same operator cannot '
                + 'witness their own draft.'
                + '</div>'
                + '</div>',
            );
            return;
        }
        const entry = escapeHTML(String(data.entry_id || '').slice(0, 16));
        const seq = escapeHTML(String(data.sequence_no || '?'));
        const sha = escapeHTML(String(data.content_sha256 || '').slice(0, 16));
        // Sealed-by-witness path carries both signers in the response.
        const witnessLine = (data.witness_required && data.first_signer)
            ? `<div class="proc-sign-witness-line">Maker: `
                + `<code>${escapeHTML(String(data.first_signer))}</code> · `
                + `Checker: <code>${escapeHTML(String(data.second_signer || operatorId))}</code></div>`
            : '';
        // Save-to-library button — Epic 6 Option A consolidation.
        // Only renders for fully-sealed signs (signed: true). Click
        // POSTs to /architect/save-to-library and reports the
        // library_id back into the same result slot.
        const idEsc = escapeHTML(draft.draft_id || '');
        const ledgerEntryEsc = escapeHTML(String(data.entry_id || ''));
        const saveBtn = `<button class="proc-btn proc-btn-save-library"
                data-action="save-to-library"
                data-draft-id="${idEsc}"
                data-ledger-entry-id="${ledgerEntryEsc}">
            📚 Save to library
        </button>`;
        slot.innerHTML = sanitizeHTML(
            `<div class="proc-sign-ok">
                Signed to ledger ·
                entry <code>${entry}</code> ·
                seq #${seq} ·
                sha256 <code>${sha}…</code>
            </div>`
            + witnessLine,
        ) + saveBtn;
    } catch (e) {
        slot.innerHTML = sanitizeHTML(
            `<div class="proc-sign-fail">Network error: `
            + `${escapeHTML(e.message)}</div>`,
        );
    }
}


// ─── Save approved draft to the corpus library ──────────────────────
async function _submitSaveToLibrary(draftId, ledgerEntryId) {
    const root = $('view-procedures-architect');
    if (!root || !_currentDraft) return;
    const draft = _currentDraft.draft || {};
    if (draft.draft_id !== draftId) return;
    const slot = root.querySelector(
        `.proc-sign-result[data-draft-id="${CSS.escape(draftId)}"]`,
    );
    if (!slot) return;
    const opInput = root.querySelector('[data-proc-operator-id]');
    const operatorId = (opInput?.value || 'wilmer.angel').trim() || 'wilmer.angel';
    try {
        const resp = await fetch(
            '/api/procedures/architect/save-to-library', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    draft_id: draft.draft_id,
                    doc_type: draft.doc_type,
                    content: draft.content,
                    asset_id: draft.asset_id || null,
                    operator_id: operatorId,
                    actor_role: 'SME_L6',
                    ledger_entry_id: ledgerEntryId || null,
                }),
            },
        );
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
            // Append a failure line rather than overwriting the sign
            // success — operator needs to see both the seal AND why
            // the library save bounced.
            slot.insertAdjacentHTML(
                'beforeend',
                sanitizeHTML(
                    `<div class="proc-library-fail">Save to library `
                    + `failed (HTTP ${resp.status}): `
                    + `${escapeHTML(data.detail || resp.statusText)}</div>`,
                ),
            );
            return;
        }
        // Replace the Save button with a success confirmation; the
        // sign block above stays in place so the audit trail line
        // is preserved.
        const btn = slot.querySelector('.proc-btn-save-library');
        if (btn) btn.remove();
        const libId = escapeHTML(String(data.library_id || '').slice(0, 16));
        const size = escapeHTML(String(data.library_size ?? '?'));
        slot.insertAdjacentHTML(
            'beforeend',
            sanitizeHTML(
                `<div class="proc-library-ok">Saved to library · `
                + `id <code>${libId}…</code> · `
                + `library now holds ${size} draft(s)</div>`,
            ),
        );
    } catch (e) {
        slot.insertAdjacentHTML(
            'beforeend',
            sanitizeHTML(
                `<div class="proc-library-fail">Network error: `
                + `${escapeHTML(e.message)}</div>`,
            ),
        );
    }
}


// ─── Click dispatch ──────────────────────────────────────────────────
function _onClick(ev) {
    const t = ev.target.closest('[data-action]');
    if (!t) return;
    const action = t.dataset.action;
    switch (action) {
        case 'generate':
            _submitGenerate();
            break;
        case 'sign':
            _submitSign(t.dataset.draftId);
            break;
        case 'ctx-fill': {
            // Chip click: pre-fill the textarea with the template and
            // substitute the currently-selected asset_id.
            const root = $('view-procedures-architect');
            if (root) _applyContextTemplate(root, t.dataset.ctxText);
            break;
        }
        case 'save-to-library':
            _submitSaveToLibrary(t.dataset.draftId, t.dataset.ledgerEntryId);
            break;
    }
}


// ─── Static skeleton + activation ────────────────────────────────────
function _wireProceduresView() {
    if (_viewWired) return;
    const root = $('view-procedures-architect');
    if (!root) return;
    const opts = DOC_TYPES.map(
        (t) => `<option value="${escapeHTML(t)}">${escapeHTML(t)}</option>`,
    ).join('');
    root.innerHTML = `
        <div class="proc-hdr">
            <h2>Procedure Architect · SOP / MOP / EOP / EMP</h2>
            <div class="proc-sub">
                LLM-authored documentation with deterministic Safety Officer
                audit. MOPs missing LOTO / PPE / CSA Z462-24 are refused.
                Approved drafts can be signed into the forensic ledger.
                Epic 6 · ADR-006 deterministic gate.
            </div>
        </div>
        <div class="proc-form">
            <label>
                Document type:
                <select data-proc-doc-type class="proc-select">${opts}</select>
            </label>
            <label>
                Asset id (optional):
                <select data-proc-asset-select class="proc-select">
                    ${_renderAssetSelect()}
                </select>
            </label>
            <label data-proc-asset-custom-wrap hidden>
                Custom asset id:
                <input type="text" data-proc-asset-custom class="proc-input"
                       placeholder="any canonical_id (e.g. genset_a, bess_1)">
            </label>
            <label data-proc-mop-category-wrap hidden>
                MOP category:
                <select data-proc-mop-category class="proc-select">
                    ${MOP_CATEGORY_KEYS.map((k) => (
                        `<option value="${escapeHTML(k)}"`
                        + `${k === MOP_CATEGORY_DEFAULT ? ' selected' : ''}>`
                        + `${escapeHTML(MOP_CATEGORY_LABELS[k])}</option>`
                    )).join('')}
                </select>
            </label>
            <label>
                Operator context:
                <div data-proc-ctx-chips class="proc-chips-row"></div>
                <textarea data-proc-context class="proc-textarea" rows="4"
                          placeholder="Describe the maintenance / operation / incident the document must cover. Example: Replace UPS-B battery cabinet on Phase 1 main bus during scheduled window."></textarea>
            </label>
            <label>
                Operator id (used at sign time — change to a DIFFERENT
                name for MOP Maker-Checker witness):
                <input type="text" data-proc-operator-id class="proc-input"
                       value="wilmer.angel"
                       placeholder="signing operator id">
            </label>
            <button data-action="generate" class="proc-btn proc-btn-generate">
                Generate
            </button>
        </div>
        <div data-proc-result class="proc-result"></div>
    `;
    // Initial chip render for the default doc_type (SOP).
    _renderContextChips(root);
    // Initial sync of the MOP-category wrap (hidden when doc_type !== MOP).
    _syncMopCategoryVisibility(root);
    // Phase 2: textarea input listener — clears verdict + hides Sign
    // when the operator edits after a generate.
    _installStaleHandler(root);
    root.addEventListener('click', _onClick);
    // Re-render chips when doc_type changes; sync custom-asset and
    // mop-category visibility when applicable. All 'change' events
    // (not 'click') so they need dedicated listeners.
    root.querySelector('[data-proc-doc-type]')?.addEventListener(
        'change', () => {
            _syncMopCategoryVisibility(root);
            _renderContextChips(root);
        },
    );
    root.querySelector('[data-proc-asset-select]')?.addEventListener(
        'change', () => _syncCustomAssetVisibility(root),
    );
    root.querySelector('[data-proc-mop-category]')?.addEventListener(
        'change', (ev) => {
            _currentMopCategory = ev.target.value || MOP_CATEGORY_DEFAULT;
            _renderContextChips(root);
        },
    );
    _viewWired = true;
}

async function _activate() {
    _wireProceduresView();
}


/** Public entry — called once from main.js at bootstrap. */
export function initProceduresView() {
    if (_routeRegistered) return;
    if (!$('view-procedures-architect')) {
        console.warn(
            '[procedures] #view-procedures-architect not in DOM; view disabled.',
        );
        return;
    }
    registerRoute('procedures-architect', {
        viewId: 'view-procedures-architect',
        activate: _activate,
    });
    _routeRegistered = true;
    console.log('[procedures] route registered (Epic 6 — Procedure Architect)');
}


// ─── Test surface ────────────────────────────────────────────────────
export const __procedures_view_test__ = {
    renderMarkdown: _renderMarkdown,
    renderResult: _renderResult,
    verdictPill: _verdictPill,
    submitGenerate: _submitGenerate,
    submitSign: _submitSign,
    submitSaveToLibrary: _submitSaveToLibrary,
    onClick: _onClick,
    renderAssetSelect: _renderAssetSelect,
    resolveAssetId: _resolveAssetId,
    syncCustomAssetVisibility: _syncCustomAssetVisibility,
    renderContextChips: _renderContextChips,
    applyContextTemplate: _applyContextTemplate,
    installStaleHandler: _installStaleHandler,
    isStaleVsLastGenerate: _isStaleVsLastGenerate,
    markResultStale: _markResultStale,
    fetchTelemetrySnapshot: _fetchTelemetrySnapshot,
    TELEMETRY_METADATA_KEYS: _TELEMETRY_METADATA_KEYS,
    initProceduresView,
    reset: () => {
        _routeRegistered = false;
        _viewWired = false;
        _currentDraft = null;
        _lastGeneratedContext = null;
        _staleHandlerInstalled = false;
        _currentMopCategory = MOP_CATEGORY_DEFAULT;
    },
    DOC_TYPES,
    ASSET_PRESETS,
    ASSET_CUSTOM_VALUE,
    ASSET_NONE_VALUE,
    CONTEXT_TEMPLATES,
    MOP_CATEGORIES,
    MOP_CATEGORY_KEYS,
    MOP_CATEGORY_LABELS,
    MOP_CATEGORY_DEFAULT,
    syncMopCategoryVisibility: _syncMopCategoryVisibility,
    getCurrentMopCategory: () => _currentMopCategory,
    setCurrentMopCategory: (k) => { _currentMopCategory = k; },
};
