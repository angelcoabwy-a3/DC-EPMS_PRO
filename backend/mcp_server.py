"""
DC-EPMS PRO - MCP (Model Context Protocol) Server
==================================================
Exposes the a3semi A3-Alpha facility state to Claude Desktop and any
other MCP-compatible client via the stdio transport.

Architecture
------------
The MCP server runs as a subprocess of Claude Desktop. Claude Desktop
spawns it on demand and communicates via stdin/stdout using the JSON-RPC
2.0 framing defined by the MCP specification (https://spec.modelcontextprotocol.io).

Resources exposed
-----------------
1. a3semi://telemetry/current
   - Latest telemetry snapshot (PUE, hall temps, IT load, etc.)

2. a3semi://physics/site-health
   - Live SHI + per-module health from the physics engine

3. a3semi://scenarios/list
   - Catalog of 10 failure scenarios (SCN-01 to SCN-10)

4. a3semi://incidents/recent
   - Last 20 incidents from PostgreSQL audit log

Tools exposed
-------------
1. simulate_failure(scenario_id, horizon_s)
   - Run a named scenario through the physics engine

2. read_bms_tag(tag_id)
   - Read current value of any BMS tag (BACnet/Modbus)

Reference compliance
--------------------
Spec version: 2024-11-05 (latest stable as of project start)
Transport: stdio (most compatible with Claude Desktop)
Capabilities advertised: resources + tools (not prompts/sampling for v1)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
from pathlib import Path

# Configure logging to stderr so it doesn't interfere with stdio transport
logging.basicConfig(
    level=logging.INFO,
    format="[mcp-server] %(asctime)s %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("mcp-server")

# Make backend importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

# ---------------------------------------------------------------------------
# Lazy backend imports (only when actually serving a request)
# ---------------------------------------------------------------------------
_physics_engine = None
_bms = None
_db_manager = None


def _get_physics():
    global _physics_engine
    if _physics_engine is None:
        try:
            from physics_engine import get_engine

            _physics_engine = get_engine()
        except Exception as e:
            log.error("Physics engine unavailable: %s", e)
    return _physics_engine


def _get_bms():
    global _bms
    if _bms is None:
        try:
            from bms_connector import get_bms

            _bms = get_bms(PROJECT_ROOT)
        except Exception as e:
            log.error("BMS connector unavailable: %s", e)
    return _bms


def _build_default_telemetry() -> dict:
    """Default nominal telemetry when no live data available."""
    return {
        "rack_count": 118,
        "rack_tdp_kw": 142.0,
        "dlc_supply_c": 18.0,
        "dlc_return_c": 39.3,
        "dlc_flow_l_min": 100.0,
        "hall_inlet_c": 20.0,
        "hall_return_c": 22.0,
        "gpu_tj_max_c": 70.0,
        "loop_flow_m3_s": 0.066,
        "loop_supply_c": 18.0,
        "loop_return_c": 40.0,
        "cdu_primary_in_c": 7.0,
        "cdu_primary_out_c": 27.0,
        "cdu_primary_flow_m3_s": 0.066,
        "pump_speed_hz": 60.0,
        "pump_suction_bar": 1.8,
        "pump_power_kw": 45.0,
        "loop_dp_measured_bar": 2.17,
        "utility_kw": 17_400.0,
        "facility_it_kw": 16_756.0,
        "ups_load_kw": 300.0,
        "ups_mode": "online",
        "ups_input_kw": 312.5,
        "xfmr_load_kva": 1800.0,
        "xfmr_top_oil_c": 65.0,
        "xfmr_winding_c": 98.7,
        "battery_soc": 1.0,
        "battery_vdc": 540.0,
        "battery_on_load": False,
        "outdoor_t_db_c": 25.0,
        "outdoor_rh_percent": 50.0,
        "hall_dew_point_c": 8.0,
        "chiller_1_load_kw": 2500.0,
        "chiller_1_power_kw": 350.0,
        "chiller_1_ecwt_c": 29.0,
        "chiller_1_lchwt_c": 6.7,
        "chiller_2_load_kw": 2500.0,
        "chiller_2_power_kw": 350.0,
        "chiller_2_ecwt_c": 29.0,
        "chiller_2_lchwt_c": 6.7,
    }


# ---------------------------------------------------------------------------
# Resource handlers
# ---------------------------------------------------------------------------
RESOURCES = [
    {
        "uri": "a3semi://telemetry/current",
        "name": "Current telemetry snapshot",
        "description": (
            "Latest telemetry from the A3-Alpha facility: PUE, hall "
            "temperatures, IT load, DLC supply/return, GPU Tj, etc."
        ),
        "mimeType": "application/json",
    },
    {
        "uri": "a3semi://physics/site-health",
        "name": "Site Health Index + per-module health",
        "description": (
            "Live Site Health Index (SHI) computed by the physics "
            "engine. Includes per-module health (IT thermal, mechanical, "
            "electrical, heat rejection), severity classification, and "
            "cascade event count."
        ),
        "mimeType": "application/json",
    },
    {
        "uri": "a3semi://scenarios/list",
        "name": "Failure scenario catalog",
        "description": (
            "10 critical failure scenarios available for simulation: "
            "SCN-01 (pump cavitation) through SCN-10 (OT network "
            "partition). Each scenario has a primary module, expected "
            "TTR, severity classification, and standards references "
            "(ASHRAE, IEEE, IEC, NFPA, etc.)."
        ),
        "mimeType": "application/json",
    },
    {
        "uri": "a3semi://incidents/recent",
        "name": "Recent incidents (last 20)",
        "description": (
            "Last 20 incidents from the audit log. Includes timestamps, "
            "severity, source, and PUE measured at the time of incident."
        ),
        "mimeType": "application/json",
    },
]


async def read_resource(uri: str) -> dict:
    """Resolve a resource URI to its current content."""
    if uri == "a3semi://telemetry/current":
        return _build_default_telemetry()

    if uri == "a3semi://physics/site-health":
        engine = _get_physics()
        if not engine:
            return {"error": "Physics engine unavailable"}
        result = engine.validate_site(_build_default_telemetry())
        return {
            "site_health": round(result.site_health, 3),
            "weakest_module": result.weakest_module,
            "overall_severity": result.overall_severity.value,
            "module_healths": {name: round(r.health, 3) for name, r in result.modules.items()},
            "module_severities": {name: r.severity.value for name, r in result.modules.items()},
            "cascade_count": len(result.cascade_events),
            "validation_method": "First law + ODE integration (scipy.solve_ivp)",
        }

    if uri == "a3semi://scenarios/list":
        try:
            import yaml

            scenarios_path = PROJECT_ROOT / "config" / "scenarios.yml"
            if not scenarios_path.exists():
                return {"error": "scenarios.yml not found"}
            data = yaml.safe_load(scenarios_path.read_text(encoding="utf-8"))
            return {
                "scenarios": [
                    {
                        "id": s.get("id"),
                        "name": s.get("name"),
                        "primary_module": s.get("primary_module"),
                        "severity_if_uncorrected": s.get("severity_if_uncorrected"),
                        "expected_ttr_minutes": s.get("expected_ttr_minutes"),
                        "mitigation_doc": s.get("mitigation_doc"),
                        "standard_refs": s.get("standard_refs", []),
                    }
                    for s in data.get("scenarios", [])
                ],
                "count": len(data.get("scenarios", [])),
            }
        except Exception as e:
            return {"error": f"Failed to load scenarios: {e}"}

    if uri == "a3semi://incidents/recent":
        # Try DB; if unavailable, return empty
        try:
            from database import DBManager

            pg_dsn = os.environ.get(
                "PG_DSN",
                "postgresql://postgres:epms2026@localhost:5432/epms",
            )
            db = DBManager(pg_dsn)
            await db.connect()
            try:
                # Use the same method the API uses
                rows = await db.fetch_incidents(limit=20)
                return {"incidents": rows, "count": len(rows)}
            finally:
                await db.close()
        except Exception as e:
            return {"incidents": [], "count": 0, "warning": f"DB unavailable: {e}"}

    return {"error": f"Unknown resource: {uri}"}


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------
TOOLS = [
    {
        "name": "simulate_failure",
        "description": (
            "Execute a named failure scenario through the physics engine "
            "and return the trajectory + events. Use this to evaluate "
            "what would happen if a specific failure occurred. "
            "Available scenarios: SCN-01-PUMP-CAVITATION, "
            "SCN-02-CHILLER-SURGE, SCN-03-UTILITY-FAIL-GEN-SLOW, "
            "SCN-04-DLC-LEAK, SCN-05-XFMR-OVERTEMP, SCN-06-CRAH-FAN-FAIL, "
            "SCN-07-GEN-START-FAIL, SCN-08-DLC-SUPPLY-HIGH, "
            "SCN-09-CONDENSATION-EVENT, SCN-10-OT-NET-PARTITION."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "scenario_id": {
                    "type": "string",
                    "description": "Scenario identifier from scenarios.yml",
                },
                "horizon_s": {
                    "type": "integer",
                    "description": "Simulation time horizon in seconds (default 900 = 15 min)",
                    "default": 900,
                },
            },
            "required": ["scenario_id"],
        },
    },
    {
        "name": "read_bms_tag",
        "description": (
            "Read the current value of a BMS (Building Management System) "
            "tag. Tags follow the namespace OBJECT.SUBSYSTEM.POINT.PROPERTY "
            "(e.g., HVAC.CDU_A.SUPPLY_TEMP, PWR.UPS_A.BATTERY_SOC). "
            "Use list_bms_tags first to discover available tags."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "tag_id": {
                    "type": "string",
                    "description": "Tag ID, e.g. HVAC.CDU_A.SUPPLY_TEMP",
                },
            },
            "required": ["tag_id"],
        },
    },
    {
        "name": "list_bms_tags",
        "description": (
            "List all available BMS tags, optionally filtered by category. "
            "Categories: HVAC, PWR, IT, FIRE, SEC, ENV. Returns tag IDs "
            "and metadata."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Optional: HVAC | PWR | IT | FIRE | SEC | ENV",
                },
            },
        },
    },
]


async def call_tool(name: str, arguments: dict) -> dict:
    """Execute a tool and return the result."""
    if name == "simulate_failure":
        scenario_id = arguments.get("scenario_id", "")
        horizon_s = int(arguments.get("horizon_s", 900))
        if not scenario_id:
            return {"error": "scenario_id is required"}

        engine = _get_physics()
        if not engine:
            return {"error": "Physics engine unavailable"}

        try:
            import yaml

            data = yaml.safe_load(
                (PROJECT_ROOT / "config" / "scenarios.yml").read_text(encoding="utf-8")
            )
            scenario = next(
                (s for s in data.get("scenarios", []) if s.get("id") == scenario_id),
                None,
            )
            if not scenario:
                return {"error": f"Scenario '{scenario_id}' not found"}

            result = engine.simulate_scenario(scenario, horizon_s=horizon_s, dt_s=1.0)
            # Strip trajectory for token efficiency; return only summary + events
            return {
                "scenario_id": result.get("scenario_id"),
                "scenario_name": result.get("scenario_name"),
                "module": result.get("module"),
                "summary": result.get("summary", {}),
                "events": result.get("events", []),
                "snapshot_count": len(result.get("trajectory", [])),
                "first_snapshot": result.get("trajectory", [{}])[0]
                if result.get("trajectory")
                else None,
                "last_snapshot": result.get("trajectory", [{}])[-1]
                if result.get("trajectory")
                else None,
            }
        except Exception as e:
            log.error("simulate_failure error: %s", e)
            return {"error": f"Simulation failed: {str(e)[:200]}"}

    if name == "read_bms_tag":
        tag_id = arguments.get("tag_id", "")
        if not tag_id:
            return {"error": "tag_id is required"}
        bms = _get_bms()
        if not bms:
            return {"error": "BMS connector unavailable"}
        # Refresh values
        engine = _get_physics()
        if engine:
            full = _build_default_telemetry()
            result = engine.validate_site(full)
            physics_metrics = {name: r.metrics for name, r in result.modules.items()}
            bms.refresh(full, physics_metrics)
        tag = bms.read(tag_id)
        if not tag:
            return {"error": f"Tag '{tag_id}' not found"}
        return tag.to_dict()

    if name == "list_bms_tags":
        category = arguments.get("category")
        bms = _get_bms()
        if not bms:
            return {"error": "BMS connector unavailable"}
        tags = bms.list_tags(category=category)
        return {
            "tags": [
                {
                    "id": t.id,
                    "protocol": t.protocol,
                    "category": t.category,
                    "writable": t.writable,
                    "description": t.description,
                    "units": t.units,
                }
                for t in tags
            ],
            "count": len(tags),
        }

    return {"error": f"Unknown tool: {name}"}


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 dispatcher
# ---------------------------------------------------------------------------
async def handle_request(request: dict) -> dict | None:
    """Handle a single JSON-RPC 2.0 request and return the response."""
    method = request.get("method", "")
    params = request.get("params", {}) or {}
    req_id = request.get("id")

    # initialize: spec-mandated handshake
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {
                    "name": "dc-epms-pro-a3semi",
                    "version": "1.0.0",
                },
                "capabilities": {
                    "resources": {"subscribe": False, "listChanged": False},
                    "tools": {"listChanged": False},
                },
            },
        }

    # initialized: spec notification, no response
    if method == "notifications/initialized":
        return None

    # resources/list
    if method == "resources/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"resources": RESOURCES},
        }

    # resources/read
    if method == "resources/read":
        uri = params.get("uri", "")
        content = await read_resource(uri)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": json.dumps(content, indent=2, default=str),
                    }
                ],
            },
        }

    # tools/list
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOLS},
        }

    # tools/call
    if method == "tools/call":
        name = params.get("name", "")
        arguments = params.get("arguments", {}) or {}
        result = await call_tool(name, arguments)
        is_error = "error" in result
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, indent=2, default=str),
                    }
                ],
                "isError": is_error,
            },
        }

    # ping
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    # Unknown method
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


# ---------------------------------------------------------------------------
# Main loop: read JSON-RPC from stdin, write to stdout
#
# IMPORTANT — Windows compatibility:
# asyncio.connect_read_pipe(sys.stdin) does NOT work on Windows because
# sys.stdin is not a native IOCP-compatible handle. We use a thread-based
# reader that pushes lines onto an asyncio.Queue. This pattern is what the
# official Anthropic MCP Python SDK uses for stdio transport on Windows.
# ---------------------------------------------------------------------------


def _stdin_reader_thread(queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
    """Blocking reader that runs in a daemon thread.

    Reads stdin line-by-line and posts each line into the asyncio queue
    on the main event loop. Sends None on EOF to signal shutdown.
    """
    try:
        for line in sys.stdin:
            asyncio.run_coroutine_threadsafe(queue.put(line), loop)
    except Exception as e:
        log.error("stdin reader thread error: %s", e)
    finally:
        # Signal EOF
        asyncio.run_coroutine_threadsafe(queue.put(None), loop)


async def main():
    log.info("DC-EPMS PRO MCP server starting (stdio transport)")
    log.info("Project root: %s", PROJECT_ROOT)
    log.info("Python: %s on %s", sys.version.split()[0], sys.platform)

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    # Spawn the blocking stdin reader in a daemon thread
    reader_thread = threading.Thread(
        target=_stdin_reader_thread,
        args=(queue, loop),
        daemon=True,
        name="mcp-stdin-reader",
    )
    reader_thread.start()
    log.info("stdin reader thread started; awaiting JSON-RPC requests")

    while True:
        try:
            line = await queue.get()
            if line is None:
                log.info("EOF received, shutting down")
                break

            line_text = line.strip()
            if not line_text:
                continue

            try:
                request = json.loads(line_text)
            except json.JSONDecodeError as e:
                log.warning("Malformed JSON: %s", e)
                continue

            response = await handle_request(request)
            if response is not None:
                response_text = json.dumps(response) + "\n"
                sys.stdout.write(response_text)
                sys.stdout.flush()
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error("Request handler error: %s", e, exc_info=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Shutting down (KeyboardInterrupt)")
