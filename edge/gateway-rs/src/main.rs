//! dc-epms-gateway — A3 edge gateway binary.
//!
//! Phase 2 Batch A: real Modbus TCP polling. Loads `gateway.toml`,
//! connects to the configured device (bench `modbus-sim` or a real
//! PLC), sweeps the register map every poll period and logs the
//! strict-SI samples. Egress of v1 proto envelopes to the backend is
//! Batch B — the sample structs produced here are already
//! payload-shaped for it.

use std::path::PathBuf;
use std::time::Duration;

use anyhow::Result;
use dc_epms_gateway::config::GatewayConfig;
use dc_epms_gateway::egress::EgressClient;
use dc_epms_gateway::envelope::build_envelope;
use dc_epms_gateway::modbus::ModbusClient;
use tracing::{error, info, warn};

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_target(false)
        .with_level(true)
        .init();

    let config_path = std::env::args()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("gateway.toml"));
    let cfg = GatewayConfig::load(&config_path)?;
    info!(
        site_id = %cfg.site_id,
        device = %format!("{}:{}", cfg.device.host, cfg.device.port),
        channels = cfg.channels.len(),
        poll_ms = cfg.poll_period_ms,
        "dc-epms-gateway boot (phase 2 batch A — modbus ingestion)"
    );

    let io_timeout = Duration::from_millis(cfg.device.timeout_ms);
    let poll_period = Duration::from_millis(cfg.poll_period_ms);
    let egress = EgressClient::new(&cfg.backend_ingest_url, Duration::from_secs(5))?;
    let mut sequence: u64 = 0;
    let mut dropped_batches: u64 = 0;

    // Defensive outer loop: a lost device connection (PLC reboot,
    // network blip) re-enters connect with backoff instead of dying.
    loop {
        let mut client = match ModbusClient::connect(
            &cfg.device.host,
            cfg.device.port,
            cfg.device.unit_id,
            io_timeout,
        )
        .await
        {
            Ok(c) => {
                info!("modbus: connected");
                c
            }
            Err(e) => {
                error!(error = %e, "modbus: connect failed; retrying in 3 s");
                tokio::time::sleep(Duration::from_secs(3)).await;
                continue;
            }
        };

        'poll: loop {
            tokio::time::sleep(poll_period).await;
            let mut batch = Vec::with_capacity(cfg.channels.len());
            for ch in &cfg.channels {
                match client.read_holdings(ch.register, ch.kind.word_count()).await {
                    Ok(words) => match ch.to_si(&words) {
                        Ok(sample) => {
                            sequence += 1;
                            batch.push(build_envelope(&cfg.site_id, sequence, ch, &sample));
                            info!(channel = %ch.name, asset = %ch.asset_id,
                                  quality = ?ch.quality, sample = ?sample, "poll");
                        }
                        Err(e) => warn!(channel = %ch.name, error = %e, "scaling error"),
                    },
                    Err(e) => {
                        warn!(channel = %ch.name, error = %e, "modbus read failed; reconnecting");
                        break 'poll;
                    }
                }
            }
            // Drop-and-continue egress policy: a dead backend must never
            // stall field polling. Losses are counted and logged.
            match egress.ship(&batch).await {
                Ok(n) => info!(shipped = n, "egress"),
                Err(e) => {
                    dropped_batches += 1;
                    warn!(error = %e, dropped_batches, "egress failed; batch dropped");
                }
            }
        }
    }
}
