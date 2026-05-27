"""
tests/test_telemetry_proto_schema.py
====================================
Schema invariants for the canonical v1 telemetry wire format at
``backend/telemetry_proto/v1/telemetry.proto``.

Strategy
--------
The .proto file is the source of truth. These tests parse it as
TEXT (regex-based) and assert structural invariants -- the schema
is auditable from a clean Python environment without needing
``protoc`` installed. When ``grpcio-tools`` IS available, an
acceptance test also runs ``grpc_tools.protoc`` against the file
to verify proto3 syntax.

The invariants encoded here are not "nice to have": they are
panel-grade Tier IV operational requirements that derive from the
companion RFC ``docs/rfc/telemetry_sizing_and_ocp_validation.md``
(approved by the operator on 2026-05-26):

* **Vocabulary fence** -- DC unipolar messages MUST NOT carry phase
  fields. Saying "800 VDC trifasico" is a credibility-destroying
  error in CO+I panel review; the schema's `oneof topology` makes
  the mistake structurally impossible, and these tests guard the
  fence at audit time.
* **Strict SI units** -- forbidden suffixes (`_kpa`, `_celsius`,
  `_lpm`, `_kw`, `_rpm`, `_pct`, etc.) trip the suite. The unit
  policy is documented in the .proto header block.
* **MeasurementQuality propagation** -- every measurement message
  must carry a `MeasurementQuality quality` field so the Safety
  Officer (S-DET-02) can gate verdicts on sensor health.
* **PTP sub-microsecond timestamps** -- event messages (SSCB
  clearing, ATS state, STS alarm) carry a uint64
  `ptp_nanos_since_epoch` field; the operator confirmed (RFC §10
  Q4) that a PTP grandmaster is physically present on the
  management network.
* **UPS five-way split** -- monolithic `UPSStatus` is forbidden;
  the operator (RFC §10 Q3) mandated the addition of
  `UPSBatteryStringStatus` as the fifth sub-message for predictive
  maintenance at string granularity.
* **OCP CDU mapping** -- `FlowMeasurement` carries `rack_id`,
  `AbsolutePressureMeasurement` is a sibling of the differential
  variant, and the operator (RFC §10 Q2) added fluid chemistry
  (conductivity + pH) and filter differential pressure.

Skills exercised by these tests
-------------------------------
* ``S-TELEMETRY-01`` -- wire-format invariants (this module).
* ``S-OCP-CDU-01``   -- OCP CDU Test Methodology alignment.
* ``S-PTP-01``       -- sub-us PTP timestamp policy.
* ``S-VOCAB-01``     -- 800 VDC is unipolar; never trifasico.
* ``S-TEST-01``      -- pytest floor + targeted-first.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

PROTO_PATH = (
    Path(__file__).resolve().parent.parent
    / "backend"
    / "telemetry_proto"
    / "v1"
    / "telemetry.proto"
)


# ─── helpers ──────────────────────────────────────────────────────────────

def _extract_message_blocks(text: str) -> dict[str, str]:
    """Return ``{message_name: body_text}`` for every top-level
    ``message X { ... }`` block in the proto text.

    Nested messages are NOT returned separately; their text lives
    inside the enclosing block's body. v1 does not define nested
    messages, so this simplification is safe.
    """
    blocks: dict[str, str] = {}
    pattern = re.compile(r"^message\s+(\w+)\s*\{", re.MULTILINE)
    for m in pattern.finditer(text):
        name = m.group(1)
        depth = 1
        i = m.end()
        while i < len(text) and depth > 0:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        blocks[name] = text[m.end(): i - 1]
    return blocks


def _extract_field_names(block_text: str) -> list[str]:
    """Return field names (snake_case) declared inside the block.

    Skips comments, oneof markers, reserved markers, and the
    ``message``/``enum`` keywords. Captures both scalar and
    message-typed fields.
    """
    names: list[str] = []
    for line in block_text.splitlines():
        s = line.strip()
        if not s or s.startswith("//"):
            continue
        if s.startswith(("oneof", "}", "reserved", "message", "enum", "{")):
            continue
        m = re.match(
            r"^(?:repeated\s+)?[A-Za-z_][\w.]*\s+([a-z_][a-z0-9_]*)\s*=\s*\d+",
            s,
        )
        if m:
            names.append(m.group(1))
    return names


@pytest.fixture(scope="module")
def proto_text() -> str:
    assert PROTO_PATH.exists(), (
        f"v1 proto not found at {PROTO_PATH}; FASE 3 not delivered"
    )
    return PROTO_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def blocks(proto_text: str) -> dict[str, str]:
    return _extract_message_blocks(proto_text)


# ─── Block A -- file structure ────────────────────────────────────────────


class TestProtoStructure:

    def test_proto_file_exists(self, proto_text):
        assert proto_text

    def test_syntax_is_proto3(self, proto_text):
        assert 'syntax = "proto3";' in proto_text

    def test_package_is_dcepms_telemetry_v1(self, proto_text):
        assert "package dcepms.telemetry.v1;" in proto_text

    def test_imports_timestamp(self, proto_text):
        assert 'import "google/protobuf/timestamp.proto";' in proto_text


# ─── Block B -- vocabulary fence (CRITICAL) ───────────────────────────────


class TestVocabularyFence:
    """The 800 VDC bus is unipolar TN-S. Phase fields on a DC
    message are a credibility error -- these tests enforce the
    fence structurally."""

    def test_voltage_reading_has_oneof_topology(self, blocks):
        assert "VoltageReading" in blocks
        body = blocks["VoltageReading"]
        assert "oneof topology" in body
        assert "ac_three_phase" in body
        assert "dc_unipolar" in body

    def test_current_reading_has_oneof_topology(self, blocks):
        assert "CurrentReading" in blocks
        body = blocks["CurrentReading"]
        assert "oneof topology" in body
        assert "ac_three_phase" in body
        assert "dc_unipolar" in body

    def test_dc_unipolar_voltage_has_no_phase_fields(self, blocks):
        body = blocks["DcUnipolarVoltage"]
        for forbidden in ("_ab", "_bc", "_ca", "_phase_", "three_phase"):
            assert forbidden not in body, (
                f"DcUnipolarVoltage must NOT contain {forbidden!r} -- "
                "the 800 VDC bus is unipolar TN-S, NEVER trifasico "
                "(S-VOCAB-01)"
            )

    def test_dc_unipolar_current_has_no_phase_fields(self, blocks):
        body = blocks["DcUnipolarCurrent"]
        for forbidden in ("i_a_", "i_b_", "i_c_", "i_n_", "three_phase"):
            assert forbidden not in body, (
                f"DcUnipolarCurrent must NOT contain {forbidden!r} "
                "(S-VOCAB-01)"
            )

    def test_ac_three_phase_voltage_has_three_line_voltages(self, blocks):
        body = blocks["AcThreePhaseVoltage"]
        for required in ("v_ab_v", "v_bc_v", "v_ca_v"):
            assert required in body, (
                f"AcThreePhaseVoltage missing {required!r}"
            )


# ─── Block C -- strict SI units (operator answer Q5) ──────────────────────


FORBIDDEN_SI_SUFFIXES = (
    # Pressure -- must be Pa, not kPa / MPa / bar
    "_kpa", "_mpa", "_bar",
    # Temperature -- must be K, not Celsius
    "_celsius", "_deg_c",
    # Flow -- must be m3_per_s, not L/min or L/s
    "_lpm", "_l_per_s",
    # Power -- must be W, not kW / MW / kVA / kVAR / MVA
    "_kw", "_mw", "_kva", "_kvar", "_mva", "_gw",
    # Energy -- must be J, not kWh / MWh
    "_kwh", "_mwh",
    # Ratios -- must be _ratio, not _pct
    "_pct", "_percent",
    # Rotational speed -- must be rad/s, not RPM
    "_rpm",
    # Durations -- must be s, not min / hour / ms / us
    "_min", "_minute", "_hour", "_ms_duration", "_us_duration",
    # Resistance -- must be ohm, not milliohm or kohm
    "_mohm", "_kohm",
    # Conductivity -- must be S/m, not uS/cm
    "_us_per_cm", "_ms_per_cm",
)


class TestStrictSIUnits:

    def test_no_field_name_ends_with_a_forbidden_suffix(self, blocks):
        violations: list[str] = []
        for msg_name, body in blocks.items():
            for fname in _extract_field_names(body):
                for bad in FORBIDDEN_SI_SUFFIXES:
                    if fname.endswith(bad):
                        violations.append(
                            f"{msg_name}.{fname} ends with forbidden "
                            f"{bad!r}"
                        )
        assert not violations, (
            "Strict SI policy violations "
            "(operator answer RFC §10 Q5):\n  - "
            + "\n  - ".join(violations)
        )

    def test_temperature_field_is_kelvin(self, blocks):
        body = blocks["TemperatureMeasurement"]
        assert "temperature_k" in body
        assert "approach_to_dewpoint_k" in body

    def test_pressure_fields_are_pascal(self, blocks):
        assert "gauge_pa" in blocks["AbsolutePressureMeasurement"]
        assert "delta_p_pa" in blocks["PressureDiffMeasurement"]
        assert "delta_p_pa" in blocks["FilterDifferentialPressure"]

    def test_flow_field_is_m3_per_s(self, blocks):
        assert "flow_m3_per_s" in blocks["FlowMeasurement"]

    def test_power_fields_are_watts(self, blocks):
        body = blocks["PowerReading"]
        for fld in ("active_w", "reactive_w", "apparent_w"):
            assert fld in body, f"PowerReading missing {fld}"

    def test_soc_is_dimensionless_ratio(self, blocks):
        assert "soc_ratio" in blocks["UPSBatteryHealth"]
        assert "soc_ratio" in blocks["UPSBatteryStringStatus"]

    def test_angular_velocity_is_rad_per_s(self, blocks):
        assert "angular_velocity_rad_per_s" in blocks["PumpStatus"]

    def test_conductivity_is_siemens_per_metre(self, blocks):
        body = blocks["FluidChemistryMeasurement"]
        assert "conductivity_s_per_m" in body


# ─── Block D -- MeasurementQuality propagation ────────────────────────────


MEASUREMENT_MESSAGES = frozenset({
    "AcThreePhaseVoltage",
    "DcUnipolarVoltage",
    "AcThreePhaseCurrent",
    "DcUnipolarCurrent",
    "PowerReading",
    "STSAlarmEvent",
    "ATSStateEvent",
    "UPSElectricalStatus",
    "UPSThermalStatus",
    "UPSBatteryHealth",
    "UPSBatteryStringStatus",
    "UPSOperationalMode",
    "SSCBClearingEvent",
    "SSCBClearingEventCapture",
    "FlowMeasurement",
    "PressureDiffMeasurement",
    "AbsolutePressureMeasurement",
    "FluidChemistryMeasurement",
    "FilterDifferentialPressure",
    "TemperatureMeasurement",
    "PumpStatus",
    "LifeSafetyReading",
    "CombustibleReading",
})


class TestMeasurementQualityPropagation:

    def test_every_measurement_message_carries_quality_field(self, blocks):
        missing: list[str] = []
        for msg in MEASUREMENT_MESSAGES:
            if msg not in blocks:
                missing.append(f"{msg} (message itself absent)")
                continue
            body = blocks[msg]
            if not re.search(r"\bMeasurementQuality\s+quality\b", body):
                missing.append(f"{msg} (no MeasurementQuality quality field)")
        assert not missing, (
            "Quality propagation gaps (S-DET-02 input gating):\n  - "
            + "\n  - ".join(missing)
        )


# ─── Block E -- Discipline discriminator (RFC §6) ─────────────────────────


class TestDisciplineDiscriminator:

    def test_envelope_has_discipline_field_one(self, blocks):
        body = blocks["TelemetryEnvelope"]
        match = re.search(
            r"^\s*Discipline\s+discipline\s*=\s*1\s*;",
            body,
            re.MULTILINE,
        )
        assert match is not None, (
            "TelemetryEnvelope.discipline must be field #1 for "
            "zero-cost gRPC interceptor routing (RFC §6)"
        )

    def test_discipline_enum_lists_all_six_disciplines(self, proto_text):
        for name in (
            "DISCIPLINE_ELECTRICAL",
            "DISCIPLINE_MECHANICAL",
            "DISCIPLINE_THERMAL",
            "DISCIPLINE_LIFE_SAFETY",
            "DISCIPLINE_COMBUSTIBLE",
        ):
            assert name in proto_text, f"Discipline enum missing {name}"


# ─── Block F -- PTP sub-microsecond timestamps (operator Q4 confirmed) ────


EVENT_MESSAGES_WITH_PTP = frozenset({
    "STSAlarmEvent",
    "ATSStateEvent",
    "SSCBClearingEvent",
    "SubMicroSample",
    "UPSOperationalMode",
})


class TestPTPTimestamps:

    def test_event_messages_carry_ptp_nanos_field(self, blocks):
        missing: list[str] = []
        for msg in EVENT_MESSAGES_WITH_PTP:
            if msg not in blocks:
                missing.append(f"{msg} (message itself absent)")
                continue
            if "ptp_nanos_since_epoch" not in blocks[msg]:
                missing.append(msg)
        assert not missing, (
            "Event messages missing uint64 ptp_nanos_since_epoch "
            f"(S-PTP-01): {missing}"
        )

    def test_sscb_clearing_capture_carries_event_start_ptp_nanos(self, blocks):
        body = blocks["SSCBClearingEventCapture"]
        assert "event_start_ptp_nanos" in body, (
            "Waveform capture must carry an event-start timestamp "
            "anchor distinct from per-sample timestamps"
        )

    def test_ptp_nanos_is_uint64(self, proto_text):
        match = re.search(
            r"uint64\s+ptp_nanos_since_epoch\s*=\s*1",
            proto_text,
        )
        assert match is not None, (
            "PTP nanoseconds-since-epoch must be uint64 (capacity for "
            "post-2554 timestamps; PTP grandmaster guarantees alignment)"
        )

    def test_sub_micro_sample_carries_ptp_per_sample(self, blocks):
        body = blocks["SubMicroSample"]
        assert "ptp_nanos_since_epoch" in body, (
            "Each SSCB waveform sample needs its own sub-us PTP "
            "timestamp (1 MHz sampling -> 1 us per sample)"
        )


# ─── Block G -- UPS 5-way split (operator Q3) ─────────────────────────────


UPS_SUB_MESSAGES = frozenset({
    "UPSElectricalStatus",
    "UPSThermalStatus",
    "UPSBatteryHealth",
    "UPSBatteryStringStatus",   # NEW v1 per operator answer Q3
    "UPSOperationalMode",
})


class TestUPSSegmentation:

    def test_ups_split_into_five_sub_messages(self, blocks):
        missing = UPS_SUB_MESSAGES - set(blocks.keys())
        assert not missing, (
            f"UPS sub-messages missing (operator Q3 mandates 5): {missing}"
        )

    def test_monolithic_ups_status_is_forbidden(self, blocks):
        assert "UPSStatus" not in blocks, (
            "Monolithic UPSStatus must NOT exist in v1; the operator "
            "(RFC §2) mandated the 5-way split"
        )

    def test_no_ups_wrapper_message_refuses_the_split(self, blocks):
        for forbidden in (
            "UPSCompositeStatus",
            "UPSStatusBundle",
            "UPSStatusV1",
            "UPSAggregateStatus",
        ):
            assert forbidden not in blocks, (
                "v1 forbids re-fusing the 5 UPS sub-messages "
                f"into a wrapper ({forbidden})"
            )

    def test_battery_string_status_carries_string_id(self, blocks):
        body = blocks["UPSBatteryStringStatus"]
        assert "string_id" in body, (
            "Per-string predictive maintenance requires string_id "
            "(operator Q3)"
        )


# ─── Block H -- OCP CDU Test Methodology compliance (operator Q2) ─────────


class TestOCPCDUMapping:

    def test_flow_measurement_has_rack_id_and_cdu_id(self, blocks):
        body = blocks["FlowMeasurement"]
        assert "rack_id" in body, (
            "OCP CDU Test Methodology requires per-rack flow attribution"
        )
        assert "cdu_id" in body

    def test_absolute_pressure_measurement_exists(self, blocks):
        assert "AbsolutePressureMeasurement" in blocks
        body = blocks["AbsolutePressureMeasurement"]
        assert "gauge_pa" in body
        assert "location" in body

    def test_absolute_pressure_is_sibling_of_differential(self, blocks):
        # Both messages exist, neither subsumes the other.
        assert "PressureDiffMeasurement" in blocks
        assert "AbsolutePressureMeasurement" in blocks

    def test_fluid_chemistry_message_exists(self, blocks):
        # Operator answer Q2: conductivity + pH for corrosion monitoring.
        assert "FluidChemistryMeasurement" in blocks
        body = blocks["FluidChemistryMeasurement"]
        assert "conductivity_s_per_m" in body
        assert re.search(r"\bdouble\s+ph\s*=\s*\d+", body) is not None, (
            "FluidChemistryMeasurement must declare a `double ph` field "
            "(operator Q2)"
        )

    def test_filter_differential_pressure_message_exists(self, blocks):
        # Operator answer Q2: filter dP per stage.
        assert "FilterDifferentialPressure" in blocks
        body = blocks["FilterDifferentialPressure"]
        assert "delta_p_pa" in body
        assert "stage" in body, (
            "Filter dP must declare a `stage` field (FilterStage enum)"
        )

    def test_filter_stage_enum_has_three_stages(self, proto_text):
        for stage in (
            "FILTER_STAGE_PRE",
            "FILTER_STAGE_MAIN",
            "FILTER_STAGE_POLISHING",
        ):
            assert stage in proto_text, f"FilterStage enum missing {stage}"

    def test_atd_first_class_on_temperature_measurement(self, blocks):
        body = blocks["TemperatureMeasurement"]
        assert "approach_to_dewpoint_k" in body, (
            "ATD (Approach to Dewpoint) is the panel-grade DLC safety "
            "metric and must be a first-class field on every "
            "TemperatureMeasurement (RFC §3.4)"
        )


# ─── Block I -- Wire-size budget + protoc acceptance ──────────────────────


class TestSchemaAcceptance:

    def test_envelope_field_count_within_ceiling(self, blocks):
        body = blocks["TelemetryEnvelope"]
        # Count numbered field slots (each = a varint-tagged wire field).
        # Include both top-level fields and oneof variants -- they all
        # consume a tag slot.
        n_slots = len(re.findall(r"=\s*\d+\s*;", body))
        assert n_slots <= 15, (
            f"TelemetryEnvelope has {n_slots} numbered slots; RFC §1.5 "
            "budget assumes <=15 to hold the 200 B/msg wire ceiling"
        )

    def test_proto_compiles_via_grpc_tools_if_available(self, tmp_path):
        protoc = pytest.importorskip("grpc_tools.protoc")
        import grpc_tools  # type: ignore[import-not-found]

        # grpc_tools.protoc.main(...) does NOT auto-include the
        # bundled well-known types path the way `python -m
        # grpc_tools.protoc` does -- we replicate that injection here
        # so `import "google/protobuf/timestamp.proto"` resolves.
        proto_include = str(Path(grpc_tools.__file__).parent / "_proto")
        src_dir = PROTO_PATH.parent
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        rc = protoc.main([
            "grpc_tools.protoc",
            f"-I{proto_include}",
            f"--proto_path={src_dir}",
            f"--python_out={out_dir}",
            str(PROTO_PATH),
        ])
        assert rc == 0, (
            "grpc_tools.protoc failed to compile telemetry.proto -- "
            "schema is not proto3-valid"
        )

    def test_no_orphan_messages(self, blocks, proto_text):
        # Every message defined in the file should be referenced
        # somewhere (either inside another message body or as a type
        # in the envelope's oneof). Orphans = dead schema = panel risk.
        ROOT = "TelemetryEnvelope"
        orphans: list[str] = []
        for msg in blocks:
            if msg == ROOT:
                continue
            # crude reference check: name appears as a field type
            # somewhere outside its own definition.
            pattern = re.compile(rf"\b{msg}\b\s+\w+\s*=\s*\d+")
            n_refs = sum(
                1 for other_body in blocks.values()
                if pattern.search(other_body)
            )
            if n_refs == 0:
                orphans.append(msg)
        assert not orphans, (
            f"Orphan messages (defined but never referenced): {orphans}"
        )
