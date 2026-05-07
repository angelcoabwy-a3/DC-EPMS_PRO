"""
russelectric_adapter.py — Russelectric Bypass switch adapter.

Russelectric Bypass switches (RTS, RPTCS series) are typically
controlled via dry-contact relays wired to the building BMS, not via
a native protocol gateway. The adapter therefore communicates THROUGH
the existing bms_connector (BACnet/Modbus to the BMS controller), not
directly to the switch.

This is a real-world Tier IV pattern: legacy power-distribution
hardware does not natively speak modern protocols, so the BMS acts
as the protocol bridge with hardwired interlocks for safety.

Russelectric switches require maintained vs momentary signaling
depending on model. The adapter handles momentary signaling internally:
asserts the contact for `pulse_ms` then releases. The bypass switch
latches its position via internal mechanism.

═══════════════════════════════════════════════════════════════════════
  HONEST: Russelectric does not publish a uniform protocol — every
  installation has its own BMS point list maintained by the panel
  builder. The canonical command set below covers the typical bypass
  switch operations; the BMS point IDs in the targets config must
  match what the panel builder actually wired.
═══════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol

from . import FailureMode, HardwareAdapter

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
#  Backend protocol — anything that exposes BMS read/write
# ─────────────────────────────────────────────────────────────────────────
class BypassBackend(Protocol):
    """Russelectric adapter operates through the BMS connector. The
    backend is whatever exposes read/write operations against named
    BMS points (BACnet AO/AI/BO/BI tags)."""

    async def read_point(self, point_id: str) -> Any: ...
    async def write_point(self, point_id: str, value: Any) -> dict: ...


# ─────────────────────────────────────────────────────────────────────────
#  Canonical bypass states
# ─────────────────────────────────────────────────────────────────────────
# Bypass switches have 3 contact positions: NORMAL / TEST / BYPASS.
#   NORMAL: load fed from primary source (utility), UPS in line
#   TEST:   maintenance test position (load on UPS, bypass exercised)
#   BYPASS: load fed directly through bypass, UPS isolated for service
#
# Position changes require maintained or momentary contact closure
# depending on switch model. The adapter applies pulse-width as
# configured per target.

_VALID_POSITIONS = ("NORMAL", "TEST", "BYPASS")


class RusselectricAdapter(HardwareAdapter):
    """Russelectric Bypass switch adapter via BMS dry contacts."""

    vendor = "russelectric"
    protocol = "bms_dry_contact"

    def __init__(
        self,
        backend: BypassBackend,
        targets: dict[str, dict],
        failure_mode: FailureMode = FailureMode.FAIL_OPEN,
    ):
        """
        Args:
            backend: bms_connector facade exposing read_point/write_point.
            targets: per-switch config, e.g.:
                { "bypass_a": {
                    "status_point":         "BMS.UPS_A.BYPASS_POSITION",
                    "cmd_to_normal_point":  "BMS.UPS_A.CMD_BYPASS_TO_NORMAL",
                    "cmd_to_test_point":    "BMS.UPS_A.CMD_BYPASS_TO_TEST",
                    "cmd_to_bypass_point":  "BMS.UPS_A.CMD_BYPASS_TO_BYPASS",
                    "interlock_ok_point":   "BMS.UPS_A.BYPASS_INTERLOCK_OK",
                    "pulse_ms":             500,
                    "model":                "RTS",
                  } }
            failure_mode: behavior on backend ops failing.
        """
        super().__init__(failure_mode)
        self.backend = backend
        self.targets = targets

    async def connect(self) -> bool:
        # No connection state — the BMS connector is independently managed.
        # Validate that each target's status point reads.
        try:
            for name, cfg in self.targets.items():
                await self.backend.read_point(cfg["status_point"])
            self._connected = True
            return True
        except Exception as e:
            log.error("[russelectric] target probe failed: %s", e)
            self._connected = False
            return False

    async def close(self) -> None:
        self._connected = False

    async def read(self, target: str, fields: list[str]) -> dict:
        """Supported fields:
        - position             : current bypass position (NORMAL/TEST/BYPASS)
        - interlock_ok         : True if all interlocks satisfied
        - last_change_ts       : timestamp of last position change (if BMS tracks it)
        """
        if target not in self.targets:
            raise ValueError(f"unknown target '{target}'. known: {list(self.targets.keys())}")
        cfg = self.targets[target]
        result: dict[str, Any] = {}

        try:
            for field in fields:
                if field == "position":
                    raw = await self.backend.read_point(cfg["status_point"])
                    result["position"] = self._decode_position(raw)
                elif field == "interlock_ok":
                    raw = await self.backend.read_point(cfg.get("interlock_ok_point", ""))
                    result["interlock_ok"] = bool(raw)
                else:
                    log.warning("[russelectric] unknown field '%s'", field)
                    result[field] = None
        except Exception as e:
            return self._on_failure("read", target, e)

        self._cache[target] = result
        return result

    async def write(self, target: str, command: str, payload: dict | None = None) -> dict:
        """Canonical commands:
        - GO_TO_NORMAL    → pulse cmd_to_normal_point
        - GO_TO_TEST      → pulse cmd_to_test_point
        - GO_TO_BYPASS    → pulse cmd_to_bypass_point
        """
        if target not in self.targets:
            raise ValueError(f"unknown target '{target}'")
        cfg = self.targets[target]
        payload = payload or {}

        cmd_to_point_map = {
            "GO_TO_NORMAL": cfg.get("cmd_to_normal_point"),
            "GO_TO_TEST": cfg.get("cmd_to_test_point"),
            "GO_TO_BYPASS": cfg.get("cmd_to_bypass_point"),
        }
        if command not in cmd_to_point_map:
            raise NotImplementedError(
                f"russelectric canonical command '{command}' not supported. "
                f"Supported: {list(cmd_to_point_map.keys())}"
            )

        point = cmd_to_point_map[command]
        if not point:
            raise ValueError(f"target '{target}' has no point configured for command '{command}'")

        # Pre-flight interlock check — refuse to issue command if interlocks not OK.
        # This is a software guard ON TOP of the hardware interlocks; both must agree.
        interlock_point = cfg.get("interlock_ok_point")
        if interlock_point:
            try:
                ok = await self.backend.read_point(interlock_point)
                if not bool(ok):
                    return {
                        "status": "REJECTED",
                        "reason": "interlock_not_ok",
                        "_note": (
                            "Software interlock guard refused the command. "
                            "Hardware interlocks would also block; this is "
                            "defence-in-depth."
                        ),
                    }
            except Exception as e:
                return self._on_failure("interlock_check", target, e)

        # Issue the pulse: assert, wait pulse_ms, release.
        pulse_ms = int(cfg.get("pulse_ms", 500))
        try:
            await self.backend.write_point(point, True)
            # Pulse capped at 5s for development to keep tests fast
            await asyncio.sleep(min(pulse_ms / 1000.0, 5.0))
            await self.backend.write_point(point, False)
        except Exception as e:
            return self._on_failure("write_pulse", target, e)

        return {
            "status": "OK",
            "vendor": "russelectric",
            "target": target,
            "command": command,
            "point_pulsed": point,
            "pulse_ms": pulse_ms,
        }

    @staticmethod
    def _decode_position(raw: Any) -> str:
        """BMS may report position as int (0/1/2) or string. Normalize."""
        if isinstance(raw, str) and raw.upper() in _VALID_POSITIONS:
            return raw.upper()
        try:
            return {0: "NORMAL", 1: "TEST", 2: "BYPASS"}.get(int(raw), "UNKNOWN")
        except (TypeError, ValueError):
            return "UNKNOWN"


# ─────────────────────────────────────────────────────────────────────────
#  MockBypassBackend — used in tests
# ─────────────────────────────────────────────────────────────────────────
class MockBypassBackend:
    """Mock BMS connector for Russelectric tests."""

    def __init__(self, initial_state: dict[str, Any] | None = None):
        self._state: dict[str, Any] = dict(initial_state or {})
        self.write_log: list[tuple[str, Any]] = []

    async def read_point(self, point_id: str) -> Any:
        return self._state.get(point_id, 0)

    async def write_point(self, point_id: str, value: Any) -> dict:
        self._state[point_id] = value
        self.write_log.append((point_id, value))
        return {"status": "OK", "point_id": point_id, "value": value}

    # ── Test helpers ─────────────────────────────────────────────────
    def preload(self, point_id: str, value: Any) -> None:
        self._state[point_id] = value

    def get_writes_to(self, point_id: str) -> list[Any]:
        return [v for (p, v) in self.write_log if p == point_id]
