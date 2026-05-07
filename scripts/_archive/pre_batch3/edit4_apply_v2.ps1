# Sprint S1b — Edit #4 v2: regex-based markers (resilient to whitespace/emoji issues)

$root = "C:\dev\DC-EPMS_PRO\frontend"
$indexPath = Join-Path $root "index.html"
$jsPath    = Join-Path $root "assets\app.js"

$indexBak = $indexPath + ".bak_pre_s1b_e4"
$jsBak    = $jsPath + ".bak_pre_s1b_e4"
if (-not (Test-Path $indexBak)) { Copy-Item $indexPath $indexBak }
if (-not (Test-Path $jsBak))    { Copy-Item $jsPath    $jsBak    }
Write-Host "Backups confirmed (or created)" -ForegroundColor Cyan

# ────────────────────────────────────────────────────────────────────
# Edit A: nav-item (regex-based, no emoji match needed)
# ────────────────────────────────────────────────────────────────────
$indexContent = [System.IO.File]::ReadAllText($indexPath)

# Match the entire omniverse nav-item line and capture leading whitespace
$navPattern = '(?m)^(\s*)<div class="nav-item" data-route="omniverse">.*?</div>'
$navMatch = [regex]::Match($indexContent, $navPattern)

if ($navMatch.Success) {
    $indent = $navMatch.Groups[1].Value
    $newNav = $navMatch.Value + "`r`n" + $indent + '<div class="nav-item" data-route="site_topology"><span class="icon">&#127970;</span>Site Topology</div>'
    $indexContent = $indexContent.Substring(0, $navMatch.Index) + $newNav + $indexContent.Substring($navMatch.Index + $navMatch.Length)
    Write-Host "Edit A OK: nav-item inserted (indent: $($indent.Length) chars)" -ForegroundColor Green
} else {
    Write-Host "Edit A ERROR: omniverse nav-item pattern not found" -ForegroundColor Red
    exit 1
}

# ────────────────────────────────────────────────────────────────────
# Edit B: <section> before </main>
# ────────────────────────────────────────────────────────────────────
$siteTopoSection = @"

            <!-- View: Site Topology (Sprint S1b) -->
            <div class="view" id="view-site-topology" hidden>
                <div class="view-hdr">
                    <h2>Site Topology &mdash; A3-Alpha Toronto Area</h2>
                    <div class="view-sub">Physical hierarchy &middot; 2N power chains &middot; LOTO impact analysis</div>
                </div>

                <div class="topology-tabs">
                    <span class="topo-meta">
                        <span class="topo-redundancy-badge">Tier IV</span>
                        <span class="topo-meta-sep">&middot;</span>
                        <span class="topo-meta-lbl">Components:</span>
                        <span class="topo-meta-val" id="st-count">&mdash;</span>
                        <span class="topo-meta-sep">&middot;</span>
                        <span class="topo-meta-lbl">Redundancy:</span>
                        <span class="topo-meta-val" id="st-redundancy">&mdash;</span>
                    </span>
                    <button class="btn btn-secondary btn-sm" id="st-refresh">Refresh</button>
                </div>

                <div style="display:grid;grid-template-columns:340px 1fr;gap:16px;margin-top:12px;height:calc(100vh - 280px);">
                    <aside style="background:var(--surface,#14181D);border:1px solid var(--border,#1f262d);border-radius:8px;display:flex;flex-direction:column;overflow:hidden;">
                        <div style="padding:10px 14px;border-bottom:1px solid var(--border,#1f262d);background:var(--bg,#0B0D10);font-size:12px;text-transform:uppercase;letter-spacing:0.05em;color:var(--cyan,#00B8D4);font-weight:600;">Hierarchy</div>
                        <div id="st-tree" style="flex:1;overflow-y:auto;padding:8px;font-size:13px;color:var(--text,#c4cdd6);">
                            <div style="padding:24px;text-align:center;color:var(--text-muted,#6a7a8b);font-style:italic;">Loading site model&hellip;</div>
                        </div>
                    </aside>
                    <section style="background:var(--surface,#14181D);border:1px solid var(--border,#1f262d);border-radius:8px;overflow-y:auto;display:flex;flex-direction:column;">
                        <div id="st-detail-empty" style="margin:auto;text-align:center;color:var(--text-muted,#6a7a8b);padding:32px;max-width:340px;line-height:1.5;">Select a component on the left to view its location, power chain, and LOTO impact.</div>
                        <div id="st-detail-content" style="padding:18px 22px;display:none;">
                            <header style="margin-bottom:14px;">
                                <h3 id="st-title" style="margin:0 0 6px;font-size:17px;color:var(--cyan,#00B8D4);">&mdash;</h3>
                                <div id="st-breadcrumb" style="font-size:12px;color:var(--text-muted,#8a9aab);font-family:'JetBrains Mono','Consolas',monospace;"></div>
                            </header>
                            <div style="display:flex;gap:4px;margin-bottom:14px;border-bottom:1px solid var(--border,#1f262d);">
                                <button class="st-tab st-tab-active" data-st-tab="overview">Overview</button>
                                <button class="st-tab" data-st-tab="power">Power Chain</button>
                                <button class="st-tab" data-st-tab="loto">LOTO Impact</button>
                            </div>
                            <div id="st-tab-overview" class="st-tab-content"></div>
                            <div id="st-tab-power" class="st-tab-content" hidden></div>
                            <div id="st-tab-loto" class="st-tab-content" hidden></div>
                        </div>
                    </section>
                </div>

                <style>
                    .st-tab { background:transparent;border:none;color:var(--text-muted,#8a9aab);padding:7px 13px;font-size:13px;cursor:pointer;border-bottom:2px solid transparent; }
                    .st-tab:hover { color:var(--text,#c4cdd6); }
                    .st-tab-active { color:var(--cyan,#00B8D4)!important;border-bottom-color:var(--cyan,#00B8D4)!important; }
                    .st-tree-row { display:flex;align-items:center;padding:4px 6px;border-radius:4px;cursor:pointer;gap:6px;user-select:none; }
                    .st-tree-row:hover { background:rgba(0,184,212,0.07); }
                    .st-tree-row.st-selected { background:rgba(0,184,212,0.15);color:var(--cyan,#00B8D4);font-weight:500; }
                    .st-tree-toggle { width:14px;display:inline-block;text-align:center;color:var(--text-muted,#6a7a8b);font-size:10px; }
                    .st-tree-icon { font-size:11px;color:var(--text-muted,#6a7a8b); }
                    .st-tree-label { flex:1; }
                    .st-tree-count { font-size:11px;color:var(--text-muted,#6a7a8b);margin-left:6px; }
                    .st-tree-children { padding-left:16px;border-left:1px dashed var(--border,#1f262d);margin-left:7px; }
                    .st-tree-leaf { padding:3px 6px 3px 22px;font-size:12px;color:var(--text-muted,#8a9aab);cursor:pointer;border-radius:3px;font-family:'JetBrains Mono','Consolas',monospace; }
                    .st-tree-leaf:hover { background:rgba(0,184,212,0.07);color:var(--text,#c4cdd6); }
                    .st-tree-leaf.st-selected { background:rgba(0,184,212,0.15);color:var(--cyan,#00B8D4); }
                    .st-feed-block { background:var(--bg,#0B0D10);border-left:3px solid var(--cyan,#00B8D4);border-radius:4px;padding:11px 13px;margin-bottom:9px; }
                    .st-feed-block.st-path-b { border-left-color:#d4a000; }
                    .st-feed-block.st-other { border-left-color:var(--text-muted,#6a7a8b); }
                    .st-feed-title { font-size:11px;text-transform:uppercase;letter-spacing:0.06em;color:var(--cyan,#00B8D4);margin-bottom:5px;font-weight:600; }
                    .st-feed-block.st-path-b .st-feed-title { color:#d4a000; }
                    .st-feed-roots { font-size:12px;color:var(--text-muted,#8a9aab);margin-bottom:6px; }
                    .st-root-pill { display:inline-block;background:rgba(0,184,212,0.1);padding:2px 8px;border-radius:3px;font-family:'JetBrains Mono','Consolas',monospace;font-size:11px;margin-right:4px;color:var(--text,#c4cdd6); }
                    .st-feed-path { font-family:'JetBrains Mono','Consolas',monospace;font-size:11px;color:var(--text,#c4cdd6);word-break:break-word; }
                    .st-loto-banner { padding:11px 14px;border-radius:6px;margin-bottom:14px;font-size:13px; }
                    .st-loto-banner.st-safe { background:rgba(0,212,122,0.12);border-left:3px solid #00d47a;color:#c4ffe0; }
                    .st-loto-banner.st-unsafe { background:rgba(255,80,80,0.12);border-left:3px solid #ff5050;color:#ffd0d0; }
                    .st-stats { display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:16px; }
                    .st-stat { background:var(--bg,#0B0D10);border-radius:6px;padding:11px 13px;text-align:center; }
                    .st-stat-val { font-size:22px;color:var(--cyan,#00B8D4);font-weight:600;font-family:'JetBrains Mono','Consolas',monospace; }
                    .st-stat-val.st-danger { color:#ff5050; }
                    .st-stat-val.st-ok { color:#00d47a; }
                    .st-stat-lbl { font-size:11px;text-transform:uppercase;letter-spacing:0.04em;color:var(--text-muted,#6a7a8b);margin-top:3px; }
                    .st-rack-list { background:var(--bg,#0B0D10);border-radius:6px;padding:10px;max-height:240px;overflow-y:auto; }
                    .st-rack-row { display:flex;justify-content:space-between;padding:3px 8px;font-family:'JetBrains Mono','Consolas',monospace;font-size:12px;color:var(--text,#c4cdd6); }
                    .st-rack-row .st-status-safe { color:#00d47a; }
                    .st-rack-row .st-status-danger { color:#ff5050; }
                    .st-overview-grid { display:grid;grid-template-columns:140px 1fr;gap:6px 14px;margin:0;font-size:13px; }
                    .st-overview-grid dt { color:var(--text-muted,#6a7a8b);text-transform:uppercase;letter-spacing:0.04em;font-size:11px;padding-top:2px; }
                    .st-overview-grid dd { color:var(--text,#c4cdd6);margin:0;font-family:'JetBrains Mono','Consolas',monospace;word-break:break-word; }
                </style>
            </div>

"@

$mainPattern = '(?m)^    </main>'
$mainMatch = [regex]::Match($indexContent, $mainPattern)
if ($mainMatch.Success) {
    $indexContent = $indexContent.Substring(0, $mainMatch.Index) + $siteTopoSection + $indexContent.Substring($mainMatch.Index)
    [System.IO.File]::WriteAllText($indexPath, $indexContent, [System.Text.UTF8Encoding]::new($false))
    Write-Host "Edit B OK: section inserted before </main>" -ForegroundColor Green
} else {
    Write-Host "Edit B ERROR: </main> pattern not found" -ForegroundColor Red
    exit 1
}

# ────────────────────────────────────────────────────────────────────
# Edit C: register MODULES['site_topology'] in app.js
# ────────────────────────────────────────────────────────────────────
$jsContent = [System.IO.File]::ReadAllText($jsPath)

# Match the whitespace-tolerant copilot module entry
$modPattern = '(?m)^(\s*)copilot:\s*\{\r?\n\s*kind:\s*''copilot'','
$modMatch = [regex]::Match($jsContent, $modPattern)

if ($modMatch.Success) {
    $indent = $modMatch.Groups[1].Value
    $newModule = $indent + "site_topology: {`r`n" + $indent + "    kind: 'site_topology',`r`n" + $indent + "    title: 'Site Topology',`r`n" + $indent + "    sub:   'Physical hierarchy and 2N power chain analysis',`r`n" + $indent + "},`r`n" + $modMatch.Value
    $jsContent = $jsContent.Substring(0, $modMatch.Index) + $newModule + $jsContent.Substring($modMatch.Index + $modMatch.Length)
    Write-Host "Edit C OK: MODULES['site_topology'] registered" -ForegroundColor Green
} else {
    Write-Host "Edit C ERROR: copilot module pattern not found" -ForegroundColor Red
    exit 1
}

# ────────────────────────────────────────────────────────────────────
# Edit D.1: navigateTo branch
# ────────────────────────────────────────────────────────────────────
$navJsPattern = '(?ms)(\s*)\} else if \(cfg\.kind === ''copilot''\) \{\s*\r?\n\s*const v = \$\(''view-copilot''\);\s*\r?\n\s*if \(v\) v\.removeAttribute\(''hidden''\);\s*\r?\n\s*renderCopilotView\(\);'

$navJsMatch = [regex]::Match($jsContent, $navJsPattern)
if ($navJsMatch.Success) {
    $newBranch = $navJsMatch.Groups[1].Value + "} else if (cfg.kind === 'site_topology') {`r`n            const v = `$('view-site-topology');`r`n            if (v) v.removeAttribute('hidden');`r`n            renderSiteTopologyView();`r`n        " + $navJsMatch.Value.TrimStart()
    $jsContent = $jsContent.Substring(0, $navJsMatch.Index) + $newBranch + $jsContent.Substring($navJsMatch.Index + $navJsMatch.Length)
    Write-Host "Edit D.1 OK: navigateTo branch inserted" -ForegroundColor Green
} else {
    Write-Host "Edit D.1 ERROR: copilot navigate pattern not matched" -ForegroundColor Red
    exit 1
}

# ────────────────────────────────────────────────────────────────────
# Edit D.2: renderSiteTopologyView function (before setupRouter)
# ────────────────────────────────────────────────────────────────────
$renderFn = @'

    // Sprint S1b — Site Topology view renderer
    let _stSelectedId = null;
    let _stInitialized = false;

    async function renderSiteTopologyView() {
        if (_stInitialized) {
            await _stRenderTree();
            return;
        }
        _stInitialized = true;
        document.querySelectorAll('.st-tab').forEach(btn => {
            if (btn._bound) return;
            btn._bound = true;
            btn.addEventListener('click', () => {
                const tab = btn.dataset.stTab;
                document.querySelectorAll('.st-tab').forEach(b => b.classList.toggle('st-tab-active', b === btn));
                document.querySelectorAll('.st-tab-content').forEach(c => { c.hidden = c.id !== `st-tab-${tab}`; });
                if (tab === 'power') _stLoadPowerTab();
                if (tab === 'loto') _stLoadLotoTab();
            });
        });
        const refreshBtn = $('st-refresh');
        if (refreshBtn && !refreshBtn._bound) {
            refreshBtn._bound = true;
            refreshBtn.addEventListener('click', _stRenderTree);
        }
        await _stRenderTree();
    }

    async function _stApi(path) {
        const r = await fetch(`${API_BASE}/api/site${path}`);
        if (!r.ok) throw new Error(`API ${path} -> ${r.status}`);
        return r.json();
    }

    async function _stRenderTree() {
        const root = $('st-tree');
        root.innerHTML = '<div style="padding:24px;text-align:center;color:var(--text-muted,#6a7a8b);font-style:italic;">Loading...</div>';
        try {
            const meta = await _stApi('/metadata');
            $('st-redundancy').textContent = `${meta.redundancy.electrical} / ${meta.redundancy.cooling}`;
            const compsResp = await _stApi('/components?limit=1000');
            $('st-count').textContent = compsResp.total;
            const { buildings } = await _stApi('/buildings');
            root.innerHTML = '';
            for (const b of buildings) root.appendChild(_stBuildingNode(b));
        } catch (e) {
            root.innerHTML = `<div style="padding:24px;color:#ff5050;">Error: ${e.message}</div>`;
        }
    }

    function _stBuildingNode(b) {
        const wrap = document.createElement('div');
        const row = document.createElement('div'); row.className = 'st-tree-row';
        const toggle = document.createElement('span'); toggle.className = 'st-tree-toggle'; toggle.textContent = '\u25B8';
        const icon = document.createElement('span'); icon.className = 'st-tree-icon'; icon.textContent = '\u25A6';
        const label = document.createElement('span'); label.className = 'st-tree-label'; label.textContent = b.display;
        const count = document.createElement('span'); count.className = 'st-tree-count'; count.textContent = `${b.room_count} rooms`;
        row.append(toggle, icon, label, count); wrap.appendChild(row);
        const children = document.createElement('div'); children.className = 'st-tree-children'; children.style.display = 'none';
        wrap.appendChild(children);
        let loaded = false;
        row.addEventListener('click', async (e) => {
            e.stopPropagation();
            const expanded = children.style.display === 'block';
            children.style.display = expanded ? 'none' : 'block';
            toggle.textContent = expanded ? '\u25B8' : '\u25BE';
            if (!loaded && !expanded) {
                loaded = true;
                children.innerHTML = '<div style="padding:6px 12px;color:var(--text-muted,#6a7a8b);font-style:italic;font-size:11px;">Loading...</div>';
                try {
                    const data = await _stApi(`/tree/${b.id}`);
                    children.innerHTML = '';
                    for (const room of data.rooms) children.appendChild(_stRoomNode(room));
                } catch (err) {
                    children.innerHTML = `<div style="padding:6px;color:#ff5050;">${err.message}</div>`;
                }
            }
        });
        return wrap;
    }

    function _stRoomNode(room) {
        const wrap = document.createElement('div');
        const row = document.createElement('div'); row.className = 'st-tree-row';
        const toggle = document.createElement('span'); toggle.className = 'st-tree-toggle'; toggle.textContent = '\u25B8';
        const iconMap = { data_hall:'\u25A5', electrical_room:'\u26A1', mechanical_room:'\u2744', mechanical_plant:'\u2744', emergency_power:'\u26A1', utility_intake:'\u26A1', fuel_depot:'\u26FD', control_room:'\u25A3' };
        const icon = document.createElement('span'); icon.className = 'st-tree-icon'; icon.textContent = iconMap[room.type] || '\u00B7';
        const label = document.createElement('span'); label.className = 'st-tree-label'; label.textContent = room.display;
        const total = (room.components || []).length + (room.rows || []).length;
        const count = document.createElement('span'); count.className = 'st-tree-count'; count.textContent = total ? `${total} items` : '';
        row.append(toggle, icon, label, count); wrap.appendChild(row);
        const children = document.createElement('div'); children.className = 'st-tree-children'; children.style.display = 'none';
        wrap.appendChild(children);
        for (const r of (room.rows || [])) children.appendChild(_stRowNode(r));
        for (const cId of (room.components || [])) children.appendChild(_stLeaf(cId));
        row.addEventListener('click', (e) => {
            e.stopPropagation();
            const expanded = children.style.display === 'block';
            children.style.display = expanded ? 'none' : 'block';
            toggle.textContent = expanded ? '\u25B8' : '\u25BE';
        });
        return wrap;
    }

    function _stRowNode(rowData) {
        const wrap = document.createElement('div');
        const row = document.createElement('div'); row.className = 'st-tree-row';
        const toggle = document.createElement('span'); toggle.className = 'st-tree-toggle'; toggle.textContent = '\u25B8';
        const icon = document.createElement('span'); icon.className = 'st-tree-icon'; icon.textContent = '\u2261';
        const label = document.createElement('span'); label.className = 'st-tree-label'; label.textContent = rowData.display;
        const count = document.createElement('span'); count.className = 'st-tree-count'; count.textContent = `${rowData.racks.length} racks`;
        row.append(toggle, icon, label, count); wrap.appendChild(row);
        const children = document.createElement('div'); children.className = 'st-tree-children'; children.style.display = 'none';
        wrap.appendChild(children);
        for (const rackId of rowData.racks) children.appendChild(_stLeaf(rackId));
        row.addEventListener('click', (e) => {
            e.stopPropagation();
            const expanded = children.style.display === 'block';
            children.style.display = expanded ? 'none' : 'block';
            toggle.textContent = expanded ? '\u25B8' : '\u25BE';
        });
        return wrap;
    }

    function _stLeaf(canonicalId) {
        const leaf = document.createElement('div');
        leaf.className = 'st-tree-leaf';
        leaf.textContent = canonicalId;
        leaf.dataset.cid = canonicalId;
        leaf.addEventListener('click', (e) => { e.stopPropagation(); _stSelect(canonicalId); });
        return leaf;
    }

    async function _stSelect(canonicalId) {
        _stSelectedId = canonicalId;
        document.querySelectorAll('.st-tree-leaf.st-selected').forEach(n => n.classList.remove('st-selected'));
        document.querySelectorAll(`.st-tree-leaf[data-cid="${canonicalId}"]`).forEach(n => n.classList.add('st-selected'));
        $('st-detail-empty').style.display = 'none';
        $('st-detail-content').style.display = 'block';
        try {
            const comp = await _stApi(`/components/${canonicalId}`);
            $('st-title').textContent = comp.display;
            const bc = $('st-breadcrumb'); bc.innerHTML = '';
            comp.location.components.forEach((c, i) => {
                if (i > 0) bc.insertAdjacentHTML('beforeend', '<span style="margin:0 6px;color:var(--border,#2b3640);">/</span>');
                bc.insertAdjacentHTML('beforeend', `<span>${c.display}</span>`);
            });
            const grid = $('st-tab-overview');
            grid.innerHTML = '<dl class="st-overview-grid"></dl>';
            const dl = grid.firstElementChild;
            const fields = [
                ['Canonical ID', comp.canonical_id],
                ['Display', comp.display],
                ['Type', comp.type],
                ['Location', comp.location.path],
            ];
            Object.entries(comp).forEach(([k, v]) => {
                if (['canonical_id','display','type','location'].includes(k)) return;
                if (v === null || v === undefined || typeof v === 'object') return;
                const label = k.replace(/_/g,' ').replace(/\b\w/g, l => l.toUpperCase());
                fields.push([label, String(v)]);
            });
            for (const [k, v] of fields) {
                dl.insertAdjacentHTML('beforeend', `<dt>${k}</dt><dd>${v}</dd>`);
            }
            document.querySelectorAll('.st-tab').forEach(b => b.classList.toggle('st-tab-active', b.dataset.stTab === 'overview'));
            document.querySelectorAll('.st-tab-content').forEach(c => c.hidden = c.id !== 'st-tab-overview');
            $('st-tab-power').innerHTML = '<em style="color:var(--text-muted,#6a7a8b)">Click "Power Chain" to load.</em>';
            $('st-tab-loto').innerHTML = '<em style="color:var(--text-muted,#6a7a8b)">Click "LOTO Impact" to load.</em>';
        } catch (e) {
            $('st-title').textContent = 'Error';
            $('st-tab-overview').textContent = e.message;
        }
    }

    async function _stLoadPowerTab() {
        if (!_stSelectedId) return;
        const target = $('st-tab-power');
        target.innerHTML = '<em style="color:var(--text-muted,#6a7a8b)">Loading...</em>';
        try {
            const data = await _stApi(`/power-chain/${_stSelectedId}`);
            target.innerHTML = '';
            const summary = document.createElement('div');
            summary.style.cssText = 'background:var(--bg,#0B0D10);border-radius:6px;padding:11px 14px;margin-bottom:14px;display:flex;gap:18px;align-items:center;';
            if (data.feed_count >= 2) {
                summary.innerHTML = `<span style="background:var(--cyan,#00B8D4);color:var(--bg,#0B0D10);padding:3px 10px;border-radius:4px;font-weight:700;font-size:12px;">2N</span><span>${data.feed_count} redundant feed paths</span>`;
            } else if (data.feed_count === 1) {
                summary.innerHTML = `<span>1 feed path (single-corded)</span>`;
            } else {
                summary.innerHTML = `<span>No upstream feeds</span>`;
            }
            target.appendChild(summary);
            data.feeds.forEach(feed => {
                const block = document.createElement('div');
                block.className = 'st-feed-block ' + (feed.group === 'path_b' ? 'st-path-b' : feed.group === 'path_a' ? '' : 'st-other');
                let html = `<div class="st-feed-title">${feed.group.replace('_',' ').toUpperCase()}</div>`;
                html += '<div class="st-feed-roots">Roots: ';
                feed.roots.forEach(r => html += `<span class="st-root-pill">${r}</span>`);
                html += '</div>';
                html += '<div class="st-feed-path">';
                feed.representative_path.forEach((node, i) => {
                    if (i > 0) html += '<span style="color:var(--text-muted,#6a7a8b);margin:0 4px;">\u2192</span>';
                    html += node;
                });
                html += '</div>';
                block.innerHTML = html;
                target.appendChild(block);
            });
        } catch (e) {
            target.innerHTML = `<div style="color:#ff5050;">Error: ${e.message}</div>`;
        }
    }

    async function _stLoadLotoTab() {
        if (!_stSelectedId) return;
        const target = $('st-tab-loto');
        target.innerHTML = '<em style="color:var(--text-muted,#6a7a8b)">Loading...</em>';
        try {
            const data = await _stApi(`/loto-impact/${_stSelectedId}`);
            target.innerHTML = '';
            const safe = data.racks_losing_all_redundancy.length === 0;
            const banner = document.createElement('div');
            banner.className = 'st-loto-banner ' + (safe ? 'st-safe' : 'st-unsafe');
            banner.textContent = safe
                ? '\u2713 Safe LOTO - all affected racks retain Path B redundancy.'
                : `\u26A0 Risk - ${data.racks_losing_all_redundancy.length} racks would lose all redundancy.`;
            target.appendChild(banner);
            const stats = document.createElement('div');
            stats.className = 'st-stats';
            stats.innerHTML = `
                <div class="st-stat"><div class="st-stat-val">${data.downstream_count}</div><div class="st-stat-lbl">Downstream</div></div>
                <div class="st-stat"><div class="st-stat-val">${data.racks_affected.length}</div><div class="st-stat-lbl">Racks Affected</div></div>
                <div class="st-stat"><div class="st-stat-val ${safe ? 'st-ok' : 'st-danger'}">${data.racks_losing_all_redundancy.length}</div><div class="st-stat-lbl">At Outage Risk</div></div>
            `;
            target.appendChild(stats);
            if (data.racks_affected.length) {
                const h = document.createElement('h4');
                h.style.cssText = 'font-size:12px;color:var(--text-muted,#8a9aab);margin:14px 0 8px;text-transform:uppercase;letter-spacing:0.04em;';
                h.textContent = 'Per-Rack Redundancy';
                target.appendChild(h);
                const list = document.createElement('div');
                list.className = 'st-rack-list';
                data.racks_affected.forEach(r => {
                    const status = r.still_has_redundancy
                        ? `<span class="st-status-safe">${r.remaining_paths}/${r.total_paths} paths OK</span>`
                        : `<span class="st-status-danger">OUTAGE RISK</span>`;
                    list.insertAdjacentHTML('beforeend', `<div class="st-rack-row"><span>${r.rack}</span>${status}</div>`);
                });
                target.appendChild(list);
            }
        } catch (e) {
            target.innerHTML = `<div style="color:#ff5050;">Error: ${e.message}</div>`;
        }
    }

'@

$setupRouterMarker = '    function setupRouter() {'
if ($jsContent.Contains($setupRouterMarker)) {
    $jsContent = $jsContent.Replace($setupRouterMarker, $renderFn + $setupRouterMarker)
    [System.IO.File]::WriteAllText($jsPath, $jsContent, [System.Text.UTF8Encoding]::new($false))
    Write-Host "Edit D.2 OK: renderSiteTopologyView() added" -ForegroundColor Green
} else {
    Write-Host "Edit D.2 ERROR: setupRouter marker not found" -ForegroundColor Red
    exit 1
}

Write-Host "`n=== ALL 4 EDITS APPLIED ===" -ForegroundColor Cyan
