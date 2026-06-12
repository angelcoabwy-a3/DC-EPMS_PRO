//! `gateway.toml` schema — device endpoint + register map.
//!
//! Each channel maps ONE Modbus register window to ONE strict-SI value
//! stream bound for a v1 `TelemetryEnvelope` payload. The word count is
//! implied by the kind (see [`ChannelKind::word_count`]); raw register
//! words convert to SI as `value = raw * scale + offset`.
//!
//! STRICT SI: scales/offsets MUST land the value in the SI unit the v1
//! schema demands (Volts, Kelvin, m^3/s, Hz). E.g. a register holding
//! tenths of a volt uses `scale = 0.1`; one holding centi-Kelvin uses
//! `scale = 0.01`. There is no Celsius/bar/LPM anywhere past this file.

use std::path::Path;

use anyhow::{bail, Context, Result};
use serde::Deserialize;

#[derive(Debug, Clone, Deserialize)]
pub struct GatewayConfig {
    /// Site identifier stamped on every envelope (e.g. "a3-alpha-toronto").
    pub site_id: String,
    /// Backend ingest endpoint (Batch B egress target).
    pub backend_ingest_url: String,
    /// Poll period for the register sweep, milliseconds.
    pub poll_period_ms: u64,
    pub device: DeviceConfig,
    pub channels: Vec<ChannelConfig>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct DeviceConfig {
    pub host: String,
    pub port: u16,
    pub unit_id: u8,
    /// Per-request IO timeout, milliseconds.
    pub timeout_ms: u64,
}

/// Which v1 payload a channel feeds. THIS is the vocabulary fence at
/// the edge: `DcUnipolarVoltage` can only ever construct the
/// `dc_unipolar` arm of `VoltageReading.oneof topology` — there is no
/// code path from a DC channel to phase fields.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ChannelKind {
    /// 1 word: v_dc_bus_v. 800 VDC bus is UNIPOLAR TN-S — no phases.
    DcUnipolarVoltage,
    /// 4 words: v_ab, v_bc, v_ca (shared scale) + frequency (x0.01 Hz).
    AcThreePhaseVoltage,
    /// 1 word: temperature_k.
    Temperature,
    /// 1 word: flow_m3_per_s.
    Flow,
}

impl ChannelKind {
    /// Modbus holding-register words this kind consumes.
    pub fn word_count(self) -> u16 {
        match self {
            ChannelKind::AcThreePhaseVoltage => 4,
            _ => 1,
        }
    }
}

/// Honest data labeling. Bench profile (modbus-sim) marks SIMULATED;
/// a real PLC profile marks GOOD. Mapped to the v1 MeasurementQuality
/// enum in Batch B.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum QualityLabel {
    #[default]
    Good,
    Simulated,
}

#[derive(Debug, Clone, Deserialize)]
pub struct ChannelConfig {
    /// Unique channel name (logging + dedup key).
    pub name: String,
    /// Canonical asset id, aligned with the backend node registry
    /// (e.g. "dc_bus_d", "utility_intake_d", "cdu_a_01").
    pub asset_id: String,
    pub kind: ChannelKind,
    /// First holding register of this channel's window.
    pub register: u16,
    /// raw -> SI multiplier (applies to all words except the AC
    /// frequency word, which is fixed at x0.01 Hz).
    pub scale: f64,
    #[serde(default)]
    pub offset: f64,
    #[serde(default)]
    pub quality: QualityLabel,
}

/// One scaled strict-SI sample read from the device.
#[derive(Debug, Clone, PartialEq)]
pub enum SiSample {
    DcUnipolarVoltage { v_dc_bus_v: f64 },
    AcThreePhaseVoltage { v_ab_v: f64, v_bc_v: f64, v_ca_v: f64, frequency_hz: f64 },
    Temperature { temperature_k: f64 },
    Flow { flow_m3_per_s: f64 },
}

impl ChannelConfig {
    /// Convert raw register words into a strict-SI sample. Word count
    /// must match the kind; the caller reads exactly
    /// `kind.word_count()` registers.
    pub fn to_si(&self, words: &[u16]) -> Result<SiSample> {
        let need = self.kind.word_count() as usize;
        if words.len() != need {
            bail!(
                "channel {}: expected {} register word(s), got {}",
                self.name, need, words.len()
            );
        }
        let si = |raw: u16| f64::from(raw) * self.scale + self.offset;
        Ok(match self.kind {
            ChannelKind::DcUnipolarVoltage => SiSample::DcUnipolarVoltage { v_dc_bus_v: si(words[0]) },
            ChannelKind::AcThreePhaseVoltage => SiSample::AcThreePhaseVoltage {
                v_ab_v: si(words[0]),
                v_bc_v: si(words[1]),
                v_ca_v: si(words[2]),
                // Fixed convention: AC frequency word is centi-Hertz.
                frequency_hz: f64::from(words[3]) * 0.01,
            },
            ChannelKind::Temperature => SiSample::Temperature { temperature_k: si(words[0]) },
            ChannelKind::Flow => SiSample::Flow { flow_m3_per_s: si(words[0]) },
        })
    }
}

impl GatewayConfig {
    pub fn from_toml_str(raw: &str) -> Result<Self> {
        let cfg: GatewayConfig = toml::from_str(raw).context("gateway.toml parse failed")?;
        cfg.validate()?;
        Ok(cfg)
    }

    pub fn load(path: &Path) -> Result<Self> {
        let raw = std::fs::read_to_string(path)
            .with_context(|| format!("cannot read config {}", path.display()))?;
        Self::from_toml_str(&raw)
    }

    fn validate(&self) -> Result<()> {
        if self.site_id.is_empty() {
            bail!("site_id must be non-empty");
        }
        if self.poll_period_ms == 0 {
            bail!("poll_period_ms must be > 0");
        }
        if self.channels.is_empty() {
            bail!("at least one channel is required");
        }
        let mut names = std::collections::HashSet::new();
        for ch in &self.channels {
            if ch.name.is_empty() || ch.asset_id.is_empty() {
                bail!("channel name/asset_id must be non-empty");
            }
            if ch.scale == 0.0 {
                bail!("channel {}: scale must be non-zero", ch.name);
            }
            if !names.insert(ch.name.as_str()) {
                bail!("duplicate channel name: {}", ch.name);
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const BENCH_TOML: &str = r#"
        site_id = "a3-alpha-toronto"
        backend_ingest_url = "http://127.0.0.1:8080/api/telemetry/ingest/proto"
        poll_period_ms = 1000

        [device]
        host = "127.0.0.1"
        port = 1502
        unit_id = 1
        timeout_ms = 2000

        [[channels]]
        name = "dc_bus_d_voltage"
        asset_id = "dc_bus_d"
        kind = "dc_unipolar_voltage"
        register = 0
        scale = 0.1
        quality = "simulated"

        [[channels]]
        name = "utility_d_mv"
        asset_id = "utility_intake_d"
        kind = "ac_three_phase_voltage"
        register = 10
        scale = 1.0
        quality = "simulated"
    "#;

    #[test]
    fn parses_bench_profile() {
        let cfg = GatewayConfig::from_toml_str(BENCH_TOML).unwrap();
        assert_eq!(cfg.channels.len(), 2);
        assert_eq!(cfg.channels[0].kind, ChannelKind::DcUnipolarVoltage);
        assert_eq!(cfg.channels[1].kind.word_count(), 4);
        assert_eq!(cfg.channels[0].quality, QualityLabel::Simulated);
    }

    #[test]
    fn dc_channel_scales_to_si_volts() {
        let cfg = GatewayConfig::from_toml_str(BENCH_TOML).unwrap();
        // raw 8000 x 0.1 = 800.0 V on the unipolar bus
        let s = cfg.channels[0].to_si(&[8000]).unwrap();
        assert_eq!(s, SiSample::DcUnipolarVoltage { v_dc_bus_v: 800.0 });
    }

    #[test]
    fn ac_channel_yields_three_phases_plus_frequency() {
        let cfg = GatewayConfig::from_toml_str(BENCH_TOML).unwrap();
        let s = cfg.channels[1].to_si(&[35000, 35010, 34990, 6000]).unwrap();
        match s {
            SiSample::AcThreePhaseVoltage { v_ab_v, v_bc_v, v_ca_v, frequency_hz } => {
                assert_eq!(v_ab_v, 35000.0);
                assert_eq!(v_bc_v, 35010.0);
                assert_eq!(v_ca_v, 34990.0);
                assert!((frequency_hz - 60.0).abs() < 1e-9);
            }
            other => panic!("wrong sample kind: {other:?}"),
        }
    }

    #[test]
    fn word_count_mismatch_is_an_error() {
        let cfg = GatewayConfig::from_toml_str(BENCH_TOML).unwrap();
        assert!(cfg.channels[1].to_si(&[1, 2]).is_err());
    }

    #[test]
    fn duplicate_channel_names_rejected() {
        let dup = BENCH_TOML.replace("utility_d_mv", "dc_bus_d_voltage");
        assert!(GatewayConfig::from_toml_str(&dup).is_err());
    }
}
