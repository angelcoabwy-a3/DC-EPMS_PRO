/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — core/version.js
 *
 * JS mirror of the canonical application version. The single source
 * of truth is ``backend/__version__.py``; this file is the
 * compile-free way to surface it in the HMI (no build step → no
 * substitution macro). Keep in lockstep with __version__.py and
 * package.json — the docstring in __version__.py lists the bump
 * checklist.
 *
 * Consumed by:
 *   - core/bootstrap.js — banner + footer stamp on init
 *   - index.html footer literal (fallback before JS runs)
 * ════════════════════════════════════════════════════════════════ */

export const APP_VERSION = '0.16.1';
