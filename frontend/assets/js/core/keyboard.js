/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — core/keyboard.js
 *
 * Tier C / C3: Keyboard shortcuts + help modal.
 *
 * Conventions (operator-grade, vim-influenced):
 *   ?              Show shortcuts help modal
 *   Esc            Close help modal / any open modal
 *   1..9           Navigate to nav-item N
 *   g <letter>     Two-stroke navigate:
 *                    g o   overview
 *                    g m   maintenance
 *                    g t   tech-assist
 *                    g a   multi-agent (a for agent)
 *                    g l   loto auditor
 *                    g s   site topology
 *                    g i   incidents
 *                    g p   power & ups
 *                    g c   cooling
 *   /              Focus the visible search/query input on the
 *                  currently active view (textarea or text input).
 *   m              Toggle sound (mute/unmute)
 *
 * Discipline:
 *   - Shortcuts disabled while typing in a textarea/input/select.
 *   - "g" is a two-stroke leader: pressing g alone shows a tiny
 *     hint at the bottom right; second key within 1.2s triggers nav.
 *   - Shortcuts that trigger nav use the existing nav-item click
 *     so router delegation (LOTO pattern) fires correctly.
 * ════════════════════════════════════════════════════════════════ */

import { toggleSound } from './sound.js';

const NUMERIC_NAV_LIMIT = 9;
const G_LEADER_TIMEOUT_MS = 1200;

let _gLeaderArmed = false;
let _gLeaderTimer = null;
let _gHintEl = null;
let _helpModalEl = null;

// ─── Two-stroke "g" leader hint ──────────────────────────────────
function _showGHint() {
    if (!_gHintEl) {
        _gHintEl = document.createElement('div');
        _gHintEl.id = 'kbd-g-hint';
        _gHintEl.className = 'kbd-g-hint';
        _gHintEl.innerHTML = '<kbd>g</kbd> <span>— go to: <kbd>o</kbd>verview · <kbd>m</kbd>aintenance · <kbd>t</kbd>ech · <kbd>a</kbd>gent · <kbd>l</kbd>oto · <kbd>s</kbd>ite · <kbd>i</kbd>ncidents · <kbd>p</kbd>ower · <kbd>c</kbd>ooling</span>';
        document.body.appendChild(_gHintEl);
    }
    _gHintEl.classList.add('kbd-g-hint-visible');
}
function _hideGHint() {
    _gHintEl?.classList.remove('kbd-g-hint-visible');
}
function _disarmGLeader() {
    _gLeaderArmed = false;
    if (_gLeaderTimer) { clearTimeout(_gLeaderTimer); _gLeaderTimer = null; }
    _hideGHint();
}

// ─── Navigate via existing nav-item click (so router runs) ───────
function _navByRoute(route) {
    const navItem = document.querySelector(`.nav-item[data-route="${route}"]`);
    if (!navItem) {
        console.warn(`[keyboard] no nav-item for route='${route}'`);
        return false;
    }
    navItem.click();
    return true;
}

const G_LETTER_MAP = {
    o: 'overview',
    m: 'maintenance',
    t: 'tech-assist',
    a: 'multi-agent',
    l: 'loto',
    s: 'site_topology',
    i: 'incidents',
    p: 'power',
    c: 'cooling',
};

// ─── Shortcut tables (also used by help modal) ───────────────────
const SHORTCUTS = [
    { group: 'Help & global', items: [
        { keys: ['?'],   desc: 'Show this shortcuts panel' },
        { keys: ['Esc'], desc: 'Close any open modal' },
        { keys: ['m'],   desc: 'Toggle sound (mute / unmute)' },
        { keys: ['/'],   desc: 'Focus the active search / query input' },
    ]},
    { group: 'Direct nav (1-9)', items: [
        { keys: ['1'], desc: 'Overview' },
        { keys: ['2'], desc: 'Scenarios' },
        { keys: ['3'], desc: 'Power & UPS' },
        { keys: ['4'], desc: 'Cooling (DLC)' },
        { keys: ['5'], desc: 'Incidents' },
        { keys: ['6'], desc: 'MOPs & EOPs' },
        { keys: ['7'], desc: 'BMS Connector' },
        { keys: ['8'], desc: 'Co-Pilot' },
        { keys: ['9'], desc: 'Site Topology' },
    ]},
    { group: 'Vim-style (g + letter)', items: [
        { keys: ['g', 'o'], desc: 'Go &rarr; Overview' },
        { keys: ['g', 'm'], desc: 'Go &rarr; Maintenance' },
        { keys: ['g', 't'], desc: 'Go &rarr; Tech Assist' },
        { keys: ['g', 'a'], desc: 'Go &rarr; Multi-Agent (Agent)' },
        { keys: ['g', 'l'], desc: 'Go &rarr; LOTO Auditor' },
        { keys: ['g', 's'], desc: 'Go &rarr; Site Topology' },
        { keys: ['g', 'i'], desc: 'Go &rarr; Incidents' },
        { keys: ['g', 'p'], desc: 'Go &rarr; Power & UPS' },
        { keys: ['g', 'c'], desc: 'Go &rarr; Cooling' },
    ]},
];

// ─── Help modal ──────────────────────────────────────────────────
function _ensureHelpModal() {
    if (_helpModalEl) return _helpModalEl;
    const overlay = document.createElement('div');
    overlay.className = 'kbd-help-overlay';
    overlay.id = 'kbd-help-overlay';
    overlay.setAttribute('hidden', '');
    overlay.innerHTML = `
        <div class="kbd-help-modal" role="dialog" aria-labelledby="kbd-help-title">
            <div class="kbd-help-header">
                <div class="kbd-help-title" id="kbd-help-title">Keyboard shortcuts</div>
                <button class="m-modal-close-x" id="kbd-help-close" aria-label="Close" type="button">&times;</button>
            </div>
            <div class="kbd-help-body">
                ${SHORTCUTS.map(grp => `
                    <div class="kbd-help-group">
                        <div class="kbd-help-group-title">${grp.group}</div>
                        <table class="kbd-help-table">
                            ${grp.items.map(it => `
                                <tr>
                                    <td class="kbd-help-keys">
                                        ${it.keys.map(k => `<kbd>${k}</kbd>`).join('<span class="kbd-then"> &rarr; </span>')}
                                    </td>
                                    <td class="kbd-help-desc">${it.desc}</td>
                                </tr>
                            `).join('')}
                        </table>
                    </div>
                `).join('')}
                <div class="kbd-help-footer">
                    Shortcuts disabled while typing in a textarea or input.
                    Press <kbd>Esc</kbd> or click outside to close.
                </div>
            </div>
        </div>`;
    document.body.appendChild(overlay);
    _helpModalEl = overlay;
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) _closeHelp();
    });
    document.getElementById('kbd-help-close')?.addEventListener('click', _closeHelp);
    return overlay;
}
function _openHelp() {
    _ensureHelpModal().removeAttribute('hidden');
}
function _closeHelp() {
    _ensureHelpModal().setAttribute('hidden', '');
}
function _isHelpOpen() {
    return _helpModalEl && !_helpModalEl.hasAttribute('hidden');
}

// ─── Helpers ─────────────────────────────────────────────────────
function _isTypingTarget(target) {
    if (!target) return false;
    const tag = (target.tagName || '').toUpperCase();
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
    return target.isContentEditable === true;
}

function _focusActiveQuery() {
    // Prefer textareas inside the currently visible .view; fall back to inputs.
    const visible = document.querySelector('.view:not([hidden])');
    if (!visible) return;
    const target = visible.querySelector('textarea, input[type="text"], input[type="search"]');
    if (target) { target.focus(); target.select?.(); }
}

// ─── Direct numeric nav ──────────────────────────────────────────
function _navByOrdinal(n) {
    const navItems = document.querySelectorAll('.nav-item[data-route]');
    const idx = n - 1;
    if (idx < 0 || idx >= navItems.length) return;
    navItems[idx].click();
}

// ─── Main key handler ────────────────────────────────────────────
function _onKeydown(e) {
    // Esc always closes help (works even while typing)
    if (e.key === 'Escape') {
        if (_isHelpOpen()) { _closeHelp(); e.preventDefault(); return; }
        // Let other modals handle their own Esc.
        return;
    }

    // Help modal: only Esc inside; no other shortcuts trigger
    if (_isHelpOpen()) return;

    // Suppress shortcuts while typing
    if (_isTypingTarget(e.target)) return;

    // Modifier keys (Ctrl/Cmd/Alt) are reserved for browser shortcuts —
    // we only handle bare keys.
    if (e.ctrlKey || e.metaKey || e.altKey) return;

    const k = e.key;

    if (_gLeaderArmed) {
        const route = G_LETTER_MAP[k.toLowerCase()];
        _disarmGLeader();
        if (route) {
            _navByRoute(route);
            e.preventDefault();
        }
        return;
    }

    if (k === '?') {
        _openHelp();
        e.preventDefault();
        return;
    }

    if (k === 'g' || k === 'G') {
        _gLeaderArmed = true;
        _showGHint();
        _gLeaderTimer = setTimeout(_disarmGLeader, G_LEADER_TIMEOUT_MS);
        e.preventDefault();
        return;
    }

    if (k === 'm' || k === 'M') {
        toggleSound();
        e.preventDefault();
        return;
    }

    if (k === '/') {
        _focusActiveQuery();
        e.preventDefault();
        return;
    }

    // Numeric direct nav (1-9)
    if (k >= '1' && k <= String(NUMERIC_NAV_LIMIT)) {
        _navByOrdinal(parseInt(k, 10));
        e.preventDefault();
        return;
    }
}

// ─── Public init ────────────────────────────────────────────────
export function initKeyboard() {
    document.addEventListener('keydown', _onKeydown);
    document.getElementById('epms-shortcuts-toggle')
        ?.addEventListener('click', _openHelp);
    console.log('[keyboard] ready (? for shortcuts)');
}
