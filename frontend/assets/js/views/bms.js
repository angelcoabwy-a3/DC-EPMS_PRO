/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — views/bms.js
 * ROADMAP V11 T2.1 Vector 1 — BMS Connector view extracted from app.js.
 *
 * The BACnet/Modbus tag-namespace browser (Niagara/EBI/EcoStruxure
 * compatible), lifted out of the monolithic IIFE into a decoupled ES
 * module:
 *
 *   - registerRoute('bms', …) hands navigation to core/router.js.
 *   - the tag table, the RBAC-gated write modal (POST /api/bms/write,
 *     SME_L6 actor_role) and the NIST SP 800-82 audit modal are ported
 *     faithfully; every interpolated value is escapeHTML'd.
 *   - showBmsAudit() is re-exposed on window so the extracted
 *     views/copilot.js audit deep-link (which guards on
 *     `typeof window.showBmsAudit === 'function'`) keeps working.
 *
 * Test surface: __bms_test__ exposes the pure render helpers.
 * ════════════════════════════════════════════════════════════════ */

import { registerRoute } from '../core/router.js';
import { escapeHTML } from '../core/sanitize.js';

const $ = (id) => document.getElementById(id);

let _initialized = false;
let bmsCache = null;
let bmsCurrentCategory = '';
let bmsRefreshInterval = null;

// ─── Modal helpers ─────────────────────────────────────────────────
/** Close any open BMS modal. */
function closeBmsModals() {
    const writeModal = $('bms-write-modal');
    if (writeModal) {
        writeModal.hidden = true;
        writeModal.style.display = 'none';
    }
    // Audit modal is dynamic - destroy any open dynamic instance
    document.querySelectorAll('.bms-audit-modal-dynamic').forEach((el) => el.remove());
}

/** Bind click-away (clicking the modal backdrop closes it). */
function bindModalClickAway(modalEl) {
    if (!modalEl || modalEl._clickAwayBound) return;
    modalEl._clickAwayBound = true;
    modalEl.addEventListener('click', (ev) => {
        // Only close if the click target IS the backdrop (not the inner content)
        if (ev.target === modalEl) {
            modalEl.hidden = true;
        }
    });
}

// ─── Lifecycle / routing ───────────────────────────────────────────
async function renderBmsView() {
    // Bind action-bar buttons (idempotent; these are stable elements)
    const refreshBtn = $('bms-refresh-btn');
    if (refreshBtn && !refreshBtn._bound) {
        refreshBtn._bound = true;
        refreshBtn.addEventListener('click', () => fetchBmsTags(true));
    }

    const auditBtn = $('bms-audit-btn');
    if (auditBtn && !auditBtn._bound) {
        auditBtn._bound = true;
        auditBtn.addEventListener('click', showBmsAudit);
    }

    // Bind modal click-away (idempotent on each modal element)
    bindModalClickAway($('bms-write-modal'));
    // Audit modal manages its own click-away (it's dynamic)

    // Make sure write modal starts hidden when entering the view
    closeBmsModals();

    await fetchBmsTags(true);

    if (!bmsRefreshInterval) {
        bmsRefreshInterval = setInterval(() => {
            // Self-cancel when the view leaves the screen (T2.1: avoid an
            // orphaned poll once the IIFE no longer owns the lifecycle).
            const v = $('view-bms');
            if (v && !v.hasAttribute('hidden')) {
                fetchBmsTags(false);
            } else {
                clearInterval(bmsRefreshInterval);
                bmsRefreshInterval = null;
            }
        }, 10000);
    }
}

// ─── Data ──────────────────────────────────────────────────────────
async function fetchBmsTags(showLoading) {
    const tbody = $('bms-tbody');
    if (showLoading && tbody) {
        tbody.innerHTML = '<tr><td colspan="7" class="bms-loading">Loading tags…</td></tr>';
    }
    try {
        const url = '/api/bms/tags' + (bmsCurrentCategory ? '?category=' + bmsCurrentCategory : '');
        const resp = await fetch(url);
        if (!resp.ok) throw new Error('failed: ' + resp.status);
        bmsCache = await resp.json();
        renderBmsCategories(bmsCache.stats);
        renderBmsTable(bmsCache.tags);
        renderBmsStats(bmsCache.stats);
    } catch (e) {
        if (tbody) {
            tbody.innerHTML = '<tr><td colspan="7" class="bms-loading" style="color:var(--crit)">Failed: '
                + escapeHTML(e.message) + '</td></tr>';
        }
    }
}

function renderBmsCategories(stats) {
    const tabs = $('bms-tabs');
    if (!tabs) return;
    const cats = stats.categories || {};
    const counts = stats.by_category || {};

    // Re-render every time so counts stay live and active state syncs.
    let html = `<button class="bms-tab ${bmsCurrentCategory === '' ? 'active' : ''}" data-cat="">All (${stats.total_tags})</button>`;
    Object.entries(cats).forEach(([key, info]) => {
        const count = counts[key] || 0;
        const isActive = bmsCurrentCategory === key;
        html += `<button class="bms-tab ${isActive ? 'active' : ''}" data-cat="${escapeHTML(key)}">${info.icon || ''} ${escapeHTML(info.name)} (${count})</button>`;
    });
    tabs.innerHTML = html;

    // Bind click handlers fresh on each render
    tabs.querySelectorAll('.bms-tab').forEach((btn) => {
        btn.addEventListener('click', () => {
            bmsCurrentCategory = btn.dataset.cat;
            // Optimistic UI: highlight immediately, then fetch
            tabs.querySelectorAll('.bms-tab').forEach((b) => b.classList.remove('active'));
            btn.classList.add('active');
            fetchBmsTags(true);
        });
    });
}

function renderBmsStats(stats) {
    const el = $('bms-stats');
    if (!el) return;
    el.innerHTML = `
        <span class="bms-stat-pill">${stats.total_tags} tags</span>
        <span class="bms-stat-sep">·</span>
        <span class="bms-stat-pill">${stats.writable_tags} writable</span>
        <span class="bms-stat-sep">·</span>
        ${stats.alarm_count > 0 ? `<span class="bms-stat-pill alarm">${stats.alarm_count} ALARM</span>` : ''}
        ${stats.warning_count > 0 ? `<span class="bms-stat-pill warning">${stats.warning_count} warn</span>` : ''}
        ${stats.alarm_count === 0 && stats.warning_count === 0 ? '<span class="bms-stat-pill ok">All normal</span>' : ''}
    `;
}

function renderBmsTable(tags) {
    const tbody = $('bms-tbody');
    if (!tbody) return;
    if (tags.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="bms-loading">No tags in this category.</td></tr>';
        return;
    }
    tbody.innerHTML = tags.map((t) => {
        const valDisplay = formatBmsValue(t);
        const alarmCls = `alarm-${t.alarm_state}`;
        const writeBtn = t.writable
            ? `<button class="btn-bms-write" data-id="${escapeHTML(t.id)}">Write</button>`
            : '<span class="bms-readonly">RO</span>';
        return `<tr class="${alarmCls}">
            <td class="bms-tag-id">${escapeHTML(t.id)}</td>
            <td class="bms-tag-desc">${escapeHTML(t.description)}</td>
            <td><span class="bms-protocol bms-protocol-${escapeHTML(t.protocol.toLowerCase())}">${escapeHTML(t.protocol)}</span></td>
            <td class="bms-value">${valDisplay}</td>
            <td class="bms-units">${escapeHTML(t.units)}</td>
            <td><span class="bms-status ${alarmCls}">${escapeHTML(t.alarm_state)}</span></td>
            <td>${writeBtn}</td>
        </tr>`;
    }).join('');

    // Bind write buttons
    tbody.querySelectorAll('.btn-bms-write').forEach((btn) => {
        btn.addEventListener('click', () => showBmsWriteModal(btn.dataset.id));
    });
}

function formatBmsValue(t) {
    const v = t.current_value;
    if (v === null || v === undefined) return '<span class="bms-no-data">—</span>';
    if (typeof v === 'number') {
        return Number.isInteger(v)
            ? v.toLocaleString()
            : Number(v).toFixed(2);
    }
    if (typeof v === 'boolean') return v ? 'On' : 'Off';
    return escapeHTML(String(v));
}

// ─── Write modal ───────────────────────────────────────────────────
function showBmsWriteModal(tagId) {
    const tag = bmsCache.tags.find((t) => t.id === tagId);
    if (!tag) return;

    const modal = $('bms-write-modal');
    const titleEl = $('bms-write-title');
    const bodyEl = $('bms-write-body');
    if (!modal || !bodyEl) return;

    // BULLETPROOF close: use style.display directly + capture phase delegation.
    // .bms-modal CSS defines display:flex which beat the [hidden] attribute
    // on some browsers.
    const hideModal = () => {
        modal.hidden = true;
        modal.style.display = 'none';
        try { document.removeEventListener('click', writeDelegated, true); } catch (_) { /* noop */ }
        try { document.removeEventListener('keydown', writeEsc); } catch (_) { /* noop */ }
    };

    const closeBtn = $('bms-write-close');
    // Re-bind close button fresh every time (replace node to drop old listeners)
    if (closeBtn) {
        const fresh = closeBtn.cloneNode(true);
        closeBtn.parentNode.replaceChild(fresh, closeBtn);
        fresh.id = 'bms-write-close';
        fresh.type = 'button';
        // Direct onclick (capa 1)
        fresh.onclick = (ev) => {
            ev.preventDefault();
            ev.stopPropagation();
            hideModal();
        };
        // Capa 2: addEventListener
        fresh.addEventListener('click', (ev) => {
            ev.preventDefault();
            ev.stopPropagation();
            hideModal();
        });
    }

    // Capa 3: capture-phase delegation at document level
    const writeDelegated = (ev) => {
        const closeBtnNow = document.getElementById('bms-write-close');
        if (!closeBtnNow) return;
        if (ev.target === closeBtnNow || (closeBtnNow.contains && closeBtnNow.contains(ev.target))) {
            ev.preventDefault();
            ev.stopPropagation();
            hideModal();
        }
    };
    document.addEventListener('click', writeDelegated, true);

    // Esc handler
    const writeEsc = (ev) => {
        if (ev.key === 'Escape' && !modal.hidden) {
            ev.preventDefault();
            hideModal();
        }
    };
    document.addEventListener('keydown', writeEsc);

    if (titleEl) titleEl.textContent = `Write to ${tagId}`;

    let inputHtml;
    if (tag.enum_values && tag.enum_values.length > 0) {
        inputHtml = `<select id="bms-write-input" class="bms-write-field">
            ${tag.enum_values.map((v) => `<option value="${escapeHTML(v)}" ${v === tag.current_value ? 'selected' : ''}>${escapeHTML(v)}</option>`).join('')}
        </select>`;
    } else {
        inputHtml = `<input type="text" id="bms-write-input" class="bms-write-field"
            value="${tag.current_value !== null ? escapeHTML(String(tag.current_value)) : ''}">`;
    }

    const bandHtml = tag.alarm_band
        ? `<div class="bms-write-band">Alarm band: [${tag.alarm_band[0]}, ${tag.alarm_band[1]}] ${escapeHTML(tag.units)}</div>`
        : '';

    bodyEl.innerHTML = `
        <div class="bms-write-info">
            <div><strong>Description:</strong> ${escapeHTML(tag.description)}</div>
            <div><strong>Current value:</strong> ${formatBmsValue(tag)} ${escapeHTML(tag.units)}</div>
            <div><strong>Protocol:</strong> ${escapeHTML(tag.protocol)} (${escapeHTML(tag.object_type)})</div>
            ${bandHtml}
        </div>
        <div class="bms-write-form">
            <label>New value:</label>
            ${inputHtml}
            <div class="bms-write-warn">⚠ This write will be logged to the audit log per NIST SP 800-82 OT operations standard.</div>
            <div class="bms-write-actions">
                <button class="btn" id="bms-write-confirm">Confirm Write</button>
                <button class="btn btn-secondary" id="bms-write-cancel">Cancel</button>
            </div>
            <div id="bms-write-result"></div>
        </div>
    `;

    modal.hidden = false;
    modal.style.display = '';  // undo any previous display:none from hideModal()

    const confirmBtn = $('bms-write-confirm');
    if (confirmBtn) {
        confirmBtn.addEventListener('click', () => submitBmsWrite(tagId));
    }
    const cancelBtn = $('bms-write-cancel');
    if (cancelBtn) {
        cancelBtn.addEventListener('click', () => {
            hideModal();
        });
    }
}

async function submitBmsWrite(tagId) {
    const input = $('bms-write-input');
    const result = $('bms-write-result');
    if (!input) return;
    const value = input.value;

    if (result) result.innerHTML = '<span class="bms-write-loading">Writing…</span>';

    try {
        const resp = await fetch('/api/bms/write', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            // F3-2: backend RBAC gate - BMS write requires SME_L6. The legacy
            // BMS view has no role selector, so a gate-satisfying demo default
            // is sent (swap for a selector value when one is added).
            body: JSON.stringify({ tag_id: tagId, value: value, user: 'dashboard-operator', actor_role: 'SME_L6' }),
        });
        const data = await resp.json();
        if (!resp.ok) {
            throw new Error(data.detail || 'Write failed');
        }
        if (result) result.innerHTML = '<span class="bms-write-success">✓ ' + escapeHTML(data.message) + '</span>';
        // Refresh table after a beat
        setTimeout(() => {
            const m = $('bms-write-modal');
            if (m) {
                m.hidden = true;
                m.style.display = 'none';
            }
            fetchBmsTags(false);
        }, 1500);
    } catch (e) {
        if (result) result.innerHTML = '<span class="bms-write-fail">✗ ' + escapeHTML(e.message) + '</span>';
    }
}

// ─── Audit modal (NIST SP 800-82) ──────────────────────────────────
async function showBmsAudit() {
    // ═══════════════════════════════════════════════════
    //  v5.0.1 — Surgical fix for silent body-collapse bug
    //  ───────────────────────────────────────────────────
    //  Three issues fixed vs prior version:
    //
    //  1. Body collapsed to 0px in flex layout because it lacked
    //     `flex: 1 1 auto` + `min-height: 0` (without min-height: 0,
    //     a flex child with overflow:auto refuses to shrink below its
    //     content height — Mozilla devtools quirk well-documented).
    //
    //  2. The "Loading…" state never painted because we awaited fetch
    //     synchronously after appendChild — browser had no chance to
    //     repaint. Fix: yield to the event loop with double-rAF before
    //     starting the fetch, guaranteeing the loading state is visible.
    //
    //  3. Backend schema was bullet-proofed: any non-array `audit`,
    //     missing `total_entries`, or non-JSON response degrades to
    //     a clear error state instead of throwing silently.
    // ═══════════════════════════════════════════════════

    // 1. Nuke any existing dynamic modal (idempotent)
    document.querySelectorAll('.bms-audit-modal-dynamic').forEach((el) => el.remove());

    // 2. Build modal in detached form
    const overlay = document.createElement('div');
    overlay.className = 'bms-audit-modal-dynamic';
    overlay.style.cssText = `
        position: fixed; top: 0; left: 0; right: 0; bottom: 0;
        background: rgba(0,0,0,0.7); z-index: 999999;
        display: flex; align-items: center; justify-content: center;
        cursor: pointer;
    `;

    const panel = document.createElement('div');
    // CRITICAL: panel itself needs an explicit height for the flex child
    // (body) to know what to shrink to. max-height alone is not enough.
    panel.style.cssText = `
        background: #14181D; border: 1px solid #00B8D4; border-radius: 6px;
        width: 800px; max-width: 95vw;
        height: 85vh; max-height: 85vh;
        display: flex; flex-direction: column;
        box-shadow: 0 4px 32px rgba(0,0,0,0.7);
        cursor: auto;
        overflow: hidden;
    `;

    const header = document.createElement('div');
    // flex-shrink: 0 prevents header from being squeezed when body grows
    header.style.cssText = `
        display: flex; justify-content: space-between; align-items: center;
        padding: 12px 16px; border-bottom: 1px solid #2A3038;
        color: #E8EAED; font-weight: 600;
        flex: 0 0 auto;
    `;
    header.innerHTML = '<span>Write Audit Log (NIST SP 800-82)</span>';

    const closeBtn = document.createElement('button');
    closeBtn.textContent = '×';
    closeBtn.id = 'bms-audit-dynamic-close';
    closeBtn.type = 'button';
    closeBtn.style.cssText = `
        background: transparent; border: none; color: #9AA0A6;
        font-size: 28px; cursor: pointer; padding: 0 12px;
        line-height: 1; user-select: none;
        pointer-events: auto;
        min-width: 36px; min-height: 36px;
        display: flex; align-items: center; justify-content: center;
        border-radius: 4px;
    `;
    closeBtn.title = 'Close (Esc)';
    closeBtn.onmouseenter = () => { closeBtn.style.background = 'rgba(229,57,53,0.15)'; closeBtn.style.color = '#E53935'; };
    closeBtn.onmouseleave = () => { closeBtn.style.background = 'transparent'; closeBtn.style.color = '#9AA0A6'; };
    header.appendChild(closeBtn);
    panel.appendChild(header);

    const body = document.createElement('div');
    // CRITICAL FIX: flex: 1 1 auto + min-height: 0 makes the body
    // claim remaining space AND respect its overflow-y: auto.
    body.style.cssText = `
        padding: 16px;
        overflow-y: auto;
        color: #E8EAED;
        flex: 1 1 auto;
        min-height: 0;
    `;
    body.innerHTML = `
        <div style="text-align:center;color:#9AA0A6;padding:40px 20px">
            <div style="font-size:24px;margin-bottom:10px">⏳</div>
            <div style="font-size:12px">Loading audit log…</div>
        </div>
    `;
    panel.appendChild(body);
    overlay.appendChild(panel);

    // 3. Close function — single source of truth
    const closeModal = () => {
        try { document.removeEventListener('keydown', escHandler); } catch (_) { /* noop */ }
        try { document.removeEventListener('click', delegatedClickHandler, true); } catch (_) { /* noop */ }
        if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
    };

    // 4. SINGLE delegated click handler at document level using CAPTURE phase.
    const delegatedClickHandler = (ev) => {
        // 1) Click on the X button (or any descendant of it)
        if (ev.target === closeBtn || (closeBtn.contains && closeBtn.contains(ev.target))) {
            ev.preventDefault();
            ev.stopPropagation();
            closeModal();
            return;
        }
        // 2) Click on the overlay backdrop (outside the panel)
        if (ev.target === overlay) {
            ev.preventDefault();
            closeModal();
        }
    };
    // Capture phase = true → runs before bubble phase, beats any stopPropagation
    document.addEventListener('click', delegatedClickHandler, true);

    // Belt-and-suspenders: also wire the closeBtn directly with onclick.
    closeBtn.onclick = (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        closeModal();
    };

    const escHandler = (ev) => {
        if (ev.key === 'Escape') {
            ev.preventDefault();
            closeModal();
        }
    };
    document.addEventListener('keydown', escHandler);

    // 5. Insert into <body>
    document.body.appendChild(overlay);

    // 6. CRITICAL FIX: yield to browser so it paints "Loading…" BEFORE
    //    we start the network fetch (double-rAF guarantees one paint cycle).
    await new Promise((resolve) =>
        requestAnimationFrame(() =>
            requestAnimationFrame(resolve),
        ),
    );

    // 7. Now fetch with hardened parsing
    try {
        const resp = await fetch('/api/bms/audit?limit=100');
        if (!resp.ok) {
            throw new Error('HTTP ' + resp.status + ' ' + (resp.statusText || ''));
        }

        // Defensive JSON parsing — server might return HTML on error
        let d;
        try {
            d = await resp.json();
        } catch (parseErr) {
            throw new Error('Invalid JSON response (likely server error page): ' + parseErr.message);
        }

        // Schema bullet-proofing: handle three possible response shapes
        //   A) {audit: [...], total_entries: N}  ← expected
        //   B) {audit: [...]}                     ← legacy without count
        //   C) [...]                              ← raw array
        let entries;
        let total;
        if (Array.isArray(d)) {
            entries = d;
            total = d.length;
        } else if (d && typeof d === 'object') {
            entries = Array.isArray(d.audit) ? d.audit : [];
            total = (typeof d.total_entries === 'number') ? d.total_entries : entries.length;
        } else {
            entries = [];
            total = 0;
        }

        if (entries.length === 0) {
            body.innerHTML = `
                <div style="text-align:center;padding:40px 20px;color:#9AA0A6">
                    <div style="font-size:32px;margin-bottom:10px">📋</div>
                    <div style="font-size:13px;color:#E8EAED;margin-bottom:6px">
                        No audit entries yet
                    </div>
                    <div style="font-size:11px;color:#9AA0A6;line-height:1.6">
                        The NIST SP 800-82 audit log is empty.<br>
                        Issue a Write to a tag to create your first entry.
                    </div>
                    <button id="bms-audit-empty-close-btn"
                            style="margin-top:16px;padding:8px 18px;
                                   background:#00B8D4;color:#0B0D10;
                                   border:none;border-radius:3px;
                                   cursor:pointer;font-weight:600;
                                   font-family:inherit;">
                        Close
                    </button>
                </div>
            `;
            const innerClose = document.getElementById('bms-audit-empty-close-btn');
            if (innerClose) innerClose.addEventListener('click', closeModal);
            return;
        }

        // Render the audit table — each row is bullet-proofed against
        // missing fields with default values.
        const safeRow = (e) => {
            const ts = (typeof e.ts === 'number') ? new Date(e.ts * 1000).toLocaleString() : '—';
            const user = String(e.user || 'unknown');
            const tagId = String(e.tag_id || '—');
            const oldVal = (e.old_value === undefined || e.old_value === null) ? '—' : String(e.old_value);
            const newVal = (e.new_value === undefined || e.new_value === null) ? '—' : String(e.new_value);
            const success = (e.success === undefined) ? true : Boolean(e.success);
            const errMsg = String(e.error || '');
            return { ts, user, tagId, oldVal, newVal, success, errMsg };
        };

        body.innerHTML = `
            <div style="color:#9AA0A6;font-size:11px;margin-bottom:10px;font-family:monospace">
                Showing ${entries.length} of ${total} entries · newest first
            </div>
            <table style="width:100%;border-collapse:collapse;font-size:11px">
                <thead>
                    <tr style="color:#6C737D;font-size:10px;text-transform:uppercase">
                        <th style="padding:6px 10px;text-align:left;border-bottom:1px solid #2A3038;position:sticky;top:0;background:#14181D">Timestamp</th>
                        <th style="padding:6px 10px;text-align:left;border-bottom:1px solid #2A3038;position:sticky;top:0;background:#14181D">User</th>
                        <th style="padding:6px 10px;text-align:left;border-bottom:1px solid #2A3038;position:sticky;top:0;background:#14181D">Tag</th>
                        <th style="padding:6px 10px;text-align:left;border-bottom:1px solid #2A3038;position:sticky;top:0;background:#14181D">Old → New</th>
                        <th style="padding:6px 10px;text-align:left;border-bottom:1px solid #2A3038;position:sticky;top:0;background:#14181D">Status</th>
                    </tr>
                </thead>
                <tbody>
                    ${entries.map((e) => {
                        const r = safeRow(e);
                        return `
                            <tr style="${r.success ? '' : 'background:rgba(229,57,53,0.06)'}">
                                <td style="padding:6px 10px;font-family:monospace;color:#6C737D;font-size:10px;border-bottom:1px solid rgba(42,48,56,0.5)">${escapeHTML(r.ts)}</td>
                                <td style="padding:6px 10px;border-bottom:1px solid rgba(42,48,56,0.5)">${escapeHTML(r.user)}</td>
                                <td style="padding:6px 10px;font-family:monospace;color:#00B8D4;border-bottom:1px solid rgba(42,48,56,0.5)">${escapeHTML(r.tagId)}</td>
                                <td style="padding:6px 10px;border-bottom:1px solid rgba(42,48,56,0.5)">${escapeHTML(r.oldVal)} → ${escapeHTML(r.newVal)}</td>
                                <td style="padding:6px 10px;border-bottom:1px solid rgba(42,48,56,0.5)">
                                    ${r.success
                                        ? '<span style="color:#4CAF50;font-size:10px">✓ OK</span>'
                                        : '<span style="color:#E53935;font-size:10px">✗ ' + escapeHTML(r.errMsg) + '</span>'}
                                </td>
                            </tr>
                        `;
                    }).join('')}
                </tbody>
            </table>
        `;
    } catch (e) {
        body.innerHTML = `
            <div style="padding:20px;color:#E53935">
                <div style="margin-bottom:10px;font-weight:600">⚠ Failed to load audit log</div>
                <div style="font-size:11px;color:#9AA0A6;font-family:monospace;
                            background:rgba(0,0,0,0.3);padding:10px;border-radius:3px;
                            word-break:break-word">${escapeHTML(e.message || String(e))}</div>
                <div style="font-size:11px;color:#9AA0A6;margin-top:14px;line-height:1.6">
                    Verify backend is running on <code>${escapeHTML(window.location.origin)}</code> and that
                    <code>/api/bms/audit</code> endpoint is reachable.
                </div>
                <button id="bms-audit-err-close-btn"
                        style="margin-top:16px;padding:8px 18px;
                               background:#2A3038;color:#E8EAED;
                               border:none;border-radius:3px;
                               cursor:pointer;font-family:inherit;">
                    Close
                </button>
            </div>
        `;
        const errClose = document.getElementById('bms-audit-err-close-btn');
        if (errClose) errClose.addEventListener('click', closeModal);
    }
}

/** Public entry — called once from main.js at bootstrap. */
export function initBmsView() {
    if (_initialized) return;
    if (!$('view-bms')) {
        console.warn('[bms] #view-bms not in DOM; view disabled.');
        return;
    }
    registerRoute('bms', { viewId: 'view-bms', activate: renderBmsView });

    // T2.1 Vector 1 — re-expose showBmsAudit on window so the extracted
    // views/copilot.js audit deep-link (which guards on
    // `typeof window.showBmsAudit === 'function'`) keeps working after
    // this view leaves the IIFE.
    window.showBmsAudit = showBmsAudit;

    // Global ESC handler for the BMS write modal (bind once).
    if (!window._bmsEscBound) {
        window._bmsEscBound = true;
        document.addEventListener('keydown', (ev) => {
            if (ev.key === 'Escape') {
                const writeModal = document.getElementById('bms-write-modal');
                if (writeModal && !writeModal.hidden) writeModal.hidden = true;
                // Audit modal handles its own Esc internally (in showBmsAudit)
            }
        });
    }

    _initialized = true;
    console.log('[bms] view ready (BMS Connector — T2.1 Vector 1 ES module)');
}

// ─── Test surface ──────────────────────────────────────────────────
export const __bms_test__ = {
    formatBmsValue,
    renderBmsTable,
    renderBmsStats,
    renderBmsCategories,
    showBmsWriteModal,
    initBmsView,
    setCache: (c) => { bmsCache = c; },
    reset: () => {
        _initialized = false;
        bmsCache = null;
        bmsCurrentCategory = '';
        if (bmsRefreshInterval) { clearInterval(bmsRefreshInterval); bmsRefreshInterval = null; }
        document.querySelectorAll('.bms-audit-modal-dynamic').forEach((el) => el.remove());
    },
};
