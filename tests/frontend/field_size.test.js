// Field view readability toggle (2026-11-26): LARGE / FIT, remembered
// per browser, phones start in FIT.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { __power_test__ } from '/assets/js/views/power.js';

const XFER = { id: 'mvtc_a', kind: 'transfer', path: 'a', state: 'UTILITY', cubicles: [] };

function boot(width) {
    document.body.innerHTML = '<div id="view-power"><div class="pid-canvas"><svg class="pid-svg"></svg></div></div>';
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: width });
    __power_test__.setPlant({ paths: [{ path: 'a' }], devices: [XFER], events: [] });
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => (
        { ok: true, status: 200, json: async () => ({ paths: [{ path: 'a' }], devices: [XFER], events: [] }) }));
    __power_test__.openField('a', 'swgr');
    return document.getElementById('pwr-field');
}

describe('field view text size', () => {
    afterEach(() => { vi.restoreAllMocks(); window.localStorage.clear(); __power_test__.closeField(); });

    it('starts LARGE on a desktop and FIT on a phone', () => {
        expect(boot(1400).getAttribute('data-size')).toBe('large');
        document.getElementById('pwr-field').remove();
        expect(boot(430).getAttribute('data-size')).toBe('fit');
    });

    it('switches between FIT, MEDIUM and LARGE and remembers it', async () => {
        const el = boot(1400);
        const btn = (k) => el.querySelector(`[data-fsize="${k}"]`);
        expect(btn('large').getAttribute('aria-pressed')).toBe('true');
        for (const k of ['medium', 'fit', 'large']) {
            await __power_test__.onFieldClick({ target: btn(k) });
            expect(el.getAttribute('data-size')).toBe(k);
            expect(window.localStorage.getItem('dcepms.field.size')).toBe(k);
            for (const o of ['fit', 'medium', 'large']) {
                expect(btn(o).getAttribute('aria-pressed')).toBe(String(o === k));
            }
        }
        window.localStorage.setItem('dcepms.field.size', 'medium');
        __power_test__.closeField();
        document.getElementById('pwr-field').remove();
        expect(boot(1400).getAttribute('data-size')).toBe('medium');
    });
});
