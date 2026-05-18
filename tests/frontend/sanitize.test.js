/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/sanitize.test.js
 * E2E Security Audit F3-5 — client-side XSS sanitizer coverage.
 *
 * Verifies core/sanitize.js neutralises script-capable markup,
 * event-handler attributes and dangerous URL schemes while keeping
 * the safe structural/inline tags an LLM answer legitimately uses.
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect } from 'vitest';

import { sanitizeHTML, __sanitize_test__ } from '/assets/js/core/sanitize.js';

describe('F3-5 — sanitizeHTML() XSS allowlist sanitizer', () => {
    // ── the canonical audit payload ──────────────────────────────────
    it('neutralises <img src="x" onerror="alert(1)"> (the audit payload)', () => {
        const out = sanitizeHTML('<img src="x" onerror="alert(1)">');
        expect(out.toLowerCase()).not.toContain('<img');
        expect(out.toLowerCase()).not.toContain('onerror');
        expect(out).not.toContain('alert(1)');
    });

    // ── script-capable tags are removed with their subtree ───────────
    it('drops <script> tags and their payload entirely', () => {
        const out = sanitizeHTML('before<script>alert(document.cookie)</script>after');
        expect(out.toLowerCase()).not.toContain('<script');
        expect(out).not.toContain('alert(document.cookie)');
        expect(out).toContain('before');
        expect(out).toContain('after');
    });

    it('drops <iframe> elements', () => {
        const out = sanitizeHTML('<iframe src="https://evil.example"></iframe>ok');
        expect(out.toLowerCase()).not.toContain('<iframe');
        expect(out).toContain('ok');
    });

    it('drops <style> elements and their CSS payload', () => {
        const out = sanitizeHTML('<style>body{background:url(javascript:alert(1))}</style>x');
        expect(out.toLowerCase()).not.toContain('<style');
        expect(out).not.toContain('javascript:');
        expect(out).toContain('x');
    });

    it('drops <object> / <embed> resource-loading tags', () => {
        const out = sanitizeHTML('<object data="evil.swf"></object><embed src="evil.swf">');
        expect(out.toLowerCase()).not.toContain('<object');
        expect(out.toLowerCase()).not.toContain('<embed');
    });

    // ── event-handler attributes are stripped from survivors ─────────
    it('strips on* handler attributes from an allowed element', () => {
        const out = sanitizeHTML('<div onclick="steal()" onmouseover="x()">hi</div>');
        expect(out.toLowerCase()).not.toContain('onclick');
        expect(out.toLowerCase()).not.toContain('onmouseover');
        expect(out).toContain('hi');
        expect(out.toLowerCase()).toContain('<div');
    });

    it('strips inline style attributes', () => {
        const out = sanitizeHTML('<p style="position:fixed;top:0">t</p>');
        expect(out.toLowerCase()).not.toContain('style=');
        expect(out).toContain('t');
    });

    // ── dangerous URL schemes on href ────────────────────────────────
    it('neutralises a javascript: href but keeps the <a> element + text', () => {
        const out = sanitizeHTML('<a href="javascript:alert(1)">click</a>');
        expect(out).not.toContain('javascript:');
        expect(out.toLowerCase()).toContain('<a');
        expect(out).toContain('click');
    });

    it('neutralises whitespace-obfuscated javascript: schemes', () => {
        const out = sanitizeHTML('<a href="java\tscript:alert(1)">x</a>');
        expect(out).not.toMatch(/href=/i);
    });

    it('preserves a safe https href', () => {
        const out = sanitizeHTML('<a href="https://learn.microsoft.com">docs</a>');
        expect(out).toContain('https://learn.microsoft.com');
        expect(out).toContain('docs');
    });

    // ── safe markdown-rendered structure survives ────────────────────
    it('keeps the safe tags the LLM markdown renderer emits', () => {
        const md = '<h3>Title</h3><p>A <strong>bold</strong> <code>cmd</code></p>'
            + '<ul><li>one</li><li>two</li></ul>';
        const out = sanitizeHTML(md);
        expect(out).toContain('<h3>');
        expect(out).toContain('<strong>');
        expect(out).toContain('<code>');
        expect(out).toContain('<li>');
        expect(out).toContain('one');
    });

    it('unwraps an unknown tag but preserves its text content', () => {
        const out = sanitizeHTML('<marquee>scrolling text</marquee>');
        expect(out.toLowerCase()).not.toContain('<marquee');
        expect(out).toContain('scrolling text');
    });

    it('passes plain text through unchanged', () => {
        expect(sanitizeHTML('chiller LWT 6-8 C nominal')).toBe('chiller LWT 6-8 C nominal');
    });

    // ── contract / edge cases ────────────────────────────────────────
    it('returns empty string for null / undefined', () => {
        expect(sanitizeHTML(null)).toBe('');
        expect(sanitizeHTML(undefined)).toBe('');
    });

    it('is idempotent — re-sanitising a clean string is a no-op', () => {
        const dirty = '<p onclick="x">hi<script>bad()</script></p>';
        const once = sanitizeHTML(dirty);
        expect(sanitizeHTML(once)).toBe(once);
    });

    it('handles a nested attack (script inside an allowed wrapper)', () => {
        const out = sanitizeHTML('<div><p>safe<iframe></iframe><img onerror="x"></p></div>');
        expect(out.toLowerCase()).not.toContain('<iframe');
        expect(out.toLowerCase()).not.toContain('<img');
        expect(out.toLowerCase()).not.toContain('onerror');
        expect(out).toContain('safe');
    });

    // ── _isDangerousURL unit ─────────────────────────────────────────
    it('_isDangerousURL flags script-capable schemes, allows safe ones', () => {
        const { _isDangerousURL } = __sanitize_test__;
        expect(_isDangerousURL('javascript:alert(1)')).toBe(true);
        expect(_isDangerousURL('JaVaScRiPt:alert(1)')).toBe(true);
        expect(_isDangerousURL('data:text/html,<script>')).toBe(true);
        expect(_isDangerousURL('vbscript:msgbox(1)')).toBe(true);
        expect(_isDangerousURL('https://example.com')).toBe(false);
        expect(_isDangerousURL('/api/health')).toBe(false);
        expect(_isDangerousURL('#anchor')).toBe(false);
    });
});
