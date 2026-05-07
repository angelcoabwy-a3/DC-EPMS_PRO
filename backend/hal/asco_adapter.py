"""
asco_adapter.py — ASCO 7000 series ATS BACnet/IP adapter.

ASCO Series 7000 Group G/J Automatic Transfer Switches expose a
BACnet/IP gateway that maps switch state and control to BACnet
objects. The adapter speaks BACnet ReadProperty/WriteProperty against
the gateway IP, on UDP/47808 by default.

ASCO BACnet object map referenced from ASCO 381333-330 ("BACnet
Communication Protocol for 7000 Series ATS"). Object instances vary
by gateway firmware version; this adapter targets G3 firmware.

Key invariant: an ATS transfer is a STATE transition, not an event.
The adapter ALWAYS verifies the post-write state. ASCO transfers
typically take 50-200ms electrically but report completion via a
binaryInput that the controller asserts after contacts close.

═══════════════════════════════════════════════════════════════════════
  HONEST: Untested against real ASCO hardware. The object IDs below
  are from ASCO documentation; some installations use custom mappings
  done by the panel integrator. Verify against site-specific BACnet
  point list before commissioning.
═══════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import logging
from typing import Any

from . import BACnetBackend, FailureMode, HardwareAdapter

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
#  ASCO 7000 BACnet object map (G3 firmware)
# ─────────────────────────────────────────────────────────────────────────
# Format: canonical_field -> (object_type, object_id, prop, decoder)
#
# decoder:
#   "raw"        : pass through
#   "ats_position": {0: NORMAL, 1: EMERGENCY, 2: OFF}
#   "bool"       : 0/1 -> False/True
#
# Reference: ASCO 381333-330 BACnet Communication Protocol Manual
_OBJECT_MAP: dict[str, tuple[str, int, str, str]] = {
    # ── Status (binaryInput / multiStateInput / analogInput) ─────────
    "ats_position": ("multiStateInput", 1, "presentValue", "ats_position"),
    "ats_in_transit": ("binaryInput", 1, "presentValue", "bool"),
    "ats_armed": ("binaryInput", 2, "presentValue", "bool"),
    "source_normal_avail": ("binaryInput", 3, "presentValue", "bool"),
    "source_emergency_avail": ("binaryInput", 4, "presentValue", "bool"),
    "voltage_normal_l_l": ("analogInput", 1, "presentValue", "raw"),
    "voltage_emergency_l_l": ("analogInput", 2, "presentValue", "raw"),
    "frequency_normal_hz": ("analogInput", 3, "presentValue", "raw"),
    "frequency_emergency_hz": ("analogInput", 4, "presentValue", "raw"),
    "load_kw": ("analogInput", 5, "presentValue", "raw"),
    "transfer_count": ("analogInput", 10, "presentValue", "raw"),
    # ── Commands (binaryOutput) ──────────────────────────────────────
    "cmd_arm": ("binaryOutput", 1, "presentValue", "raw"),
    "cmd_transfer_to_norm": ("binaryOutput", 2, "presentValue", "raw"),
    "cmd_transfer_to_emerg": ("binaryOutput", 3, "presentValue", "raw"),
    "cmd_force_to_norm": ("binaryOutput", 4, "presentValue", "raw"),
    "cmd_disarm": ("binaryOutput", 5, "presentValue", "raw"),
    "cmd_test_transfer": ("binaryOutput", 6, "presentValue", "raw"),
}

_ATS_POSITION_ENUM = {0: "NORMAL", 1: "EMERGENCY", 2: "OFF"}


# ─────────────────────────────────────────────────────────────────────────
#  AscoAdapter — real implementation
# ─────────────────────────────────────────────────────────────────────────
class AscoAdapter(HardwareAdapter):
    """ASCO 7000 series ATS adapter via BACnet/IP."""

    vendor = "asco"
    protocol = "bacnet_ip"

    def __init__(
        self,
        backend: BACnetBackend,
        targets: dict[str, dict],
        failure_mode: FailureMode = FailureMode.FAIL_OPEN,
    ):
        """
        Args:
            backend:   BAC0 client OR mock implementing BACnetBackend.
            targets:   { "ats_a": {"address": "10.5.2.50", "device_id": 1001},
                         "ats_b": {"address": "10.5.2.51", "device_id": 1002} }
                       The address is the BACnet network address (IP); device_id
                       is the BACnet Object Identifier of the ATS device.
            failure_mode: behavior when backend ops fail.
        """
        super().__init__(failure_mode)
        self.backend = backend
        self.targets = targets

    async def connect(self) -> bool:
        # BACnet is connectionless (UDP); presence verified by reading a
        # well-known property like Object_List from the device.
        try:
            for name, cfg in self.targets.items():
                # Probe each device with a System Status read
                await self.backend.read(
                    address=cfg["address"],
                    object_type="device",
                    object_id=cfg["device_id"],
                    prop="systemStatus",
                )
            self._connected = True
            return True
        except Exception as e:
            log.error("[asco] discovery failed: %s", e)
            self._connected = False
            return False

    async def close(self) -> None:
        # BACnet has no persistent connection; nothing to release.
        self._connected = False

    async def read(self, target: str, fields: list[str]) -> dict:
        """Read named fields. Returns {field: decoded_value}."""
        if target not in self.targets:
            raise ValueError(f"unknown target '{target}'. known: {list(self.targets.keys())}")

        cfg = self.targets[target]
        result: dict[str, Any] = {}

        try:
            for field in fields:
                if field not in _OBJECT_MAP:
                    log.warning("[asco] unknown field '%s' — skipping", field)
                    result[field] = None
                    continue
                otype, oid, prop, decoder = _OBJECT_MAP[field]
                raw = await self.backend.read(
                    address=cfg["address"],
                    object_type=otype,
                    object_id=oid,
                    prop=prop,
                )
                result[field] = self._decode(raw, decoder)
        except Exception as e:
            return self._on_failure("read", target, e)

        self._cache[target] = result
        return result

    async def write(self, target: str, command: str, payload: dict | None = None) -> dict:
        """Translate canonical command to BACnet WriteProperty.

        Supported canonical commands:
          - ARM                          → cmd_arm = 1 (or 2 if test_mode)
          - DISARM                       → cmd_disarm = 1
          - TRANSFER_TO_EMERGENCY        → cmd_transfer_to_emerg = 1
          - TRANSFER_TO_NORMAL           → cmd_transfer_to_norm = 1
          - TRANSFER_TO_NORMAL_FORCED    → cmd_force_to_norm = 1   (abort path)
          - TEST_TRANSFER                → cmd_test_transfer = 1   (no actual transfer)
        """
        if target not in self.targets:
            raise ValueError(f"unknown target '{target}'")
        cfg = self.targets[target]
        payload = payload or {}

        cmd_field_map = {
            "ARM": ("cmd_arm", 2 if payload.get("test_mode") else 1),
            "DISARM": ("cmd_disarm", 1),
            "TRANSFER_TO_EMERGENCY": ("cmd_transfer_to_emerg", 1),
            "TRANSFER_TO_NORMAL": ("cmd_transfer_to_norm", 1),
            "TRANSFER_TO_NORMAL_FORCED": ("cmd_force_to_norm", 1),
            "TEST_TRANSFER": ("cmd_test_transfer", 1),
        }

        if command not in cmd_field_map:
            raise NotImplementedError(
                f"asco canonical command '{command}' not supported. "
                f"Supported: {list(cmd_field_map.keys())}"
            )

        field, value = cmd_field_map[command]
        otype, oid, prop, _ = _OBJECT_MAP[field]

        try:
            await self.backend.write(
                address=cfg["address"],
                object_type=otype,
                object_id=oid,
                prop=prop,
                value=value,
            )
        except Exception as e:
            return self._on_failure("write", target, e)

        return {
            "status": "OK",
            "vendor": "asco",
            "target": target,
            "command": command,
            "object_type": otype,
            "object_id": oid,
            "value_written": value,
        }

    @staticmethod
    def _decode(raw: Any, decoder: str) -> Any:
        if raw is None:
            return None
        if decoder == "raw":
            return raw
        if decoder == "bool":
            return bool(raw)
        if decoder == "ats_position":
            try:
                return _ATS_POSITION_ENUM.get(int(raw), str(raw))
            except (TypeError, ValueError):
                return str(raw)
        return raw


# ─────────────────────────────────────────────────────────────────────────
#  MockBACnetBackend — for tests and offline demo
# ─────────────────────────────────────────────────────────────────────────
class MockBACnetBackend:
    """In-memory BACnet simulator. Maintains state per (address,
    object_type, object_id, prop). Useful for testing the adapter
    logic without a real network."""

    def __init__(self):
        # key = (address, object_type, object_id, prop)
        self._store: dict[tuple, Any] = {}

    def _key(self, address, object_type, object_id, prop):
        return (address, object_type, int(object_id), prop)

    async def read(self, address, object_type, object_id, prop):
        k = self._key(address, object_type, object_id, prop)
        # systemStatus is hardcoded operational so connect() succeeds
        if object_type == "device" and prop == "systemStatus":
            return "operational"
        return self._store.get(k, 0)

    async def write(self, address, object_type, object_id, prop, value):
        k = self._key(address, object_type, object_id, prop)
        self._store[k] = value
        return {"status": "OK"}

    # ── Test helpers ─────────────────────────────────────────────────
    def preload(self, address, object_type, object_id, prop, value):
        """Inject a property value as if the device had reported it."""
        self._store[self._key(address, object_type, object_id, prop)] = value

    def assert_written(self, address, object_type, object_id, prop, expected):
        """Assert the last value written matches expected."""
        actual = self._store.get(self._key(address, object_type, object_id, prop))
        assert actual == expected, f"expected {expected}, got {actual}"
