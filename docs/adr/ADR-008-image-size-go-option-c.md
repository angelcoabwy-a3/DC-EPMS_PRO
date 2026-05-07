# ADR-008: GO-OPTION-C — Accept 1.54 GB CPU-Only Container Image (Phase 1)

* Status: ACCEPTED
* Date: 2026-05-06 (decision taken during Batch 2 DevOps Quick Wins, formally documented in Batch 3)
* Decision-maker: Wilmer Y. Angel Beltran (CET, Lead Architect a3semi)
* Sprint: DevOps Quick Wins Batch 2
* MADR template: https://adr.github.io/madr/

## Context

During DevOps Quick Wins Batch 2, the initial Docker build of `dc-epms-pro` produced an **8.85 GB image**. Investigation revealed two cumulative causes:

1. **Transitive CUDA toolkit pull**: `sentence-transformers` 3.2.1 declares `torch>=2.1.0` as a dependency. The default PyPI resolution selects the GPU build of torch which transitively requires CUDA libraries (cuDNN, cuBLAS, NCCL) totaling ~3.5 GB. The project's runtime is CPU-only by deployment intent (RTX 3060 6 GB cannot host the full inference stack anyway, and the production target is edge-local without GPU).

2. **Bloated venv + dev artifacts**: the build context included pytest caches, `.pyc`, dev tooling (mypy, ruff, black, pre-commit), Jupyter caches, and uncompressed .so debug symbols inherited from PyPI wheels.

A target of `<1.2 GB` was hypothesized as "ideal" before the rebuild. The rebuild achieved **1.54 GB** — better than the original 8.85 GB by 83 percent, but 28 percent above the hypothetical target.

The decision presented in Batch 2 was: ship 1.54 GB now, OR push for further reduction (Distroless final stage, Alpine base with musl libc, externalize the RAG stack to a separate container).

## Decision

**Accept 1.54 GB as the Phase 1 image size**. Defer Distroless or Alpine migration to Phase 3.

Specifically:

- The Dockerfile uses Debian-slim (`python:3.12-slim` based) rather than Alpine. Reasoning: glibc compatibility for sentence-transformers and FAISS is well-tested; musl libc has known edge cases for ML wheels even in CPU mode.
- The runtime stage runs as non-root user `epms` (uid 10001) per IEC 62443 segregation.
- `tini` is the PID 1 for proper signal handling and zombie reaping.
- torch is installed from the **PyTorch CPU index** (`https://download.pytorch.org/whl/cpu`) explicitly, preventing the GPU resolution bug.
- Aggressive cleanup: `__pycache__`, `*.pyc`, test directories, .so debug symbols are stripped post-install.
- The RAG stack (`sentence-transformers`, `faiss-cpu`, `chromadb`) stays inside the container, preserving the **edge-first autonomy** that the Hyperscale Override Protocol scenario demands.

## Consequences

### Positive

- **Edge-first autonomy preserved**. The 1.4 GW Federated Fleet hyperscale scenario assumes uplink degradation; an edge node must be able to run RAG queries and physics validation locally without phoning home. Externalizing the RAG stack would break this property.
- **Healthcheck cadence achievable**. Container starts in 10 seconds in the Batch 2 validation, well within the 60-second `start_period` aligned to Tier IV monitoring.
- **CPU-only is appropriate for the deployment target**. The RTX 3060 6 GB is the development machine; the production edge appliance is expected to be CPU-only with optional GPU acceleration via cloud-burst (out of V9 scope).
- **Honest engineering**. 1.54 GB is genuinely production-grade for a Python + ML stack. Public reference images for similar workloads (e.g., HuggingFace inference servers, NVIDIA Triton CPU edition) are in the same range or larger.
- **Reproducible build**. The torch CPU index pin in `Dockerfile` makes the image size deterministic across rebuilds.

### Negative / Trade-offs

- **Image distribution bandwidth**. At 1.54 GB on disk / 338 MB compressed, pushing to a registry across slow uplinks is non-trivial. Mitigation: use registry layer caching; the base layers (Debian, Python, torch CPU) are stable across rebuilds and only the application layer changes.
- **Cold start on a fresh node**. First pull is ~338 MB. Acceptable for a daemon that is started rarely. Not appropriate for ephemeral Lambda-style workloads (not a target).
- **Marginally above the hypothetical 1.2 GB target**. The remaining ~340 MB delta is genuinely consumed by the ML stack (torch CPU + sentence-transformers model + FAISS + ChromaDB embeddings). Compressing further requires architectural changes (RAG externalization), not packaging tricks.
- **Distroless or Alpine migration deferred to Phase 3**. If the project ships to bandwidth-constrained edge sites, this becomes a higher priority.

## Alternatives Considered and Rejected

- **Option A: Aggressive shrinking now (target <1.2 GB)**. Approaches considered: Alpine base (rejected per glibc concern above), Distroless final stage (rejected because debugging the running container becomes very difficult — `kubectl exec` for shell debugging is impossible without a shell layer; this was deemed a Phase 1 operability risk worse than the size cost), externalize RAG (rejected per edge-first autonomy).
- **Option B: GPU image variant**. Build a GPU-enabled tag for environments with CUDA available. Rejected for V9: complicates the image matrix; the project does not yet exercise GPU paths; GPU support belongs to V10 if/when the inference stack moves beyond gemma-4-e2b-it.
- **Option C (CHOSEN): Accept 1.54 GB CPU-only Phase 1, defer further shrinking to Phase 3**. Pragmatic, ships now, preserves all critical V9 properties.

## References

- `Dockerfile` — multi-stage build with CPU-only torch index pin
- `.dockerignore` — excludes ~3 GB of build context bloat
- `docker-compose.yml` — healthcheck configuration aligned to Tier IV cadence
- `validate_batch2.ps1` — 8-layer validator confirming image size 1.54 GB and all functional layers green
- DC-EPMS-009 (CHANGELOG.md) — bug entry registering the size variance against the hypothetical 1.2 GB target

## Verification

- Image size: `docker images dc-epms-pro:latest --format "{{.Size}}"` returns `1.54GB` (Batch 2 closure 2026-05-06).
- 8/8 validation layers pass in `validate_batch2.ps1`.
- 103 tests pass in 6.67 seconds aggregate (no regression from Batch 1 baseline).
- Container healthy in 10 seconds, well under 60-second `start_period`.
- `/metrics` endpoint serves Prometheus exposition format with `dc_epms_*` namespace, HTTP 200.

## Future Work (Phase 3 candidates)

- **Migration to Distroless final stage** — would shave ~80 to 120 MB and reduce attack surface. Operability impact: shell-less debugging requires `kubectl debug` or sidecar containers.
- **Alpine base with musl libc** — would require validating sentence-transformers + FAISS + ChromaDB for musl compatibility. Empirical risk, not theoretical; needs a spike branch.
- **Externalize RAG stack to companion container** — breaks edge-first autonomy as currently defined; would only be reconsidered if the deployment model changes (e.g., a tier of "thick edge" nodes that hold RAG and a tier of "thin edge" nodes that consume it).
- **Multi-arch builds (amd64 + arm64)** for Graviton or Ampere edge appliances. Useful if Microsoft CO+I deploys ARM-based edge servers.
