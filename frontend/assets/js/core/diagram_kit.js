/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — core/diagram_kit.js
 * Diagram Rebuild Batch 0 — shared SVG diagram toolkit.
 *
 * One visual language for every engineering diagram in the HMI.
 * Before this module the Power SLD, the Cooling P&ID, the HLD
 * canvas and the Site Topology graph each carried private copies of
 * the symbol builders, the sparkline math, the severity palette and
 * the actuation modal — drifting apart commit by commit.
 *
 * Provides:
 *   - SEV tokens + severityFromChannels()  (single severity model)
 *   - symbol(type, x, y)                   (IEEE/ISA-ish symbol set,
 *     incl. Phase 2: MV Rectifier, SSCB, 800 VDC bus, BESS)
 *   - orthoPath(points) / wire(points,cls) (orthogonal-by-construction)
 *   - sparkPoints / createSparkTracker     (micro-trend sparklines)
 *   - legend(items)                        (shared diagram legend)
 *   - createActuationModal(cfg)            (RBAC-gated command modal)
 *
 * Security: every label interpolated into markup passes escapeHTML
 * (S-SEC-01) — symbol/label inputs become registry-driven and can no
 * longer be assumed to be compile-time constants.
 * ════════════════════════════════════════════════════════════════ */

import { escapeHTML } from './sanitize.js';

// ─── Severity model (single source) ────────────────────────────────
export const SEV = Object.freeze({
    OK: 'ok',
    WARNING: 'warning',
    CRITICAL: 'critical',
});

/**
 * Coarse SCADA severity from a set of Kalman channel fields. Pure.
 * is_anomalous -> critical; |max_z| >= 2 -> warning; otherwise ok.
 */
export function severityFromChannels(fieldsList) {
    let sev = SEV.OK;
    for (const f of fieldsList || []) {
        if (!f) continue;
        if (f.is_anomalous) return SEV.CRITICAL;
        if (Math.abs(Number(f.max_z) || 0) >= 2) sev = SEV.WARNING;
    }
    return sev;
}

// ─── Orthogonal wiring ─────────────────────────────────────────────
/**
 * Axis-aligned polyline -> SVG path `d`. Throws in construction if a
 * segment is diagonal — the no-spaghetti guarantee is structural, not
 * a review convention.
 */
export function orthoPath(points) {
    for (let i = 1; i < points.length; i += 1) {
        const [x1, y1] = points[i - 1];
        const [x2, y2] = points[i];
        if (x1 !== x2 && y1 !== y2) {
            throw new Error(
                `diagram_kit.orthoPath: diagonal segment (${x1},${y1})->(${x2},${y2})`);
        }
    }
    return points.map((p, i) => (i === 0 ? 'M' : 'L') + p[0] + ' ' + p[1]).join(' ');
}

/** Orthogonal connector element. cls examples: 'pf-a', 'cool-supply'.
 *  base defaults to the SLD wire class; P&ID views pass 'cool-pipe'. */
export function wire(points, cls, base = 'pf-wire') {
    return `<path class="${base} ${cls}" d="${orthoPath(points)}"/>`;
}

// ─── Symbol library ────────────────────────────────────────────────
// Every symbol carries the pid-symbol class + data-sev="ok" so the
// severity binders and CSS keep working unchanged. The base class is
// caller-overridable: the Power SLD uses 'pf-sym pid-symbol', the
// Cooling P&ID uses 'pid-symbol cool-sym' (its CSS hook order).
const DEFAULT_SYM_CLASS = 'pf-sym pid-symbol';

const _SYMBOLS = {
    xfmr: (x, y, S) =>
        `<circle ${S} cx="${x}" cy="${y - 8}" r="14"/>`
        + `<circle ${S} cx="${x}" cy="${y + 8}" r="14"/>`,
    genset: (x, y, S) =>
        `<circle ${S} cx="${x}" cy="${y}" r="23"/>`
        + `<text class="pf-glyph" x="${x}" y="${y + 6}">G</text>`,
    parbus: (x, y, S, cls) =>
        `<rect class="${cls} pf-bus" data-sev="ok" x="${x - 52}" y="${y - 5}" width="104" height="10" rx="2"/>`,
    pump: (x, y, S) =>
        `<circle ${S} cx="${x}" cy="${y}" r="21"/>`
        + `<path class="cool-glyph" d="M${x - 9} ${y} L${x + 8} ${y - 8} L${x + 8} ${y + 8} Z"/>`,
    tower: (x, y, S) =>
        `<rect ${S} x="${x - 42}" y="${y - 32}" width="84" height="64" rx="3"/>`
        + `<path class="cool-fin" d="M${x - 30} ${y - 14} H${x + 30} `
        + `M${x - 30} ${y + 2} H${x + 30} M${x - 30} ${y + 18} H${x + 30}"/>`,
    chiller: (x, y, S) =>
        `<rect ${S} x="${x - 40}" y="${y - 23}" width="80" height="46" rx="2.5"/>`,
    // Phase 2 — MV Rectifier: the AC/DC conversion boundary. The
    // diagonal divider + AC/DC glyphs are the IEC-style converter mark.
    rectifier: (x, y, S) =>
        `<rect ${S} x="${x - 40}" y="${y - 28}" width="80" height="56" rx="2.5"/>`
        + `<line class="pf-conv-divider" x1="${x - 40}" y1="${y + 28}" x2="${x + 40}" y2="${y - 28}"/>`
        + `<text class="pf-glyph pf-glyph-sm" x="${x - 22}" y="${y - 8}">AC</text>`
        + `<text class="pf-glyph pf-glyph-sm" x="${x + 22}" y="${y + 16}">DC</text>`,
    // Phase 2 — SSCB: solid-state circuit breaker (1-100 us clearing).
    sscb: (x, y, S) =>
        `<rect ${S} x="${x - 26}" y="${y - 23}" width="52" height="46" rx="2.5"/>`
        + `<path class="pf-glyph-stroke" d="M${x - 10} ${y + 12} L${x + 10} ${y - 12}"/>`
        + `<path class="pf-glyph-stroke" d="M${x - 10} ${y - 4} L${x - 2} ${y - 4}"/>`,
    // Phase 2 — 800 VDC unipolar bus bar (wider than the AC parbus).
    dcbus: (x, y, S, cls) =>
        `<rect class="${cls} pf-bus pf-bus-dc" data-sev="ok" x="${x - 120}" y="${y - 6}" width="240" height="12" rx="2"/>`,
    // Phase 2 — BESS: container + cell-stack glyph.
    bess: (x, y, S) =>
        `<rect ${S} x="${x - 40}" y="${y - 23}" width="80" height="46" rx="2.5"/>`
        + `<path class="pf-glyph-stroke" d="M${x - 22} ${y - 8} h14 M${x - 15} ${y - 15} v14 `
        + `M${x + 8} ${y - 8} h14"/>`,
    hall: (x, y, S) =>
        `<rect ${S} x="${x - 50}" y="${y - 29}" width="100" height="58" rx="2.5"/>`,
    crah: (x, y, S) =>
        `<rect ${S} x="${x - 28}" y="${y - 17}" width="56" height="34" rx="2.5"/>`,
    // Default equipment box (util / ats / ups / batt / rpp / cdu ...).
    box: (x, y, S) =>
        `<rect ${S} x="${x - 40}" y="${y - 23}" width="80" height="46" rx="2.5"/>`,
};

/**
 * SVG markup for one equipment symbol. Unknown types -> box.
 * opts.cls overrides the base class list (e.g. 'pid-symbol cool-sym'
 * for the Cooling P&ID CSS hooks); data-sev="ok" is always stamped.
 */
export function symbol(type, x, y, opts = {}) {
    const cls = opts.cls || DEFAULT_SYM_CLASS;
    const S = `class="${cls}" data-sev="ok"`;
    return (_SYMBOLS[type] || _SYMBOLS.box)(x, y, S, cls);
}

/** Symbol types rendered by a dedicated builder (legend/testing aid). */
export const SYMBOL_TYPES = Object.freeze(Object.keys(_SYMBOLS));

// ─── Sparklines (micro-trends, last N Kalman ticks) ────────────────
/** Map a value buffer to an SVG polyline `points` string within a box. */
export function sparkPoints(values, sx, sy, sw, sh) {
    if (!values || values.length < 2) return '';
    const lo = Math.min(...values);
    const span = (Math.max(...values) - lo) || 1;
    const step = sw / (values.length - 1);
    return values.map((v, i) => {
        const px = sx + i * step;
        // sy is the box centre; high value -> top of the box.
        const py = sy - ((v - lo) / span - 0.5) * sh;
        return `${px.toFixed(1)},${py.toFixed(1)}`;
    }).join(' ');
}

function _siteMeanZ(channels) {
    const ids = channels ? Object.keys(channels) : [];
    if (!ids.length) return 0;
    let sum = 0;
    for (const c of ids) sum += Math.abs(Number(channels[c].mean_z) || 0);
    return sum / ids.length;
}

/**
 * Stateful sparkline tracker shared by the SLD views. One instance
 * per view; `update(channels, matcher)` pushes one tick per tracked
 * node and redraws its <polyline> inside `rootSelector`.
 *
 * matcher(nodeId, channelId) decides channel ownership — pass the
 * registry's matchesChannel for prefix discipline, or a legacy
 * substring matcher during migration.
 */
export function createSparkTracker({ rootSelector, nodes, ticks = 20 }) {
    const history = {};
    function update(channels, matcher) {
        const ids = channels ? Object.keys(channels) : [];
        const siteAvg = _siteMeanZ(channels);
        nodes.forEach((nodeId) => {
            const poly = document.querySelector(
                `${rootSelector} [data-spark="${nodeId}"]`);
            if (!poly) return;
            const matched = ids.filter((c) => matcher(nodeId, c));
            const v = matched.length
                ? matched.reduce((s, c) =>
                    s + Math.abs(Number(channels[c].mean_z) || 0), 0) / matched.length
                : siteAvg;
            const hist = history[nodeId] || (history[nodeId] = []);
            hist.push(v);
            if (hist.length > ticks) hist.shift();
            poly.setAttribute('points', sparkPoints(
                hist, Number(poly.dataset.sx), Number(poly.dataset.sy),
                Number(poly.dataset.sw), Number(poly.dataset.sh)));
        });
    }
    function reset() { for (const k of Object.keys(history)) delete history[k]; }
    return { update, reset, _history: history };
}

/** Sparkline polyline stub with its plot-box geometry stamped on. */
export function sparkPolyline(nodeId, sx, sy, sw = 52, sh = 12) {
    return `<polyline class="pf-spark" data-spark="${escapeHTML(nodeId)}" `
        + `data-sx="${sx}" data-sy="${sy}" data-sw="${sw}" data-sh="${sh}" points=""/>`;
}

// ─── Legend ────────────────────────────────────────────────────────
/**
 * Shared diagram legend. items: [{ swatch:'ok'|'warning'|'critical'
 * |'ac'|'dc'|'standby', label }]. Renders as one SVG group anchored
 * at (x, y); every diagram view mounts the same legend so the visual
 * language is learned once.
 */
export function legend(items, x, y) {
    const rows = items.map((it, i) =>
        `<g class="dk-legend-row" transform="translate(0 ${i * 18})">`
        + `<rect class="dk-swatch dk-swatch-${escapeHTML(it.swatch)}" x="0" y="-9" width="14" height="10" rx="2"/>`
        + `<text class="dk-legend-text" x="22" y="0">${escapeHTML(it.label)}</text>`
        + `</g>`).join('');
    return `<g class="dk-legend" transform="translate(${x} ${y})">${rows}</g>`;
}

/** The default legend every SLD view mounts (one visual language). */
export const DEFAULT_LEGEND = Object.freeze([
    { swatch: 'ok', label: 'Nominal' },
    { swatch: 'warning', label: 'Warning (|z| >= 2)' },
    { swatch: 'critical', label: 'Critical / anomalous' },
    { swatch: 'ac', label: 'AC path (3-phase)' },
    { swatch: 'dc', label: '800 VDC unipolar TN-S' },
]);

// ─── Actuation modal (RBAC-gated command dialog) ───────────────────
/**
 * Factory for the confirm-command modal shared by the SLD control
 * planes (Power breakers / Cooling pumps). DOM contract preserved
 * verbatim from the original power.js implementation: ids and class
 * names are caller-supplied so existing tests and CSS keep matching.
 *
 * cfg: { modalId, titleId, roleSelectId, icon, title, commands:
 *        [{cmd,label}], onSubmit(nodeId, cmd, actorRole) }
 */
export function createActuationModal(cfg) {
    let _cmd = null;

    function close() {
        const m = document.getElementById(cfg.modalId);
        if (m) m.hidden = true;
    }

    function _ensure() {
        let modal = document.getElementById(cfg.modalId);
        if (modal) return modal;
        modal = document.createElement('div');
        modal.id = cfg.modalId;
        modal.className = 'pwr-modal-overlay';
        modal.hidden = true;
        const cmdBtns = cfg.commands.map((c) =>
            `<button type="button" class="pwr-cmd-btn" data-cmd="${escapeHTML(c.cmd)}">`
            + `${escapeHTML(c.label)}</button>`).join('');
        modal.innerHTML = `
        <div class="pwr-modal" role="dialog" aria-modal="true" aria-labelledby="${escapeHTML(cfg.titleId)}">
            <div class="pwr-modal-hdr">
                <span class="pwr-modal-icon">${cfg.icon}</span>
                <h3 id="${escapeHTML(cfg.titleId)}">${escapeHTML(cfg.title)}</h3>
            </div>
            <div class="pwr-modal-body">
                <p class="pwr-modal-target">${escapeHTML(cfg.targetLabel || 'Target:')}
                    <strong data-field="target">&mdash;</strong></p>
                <label class="pwr-modal-lbl">Command</label>
                <div class="pwr-modal-cmds">${cmdBtns}</div>
                <label class="pwr-modal-lbl" for="${escapeHTML(cfg.roleSelectId)}">Actor role (RBAC claim)</label>
                <select id="${escapeHTML(cfg.roleSelectId)}" class="pwr-modal-select">
                    <option value="TECH_L4">TECH_L4</option>
                    <option value="SENIOR_TECH_L5">SENIOR_TECH_L5</option>
                    <option value="SME_L6" selected>SME_L6</option>
                </select>
                <div class="pwr-modal-result" data-field="result"></div>
            </div>
            <div class="pwr-modal-foot">
                <button type="button" class="btn btn-secondary" data-act="cancel">Cancel</button>
                <button type="button" class="btn" data-act="confirm" disabled>Confirm actuation</button>
            </div>
        </div>`;
        document.body.appendChild(modal);

        modal.addEventListener('click', (e) => {
            if (e.target === modal || e.target.dataset.act === 'cancel') {
                close();
                return;
            }
            const cmdBtn = e.target.closest('.pwr-cmd-btn');
            if (cmdBtn) {
                _cmd = cmdBtn.dataset.cmd;
                modal.querySelectorAll('.pwr-cmd-btn').forEach((b) =>
                    b.classList.toggle('is-sel', b === cmdBtn));
                modal.querySelector('[data-act="confirm"]').disabled = false;
                return;
            }
            if (e.target.dataset.act === 'confirm') {
                cfg.onSubmit(
                    modal.dataset.nodeId, _cmd,
                    modal.querySelector(`#${cfg.roleSelectId}`).value,
                );
            }
        });
        return modal;
    }

    function open(nodeId, label) {
        const modal = _ensure();
        _cmd = null;
        modal.dataset.nodeId = nodeId;
        modal.querySelector('[data-field="target"]').textContent = label || nodeId;
        const result = modal.querySelector('[data-field="result"]');
        result.textContent = '';
        result.className = 'pwr-modal-result';
        modal.querySelectorAll('.pwr-cmd-btn').forEach((b) => b.classList.remove('is-sel'));
        modal.querySelector('[data-act="confirm"]').disabled = true;
        modal.hidden = false;
    }

    /** Paint a writeBmsTag-style outcome into the modal result line. */
    function showResult({ ok, status, data }, cmd, nodeId) {
        const modal = document.getElementById(cfg.modalId);
        if (!modal) return;
        const result = modal.querySelector('[data-field="result"]');
        if (status === 403) {
            result.className = 'pwr-modal-result is-denied';
            result.textContent = `RBAC DENIED — ${data.detail || 'SME_L6 required for BMS write'}`;
            return;
        }
        if (!ok) {
            result.className = 'pwr-modal-result is-err';
            result.textContent = `Command rejected — ${data.detail || ('HTTP ' + status)}`;
            return;
        }
        result.className = 'pwr-modal-result is-ok';
        result.textContent = `✓ ${cmd} accepted — ${data.message || nodeId}`;
    }

    function showPending() {
        const modal = document.getElementById(cfg.modalId);
        if (!modal) return;
        const result = modal.querySelector('[data-field="result"]');
        result.className = 'pwr-modal-result is-pending';
        result.textContent = 'Issuing command to BMS control surface…';
    }

    return { open, close, showPending, showResult };
}
