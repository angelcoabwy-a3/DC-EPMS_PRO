//! dc-epms-gateway — A3 edge gateway library (Rust).
//!
//! Phase 2 (2026-06-12): real Modbus TCP ingestion. The crate is split
//! into a library so the gateway binary, the bench `modbus-sim` binary
//! and the integration tests share one implementation:
//!
//!   - [`config`]  — `gateway.toml` schema: device endpoint + the
//!     register map (register -> scale -> strict-SI value -> v1 payload
//!     kind). The vocabulary fence starts HERE: a channel's `kind`
//!     decides which side of the `VoltageReading.oneof topology` it can
//!     ever reach — a `dc_unipolar_voltage` channel cannot produce
//!     phase fields by construction.
//!   - [`modbus`]  — async Modbus TCP client (rmodbus frame layer over
//!     tokio sockets; rmodbus is sans-io, so the same frames serve a
//!     bench sim or a real PLC unchanged).
//!   - [`sim`]     — bench Modbus TCP SERVER. Real protocol on a real
//!     socket; only the register VALUES are synthetic. Envelopes built
//!     from this profile are marked QUALITY_SIMULATED (honest scope) —
//!     pointing the gateway at a real PLC drops the override.
//!
//! Egress to the backend (v1 proto over HTTP) is Batch B. gRPC/tonic
//! was REMOVED from the dependency set: the canonical
//! `backend/telemetry_proto/v1/telemetry.proto` defines messages only —
//! no `service` — and adding one is a schema change gated behind
//! RFC + ADR per project policy. HTTP POST of the canonical envelopes
//! does not touch the schema.

pub mod config;
pub mod modbus;
pub mod sim;

use nalgebra::Vector6;

/// The A3 edge feature vector: a fixed 6-component real vector.
///
/// The PHYSICAL MEANING of each component is PENDING the A3 manifest
/// (`edge/CLAUDE.md`, to be authored). Until that spec is grounded,
/// this is a neutral 6-D container only — no component is claimed to
/// represent any specific physical quantity.
pub type FeatureVector = Vector6<f64>;

/// Construct a zeroed feature vector. Placeholder until the A3
/// extraction pipeline (Modbus -> features) is specified and wired.
pub fn empty_feature_vector() -> FeatureVector {
    FeatureVector::zeros()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn feature_vector_has_six_components() {
        assert_eq!(empty_feature_vector().len(), 6);
    }

    #[test]
    fn feature_vector_starts_zeroed() {
        assert!(empty_feature_vector().iter().all(|&x| x == 0.0));
    }
}
