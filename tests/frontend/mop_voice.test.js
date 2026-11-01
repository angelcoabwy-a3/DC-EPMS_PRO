/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/mop_voice.test.js
 * MOP Verification voice readback: WAV encoder, hold-to-talk mic,
 * M key, sample readbacks, transcript fill + parsed claim.
 *
 * Runs with the normal suite — no server, no network, no Meta calls:
 *   .\node_modules\.bin\vitest.cmd run
 *
 * All fetch traffic is stubbed; microphone APIs are stubbed where the
 * test needs them and absent (happy-dom default) elsewhere.
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect, afterEach, vi } from 'vitest';

import { setDemoState } from '/assets/js/core/demo.js';
import { __mop_verify_test__ as mv } from '/assets/js/views/mop_verify.js';

const DEMO_ON = { active: true, allowed: ['mop-verify'], defaultView: 'mop-verify' };
const DEMO_OFF = { active: false, allowed: ['mop-verify'], defaultView: 'mop-verify' };

const _origFetch = globalThis.fetch;
const _origMediaDevices = (typeof navigator !== 'undefined') ? navigator.mediaDevices : undefined;
const _origAudioContext = (typeof window !== 'undefined') ? window.AudioContext : undefined;
const _origAudio = globalThis.Audio;

afterEach(() => {
    setDemoState(DEMO_OFF);
    mv.reset();
    globalThis.fetch = _origFetch;
    globalThis.Audio = _origAudio;
    try {
        Object.defineProperty(window.navigator, 'mediaDevices', {
            value: _origMediaDevices, configurable: true,
        });
    } catch (_e) { /* navigator without mediaDevices stays that way */ }
    try {
        window.AudioContext = _origAudioContext;
    } catch (_e) { /* ignore */ }
    document.body.innerHTML = '';
});

const flush = () => new Promise((r) => setTimeout(r, 20));

function voiceFixture() {
    document.body.innerHTML = `
        <div class="view" id="view-mop-verify">
            <label class="mv-field"><span class="mv-claim-col"><span class="mv-claim-row">
                <input type="text" data-mv-claim value="">
                <button type="button" data-mv-mic>Hold to talk</button>
                <span data-mv-rec hidden></span>
            </span><span data-mv-parsed></span></span></label>
            <div data-mv-voice-section hidden><div data-mv-voice-samples></div></div>
            <div data-mv-result></div>
            <div data-mv-status></div>
        </div>`;
}

function layoutFixture() {
    document.body.innerHTML = `
        <div class="view" id="view-mop-verify">
            <div class="mv-layout"><div data-mv-mop>classic</div></div>
        </div>`;
}

const STEPS5 = {
    mop_id: 'MOP-UPS-BYP-DEMO-01',
    version: '1.3',
    operated_labels: ['Q5', 'Q7', 'Q9', 'Q8', 'BYP'],
    initial_state: { Q5: 'CLOSED', Q7: 'CLOSED', Q9: 'CLOSED', Q8: 'OPEN', BYP: 'OPEN' },
    steps: [1, 2, 3, 4, 5].map((id) => ({
        step_id: id,
        panel_label: ['BYP', 'Q8', 'Q9', 'Q7', 'Q5'][id - 1],
        action: 'Do step ' + id + '.',
        expected_state: { Q5: 'CLOSED', Q7: 'CLOSED', Q9: 'CLOSED', Q8: 'CLOSED', BYP: 'CLOSED' },
    })),
};

function demoFixture() {
    layoutFixture();
    setDemoState(DEMO_ON);
    mv.setStepsData(STEPS5);
    mv.setSession('sess-voice', 2);
    mv.syncDemoLayout();
}

class FakeAudioContext {
    constructor() {
        this.sampleRate = 48000;
        this.destination = {};
        this.closed = false;
    }
    createMediaStreamSource() { return { connect() {} }; }
    createScriptProcessor() { return { connect() {}, disconnect() {}, onaudioprocess: null }; }
    createGain() { return { gain: { value: 1 }, connect() {}, disconnect() {} }; }
    close() { this.closed = true; }
}

function stubMic() {
    const getUserMedia = vi.fn(async () => ({ getTracks: () => [] }));
    Object.defineProperty(window.navigator, 'mediaDevices', {
        value: { getUserMedia }, configurable: true,
    });
    window.AudioContext = FakeAudioContext;
    return getUserMedia;
}

function ascii(bytes, offset, length) {
    return String.fromCharCode(...bytes.slice(offset, offset + length));
}

describe('mop voice — WAV encoder output', () => {
    it('produces a valid 44-byte header: mono, 24000 Hz, 16 bits', () => {
        const bytes = mv.encodeWav(new Float32Array([0, 0.5, -0.5, 1]), 24000);
        expect(bytes.length).toBe(44 + 4 * 2);
        const view = new DataView(bytes.buffer);
        expect(ascii(bytes, 0, 4)).toBe('RIFF');
        expect(view.getUint32(4, true)).toBe(36 + 8);
        expect(ascii(bytes, 8, 4)).toBe('WAVE');
        expect(ascii(bytes, 12, 4)).toBe('fmt ');
        expect(view.getUint32(16, true)).toBe(16);
        expect(view.getUint16(20, true)).toBe(1);
        expect(view.getUint16(22, true)).toBe(1);
        expect(view.getUint32(24, true)).toBe(24000);
        expect(view.getUint32(28, true)).toBe(48000);
        expect(view.getUint16(32, true)).toBe(2);
        expect(view.getUint16(34, true)).toBe(16);
        expect(ascii(bytes, 36, 4)).toBe('data');
        expect(view.getUint32(40, true)).toBe(8);
        expect(view.getInt16(44, true)).toBe(0);
        expect(view.getInt16(46, true)).toBe(16384);
    });

    it('mixes channels down and resamples across rates', () => {
        const mono = mv.mixdownToMono([new Float32Array([0, 1]), new Float32Array([1, 0])]);
        expect(Array.from(mono)).toEqual([0.5, 0.5]);
        const down = mv.resampleLinear(new Float32Array([0, 1, 0, 1]), 48000, 24000);
        expect(down.length).toBe(2);
    });
});

describe('mop voice — sample readback labels', () => {
    it('labels every sample from its file name, s4 as Step 4: Q7 OFF only', () => {
        expect(mv.humanizeReadbackName('readback_s0_q8_off.wav')).toBe('Step 0: Q8 OFF');
        expect(mv.humanizeReadbackName('readback_s1_byp_on.wav')).toBe('Step 1: BYP ON');
        expect(mv.humanizeReadbackName('readback_s2_q8_on.wav')).toBe('Step 2: Q8 ON');
        expect(mv.humanizeReadbackName('readback_s3_q9_off.wav')).toBe('Step 3: Q9 OFF');
        expect(mv.humanizeReadbackName('readback_s4_q7_off.wav')).toBe('Step 4: Q7 OFF');
        expect(mv.humanizeReadbackName('readback_s5_q5_off.wav')).toBe('Step 5: Q5 OFF');
    });

    it('renders one button per file with the derived label', () => {
        voiceFixture();
        mv.renderVoiceSamples(['readback_s4_q7_off.wav', 'readback_s2_q8_on.wav']);
        const btns = Array.from(document.querySelectorAll('[data-voice-sample]'));
        expect(btns).toHaveLength(2);
        expect(btns[0].textContent).toBe('Step 4: Q7 OFF');
        expect(btns[0].getAttribute('data-voice-sample')).toBe('readback_s4_q7_off.wav');
    });

    it('hides the button whose file is missing, and the section when all are', async () => {
        voiceFixture();
        globalThis.fetch = async (url, options) => {
            if ((options && options.method) === 'HEAD') {
                return { ok: String(url).endsWith('readback_s0_q8_off.wav') };
            }
            throw new Error('unexpected ' + url);
        };
        await mv.probeVoiceSamples();
        const btns = Array.from(document.querySelectorAll('[data-voice-sample]'));
        expect(btns).toHaveLength(1);
        expect(btns[0].textContent).toBe('Step 0: Q8 OFF');
        expect(document.querySelector('[data-mv-voice-section]').hasAttribute('hidden')).toBe(false);

        globalThis.fetch = async () => ({ ok: false, status: 404 });
        await mv.probeVoiceSamples();
        expect(document.querySelector('[data-mv-voice-section]').hasAttribute('hidden')).toBe(true);
    });
});

describe('mop voice — sample readback transcription', () => {
    function stubTranscribe(transcript, claim, rejectionReason) {
        const calls = [];
        const wavBytes = mv.encodeWav(new Float32Array(2400), 24000);
        globalThis.fetch = async (url, options) => {
            const method = (options && options.method) || 'GET';
            calls.push({ url: String(url), method, body: options ? options.body : null });
            if (String(url).startsWith('/assets/demo_audio/')) {
                return { ok: true, status: 200, blob: async () => new Blob([wavBytes], { type: 'audio/wav' }) };
            }
            if (String(url) === mv.TRANSCRIBE_URL && method === 'POST') {
                return {
                    status: 200,
                    ok: true,
                    json: async () => ({
                        transcript, claim, rejection_reason: rejectionReason || null,
                    }),
                };
            }
            throw new Error('unexpected ' + method + ' ' + url);
        };
        return calls;
    }

    it('posts the sample WAV, fills the readback field and shows the parsed claim', async () => {
        voiceFixture();
        const calls = stubTranscribe('step two, Q eight, on,', { label: 'Q8', state: 'CLOSED' });
        mv.renderVoiceSamples(['readback_s2_q8_on.wav']);
        document.querySelector('[data-voice-sample]').click();
        await flush();
        await flush();
        const post = calls.find((c) => c.url === '/api/copilot/mop/transcribe');
        expect(post).toBeTruthy();
        expect(post.method).toBe('POST');
        expect(post.body).toBeInstanceOf(FormData);
        expect(post.body.get('audio')).toBeInstanceOf(Blob);
        expect(document.querySelector('[data-mv-claim]').value).toBe('step two, Q eight, on,');
        expect(document.querySelector('[data-mv-parsed]').textContent).toBe('Parsed: Q8 CLOSED');
    });

    it('shows the rejection reason when the transcript does not parse', async () => {
        voiceFixture();
        stubTranscribe('hello there', null, 'no breaker label or state word heard');
        mv.renderVoiceSamples(['readback_s2_q8_on.wav']);
        document.querySelector('[data-voice-sample]').click();
        await flush();
        await flush();
        expect(document.querySelector('[data-mv-claim]').value).toBe('hello there');
        expect(document.querySelector('[data-mv-parsed]').textContent)
            .toBe('Not understood: no breaker label or state word heard. Say it again or type it.');
    });

    it('never runs Verify automatically after a transcription', async () => {
        voiceFixture();
        const calls = stubTranscribe('step two, Q eight, on,', { label: 'Q8', state: 'CLOSED' });
        mv.renderVoiceSamples(['readback_s2_q8_on.wav']);
        document.querySelector('[data-voice-sample]').click();
        await flush();
        await flush();
        expect(calls.some((c) => c.url === '/api/copilot/mop/verify')).toBe(false);
        expect(document.querySelector('[data-mv-result]').innerHTML).toBe('');
    });
});

describe('mop voice — hold-M key (demo only)', () => {
    it('is ignored inside text fields, on key repeat and on tracker circles', async () => {
        stubMic();
        demoFixture();
        const gum = window.navigator.mediaDevices.getUserMedia;
        const claim = document.querySelector('[data-mv-claim]');
        claim.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'm', bubbles: true }));
        document.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'm', repeat: true, bubbles: true }));
        document.querySelector('.mv-dot').dispatchEvent(
            new window.KeyboardEvent('keydown', { key: 'm', bubbles: true }));
        await flush();
        expect(gum).not.toHaveBeenCalled();
        expect(mv.getState().recording).toBe(false);
    });

    it('starts on keydown and stops on key release', async () => {
        stubMic();
        demoFixture();
        const gum = window.navigator.mediaDevices.getUserMedia;
        document.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'm', bubbles: true }));
        await flush();
        expect(gum).toHaveBeenCalledTimes(1);
        expect(mv.getState().recording).toBe(true);
        document.dispatchEvent(new window.KeyboardEvent('keyup', { key: 'm', bubbles: true }));
        expect(mv.getState().recording).toBe(false);
    });
});

describe('mop voice — microphone unavailable', () => {
    it('disables the mic button with an explanation while samples still work', async () => {
        demoFixture();
        const mic = document.querySelector('[data-mv-mic]');
        expect(mic.disabled).toBe(true);
        expect(mic.textContent).toBe('Mic unavailable');
        expect(mic.title).toContain('sample readback');
        globalThis.fetch = async () => ({ ok: true });
        await mv.probeVoiceSamples();
        expect(document.querySelectorAll('[data-voice-sample]')).toHaveLength(6);
    });
});

describe('mop voice — sample playback', () => {
    class FakeAudio {
        constructor(src) {
            this.src = src;
            this.playCalls = 0;
            this.pauseCalls = 0;
            FakeAudio.instances.push(this);
        }
        play() { this.playCalls += 1; return Promise.resolve(); }
        pause() { this.pauseCalls += 1; }
        addEventListener() {}
        removeAttribute() {}
        load() {}
    }
    FakeAudio.instances = [];

    function stubSampleFetch() {
        const wavBytes = mv.encodeWav(new Float32Array(2400), 24000);
        globalThis.fetch = async (url, options) => {
            const method = (options && options.method) || 'GET';
            if (String(url).startsWith('/assets/demo_audio/')) {
                return { ok: true, status: 200, blob: async () => new Blob([wavBytes], { type: 'audio/wav' }) };
            }
            if (String(url) === mv.TRANSCRIBE_URL && method === 'POST') {
                return {
                    status: 200,
                    ok: true,
                    json: async () => ({
                        transcript: 'step two, Q eight, on,',
                        claim: { label: 'Q8', state: 'CLOSED' },
                        rejection_reason: null,
                    }),
                };
            }
            throw new Error('unexpected ' + method + ' ' + url);
        };
    }

    it('creates an audio element with that file and calls play()', async () => {
        FakeAudio.instances = [];
        globalThis.Audio = FakeAudio;
        voiceFixture();
        stubSampleFetch();
        mv.renderVoiceSamples(['readback_s2_q8_on.wav']);
        document.querySelector('[data-voice-sample]').click();
        expect(FakeAudio.instances).toHaveLength(1);
        expect(FakeAudio.instances[0].src).toBe('/assets/demo_audio/readback_s2_q8_on.wav');
        expect(FakeAudio.instances[0].playCalls).toBe(1);
        const status = document.querySelector('[data-voice-status="readback_s2_q8_on.wav"]');
        expect(status.hasAttribute('hidden')).toBe(false);
        expect(status.textContent).toBe('Playing sample');
        await flush();
        await flush();
    });

    it('a second click stops the first playback', () => {
        FakeAudio.instances = [];
        globalThis.Audio = FakeAudio;
        voiceFixture();
        stubSampleFetch();
        mv.renderVoiceSamples(['readback_s0_q8_off.wav', 'readback_s2_q8_on.wav']);
        const btns = document.querySelectorAll('[data-voice-sample]');
        btns[0].click();
        btns[1].click();
        expect(FakeAudio.instances).toHaveLength(2);
        expect(FakeAudio.instances[0].pauseCalls).toBe(1);
        expect(FakeAudio.instances[1].playCalls).toBe(1);
    });

    it('transcription still runs if play() rejects', async () => {
        class RejectAudio extends FakeAudio {
            play() { this.playCalls += 1; return Promise.reject(new Error('autoplay blocked')); }
        }
        FakeAudio.instances = [];
        globalThis.Audio = RejectAudio;
        voiceFixture();
        stubSampleFetch();
        mv.renderVoiceSamples(['readback_s2_q8_on.wav']);
        document.querySelector('[data-voice-sample]').click();
        await flush();
        await flush();
        expect(document.querySelector('[data-mv-claim]').value).toBe('step two, Q eight, on,');
        expect(document.querySelector('[data-mv-parsed]').textContent).toBe('Parsed: Q8 CLOSED');
        const status = document.querySelector('[data-voice-status="readback_s2_q8_on.wav"]');
        expect(status.hasAttribute('hidden')).toBe(true);
        expect(status.textContent).toBe('');
    });
});

describe('mop voice — stale rate-limit countdown clears on success', () => {
    it('a successful transcription clears the countdown and re-enables Verify', async () => {
        voiceFixture();
        document.getElementById('view-mop-verify')
            .insertAdjacentHTML('beforeend', '<button type="button" data-mv-verify-btn></button>');
        mv.setStepsData(STEPS5);
        mv.setSession('sess-1', 2);
        mv.setPhotoForTest(new Blob(['x'], { type: 'image/jpeg' }), 'p.jpg', 100, 100);
        const btn = document.querySelector('[data-mv-verify-btn]');
        btn.disabled = false;
        let mode = 'limited';
        globalThis.fetch = async (url) => {
            if (String(url) !== mv.TRANSCRIBE_URL) throw new Error('unexpected ' + url);
            if (mode === 'limited') {
                return {
                    status: 429,
                    ok: false,
                    headers: { get: (n) => (n === 'Retry-After' ? '120' : null) },
                    json: async () => ({
                        limit: 'per_ip', daily_cap: 50, meta_call_made: false,
                        detail: 'limited', retry_after_s: 120,
                    }),
                };
            }
            return {
                status: 200,
                ok: true,
                headers: { get: () => null },
                json: async () => ({
                    transcript: 'step two, Q eight, on,',
                    claim: { label: 'Q8', state: 'CLOSED' },
                    rejection_reason: null,
                }),
            };
        };
        await mv.transcribeWav(new Blob(['x'], { type: 'audio/wav' }), 'readback.wav');
        expect(btn.disabled).toBe(true);
        expect(document.querySelector('[data-mv-status]').textContent).toContain('Rate limited: retry in');
        mode = 'open';
        await mv.transcribeWav(new Blob(['x'], { type: 'audio/wav' }), 'readback.wav');
        expect(document.querySelector('[data-mv-status]').textContent).toBe('');
        expect(btn.disabled).toBe(false);
        expect(document.querySelector('[data-mv-claim]').value).toBe('step two, Q eight, on,');
    });
});

describe('mop voice — stale error card clears on success', () => {
    it('a successful transcription removes the old network error card', async () => {
        voiceFixture();
        globalThis.fetch = async () => { throw new Error('down'); };
        await mv.transcribeWav(new Blob(['x'], { type: 'audio/wav' }), 'readback.wav');
        expect(document.querySelector('[data-mv-result]').textContent).toContain('No transcript was produced');
        globalThis.fetch = async () => ({
            status: 200,
            ok: true,
            headers: { get: () => null },
            json: async () => ({
                transcript: 'step two, Q eight, on,',
                claim: { label: 'Q8', state: 'CLOSED' },
                rejection_reason: null,
            }),
        });
        await mv.transcribeWav(new Blob(['x'], { type: 'audio/wav' }), 'readback.wav');
        expect(document.querySelector('[data-mv-result]').querySelector('.mv-banner')).toBeNull();
        expect(document.querySelector('[data-mv-claim]').value).toBe('step two, Q eight, on,');
    });
});
