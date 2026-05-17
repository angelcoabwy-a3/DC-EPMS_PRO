/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — core/focus_trap.js
 *
 * T2.5 Accessibility — Bite A11y-1, Violation #5.
 *
 * Minimal modal focus management for WCAG 2.1:
 *   - 2.4.3 Focus Order (A): focus moves into the dialog on open and
 *     is constrained to it (Tab / Shift+Tab cycle within).
 *   - 4.1.2 Name, Role, Value (A): pairs with role="dialog" +
 *     aria-modal="true" on the dialog element.
 *   - On release, focus returns to the element that held it before the
 *     dialog opened (the trigger), so keyboard context is never lost.
 *
 * No framework, no dependency — pure DOM. One export: trapFocus().
 * ════════════════════════════════════════════════════════════════ */

// Elements that can take keyboard focus inside a dialog. The :not(...)
// and tabindex guards keep disabled / programmatic-only nodes out of
// the Tab cycle.
const FOCUSABLE_SELECTOR = [
    'a[href]',
    'button:not([disabled])',
    'input:not([disabled])',
    'select:not([disabled])',
    'textarea:not([disabled])',
    '[tabindex]:not([tabindex="-1"])',
].join(',');

/**
 * Trap keyboard focus inside `dialogEl` until the returned release()
 * function is called.
 *
 * @param {HTMLElement} dialogEl        The dialog container (role="dialog").
 * @param {object}      [opts]
 * @param {Function}    [opts.onEscape] Called when Escape is pressed inside
 *        the dialog. Omit it when the caller already wires Escape elsewhere
 *        (passing it anyway would double-close).
 * @returns {Function}  release() — detaches the trap and restores focus to
 *        whatever element held it before trapFocus() was called.
 */
export function trapFocus(dialogEl, { onEscape } = {}) {
    if (!dialogEl) return () => {};

    // Cache the trigger so focus can be handed back cleanly on release.
    const triggerEl = document.activeElement;

    // Live query — re-evaluated on every Tab so controls injected after
    // open (e.g. result-panel buttons) join the cycle automatically.
    const focusables = () =>
        Array.from(dialogEl.querySelectorAll(FOCUSABLE_SELECTOR))
            .filter((el) => el.offsetParent !== null);

    // Move focus into the dialog. Fall back to the dialog itself if it has
    // no focusable child yet, so focus never lingers on the inert page.
    const initial = focusables();
    if (initial.length) {
        initial[0].focus();
    } else {
        dialogEl.setAttribute('tabindex', '-1');
        dialogEl.focus();
    }

    const onKeydown = (e) => {
        if (e.key === 'Escape' && typeof onEscape === 'function') {
            e.preventDefault();
            onEscape();
            return;
        }
        if (e.key !== 'Tab') return;

        const f = focusables();
        if (f.length === 0) { e.preventDefault(); return; }

        const first = f[0];
        const last = f[f.length - 1];
        const active = document.activeElement;

        if (e.shiftKey && (active === first || !dialogEl.contains(active))) {
            e.preventDefault();
            last.focus();
        } else if (!e.shiftKey && active === last) {
            e.preventDefault();
            first.focus();
        }
    };

    dialogEl.addEventListener('keydown', onKeydown);

    let released = false;
    return function release() {
        if (released) return;
        released = true;
        dialogEl.removeEventListener('keydown', onKeydown);
        if (triggerEl &&
            typeof triggerEl.focus === 'function' &&
            document.contains(triggerEl)) {
            triggerEl.focus();
        }
    };
}
