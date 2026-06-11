/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — core/n1_overlay.js
 * N-1 Shadow — shared diagram overlay (one implementation for the
 * Power SLD and the Cooling P&ID; one visual language, ADR-012).
 *
 * attach(): stamps an `N-1` badge on every diagram node — its tone
 * answers "if THIS trips, sustained, who pays?":
 *   - critical  ->  N-1:<n> loads LOST (steady-state, battery
 *                   holdup honestly excluded)
 *   - warning   ->  N-1:▲<n> survivors DEGRADED (running on genset
 *                   / redundancy consumed)
 *   - ok        ->  N-1:OK (the failure is fully absorbed)
 * Hovering a node lights its victims: lost = critical glow,
 * degraded = warning glow. detach() removes everything.
 *
 * Pure DOM layer over core/contingency.js — recomputed on attach
 * (topology is structural; live trips are the What-If sandbox's
 * job, and the views disable this overlay in What-If mode).
 * ════════════════════════════════════════════════════════════════ */

/**
 * @param {Object} cfg
 * @param {string}   cfg.rootSelector  diagram SVG root (e.g. '#view-power .pid-svg')
 * @param {string}   cfg.nodeSelector  node group selector ('.pf-node' | '.cool-node')
 * @param {string}   cfg.idAttr        dataset key holding the node id ('sldNode' | 'node')
 * @param {string}   cfg.nameSelector  per-node label element ('.pf-name' | '.cool-name')
 * @param {Function} cfg.analysisFn    () => Map<id, {lost, degraded, tone}>
 */
export function createN1Overlay(cfg) {
    let _attached = false;
    let _analysis = null;
    const SVG_NS = 'http://www.w3.org/2000/svg';

    function _root() { return document.querySelector(cfg.rootSelector); }
    function _nodes() {
        const r = _root();
        return r ? [...r.querySelectorAll(cfg.nodeSelector)] : [];
    }

    function _badgeText(entry) {
        if (!entry) return null;
        // Tone drives the reading: critical counts what went DARK;
        // warning counts everything impacted but still served.
        if (entry.tone === 'critical') return `N-1:${entry.lost.length}`;
        if (entry.tone === 'warning') return `N-1:▲${entry.lost.length + entry.degraded.length}`;
        return 'N-1:OK';
    }

    function _clearGlow() {
        _nodes().forEach((n) => n.classList.remove('dk-n1-victim', 'dk-n1-deg'));
    }

    function _onOver(e) {
        const node = e.target.closest(cfg.nodeSelector);
        if (!node || !_analysis) return;
        const entry = _analysis.get(node.dataset[cfg.idAttr]);
        if (!entry) return;
        _clearGlow();
        const lost = new Set(entry.lost);
        const deg = new Set(entry.degraded);
        _nodes().forEach((n) => {
            const id = n.dataset[cfg.idAttr];
            if (lost.has(id)) n.classList.add('dk-n1-victim');
            else if (deg.has(id)) n.classList.add('dk-n1-deg');
        });
    }

    function _onOut(e) {
        if (!e.relatedTarget || !e.relatedTarget.closest?.(cfg.nodeSelector)) _clearGlow();
    }

    function attach() {
        if (_attached) return;
        const root = _root();
        if (!root) return;
        _analysis = cfg.analysisFn();
        _nodes().forEach((node) => {
            const id = node.dataset[cfg.idAttr];
            const entry = _analysis.get(id);
            const label = _badgeText(entry);
            if (!label) return;   // node outside the contingency model
            const name = node.querySelector(cfg.nameSelector);
            if (!name) return;
            const badge = document.createElementNS(SVG_NS, 'text');
            badge.setAttribute('class', 'dk-n1-badge');
            badge.setAttribute('data-n1-badge', id);
            badge.setAttribute('data-tone', entry.tone);
            badge.setAttribute('x', name.getAttribute('x'));
            badge.setAttribute('y', String(Number(name.getAttribute('y')) - 13));
            badge.textContent = label;
            node.appendChild(badge);
        });
        root.addEventListener('mouseover', _onOver);
        root.addEventListener('mouseout', _onOut);
        _attached = true;
    }

    function detach() {
        if (!_attached) return;
        const root = _root();
        if (root) {
            root.removeEventListener('mouseover', _onOver);
            root.removeEventListener('mouseout', _onOut);
            root.querySelectorAll('[data-n1-badge]').forEach((b) => b.remove());
        }
        _clearGlow();
        _analysis = null;
        _attached = false;
    }

    return { attach, detach, isAttached: () => _attached };
}
