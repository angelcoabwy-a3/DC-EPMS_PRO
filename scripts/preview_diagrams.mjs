/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — scripts/preview_diagrams.mjs
 * Diagram Rebuild — standalone visual preview generator.
 *
 * Imports the REAL view builders (the same pure functions vitest
 * exercises) and dumps the three regenerated diagrams into one
 * static HTML page styled by the served app.css — so the operator
 * can SEE the rebuild without logging into the HMI.
 *
 * Usage:  node scripts/preview_diagrams.mjs
 * Output: logs/diagram_preview.html  (open in any browser while the
 *         backend serves :8080 for the stylesheet)
 * ════════════════════════════════════════════════════════════════ */
import { writeFileSync, mkdirSync } from 'node:fs';

const { __power_test__ } = await import('../frontend/assets/js/views/power.js');
const { __cooling_test__ } = await import('../frontend/assets/js/views/cooling.js');
const { __topology_test__ } = await import('../frontend/assets/js/views/topology.js');

const powerSvg = __power_test__.buildFlatMarkup();
const coolingSvg = __cooling_test__.buildCoolingSld();
const hldSvg = __topology_test__.buildHldMarkup();

const page = `<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>DC-EPMS PRO — Diagram Rebuild Preview (Batches 0-4)</title>
<link rel="stylesheet" href="http://127.0.0.1:8080/assets/app.css?v=preview">
<style>
  body { background:#0B0D10; color:#c7d6e2; font-family:system-ui,sans-serif;
         margin:0; padding:24px 32px; }
  h1 { font-size:20px; letter-spacing:.06em; }
  h2 { font-size:15px; letter-spacing:.1em; color:#8fa3b8; margin-top:40px;
       border-bottom:1px solid #22303c; padding-bottom:6px; }
  .note { font-size:13px; color:#7e93a5; max-width:900px; }
  svg { width:100%; max-width:1280px; height:auto; display:block;
        background:#0E1318; border:1px solid #1C2128; border-radius:6px;
        margin-top:12px; }
</style>
</head>
<body>
<h1>⚡ DC-EPMS PRO — Diagram Rebuild Preview</h1>
<p class="note">Generado por <code>scripts/preview_diagrams.mjs</code> desde los
builders REALES de las vistas (mismas funciones que valida vitest). Estático:
sin telemetría viva, sin login — para eso, el HMI en
<a href="http://127.0.0.1:8080/" style="color:#00B8D4">127.0.0.1:8080</a>.</p>

<h2>1 · POWER &amp; UPS — SLD ortogonal + rama FASE 2 (Building D, 800 VDC unipolar TN-S)</h2>
<p class="note">Mirá la mitad inferior: UTILITY D 35 kV AC → MV RECTIFIER →
<strong>fence AC/DC rotulado</strong> → SSCB (IEC 60947-2) → bus 800 VDC →
BESS 2.5 MWh + RPP D1/D2. Punteado = DESIGN (no desplegado). Leyenda compartida
arriba a la izquierda.</p>
<svg viewBox="0 0 1200 1080" class="pf-svg pid-svg" xmlns="http://www.w3.org/2000/svg">${powerSvg}</svg>

<h2>2 · COOLING (DLC) — P&amp;ID ortogonal sobre el kit compartido</h2>
<p class="note">Mismo lenguaje visual que Power (kit + tokens de severidad
unificados). En el HMI, el botón WHAT-IF ahora tripea el DAG hidráulico real:
un chiller → su peer N+1 queda en warning; ambos → CDUs + hall en critical.</p>
<svg viewBox="0 0 1040 740" class="cool-svg pid-svg" xmlns="http://www.w3.org/2000/svg">${coolingSvg}</svg>

<h2>3 · TOPOLOGY (HLD) — system-of-systems generado desde el registry</h2>
<p class="note">El SVG estático de 18 KB murió. Flujos 100% ortogonales,
header eléctrico corregido a <strong>480 VAC 3-φ</strong> (el "480VDC" falso fue
erradicado), y Building D como marcador honesto de diseño Fase 2.</p>
<svg viewBox="0 0 1100 620" class="topo-svg" xmlns="http://www.w3.org/2000/svg">${hldSvg}</svg>

<h2>4 · SITE TOPOLOGY + cross-links (solo en el HMI vivo)</h2>
<p class="note">El grafo force-directed ahora tiene severidad Hermes en vivo
(glow warning/critical) y el panel de detalle gana «Open in Power SLD /
Cooling P&amp;ID» — un activo, una identidad, cinco vistas. Eso requiere el
stream vivo: vélo en el HMI (Site Topology → click en ups_a o chiller_1).</p>
</body>
</html>`;

mkdirSync('logs', { recursive: true });
writeFileSync('logs/diagram_preview.html', page, 'utf8');
console.log('[preview] logs/diagram_preview.html written ('
    + page.length + ' chars; power=' + powerSvg.length
    + ', cooling=' + coolingSvg.length + ', hld=' + hldSvg.length + ')');
