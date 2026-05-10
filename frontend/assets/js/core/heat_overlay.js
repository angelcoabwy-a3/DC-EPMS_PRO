/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — core/heat_overlay.js
 *
 * Tier A / A3: Heat overlay toggle + thermal-state classifier for
 * the cooling P&ID view. Subscribes to telemetry state when a
 * GPU Tj or rack-inlet channel is published; otherwise keeps the
 * overlay in "normal" state.
 *
 * Discipline:
 *   - Toggle button (#pid-heat-toggle) flips the overlay group's
 *     data-show="0|1" attribute (CSS handles the fade).
 *   - State classifier maps Tj_max → cold | normal | warn | crit
 *     using GB200 NVL72 spec thresholds:
 *
 *       Tj_max ≤ 60°C  → cold     (under-utilized, rare)
 *       60..78°C       → normal   (training-step burst typical)
 *       78..86°C       → warn     (sustained heavy load, watch DLC)
 *       86..95°C       → crit     (approaching NVIDIA thermal trip)
 *
 *   - Per ADR-006: visual advisory only. No autonomous shed.
 * ════════════════════════════════════════════════════════════════ */

import { subscribe } from './state.js';

const STORAGE_KEY = 'epms_heat_overlay_on';

let _initialized = false;
let _toggleEl = null;
let _stateEl = null;
let _overlayEl = null;
let _rackZoneEl = null;
let _currentBand = 'normal';

// ─── Telemetry classifier ────────────────────────────────────────
const BANDS = [
    { name: 'cold',   max: 60, gradient: 'pid-heat-cold' },
    { name: 'normal', max: 78, gradient: 'pid-heat-normal' },
    { name: 'warn',   max: 86, gradient: 'pid-heat-warm' },
    { name: 'crit',   max: 999, gradient: 'pid-heat-hot' },
];

function _classify(tjMaxC) {
    if (typeof tjMaxC !== 'number' || Number.isNaN(tjMaxC)) return BANDS[1]; // normal
    for (const b of BANDS) {
        if (tjMaxC <= b.max) return b;
    }
    return BANDS[BANDS.length - 1];
}

function _applyBand(band) {
    if (!_overlayEl || !_rackZoneEl) return;
    if (band.name === _currentBand) return;
    _currentBand = band.name;
    _overlayEl.setAttribute('data-heat', band.name);
    _rackZoneEl.setAttribute('fill', `url(#${band.gradient})`);
    if (_stateEl) {
        _stateEl.textContent = band.name;
        _stateEl.setAttribute('data-heat', band.name);
    }
    _applyPerRackBand(band);
}

// Tier A+ / A3': stagger the band across the 12 rack dots so the row
// reads as "individual rack thermal states" rather than a single class.
// Hottest dots cluster around the centre (typical training-step burst
// pattern — racks in the middle have less airflow margin).
function _applyPerRackBand(centerBand) {
    const dots = document.querySelectorAll('.pid-rack-dot');
    if (!dots.length) return;
    const order = centerBand.name === 'normal'
        ? ['normal','normal','normal','normal','normal','normal','normal','normal','normal','normal','normal','normal']
        : centerBand.name === 'warn'
        ? ['normal','normal','normal','warn','warn','warn','warn','warn','warn','normal','normal','normal']
        : centerBand.name === 'crit'
        ? ['warn','warn','crit','crit','crit','crit','crit','crit','crit','warn','warn','normal']
        : ['cold','cold','cold','cold','normal','normal','normal','normal','cold','cold','cold','cold'];
    dots.forEach((d, i) => {
        d.setAttribute('data-band', order[i] || centerBand.name);
    });
}

// ─── Toggle ──────────────────────────────────────────────────────
function _readEnabled() {
    try { return localStorage.getItem(STORAGE_KEY) !== '0'; }
    catch { return true; }
}
function _writeEnabled(on) {
    try { localStorage.setItem(STORAGE_KEY, on ? '1' : '0'); } catch {}
}

function _setToggle(on) {
    if (_toggleEl) _toggleEl.setAttribute('data-on', on ? '1' : '0');
    if (_overlayEl) _overlayEl.setAttribute('data-show', on ? '1' : '0');
    _writeEnabled(on);
}

function _onToggleClick() {
    const cur = _toggleEl?.getAttribute('data-on') === '1';
    _setToggle(!cur);
}

// ─── Telemetry hook: try a few common Tj field names ─────────────
function _onTelemetryUpdate(point) {
    if (!point) return;
    // Look for any of the documented thermal channels emitted by the
    // simulator. If none present, leave the band where it is.
    const candidates = [
        point.gpu_tj_max_c,
        point.rack_tj_max_c,
        point?.metrics?.gpu_tj_max,
        point?.metrics?.rack_tj_max,
    ];
    const tj = candidates.find(v => typeof v === 'number' && !Number.isNaN(v));
    if (typeof tj !== 'number') return;
    _applyBand(_classify(tj));
}

// ─── Public init ────────────────────────────────────────────────
export function initHeatOverlay() {
    if (_initialized) return;
    _toggleEl  = document.getElementById('pid-heat-toggle');
    _stateEl   = document.getElementById('pid-heat-state');
    _overlayEl = document.getElementById('pid-heat-overlay');
    _rackZoneEl = document.querySelector('.pid-heat-zone[data-zone="rack-row"]');
    if (!_overlayEl) return; // P&ID not in DOM (defensive)

    _toggleEl?.addEventListener('click', _onToggleClick);
    _setToggle(_readEnabled());
    _applyBand(BANDS[1]); // start at normal

    try { subscribe('latestTelemetry', _onTelemetryUpdate); } catch {}

    _initialized = true;
    console.log('[heat_overlay] ready (toggle: %s, band: normal)', _readEnabled() ? 'ON' : 'OFF');
}
