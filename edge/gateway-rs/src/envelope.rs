//! Strict-SI samples -> canonical v1 `TelemetryEnvelope`.
//!
//! This is where the vocabulary fence reaches the WIRE: a
//! `SiSample::DcUnipolarVoltage` can only construct the
//! `voltage_reading::Topology::DcUnipolar` arm — phase fields are
//! unreachable from a DC channel by type construction, mirroring the
//! schema's own `oneof topology` design.
//!
//! Quality policy (honest labeling): the channel's configured label
//! (GOOD for a real PLC, SIMULATED for the bench sim) is stamped both
//! on the envelope and on the payload-level quality field.

use std::time::{SystemTime, UNIX_EPOCH};

use crate::config::{ChannelConfig, QualityLabel, SiSample};
use crate::proto::v1;

fn now_timestamp() -> prost_types::Timestamp {
    let d = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default();
    prost_types::Timestamp {
        seconds: d.as_secs() as i64,
        nanos: d.subsec_nanos() as i32,
    }
}

fn quality(label: QualityLabel) -> v1::MeasurementQuality {
    match label {
        QualityLabel::Good => v1::MeasurementQuality::QualityGood,
        QualityLabel::Simulated => v1::MeasurementQuality::QualitySimulated,
    }
}

fn temp_location(name: Option<&str>) -> v1::TempLocation {
    match name.unwrap_or("") {
        "dlc_supply" => v1::TempLocation::TempDlcSupply,
        "dlc_return" => v1::TempLocation::TempDlcReturn,
        "rack_inlet" => v1::TempLocation::TempRackInlet,
        "rack_outlet" => v1::TempLocation::TempRackOutlet,
        "chiller_lwt" => v1::TempLocation::TempChillerLwt,
        "chiller_ewt" => v1::TempLocation::TempChillerEwt,
        "ecwt" => v1::TempLocation::TempEcwt,
        "wet_bulb" => v1::TempLocation::TempWetBulb,
        _ => v1::TempLocation::Unspecified,
    }
}

fn coolant_loop(name: Option<&str>) -> v1::CoolantLoop {
    match name.unwrap_or("") {
        "primary" => v1::CoolantLoop::Primary,
        "secondary" => v1::CoolantLoop::Secondary,
        "condenser" => v1::CoolantLoop::Condenser,
        _ => v1::CoolantLoop::Unspecified,
    }
}

fn bus_segment(name: Option<&str>) -> v1::AcBusSegment {
    match name.unwrap_or("") {
        "utility_mv" => v1::AcBusSegment::AcBusUtilityMv,
        "primary_480_a" => v1::AcBusSegment::AcBusPrimary480A,
        "primary_480_b" => v1::AcBusSegment::AcBusPrimary480B,
        "generator_parallel" => v1::AcBusSegment::AcBusGeneratorParallel,
        _ => v1::AcBusSegment::AcBusUnspecified,
    }
}

/// Build the canonical envelope for one polled sample.
pub fn build_envelope(
    site_id: &str,
    sequence_number: u64,
    ch: &ChannelConfig,
    sample: &SiSample,
) -> v1::TelemetryEnvelope {
    let q = quality(ch.quality);
    let (discipline, payload) = match *sample {
        SiSample::DcUnipolarVoltage { v_dc_bus_v } => (
            v1::Discipline::Electrical,
            v1::telemetry_envelope::Payload::Electrical(v1::ElectricalReading {
                body: Some(v1::electrical_reading::Body::Voltage(v1::VoltageReading {
                    // VOCABULARY FENCE: the only constructible arm for a
                    // DC channel. No v_ab/v_bc/v_ca exist on this type.
                    topology: Some(v1::voltage_reading::Topology::DcUnipolar(
                        v1::DcUnipolarVoltage {
                            v_dc_bus_v,
                            ripple_ratio: 0.0,
                            mv_rectifier_output_v: 0.0,
                            quality: q as i32,
                        },
                    )),
                })),
            }),
        ),
        SiSample::AcThreePhaseVoltage { v_ab_v, v_bc_v, v_ca_v, frequency_hz } => (
            v1::Discipline::Electrical,
            v1::telemetry_envelope::Payload::Electrical(v1::ElectricalReading {
                body: Some(v1::electrical_reading::Body::Voltage(v1::VoltageReading {
                    topology: Some(v1::voltage_reading::Topology::AcThreePhase(
                        v1::AcThreePhaseVoltage {
                            v_ab_v,
                            v_bc_v,
                            v_ca_v,
                            frequency_hz,
                            bus_segment: bus_segment(ch.bus_segment.as_deref()) as i32,
                            quality: q as i32,
                        },
                    )),
                })),
            }),
        ),
        SiSample::Temperature { temperature_k } => (
            v1::Discipline::Thermal,
            v1::telemetry_envelope::Payload::Thermal(v1::ThermalReading {
                body: Some(v1::thermal_reading::Body::Temperature(
                    v1::TemperatureMeasurement {
                        location: temp_location(ch.temp_location.as_deref()) as i32,
                        temperature_k,
                        // ATD only required at TEMP_DLC_SUPPLY (RFC §3.4)
                        // — generic temperature channels carry 0.0.
                        approach_to_dewpoint_k: 0.0,
                        quality: q as i32,
                    },
                )),
            }),
        ),
        SiSample::TemperatureDlcSupply { temperature_k, approach_to_dewpoint_k } => (
            v1::Discipline::Thermal,
            v1::telemetry_envelope::Payload::Thermal(v1::ThermalReading {
                body: Some(v1::thermal_reading::Body::Temperature(
                    v1::TemperatureMeasurement {
                        location: v1::TempLocation::TempDlcSupply as i32,
                        temperature_k,
                        approach_to_dewpoint_k,
                        quality: q as i32,
                    },
                )),
            }),
        ),
        SiSample::Flow { flow_m3_per_s } => (
            v1::Discipline::Mechanical,
            v1::telemetry_envelope::Payload::Mechanical(v1::MechanicalReading {
                body: Some(v1::mechanical_reading::Body::Flow(v1::FlowMeasurement {
                    flow_m3_per_s,
                    r#loop: coolant_loop(ch.coolant_loop.as_deref()) as i32,
                    rack_id: String::new(),
                    cdu_id: String::new(),
                    quality: q as i32,
                })),
            }),
        ),
    };

    v1::TelemetryEnvelope {
        discipline: discipline as i32,
        sequence_number,
        emitted_at: Some(now_timestamp()),
        site_id: site_id.to_string(),
        asset_id: ch.asset_id.clone(),
        payload: Some(payload),
        innovation: None, // Kalman runs backend-side; the edge sends raw
        quality: q as i32,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::ChannelKind;

    fn ch(kind: ChannelKind) -> ChannelConfig {
        ChannelConfig {
            name: "t".into(),
            asset_id: "dc_bus_d".into(),
            kind,
            register: 0,
            scale: 1.0,
            offset: 0.0,
            quality: QualityLabel::Simulated,
            temp_location: None,
            coolant_loop: Some("secondary".into()),
            bus_segment: Some("utility_mv".into()),
        }
    }

    #[test]
    fn dc_sample_reaches_the_wire_as_dc_unipolar_only() {
        let env = build_envelope(
            "a3-alpha-toronto", 7,
            &ch(ChannelKind::DcUnipolarVoltage),
            &SiSample::DcUnipolarVoltage { v_dc_bus_v: 800.0 },
        );
        assert_eq!(env.discipline, v1::Discipline::Electrical as i32);
        assert_eq!(env.sequence_number, 7);
        assert_eq!(env.quality, v1::MeasurementQuality::QualitySimulated as i32);
        let v1::telemetry_envelope::Payload::Electrical(e) = env.payload.unwrap() else {
            panic!("wrong payload arm");
        };
        let v1::electrical_reading::Body::Voltage(v) = e.body.unwrap() else {
            panic!("wrong body arm");
        };
        match v.topology.unwrap() {
            v1::voltage_reading::Topology::DcUnipolar(dc) => {
                assert_eq!(dc.v_dc_bus_v, 800.0);
            }
            v1::voltage_reading::Topology::AcThreePhase(_) => {
                panic!("VOCABULARY FENCE BREACH: dc sample mapped to ac_three_phase");
            }
        }
    }

    #[test]
    fn ac_sample_carries_bus_segment_and_three_phases() {
        let env = build_envelope(
            "a3-alpha-toronto", 1,
            &ch(ChannelKind::AcThreePhaseVoltage),
            &SiSample::AcThreePhaseVoltage {
                v_ab_v: 35000.0, v_bc_v: 35010.0, v_ca_v: 34990.0, frequency_hz: 60.0,
            },
        );
        let v1::telemetry_envelope::Payload::Electrical(e) = env.payload.unwrap() else {
            panic!("wrong payload arm");
        };
        let v1::electrical_reading::Body::Voltage(v) = e.body.unwrap() else {
            panic!("wrong body arm");
        };
        let v1::voltage_reading::Topology::AcThreePhase(ac) = v.topology.unwrap() else {
            panic!("ac sample lost its phases");
        };
        assert_eq!(ac.v_ab_v, 35000.0);
        assert_eq!(ac.bus_segment, v1::AcBusSegment::AcBusUtilityMv as i32);
        assert_eq!(ac.frequency_hz, 60.0);
    }

    #[test]
    fn dlc_supply_temperature_carries_required_atd() {
        let env = build_envelope(
            "a3-alpha-toronto", 2,
            &ch(ChannelKind::TemperatureDlcSupply),
            &SiSample::TemperatureDlcSupply {
                temperature_k: 291.15,
                approach_to_dewpoint_k: 10.0,
            },
        );
        assert_eq!(env.discipline, v1::Discipline::Thermal as i32);
        let v1::telemetry_envelope::Payload::Thermal(t) = env.payload.unwrap() else {
            panic!("wrong payload arm");
        };
        let v1::thermal_reading::Body::Temperature(m) = t.body.unwrap();
        assert_eq!(m.location, v1::TempLocation::TempDlcSupply as i32);
        assert_eq!(m.approach_to_dewpoint_k, 10.0);
    }

    #[test]
    fn flow_sample_maps_to_mechanical_secondary_loop() {
        let env = build_envelope(
            "a3-alpha-toronto", 3,
            &ch(ChannelKind::Flow),
            &SiSample::Flow { flow_m3_per_s: 0.066 },
        );
        assert_eq!(env.discipline, v1::Discipline::Mechanical as i32);
        let v1::telemetry_envelope::Payload::Mechanical(m) = env.payload.unwrap() else {
            panic!("wrong payload arm");
        };
        let v1::mechanical_reading::Body::Flow(f) = m.body.unwrap() else {
            panic!("wrong body arm");
        };
        assert_eq!(f.flow_m3_per_s, 0.066);
        assert_eq!(f.r#loop, v1::CoolantLoop::Secondary as i32);
    }
}
