$copilotPath = "C:\dev\DC-EPMS_PRO\backend\agent_copilot.py"
$content = [System.IO.File]::ReadAllText($copilotPath)

# Marker matches the actual file: 1 blank line between log.warning and return reg
# Using regex to be tolerant of whitespace variants
$pattern = @'
(?ms)        log\.warning\(f"\[v8\.1\] CMMS work-order tool NOT registered: \{e\}"\)\r?\n\s*\r?\n    return reg
'@

$replacement = @'
        log.warning(f"[v8.1] CMMS work-order tool NOT registered: {e}")

    # Sprint S1b: Site Model query tool
    try:
        from agent_site_tool import tool_query_site_model, QUERY_SITE_MODEL_SCHEMA
        reg.register("query_site_model", tool_query_site_model)
        TOOLS_SCHEMA.append(QUERY_SITE_MODEL_SCHEMA)
        log.info("[Sprint S1b] Site model query tool registered")
    except Exception as e:
        log.warning(f"[Sprint S1b] Site model query tool NOT registered: {e}")

    return reg
'@

if ($content -match $pattern) {
    $newContent = [regex]::Replace($content, $pattern, $replacement, 1)
    [System.IO.File]::WriteAllText($copilotPath, $newContent, [System.Text.UTF8Encoding]::new($false))
    Write-Host "OK: Site tool registration block inserted in agent_copilot.py" -ForegroundColor Green
} else {
    Write-Host "ERROR: pattern not matched. agent_copilot.py unchanged." -ForegroundColor Red
    Write-Host "Diagnostic: searching for fragments..." -ForegroundColor Yellow
    if ($content.Contains('log.warning(f"[v8.1] CMMS work-order tool NOT registered:')) {
        Write-Host "  - log.warning line: FOUND" -ForegroundColor Cyan
    } else {
        Write-Host "  - log.warning line: NOT FOUND" -ForegroundColor Red
    }
    if ($content -match 'return reg') {
        Write-Host "  - 'return reg': FOUND" -ForegroundColor Cyan
    }
}
