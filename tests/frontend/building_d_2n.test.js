/* DC-EPMS-076 step 2: Building D drawn and evaluated as 2N (A + B). */
import { describe, it, expect } from 'vitest';
import { matchesChannel, channelPrefixesFor, getNode } from '/assets/js/core/node_registry.js';
import { getAssetMeta } from '/assets/js/core/asset_metadata.js';
import { TOPOLOGY } from '/assets/js/core/power_grid.js';
import { n1Power, steadyStatePower } from '/assets/js/core/contingency.js';
import { __power_test__ } from '/assets/js/views/power.js';

const B_IDS = ['util_d_b', 'mv_rect_d_b', 'sscb_d_b', 'dc_bus_d_b', 'bess_d_b'];

describe('Building D 2N', () => {
    it('every path B node exists in the DAG, the registry and the asset metadata', () => {
        for (const id of B_IDS) {
            expect(TOPOLOGY[id], id).toBeTruthy();
            expect(getNode(id), id).toBeTruthy();
            expect(getAssetMeta(id), id).toBeTruthy();
        }
        expect(TOPOLOGY.rpp_d1.sources).toEqual(['dc_bus_d', 'dc_bus_d_b']);
        expect(getAssetMeta('util_d').label).toBe('Utility D-A · 35 kV');
        expect(getAssetMeta('util_d_b').label).toBe('Utility D-B · 35 kV');
        expect(getAssetMeta('dc_bus_d_b').label).toBe('800 VDC Bus D-B');
        expect(getAssetMeta('bess_d').label).toBe('BESS D-A');
        expect(TOPOLOGY.rpp_d2.sources).toEqual(['dc_bus_d', 'dc_bus_d_b']);
    });

    it('channel ownership: path A never swallows path B channels', () => {
        const a = (id) => channelPrefixesFor(id);
        expect(matchesChannel('utility_feed_d:utility_voltage_kv', a('util_d'))).toBe(true);
        expect(matchesChannel('utility_feed_d_b:utility_voltage_kv', a('util_d'))).toBe(false);
        expect(matchesChannel('utility_feed_d_b:utility_voltage_kv', a('util_d_b'))).toBe(true);
        expect(matchesChannel('bess_d_01:bess_soc_pct', a('bess_d'))).toBe(true);
        expect(matchesChannel('bess_d_b_01:bess_soc_pct', a('bess_d'))).toBe(false);
        expect(matchesChannel('bess_d_b_01:bess_soc_pct', a('bess_d_b'))).toBe(true);
        expect(matchesChannel('sscb_d_b_01:sscb_junction_T_c', a('sscb_d'))).toBe(false);
        expect(matchesChannel('main_bus_dc_d:voltage_v_dc_bus', a('dc_bus_d'))).toBe(true);
        expect(matchesChannel('main_bus_dc_d_b:voltage_v_dc_bus', a('dc_bus_d'))).toBe(false);
        expect(matchesChannel('mv_rectifier_d_b:rect_load_mw', a('mv_rect_d'))).toBe(false);
        expect(matchesChannel('mv_rectifier_d_b:rect_load_mw', a('mv_rect_d_b'))).toBe(true);
    });

    it('either whole path can be lost and the hall stays up; both cannot', () => {
        expect(steadyStatePower(new Set(['util_d', 'mv_rect_d'])).get('hall_d').alive).toBe(true);
        expect(steadyStatePower(new Set(['dc_bus_d_b'])).get('hall_d').alive).toBe(true);
        expect(steadyStatePower(new Set(['dc_bus_d', 'dc_bus_d_b'])).get('hall_d').alive).toBe(false);
        const n1 = n1Power();
        for (const id of [...B_IDS, 'util_d', 'mv_rect_d', 'sscb_d', 'dc_bus_d']) {
            expect(n1.get(id)?.lost ?? [], id).not.toContain('hall_d');
        }
    });

    it('the SLD draws both paths, feeds the RPPs from both buses, vocabulary-safe', () => {
        const p2 = __power_test__.buildPhase2Markup();
        for (const id of B_IDS) expect(p2).toContain(`data-sld-node="${id}"`);
        expect(p2).toContain('RPP D1 · A + B');
        expect(p2).toContain('800 VDC BUS D-B · UNIPOLAR TN-S');
        // S-VOCAB-01: no phase words on any DC node label in the branch
        for (const m of p2.matchAll(/data-sld-node="(dc_bus_d[^"]*|sscb_d[^"]*|bess_d[^"]*|rpp_d\d)"[\s\S]*?<\/g>/g)) {
            expect(m[0], m[1]).not.toMatch(/phase|trif/i);
        }
    });
});
