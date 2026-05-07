# Sprint S1b — Edit #4 fix v3
# Move the site-topology view block from its wrong location (after </section>)
# to its correct location (before </section> of panel-main)
#
# Strategy: line-based manipulation. No regex. No encoding issues.

$indexPath = "C:\dev\DC-EPMS_PRO\frontend\index.html"
$lines = [System.IO.File]::ReadAllLines($indexPath)

Write-Host "Total lines: $($lines.Count)" -ForegroundColor Cyan

# ───────────────────────────────────────────────────────────
# Step 1: Locate key markers
# ───────────────────────────────────────────────────────────
# We expect (1-indexed in user view, 0-indexed in $lines):
#   panelMainCloseLine: line containing "        </section>" that closes panel-main
#                       (NOT the inner </section> of view-site-topology)
#   viewSiteTopoStartLine: line with comment "<!-- View: Site Topology"
#   viewSiteTopoEndLine: matching </div> for the view block
#
# Strategy:
#   - Find the comment marker (unique)
#   - Walk forward to find the closing </div> by matching nesting
#   - Find the </section> that's BEFORE the comment marker (panel-main closer)

$commentIdx = -1
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '<!-- View: Site Topology \(Sprint S1b\) -->') {
        $commentIdx = $i
        break
    }
}

if ($commentIdx -eq -1) {
    Write-Host "ERROR: comment marker '<!-- View: Site Topology (Sprint S1b) -->' not found" -ForegroundColor Red
    exit 1
}
Write-Host "Comment marker at line $($commentIdx + 1)" -ForegroundColor Green

# Find the opening <div class="view" id="view-site-topology" hidden> right after the comment
$divOpenIdx = -1
for ($i = $commentIdx; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match 'id="view-site-topology"') {
        $divOpenIdx = $i
        break
    }
}

if ($divOpenIdx -eq -1) {
    Write-Host "ERROR: opening <div id='view-site-topology'> not found" -ForegroundColor Red
    exit 1
}
Write-Host "View div opens at line $($divOpenIdx + 1)" -ForegroundColor Green

# Now walk forward counting div depth to find matching </div>
$depth = 1
$divCloseIdx = -1
$i = $divOpenIdx + 1
while ($i -lt $lines.Count) {
    $line = $lines[$i]
    # Count <div openings (rough: matches "<div " or "<div>")
    $opens = ([regex]::Matches($line, '<div(\s|>)')).Count
    $closes = ([regex]::Matches($line, '</div>')).Count
    $depth = $depth + $opens - $closes
    if ($depth -eq 0) {
        $divCloseIdx = $i
        break
    }
    $i++
}

if ($divCloseIdx -eq -1) {
    Write-Host "ERROR: closing </div> for view-site-topology not found" -ForegroundColor Red
    exit 1
}
Write-Host "View div closes at line $($divCloseIdx + 1)" -ForegroundColor Green

# Find the </section> that closes panel-main: it's the nearest </section> BEFORE the comment
$panelMainCloseIdx = -1
for ($i = $commentIdx - 1; $i -ge 0; $i--) {
    if ($lines[$i] -match '^\s*</section>\s*$') {
        $panelMainCloseIdx = $i
        break
    }
}

if ($panelMainCloseIdx -eq -1) {
    Write-Host "ERROR: panel-main </section> not found before comment" -ForegroundColor Red
    exit 1
}
Write-Host "panel-main </section> at line $($panelMainCloseIdx + 1)" -ForegroundColor Green

# ───────────────────────────────────────────────────────────
# Step 2: Build new line list
# ───────────────────────────────────────────────────────────
# Identify the block to move:
#   - From: line right before the comment (to capture the blank line)
#   - To: divCloseIdx (inclusive)
# Block to MOVE: $commentIdx .. $divCloseIdx (or include leading blank if exists)

# Capture leading blank line if present (visual separation)
$blockStart = $commentIdx
if ($blockStart -gt 0 -and $lines[$blockStart - 1].Trim() -eq '') {
    $blockStart--
}
$blockEnd = $divCloseIdx

Write-Host "Block to move: lines $($blockStart + 1) to $($blockEnd + 1) ($($blockEnd - $blockStart + 1) lines)" -ForegroundColor Cyan

# Extract the block
$blockLines = $lines[$blockStart..$blockEnd]

# Build new array:
#   1. Everything from start to panelMainCloseIdx-1 (i.e., before </section>)
#   2. blockLines
#   3. The </section> line and everything after, EXCEPT the original block location
$newLines = New-Object System.Collections.ArrayList
for ($i = 0; $i -lt $panelMainCloseIdx; $i++) {
    [void]$newLines.Add($lines[$i])
}
# Insert block here (before panel-main close)
foreach ($bl in $blockLines) {
    [void]$newLines.Add($bl)
}
# Continue from panelMainCloseIdx onward, but skip the original block lines
for ($i = $panelMainCloseIdx; $i -lt $lines.Count; $i++) {
    if ($i -ge $blockStart -and $i -le $blockEnd) { continue }
    [void]$newLines.Add($lines[$i])
}

Write-Host "New line count: $($newLines.Count) (was $($lines.Count))" -ForegroundColor Cyan

# Write back, preserving CRLF line endings
$newContent = ($newLines -join "`r`n") + "`r`n"
[System.IO.File]::WriteAllText($indexPath, $newContent, [System.Text.UTF8Encoding]::new($false))
Write-Host "File written" -ForegroundColor Green

# Verify
$check = [System.IO.File]::ReadAllText($indexPath)
$panelOpen = $check.IndexOf('<section class="panel-main">')
$siteTopo = $check.IndexOf('id="view-site-topology"')
$endMain = $check.IndexOf('</main>')
$panelCloseSearch = $check.LastIndexOf('</section>', $endMain)

if ($panelOpen -lt $siteTopo -and $siteTopo -lt $panelCloseSearch) {
    Write-Host "`n=== VERIFY OK: view-site-topology is now INSIDE panel-main ===" -ForegroundColor Green
    Write-Host "  panel-main open at char  $panelOpen" -ForegroundColor Cyan
    Write-Host "  view-site-topology at    $siteTopo" -ForegroundColor Cyan
    Write-Host "  panel-main close at      $panelCloseSearch" -ForegroundColor Cyan
    Write-Host "  </main> at               $endMain" -ForegroundColor Cyan
} else {
    Write-Host "`n=== VERIFY FAILED ===" -ForegroundColor Red
    Write-Host "  panel-main open: $panelOpen"
    Write-Host "  view-site-topology: $siteTopo"
    Write-Host "  panel-main close: $panelCloseSearch"
    Write-Host "  </main>: $endMain"
}
