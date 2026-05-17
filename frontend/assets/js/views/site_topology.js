/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — views/site_topology.js
 *
 * Tier A / A1: Force-directed topology graph.
 *
 * Custom Verlet/spring simulation in SVG (no external deps). 91 nodes
 * + ~68 edges converges in ~50-80 iterations, ~30 ms total. Cheaper
 * than including d3-force (~300 KB) for a graph this size.
 *
 * Forces:
 *   - Coulomb-like repulsion (all pairs, O(N²) but N=91 so ~8k ops)
 *   - Spring attraction along edges (Hooke's law, rest length 80px)
 *   - Centering (weak pull toward viewbox center)
 *
 * Discipline:
 *   - Severity-coded by component type (utility, ups, chiller, ...)
 *   - Click a node → highlight its impact_set + dim everything else
 *   - Drag a node → pin its position (alt+click to unpin)
 *   - Re-layout button restarts physics with new random seeds
 *   - Pan/zoom via wheel + drag on empty space
 *
 * Routing (LOTO pattern): the legacy router has the `site_topology`
 * branch declared but doesn't initialize this graph. We hook the
 * nav-item click here and run our own initialization.
 * ════════════════════════════════════════════════════════════════ */

import { registerRoute } from '../core/router.js';

const API_BASE = '';

// ─── Force simulation constants ──────────────────────────────────
const SIM_ITERATIONS = 220;       // total ticks before settling
const REPULSION = 1800;           // Coulomb-like, k/r^2
const SPRING_K = 0.04;            // spring stiffness
const SPRING_REST = 95;           // rest length (px)
const CENTER_PULL = 0.0035;       // weak gravitation to centre
const DAMPING = 0.86;             // velocity damping per tick
const MIN_DIST = 18;              // floor to avoid singularity

// ─── Node radius + colour by component type ──────────────────────
// Operations grading: critical infrastructure gets larger + cyan-leaning;
// IT load is small + dim-cyan; utility/genset are amber (input flexibility).
const TYPE_STYLE = {
    utility_intake:      { r: 14, fill: '#f59e0b', stroke: '#fbbf24', shape: 'square'   },
    genset:              { r: 12, fill: '#f59e0b', stroke: '#fbbf24', shape: 'square'   },
    fuel_tank:           { r:  8, fill: '#9ca3af', stroke: '#d1d5db', shape: 'square'   },
    transformer:         { r: 10, fill: '#10b981', stroke: '#34d399', shape: 'diamond'  },
    switchgear:          { r: 10, fill: '#10b981', stroke: '#34d399', shape: 'circle'   },
    ats:                 { r:  9, fill: '#10b981', stroke: '#34d399', shape: 'diamond'  },
    ups:                 { r: 14, fill: '#00B8D4', stroke: '#5eead4', shape: 'circle'   },
    rpp:                 { r:  8, fill: '#00B8D4', stroke: '#67e8f9', shape: 'square'   },
    busway:              { r:  6, fill: '#0891b2', stroke: '#06b6d4', shape: 'circle'   },
    bms_panel:           { r:  7, fill: '#a855f7', stroke: '#c084fc', shape: 'diamond'  },
    chiller:             { r: 13, fill: '#0ea5e9', stroke: '#7dd3fc', shape: 'circle'   },
    cooling_tower:       { r: 11, fill: '#0ea5e9', stroke: '#7dd3fc', shape: 'square'   },
    cooling_tower_field: { r: 11, fill: '#0ea5e9', stroke: '#7dd3fc', shape: 'square'   },
    cdu:                 { r: 10, fill: '#06b6d4', stroke: '#22d3ee', shape: 'square'   },
    pump:                { r:  7, fill: '#06b6d4', stroke: '#22d3ee', shape: 'circle'   },
    it_rack:             { r:  4, fill: '#475569', stroke: '#64748b', shape: 'circle'   },
    workstation:         { r:  5, fill: '#64748b', stroke: '#94a3b8', shape: 'square'   },
    sensor:              { r:  3, fill: '#64748b', stroke: '#94a3b8', shape: 'circle'   },
    other:               { r:  6, fill: '#64748b', stroke: '#94a3b8', shape: 'circle'   },
};
function styleFor(type) { return TYPE_STYLE[type] || TYPE_STYLE.other; }

// ─── Module state ────────────────────────────────────────────────
let _data = { nodes: [], edges: [] };
let _byId = new Map();
let _activeChain = 'all';
let _selectedId = null;
let _zoom = 1;
let _panX = 0, _panY = 0;
let _initialized = false;
let _viewBox = { w: 1100, h: 620 };

// Tier A+ / A1' state
let _searchTerm = '';
let _pathColorOn = false;
let _pathByNode = new Map();      // node_id -> 'A' | 'B' | 'AB' | undefined

// ─── HTML escape (defense-in-depth) ──────────────────────────────
function _esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[c]);
}

// ─── Verlet force simulation ─────────────────────────────────────
function _runSimulation(nodes, edges) {
    const N = nodes.length;
    if (N === 0) return;

    // Seed positions: lightly clustered by type for nicer initial layout
    const cx = _viewBox.w / 2, cy = _viewBox.h / 2;
    const typeBuckets = new Map();
    nodes.forEach(n => {
        if (!typeBuckets.has(n.type)) typeBuckets.set(n.type, typeBuckets.size);
    });
    const typeCount = typeBuckets.size;
    nodes.forEach((n, i) => {
        if (n.fx != null) { n.x = n.fx; n.y = n.fy; n.vx = 0; n.vy = 0; return; }
        const bucket = typeBuckets.get(n.type);
        const angle = (bucket / Math.max(typeCount, 1)) * Math.PI * 2 + (i / N) * 0.4;
        const radius = 100 + (i % 7) * 20;
        n.x = cx + Math.cos(angle) * radius;
        n.y = cy + Math.sin(angle) * radius;
        n.vx = 0; n.vy = 0;
    });

    // Index edges for spring forces
    const edgeIdx = edges.map(e => ({
        a: _byId.get(e.src),
        b: _byId.get(e.dst),
    })).filter(e => e.a && e.b);

    for (let tick = 0; tick < SIM_ITERATIONS; tick++) {
        // 1. Repulsion (O(N²))
        for (let i = 0; i < N; i++) {
            const a = nodes[i];
            if (a.fx != null) continue;
            for (let j = i + 1; j < N; j++) {
                const b = nodes[j];
                let dx = b.x - a.x;
                let dy = b.y - a.y;
                let dist = Math.hypot(dx, dy);
                if (dist < MIN_DIST) dist = MIN_DIST;
                const force = REPULSION / (dist * dist);
                const fx = (dx / dist) * force;
                const fy = (dy / dist) * force;
                a.vx -= fx; a.vy -= fy;
                if (b.fx == null) { b.vx += fx; b.vy += fy; }
            }
        }
        // 2. Spring attraction along edges (Hooke)
        for (const e of edgeIdx) {
            const a = e.a, b = e.b;
            const dx = b.x - a.x;
            const dy = b.y - a.y;
            const dist = Math.hypot(dx, dy) || 0.01;
            const displacement = dist - SPRING_REST;
            const fx = (dx / dist) * displacement * SPRING_K;
            const fy = (dy / dist) * displacement * SPRING_K;
            if (a.fx == null) { a.vx += fx; a.vy += fy; }
            if (b.fx == null) { b.vx -= fx; b.vy -= fy; }
        }
        // 3. Centering pull
        for (const n of nodes) {
            if (n.fx != null) continue;
            n.vx += (cx - n.x) * CENTER_PULL;
            n.vy += (cy - n.y) * CENTER_PULL;
        }
        // 4. Integrate + damp
        for (const n of nodes) {
            if (n.fx != null) continue;
            n.vx *= DAMPING; n.vy *= DAMPING;
            n.x += n.vx; n.y += n.vy;
        }
    }
}

// ─── Tier A+ / A1': Path A vs Path B classifier ──────────────────
// BFS forward from the two utility roots. Nodes reachable from both
// are tagged 'AB' (true 2N redundancy); nodes reachable from one
// only are 'A' or 'B'. Cooling roots (cooling_tower_field) are
// classified the same way for the cooling chain.
function _computePathClassification() {
    _pathByNode.clear();
    const ROOTS = [
        { id: 'utility_feed_a', tag: 'A' },
        { id: 'utility_feed_b', tag: 'B' },
    ];
    const reach = { A: new Set(), B: new Set() };
    for (const root of ROOTS) {
        if (!_byId.has(root.id)) continue;
        const queue = [root.id];
        const visited = reach[root.tag];
        visited.add(root.id);
        while (queue.length) {
            const cur = queue.shift();
            for (const e of _data.edges) {
                if (e.chain !== 'power') continue;
                if (e.src !== cur) continue;
                if (visited.has(e.dst)) continue;
                visited.add(e.dst);
                queue.push(e.dst);
            }
        }
    }
    for (const n of _data.nodes) {
        const inA = reach.A.has(n.id);
        const inB = reach.B.has(n.id);
        if (inA && inB) _pathByNode.set(n.id, 'AB');
        else if (inA) _pathByNode.set(n.id, 'A');
        else if (inB) _pathByNode.set(n.id, 'B');
    }
}

// ─── Compute downstream impact set client-side ───────────────────
// (Backend has /api/site/impact, but for the cascade highlight we
// can BFS over the local edge index, sub-millisecond, no roundtrip.)
function _impactSet(nodeId, chainFilter) {
    const visited = new Set();
    const queue = [nodeId];
    while (queue.length) {
        const cur = queue.shift();
        for (const e of _data.edges) {
            if (e.src !== cur) continue;
            if (chainFilter !== 'all' && e.chain !== chainFilter) continue;
            if (visited.has(e.dst)) continue;
            visited.add(e.dst);
            queue.push(e.dst);
        }
    }
    return visited;
}

// ─── SVG rendering ───────────────────────────────────────────────
function _renderEdges() {
    const g = document.getElementById('topo-graph-edges');
    if (!g) return;
    const impact = _selectedId ? _impactSet(_selectedId, _activeChain) : null;
    g.innerHTML = _data.edges
        .filter(e => _activeChain === 'all' || e.chain === _activeChain)
        .map(e => {
            const a = _byId.get(e.src);
            const b = _byId.get(e.dst);
            if (!a || !b) return '';
            // Tier A+ / A1': path-based edge colouring (when toggle is on)
            let pathClass = '';
            if (_pathColorOn && e.chain === 'power') {
                const pa = _pathByNode.get(e.src);
                const pb = _pathByNode.get(e.dst);
                // Edge inherits its src node's path classification.
                if (pa === 'A' || (pa === 'AB' && pb === 'A')) pathClass = ' topo-edge-path-a';
                else if (pa === 'B' || (pa === 'AB' && pb === 'B')) pathClass = ' topo-edge-path-b';
                else if (pa === 'AB') pathClass = ' topo-edge-path-ab';
            }
            const cls = `topo-edge topo-edge-${e.chain}` + pathClass +
                (impact && (e.src === _selectedId || impact.has(e.src)) && impact.has(e.dst)
                    ? ' topo-edge-impact' : '') +
                (_selectedId && impact && !(e.src === _selectedId || impact.has(e.src))
                    ? ' topo-edge-dim' : '');
            return `<line class="${cls}" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}"
                          marker-end="url(#topo-arrow-${e.chain})"/>`;
        }).join('');
}

function _renderNodes() {
    const g = document.getElementById('topo-graph-nodes');
    if (!g) return;
    const impact = _selectedId ? _impactSet(_selectedId, _activeChain) : null;
    const searchActive = _searchTerm.length > 0;
    g.innerHTML = _data.nodes.map(n => {
        const s = styleFor(n.type);
        const isSel = n.id === _selectedId;
        const inImpact = impact && impact.has(n.id);
        const matchesSearch = searchActive && n.id.toLowerCase().includes(_searchTerm);
        // Search dimming overrides selection dimming (looking for a node)
        const dim = (_selectedId && !isSel && !inImpact) ||
                    (searchActive && !matchesSearch);
        const klass = 'topo-node' +
            (isSel ? ' topo-node-selected' : '') +
            (inImpact ? ' topo-node-impact' : '') +
            (matchesSearch ? ' topo-node-search-hit' : '') +
            (_pathColorOn && _pathByNode.get(n.id) === 'A' ? ' topo-node-path-a' : '') +
            (_pathColorOn && _pathByNode.get(n.id) === 'B' ? ' topo-node-path-b' : '') +
            (_pathColorOn && _pathByNode.get(n.id) === 'AB' ? ' topo-node-path-ab' : '') +
            (dim ? ' topo-node-dim' : '');
        const r = isSel ? s.r + 3 : s.r;
        let shape;
        if (s.shape === 'square') {
            shape = `<rect x="${-r}" y="${-r}" width="${r * 2}" height="${r * 2}" rx="2"
                          fill="${s.fill}" stroke="${s.stroke}" stroke-width="1.5"/>`;
        } else if (s.shape === 'diamond') {
            shape = `<polygon points="0,${-r} ${r},0 0,${r} ${-r},0"
                              fill="${s.fill}" stroke="${s.stroke}" stroke-width="1.5"/>`;
        } else {
            shape = `<circle r="${r}" fill="${s.fill}" stroke="${s.stroke}" stroke-width="1.5"/>`;
        }
        const label = n.id.length > 14 ? n.id.slice(0, 13) + '…' : n.id;
        const labelY = r + 11;
        return `<g class="${klass}" transform="translate(${n.x},${n.y})"
                   data-id="${_esc(n.id)}" data-type="${_esc(n.type)}">
                    ${shape}
                    <text class="topo-node-label" x="0" y="${labelY}" text-anchor="middle">${_esc(label)}</text>
                </g>`;
    }).join('');
}

function _render() {
    _renderEdges();
    _renderNodes();
    _updateMeta();
    _renderDetail();
}

function _updateMeta() {
    const meta = document.getElementById('topo-graph-meta');
    if (!meta) return;
    const nN = _data.nodes.length;
    const nE = _data.edges.filter(e => _activeChain === 'all' || e.chain === _activeChain).length;
    meta.textContent = `${nN} nodes · ${nE} ${_activeChain === 'all' ? 'edges' : _activeChain + ' edges'}`;
}

function _renderDetail() {
    const box = document.getElementById('topo-graph-detail');
    if (!box) return;
    if (!_selectedId) { box.setAttribute('hidden', ''); return; }
    const n = _byId.get(_selectedId);
    if (!n) { box.setAttribute('hidden', ''); return; }
    box.removeAttribute('hidden');
    document.getElementById('topo-graph-detail-id').textContent = n.id;
    document.getElementById('topo-graph-detail-type').textContent = n.type;
    document.getElementById('topo-graph-detail-facility').textContent = n.facility || '—';
    document.getElementById('topo-graph-detail-building').textContent = n.building_id || '—';
    document.getElementById('topo-graph-detail-room').textContent = n.room_type || '—';
    const impact = _impactSet(n.id, _activeChain);
    document.getElementById('topo-graph-detail-impact').textContent =
        impact.size > 0 ? `${impact.size} downstream component(s)` : 'no downstream feed';
}

// ─── Pan/zoom + interactions ─────────────────────────────────────
function _setSvgViewBox() {
    const svg = document.getElementById('topo-graph-svg');
    if (!svg) return;
    const x = -_panX / _zoom;
    const y = -_panY / _zoom;
    const w = _viewBox.w / _zoom;
    const h = _viewBox.h / _zoom;
    svg.setAttribute('viewBox', `${x} ${y} ${w} ${h}`);
}

function _onWheel(e) {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    _zoom = Math.min(4, Math.max(0.4, _zoom * delta));
    _setSvgViewBox();
}

let _dragNode = null;
let _dragStart = null;

function _onSvgMouseDown(e) {
    const target = e.target.closest('.topo-node');
    if (target) {
        const id = target.dataset.id;
        const n = _byId.get(id);
        if (n) {
            _dragNode = n;
            _dragStart = { x: e.clientX, y: e.clientY, nx: n.x, ny: n.y };
        }
    } else {
        // Pan on empty space
        _dragStart = { x: e.clientX, y: e.clientY, panX: _panX, panY: _panY, isPan: true };
    }
}
function _onSvgMouseMove(e) {
    if (!_dragStart) return;
    if (_dragStart.isPan) {
        _panX = _dragStart.panX + (e.clientX - _dragStart.x);
        _panY = _dragStart.panY + (e.clientY - _dragStart.y);
        _setSvgViewBox();
        return;
    }
    if (_dragNode) {
        const svg = document.getElementById('topo-graph-svg');
        const ctm = svg.getScreenCTM();
        if (!ctm) return;
        const scale = ctm.a;
        _dragNode.x = _dragStart.nx + (e.clientX - _dragStart.x) / scale;
        _dragNode.y = _dragStart.ny + (e.clientY - _dragStart.y) / scale;
        _dragNode.fx = _dragNode.x;   // pin while dragging
        _dragNode.fy = _dragNode.y;
        _renderEdges();
        const nodeEl = document.querySelector(`.topo-node[data-id="${CSS.escape(_dragNode.id)}"]`);
        if (nodeEl) nodeEl.setAttribute('transform', `translate(${_dragNode.x},${_dragNode.y})`);
    }
}
function _onSvgMouseUp() {
    _dragNode = null;
    _dragStart = null;
}

function _onSvgClick(e) {
    const target = e.target.closest('.topo-node');
    if (target) {
        const id = target.dataset.id;
        if (e.altKey) {
            const n = _byId.get(id);
            if (n) { n.fx = null; n.fy = null; }
            return;
        }
        _selectedId = (_selectedId === id) ? null : id;
        _render();
    } else if (e.target.closest('svg') && !_dragNode) {
        // Click on empty space deselects
        _selectedId = null;
        _render();
    }
}

// ─── Tooltip on hover ────────────────────────────────────────────
function _onSvgMouseOver(e) {
    const t = e.target.closest('.topo-node');
    const tip = document.getElementById('topo-graph-tooltip');
    if (!t || !tip) return;
    const id = t.dataset.id;
    const n = _byId.get(id);
    if (!n) return;
    tip.innerHTML = `<strong>${_esc(n.id)}</strong><br>` +
                    `<span class="topo-tip-type">${_esc(n.type)}</span><br>` +
                    `<span class="topo-tip-loc">${_esc(n.location_path || '')}</span>`;
    tip.style.display = 'block';
    tip.style.left = (e.clientX + 12) + 'px';
    tip.style.top = (e.clientY + 12) + 'px';
}
function _onSvgMouseLeave() {
    const tip = document.getElementById('topo-graph-tooltip');
    if (tip) tip.style.display = 'none';
}
function _onSvgMouseMoveTip(e) {
    const tip = document.getElementById('topo-graph-tooltip');
    if (!tip || tip.style.display !== 'block') return;
    tip.style.left = (e.clientX + 12) + 'px';
    tip.style.top = (e.clientY + 12) + 'px';
}

// ─── Filter buttons ──────────────────────────────────────────────
function _onFilterClick(e) {
    const btn = e.target.closest('.topo-filter');
    if (!btn) return;
    document.querySelectorAll('.topo-filter').forEach(b => b.classList.toggle('active', b === btn));
    _activeChain = btn.dataset.chain;
    _render();
}

function _onReseed() {
    _data.nodes.forEach(n => { n.fx = null; n.fy = null; });
    _runSimulation(_data.nodes, _data.edges);
    _render();
}

// Tier A+ / A1' search + path coloring handlers
function _onSearchInput(e) {
    _searchTerm = (e.target.value || '').trim().toLowerCase();
    _render();
}
function _onPathColorToggle() {
    _pathColorOn = !_pathColorOn;
    const btn = document.getElementById('topo-path-color-toggle');
    if (btn) {
        btn.setAttribute('data-on', _pathColorOn ? '1' : '0');
        btn.classList.toggle('active', _pathColorOn);
    }
    _render();
}

function _onDetailClose() {
    _selectedId = null;
    _render();
}

// ─── Fetch + bootstrap ───────────────────────────────────────────
async function _loadGraph() {
    try {
        const r = await fetch(`${API_BASE}/api/site/graph?chain=all`);
        if (!r.ok) {
            console.warn('[site_topology] graph fetch failed', r.status);
            return;
        }
        const data = await r.json();
        _data.nodes = data.nodes || [];
        _data.edges = data.edges || [];
        _byId = new Map(_data.nodes.map(n => [n.id, n]));
        _computePathClassification();
        _runSimulation(_data.nodes, _data.edges);
        _render();
        console.log('[site_topology] graph ready: %d nodes, %d edges',
                    _data.nodes.length, _data.edges.length);
    } catch (e) {
        console.warn('[site_topology] graph load error:', e);
    }
}

// ─── Wiring ──────────────────────────────────────────────────────
function _wireEvents() {
    document.getElementById('topo-graph-svg')?.addEventListener('mousedown', _onSvgMouseDown);
    document.addEventListener('mousemove', _onSvgMouseMove);
    document.addEventListener('mouseup', _onSvgMouseUp);
    document.getElementById('topo-graph-svg')?.addEventListener('click', _onSvgClick);
    document.getElementById('topo-graph-svg')?.addEventListener('wheel', _onWheel, { passive: false });
    document.getElementById('topo-graph-svg')?.addEventListener('mouseover', _onSvgMouseOver);
    document.getElementById('topo-graph-svg')?.addEventListener('mousemove', _onSvgMouseMoveTip);
    document.getElementById('topo-graph-svg')?.addEventListener('mouseleave', _onSvgMouseLeave);

    document.querySelector('.topo-graph-filters')?.addEventListener('click', _onFilterClick);
    document.getElementById('topo-graph-reseed')?.addEventListener('click', _onReseed);
    document.getElementById('topo-graph-detail-close')?.addEventListener('click', _onDetailClose);

    // Tier A+ / A1'
    document.getElementById('topo-graph-search')?.addEventListener('input', _onSearchInput);
    document.getElementById('topo-path-color-toggle')?.addEventListener('click', _onPathColorToggle);
}

// LOTO-pattern: legacy router has site_topology branch but doesn't
// initialize the graph. We listen for the click and auto-load on first
// activation, then idempotently render on subsequent visits.
function _wireRouting() {
    // T2.2: declarative registry (replaces the setTimeout(0) LOTO race).
    registerRoute('site_topology', {
        viewId: 'view-site-topology',
        activate: ({ firstActivation }) => {
            if (firstActivation) {
                _loadGraph();
            } else {
                _setSvgViewBox();
            }
        },
    });
}

export function initSiteTopologyView() {
    if (_initialized) return;
    if (!document.getElementById('topo-graph-svg')) {
        console.warn('[site_topology] graph SVG not in DOM; view disabled.');
        return;
    }
    _wireEvents();
    _wireRouting();
    _setSvgViewBox();
    _initialized = true;
    console.log('[site_topology] ready (force-directed graph)');
}
