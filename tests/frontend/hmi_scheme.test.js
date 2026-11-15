/* HMI H1: breaker colour convention lives in one constant. */
import { describe, it, expect } from 'vitest';
import { BREAKER_SCHEME, BREAKER_SCHEMES, breakerText } from '/assets/js/core/hmi_scheme.js';

describe('hmi_scheme', () => {
    it('A3-Alpha (Ontario) defaults to the North American ANSI convention', () => {
        expect(BREAKER_SCHEME.id).toBe('ansi');
        expect(BREAKER_SCHEME.legendClosed).toMatch(/red/);
        expect(BREAKER_SCHEME.legendOpen).toMatch(/green/);
    });
    it('IEC variant is the inverse colour, same state words', () => {
        expect(BREAKER_SCHEMES.iec.legendClosed).toMatch(/green/);
        expect(BREAKER_SCHEMES.iec.legendOpen).toMatch(/red/);
        expect(breakerText('closed', BREAKER_SCHEMES.iec)).toBe('CLOSED');
    });
    it('state text for every state, empty for unknown', () => {
        expect(['closed', 'open', 'transfer', 'trip'].map((s) => breakerText(s)))
            .toEqual(['CLOSED', 'OPEN', 'XFER', 'TRIP']);
        expect(breakerText('bogus')).toBe('');
    });
    it('schemes are frozen', () => {
        expect(Object.isFrozen(BREAKER_SCHEME)).toBe(true);
    });
});
