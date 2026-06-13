//! Egress: canonical v1 envelopes -> backend over HTTP.
//!
//! Wire framing (documented contract, mirrored by the backend ingest
//! endpoint): the POST body is a sequence of envelopes, each preceded
//! by a 4-byte BIG-ENDIAN unsigned length of the protobuf-encoded
//! envelope that follows.
//!
//! ```text
//! [u32be len][envelope bytes][u32be len][envelope bytes]...
//! ```
//!
//! Content-Type: application/x-dcepms-telemetry-v1
//!
//! Transport is HTTP POST (NOT gRPC) by design: the canonical
//! telemetry.proto defines messages only — adding a `service` is a
//! schema change gated behind RFC + ADR. Length-prefix framing is
//! trivial to produce here and to parse with the existing Python v1
//! stubs backend-side.

use anyhow::{bail, Context, Result};
use prost::Message;

use crate::proto::v1;

pub const CONTENT_TYPE: &str = "application/x-dcepms-telemetry-v1";

/// Frame a batch of envelopes into one POST body.
pub fn frame_batch(envelopes: &[v1::TelemetryEnvelope]) -> Vec<u8> {
    let mut body = Vec::with_capacity(envelopes.len() * 96);
    for env in envelopes {
        let bytes = env.encode_to_vec();
        body.extend_from_slice(&(bytes.len() as u32).to_be_bytes());
        body.extend_from_slice(&bytes);
    }
    body
}

/// Parse a framed body back into envelopes (test + tooling symmetry;
/// the production parser lives backend-side in Python).
pub fn parse_batch(body: &[u8]) -> Result<Vec<v1::TelemetryEnvelope>> {
    let mut out = Vec::new();
    let mut at = 0usize;
    while at < body.len() {
        if at + 4 > body.len() {
            bail!("truncated length prefix at offset {at}");
        }
        let len = u32::from_be_bytes(body[at..at + 4].try_into().unwrap()) as usize;
        at += 4;
        if at + len > body.len() {
            bail!("truncated envelope at offset {at} (declared {len} bytes)");
        }
        out.push(
            v1::TelemetryEnvelope::decode(&body[at..at + len])
                .context("envelope decode failed")?,
        );
        at += len;
    }
    Ok(out)
}

pub struct EgressClient {
    http: reqwest::Client,
    url: String,
}

impl EgressClient {
    pub fn new(url: &str, timeout: std::time::Duration) -> Result<Self> {
        let http = reqwest::Client::builder()
            .timeout(timeout)
            .build()
            .context("egress http client build failed")?;
        Ok(Self { http, url: url.to_string() })
    }

    /// POST one framed batch. Returns the number of envelopes shipped.
    /// Errors are returned (not retried here) — the poll loop owns the
    /// retry/drop policy so a dead backend cannot stall field polling.
    pub async fn ship(&self, envelopes: &[v1::TelemetryEnvelope]) -> Result<usize> {
        if envelopes.is_empty() {
            return Ok(0);
        }
        let body = frame_batch(envelopes);
        let resp = self
            .http
            .post(&self.url)
            .header("content-type", CONTENT_TYPE)
            .body(body)
            .send()
            .await
            .context("egress POST failed")?;
        let status = resp.status();
        if !status.is_success() {
            let detail = resp.text().await.unwrap_or_default();
            bail!("backend ingest rejected batch: {status} {detail}");
        }
        Ok(envelopes.len())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::{ChannelConfig, ChannelKind, QualityLabel, SiSample};
    use crate::envelope::build_envelope;

    fn sample_envelopes() -> Vec<v1::TelemetryEnvelope> {
        let ch = ChannelConfig {
            name: "t".into(),
            asset_id: "dc_bus_d".into(),
            kind: ChannelKind::DcUnipolarVoltage,
            register: 0,
            scale: 0.1,
            offset: 0.0,
            quality: QualityLabel::Simulated,
            temp_location: None,
            coolant_loop: None,
            bus_segment: None,
        };
        (1..=3u64)
            .map(|seq| build_envelope(
                "a3-alpha-toronto", seq, &ch,
                &SiSample::DcUnipolarVoltage { v_dc_bus_v: 800.0 + seq as f64 },
            ))
            .collect()
    }

    #[test]
    fn frame_then_parse_roundtrips_batches() {
        let envs = sample_envelopes();
        let body = frame_batch(&envs);
        let back = parse_batch(&body).unwrap();
        assert_eq!(back.len(), 3);
        assert_eq!(back[0].sequence_number, 1);
        assert_eq!(back[2].site_id, "a3-alpha-toronto");
        assert_eq!(back, envs);
    }

    #[test]
    fn truncated_bodies_are_rejected_not_misparsed() {
        let body = frame_batch(&sample_envelopes());
        assert!(parse_batch(&body[..body.len() - 3]).is_err());
        assert!(parse_batch(&body[..2]).is_err());
    }

    #[test]
    fn empty_batch_frames_to_empty_body() {
        assert!(frame_batch(&[]).is_empty());
        assert!(parse_batch(&[]).unwrap().is_empty());
    }
}
