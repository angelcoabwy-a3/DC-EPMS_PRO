# Sprint S1b — Edit #4 fix: relocate the site-topology section
# from being a child of <main> to being a child of <section class="panel-main">

$root = "C:\dev\DC-EPMS_PRO\frontend"
$indexPath = Join-Path $root "index.html"

$content = [System.IO.File]::ReadAllText($indexPath)

# Step 1: Extract the site-topology section that's currently misplaced
$sectionStartPattern = '(?s)\s*<!-- View: Site Topology \(Sprint S1b\) -->\s*\r?\n\s*<div class="view" id="view-site-topology" hidden>'
$sectionStartMatch = [regex]::Match($content, $sectionStartPattern)

if (-not $sectionStartMatch.Success) {
    Write-Host "ERROR: site-topology section start marker not found. Did Edit B not run?" -ForegroundColor Red
    Write-Host "Check: Select-String -Path $indexPath -Pattern 'view-site-topology'" -ForegroundColor Yellow
    exit 1
}

$startIdx = $sectionStartMatch.Index

# Find the matching closing </div> by counting div depth from this point
# Skip the opening <div> we matched and walk forward
$openDivCount = 1
$i = $sectionStartMatch.Index + $sectionStartMatch.Length
$endIdx = -1

while ($i -lt $content.Length -and $openDivCount -gt 0) {
    $nextOpen = $content.IndexOf('<div', $i)
    $nextClose = $content.IndexOf('</div>', $i)

    if ($nextClose -eq -1) { break }

    if ($nextOpen -ne -1 -and $nextOpen -lt $nextClose) {
        $openDivCount++
        $i = $nextOpen + 4
    } else {
        $openDivCount--
        if ($openDivCount -eq 0) {
            $endIdx = $nextClose + 6  # length of "</div>"
            break
        }
        $i = $nextClose + 6
    }
}

if ($endIdx -eq -1) {
    Write-Host "ERROR: could not find matching </div> for the site-topology section" -ForegroundColor Red
    exit 1
}

# Extract the section block (including leading whitespace and trailing newline)
# Walk back to include the leading newline + indentation
$blockStart = $startIdx
while ($blockStart -gt 0 -and ($content[$blockStart - 1] -eq ' ' -or $content[$blockStart - 1] -eq "`t")) { $blockStart-- }
if ($blockStart -gt 0 -and $content[$blockStart - 1] -eq "`n") { $blockStart-- }
if ($blockStart -gt 0 -and $content[$blockStart - 1] -eq "`r") { $blockStart-- }

# Walk forward to include trailing newline
$blockEnd = $endIdx
if ($blockEnd -lt $content.Length -and $content[$blockEnd] -eq "`r") { $blockEnd++ }
if ($blockEnd -lt $content.Length -and $content[$blockEnd] -eq "`n") { $blockEnd++ }

$extractedBlock = $content.Substring($blockStart, $blockEnd - $blockStart)
Write-Host "Step 1 OK: extracted section ($($extractedBlock.Length) chars)" -ForegroundColor Green

# Remove from current location
$contentWithoutSection = $content.Substring(0, $blockStart) + $content.Substring($blockEnd)

# Step 2: Find the </section> that closes panel-main, insert section right before it
# panel-main opens at line 62 and closes at line 1271 according to the user's report
# We use a smarter approach: find the LAST </section> that comes before </main>
$mainClosePattern = '(?m)^    </main>'
$mainCloseMatch = [regex]::Match($contentWithoutSection, $mainClosePattern)

if (-not $mainCloseMatch.Success) {
    Write-Host "ERROR: </main> not found" -ForegroundColor Red
    exit 1
}

# Find the </section> that immediately precedes </main>
$mainCloseIdx = $mainCloseMatch.Index
$searchUpTo = $mainCloseIdx
$lastSectionClose = $contentWithoutSection.LastIndexOf('</section>', $searchUpTo)

if ($lastSectionClose -eq -1) {
    Write-Host "ERROR: no </section> before </main>" -ForegroundColor Red
    exit 1
}

# Walk back to include the leading whitespace before </section>
$insertPoint = $lastSectionClose
while ($insertPoint -gt 0 -and ($contentWithoutSection[$insertPoint - 1] -eq ' ' -or $contentWithoutSection[$insertPoint - 1] -eq "`t")) { $insertPoint-- }

# Build new content: insert the extracted section right before this position
$newContent = $contentWithoutSection.Substring(0, $insertPoint) + $extractedBlock + $contentWithoutSection.Substring($insertPoint)

[System.IO.File]::WriteAllText($indexPath, $newContent, [System.Text.UTF8Encoding]::new($false))
Write-Host "Step 2 OK: section moved inside <section class='panel-main'>" -ForegroundColor Green

# Verify
$verify = [System.IO.File]::ReadAllText($indexPath)
$panelMainOpen = $verify.IndexOf('<section class="panel-main">')
$siteTopo = $verify.IndexOf('id="view-site-topology"')
$panelMainClose = $verify.LastIndexOf('</section>', $verify.IndexOf('</main>'))

if ($panelMainOpen -lt $siteTopo -and $siteTopo -lt $panelMainClose) {
    Write-Host "Verify OK: view-site-topology is between panel-main open and close" -ForegroundColor Green
} else {
    Write-Host "Verify ERROR: positions don't match expectation" -ForegroundColor Red
    Write-Host "  panel-main open: $panelMainOpen"
    Write-Host "  view-site-topology: $siteTopo"
    Write-Host "  panel-main close: $panelMainClose"
}

Write-Host "`n=== Done. Hard reload the browser. ===" -ForegroundColor Cyan
