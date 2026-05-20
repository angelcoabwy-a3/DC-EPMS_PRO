/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — core/hermes_events.js
 * ROADMAP V11 T3.1 — unified event-driven plane, frontend routing.
 *
 * Subscribes the two NEW Hermes streams and routes them into the HMI:
 *
 *   cmms_alerts      Work-Order mutations + EDGE_HEALING recommendations
 *   agent_consensus  Multi-Agent consensus / Safety-Officer verdicts
 *
 * Each incoming frame is (a) pushed into the reactive store and (b)
 * re-emitted as a decoupled DOM CustomEvent on `document`. Views opt in
 * by binding the state keys or by listening for the events — no view is
 * coupled to this module, so the integration is purely additive: the
 * legacy per-view polling stays in place; retiring it view-by-view is a
 * follow-up bite (the streams run alongside, same pattern as the cutover).
 *
 * State keys written:
 *   cmmsAlerts        last 50 cmms_alerts payloads (newest first)
 *   cmmsAlertCount    running count of cmms_alerts received
 *   edgeHealingAlert  the most recent EDGE_HEALING_RECOMMENDED payload
 *   agentConsensus    last 50 agent_consensus payloads (newest first)
 *
 * DOM events dispatched on `document`:
 *   hermes:cmms-alert         detail = cmms_alerts payload
 *   hermes:edge-healing       detail = EDGE_HEALING_RECOMMENDED payload
 *   hermes:agent-consensus    detail = agent_consensus payload
 *   hermes:optimizer-proposal detail = optimizer_proposal payload (Batch 2.D)
 * ════════════════════════════════════════════════════════════════ */

import { onHermesStream } from '../services/api.js';
import { setState } from './state.js';

const _MAX_RETAINED = 50;

let _initialized = false;
let _cmmsAlerts = [];
let _agentConsensus = [];
let _optimizerProposals = [];
let _cmmsAlertCount = 0;

function _dispatch(name, detail) {
    try {
        document.dispatchEvent(new CustomEvent(name, { detail }));
    } catch (e) {
        console.warn('[hermes-events] dispatch failed:', name, e);
    }
}

function _onCmmsAlert(payload) {
    if (!payload || typeof payload !== 'object') return;
    _cmmsAlerts = [payload, ..._cmmsAlerts].slice(0, _MAX_RETAINED);
    _cmmsAlertCount += 1;
    setState('cmmsAlerts', _cmmsAlerts);
    setState('cmmsAlertCount', _cmmsAlertCount);
    _dispatch('hermes:cmms-alert', payload);
    // Edge-healing recommendations are a distinct, higher-severity signal.
    if (payload.event === 'EDGE_HEALING_RECOMMENDED') {
        setState('edgeHealingAlert', payload);
        _dispatch('hermes:edge-healing', payload);
        console.warn('[hermes-events] EDGE_HEALING_RECOMMENDED',
                     payload.asset_id, 'z=' + payload.max_z,
                     '— CET approval required');
    }
}

function _onAgentConsensus(payload) {
    if (!payload || typeof payload !== 'object') return;
    _agentConsensus = [payload, ..._agentConsensus].slice(0, _MAX_RETAINED);
    setState('agentConsensus', _agentConsensus);
    _dispatch('hermes:agent-consensus', payload);
}

function _onOptimizerProposal(payload) {
    // Epic 2 Batch 2.D — proactive Optimizer events. The backend
    // emit_event payload carries { event, proposal, consensus_verdict,
    // safety_officer_veto, narrative_present } shaped by
    // backend/optimizer.py tick(). The HMI views/optimizer.js listens
    // on the DOM event and refreshes its queue.
    if (!payload || typeof payload !== 'object') return;
    _optimizerProposals = [payload, ..._optimizerProposals].slice(0, _MAX_RETAINED);
    setState('optimizerProposals', _optimizerProposals);
    _dispatch('hermes:optimizer-proposal', payload);
}

/** Public entry — called once from main.js at bootstrap. */
export function initHermesEvents() {
    if (_initialized) return;
    onHermesStream('cmms_alerts', _onCmmsAlert);
    onHermesStream('agent_consensus', _onAgentConsensus);
    onHermesStream('optimizer_proposal', _onOptimizerProposal);
    _initialized = true;
    console.log('[hermes-events] subscribed: cmms_alerts + agent_consensus + optimizer_proposal');
}

// Test surface.
export const __hermes_events_test__ = {
    onCmmsAlert: _onCmmsAlert,
    onAgentConsensus: _onAgentConsensus,
    onOptimizerProposal: _onOptimizerProposal,
    getCmmsAlerts: () => _cmmsAlerts,
    getAgentConsensus: () => _agentConsensus,
    getOptimizerProposals: () => _optimizerProposals,
    reset: () => {
        _cmmsAlerts = [];
        _agentConsensus = [];
        _optimizerProposals = [];
        _cmmsAlertCount = 0;
        _initialized = false;
    },
};
