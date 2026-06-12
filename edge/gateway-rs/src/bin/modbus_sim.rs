//! modbus-sim — bench Modbus TCP field-device stand-in.
//!
//! Serves the bench register profile (see `sim::bench_profile`) over
//! REAL Modbus TCP, with a deterministic wobble so consecutive gateway
//! polls see realistic excursions. Usage:
//!
//!     modbus-sim [port]        # default 1502, unit id 1
//!
//! HONEST SCOPE: values are synthetic; the protocol is not. Data
//! sourced from this sim must travel as QUALITY_SIMULATED.

use std::time::Duration;

use anyhow::Result;
use dc_epms_gateway::sim;
use tokio::net::TcpListener;
use tracing::info;

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt().with_target(false).init();

    let port: u16 = std::env::args()
        .nth(1)
        .map(|p| p.parse().expect("port must be a u16"))
        .unwrap_or(1502);
    let listener = TcpListener::bind(("127.0.0.1", port)).await?;
    info!(port, unit_id = 1, "modbus-sim listening (bench field-device stand-in)");

    let storage = sim::bench_profile();
    let wobbler = tokio::spawn(sim::wobble_loop(storage.clone(), Duration::from_secs(1)));

    let served = sim::serve(listener, 1, storage).await;
    wobbler.abort();
    served
}
