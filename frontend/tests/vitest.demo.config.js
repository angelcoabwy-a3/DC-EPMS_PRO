/* DC-EPMS PRO — frontend/tests/vitest.demo.config.js
 * Runner for the hackathon demo-mode tests ONLY. The repo-root
 * vitest.config.js intentionally includes just tests/frontend/** and
 * must stay untouched, so this sibling config runs the new
 * frontend/tests/** file with the same environment (happy-dom), the
 * same /assets alias, and the same setup file (read, never modified):
 *   npx vitest run --config frontend/tests/vitest.demo.config.js
 * No server, no network, no Meta calls.
 */
import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';

export default defineConfig({
    root: fileURLToPath(new URL('../..', import.meta.url)),
    test: {
        environment: 'happy-dom',
        globals: true,
        include: ['frontend/tests/**/*.test.js'],
        setupFiles: ['tests/frontend/setup.js'],
    },
    resolve: {
        alias: {
            '/assets': fileURLToPath(new URL('../assets', import.meta.url)),
        },
    },
});
