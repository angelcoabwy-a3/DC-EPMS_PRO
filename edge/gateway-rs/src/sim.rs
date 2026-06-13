//! Bench Modbus TCP server (`modbus-sim` binary + integration tests).
//!
//! HONEST SCOPE: this is a FIELD-DEVICE STAND-IN for the lab bench.
//! The Modbus TCP protocol on the socket is real (rmodbus server
//! frames); only the register VALUES are synthetic. Channels read from
//! this profile must carry QUALITY_SIMULATED on the wire. Pointing the
//! gateway at a real PLC removes the sim from the loop with zero
//! gateway code changes.

use std::sync::{Arc, RwLock};
use std::time::Duration;

use anyhow::{Context, Result};
use rmodbus::server::context::ModbusContext;
use rmodbus::server::{storage::ModbusStorageFull, ModbusFrame};
use rmodbus::{ModbusFrameBuf, ModbusProto};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;

pub type SharedStorage = Arc<RwLock<ModbusStorageFull>>;

/// Bench register profile — mirrors `gateway.toml` (committed bench
/// config). Raw register encodings (strict-SI after gateway scaling):
///
///   reg 0      dc_bus_d        deci-volts        8000 -> 800.0 V
///   reg 10-12  utility_d MV    volts             ~35000 V line-line
///   reg 13     utility_d freq  centi-hertz       6000 -> 60.00 Hz
///   reg 20     dlc supply      centi-kelvin      29115 -> 291.15 K
///   reg 21     hall dewpoint   centi-kelvin      28115 -> 281.15 K
///              (ATD = reg20 - reg21 = 10 K, the RFC 3.4 requirement)
///   reg 30     dlc loop flow   1e-5 m^3/s units  6600 -> 0.066 m^3/s
pub fn bench_profile() -> SharedStorage {
    let mut s = ModbusStorageFull::default();
    s.set_holding(0, 8000).expect("dc bus reg");
    s.set_holdings_bulk(10, &[35000, 35010, 34990, 6000]).expect("mv intake regs");
    s.set_holdings_bulk(20, &[29115, 28115]).expect("dlc temp + dewpoint regs");
    s.set_holding(30, 6600).expect("loop flow reg");
    Arc::new(RwLock::new(s))
}

/// Apply one wobble tick to the bench profile so consecutive polls see
/// realistic small excursions (deterministic, phase-driven — no RNG).
pub fn wobble_tick(storage: &SharedStorage, tick: u64) {
    let phase = (tick as f64) * 0.35;
    let mut s = storage.write().expect("sim storage poisoned");
    // 800 V bus: +/- 1.5 V ripple-scale wobble (deci-volt register).
    let dc = 8000.0 + 15.0 * phase.sin();
    s.set_holding(0, dc as u16).ok();
    // MV intake: +/- 40 V swing around 35 kV, slight per-phase skew.
    for (i, skew) in [0.0_f64, 0.7, 1.4].iter().enumerate() {
        let v = 35000.0 + 40.0 * (phase + skew).sin();
        s.set_holding(10 + i as u16, v as u16).ok();
    }
    // Frequency: 60.00 +/- 0.02 Hz (centi-hertz register).
    let hz = 6000.0 + 2.0 * (phase * 0.5).cos();
    s.set_holding(13, hz as u16).ok();
    // DLC supply: 291.15 K +/- 0.2 K (centi-kelvin register).
    let k = 29115.0 + 20.0 * (phase * 0.2).sin();
    s.set_holding(20, k as u16).ok();
}

/// Serve Modbus TCP on `listener` until the task is dropped. One
/// spawned task per connection; storage shared behind an RwLock.
pub async fn serve(listener: TcpListener, unit_id: u8, storage: SharedStorage) -> Result<()> {
    loop {
        let (mut socket, peer) = listener.accept().await.context("accept failed")?;
        tracing::info!(%peer, "modbus-sim: client connected");
        let storage = storage.clone();
        tokio::spawn(async move {
            loop {
                let mut buf: ModbusFrameBuf = [0; 256];
                let n = match socket.read(&mut buf).await {
                    Ok(0) | Err(_) => return,
                    Ok(n) => n,
                };
                let _ = n; // rmodbus parses from the fixed frame buffer
                let mut response = Vec::new();
                let mut frame = ModbusFrame::new(unit_id, &buf, ModbusProto::TcpUdp, &mut response);
                if frame.parse().is_err() {
                    tracing::warn!("modbus-sim: bad frame, dropping connection");
                    return;
                }
                if frame.processing_required {
                    let ok = if frame.readonly {
                        frame.process_read(&*storage.read().expect("sim storage poisoned"))
                    } else {
                        frame.process_write(&mut *storage.write().expect("sim storage poisoned"))
                    };
                    if ok.is_err() {
                        tracing::warn!("modbus-sim: frame processing error");
                        return;
                    }
                }
                if frame.response_required {
                    if frame.finalize_response().is_err() {
                        return;
                    }
                    if socket.write_all(&response).await.is_err() {
                        return;
                    }
                }
            }
        });
    }
}

/// Run the wobble loop alongside `serve` (used by the modbus-sim bin).
pub async fn wobble_loop(storage: SharedStorage, period: Duration) {
    let mut tick: u64 = 0;
    loop {
        tokio::time::sleep(period).await;
        tick = tick.wrapping_add(1);
        wobble_tick(&storage, tick);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bench_profile_seeds_expected_registers() {
        let storage = bench_profile();
        let s = storage.read().unwrap();
        assert_eq!(s.get_holding(0).unwrap(), 8000);
        assert_eq!(s.get_holding(10).unwrap(), 35000);
        assert_eq!(s.get_holding(13).unwrap(), 6000);
        assert_eq!(s.get_holding(20).unwrap(), 29115);
        assert_eq!(s.get_holding(21).unwrap(), 28115);
        assert_eq!(s.get_holding(30).unwrap(), 6600);
    }

    #[test]
    fn wobble_stays_within_engineering_bounds() {
        let storage = bench_profile();
        for tick in 1..=400 {
            wobble_tick(&storage, tick);
            let s = storage.read().unwrap();
            let dc = s.get_holding(0).unwrap();
            assert!((7980..=8020).contains(&dc), "dc bus out of band: {dc}");
            let hz = s.get_holding(13).unwrap();
            assert!((5995..=6005).contains(&hz), "frequency out of band: {hz}");
        }
    }
}
