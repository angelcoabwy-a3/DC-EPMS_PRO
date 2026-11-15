/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — frontend/assets/js/core/plant_client.js
 *
 * T2: POST helper for the simulated plant (devices, alarms, training)
 * used from the Power view. Same contract as views/device_control.js:
 * session token from core/auth.js; the legacy role fields only count
 * on the server when no token exists and the session gate is off.
 * Returns { ok, data } or { ok: false, status, detail } — never throws.
 * ════════════════════════════════════════════════════════════════ */

import { getAuthHeader } from './auth.js';

export async function plantPost(url, body = {}) {
    let res;
    try {
        res = await fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: Object.assign({ 'Content-Type': 'application/json' }, getAuthHeader()),
            body: JSON.stringify(Object.assign({ actor_role: 'SME_L6', user: 'dashboard-operator' }, body)),
        });
    } catch (_e) {
        return { ok: false, status: 0, detail: 'Server unreachable.' };
    }
    let data = null;
    try { data = await res.json(); } catch (_e) { data = null; }
    if (!res.ok) {
        const detail = data && typeof data.detail === 'string' ? data.detail : `HTTP ${res.status}`;
        return { ok: false, status: res.status, detail };
    }
    return { ok: true, status: res.status, data: data || {} };
}

export async function plantGet(url) {
    let res;
    try {
        res = await fetch(url, { credentials: 'same-origin', headers: getAuthHeader() });
    } catch (_e) {
        return { ok: false, status: 0, detail: 'Server unreachable.' };
    }
    let data = null;
    try { data = await res.json(); } catch (_e) { data = null; }
    if (!res.ok) {
        const detail = data && typeof data.detail === 'string' ? data.detail : `HTTP ${res.status}`;
        return { ok: false, status: res.status, detail };
    }
    return { ok: true, status: res.status, data: data || {} };
}
