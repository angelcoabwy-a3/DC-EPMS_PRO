$root = "C:\dev\DC-EPMS_PRO\backend"
$siteToolPath = Join-Path $root "agent_site_tool.py"
$copilotPath  = Join-Path $root "agent_copilot.py"

# Part A: append schema constant to agent_site_tool.py
$schemaConst = @"


# Schema in the format expected by agent_copilot.TOOLS_SCHEMA
QUERY_SITE_MODEL_SCHEMA: dict = {
    "type": "function",
    "function": {
        "name": TOOL_DEFINITION["name"],
        "description": TOOL_DEFINITION["description"],
        "parameters": TOOL_DEFINITION["input_schema"],
    },
}
"@

$existing = [System.IO.File]::ReadAllText($siteToolPath)
[System.IO.File]::WriteAllText($siteToolPath, $existing + $schemaConst, [System.Text.UTF8Encoding]::new($false))
Write-Host "Part A OK: schema constant appended" -ForegroundColor Green

# Part B: insert tool registration in agent_copilot.py
$content = [System.IO.File]::ReadAllText($copilotPath)

$marker = @"
        log.info("[v8.1] CMMS work-order tool registered")
    except Exception as e:
        log.warning(f"[v8.1] CMMS work-order tool NOT registered: {e}")
    return reg
"@

$replacement = @"
        log.info("[v8.1] CMMS work-order tool registered")
    except Exception as e:
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
"@

if ($content.Contains($marker)) {
    $newContent = $content.Replace($marker, $replacement)
    [System.IO.File]::WriteAllText($copilotPath, $newContent, [System.Text.UTF8Encoding]::new($false))
    Write-Host "Part B OK: registration block inserted" -ForegroundColor Green
} else {
    Write-Host "Part B ERROR: marker not matched" -ForegroundColor Red
}
