//! Generated bindings for the canonical v1 telemetry schema.
//!
//! Source of truth: `backend/telemetry_proto/v1/telemetry.proto`
//! (READ-ONLY here; see build.rs). The vocabulary fence lives in the
//! generated `voltage_reading::Topology` oneof — `DcUnipolarVoltage`
//! structurally has no phase fields.

#[allow(clippy::all)]
pub mod v1 {
    include!(concat!(env!("OUT_DIR"), "/dcepms.telemetry.v1.rs"));
}
