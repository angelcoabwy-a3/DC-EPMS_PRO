/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/copilot.test.js
 * ROADMAP V11 T2.1 Phase 3 — verifies the extracted Facility Co-Pilot.
 *
 * Behaviour-preserving extraction smoke test PLUS the F3-5 XSS gate:
 * every LLM-authored surface (chat replies, tool traces) must route
 * through core/sanitize.js — a hostile <script>/<img onerror> payload
 * must not survive into the DOM. The structured draft-card UI keeps
 * its per-value escapeHTML defence. No browser, no backend.
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect, afterEach } from 'vitest';

import { __copilot_test__ } from '/assets/js/views/copilot.js';

const { appendCopilotMessage, renderToolTrace, renderDraftCard,
    onAgentConsensus, reset } = __copilot_test__;

function mountChat(visible = true) {
    document.body.innerHTML =
        `<div id="view-copilot"${visible ? '' : ' hidden'}>`
        + '<div id="copilot-messages"></div></div>';
}

afterEach(() => {
    reset();
    document.body.innerHTML = '';
});

describe('T2.1 Phase 3 — views/copilot.js chat surface', () => {
    it('appends an LLM reply and renders **bold** / `code` markdown', () => {
        mountChat();
        appendCopilotMessage('assistant', 'Chiller **2** is at `4.2` COP');
        const msg = document.querySelector('.copilot-msg-assistant');
        expect(msg).not.toBeNull();
        expect(msg.querySelector('strong').textContent).toBe('2');
        expect(msg.querySelector('code').textContent).toBe('4.2');
    });

    it('neutralises a hostile <script> in a pre-built HTML reply (F3-5)', () => {
        mountChat();
        appendCopilotMessage('assistant',
            'status<script>window.__pwned=1<\/script><b>ok</b>', { html: true });
        const messages = document.getElementById('copilot-messages');
        expect(messages.querySelector('script')).toBeNull();
        expect(window.__pwned).toBeUndefined();
    });

    it('escapes an <img onerror> injected via an LLM text reply (F3-5)', () => {
        mountChat();
        appendCopilotMessage('assistant', 'see <img src=x onerror=alert(1)>');
        const messages = document.getElementById('copilot-messages');
        expect(messages.querySelector('img')).toBeNull();
        expect(messages.textContent).toContain('<img src=x onerror=alert(1)>');
    });

    it('renderToolTrace lists tool calls with escaped arguments', () => {
        mountChat();
        renderToolTrace([
            { tool: 'get_telemetry', args: { ch: '<x>' }, result_summary: '238 channels' },
        ]);
        const trace = document.querySelector('.copilot-tool-trace');
        expect(trace).not.toBeNull();
        expect(trace.textContent).toContain('get_telemetry');
        expect(trace.textContent).toContain('238 channels');
        expect(trace.querySelector('x')).toBeNull();
    });
});

describe('T2.1 Phase 3 — views/copilot.js draft cards', () => {
    it('renders a CMMS work-order card with the three action buttons', () => {
        const html = renderDraftCard({
            draft_id: 'd-1234abcd', kind: 'cmms_work_order',
            rationale: 'CDU pressure trending low', expires_at_unix: (Date.now() / 1000) + 600,
            metadata: { lor: 2, procedure_class: 'MOP', work_class: 'B',
                issue_summary: 'CDU-A delta-P drift' },
        });
        document.body.innerHTML = `<div>${html}</div>`;
        expect(document.querySelector('.copilot-draft-approve')).not.toBeNull();
        expect(document.querySelector('.copilot-draft-reject')).not.toBeNull();
        expect(document.querySelector('.copilot-draft-inspect')).not.toBeNull();
        expect(document.querySelector('.copilot-draft-approve').dataset.draftId)
            .toBe('d-1234abcd');
    });

    it('escapes a hostile issue_summary in the draft card (XSS defence)', () => {
        const html = renderDraftCard({
            draft_id: 'd-evil', kind: 'cmms_work_order', rationale: 'x',
            expires_at_unix: (Date.now() / 1000) + 600,
            metadata: { issue_summary: '<img src=x onerror=alert(1)>' },
        });
        expect(html).not.toContain('<img src=x');
        expect(html).toContain('&lt;img');
    });
});

describe('T2.1 Phase 3 — views/copilot.js Hermes EDA wiring', () => {
    it('surfaces a resolved multi-agent consensus into the visible chat', () => {
        mountChat(true);
        onAgentConsensus({ detail: { content: 'pre-cool plan approved', veto_active: false } });
        const msg = document.querySelector('.copilot-msg-assistant');
        expect(msg.textContent).toContain('Multi-agent consensus');
        expect(msg.textContent).toContain('pre-cool plan approved');
    });

    it('flags an active Safety Officer veto in the consensus message', () => {
        mountChat(true);
        onAgentConsensus({ detail: { event: 'EOP-ABORT', veto_active: true } });
        expect(document.querySelector('.copilot-msg-assistant').textContent)
            .toContain('SAFETY VETO');
    });

    it('is a no-op when the Co-Pilot view is hidden', () => {
        mountChat(false);
        onAgentConsensus({ detail: { content: 'ignored' } });
        expect(document.querySelector('.copilot-msg-assistant')).toBeNull();
    });
});
