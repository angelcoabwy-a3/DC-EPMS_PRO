/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/rack_heatmap.test.js
 * ROADMAP V11 T3.6 — Anomaly Heatmap live Kalman integration.
 *
 * Verifies the heatmap maps the real Hermes `channel_innovations`
 * payload (per-rack gpu_Tj_c: last_emission + max_z) onto rack cells,
 * supersedes the deterministic simulator, and ignores non-matching
 * channels. No DOM fixture needed — the render functions guard on
 * missing elements.
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect, beforeEach } from 'vitest';

import { __rack_heatmap_test__ } from '/assets/js/views/rack_heatmap.js';

describe('T3.6 — rack heatmap live Kalman integration', () => {
    beforeEach(() => { __rack_heatmap_test__.reset(); });

    it('_onChannels maps real channel_innovations to rack tj + z', () => {
        __rack_heatmap_test__.seedRacks([{ asset_id: 'rack_a_01_05' }]);
        __rack_heatmap_test__.onChannels({
            'rack_a_01_05:gpu_Tj_c': { last_emission: 84.2, max_z: 3.7, is_anomalous: true },
        });
        const r = __rack_heatmap_test__.getRack('rack_a_01_05');
        expect(r.tj).toBe(84.2);
        expect(r.z).toBe(3.7);
        expect(r.band).toBe('warn');   // 78 < 84.2 <= 86
    });

    it('_onChannels stamps the live timestamp so the sim fallback yields', () => {
        expect(__rack_heatmap_test__.lastLiveTs()).toBe(0);
        __rack_heatmap_test__.seedRacks([{ asset_id: 'rack_b_02_01' }]);
        __rack_heatmap_test__.onChannels({
            'rack_b_02_01:gpu_Tj_c': { last_emission: 71.0, max_z: 1.1 },
        });
        expect(__rack_heatmap_test__.lastLiveTs()).toBeGreaterThan(0);
    });

    it('_onChannels leaves racks with no matching channel untouched', () => {
        __rack_heatmap_test__.seedRacks([{ asset_id: 'rack_a_01_05' }]);
        __rack_heatmap_test__.onChannels({ 'genset_a_01:genset_voltage_v': { max_z: 9.0 } });
        const r = __rack_heatmap_test__.getRack('rack_a_01_05');
        expect(r.tj).toBe(70);    // untouched baseline
        expect(r.z).toBe(1.0);
    });

    it('bandFor classifies the NVIDIA GB200 Tj envelope', () => {
        expect(__rack_heatmap_test__.bandFor(55)).toBe('cold');
        expect(__rack_heatmap_test__.bandFor(72)).toBe('normal');
        expect(__rack_heatmap_test__.bandFor(90)).toBe('crit');
    });
});
