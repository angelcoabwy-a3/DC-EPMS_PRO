//! Compile the CANONICAL v1 telemetry schema into Rust types.
//!
//! The single source of truth is `backend/telemetry_proto/v1/telemetry.proto`
//! (operator-approved 2026-05-26; changes require RFC + ADR). This build
//! script consumes it READ-ONLY — the gateway must never fork the schema.
//! protoc ships vendored (protoc-bin-vendored) so the build has no system
//! dependency; google.protobuf.Timestamp maps to prost_types::Timestamp.

fn main() {
    let proto = "../../backend/telemetry_proto/v1/telemetry.proto";
    let include_root = "../../backend/telemetry_proto/v1";

    println!("cargo:rerun-if-changed={proto}");

    let protoc = protoc_bin_vendored::protoc_bin_path().expect("vendored protoc unavailable");
    let wkt_include = protoc_bin_vendored::include_path().expect("vendored WKT includes");
    // SAFETY: build scripts are single-threaded at this point; prost-build
    // reads PROTOC at compile_protos time.
    unsafe { std::env::set_var("PROTOC", protoc) };

    prost_build::Config::new()
        .compile_protos(&[proto], &[include_root, wkt_include.to_str().unwrap()])
        .expect("canonical telemetry.proto failed to compile — schema is operator-approved, fix the build, not the proto");
}
