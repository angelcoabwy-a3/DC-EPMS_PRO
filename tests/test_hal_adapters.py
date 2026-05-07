"""
Tests for HAL adapters — Sprint 2 of Opción B.

Covers Cummins (Modbus), ASCO (BACnet), Russelectric (BMS dry-contact).
Every test uses mock backends — no real hardware, no network.

Run:
    pytest tests/test_hal_adapters.py -v
"""
import sys
import pathlib
import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from hal import (
    FailureMode,
    CumminsAdapter, MockModbusBackend,
    AscoAdapter, MockBACnetBackend,
    RusselectricAdapter, MockBypassBackend,
)


# ═══════════════════════════════════════════════════════════════════════
#  Cummins
# ═══════════════════════════════════════════════════════════════════════
class TestCumminsAdapter:

    @pytest.fixture
    def adapter(self):
        backend = MockModbusBackend()
        # Pre-load realistic genset state into mock registers
        # Mode register at 40001 (offset 0): 1 = AUTO
        backend.preload(slave=1, address=0, value=1)
        # Running state at 40002 (offset 1): 2 = RUNNING
        backend.preload(slave=1, address=1, value=2)
        # kw_output u32 at 40010-40011 (offsets 9-10): 1500 kW
        backend.preload(slave=1, address=9, value=0)
        backend.preload(slave=1, address=10, value=1500)
        # Hertz at 40014 (offset 13): 6005 / 100 = 60.05 Hz
        backend.preload(slave=1, address=13, value=6005)
        # Voltage L-L at 40015 (offset 14): 480 V
        backend.preload(slave=1, address=14, value=480)
        # Fuel pct at 40020 (offset 19): 850 / 10 = 85.0 %
        backend.preload(slave=1, address=19, value=850)
        # Coolant temp i16 at 40021 (offset 20): 750 / 10 = 75.0 C
        backend.preload(slave=1, address=20, value=750)
        # Battery V at 40024 (offset 23): 2440 / 100 = 24.4 V
        backend.preload(slave=1, address=23, value=2440)

        return CumminsAdapter(
            backend=backend,
            targets={"genset_a": {"slave_id": 1, "host": "10.5.1.10"}},
        )

    @pytest.mark.asyncio
    async def test_connect_succeeds(self, adapter):
        ok = await adapter.connect()
        assert ok is True

    @pytest.mark.asyncio
    async def test_read_mode_returns_auto_string(self, adapter):
        """Mode field decodes enum int → human-readable string for
        vendor-agnostic procedure YAMLs."""
        await adapter.connect()
        result = await adapter.read("genset_a", ["mode"])
        assert result["mode"] == "AUTO"

    @pytest.mark.asyncio
    async def test_read_kw_output_decodes_u32(self, adapter):
        await adapter.connect()
        result = await adapter.read("genset_a", ["kw_output"])
        assert result["kw_output"] == 1500

    @pytest.mark.asyncio
    async def test_read_hertz_applies_scale_100(self, adapter):
        await adapter.connect()
        result = await adapter.read("genset_a", ["hertz"])
        assert result["hertz"] == pytest.approx(60.05, rel=0.001)

    @pytest.mark.asyncio
    async def test_read_fuel_pct_applies_scale_10(self, adapter):
        await adapter.connect()
        result = await adapter.read("genset_a", ["fuel_pct"])
        assert result["fuel_pct"] == pytest.approx(85.0, rel=0.001)

    @pytest.mark.asyncio
    async def test_read_battery_voltage_applies_scale_100(self, adapter):
        await adapter.connect()
        result = await adapter.read("genset_a", ["battery_voltage_v"])
        assert result["battery_voltage_v"] == pytest.approx(24.4, rel=0.001)

    @pytest.mark.asyncio
    async def test_read_unknown_field_returns_none(self, adapter):
        await adapter.connect()
        result = await adapter.read("genset_a", ["nonexistent_field"])
        assert result["nonexistent_field"] is None

    @pytest.mark.asyncio
    async def test_read_multiple_fields_at_once(self, adapter):
        await adapter.connect()
        result = await adapter.read(
            "genset_a", ["mode", "kw_output", "fuel_pct", "battery_voltage_v"]
        )
        assert result["mode"] == "AUTO"
        assert result["kw_output"] == 1500
        assert result["fuel_pct"] == pytest.approx(85.0)
        assert result["battery_voltage_v"] == pytest.approx(24.4)

    @pytest.mark.asyncio
    async def test_read_unknown_target_raises(self, adapter):
        with pytest.raises(ValueError, match="unknown target"):
            await adapter.read("nonexistent_genset", ["mode"])

    @pytest.mark.asyncio
    async def test_write_start_command(self, adapter):
        await adapter.connect()
        result = await adapter.write("genset_a", "START")
        assert result["status"] == "OK"
        assert result["command"] == "START"
        # Verify mock backend captured the write at correct address
        # cmd_start register is at 40100 (offset 99)
        assert adapter.backend._state[1].get(99) == 1

    @pytest.mark.asyncio
    async def test_write_set_mode_to_test(self, adapter):
        await adapter.connect()
        result = await adapter.write("genset_a", "SET_MODE", {"mode_int": 3})
        assert result["status"] == "OK"
        # cmd_mode_set at 40102 (offset 101)
        assert adapter.backend._state[1].get(101) == 3

    @pytest.mark.asyncio
    async def test_write_invalid_mode_int_raises(self, adapter):
        await adapter.connect()
        with pytest.raises(ValueError, match="mode_int"):
            await adapter.write("genset_a", "SET_MODE", {"mode_int": 99})

    @pytest.mark.asyncio
    async def test_write_unsupported_command_raises(self, adapter):
        await adapter.connect()
        with pytest.raises(NotImplementedError, match="not supported"):
            await adapter.write("genset_a", "DO_THE_HOKEY_POKEY")

    @pytest.mark.asyncio
    async def test_verify_state_with_min_max_ranges(self, adapter):
        await adapter.connect()
        ok, observed = await adapter.verify_state(
            "genset_a", {
                "kw_output": {"min": 1000},          # 1500 >= 1000 OK
                "hertz":     {"min": 59.5, "max": 60.5},  # 60.05 in range OK
                "fuel_pct":  {"min": 80},            # 85 >= 80 OK
            },
        )
        assert ok is True
        assert observed["kw_output"] == 1500

    @pytest.mark.asyncio
    async def test_verify_state_fails_when_out_of_range(self, adapter):
        await adapter.connect()
        ok, observed = await adapter.verify_state(
            "genset_a", {
                "kw_output": {"min": 5000},          # 1500 < 5000 FAIL
            },
        )
        assert ok is False

    @pytest.mark.asyncio
    async def test_verify_state_empty_expected_returns_ok(self, adapter):
        ok, _ = await adapter.verify_state("genset_a", {})
        assert ok is True


# ═══════════════════════════════════════════════════════════════════════
#  ASCO
# ═══════════════════════════════════════════════════════════════════════
class TestAscoAdapter:

    @pytest.fixture
    def adapter(self):
        backend = MockBACnetBackend()
        # Preload state for ats_a — switch is in NORMAL, not in transit, not armed
        backend.preload("10.5.2.50", "multiStateInput", 1, "presentValue", 0)  # ats_position = 0 (NORMAL)
        backend.preload("10.5.2.50", "binaryInput",     1, "presentValue", 0)  # ats_in_transit = 0 (False)
        backend.preload("10.5.2.50", "binaryInput",     2, "presentValue", 0)  # ats_armed = 0 (False)
        backend.preload("10.5.2.50", "binaryInput",     3, "presentValue", 1)  # source_normal_avail = True
        backend.preload("10.5.2.50", "binaryInput",     4, "presentValue", 1)  # source_emergency_avail = True
        backend.preload("10.5.2.50", "analogInput",     1, "presentValue", 480)  # voltage_normal_l_l
        backend.preload("10.5.2.50", "analogInput",     5, "presentValue", 1500)  # load_kw

        return AscoAdapter(
            backend=backend,
            targets={"ats_a": {"address": "10.5.2.50", "device_id": 1001}},
        )

    @pytest.mark.asyncio
    async def test_connect_succeeds(self, adapter):
        ok = await adapter.connect()
        assert ok is True

    @pytest.mark.asyncio
    async def test_read_ats_position_decodes_to_normal(self, adapter):
        await adapter.connect()
        result = await adapter.read("ats_a", ["ats_position"])
        assert result["ats_position"] == "NORMAL"

    @pytest.mark.asyncio
    async def test_read_ats_in_transit_decodes_to_bool(self, adapter):
        await adapter.connect()
        result = await adapter.read("ats_a", ["ats_in_transit"])
        assert result["ats_in_transit"] is False

    @pytest.mark.asyncio
    async def test_read_load_kw_returns_raw(self, adapter):
        await adapter.connect()
        result = await adapter.read("ats_a", ["load_kw"])
        assert result["load_kw"] == 1500

    @pytest.mark.asyncio
    async def test_read_unknown_target_raises(self, adapter):
        with pytest.raises(ValueError):
            await adapter.read("nonexistent_ats", ["ats_position"])

    @pytest.mark.asyncio
    async def test_write_arm_test_mode(self, adapter):
        await adapter.connect()
        result = await adapter.write("ats_a", "ARM", {"test_mode": True})
        assert result["status"] == "OK"
        # ARM in test mode writes value=2 to binaryOutput cmd_arm
        adapter.backend.assert_written("10.5.2.50", "binaryOutput", 1, "presentValue", 2)

    @pytest.mark.asyncio
    async def test_write_arm_normal_mode(self, adapter):
        await adapter.connect()
        result = await adapter.write("ats_a", "ARM")
        assert result["status"] == "OK"
        # ARM normal mode writes value=1
        adapter.backend.assert_written("10.5.2.50", "binaryOutput", 1, "presentValue", 1)

    @pytest.mark.asyncio
    async def test_write_transfer_to_emergency(self, adapter):
        await adapter.connect()
        result = await adapter.write("ats_a", "TRANSFER_TO_EMERGENCY")
        assert result["status"] == "OK"
        adapter.backend.assert_written("10.5.2.50", "binaryOutput", 3, "presentValue", 1)

    @pytest.mark.asyncio
    async def test_write_force_to_normal(self, adapter):
        """The abort_sequence command — emergency retransfer."""
        await adapter.connect()
        result = await adapter.write("ats_a", "TRANSFER_TO_NORMAL_FORCED")
        assert result["status"] == "OK"
        adapter.backend.assert_written("10.5.2.50", "binaryOutput", 4, "presentValue", 1)

    @pytest.mark.asyncio
    async def test_write_unsupported_command_raises(self, adapter):
        await adapter.connect()
        with pytest.raises(NotImplementedError):
            await adapter.write("ats_a", "DO_BACKFLIP")

    @pytest.mark.asyncio
    async def test_verify_state_after_simulated_transfer(self, adapter):
        """Simulate a successful transfer: write TRANSFER_TO_EMERGENCY, then
        manually update mock state as the real PLC would after contacts close,
        then verify_state should reflect the new position."""
        await adapter.connect()
        await adapter.write("ats_a", "TRANSFER_TO_EMERGENCY")
        # Simulate PLC asserting new state after transfer
        adapter.backend.preload("10.5.2.50", "multiStateInput", 1, "presentValue", 1)  # EMERGENCY
        adapter.backend.preload("10.5.2.50", "binaryInput", 1, "presentValue", 0)      # not in transit

        ok, observed = await adapter.verify_state(
            "ats_a", {"ats_position": "EMERGENCY", "ats_in_transit": False},
        )
        assert ok is True
        assert observed["ats_position"] == "EMERGENCY"


# ═══════════════════════════════════════════════════════════════════════
#  Russelectric
# ═══════════════════════════════════════════════════════════════════════
class TestRusselectricAdapter:

    @pytest.fixture
    def adapter(self):
        backend = MockBypassBackend()
        # Preload bypass_a in NORMAL position with interlocks OK
        backend.preload("BMS.UPS_A.BYPASS_POSITION", 0)        # NORMAL
        backend.preload("BMS.UPS_A.BYPASS_INTERLOCK_OK", 1)    # interlocks OK

        return RusselectricAdapter(
            backend=backend,
            targets={
                "bypass_a": {
                    "status_point":         "BMS.UPS_A.BYPASS_POSITION",
                    "cmd_to_normal_point":  "BMS.UPS_A.CMD_TO_NORMAL",
                    "cmd_to_test_point":    "BMS.UPS_A.CMD_TO_TEST",
                    "cmd_to_bypass_point":  "BMS.UPS_A.CMD_TO_BYPASS",
                    "interlock_ok_point":   "BMS.UPS_A.BYPASS_INTERLOCK_OK",
                    "pulse_ms":             100,    # short pulse for test speed
                    "model":                "RTS",
                },
            },
        )

    @pytest.mark.asyncio
    async def test_connect_succeeds(self, adapter):
        ok = await adapter.connect()
        assert ok is True

    @pytest.mark.asyncio
    async def test_read_position_decodes_normal(self, adapter):
        await adapter.connect()
        result = await adapter.read("bypass_a", ["position"])
        assert result["position"] == "NORMAL"

    @pytest.mark.asyncio
    async def test_read_interlock_ok_returns_bool(self, adapter):
        await adapter.connect()
        result = await adapter.read("bypass_a", ["interlock_ok"])
        assert result["interlock_ok"] is True

    @pytest.mark.asyncio
    async def test_write_go_to_test_pulses_the_correct_point(self, adapter):
        await adapter.connect()
        result = await adapter.write("bypass_a", "GO_TO_TEST")
        assert result["status"] == "OK"
        assert result["point_pulsed"] == "BMS.UPS_A.CMD_TO_TEST"

        # Verify the pulse: True then False
        writes = adapter.backend.get_writes_to("BMS.UPS_A.CMD_TO_TEST")
        assert writes == [True, False]

    @pytest.mark.asyncio
    async def test_write_go_to_bypass_pulses_correct_point(self, adapter):
        await adapter.connect()
        await adapter.write("bypass_a", "GO_TO_BYPASS")
        writes = adapter.backend.get_writes_to("BMS.UPS_A.CMD_TO_BYPASS")
        assert writes == [True, False]

    @pytest.mark.asyncio
    async def test_write_rejects_when_interlock_not_ok(self, adapter):
        """Software interlock guard: refuse if BMS reports interlock failure."""
        await adapter.connect()
        adapter.backend.preload("BMS.UPS_A.BYPASS_INTERLOCK_OK", 0)    # interlocks NOT ok

        result = await adapter.write("bypass_a", "GO_TO_BYPASS")
        assert result["status"] == "REJECTED"
        assert "interlock" in result["reason"]

        # Verify NO command was actually pulsed
        writes = adapter.backend.get_writes_to("BMS.UPS_A.CMD_TO_BYPASS")
        assert writes == []

    @pytest.mark.asyncio
    async def test_write_unsupported_command_raises(self, adapter):
        await adapter.connect()
        with pytest.raises(NotImplementedError):
            await adapter.write("bypass_a", "DO_THE_FANDANGO")

    @pytest.mark.asyncio
    async def test_position_decoder_handles_string_input(self, adapter):
        """Some BMSes return position as string."""
        await adapter.connect()
        adapter.backend.preload("BMS.UPS_A.BYPASS_POSITION", "BYPASS")
        result = await adapter.read("bypass_a", ["position"])
        assert result["position"] == "BYPASS"

    @pytest.mark.asyncio
    async def test_position_decoder_handles_unknown_value(self, adapter):
        """Garbage input returns UNKNOWN, not crash."""
        await adapter.connect()
        adapter.backend.preload("BMS.UPS_A.BYPASS_POSITION", "garbage_data")
        result = await adapter.read("bypass_a", ["position"])
        assert result["position"] == "UNKNOWN"


# ═══════════════════════════════════════════════════════════════════════
#  Failure mode policy
# ═══════════════════════════════════════════════════════════════════════
class TestFailureModes:

    @pytest.mark.asyncio
    async def test_fail_open_reraises_backend_error(self):
        class BrokenBackend(MockModbusBackend):
            async def read_holding_registers(self, address, count, slave):
                raise ConnectionError("network unreachable")

        adapter = CumminsAdapter(
            backend=BrokenBackend(),
            targets={"genset_a": {"slave_id": 1}},
            failure_mode=FailureMode.FAIL_OPEN,
        )
        await adapter.connect()
        with pytest.raises(ConnectionError):
            await adapter.read("genset_a", ["mode"])

    @pytest.mark.asyncio
    async def test_fail_silent_returns_synthetic(self):
        class BrokenBackend(MockModbusBackend):
            async def read_holding_registers(self, address, count, slave):
                raise ConnectionError("network unreachable")

        adapter = CumminsAdapter(
            backend=BrokenBackend(),
            targets={"genset_a": {"slave_id": 1}},
            failure_mode=FailureMode.FAIL_SILENT,
        )
        await adapter.connect()
        result = await adapter.read("genset_a", ["mode"])
        assert result.get("_synthetic") is True
        assert "_error" in result

    @pytest.mark.asyncio
    async def test_fail_safe_returns_cache_after_first_failure(self):
        # Build a backend where reads succeed once then fail.
        # connect() doesn't read holding registers (just returns True),
        # so the fail counter starts after construction.
        class FlakyBackend(MockModbusBackend):
            def __init__(self):
                super().__init__()
                self.fail_after = 1
                self.read_count = 0

            async def read_holding_registers(self, address, count, slave):
                self.read_count += 1
                if self.read_count > self.fail_after:
                    raise ConnectionError("flaky network")
                return await super().read_holding_registers(address, count, slave)

        backend = FlakyBackend()
        backend.preload(slave=1, address=0, value=1)    # mode = AUTO

        adapter = CumminsAdapter(
            backend=backend,
            targets={"genset_a": {"slave_id": 1}},
            failure_mode=FailureMode.FAIL_SAFE,
        )
        await adapter.connect()

        # First read succeeds and populates cache
        result_1 = await adapter.read("genset_a", ["mode"])
        assert result_1["mode"] == "AUTO"

        # Second read fails — fail_safe returns cached value with _stale flag
        result_2 = await adapter.read("genset_a", ["mode"])
        assert result_2.get("_stale") is True
        assert result_2["mode"] == "AUTO"   # cached value preserved
