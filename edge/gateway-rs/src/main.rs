//! dc-epms-gateway — A3 edge gateway (Rust).
//!
//! Scaffold skeleton (Option 2, 2026-05-28). This binary is the field-edge
//! ingestion + feature-extraction front end for DC-EPMS PRO. It is built and
//! link-verified locally on `x86_64-pc-windows-msvc` (rustc 1.96.0).
//!
//! Responsibilities (target architecture — implemented incrementally):
//!   1. Modbus ingestion from field devices          -> `rmodbus` (phase 2).
//!   2. Feature extraction into the A3 feature vector -> `nalgebra` (below).
//!   3. Telemetry egress over gRPC                    -> `tonic` (phase 2),
//!      bound to the EXISTING canonical wire contract
//!      `backend/telemetry_proto/v1/telemetry.proto`. The gateway MUST NOT
//!      fork or redefine that schema — the vocabulary fence (AC trifasico
//!      upstream of the MV rectifier vs. 800 VDC unipolar TN-S downstream)
//!      is owned by the .proto and only referenced here.
//!
//! HONEST SCOPE: `rmodbus` and `tonic` are declared dependencies but are not
//! yet wired — that work depends on (a) the A3 spec landing in
//! `edge/CLAUDE.md` and (b) the proto-fence task. They build clean as unused
//! deps. The feature-vector SEMANTICS (what each of the 6 components means)
//! are intentionally left undefined here: defining them without the A3 spec
//! would violate the project's Grounding Forzado rule.

use nalgebra::Vector6;

/// The A3 edge feature vector: a fixed 6-component real vector.
///
/// The PHYSICAL MEANING of each component is PENDING the A3 manifest
/// (`edge/CLAUDE.md`, to be authored). Until that spec is grounded, this is a
/// neutral 6-D container only — no component is claimed to represent any
/// specific physical quantity.
pub type FeatureVector = Vector6<f64>;

/// Construct a zeroed feature vector. Placeholder until the A3 extraction
/// pipeline (Modbus -> features) is specified and wired.
fn empty_feature_vector() -> FeatureVector {
    FeatureVector::zeros()
}

#[tokio::main]
async fn main() {
    // Minimal, dependency-free boot banner. Structured logging (tracing) is
    // wired alongside the gRPC egress in phase 2.
    println!("[edge/gateway-rs] dc-epms-gateway boot — scaffold skeleton");
    println!("[edge/gateway-rs] tokio runtime: online");

    let features = empty_feature_vector();
    println!(
        "[edge/gateway-rs] A3 feature vector dim={} (semantics PENDING A3 spec)",
        features.len()
    );

    println!("[edge/gateway-rs] modbus ingestion: NOT wired (phase 2, rmodbus)");
    println!("[edge/gateway-rs] gRPC egress:      NOT wired (phase 2, tonic + v1 proto)");
    println!("[edge/gateway-rs] scaffold OK — exiting");
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
