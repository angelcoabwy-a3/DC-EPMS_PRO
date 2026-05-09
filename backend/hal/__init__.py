"""
hal/__init__.py — Universal Hardware Abstraction Layer.

The HAL gives procedure_engine.py a single, vendor-agnostic interface
to talk to facility equipment. Each vendor (Cummins, ASCO, Russelectric)
has its own concrete adapter that translates canonical commands into
vendor-specific protocol writes.

The pattern:

    +-----------------------+
    |   procedure_engine    |
    |   (calls adapter.write|
    |    with canonical     |
    |    command names)     |
    +----------+------------+
               |
               | "TRANSFER_TO_EMERGENCY"
               v
    +-----------------------+    +---------------+
    |   AdapterRegistry     +--->| AscoAdapter   |
    |   (lookup by name)    |    +---------------+
    +-----------------------+         |
                                      | BACnet WriteProperty
                                      | binaryOutput, instance=4, value=1
                                      v
                              +-----------------+
                              | ASCO 7000 PLC   |
                              | (real hardware) |
                              +-----------------+

Why this matters: a procedure YAML written for Cummins genset_a is
identical to one for Caterpillar genset_b once you swap the adapter.
The vendor lock-in is contained inside one Python file per vendor.

This is the Universal HAL described in the v7.1 whitepaper, made real.

═══════════════════════════════════════════════════════════════════════
  HONEST SCOPE NOTES — read before deploying to a real facility
═══════════════════════════════════════════════════════════════════════

  - Each adapter has been designed against vendor spec sheets I know:
      Cummins PCC 2100/3300 Modbus map, ASCO 7000 BACnet object list,
      Russelectric Bypass dry contact wiring.
    But none of them have been tested against actual hardware in this
    development environment. Validation against real units is part of
    commissioning, not part of code delivery.

  - The pymodbus / BAC0 / pyserial dependencies are imported only when
    the real backend is constructed. Mock backends are zero-dependency
    so tests run on any Python install.

  - Connection failures fall through to a CONFIGURED behavior:
      'fail_safe': writes raise, reads return last cached value
      'fail_open': writes raise, reads raise
      'fail_silent': writes return SIMULATED_OK, reads return synthetic
    Default is 'fail_open' because a Tier IV procedure that silently
    succeeds on a dead network is worse than one that explicitly fails.
═══════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Optional, Protocol

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
#  Failure mode policy
# ─────────────────────────────────────────────────────────────────────────
class FailureMode(str, Enum):
    """How an adapter should behave when its backend is unavailable."""

    FAIL_OPEN = "fail_open"  # raise — operator must respond
    FAIL_SAFE = "fail_safe"  # writes raise, reads return cache
    FAIL_SILENT = "fail_silent"  # only for testing / offline demo


# ─────────────────────────────────────────────────────────────────────────
#  Backend contracts (what real adapters and mocks must satisfy)
# ─────────────────────────────────────────────────────────────────────────
class ModbusBackend(Protocol):
    """Subset of pymodbus.AsyncModbusTcpClient that we actually use.
    A mock satisfies this protocol with the same method signatures."""

    async def connect(self) -> bool: ...
    async def close(self) -> None: ...
    async def read_holding_registers(self, address: int, count: int, slave: int) -> Any: ...
    async def read_coils(self, address: int, count: int, slave: int) -> Any: ...
    async def write_register(self, address: int, value: int, slave: int) -> Any: ...
    async def write_coil(self, address: int, value: bool, slave: int) -> Any: ...


class BACnetBackend(Protocol):
    """Subset of BAC0 client we use. Mock implements same interface."""

    async def read(self, address: str, object_type: str, object_id: int, prop: str) -> Any: ...
    async def write(
        self, address: str, object_type: str, object_id: int, prop: str, value: Any
    ) -> Any: ...


# ─────────────────────────────────────────────────────────────────────────
#  Common adapter base class
# ─────────────────────────────────────────────────────────────────────────
class HardwareAdapter:
    """Concrete adapters inherit from this. Provides the procedure_engine
    interface (read, write, verify_state) while concrete subclasses
    handle the protocol translation."""

    vendor: str = "abstract"
    protocol: str = "abstract"

    def __init__(self, failure_mode: FailureMode = FailureMode.FAIL_OPEN):
        self.failure_mode = failure_mode
        self._cache: dict[str, dict] = {}
        self._connected: bool = False

    # ── Public interface (called by procedure_engine.StepExecutor) ────
    async def read(self, target: str, fields: list[str]) -> dict:
        raise NotImplementedError

    async def write(self, target: str, command: str, payload: dict | None = None) -> dict:
        raise NotImplementedError

    async def verify_state(self, target: str, expected: dict) -> tuple[bool, dict]:
        """Generic verify: read all expected fields, compare with tolerances.

        Tolerances support 3 forms:
            "field_name": <exact_value>                     equality
            "field_name": {"min": X}                        observed >= X
            "field_name": {"max": Y}                        observed <= Y
            "field_name": {"min": X, "max": Y}              X <= observed <= Y
        """
        if not expected:
            return True, {}

        try:
            observed = await self.read(target, list(expected.keys()))
        except Exception as e:
            return False, {"_error": f"{type(e).__name__}: {e}"}

        all_match = True
        for field, want in expected.items():
            got = observed.get(field)
            if isinstance(want, dict):
                lo = want.get("min")
                hi = want.get("max")
                if lo is not None and (got is None or got < lo):
                    all_match = False
                if hi is not None and (got is None or got > hi):
                    all_match = False
            else:
                if got != want:
                    all_match = False

        return all_match, observed

    # ── Helpers used by subclasses ────────────────────────────────────
    def _on_failure(self, op: str, target: str, error: Exception) -> dict:
        """Apply failure_mode policy when a backend op fails."""
        msg = f"{self.vendor}.{op}({target}): {type(error).__name__}: {error}"
        log.error("[hal] %s", msg)

        if self.failure_mode == FailureMode.FAIL_OPEN:
            raise error  # let caller deal with it

        if self.failure_mode == FailureMode.FAIL_SAFE:
            cached = self._cache.get(target)
            if cached and op == "read":
                log.warning("[hal] returning stale cache for %s", target)
                return {**cached, "_stale": True, "_error": msg}
            raise error

        if self.failure_mode == FailureMode.FAIL_SILENT:
            log.warning("[hal] FAIL_SILENT: returning synthetic for %s", target)
            return {"_synthetic": True, "_op": op, "_error": msg}

        raise error  # unknown failure_mode


# ─────────────────────────────────────────────────────────────────────────
#  Re-export concrete adapters
# ─────────────────────────────────────────────────────────────────────────
from .asco_adapter import AscoAdapter, MockBACnetBackend
from .cummins_adapter import CumminsAdapter, MockModbusBackend
from .russelectric_adapter import MockBypassBackend, RusselectricAdapter

__all__ = [
    "AscoAdapter",
    "BACnetBackend",
    "CumminsAdapter",
    "FailureMode",
    "HardwareAdapter",
    "MockBACnetBackend",
    "MockBypassBackend",
    "MockModbusBackend",
    "ModbusBackend",
    "RusselectricAdapter",
]
