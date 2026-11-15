/**
 * HMI H1 (2026-11-14): breaker colour convention in ONE place.
 *
 * North American utility / industrial practice (ANSI device 52):
 *   red   = CLOSED (energised, "danger"), green = OPEN (safe).
 * IEC / European practice is commonly the inverse. The scheme is a
 * site setting, not a hard-coded colour: CSS keys off
 * `data-scheme` on the SVG and the state text comes from here.
 *
 * Honest scope: neither convention is mandated by a single standard
 * the HMI can cite; ISA-101.01 leaves the palette to the site HMI
 * philosophy. A3-Alpha is in Ontario, so the default is 'ansi'.
 */

export const BREAKER_SCHEMES = Object.freeze({
    ansi: Object.freeze({
        id: 'ansi',
        closed: 'CLOSED', open: 'OPEN', transfer: 'XFER', trip: 'TRIP',
        legendClosed: 'Breaker CLOSED (red, filled)',
        legendOpen: 'Breaker OPEN (green, hollow)',
    }),
    iec: Object.freeze({
        id: 'iec',
        closed: 'CLOSED', open: 'OPEN', transfer: 'XFER', trip: 'TRIP',
        legendClosed: 'Breaker CLOSED (green, filled)',
        legendOpen: 'Breaker OPEN (red, hollow)',
    }),
});

/** Active scheme for this site (A3-Alpha Toronto Area -> ANSI). */
export const BREAKER_SCHEME = BREAKER_SCHEMES.ansi;

const _STATES = new Set(['closed', 'open', 'transfer', 'trip']);

/** State text for a breaker state under a scheme ('' for unknown). */
export function breakerText(state, scheme = BREAKER_SCHEME) {
    return _STATES.has(state) ? scheme[state] : '';
}
