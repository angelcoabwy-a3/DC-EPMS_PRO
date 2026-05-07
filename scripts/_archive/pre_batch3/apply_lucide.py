"""
Sprint S1b — Part C: Replace emoji icons with inline Lucide SVG paths.
Targets:
  - Sidebar nav-items (13 icons in index.html)
  - Tree icons in Site Topology (8 icon types in app.js)
  - CSS for hover/active states (append to app.css)

Pure binary file manipulation - preserves all existing emojis/bytes
in unrelated parts of the files.
"""
from pathlib import Path
import sys

ROOT = Path(r"C:\dev\DC-EPMS_PRO\frontend")
INDEX_PATH = ROOT / "index.html"
JS_PATH = ROOT / "assets" / "app.js"
CSS_PATH = ROOT / "assets" / "app.css"

# ───────────────────────────────────────────────────────────────
#  Lucide SVG paths (stroke-based, currentColor)
#  Source: https://lucide.dev/icons/
#  All paths use viewBox="0 0 24 24"
# ───────────────────────────────────────────────────────────────
LUCIDE_SVGS = {
    "activity":         '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
    "flask-conical":    '<path d="M10 2v7.527a2 2 0 0 1-.211.896L4.72 20.55a1 1 0 0 0 .9 1.45h12.76a1 1 0 0 0 .9-1.45l-5.069-10.127A2 2 0 0 1 14 9.527V2"/><path d="M8.5 2h7"/><path d="M7 16h10"/>',
    "zap":              '<path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/>',
    "snowflake":        '<path d="M2 12h20"/><path d="M12 2v20"/><path d="m20 16-4-4 4-4"/><path d="m4 8 4 4-4 4"/><path d="m16 4-4 4-4-4"/><path d="m8 20 4-4 4 4"/>',
    "alert-triangle":   '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    "file-text":        '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
    "network":          '<rect x="16" y="16" width="6" height="6" rx="1"/><rect x="2" y="16" width="6" height="6" rx="1"/><rect x="9" y="2" width="6" height="6" rx="1"/><path d="M5 16v-3a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v3"/><path d="M12 12V8"/>',
    "plug":             '<path d="M12 22v-5"/><path d="M9 7V2"/><path d="M15 7V2"/><path d="M6 13V8h12v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4Z"/>',
    "bot":              '<path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/>',
    "shield-check":     '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
    "cpu":              '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M15 2v2"/><path d="M15 20v2"/><path d="M2 15h2"/><path d="M2 9h2"/><path d="M20 15h2"/><path d="M20 9h2"/><path d="M9 2v2"/><path d="M9 20v2"/>',
    "box":              '<path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>',
    "building-2":       '<path d="M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z"/><path d="M6 12H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"/><path d="M18 9h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2"/><path d="M10 6h4"/><path d="M10 10h4"/><path d="M10 14h4"/><path d="M10 18h4"/>',
    # Tree icons (Site Topology hierarchy)
    "warehouse":        '<path d="M22 8.35V20a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V8.35A2 2 0 0 1 3.26 6.5l8-3.2a2 2 0 0 1 1.48 0l8 3.2A2 2 0 0 1 22 8.35Z"/><path d="M6 18h12"/><path d="M6 14h12"/><rect width="12" height="12" x="6" y="10"/>',
    "layout-grid":      '<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/>',
    "server":           '<rect width="20" height="8" x="2" y="2" rx="2" ry="2"/><rect width="20" height="8" x="2" y="14" rx="2" ry="2"/><line x1="6" x2="6.01" y1="6" y2="6"/><line x1="6" x2="6.01" y1="18" y2="18"/>',
    "fuel":             '<line x1="3" x2="15" y1="22" y2="22"/><line x1="4" x2="14" y1="9" y2="9"/><path d="M14 22V4a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v18"/><path d="M14 13h2a2 2 0 0 1 2 2v2a2 2 0 0 0 2 2a2 2 0 0 0 2-2V9.83a2 2 0 0 0-.59-1.42L18 5"/>',
    "monitor":          '<rect width="20" height="14" x="2" y="3" rx="2"/><line x1="8" x2="16" y1="21" y2="21"/><line x1="12" x2="12" y1="17" y2="21"/>',
    "rows":             '<rect width="18" height="18" x="3" y="3" rx="2" ry="2"/><line x1="3" x2="21" y1="9" y2="9"/><line x1="3" x2="21" y1="15" y2="15"/>',
    "chevron-right":    '<path d="m9 18 6-6-6-6"/>',
    "chevron-down":     '<path d="m6 9 6 6 6-6"/>',
}

def make_svg(name: str, size: int = 16) -> str:
    """Build a Lucide SVG element."""
    paths = LUCIDE_SVGS[name]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
            f'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" '
            f'stroke-linecap="round" stroke-linejoin="round" data-lucide="{name}">'
            f'{paths}</svg>')

# Mapping of nav-item routes to Lucide icon names
NAV_ICON_MAP = {
    "overview":       "activity",
    "scenarios":      "flask-conical",
    "power":          "zap",
    "cooling":        "snowflake",
    "incidents":      "alert-triangle",
    "mops":           "file-text",
    "topology":       "network",
    "bms":            "plug",
    "copilot":        "bot",
    "morpheus":       "shield-check",
    "gemini":         "cpu",
    "omniverse":      "box",
    "site_topology":  "building-2",
}

def read_bytes(p: Path) -> bytes:
    return p.read_bytes()

def write_bytes(p: Path, data: bytes) -> None:
    p.write_bytes(data)

# ───────────────────────────────────────────────────────────────
print("=== Lucide SVG Inliner — Sprint S1b Part C ===")
print(f"Index: {INDEX_PATH}")
print(f"JS:    {JS_PATH}")
print(f"CSS:   {CSS_PATH}")
print()

# Backup
INDEX_BAK = INDEX_PATH.with_suffix('.html.bak_pre_lucide')
JS_BAK = JS_PATH.with_suffix('.js.bak_pre_lucide')
CSS_BAK = CSS_PATH.with_suffix('.css.bak_pre_lucide')
for src, bak in [(INDEX_PATH, INDEX_BAK), (JS_PATH, JS_BAK), (CSS_PATH, CSS_BAK)]:
    if not bak.exists():
        write_bytes(bak, read_bytes(src))
print("Safety backups created (.bak_pre_lucide)")

# ───────────────────────────────────────────────────────────────
# Edit 1: Replace emoji icons in nav-items (index.html)
# ───────────────────────────────────────────────────────────────
print()
print("--- Edit 1: nav-item icons in index.html ---")
index_data = read_bytes(INDEX_PATH)
replaced_count = 0

for route, icon_name in NAV_ICON_MAP.items():
    # Find the nav-item with this route. Pattern is approximately:
    # <div class="nav-item ...?" data-route="ROUTE">...<span class="icon">EMOJI_OR_ENTITY</span>LABEL</div>
    # We replace the inner of <span class="icon">...</span>

    route_marker = f'data-route="{route}"'.encode('utf-8')
    pos = index_data.find(route_marker)
    if pos < 0:
        print(f"  [skip] route {route!r} not found")
        continue

    # Find the next <span class="icon"> after this position
    span_open = b'<span class="icon">'
    span_pos = index_data.find(span_open, pos)
    if span_pos < 0 or span_pos > pos + 200:  # within reasonable distance
        print(f"  [skip] icon span not found near route {route!r}")
        continue

    # Find the closing </span>
    content_start = span_pos + len(span_open)
    span_close = index_data.find(b'</span>', content_start)
    if span_close < 0 or span_close > content_start + 50:
        print(f"  [skip] closing </span> not found for route {route!r}")
        continue

    new_inner = make_svg(icon_name).encode('utf-8')
    index_data = index_data[:content_start] + new_inner + index_data[span_close:]
    replaced_count += 1
    print(f"  [ok] {route} -> {icon_name}")

print(f"Replaced {replaced_count} / {len(NAV_ICON_MAP)} nav icons")

# Write index.html
write_bytes(INDEX_PATH, index_data)
print(f"Written index.html ({len(index_data)} bytes)")

# ───────────────────────────────────────────────────────────────
# Edit 2: Replace tree icons in app.js (Site Topology renderer)
# ───────────────────────────────────────────────────────────────
print()
print("--- Edit 2: tree icons in app.js ---")
js_data = read_bytes(JS_PATH)

# In the tree, icons are set via `.textContent = '\u25B8';` etc.
# We'll change these to set innerHTML with an SVG instead.
#
# Specific patterns to replace:
#   _stBuildingNode: icon.textContent = '\u25A6';        -> warehouse
#   _stRoomNode iconMap: many entries                    -> server, layout-grid, zap, snowflake, etc.
#   _stRowNode: icon.textContent = '\u2261';             -> rows
#
# Strategy: replace the emoji-based functions with SVG-based versions.

# Replace building icon (\u25A6 -> warehouse SVG)
# The SVG must be small for tree (size 14)
def make_svg_small(name: str) -> str:
    return make_svg(name, size=14)

# Patterns for tree icons:
tree_replacements = [
    # Building node - line: const icon = document.createElement('span'); icon.className = 'st-tree-icon'; icon.textContent = '\u25A6';
    (
        b"const icon = document.createElement('span'); icon.className = 'st-tree-icon'; icon.textContent = '\\u25A6';",
        b"const icon = document.createElement('span'); icon.className = 'st-tree-icon'; icon.innerHTML = '" + make_svg_small("warehouse").encode('utf-8') + b"';",
    ),
    # Row node - line: const icon = document.createElement('span'); icon.className = 'st-tree-icon'; icon.textContent = '\u2261';
    (
        b"const icon = document.createElement('span'); icon.className = 'st-tree-icon'; icon.textContent = '\\u2261';",
        b"const icon = document.createElement('span'); icon.className = 'st-tree-icon'; icon.innerHTML = '" + make_svg_small("rows").encode('utf-8') + b"';",
    ),
    # Room node iconMap rebuild + lookup
    (
        b"const iconMap = { data_hall:'\\u25A5', electrical_room:'\\u26A1', mechanical_room:'\\u2744', mechanical_plant:'\\u2744', emergency_power:'\\u26A1', utility_intake:'\\u26A1', fuel_depot:'\\u26FD', control_room:'\\u25A3' };\n        const icon = document.createElement('span'); icon.className = 'st-tree-icon'; icon.textContent = iconMap[room.type] || '\\u00B7';",
        b"const iconMap = { data_hall:'server', electrical_room:'zap', mechanical_room:'snowflake', mechanical_plant:'snowflake', emergency_power:'zap', utility_intake:'zap', fuel_depot:'fuel', control_room:'monitor' };\n        const iconName = iconMap[room.type] || 'layout-grid';\n        const icon = document.createElement('span'); icon.className = 'st-tree-icon'; icon.innerHTML = _stLucideSvg(iconName);",
    ),
]

# Try CRLF first then LF
def try_replace_with_eol(data: bytes, old_lf: bytes, new_lf: bytes) -> tuple[bytes, bool]:
    old_crlf = old_lf.replace(b'\n', b'\r\n')
    new_crlf = new_lf.replace(b'\n', b'\r\n')
    if old_crlf in data:
        return data.replace(old_crlf, new_crlf, 1), True
    if old_lf in data:
        return data.replace(old_lf, new_lf, 1), True
    return data, False

tree_replaced = 0
for old, new in tree_replacements:
    js_data, ok = try_replace_with_eol(js_data, old, new)
    if ok:
        tree_replaced += 1
        print(f"  [ok] tree replacement {tree_replaced}")
    else:
        print(f"  [skip] tree marker not matched (snippet: {old[:60]!r}...)")

# Add helper function _stLucideSvg + chevron icons for toggles
# Find a good spot: just after the line "let _stInitialized = false;"
helper_marker = b"let _stInitialized = false;"
chevron_right_svg = make_svg("chevron-right", size=12)
chevron_down_svg = make_svg("chevron-down", size=12)

# Build small SVG strings for ALL tree icons we use
all_tree_svgs = {
    name: make_svg_small(name) for name in
    ["warehouse", "server", "layout-grid", "zap", "snowflake",
     "fuel", "monitor", "rows"]
}

helper_fn_lines = [
    b"",
    b"    // Lucide SVG icons map for tree (size 14 for leaves/rooms)",
    b"    const _ST_LUCIDE_SVGS = {",
]
for name, svg in all_tree_svgs.items():
    # Escape quotes
    safe_svg = svg.replace("'", "\\'")
    helper_fn_lines.append(f"        {name.replace('-', '_')}: '{safe_svg}',".encode('utf-8'))
helper_fn_lines.append(b"    };")
helper_fn_lines.append(b"    function _stLucideSvg(name) {")
helper_fn_lines.append(b"        return _ST_LUCIDE_SVGS[name.replace(/-/g, '_')] || '';")
helper_fn_lines.append(b"    }")
helper_fn_lines.append(b"")

helper_block_lf = b"\n".join(helper_fn_lines)

# Insert AFTER the helper marker line
if helper_marker in js_data:
    eol_byte = b"\r\n" if b"\r\n" in js_data[:1000] else b"\n"
    helper_block = helper_block_lf.replace(b"\n", eol_byte)
    full_marker = helper_marker + (b"\r\n" if eol_byte == b"\r\n" else b"\n")
    if full_marker in js_data:
        js_data = js_data.replace(full_marker, full_marker + helper_block + eol_byte, 1)
        print("  [ok] _stLucideSvg helper inserted")
    else:
        print("  [warn] _stLucideSvg insert: line ending mismatch, trying simple")
        js_data = js_data.replace(helper_marker, helper_marker + b"\n" + helper_block_lf, 1)

# Replace toggle text content (\u25B8 / \u25BE) with SVG.
# Pattern: toggle.textContent = '\u25B8'; (initial state)
# Pattern: toggle.textContent = expanded ? '\u25B8' : '\u25BE'; (toggle state)

js_data = js_data.replace(
    b"toggle.textContent = '\\u25B8';",
    b"toggle.innerHTML = '" + chevron_right_svg.encode('utf-8') + b"';"
)
js_data = js_data.replace(
    b"toggle.textContent = expanded ? '\\u25B8' : '\\u25BE';",
    b"toggle.innerHTML = expanded ? '" + chevron_right_svg.encode('utf-8') + b"' : '" + chevron_down_svg.encode('utf-8') + b"';"
)
print("  [ok] chevron toggles replaced")

# Write app.js
write_bytes(JS_PATH, js_data)
print(f"Written app.js ({len(js_data)} bytes)")

# ───────────────────────────────────────────────────────────────
# Edit 3: Append CSS for nav-item icons (hover + active states)
# ───────────────────────────────────────────────────────────────
print()
print("--- Edit 3: append icon CSS to app.css ---")
css_data = read_bytes(CSS_PATH)

icon_css_block = b"""

/* ============================================================
 * Sprint S1b - Lucide SVG icon styling for nav-items + tree
 * ============================================================ */
.nav-item .icon svg {
    width: 16px;
    height: 16px;
    stroke-width: 1.5;
    stroke: currentColor;
    fill: none;
    vertical-align: middle;
    margin-right: 4px;
    transition: stroke 120ms ease, filter 120ms ease, transform 120ms ease;
}
.nav-item:hover .icon svg {
    stroke: var(--cyan, #00B8D4);
    transform: translateX(1px);
}
.nav-item.active .icon svg {
    stroke: var(--cyan, #00B8D4);
    filter: drop-shadow(0 0 4px rgba(0, 184, 212, 0.55));
}

/* Site Topology tree icons */
.st-tree-icon svg,
.st-tree-toggle svg {
    width: 14px;
    height: 14px;
    stroke-width: 1.5;
    stroke: currentColor;
    fill: none;
    vertical-align: middle;
}
.st-tree-toggle svg {
    width: 12px;
    height: 12px;
}
.st-tree-row:hover .st-tree-icon svg,
.st-tree-row.st-selected .st-tree-icon svg {
    stroke: var(--cyan, #00B8D4);
}
.st-tree-leaf.st-selected,
.st-tree-row.st-selected {
    background: rgba(0, 184, 212, 0.12);
}
"""

# Append (use original line endings)
eol_byte = b"\r\n" if b"\r\n" in css_data[:200] else b"\n"
icon_css_block_eol = icon_css_block.replace(b"\n", eol_byte) if eol_byte == b"\r\n" else icon_css_block

css_data = css_data + icon_css_block_eol
write_bytes(CSS_PATH, css_data)
print(f"Written app.css ({len(css_data)} bytes)")

print()
print("=== ALL LUCIDE EDITS APPLIED ===")
print("Restart server and hard reload browser.")
print()
print("Expected:")
print("  - All 13 sidebar nav-items now use Lucide SVG icons")
print("  - Hover effect: cyan stroke + 1px slide right")
print("  - Active state: cyan stroke + drop-shadow glow")
print("  - Site Topology tree uses Lucide icons (warehouse, server, zap, etc.)")
