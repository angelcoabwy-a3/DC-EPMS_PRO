/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — views/maintenance.js
 *
 * Sprint 6 Fase 5: CMMS Core v1.0 frontend.
 *
 * Renders the Maintenance view backed by /api/cmms/* endpoints:
 *   - Asset Health Grid (left panel) clustered by asset_type
 *   - Work Order backlog (right panel) with filters
 *   - 4 KPI cards on top (totals, overdue, predictive)
 *
 * Polling: every 15s when the view is visible. Pauses when navigated
 * away. No SSE for this MVP — polling cadence matches the SHI panel
 * pattern from app.js.
 *
 * Read-only for now: approve/reject buttons inline are V2 (Sprint 6.5
 * or later). Operators approve via curl/Swagger or the /docs UI today.
 *
 * Style: instrument-grade (mirrors Activity Strip discipline).
 * No emojis, no animations beyond severity color transitions.
 * ════════════════════════════════════════════════════════════════ */

const POLL_INTERVAL_MS = 15_000;
const API_BASE = '';  // same-origin

let _container = null;
let _intervalId = null;
let _isVisible = false;
let _filters = {
    status: '',
    priority: '',
    trigger_source: '',
    only_open: true,
};

// ─── Fetch helpers ────────────────────────────────────────────────
async function _fetchAssets() {
    const r = await fetch(`${API_BASE}/api/cmms/assets?limit=500`);
    if (!r.ok) throw new Error(`assets ${r.status}`);
    return r.json();
}

async function _fetchWorkOrders() {
    const params = new URLSearchParams();
    if (_filters.status)         params.set('status', _filters.status);
    if (_filters.priority)       params.set('priority', _filters.priority);
    if (_filters.trigger_source) params.set('trigger_source', _filters.trigger_source);
    if (_filters.only_open)      params.set('only_open', 'true');
    params.set('limit', '200');
    const r = await fetch(`${API_BASE}/api/cmms/work-orders?${params}`);
    if (!r.ok) throw new Error(`work-orders ${r.status}`);
    return r.json();
}

// ─── Sprint 6.6: CET signature + approve/reject actions ───────────
// CET id stored in sessionStorage so it persists across page reloads
// within the tab but resets on browser close. ADR-006 compliance:
// the backend enforces the state machine; this is just convenience.
function _getCetId() {
    let id = sessionStorage.getItem('cmms_cet_id');
    if (!id || !id.trim()) {
        id = prompt(
            'Enter your CET ID for this session\n(used to sign work order approvals; reset on browser close):',
            'wilmer',
        );
        if (id && id.trim()) {
            sessionStorage.setItem('cmms_cet_id', id.trim());
            return id.trim();
        }
        return null;
    }
    return id;
}

async function _approveWorkOrder(woId, woContext) {
    const cetId = _getCetId();
    if (!cetId) return false;

    const ok = confirm(
        `Approve work order?\n\n` +
        `  WO:        ${woId}\n` +
        `  Asset:     ${woContext.asset_id}\n` +
        `  Priority:  ${woContext.priority}\n` +
        `  Class:     ${woContext.work_class} / ${woContext.procedure_class || '—'}\n` +
        `  LOTO:      ${woContext.requires_loto ? 'YES' : 'no'}\n` +
        `  CET sign:  ${cetId}\n\n` +
        `This transitions status pending_approval -> approved per ADR-006.`,
    );
    if (!ok) return false;

    const r = await fetch(`${API_BASE}/api/cmms/work-orders/${encodeURIComponent(woId)}/approve`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({cet_id: cetId}),
    });
    if (!r.ok) {
        const errText = await r.text().catch(() => `${r.status}`);
        alert(`Approve failed: ${errText.slice(0, 200)}`);
        return false;
    }
    return true;
}

async function _rejectWorkOrder(woId, woContext) {
    const cetId = _getCetId();
    if (!cetId) return false;

    const reason = prompt(
        `Reject work order ${woId}?\n` +
        `Asset: ${woContext.asset_id} (priority ${woContext.priority})\n\n` +
        `Enter rejection reason (required):`,
    );
    if (!reason || !reason.trim()) return false;

    const ok = confirm(
        `Confirm rejection?\n\n` +
        `  WO:     ${woId}\n` +
        `  Reason: ${reason.trim()}\n` +
        `  CET:    ${cetId}\n\n` +
        `This transitions status pending_approval -> rejected (irreversible).`,
    );
    if (!ok) return false;

    const r = await fetch(`${API_BASE}/api/cmms/work-orders/${encodeURIComponent(woId)}/reject`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({cet_id: cetId, rejection_reason: reason.trim()}),
    });
    if (!r.ok) {
        const errText = await r.text().catch(() => `${r.status}`);
        alert(`Reject failed: ${errText.slice(0, 200)}`);
        return false;
    }
    return true;
}

async function _onActionClick(e) {
    const btn = e.target.closest('[data-cmms-action]');
    if (!btn || btn.disabled) return;
    const action = btn.dataset.cmmsAction;
    const woId = btn.dataset.woId;
    if (!action || !woId) return;

    // Build context from the row's data attributes
    const tr = btn.closest('tr');
    const ctx = {
        asset_id: tr?.dataset.assetId || '',
        priority: tr?.dataset.priority || '',
        work_class: tr?.dataset.workClass || '',
        procedure_class: tr?.dataset.procedureClass || '',
        requires_loto: tr?.dataset.requiresLoto === 'true',
    };

    btn.disabled = true;
    btn.textContent = action === 'approve' ? '...' : '...';
    try {
        const ok = action === 'approve'
            ? await _approveWorkOrder(woId, ctx)
            : await _rejectWorkOrder(woId, ctx);
        if (ok) {
            await _refresh();
        }
    } finally {
        btn.disabled = false;
    }
}

// ─── Formatters ───────────────────────────────────────────────────
function _ageText(isoTimestamp) {
    if (!isoTimestamp) return '—';
    const ms = Date.now() - new Date(isoTimestamp).getTime();
    const min = Math.floor(ms / 60_000);
    if (min < 1) return 'just now';
    if (min < 60) return `${min}m`;
    const hr = Math.floor(min / 60);
    if (hr < 24) return `${hr}h`;
    return `${Math.floor(hr / 24)}d`;
}

function _escape(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"']/g, c => (
        {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]
    ));
}

// ─── KPI cards ────────────────────────────────────────────────────
function _renderKPIs(assets, workOrders) {
    const $ = id => document.querySelector(`#view-maintenance [data-field="${id}"]`);

    const totalAssets = assets.length;
    const byCrit = assets.reduce((acc, a) => {
        acc[a.criticality_class] = (acc[a.criticality_class] || 0) + 1;
        return acc;
    }, {});
    const critSummary = ['critical', 'high', 'medium', 'low']
        .map(k => `${k[0].toUpperCase()}: ${byCrit[k] || 0}`).join(' · ');

    const openWos = workOrders.filter(w =>
        ['pending_approval', 'approved', 'scheduled', 'in_progress'].includes(w.status));
    const byPri = openWos.reduce((acc, w) => {
        acc[w.priority] = (acc[w.priority] || 0) + 1;
        return acc;
    }, {});
    const priSummary = ['P1', 'P2', 'P3', 'P4']
        .map(p => `${p}: ${byPri[p] || 0}`).join(' · ');

    const overdue = workOrders.filter(w =>
        w.due_at && new Date(w.due_at) < new Date()
        && !['completed', 'rejected', 'cancelled'].includes(w.status)
    ).length;

    const predictive = workOrders.filter(w => w.trigger_source === 'predictive_kalman').length;

    if ($('total-assets'))         $('total-assets').textContent = totalAssets;
    if ($('total-by-criticality')) $('total-by-criticality').textContent = critSummary;
    if ($('total-open-wos'))       $('total-open-wos').textContent = openWos.length;
    if ($('open-by-priority'))     $('open-by-priority').textContent = priSummary;
    if ($('overdue-wos')) {
        $('overdue-wos').textContent = overdue;
        $('overdue-wos').dataset.severity = overdue > 0 ? 'high' : 'low';
    }
    if ($('predictive-wos')) {
        $('predictive-wos').textContent = predictive;
        $('predictive-wos').dataset.severity = predictive > 0 ? 'high' : 'low';
    }
    const last = document.querySelector('#view-maintenance [data-field="last-refresh"]');
    if (last) last.textContent = `last refresh: ${new Date().toLocaleTimeString('en-CA', { hour12: false })}`;
}

// ─── Asset health grid ────────────────────────────────────────────
function _groupAssetsByCluster(assets) {
    // Cluster by asset_type, with path/pillar shown as sub-line.
    const groups = {};
    for (const a of assets) {
        const key = a.asset_type;
        if (!groups[key]) groups[key] = [];
        groups[key].push(a);
    }
    // Sort: critical types first
    const order = [
        'ups', 'ats', 'chiller', 'transformer', 'switchgear',
        'rectifier', 'utility_intake', 'genset', 'rpp', 'busway',
        'cdu', 'pump', 'cooling_tower_field', 'cooling_tower',
        'fuel_tank', 'it_rack', 'bms_panel', 'sensor', 'workstation', 'other',
    ];
    return order
        .filter(k => groups[k])
        .map(k => ({ asset_type: k, assets: groups[k] }));
}

function _renderAssetGrid(assets) {
    const container = document.getElementById('m-asset-grid');
    if (!container) return;

    if (assets.length === 0) {
        container.innerHTML = '<div class="m-empty">No assets found.</div>';
        return;
    }

    const clusters = _groupAssetsByCluster(assets);
    const cards = clusters.map(({ asset_type, assets: items }) => {
        const total = items.length;
        const healthy = items.filter(a => a.health_state === 'healthy').length;
        const degraded = items.filter(a => a.health_state === 'degraded').length;
        const failed = items.filter(a => a.health_state === 'failed').length;
        const critCount = items.filter(a => a.criticality_class === 'critical').length;

        // Determine card severity
        let cardSev = 'ok';
        if (failed > 0) cardSev = 'crit';
        else if (degraded > 0) cardSev = 'warn';

        // Path/pillar summary for this cluster
        const paths = [...new Set(items.map(a => a.path).filter(Boolean))].join(', ') || '—';
        const pillars = [...new Set(items.map(a => a.redundancy_pillar).filter(Boolean))].join(', ') || '—';

        return `
            <div class="m-asset-card" data-severity="${cardSev}">
                <div class="m-asset-card-hdr">
                    <span class="m-asset-type">${_escape(asset_type)}</span>
                    <span class="m-asset-count">${total}</span>
                </div>
                <div class="m-asset-card-body">
                    <div class="m-asset-meta">
                        <span class="m-meta-k">paths</span><span class="m-meta-v">${_escape(paths)}</span>
                    </div>
                    <div class="m-asset-meta">
                        <span class="m-meta-k">pillar</span><span class="m-meta-v">${_escape(pillars)}</span>
                    </div>
                    <div class="m-asset-meta">
                        <span class="m-meta-k">critical</span>
                        <span class="m-meta-v" data-severity="${critCount > 0 ? 'high' : 'low'}">${critCount}</span>
                    </div>
                </div>
                <div class="m-asset-card-foot">
                    <span class="m-health-pill m-health-healthy" title="healthy">${healthy}</span>
                    <span class="m-health-pill m-health-degraded" title="degraded">${degraded}</span>
                    <span class="m-health-pill m-health-failed" title="failed">${failed}</span>
                </div>
            </div>
        `;
    }).join('');

    container.innerHTML = cards;
}

// ─── Work order backlog table ─────────────────────────────────────
function _renderWOBacklog(workOrders) {
    const tbody = document.getElementById('m-wo-tbody');
    const meta = document.querySelector('#view-maintenance [data-field="wo-count-meta"]');
    if (!tbody) return;

    if (meta) meta.textContent = `${workOrders.length} shown`;

    if (workOrders.length === 0) {
        tbody.innerHTML = '<tr><td colspan="10" class="m-empty">No work orders match the current filters.</td></tr>';
        return;
    }

    const rows = workOrders.map(w => {
        const isOverdue = w.due_at && new Date(w.due_at) < new Date()
            && !['completed', 'rejected', 'cancelled'].includes(w.status);
        const wid = _escape(w.work_order_id);
        const asset = _escape(w.asset_id);
        const pri = _escape(w.priority);
        const wclass = _escape(w.work_class);
        const procClass = _escape(w.procedure_class || '');
        const lor = w.lor;
        const status = _escape(w.status);
        const trigger = _escape(w.trigger_source);
        const mop = _escape(w.linked_mop_id || '—');
        const age = _ageText(w.timestamp);
        const requiresLoto = w.requires_loto ? 'true' : 'false';

        // Sprint 6.6: inline approve/reject ONLY when pending_approval.
        // Other statuses show a dim "—" placeholder to preserve column width.
        const actionsCell = w.status === 'pending_approval'
            ? `
                <td class="m-wo-actions">
                    <button class="m-action-btn m-action-approve" data-cmms-action="approve" data-wo-id="${wid}" title="Approve and sign as CET">✓</button>
                    <button class="m-action-btn m-action-reject"  data-cmms-action="reject"  data-wo-id="${wid}" title="Reject with reason">✗</button>
                </td>
            `
            : `<td class="m-wo-actions m-wo-actions-disabled">—</td>`;

        return `
            <tr ${isOverdue ? 'data-overdue="true"' : ''}
                data-asset-id="${asset}"
                data-priority="${pri}"
                data-work-class="${wclass}"
                data-procedure-class="${procClass}"
                data-requires-loto="${requiresLoto}">
                <td class="m-wo-id" title="${wid}">${wid.slice(-12)}</td>
                <td class="m-wo-asset">${asset}</td>
                <td><span class="m-pri-badge m-pri-${pri.toLowerCase()}">${pri}</span></td>
                <td><span class="m-wclass-badge m-wclass-${wclass.toLowerCase()}">${wclass}</span></td>
                <td class="m-wo-lor">${lor}</td>
                <td><span class="m-status-pill m-status-${status.replace(/_/g, '-')}">${status.replace(/_/g, ' ')}</span></td>
                <td class="m-wo-trigger">${trigger.replace(/_/g, ' ')}</td>
                <td class="m-wo-mop">${mop}</td>
                <td class="m-wo-age">${age}</td>
                ${actionsCell}
            </tr>
        `;
    }).join('');

    tbody.innerHTML = rows;
}

// ─── Refresh cycle ────────────────────────────────────────────────
async function _refresh() {
    if (!_isVisible) return;
    try {
        const [assetsResp, wosResp] = await Promise.all([
            _fetchAssets(),
            _fetchWorkOrders(),
        ]);
        const assets = assetsResp.assets || [];
        const wos = wosResp.work_orders || [];
        _renderKPIs(assets, wos);
        _renderAssetGrid(assets);
        _renderWOBacklog(wos);
    } catch (err) {
        console.warn('[maintenance] refresh failed:', err);
        const tbody = document.getElementById('m-wo-tbody');
        if (tbody) {
            tbody.innerHTML = `<tr><td colspan="10" class="m-empty m-error">Refresh failed: ${_escape(err.message)}</td></tr>`;
        }
    }
}

// ─── Visibility tracking ──────────────────────────────────────────
function _checkVisibility() {
    const view = document.getElementById('view-maintenance');
    if (!view) return false;
    return !view.hasAttribute('hidden');
}

function _onVisibilityChange() {
    const wasVisible = _isVisible;
    _isVisible = _checkVisibility();
    if (_isVisible && !wasVisible) {
        // Just became visible — refresh immediately + start polling
        _refresh();
    }
    if (!_isVisible && wasVisible) {
        // Just got hidden — kept the interval but next tick will skip
    }
}

// ─── Filter handlers ──────────────────────────────────────────────
function _wireFilters() {
    const sf = document.getElementById('m-filter-status');
    const pf = document.getElementById('m-filter-priority');
    const tf = document.getElementById('m-filter-trigger');
    const of = document.getElementById('m-filter-only-open');
    const rb = document.getElementById('m-refresh-btn');

    if (sf) sf.addEventListener('change', () => { _filters.status = sf.value; _refresh(); });
    if (pf) pf.addEventListener('change', () => { _filters.priority = pf.value; _refresh(); });
    if (tf) tf.addEventListener('change', () => { _filters.trigger_source = tf.value; _refresh(); });
    if (of) of.addEventListener('change', () => { _filters.only_open = of.checked; _refresh(); });
    if (rb) rb.addEventListener('click', _refresh);
}

// Sprint 6.6: delegated click listener for inline approve/reject buttons.
// Single listener on the tbody catches clicks even on dynamically rendered
// rows (no need to re-bind on every refresh).
function _wireActionButtons() {
    const tbody = document.getElementById('m-wo-tbody');
    if (!tbody) return;
    tbody.addEventListener('click', _onActionClick);
}

// ─── Public API ───────────────────────────────────────────────────
export function initMaintenanceView() {
    _container = document.getElementById('view-maintenance');
    if (!_container) {
        console.warn('[maintenance] #view-maintenance not in DOM; view disabled.');
        return;
    }
    _wireFilters();
    _wireActionButtons();

    // Observe show/hide via mutation observer on the hidden attribute.
    const observer = new MutationObserver(_onVisibilityChange);
    observer.observe(_container, { attributes: true, attributeFilter: ['hidden'] });

    // Initial check + interval
    _isVisible = _checkVisibility();
    if (_isVisible) _refresh();

    if (_intervalId) clearInterval(_intervalId);
    _intervalId = setInterval(() => {
        if (_isVisible) _refresh();
    }, POLL_INTERVAL_MS);
}

export function stopMaintenanceView() {
    if (_intervalId) {
        clearInterval(_intervalId);
        _intervalId = null;
    }
}
