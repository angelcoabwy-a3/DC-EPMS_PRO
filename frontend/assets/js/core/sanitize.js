/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — frontend/assets/js/core/sanitize.js
 * E2E Security Audit F3-5 — client-side XSS sanitizer.
 *
 * Vanilla, zero-dependency HTML sanitizer. No DOMPurify, no CDN: the
 * platform ships no bundler and the demo runs air-gapped (ADR-006
 * deterministic sandbox), so an audited ~120-LOC allowlist sanitizer
 * is preferable to vendoring + trusting a 3rd-party library.
 *
 * THREAT MODEL
 *   AI/LLM-authored text (troubleshoot answers, agent output) is
 *   attacker-influenceable: a poisoned RAG corpus chunk or a prompt-
 *   injected uploaded document could make the model emit
 *   `<img src=x onerror=alert(document.cookie)>`. Any such payload
 *   that reaches innerHTML executes in the operator's HMI session.
 *
 * DESIGN
 *   - Parse the dirty string inside an inert <template>. A template's
 *     .content fragment is NOT rendered; its <img>/<script>/<iframe>
 *     do NOT load resources or execute on parse.
 *   - Walk the fragment depth-first:
 *       * elements on TAG_DROP   -> removed with their whole subtree
 *       * elements on TAG_ALLOW  -> kept, attributes scrubbed
 *       * any other element      -> unwrapped (text kept, tag dropped)
 *   - On survivors: drop every attribute not on ATTR_ALLOW (kills all
 *     on* handlers + style), and neutralise javascript:/data:/vbscript:
 *     URIs on href.
 *
 * USAGE — final-stage gate on AI payloads before innerHTML:
 *     import { sanitizeHTML } from '../core/sanitize.js';
 *     el.innerHTML = sanitizeHTML(renderMarkdown(llmAnswer));
 * ════════════════════════════════════════════════════════════════ */

// Inline/structural formatting an LLM answer legitimately needs.
// Everything here is textual — no script-bearing, no resource-loading.
const TAG_ALLOW = new Set([
    'A', 'ABBR', 'B', 'BLOCKQUOTE', 'BR', 'CODE', 'DD', 'DIV', 'DL', 'DT',
    'EM', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'HR', 'I', 'LI', 'OL', 'P',
    'PRE', 'SMALL', 'SPAN', 'STRONG', 'SUB', 'SUP', 'TABLE', 'TBODY', 'TD',
    'TH', 'THEAD', 'TR', 'U', 'UL',
]);

// Elements removed *with their entire subtree* — their text content is
// script/style source or otherwise must never surface.
const TAG_DROP = new Set([
    'SCRIPT', 'STYLE', 'IFRAME', 'OBJECT', 'EMBED', 'NOSCRIPT', 'TEMPLATE',
    'SVG', 'MATH', 'HEAD', 'TITLE', 'LINK', 'META', 'BASE', 'FORM', 'INPUT',
    'BUTTON', 'TEXTAREA', 'SELECT', 'OPTION', 'IMG', 'PICTURE', 'SOURCE',
    'VIDEO', 'AUDIO', 'CANVAS', 'APPLET', 'FRAME', 'FRAMESET', 'PORTAL',
]);

// The only attributes allowed to survive on a kept element. Note the
// ABSENCE of every on* handler, of `style`, and of `id` (id clobbering).
const ATTR_ALLOW = new Set([
    'href', 'title', 'alt', 'class', 'colspan', 'rowspan', 'lang', 'dir',
    'start',
]);

const NODE_ELEMENT = 1;
const NODE_TEXT = 3;

// C0 control chars (0x00-0x1F) + space (0x20) — stripped from URLs
// before scheme matching so `java\tscript:` / `java\nscript:` style
// tricks cannot slip past the dangerous-scheme test. Built via the
// RegExp constructor to keep this source file pure-ASCII.
const URL_NOISE = new RegExp('[\\u0000-\\u0020]+', 'g');

/** True if a URL value carries a script-capable scheme. Control chars
 *  and whitespace are stripped first; HTML entities are already
 *  decoded by the parser into attr.value. */
function _isDangerousURL(value) {
    const normalized = String(value).replace(URL_NOISE, '').toLowerCase();
    return /^(?:javascript|vbscript|data|file):/.test(normalized);
}

/** Depth-first scrub of a parent node's children, mutating in place. */
function _scrub(parent) {
    // Snapshot childNodes: the live list mutates as we remove/unwrap.
    for (const node of Array.from(parent.childNodes)) {
        if (node.nodeType === NODE_TEXT) continue;        // text is inert
        if (node.nodeType !== NODE_ELEMENT) {             // comments, etc.
            node.remove();
            continue;
        }
        const tag = (node.tagName || '').toUpperCase();

        if (TAG_DROP.has(tag)) {
            node.remove();                                 // subtree gone
            continue;
        }

        if (!TAG_ALLOW.has(tag)) {
            // Unknown-but-not-lethal tag: keep its (scrubbed) text,
            // discard the element itself.
            _scrub(node);
            while (node.firstChild) parent.insertBefore(node.firstChild, node);
            node.remove();
            continue;
        }

        // Allowed element: strip every non-allowlisted attribute (this
        // removes all on* handlers + style), then sanitise URL attrs.
        for (const attr of Array.from(node.attributes)) {
            const name = attr.name.toLowerCase();
            if (!ATTR_ALLOW.has(name)) {
                node.removeAttribute(attr.name);
                continue;
            }
            if (name === 'href' && _isDangerousURL(attr.value)) {
                node.removeAttribute(attr.name);
            }
        }
        _scrub(node);                                      // recurse
    }
}

/**
 * HTML-escape a value for safe text interpolation. The shared escaper —
 * view modules import this (aliased to `_escape`) instead of each
 * re-declaring a local copy (Phase 1 structural compaction). null /
 * undefined collapse to '' (matching every prior per-view copy). Also
 * serves as sanitizeHTML()'s escape-only fallback in a non-DOM context.
 */
export function escapeHTML(s) {
    if (s === null || s === undefined) return '';
    return String(s).replace(/[&<>"']/g, (c) => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
}

/**
 * Sanitise an untrusted HTML string into an XSS-safe HTML string.
 * Safe structural/inline tags survive; script-capable tags, event
 * handlers and dangerous URL schemes are stripped. Idempotent.
 *
 * @param {string} dirty  untrusted HTML (e.g. LLM-rendered markdown)
 * @returns {string}      sanitised HTML, safe for innerHTML
 */
export function sanitizeHTML(dirty) {
    if (dirty === null || dirty === undefined) return '';
    const input = String(dirty);
    if (typeof document === 'undefined' || !document.createElement) {
        return escapeHTML(input);                          // defensive fallback
    }
    const tpl = document.createElement('template');
    tpl.innerHTML = input;            // inert: nothing loads or executes
    _scrub(tpl.content);
    return tpl.innerHTML;
}

export const __sanitize_test__ = { _isDangerousURL, escapeHTML, TAG_ALLOW, TAG_DROP };

export default sanitizeHTML;
