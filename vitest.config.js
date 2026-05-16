/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — vitest.config.js
 * ROADMAP V11 T2.4 — Frontend Test Harness (Bite 1 skeleton).
 *
 * Runs the vanilla-JS frontend under happy-dom. No build step, no
 * bundler — tests import the same ES modules the browser loads.
 * FastAPI static serving is UNTOUCHED: this config + node_modules
 * live at the repo root; nothing under frontend/ is modified.
 * ════════════════════════════════════════════════════════════════ */
import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';

export default defineConfig({
    test: {
        environment: 'happy-dom',
        globals: true,
        include: ['tests/frontend/**/*.test.js'],
        setupFiles: ['tests/frontend/setup.js'],
    },
    resolve: {
        alias: {
            // The browser loads view modules via the absolute path
            // `/assets/...` (FastAPI serves frontend/ at the web root).
            // Map it to the real folder so Bite 2+ can import the real
            // mission_control.js / core modules. Unused by Bite 1.
            '/assets': fileURLToPath(new URL('./frontend/assets', import.meta.url)),
        },
    },
});
