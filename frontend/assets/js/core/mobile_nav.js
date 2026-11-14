/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — frontend/assets/js/core/mobile_nav.js
 *
 * DC-EPMS-064: the shell was desktop-only (3 fixed columns, 280 px
 * nav + 320 px rail). On a phone (iPhone 16 / 17 Pro Max = 440 x 956
 * CSS px) the page laid out at ~960 px and was cropped. Below the
 * MOBILE_QUERY breakpoint app.css turns the nav into an off-canvas
 * drawer; this module only owns the open / closed state:
 *
 *   - the header button (#nav-toggle) opens / closes the drawer;
 *   - choosing a view, tapping the backdrop or pressing Escape closes it;
 *   - growing past the breakpoint (rotation, split view) closes it.
 *
 * State lives on .app-shell as the `nav-open` class plus
 * aria-expanded on the button. No layout is computed here.
 * ════════════════════════════════════════════════════════════════ */

export const MOBILE_QUERY = '(max-width: 900px)';
const OPEN_CLASS = 'nav-open';

function shell() { return document.querySelector('.app-shell'); }
function toggleBtn() { return document.getElementById('nav-toggle'); }

export function isNavOpen() {
    return shell()?.classList.contains(OPEN_CLASS) === true;
}

export function setNavOpen(open) {
    const s = shell();
    if (!s) return;
    s.classList.toggle(OPEN_CLASS, open);
    const btn = toggleBtn();
    if (btn) {
        btn.setAttribute('aria-expanded', open ? 'true' : 'false');
        btn.setAttribute('aria-label', open ? 'Close navigation' : 'Open navigation');
    }
    if (open) {
        const active = document.querySelector('.panel-nav .nav-item.active')
            || document.querySelector('.panel-nav .nav-item');
        active?.focus?.({ preventScroll: true });
    }
}

let _wired = false;
let _abort = null;

export function initMobileNav() {
    if (_wired) return;
    const btn = toggleBtn();
    const nav = document.querySelector('.panel-nav');
    if (!btn || !nav) return;
    _wired = true;
    _abort = new AbortController();
    const opts = { signal: _abort.signal };

    btn.addEventListener('click', () => setNavOpen(!isNavOpen()), opts);
    document.getElementById('nav-backdrop')
        ?.addEventListener('click', () => setNavOpen(false), opts);
    nav.addEventListener('click', (e) => {
        if (e.target.closest?.('.nav-item')) setNavOpen(false);
    }, opts);
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && isNavOpen()) {
            setNavOpen(false);
            btn.focus?.();
        }
    }, opts);
    const mq = window.matchMedia?.(MOBILE_QUERY);
    mq?.addEventListener?.('change', (ev) => { if (!ev.matches) setNavOpen(false); }, opts);

    // Nav items are divs: make them reachable and operable by keyboard
    // and assistive tech now that they can live in a drawer.
    nav.querySelectorAll('.nav-item').forEach((item) => {
        if (!item.hasAttribute('tabindex')) item.setAttribute('tabindex', '0');
        if (!item.hasAttribute('role')) item.setAttribute('role', 'button');
        item.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                item.click();
            }
        }, opts);
    });
}

export const __mobile_nav_test__ = {
    reset() { _abort?.abort(); _abort = null; _wired = false; },
};
