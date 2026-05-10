/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — core/pue_widget.js
 *
 * Sprint 5.5b: Live PUE widget on Overview view.
 *
 * Polls GET /api/physics/pue every 15s. Renders two cards (Phase 1
 * live, Phase 2 design target) with PUE value + target band + state
 * color + IT / cooling / electrical breakdown + first-law residual.
 *
 * Visual coding:
 *   good   green   pue <= warn_threshold
 *   warn   amber   warn_threshold < pue <= crit_threshold
 *   crit   red     pue > crit_threshold
 *   design dim     Phase 2 always (design target, not live load)
 *
 * The fill bar inside each card visualizes pue within [1.0, crit].
 * 0% fill = perfect 1.0 PUE; 100% = at the crit threshold.
 *
 * Per ADR-006: advisory only. No mutation; no LLM in critical path.
 * ════════════════════════════════════════════════════════════════ */

const POLL_INTERVAL_MS = 15_000;
const API_BASE = '';

let _intervalId = null;
let _initialized = false;

function _$(sel) { return document.querySelector(sel); }

function _fmtNum(n, digits = 3) {
    if (n === null || n === undefined || Number.isNaN(n)) return '—';
    return Number(n).toFixed(digits);
}

function _fmtKw(n) {
    if (n === null || n === undefined) return '—';
    if (n >= 1000) return (n / 1000).toFixed(2) + ' MW';
    return Math.round(n) + ' kW';
}

function _fillPercent(pue, crit) {
    if (!Number.isFinite(pue) || !Number.isFinite(crit) || crit <= 1.0) return 0;
    const span = crit - 1.0;
    const pos = Math.max(0, pue - 1.0);
    return Math.min(100, (pos / span) * 100);
}

function _renderCard(snap, cardEl) {
    if (!cardEl || !snap) return;
    const get = (field) => cardEl.querySelector(`[data-field="${field}"]`);

    // Voltage class subtitle
    get('voltage').textContent = snap.voltage_class || '—';

    // PUE value + target
    get('pue').textContent = _fmtNum(snap.pue, 3);
    get('target').textContent = `target ${_fmtNum(snap.target_pue, 2)}`;

    // State coloring on the card itself
    cardEl.classList.remove('pue-card-good', 'pue-card-warn', 'pue-card-crit');
    cardEl.classList.add(`pue-card-${snap.state}`);

    // Fill bar
    const fill = get('fill');
    if (fill) {
        fill.style.width = _fillPercent(snap.pue, snap.crit_threshold) + '%';
        fill.classList.remove('pue-fill-good', 'pue-fill-warn', 'pue-fill-crit', 'pue-fill-design');
        fill.classList.add(`pue-fill-${snap.state}`);
    }

    // Breakdown chips
    const bd = snap.breakdown || {};
    get('it').textContent   = `IT ${_fmtKw(bd.it_load_kw)}`;
    get('cool').textContent = `cool ${_fmtKw(bd.cooling_kw)}`;
    get('elec').textContent = `elec ${_fmtKw(bd.electrical_losses_kw)}`;

    // First-law residual
    const res = snap.first_law_residual_pct;
    const resEl = get('residual');
    if (resEl) {
        resEl.textContent = `first-law residual ${_fmtNum(res, 2)} % · ${snap.first_law_state.replace(/_/g, ' ')}`;
        resEl.classList.remove('pue-residual-audit_grade', 'pue-residual-acceptable', 'pue-residual-instrumentation_drift');
        resEl.classList.add(`pue-residual-${snap.first_law_state}`);
    }
}

async function _refresh() {
    const widget = document.getElementById('pue-widget');
    if (!widget) return;
    try {
        const resp = await fetch(`${API_BASE}/api/physics/pue`);
        if (!resp.ok) {
            console.warn('[pue_widget] non-OK response', resp.status);
            return;
        }
        const data = await resp.json();
        widget.removeAttribute('hidden');

        _renderCard(data.phase_1, document.getElementById('pue-card-phase-1'));
        _renderCard(data.phase_2, document.getElementById('pue-card-phase-2'));

        const stamp = document.getElementById('pue-stamp');
        if (stamp) {
            const ts = data.phase_1?.timestamp_iso;
            stamp.textContent = ts ? new Date(ts).toISOString().slice(11, 19) + 'Z' : '—';
        }

        // Mirror the live PUE value into the legacy KPI tile if present
        // (keeps the existing "PUE" card on Overview consistent).
        const kpi = document.getElementById('kpi-pue');
        if (kpi && data.phase_1?.pue) {
            kpi.textContent = _fmtNum(data.phase_1.pue, 2);
            kpi.classList.remove('ok', 'warn', 'crit');
            kpi.classList.add(
                data.phase_1.state === 'crit' ? 'crit' :
                data.phase_1.state === 'warn' ? 'warn' : 'ok',
            );
        }
    } catch (e) {
        console.warn('[pue_widget] refresh failed:', e);
    }
}

export function initPueWidget() {
    if (_initialized) return;
    if (!document.getElementById('pue-widget')) {
        console.warn('[pue_widget] #pue-widget not in DOM; widget disabled.');
        return;
    }
    document.getElementById('pue-refresh-btn')?.addEventListener('click', _refresh);

    _refresh();
    if (_intervalId) clearInterval(_intervalId);
    _intervalId = setInterval(_refresh, POLL_INTERVAL_MS);
    _initialized = true;
    console.log('[pue_widget] ready (polling every 15s)');
}
