/**
 * L5: field view of the battery room (core/field_battery.js) and its
 * wiring in the Power view and the UPS faceplate.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { batterySvg, applyBatteryState, resolveBatteryClick, isBatteryEvent, batteryEventText, ironbow }
    from '/assets/js/core/field_battery.js';
import { fieldLogHtml } from '/assets/js/core/field_switchgear.js';
import { faceplateHtml } from '/assets/js/core/sbo_faceplate.js';
import { __power_test__ } from '/assets/js/views/power.js';

const temps = (hot) => Array.from({ length: 40 }, (_, i) => (i + 1 === hot ? 48.6 : 24.2));
const STR = (n, over = {}) => ({ n, closed: true, padlock: null, link: true, online: true, voltage_v: 542.1,
    float_a: n === 3 ? 3.0 : 0.3, float_high: n === 3, temps: temps(n === 3 ? 18 : 0), vented: [], ...over });
const ROOM = (over = {}) => ({
    strings: [1, 2, 3, 4].map((n) => STR(n)), strings_online: 4, bus_v: 542.1,
    h2_ppm: 85, h2_pct_lel: 0.21, h2_alarm_ppm: 400, h2_hihi_ppm: 10000,
    fans: [{ name: 'EF1', mode: 'AUTO', failed: false, running: true }, { name: 'EF2', mode: 'AUTO', failed: false, running: false }],
    scanned: [], measured: [], readings: [], replaced: [], runaway: [],
    thresholds: { ohmic_warn_pct: 30, ohmic_replace_pct: 50, dt_warn_c: 5, dt_alarm_c: 10, runaway_c: 60, ambient_c: 24 },
    ...over,
});
const PS = (room = ROOM()) => ({ path: 'a', battery_room: room });

function mount(ps = PS(), ui = { string: 3, tool: 'ir' }) {
    document.body.innerHTML = `<div id="root">${batterySvg('a')}</div>`;
    const root = document.getElementById('root');
    applyBatteryState(root, ps, ui);
    return root;
}

describe('field_battery: drawing', () => {
    it('one rack of 40 jars, four string disconnects, two fans, honest labels', () => {
        const root = mount();
        expect(root.querySelectorAll('.xb-jar')).toHaveLength(40);
        expect(root.querySelectorAll('.xb-sb')).toHaveLength(4);
        expect(root.querySelector('[data-sel="ef1"]')).not.toBeNull();
        expect(root.innerHTML).toContain('SIMULATED EQUIPMENT');
        expect(root.innerHTML).toContain('MODEL VALUES');
    });

    it('IR camera paints jars on the ironbow ramp and finds the hot spot', () => {
        const root = mount();
        const sec = root.querySelector('[data-section="BATT"]');
        expect(sec.getAttribute('data-ir')).toBe('1');
        const hot = root.querySelector('.xb-jar[data-jar="18"] .xb-jar-body').style.fill;
        const cold = root.querySelector('.xb-jar[data-jar="1"] .xb-jar-body').style.fill;
        expect(hot).not.toBe(cold);
        expect(root.querySelector('[data-txt="ircap"]').textContent).toContain('JAR 18 48.6');
        expect(root.querySelector('[data-txt="t18"]').textContent).toBe('48.6°');
        expect(ironbow(10)).toBe('rgb(0,0,0)');
        expect(ironbow(99)).toBe('rgb(255,255,235)');
    });

    it('without the camera the jar temperatures are hidden; the analyzer shows its last reading', () => {
        const room = ROOM({ readings: [{ jar: 'S3J18', v: 10.4, r_mohm: 14.2, r_base_mohm: 3.6, rise_pct: 294.4,
            temp_c: 48.6, status: 'REPLACE' }] });
        const root = mount(PS(room), { string: 3, tool: 'meter' });
        expect(root.querySelector('[data-txt="t18"]').textContent).toBe('');
        expect(root.querySelector('[data-txt="m1"]').textContent).toBe('JAR S3J18 · 10.40 V DC');
        expect(root.querySelector('[data-section="BATT"]').getAttribute('data-mstatus')).toBe('REPLACE');
        expect(root.querySelector('.xb-sb[data-sb="3"]').getAttribute('data-high')).toBe('1');
        expect(root.querySelector('[data-txt="h1"]').textContent).toBe('H2 85 ppm · 0.21 % LEL');
    });

    it('locked-out string and H2 alarm', () => {
        const room = ROOM({ h2_ppm: 520, h2_pct_lel: 1.3 });
        room.strings[2] = STR(3, { closed: false, padlock: 'manager', link: false, online: false, float_a: 0, float_high: false });
        const root = mount(PS(room));
        const g = root.querySelector('.xb-sb[data-sb="3"]');
        expect(g.getAttribute('data-padlock')).toBe('1');
        expect(g.getAttribute('data-link')).toBe('0');
        expect(root.querySelector('[data-txt="h2"]').textContent).toBe('ALARM · 1 % LEL');
    });
});

describe('field_battery: clicks and log', () => {
    it('tools decide what a jar click does; tabs and the camera record a scan', () => {
        const root = mount();
        const jar = root.querySelector('.xb-jar[data-jar="18"] rect');
        expect(resolveBatteryClick(jar, ROOM(), { string: 3, tool: 'meter' })).toMatchObject({ action: 'MEASURE_S3_J18' });
        expect(resolveBatteryClick(jar, ROOM(), { string: 3, tool: 'replace' })).toMatchObject({ action: 'REPLACE_S3_J18' });
        expect(resolveBatteryClick(jar, ROOM(), { string: 3, tool: 'ir' })).toEqual({ ui: { jar: 18 } });
        expect(resolveBatteryClick(root.querySelector('.xb-tool[data-tool="ir"] rect'), ROOM(), { string: 2 }))
            .toMatchObject({ ui: { tool: 'ir' }, scan: 'IR_SCAN_S2' });
        expect(resolveBatteryClick(root.querySelector('.xb-tab[data-string="4"] rect'), ROOM(), { tool: 'meter' }))
            .toMatchObject({ ui: { string: 4 }, scan: null });
        expect(resolveBatteryClick(root.querySelector('.xu-handle[data-string="3"] rect'), ROOM(), {})).toMatchObject({ action: 'OPEN_SB3' });
        expect(resolveBatteryClick(root.querySelector('.xb-hasp[data-string="3"] rect'), ROOM(), {})).toMatchObject({ action: 'PADLOCK_SB3' });
        expect(resolveBatteryClick(root.querySelector('.xb-link[data-string="2"] rect'), ROOM(), {})).toMatchObject({ action: 'BREAK_LINK_S2' });
        expect(resolveBatteryClick(root.querySelector('[data-act="ef2_hand"] rect'), ROOM(), {})).toMatchObject({ action: 'EF2_HAND' });
        expect(resolveBatteryClick(root.querySelector('[data-act="ef1_reset"] rect'), ROOM(), {})).toMatchObject({ action: 'EF1_RESET' });
    });

    it('log text for inspections and refusals, escaped', () => {
        const events = [
            { ts: 1, event: 'inspection', device_id: 'battery_room_a', command: 'MEASURE_S3_J18@BATT_A', equipment: 'battery',
                reading: { jar: 'S3J18', v: 10.4, r_mohm: 14.2, status: 'REPLACE' } },
            { ts: 2, event: 'refused', device_id: 'battery_room_a', command: 'REPLACE_S3_J18@BATT_A', detail: '<isolate first>' },
        ];
        expect(batteryEventText(events[0])).toBe('ANALYZER S3J18 · 10.4 V · 14.2 mΩ · REPLACE');
        const html = fieldLogHtml(events, '', '', { anyDevice: true,
            match: (ev) => ev.device_id === 'battery_room_a' && isBatteryEvent(ev), text: batteryEventText, empty: 'none' });
        expect(html).toContain('&lt;isolate first&gt;');
    });
});

describe('Power view + faceplate wiring (L5 battery)', () => {
    afterEach(() => { vi.restoreAllMocks(); __power_test__.closeField(); });

    it('UPS faceplate offers the battery room', () => {
        const html = faceplateHtml('ups_a', { devices: [{ id: 'ups_a_01', kind: 'ups', path: 'a', state: 'DOUBLE_CONVERSION' }],
            paths: [PS()] });
        expect(html).toContain('data-fp-equip="batt"');
    });

    it('opens the battery room, scans with the camera and measures a jar', async () => {
        document.body.innerHTML = '<div id="view-power"><div class="pid-canvas"><svg class="pid-svg"></svg></div></div>';
        const xfer = { id: 'mvtc_a', kind: 'transfer', path: 'a', state: 'UTILITY', cubicles: [] };
        __power_test__.setPlant({ paths: [PS()], devices: [xfer], events: [] });
        const calls = [];
        vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, opts) => {
            calls.push([String(url), opts && opts.body]);
            const body = String(url).includes('/api/battery-rooms/')
                ? { success: true, event: { reading: { string: 1, hottest: 'S1J20', max_c: 24.6, delta_c: 0.3 } } }
                : { paths: [PS()], devices: [xfer], events: [] };
            return { ok: true, status: 200, json: async () => body };
        });
        __power_test__.openField('a', 'batt');
        const el = document.getElementById('pwr-field');
        expect(el.getAttribute('aria-label')).toBe('Field view: battery room');
        await __power_test__.onFieldClick({ target: el.querySelector('.xb-tool[data-tool="ir"] rect') });
        await __power_test__.onFieldClick({ target: el.querySelector('.xb-tool[data-tool="meter"] rect') });
        await __power_test__.onFieldClick({ target: el.querySelector('.xb-jar[data-jar="7"] rect') });
        const posts = calls.filter(([u]) => u.includes('/api/battery-rooms/a/action')).map(([, b]) => JSON.parse(b).action);
        expect(posts).toEqual(['IR_SCAN_S1', 'MEASURE_S1_J7']);
    });
});
