/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/bms.test.js
 * ROADMAP V11 T2.1 Vector 1 — verifies the extracted BMS Connector.
 *
 * Behaviour-preserving extraction smoke test: the tag table, stats
 * pills, category tabs and RBAC write modal render onto a happy-dom
 * fixture; hostile tag metadata is escaped; and initBmsView() re-exposes
 * window.showBmsAudit so the copilot deep-link survives the extraction.
 * No browser, no backend.
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect, afterEach } from 'vitest';

import { __bms_test__ } from '/assets/js/views/bms.js';

const { formatBmsValue, renderBmsTable, renderBmsStats, renderBmsCategories,
    showBmsWriteModal, initBmsView, setCache, reset } = __bms_test__;

afterEach(() => {
    reset();
    document.body.innerHTML = '';
});

describe('T2.1 Vector 1 — views/bms.js formatBmsValue()', () => {
    it('formats integers, floats, booleans and null', () => {
        expect(formatBmsValue({ current_value: 480 })).toBe((480).toLocaleString());
        expect(formatBmsValue({ current_value: 4.237 })).toBe('4.24');
        expect(formatBmsValue({ current_value: true })).toBe('On');
        expect(formatBmsValue({ current_value: false })).toBe('Off');
        expect(formatBmsValue({ current_value: null })).toContain('bms-no-data');
    });
});

describe('T2.1 Vector 1 — views/bms.js table / stats / tabs', () => {
    it('renderBmsTable stamps tag rows with a write button for writable tags', () => {
        document.body.innerHTML = '<table><tbody id="bms-tbody"></tbody></table>';
        renderBmsTable([
            { id: 'PWR.ATS_A.BREAKER', description: 'ATS A breaker', protocol: 'BACnet',
                units: '', alarm_state: 'normal', current_value: 'CLOSE', writable: true },
            { id: 'PWR.UPS_A.SOC', description: 'UPS A state of charge', protocol: 'Modbus',
                units: '%', alarm_state: 'normal', current_value: 98, writable: false },
        ]);
        const rows = document.querySelectorAll('#bms-tbody tr');
        expect(rows).toHaveLength(2);
        expect(document.querySelector('.btn-bms-write').dataset.id).toBe('PWR.ATS_A.BREAKER');
        expect(document.querySelector('.bms-readonly').textContent).toBe('RO');
    });

    it('escapes hostile tag metadata in the table (XSS defence)', () => {
        document.body.innerHTML = '<table><tbody id="bms-tbody"></tbody></table>';
        renderBmsTable([
            { id: 'X', description: '<img src=x onerror=alert(1)>', protocol: 'BACnet',
                units: '', alarm_state: 'normal', current_value: 1, writable: false },
        ]);
        const tbody = document.getElementById('bms-tbody');
        expect(tbody.querySelector('img')).toBeNull();
        expect(tbody.textContent).toContain('<img src=x onerror=alert(1)>');
    });

    it('renderBmsStats emits the tag-count pills', () => {
        document.body.innerHTML = '<div id="bms-stats"></div>';
        renderBmsStats({ total_tags: 50, writable_tags: 9, alarm_count: 0, warning_count: 0 });
        const el = document.getElementById('bms-stats');
        expect(el.textContent).toContain('50 tags');
        expect(el.textContent).toContain('9 writable');
        expect(el.textContent).toContain('All normal');
    });

    it('renderBmsCategories emits the All tab plus one tab per category', () => {
        document.body.innerHTML = '<div id="bms-tabs"></div>';
        renderBmsCategories({
            total_tags: 50,
            categories: { power: { name: 'Power', icon: '' }, hvac: { name: 'HVAC', icon: '' } },
            by_category: { power: 30, hvac: 20 },
        });
        const tabs = document.querySelectorAll('#bms-tabs .bms-tab');
        expect(tabs).toHaveLength(3); // All + power + hvac
        expect(tabs[0].textContent).toContain('All (50)');
    });
});

describe('T2.1 Vector 1 — views/bms.js write modal + copilot deep-link', () => {
    it('showBmsWriteModal opens the modal with an enum select', () => {
        document.body.innerHTML = `
            <div id="view-bms">
                <div id="bms-write-modal" hidden>
                    <div id="bms-write-title"></div>
                    <div id="bms-write-body"></div>
                    <button id="bms-write-close"></button>
                </div>
            </div>`;
        setCache({ tags: [{
            id: 'PWR.ATS_A.BREAKER', description: 'ATS A breaker', protocol: 'BACnet',
            object_type: 'BO', units: '', current_value: 'OPEN', writable: true,
            enum_values: ['OPEN', 'CLOSE'],
        }] });
        showBmsWriteModal('PWR.ATS_A.BREAKER');
        expect(document.getElementById('bms-write-modal').hidden).toBe(false);
        expect(document.getElementById('bms-write-title').textContent)
            .toBe('Write to PWR.ATS_A.BREAKER');
        expect(document.querySelector('#bms-write-body select#bms-write-input'))
            .not.toBeNull();
        expect(document.getElementById('bms-write-confirm')).not.toBeNull();
    });

    it('initBmsView re-exposes window.showBmsAudit for the copilot deep-link', () => {
        delete window.showBmsAudit;
        document.body.innerHTML = '<div id="view-bms"></div>';
        initBmsView();
        expect(typeof window.showBmsAudit).toBe('function');
    });
});
