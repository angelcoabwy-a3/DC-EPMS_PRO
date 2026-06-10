/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — core/node_registry.js
 * Diagram Rebuild Batch 0 — canonical node identity registry.
 *
 * One physical asset, one canonical entry. Before this module the
 * same utility intake was `util_a` (Power SLD), `utility_north`
 * (/api/topology/state) and `utility_feed_a` (/api/site/graph) and
 * every view kept its own private mapping table — which made
 * cross-view linking structurally impossible.
 *
 * Grounded against the LIVE backend (2026-06-10):
 *   - /api/topology/state  hld_nodes keys   -> `topo`
 *   - /api/site/graph      node ids         -> `graph`
 * Phase 2 (Building D, Path C2 design): the graph already models
 * utility_feed_d -> mv_rectifier_d -> sscb_d_01 -> main_bus_dc_d ->
 * { bess_d_01, rpp_d_01, rpp_d_02 }. Vocabulary fence (S-VOCAB-01):
 * everything downstream of the MV Rectifier is 800 VDC UNIPOLAR
 * TN-S — labels in this registry are the single source the views
 * render, so the fence is enforced HERE, once.
 *
 * Channel bindings: `channels` lists the explicit Kalman channel-id
 * prefixes owned by the node. Views must match channels with
 * matchesChannel() (prefix discipline) — NOT substring .includes(),
 * which made `ups_a` swallow a hypothetical `ups_a1_*` channel.
 * ════════════════════════════════════════════════════════════════ */

/**
 * @typedef {Object} NodeEntry
 * @property {string}   id        canonical id (also the SLD node id)
 * @property {string}   label     display label (panel-grade vocabulary)
 * @property {string}   type      diagram_kit symbol type
 * @property {1|2}      phase     deployment phase (2 = Building D design)
 * @property {string}   chain     'power' | 'cooling' | 'it'
 * @property {?string}  topo      /api/topology/state hld_nodes key
 * @property {string[]} graph     /api/site/graph node id(s)
 * @property {string[]} channels  Kalman channel-id prefixes
 */

/** @type {NodeEntry[]} */
const ENTRIES = [
    // ── Phase 1 power chain — path A (480 VAC, 3-phase) ──────────
    { id: 'util_a',   label: 'UTILITY A',            type: 'util',   phase: 1, chain: 'power',   topo: 'utility_north', graph: ['utility_feed_a'],              channels: ['util_a', 'utility_north'] },
    { id: 'xfmr_a',   label: 'XFMR A',               type: 'xfmr',   phase: 1, chain: 'power',   topo: 'xfmr_a',        graph: ['xfmr_a'],                      channels: ['xfmr_a'] },
    { id: 'genset_a', label: 'GENSET A',             type: 'genset', phase: 1, chain: 'power',   topo: null,            graph: ['genset_a_01', 'genset_a_02'],  channels: ['genset_a'] },
    { id: 'par_bus_a', label: 'PARALLELING BUS · N+1', type: 'parbus', phase: 1, chain: 'power', topo: null,            graph: [],                              channels: [] },
    { id: 'ats_a',    label: 'ATS-A',                type: 'ats',    phase: 1, chain: 'power',   topo: null,            graph: ['ats_a'],                       channels: ['ats_a'] },
    { id: 'ups_a',    label: 'UPS GALAXY VX A',      type: 'ups',    phase: 1, chain: 'power',   topo: 'ups_a',         graph: ['ups_a'],                       channels: ['ups_a'] },
    { id: 'batt_a',   label: 'BATTERY A',            type: 'batt',   phase: 1, chain: 'power',   topo: 'ups_a',         graph: [],                              channels: ['batt_a'] },
    { id: 'rpp_a1',   label: 'RPP / PDU A',          type: 'rpp',    phase: 1, chain: 'power',   topo: 'rpp_a1',        graph: ['rpp_a_01'],                    channels: ['rpp_a1'] },
    { id: 'rpp_a2',   label: 'RPP / PDU A2',         type: 'rpp',    phase: 1, chain: 'power',   topo: 'rpp_a2',        graph: ['rpp_a_02'],                    channels: ['rpp_a2'] },
    { id: 'busway_a', label: 'BUSWAY A',             type: 'busway', phase: 1, chain: 'power',   topo: 'busway_a',      graph: ['busway_a_01', 'busway_a_02'],  channels: ['busway_a'] },

    // ── Phase 1 power chain — path B (2N mirror) ─────────────────
    { id: 'util_b',   label: 'UTILITY B',            type: 'util',   phase: 1, chain: 'power',   topo: 'utility_south', graph: ['utility_feed_b'],              channels: ['util_b', 'utility_south'] },
    { id: 'xfmr_b',   label: 'XFMR B',               type: 'xfmr',   phase: 1, chain: 'power',   topo: 'xfmr_b',        graph: ['xfmr_b'],                      channels: ['xfmr_b'] },
    { id: 'genset_b', label: 'GENSET B',             type: 'genset', phase: 1, chain: 'power',   topo: null,            graph: ['genset_b_01', 'genset_b_02'],  channels: ['genset_b'] },
    { id: 'par_bus_b', label: 'PARALLELING BUS · N+1', type: 'parbus', phase: 1, chain: 'power', topo: null,            graph: [],                              channels: [] },
    { id: 'ats_b',    label: 'ATS-B',                type: 'ats',    phase: 1, chain: 'power',   topo: null,            graph: ['ats_b'],                       channels: ['ats_b'] },
    { id: 'ups_b',    label: 'UPS GALAXY VX B',      type: 'ups',    phase: 1, chain: 'power',   topo: 'ups_b',         graph: ['ups_b'],                       channels: ['ups_b'] },
    { id: 'batt_b',   label: 'BATTERY B',            type: 'batt',   phase: 1, chain: 'power',   topo: 'ups_b',         graph: [],                              channels: ['batt_b'] },
    { id: 'rpp_b1',   label: 'RPP / PDU B',          type: 'rpp',    phase: 1, chain: 'power',   topo: 'rpp_b1',        graph: ['rpp_b_01'],                    channels: ['rpp_b1'] },
    { id: 'rpp_b2',   label: 'RPP / PDU B2',         type: 'rpp',    phase: 1, chain: 'power',   topo: 'rpp_b2',        graph: ['rpp_b_02'],                    channels: ['rpp_b2'] },
    { id: 'busway_b', label: 'BUSWAY B',             type: 'busway', phase: 1, chain: 'power',   topo: 'busway_b',      graph: ['busway_b_01', 'busway_b_02'],  channels: ['busway_b'] },

    // ── Phase 2 power chain — Building D (Path C2 design) ────────
    // Upstream of the MV Rectifier: 35 kV 3-phase AC. Downstream:
    // 800 VDC UNIPOLAR TN-S (no phases). S-VOCAB-01 fence.
    { id: 'util_d',   label: 'UTILITY D · 35 kV AC', type: 'util',     phase: 2, chain: 'power', topo: null, graph: ['utility_feed_d'], channels: ['util_d', 'utility_feed_d'] },
    { id: 'mv_rect_d', label: 'MV RECTIFIER',        type: 'rectifier', phase: 2, chain: 'power', topo: null, graph: ['mv_rectifier_d'], channels: ['mv_rect'] },
    { id: 'sscb_d',   label: 'SSCB · IEC 60947-2',   type: 'sscb',     phase: 2, chain: 'power', topo: null, graph: ['sscb_d_01'],      channels: ['sscb_d'] },
    { id: 'dc_bus_d', label: '800 VDC BUS · UNIPOLAR TN-S', type: 'dcbus', phase: 2, chain: 'power', topo: null, graph: ['main_bus_dc_d'], channels: ['dc_bus'] },
    { id: 'bess_d',   label: 'BESS 2.5 MWh',         type: 'bess',     phase: 2, chain: 'power', topo: null, graph: ['bess_d_01'],      channels: ['bess_d'] },
    { id: 'rpp_d1',   label: 'RPP D1',               type: 'rpp',      phase: 2, chain: 'power', topo: null, graph: ['rpp_d_01'],       channels: ['rpp_d1'] },
    { id: 'rpp_d2',   label: 'RPP D2',               type: 'rpp',      phase: 2, chain: 'power', topo: null, graph: ['rpp_d_02'],       channels: ['rpp_d2'] },
    { id: 'hall_d',   label: 'GB300 NVL144 · 250 RACKS @ 200 kW', type: 'hall', phase: 2, chain: 'it', topo: null, graph: [], channels: ['hall_d'] },

    // ── Cooling chain (Phase 1) ──────────────────────────────────
    { id: 'cooling_tower', label: 'COOLING TOWER',   type: 'tower',   phase: 1, chain: 'cooling', topo: 'cooling_tower', graph: ['cooling_tower_field_a', 'cooling_tower_field_b'], channels: ['cooling_tower', 'ct_'] },
    { id: 'chiller_1', label: 'CHILLER 1',           type: 'chiller', phase: 1, chain: 'cooling', topo: 'chiller_1',     graph: ['chiller_1'],  channels: ['chiller_1'] },
    { id: 'chiller_2', label: 'CHILLER 2 · N+1',     type: 'chiller', phase: 1, chain: 'cooling', topo: 'chiller_2',     graph: ['chiller_2'],  channels: ['chiller_2'] },
    { id: 'chwp_1',   label: 'CHW PUMP A',           type: 'pump',    phase: 1, chain: 'cooling', topo: null,            graph: [],             channels: ['chwp_1'] },
    { id: 'chwp_2',   label: 'CHW PUMP B',           type: 'pump',    phase: 1, chain: 'cooling', topo: null,            graph: [],             channels: ['chwp_2'] },
    { id: 'cdu_a',    label: 'CDU-A',                type: 'cdu',     phase: 1, chain: 'cooling', topo: 'cdu_a',         graph: ['cdu_a'],      channels: ['cdu_a'] },
    { id: 'cdu_b',    label: 'CDU-B',                type: 'cdu',     phase: 1, chain: 'cooling', topo: 'cdu_b',         graph: ['cdu_b'],      channels: ['cdu_b'] },

    // ── IT load (Phase 1) ────────────────────────────────────────
    { id: 'hall_1',   label: 'DATA HALL 1',          type: 'hall',    phase: 1, chain: 'it', topo: 'hall_1', graph: [], channels: ['hall_1'] },
    { id: 'hall_2',   label: 'DATA HALL 2',          type: 'hall',    phase: 1, chain: 'it', topo: 'hall_2', graph: [], channels: ['hall_2'] },
    { id: 'hall_3',   label: 'DATA HALL 3',          type: 'hall',    phase: 1, chain: 'it', topo: 'hall_3', graph: [], channels: ['hall_3'] },
];

// ─── Indexes (built once) ──────────────────────────────────────────
const _byId = new Map(ENTRIES.map((e) => [e.id, e]));
const _byGraph = new Map();
const _byTopo = new Map();
for (const e of ENTRIES) {
    for (const g of e.graph) _byGraph.set(g, e);
    // First entry wins for shared topo keys (batt_a aliases ups_a).
    if (e.topo && !_byTopo.has(e.topo)) _byTopo.set(e.topo, e);
}

// ─── Lookups ───────────────────────────────────────────────────────
export function getNode(id) { return _byId.get(id) || null; }

/** Canonical id -> /api/topology/state hld_nodes key (or null). */
export function topoKeyFor(id) { return _byId.get(id)?.topo ?? null; }

/** /api/site/graph node id -> canonical entry (or null). */
export function nodeForGraphId(graphId) { return _byGraph.get(graphId) || null; }

/** /api/topology/state hld key -> canonical entry (or null). */
export function nodeForTopoKey(topoKey) { return _byTopo.get(topoKey) || null; }

/** All entries for a phase / chain (both optional). */
export function nodesWhere({ phase, chain } = {}) {
    return ENTRIES.filter((e) =>
        (phase === undefined || e.phase === phase)
        && (chain === undefined || e.chain === chain));
}

/** Legacy view-mapping shape: { sldId: topoKey } for severity binders. */
export function sldToTopoMap() {
    const out = {};
    for (const e of ENTRIES) if (e.topo) out[e.id] = e.topo;
    return out;
}

/**
 * Channel-prefix discipline. A channel id belongs to a node iff it
 * EQUALS one of the node's prefixes or starts with `<prefix>_`.
 * This is the fix for the substring fragility where node `ups_a`
 * also swallowed channels of a hypothetical `ups_a1`.
 */
export function matchesChannel(channelId, prefixes) {
    const c = String(channelId || '').toLowerCase();
    for (const p of prefixes || []) {
        const pl = String(p).toLowerCase();
        if (c === pl || c.startsWith(pl + '_')) return true;
    }
    return false;
}

/** Channel prefixes for a canonical id ([] when unknown). */
export function channelPrefixesFor(id) { return _byId.get(id)?.channels ?? []; }

export const __registry_test__ = { ENTRIES };
