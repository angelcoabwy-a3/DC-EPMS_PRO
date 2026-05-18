/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/maintenance.test.js
 * ROADMAP V11 T3.1 Part 3 — maintenance view event-driven cutover.
 *
 * Verifies the Maintenance view reacts to a Hermes cmms_alerts event
 * (the `hermes:cmms-alert` DOM event) by refreshing — and only while
 * visible. `fetch` is stubbed with a never-resolving promise so the
 * refresh is observed at its first network call without running the
 * full async render.
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect, vi, afterEach } from 'vitest';

import { __maintenance_test__ } from '/assets/js/views/maintenance.js';

describe('T3.1 Part 3 — maintenance.js event-driven refresh', () => {
    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it('a hermes:cmms-alert refreshes the view (fetches CMMS data) when visible', () => {
        const fetchSpy = vi.fn(() => new Promise(() => {}));   // pending — refresh stops at the network call
        vi.stubGlobal('fetch', fetchSpy);

        __maintenance_test__.setVisible(true);
        __maintenance_test__.onHermesAlert();

        // _refresh() invokes fetch synchronously, before its first await —
        // i.e. the view reacts the instant the event payload lands.
        expect(fetchSpy).toHaveBeenCalled();
    });

    it('a hermes:cmms-alert is ignored when the view is not visible', () => {
        const fetchSpy = vi.fn(() => new Promise(() => {}));
        vi.stubGlobal('fetch', fetchSpy);

        __maintenance_test__.setVisible(false);
        __maintenance_test__.onHermesAlert();

        expect(fetchSpy).not.toHaveBeenCalled();
    });

    it('exposes the bound listener handle for clean teardown', () => {
        // isWired() is false until initMaintenanceView() runs in the browser;
        // the surface exists so stopMaintenanceView() can detach cleanly.
        expect(typeof __maintenance_test__.isWired).toBe('function');
        expect(__maintenance_test__.isWired()).toBe(false);
    });
});
