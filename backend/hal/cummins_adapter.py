"""
cummins_adapter.py — Cummins PowerCommand 2100/3300 Modbus TCP adapter.

Cummins gensets expose a Modbus TCP gateway (or RS-485 with a TCP
bridge) at port 502. The PCC controller maintains a register map
documented in Cummins service manual S-1570 ("PowerCommand Modbus
Communication Reference").

We implement a SUBSET of registers — only what MOP-ATS-MONTHLY-001
actually reads/writes. Adding more registers is mechanical: extend
the _REGISTER_MAP dict.

═══════════════════════════════════════════════════════════════════════
  HONEST: Register addresses below are taken from PCC 2100/3300
  spec sheets I have memorised. Cummins releases firmware revisions
  that occasionally remap registers. Before deploying to a real
  facility, verify against the as-shipped Cummins documentation for
  THAT facility's controller firmware version. PCC 1.X, 2.X, 3.X
  have non-trivially different maps.
═══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from . import HardwareAdapter, FailureMode, ModbusBackend

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
#  Register map — Cummins PCC 2100/3300 (excerpted)
# ─────────────────────────────────────────────────────────────────────────
# Format: canonical_field_name -> (address, count, scale, type)
#
#   address: Modbus holding register address
#   count:   number of 16-bit registers (1=u16, 2=u32, etc.)
#   scale:   raw_value / scale = engineering_value
#   type:    "u16" | "u32" | "i16" | "enum"
#
# Reference: Cummins S-1570 Modbus Communication Reference,
# PCC 2100/3300 Series. NOT the older PCC1300 map.
_REGISTER_MAP: dict[str, tuple[int, int, float, str]] = {
    # ── Status / Mode ────────────────────────────────────────────────
    "mode":              (40001, 1, 1,    "enum"),  # 0=OFF 1=AUTO 2=MANUAL 3=TEST
    "running_state":     (40002, 1, 1,    "enum"),  # 0=stop 1=start 2=run 3=cooldown
    "fault_code":        (40003, 1, 1,    "u16"),

    # ── Electrical output ────────────────────────────────────────────
    "kw_output":         (40010, 2, 1,    "u32"),   # kW total
    "kvar_output":       (40012, 2, 1,    "u32"),   # kVAR
    "hertz":             (40014, 1, 100,  "u16"),   # 0.01 Hz resolution
    "voltage_l_l":       (40015, 1, 1,    "u16"),   # L-L average, V
    "voltage_l_n":       (40016, 1, 1,    "u16"),   # L-N average, V
    "current_avg":       (40017, 1, 1,    "u16"),   # A

    # ── Engine ───────────────────────────────────────────────────────
    "fuel_pct":          (40020, 1, 10,   "u16"),   # 0.1% resolution
    "coolant_temp_c":    (40021, 1, 10,   "i16"),   # 0.1 C resolution
    "oil_pressure_kpa":  (40022, 1, 1,    "u16"),
    "engine_speed_rpm":  (40023, 1, 1,    "u16"),
    "battery_voltage_v": (40024, 1, 100,  "u16"),   # 0.01 V resolution
    "run_hours":         (40025, 2, 10,   "u32"),   # 0.1 hour resolution

    # ── Commands (writable holding registers) ────────────────────────
    "cmd_start":         (40100, 1, 1,    "u16"),   # write 1 to start
    "cmd_stop":          (40101, 1, 1,    "u16"),   # write 1 to stop
    "cmd_mode_set":      (40102, 1, 1,    "u16"),   # write 0=OFF 1=AUTO 2=MAN 3=TEST
    "cmd_reset_fault":   (40103, 1, 1,    "u16"),   # write 1 to reset
}

# Mode enumeration for human-readable conversion
_MODE_ENUM = {0: "OFF", 1: "AUTO", 2: "MANUAL", 3: "TEST"}
_RUN_STATE_ENUM = {0: "STOPPED", 1: "STARTING", 2: "RUNNING", 3: "COOLDOWN"}


# ─────────────────────────────────────────────────────────────────────────
#  CumminsAdapter — real implementation
# ─────────────────────────────────────────────────────────────────────────
class CumminsAdapter(HardwareAdapter):
    """Cummins PowerCommand controller adapter via Modbus TCP."""

    vendor = "cummins"
    protocol = "modbus_tcp"

    def __init__(
        self,
        backend: ModbusBackend,
        targets: dict[str, dict],
        failure_mode: FailureMode = FailureMode.FAIL_OPEN,
    ):
        """
        Args:
            backend:   pymodbus AsyncModbusTcpClient OR a mock implementing
                       the ModbusBackend protocol.
            targets:   { "genset_a": {"slave_id": 1, "host": "10.5.1.10"},
                         "genset_b": {"slave_id": 2, "host": "10.5.1.11"}, ... }
                       slave_id is the Modbus unit address; host is informational
                       (the backend handles the TCP connection).
            failure_mode: how to behave when backend ops fail.
        """
        super().__init__(failure_mode)
        self.backend = backend
        self.targets = targets

    async def connect(self) -> bool:
        try:
            ok = await self.backend.connect()
            self._connected = ok
            return ok
        except Exception as e:
            log.error("[cummins] connect failed: %s", e)
            self._connected = False
            return False

    async def close(self) -> None:
        if self._connected:
            try:
                await self.backend.close()
            finally:
                self._connected = False

    async def read(self, target: str, fields: list[str]) -> dict:
        """Read named fields for a target genset. Returns {field: engineering_value}."""
        if target not in self.targets:
            raise ValueError(f"unknown target '{target}'. known: {list(self.targets.keys())}")

        slave = self.targets[target]["slave_id"]
        result: dict[str, Any] = {}

        try:
            for field in fields:
                if field not in _REGISTER_MAP:
                    log.warning("[cummins] unknown field '%s' — skipping", field)
                    result[field] = None
                    continue
                address, count, scale, dtype = _REGISTER_MAP[field]
                raw = await self.backend.read_holding_registers(
                    address=address - 40001,    # Modbus uses 0-based addressing internally
                    count=count,
                    slave=slave,
                )
                # pymodbus response carries .registers; mocks should mimic this.
                regs = raw.registers if hasattr(raw, "registers") else raw
                value = self._decode(regs, count, scale, dtype, address_hint=address - 40001)
                result[field] = value
        except Exception as e:
            return self._on_failure("read", target, e)

        # Cache for FAIL_SAFE recovery
        self._cache[target] = result
        return result

    async def write(
        self, target: str, command: str, payload: Optional[dict] = None
    ) -> dict:
        """Translate canonical command to Modbus write.

        Supported canonical commands:
          - START                 → write cmd_start = 1
          - STOP                  → write cmd_stop = 1
          - SET_MODE              → write cmd_mode_set = payload['mode_int']
                                    payload mode_int: 0=OFF 1=AUTO 2=MAN 3=TEST
          - RESET_FAULT           → write cmd_reset_fault = 1
        """
        if target not in self.targets:
            raise ValueError(f"unknown target '{target}'")
        slave = self.targets[target]["slave_id"]
        payload = payload or {}

        try:
            if command == "START":
                addr = _REGISTER_MAP["cmd_start"][0] - 40001
                await self.backend.write_register(address=addr, value=1, slave=slave)

            elif command == "STOP":
                addr = _REGISTER_MAP["cmd_stop"][0] - 40001
                await self.backend.write_register(address=addr, value=1, slave=slave)

            elif command == "SET_MODE":
                mode_int = int(payload.get("mode_int", 1))    # default AUTO
                if mode_int not in _MODE_ENUM:
                    raise ValueError(f"mode_int {mode_int} not in {_MODE_ENUM}")
                addr = _REGISTER_MAP["cmd_mode_set"][0] - 40001
                await self.backend.write_register(address=addr, value=mode_int, slave=slave)

            elif command == "RESET_FAULT":
                addr = _REGISTER_MAP["cmd_reset_fault"][0] - 40001
                await self.backend.write_register(address=addr, value=1, slave=slave)

            else:
                raise NotImplementedError(
                    f"cummins canonical command '{command}' not supported. "
                    f"Supported: START, STOP, SET_MODE, RESET_FAULT"
                )
        except Exception as e:
            return self._on_failure("write", target, e)

        return {
            "status": "OK",
            "vendor": "cummins",
            "target": target,
            "command": command,
            "payload": payload,
        }

    # ── Decoding helpers ─────────────────────────────────────────────
    @staticmethod
    def _decode(regs: list[int], count: int, scale: float, dtype: str, address_hint: int = -1) -> Any:
        if regs is None or len(regs) < count:
            return None

        if dtype == "u16":
            raw = regs[0] & 0xFFFF
        elif dtype == "i16":
            raw = regs[0] & 0xFFFF
            if raw >= 0x8000:
                raw -= 0x10000
        elif dtype == "u32":
            # Big-endian word order (Cummins default)
            raw = (regs[0] << 16) | regs[1]
        elif dtype == "enum":
            raw = regs[0]
            # Mode register specifically maps to string for verify_state compatibility
            # with vendor-agnostic procedure YAMLs. Other enum fields would need
            # similar mapping if they participate in verify_state checks.
            if address_hint == 0:    # mode register at 40001 (offset 0)
                return _MODE_ENUM.get(raw, str(raw))
            return raw
        else:
            raw = regs[0]

        if scale != 1:
            return raw / scale
        return raw


# ─────────────────────────────────────────────────────────────────────────
#  MockModbusBackend — used in tests and offline demo
# ─────────────────────────────────────────────────────────────────────────
class _ModbusReadResponse:
    """Mimics pymodbus response object."""
    def __init__(self, registers: list[int]):
        self.registers = registers


class MockModbusBackend:
    """In-memory Modbus simulator. Used by tests and the offline demo
    mode. Never touches a network. Stores register state internally so
    write-then-read round trips work."""

    def __init__(self, initial_state: Optional[dict[int, dict[int, int]]] = None):
        # Structure: {slave_id: {address: value_u16}}
        # All registers default to 0 if not initialized.
        self._state: dict[int, dict[int, int]] = initial_state or {}
        self._connected = False

    async def connect(self) -> bool:
        self._connected = True
        return True

    async def close(self) -> None:
        self._connected = False

    async def read_holding_registers(self, address: int, count: int, slave: int):
        regs = []
        slave_state = self._state.setdefault(slave, {})
        for i in range(count):
            regs.append(slave_state.get(address + i, 0))
        return _ModbusReadResponse(regs)

    async def read_coils(self, address: int, count: int, slave: int):
        regs = []
        slave_state = self._state.setdefault(slave, {})
        for i in range(count):
            regs.append(bool(slave_state.get(address + i, 0)))
        return _ModbusReadResponse(regs)

    async def write_register(self, address: int, value: int, slave: int):
        self._state.setdefault(slave, {})[address] = value & 0xFFFF
        return _ModbusReadResponse([value])

    async def write_coil(self, address: int, value: bool, slave: int):
        self._state.setdefault(slave, {})[address] = 1 if value else 0
        return _ModbusReadResponse([1 if value else 0])

    # ── Test helpers (not part of Modbus protocol) ───────────────────
    def preload(self, slave: int, address: int, value: int) -> None:
        """Inject a register value as if the PLC had set it."""
        self._state.setdefault(slave, {})[address] = value & 0xFFFF
