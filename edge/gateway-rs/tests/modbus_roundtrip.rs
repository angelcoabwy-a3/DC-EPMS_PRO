//! Integration test: real Modbus TCP roundtrip on a real socket.
//!
//! Spins the bench sim server on an ephemeral port, connects the
//! gateway's ModbusClient, sweeps the bench register map and asserts
//! the strict-SI values — the exact path a real PLC would exercise.

use std::time::Duration;

use dc_epms_gateway::config::{ChannelConfig, ChannelKind, GatewayConfig, QualityLabel, SiSample};
use dc_epms_gateway::modbus::ModbusClient;
use dc_epms_gateway::sim;
use tokio::net::TcpListener;

const BENCH_TOML: &str = include_str!("../gateway.toml");

async fn spawn_sim() -> (u16, tokio::task::JoinHandle<()>) {
    let listener = TcpListener::bind(("127.0.0.1", 0)).await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let storage = sim::bench_profile();
    let handle = tokio::spawn(async move {
        let _ = sim::serve(listener, 1, storage).await;
    });
    (port, handle)
}

async fn connect(port: u16) -> ModbusClient {
    ModbusClient::connect("127.0.0.1", port, 1, Duration::from_secs(2))
        .await
        .expect("client connect")
}

fn bench_channels() -> Vec<ChannelConfig> {
    GatewayConfig::from_toml_str(BENCH_TOML)
        .expect("committed gateway.toml must parse")
        .channels
}

#[tokio::test]
async fn full_bench_sweep_yields_strict_si_samples() {
    let (port, server) = spawn_sim().await;
    let mut client = connect(port).await;

    let mut samples = Vec::new();
    for ch in bench_channels() {
        let words = client
            .read_holdings(ch.register, ch.kind.word_count())
            .await
            .expect("holding read");
        samples.push((ch.name.clone(), ch.quality, ch.to_si(&words).expect("scaling")));
    }

    assert_eq!(samples.len(), 4);
    // Phase 2 fence: the DC bus arrives as ONE unipolar value, 800.0 V.
    assert_eq!(
        samples[0].2,
        SiSample::DcUnipolarVoltage { v_dc_bus_v: 800.0 },
    );
    // MV intake arrives as three phases + 60.00 Hz.
    match samples[1].2 {
        SiSample::AcThreePhaseVoltage { v_ab_v, frequency_hz, .. } => {
            assert_eq!(v_ab_v, 35000.0);
            assert!((frequency_hz - 60.0).abs() < 1e-9);
        }
        ref other => panic!("expected AC sample, got {other:?}"),
    }
    // Temperature in Kelvin (291.15 K = 18 degC), flow in m^3/s.
    match samples[2].2 {
        SiSample::Temperature { temperature_k } => {
            assert!((temperature_k - 291.15).abs() < 1e-9);
        }
        ref other => panic!("expected temperature sample, got {other:?}"),
    }
    match samples[3].2 {
        SiSample::Flow { flow_m3_per_s } => assert!((flow_m3_per_s - 0.066).abs() < 1e-12),
        ref other => panic!("expected flow sample, got {other:?}"),
    }
    // Bench profile is honestly labeled.
    assert!(samples.iter().all(|(_, q, _)| *q == QualityLabel::Simulated));

    server.abort();
}

#[tokio::test]
async fn wobbled_registers_stay_readable_and_in_band() {
    let (port, server) = spawn_sim().await;
    let mut client = connect(port).await;

    // The sim wobbles between polls; every poll must still scale into
    // engineering bounds (this is the steady-state SoD precondition).
    let storage = sim::bench_profile();
    for tick in 1..=5 {
        sim::wobble_tick(&storage, tick);
        let words = client.read_holdings(0, 1).await.expect("dc bus read");
        let v = f64::from(words[0]) * 0.1;
        assert!((798.0..=802.0).contains(&v), "dc bus out of band: {v} V");
    }

    server.abort();
}

#[tokio::test]
async fn dc_kind_cannot_produce_phase_fields() {
    // Vocabulary fence at the type level: a dc_unipolar_voltage channel
    // yields a variant that simply HAS no v_ab/v_bc/v_ca — the
    // compiler, not a review checklist, enforces the fence.
    let ch = ChannelConfig {
        name: "fence".into(),
        asset_id: "dc_bus_d".into(),
        kind: ChannelKind::DcUnipolarVoltage,
        register: 0,
        scale: 0.1,
        offset: 0.0,
        quality: QualityLabel::Simulated,
    };
    match ch.to_si(&[8000]).unwrap() {
        SiSample::DcUnipolarVoltage { v_dc_bus_v } => assert_eq!(v_dc_bus_v, 800.0),
        other => panic!("dc channel produced non-dc sample: {other:?}"),
    }
}
