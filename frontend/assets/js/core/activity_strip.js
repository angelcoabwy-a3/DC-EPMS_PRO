/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — core/activity_strip.js
 *
 * Telemetry Activity Strip — global situational awareness band.
 *
 * Layout (between header and main grid):
 *
 *   Last update | Messages | Schema | Lag | Anomalies (60m) | Reconnects
 *
 * Drives 6 fields from the reactive store (state.js). Subscribes to
 * each relevant key independently so partial updates do not trigger
 * full strip re-render. A 1s tick keeps "Last update" relative time
 * progressing even when no new SSE message arrives.
 *
 * Field semantics:
 *   Last update  - ms since last SSE message (any payload, even empty).
 *   Messages     - cumulative count of SSE messages this session.
 *   Schema       - active SSE payload schema. Today: legacy_kpi.
 *                  When Sprint 5 backend C2 lands and emits
 *                  channel_innovations, this flips automatically and
 *                  visually highlights (neon-cyan, bold).
 *   Lag          - server-to-client delay in ms (Date.now() vs data.ts).
 *                  Severity color: < 500ms low, < 2000ms med, >= 2000ms high.
 *   Anomalies    - count of channels with is_anomalous=true in last 60min.
 *                  Today: 0 (no channel_innovations yet).
 *   Reconnects   - cumulative SSE reconnect attempts this session.
 *                  Non-zero indicates network instability.
 *
 * Forward compatibility: when channel_innovations arrives, anomaly
 * counting will be added here (subscribe to 'channels' key, count
 * is_anomalous flags within rolling 60min window).
 * ════════════════════════════════════════════════════════════════ */

import { subscribe, getState } from './state.js';

const REL_TIME_TICK_MS = 1000;
const LAG_THRESHOLDS_MS = Object.freeze({ med: 500, high: 2000 });

let _strip = null;
let _intervalId = null;
let _fields = {};

function _formatRelTime(ms) {
    if (ms < 1500) return 'just now';
    if (ms < 60_000) return `${Math.floor(ms / 1000)}s ago`;
    const m = Math.floor(ms / 60_000);
    return `${m}m ago`;
}

function _renderLastUpdate() {
    if (!_fields.lastUpdate) return;
    const lastMs = getState('lastTelemetryAtMs') || 0;
    if (lastMs === 0) {
        _fields.lastUpdate.textContent = '—';
        return;
    }
    _fields.lastUpdate.textContent = _formatRelTime(performance.now() - lastMs);
}

function _renderMessageCount() {
    if (!_fields.messageCount) return;
    const n = getState('messageCount') || 0;
    _fields.messageCount.textContent = n.toLocaleString();
}

function _renderSchema() {
    if (!_fields.schema) return;
    const s = getState('schemaVersion');
    _fields.schema.textContent = s || '—';
    _fields.schema.dataset.value = s || 'unknown';
}

function _renderLag() {
    if (!_fields.lag) return;
    const lag = getState('serverClientLagMs');
    if (lag === null || lag === undefined) {
        _fields.lag.textContent = '—';
        delete _fields.lag.dataset.severity;
        return;
    }
    const lagInt = Math.round(lag);
    _fields.lag.textContent = `${lagInt}ms`;
    _fields.lag.dataset.severity =
        lag >= LAG_THRESHOLDS_MS.high ? 'high'
        : lag >= LAG_THRESHOLDS_MS.med ? 'med'
        : 'low';
}

function _renderAnomalies() {
    if (!_fields.anomalies) return;
    const n = getState('anomalyCount60min') || 0;
    _fields.anomalies.textContent = n.toString();
    _fields.anomalies.dataset.severity = n > 0 ? 'high' : 'low';
}

function _renderReconnects() {
    if (!_fields.reconnects) return;
    const n = getState('reconnectCount') || 0;
    _fields.reconnects.textContent = n.toString();
    _fields.reconnects.dataset.severity = n > 0 ? 'med' : 'low';
}

export function initActivityStrip({ stripId = 'activity-strip' } = {}) {
    _strip = document.getElementById(stripId);
    if (!_strip) {
        console.warn(`[activity_strip] #${stripId} not found in DOM; strip disabled.`);
        return;
    }
    _fields = {
        lastUpdate:   _strip.querySelector('[data-field="last-update"]'),
        messageCount: _strip.querySelector('[data-field="message-count"]'),
        schema:       _strip.querySelector('[data-field="schema"]'),
        lag:          _strip.querySelector('[data-field="lag"]'),
        anomalies:    _strip.querySelector('[data-field="anomalies"]'),
        reconnects:   _strip.querySelector('[data-field="reconnects"]'),
    };

    subscribe('lastTelemetryAtMs',   _renderLastUpdate);
    subscribe('messageCount',        _renderMessageCount);
    subscribe('schemaVersion',       _renderSchema);
    subscribe('serverClientLagMs',   _renderLag);
    subscribe('anomalyCount60min',   _renderAnomalies);
    subscribe('reconnectCount',      _renderReconnects);

    if (_intervalId) clearInterval(_intervalId);
    _intervalId = setInterval(_renderLastUpdate, REL_TIME_TICK_MS);

    // initial paint
    _renderLastUpdate();
    _renderMessageCount();
    _renderSchema();
    _renderLag();
    _renderAnomalies();
    _renderReconnects();
}

export function stopActivityStrip() {
    if (_intervalId) {
        clearInterval(_intervalId);
        _intervalId = null;
    }
}
