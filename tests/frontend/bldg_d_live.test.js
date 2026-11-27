/* Lots 11 + 12 (ADR-023): Building D live numbers, plant mirror,
 * select-before-operate faceplate and Power Controls tabs. */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { metricsFromChannels, metricsFromPlant, hallCaption } from '/assets/js/core/phase2_live.js';
import { mirrorGrid } from '/assets/js/core/plant_mirror.js';
import { initPowerGrid, getGridState } from '/assets/js/core/power_grid.js';
import { isFaceplateTarget, bldgDPath, devicesFor, faceplateHtml } from '/assets/js/core/sbo_faceplate.js';
import { __device_control_test__ as dcv } from '/assets/js/views/device_control.js';

const ch = (v) => ({ last_emission: v });

function bdPath(path, over = {}) {
    return {
        path, label: `D-${path.toUpperCase()}`, utility_ok: true, input_closed: true, source: 'UTILITY',
        input_live: true, rect_units_in: 14, rect_units: 14, rect_n1_ok: true, rect_capacity_kw: 70000,
        rect_out_kw: 25000, sscb: 'CLOSED', sscb_trip: null, bus_fault: false, bus_energized: true,
        bus_v: 800, bess_breaker: 'CLOSED', bess_trip: null, soc_pct: 100, bess_kw: 0,
        farm: 'STANDBY', farm_auto: true, carrying_kw: 25000, ...over,
    };
}

function plantWith(a = {}, b = {}, hall = {}) {
    const devices = [];
    const paths = [];
    for (const p of ['a', 'b']) {
        devices.push({ id: `mvtc_${p}`, kind: 'transfer', path: p, state: 'UTILITY' });
        paths.push({ path: p, source: 'UTILITY', ups_total: 8, ups_in_service: 8, gen_total: 9, gen_available: 9 });
    }
    for (const [p, s] of [['a', ''], ['b', '_b']]) {
        devices.push({ id: `mv_rect_d${s}`, kind: 'rectifier', path: `d${p}`, state: 'UTILITY', authority: 'AUTO',
            display: `Rectifier group D-${p.toUpperCase()}`, status: { tone: 'ok', text: 'Input on utility' },
            readings: [{ label: 'Input voltage (3-phase AC)', value: 35, unit: 'kV' }],
            commands: [{ command: 'OPEN_INPUT', label: 'Open input breaker', permitted: false, blocked_reason: 'Device is in AUTO' }] });
        devices.push({ id: `sscb_d${s}`, kind: 'sscb', path: `d${p}`, state: 'CLOSED', authority: 'REMOTE', commands: [] });
        devices.push({ id: `bess_d${s}`, kind: 'bess', path: `d${p}`, state: 'STANDBY', authority: 'AUTO', commands: [] });
        devices.push({ id: `farm_d${s}`, kind: 'farm', path: `d${p}`, state: 'STANDBY', authority: 'AUTO', commands: [] });
    }
    return {
        devices, paths,
        building_d: {
            notice: 'Building D is a DESIGN', demand_kw: 50000, load_lost: false, paths_carrying: 2,
            load_step: null, paths: [bdPath('a', a), bdPath('b', b)], ...hall,
        },
    };
}

describe('phase2_live: SLD numbers', () => {
    it('reads the per-path channels', () => {
        const m = metricsFromChannels({
            'utility_feed_d:utility_voltage_kv': ch(35.02),
            'utility_feed_d_b:utility_voltage_kv': ch(0),
            'mv_rectifier_d:rect_load_mw': ch(25.0),
            'mv_rectifier_d:rect_efficiency_ratio': ch(0.985),
            'main_bus_dc_d:voltage_v_dc_bus': ch(799.6),
            'main_bus_dc_d_b:voltage_v_dc_bus': ch(0),
            'bess_d_01:bess_soc_pct': ch(98.4),
            'bess_d_01:bess_dc_current_a': ch(1250),
            'bess_d_b_01:bess_soc_pct': ch(100),
            'bess_d_b_01:bess_dc_current_a': ch(-600),
            'sscb_d_01:sscb_junction_T_c': ch(54.6),
        });
        expect(m['util_d-kv']).toBe('35.0 kV');
        expect(m['util_d_b-kv']).toBe('0 kV · LOST');
        expect(m['mv_rect_d-load']).toBe('25.0 MW · η 98.5 %');
        expect(m['util_d-kw']).toBe('AC in 25.4 MW');
        expect(m['dc_bus_d-v']).toBe('800 VDC');
        expect(m['dc_bus_d_b-v']).toBe('0 VDC · DEAD');
        expect(m['bess_d-soc']).toBe('SOC 98.4 % · discharging 1,250 A');
        expect(m['bess_d_b-soc']).toBe('SOC 100.0 % · charging 600 A');
        expect(m['sscb_d-clear']).toBe('Tj 55 °C · 1-100 µs');
        // S-VOCAB-01: nothing on the DC side speaks of phases
        for (const [k, v] of Object.entries(m)) {
            if (/^(dc_bus|bess|sscb)/.test(k)) expect(v, k).not.toMatch(/phase|trif/i);
        }
    });

    it('absent channels leave the placeholders alone', () => {
        expect(metricsFromChannels({})).toEqual({});
        expect(metricsFromChannels(null)).toEqual({});
    });

    it('plant states and hall caption', () => {
        const bd = plantWith({ sscb: 'TRIPPED', sscb_trip: 'BUS_FAULT', carrying_kw: 0 }, { carrying_kw: 50000 }).building_d;
        expect(metricsFromPlant(bd)['sscb_d-state']).toBe('TRIPPED (bus fault)');
        expect(metricsFromPlant(bd)['sscb_d_b-state']).toBe('CLOSED');
        expect(hallCaption(bd)).toBe('D-A 0.0 MW · D-B 50.0 MW');
        expect(hallCaption({ ...bd, load_lost: true })).toMatch(/LOAD LOST/);
        expect(hallCaption(null)).toBeNull();
    });
});

describe('plant mirror: Building D', () => {
    beforeEach(() => { vi.useFakeTimers(); initPowerGrid(); });

    it('nominal plant: both buses and the hall alive, farm in standby', () => {
        const g = mirrorGrid(getGridState(), plantWith());
        for (const id of ['mv_rect_d', 'sscb_d', 'dc_bus_d', 'mv_rect_d_b', 'dc_bus_d_b', 'hall_d']) {
            expect(g[id].alive, id).toBe(true);
        }
        expect(g.gen_farm_d.running).toBe(false);
    });

    it('bus fault on A: A dark, hall on B', () => {
        const g = mirrorGrid(getGridState(), plantWith(
            { sscb: 'TRIPPED', bess_breaker: 'TRIPPED', bus_energized: false, bus_v: 0, carrying_kw: 0 }));
        expect(g.sscb_d.alive).toBe(false);
        expect(g.dc_bus_d.alive).toBe(false);
        expect(g.bess_d.alive).toBe(false);
        expect(g.dc_bus_d_b.alive).toBe(true);
        expect(g.hall_d.alive).toBe(true);
    });

    it('SSCB open, bus held by its BESS', () => {
        const g = mirrorGrid(getGridState(), plantWith({ sscb: 'OPEN', bus_energized: true, carrying_kw: 0 }));
        expect(g.sscb_d.alive).toBe(false);
        expect(g.dc_bus_d.alive).toBe(true);
        expect(g.dc_bus_d.energized_by).toBe('battery');
    });

    it('utility lost with the farm still cranking: rectifier A has no input', () => {
        const p = plantWith({ utility_ok: false, input_live: false, farm: 'CRANKING' });
        const g = mirrorGrid(getGridState(), p);
        expect(g.util_d.alive).toBe(false);
        expect(g.gen_farm_d.running).toBe(false);
        expect(g.gen_farm_d.state).toBe('cranking');
        expect(g.mv_rect_d.alive).toBe(false);
    });

    it('input on the farm: rectifier A energised by the farm', () => {
        const g = mirrorGrid(getGridState(), plantWith({ utility_ok: false, source: 'FARM', farm: 'ON_LOAD' }));
        expect(g.gen_farm_d.running).toBe(true);
        expect(g.mv_rect_d.alive).toBe(true);
        expect(g.mv_rect_d.energized_by).toBe('genset');
        expect(g.mv_rect_d_b.energized_by).toBe('util');
    });

    it('hall load lost latches the hall dark', () => {
        const g = mirrorGrid(getGridState(), plantWith({}, {}, { load_lost: true }));
        expect(g.hall_d.alive).toBe(false);
    });
});

describe('faceplate: Building D', () => {
    it('targets and paths', () => {
        for (const id of ['mv_rect_d', 'sscb_d_b', 'bess_d', 'gen_farm_d', 'mvtc_a']) expect(isFaceplateTarget(id), id).toBe(true);
        for (const id of ['dc_bus_d', 'rpp_d1', 'util_d', 'hall_d']) expect(isFaceplateTarget(id), id).toBe(false);
        expect(bldgDPath('sscb_d_b')).toBe('b');
        expect(bldgDPath('bess_d')).toBe('a');
        expect(bldgDPath('mvtc_a')).toBeNull();
    });

    it('devices behind a node, farm block opens both farms', () => {
        const p = plantWith();
        expect(devicesFor('sscb_d_b', p).map((d) => d.id)).toEqual(['sscb_d_b']);
        expect(devicesFor('gen_farm_d', p).map((d) => d.id)).toEqual(['farm_d', 'farm_d_b']);
    });

    it('renders readings, AUTO hint, blocked reason and bench injections', () => {
        const html = faceplateHtml('mv_rect_d', plantWith());
        expect(html).toContain('Rectifier group D-A');
        expect(html).toContain('Input voltage (3-phase AC)');
        expect(html).toContain('Set REMOTE');
        expect(html).toContain('title="Device is in AUTO"');
        expect(html).toContain('data-fp-inject="utility_loss"');
        expect(html).toContain('data-fp-path="a"');
        const bess = faceplateHtml('bess_d_b', plantWith());
        expect(bess).toContain('data-fp-inject="load_step"');
        expect(bess).toContain('data-fp-kw="12000"');
    });

    it('escapes device text (S-SEC-01)', () => {
        const p = plantWith();
        p.devices.find((d) => d.id === 'sscb_d').display = '<img src=x onerror=alert(1)>';
        expect(faceplateHtml('sscb_d', p)).not.toContain('<img');
    });
});

describe('Power Controls: Building D tabs', () => {
    it('adds BLDG D-A / D-B paths and groups their devices', () => {
        const p = plantWith();
        expect(dcv.pathsOf(p)).toEqual(['a', 'b', 'da', 'db']);
        const groups = dcv.groupByKind(p.devices, 'db');
        expect([...groups.keys()]).toEqual(['rectifier', 'sscb', 'bess', 'farm']);
        expect(groups.get('sscb').map((d) => d.id)).toEqual(['sscb_d_b']);
    });

    it('summary tiles from the plant block', () => {
        const html = dcv.renderDSummary(plantWith({ sscb: 'TRIPPED', bus_energized: false, bus_v: 0 }), 'da');
        expect(html).toContain('DEAD');
        expect(html).toContain('50.0 MW on 2 path(s)');
        expect(dcv.renderDSummary(plantWith(), 'a')).toBe('');
    });
});

describe('phase2_live: clamps', () => {
    it('SOC jitter never reads above 100 %', () => {
        const m = metricsFromChannels({ 'bess_d_01:bess_soc_pct': ch(100.4), 'bess_d_01:bess_dc_current_a': ch(0) });
        expect(m['bess_d-soc']).toBe('SOC 100.0 % · idle');
    });
});

describe('Power SLD: standby farm is not an alarm', () => {
    it('farm, its 13.8 kV bus and step-up read ok while the farm stands by', async () => {
        const { __power_test__: pw } = await import('/assets/js/views/power.js');
        document.body.innerHTML = `<div id="view-power"><svg class="pid-svg">
            <g class="sld-node pf-node" data-sld-node="gen_farm_d"><rect class="pf-sym pid-symbol"/></g>
            <g class="sld-node pf-node" data-sld-node="stepup_d"><rect class="pf-sym pid-symbol"/></g>
            <g class="sld-node pf-node" data-sld-node="sscb_d"><rect class="pf-sym pid-symbol"/></g>
        </svg></div>`;
        const grid = {
            gen_farm_d: { type: 'farm', alive: false, running: false, state: 'standby', tripped: false },
            stepup_d: { type: 'xfmr', alive: false, tripped: false },
            sscb_d: { type: 'sscb', alive: false, tripped: true },
        };
        pw.applyGrid(grid);
        const sev = (id) => document.querySelector(`[data-sld-node="${id}"] .pid-symbol`).getAttribute('data-sev');
        expect(sev('gen_farm_d')).toBe('ok');
        expect(sev('stepup_d')).toBe('ok');
        expect(sev('sscb_d')).toBe('critical');
        pw.applyGrid({ ...grid, gen_farm_d: { ...grid.gen_farm_d, state: 'cranking' } });
        expect(sev('gen_farm_d')).toBe('warning');
        document.body.innerHTML = '';
    });
});
