# syntax=docker/dockerfile:1.7
# =============================================================================
# DC-EPMS PRO - Dockerfile v2 (Batch 2 — bloat fix per Decision GO-OPTION-C)
#
# v2 changes:
#   1. torch installed FIRST from PyTorch CPU-only index
#      (https://download.pytorch.org/whl/cpu) to prevent pip from auto-pulling
#      cuda-toolkit (~3.5 GB). Decision rationale 2026-05-06.
#   2. Aggressive cleanup post-install: strip .pyc, __pycache__, .so debug
#      symbols, pip cache.
#   3. Target image size: ~2 GB (down from 8.85 GB v1).
#   4. Documents architectural choice: runtime is CPU-only by V9 design.
#
# Build:
#   docker build --target runtime -t dc-epms-pro:latest .
#   docker build --build-arg EXTRAS="db,rag,obs,ai" -t dc-epms-pro:dual-ai .
#
# Architecture stays: amd64 only, multi-stage builder + runtime, non-root user.
# =============================================================================

ARG PYTHON_VERSION=3.12.10
ARG EXTRAS="db,rag,obs"

# =============================================================================
# Stage 1: BUILDER
# =============================================================================
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

ARG EXTRAS
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        g++ \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build

COPY pyproject.toml ./

RUN mkdir -p backend && \
    touch backend/__init__.py && \
    echo "# placeholder" > README.md

# ─── CRITICAL: Install torch CPU-only FIRST, BEFORE any other dep ───────────
# This forces pip's resolver to satisfy "torch" requirement from the
# CPU-only wheel index. Subsequent dependencies (sentence-transformers,
# transformers) will see torch is already installed and not try to pull
# the default GPU torch. Saves ~3.5 GB.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip setuptools wheel && \
    pip install --index-url https://download.pytorch.org/whl/cpu \
        torch==2.5.1+cpu \
        torchvision==0.20.1+cpu

# Install rest of dependencies. --extra-index-url ensures torch can still
# be resolved from CPU index if any transitive dep tries to upgrade it.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --extra-index-url https://download.pytorch.org/whl/cpu \
        -e ".[${EXTRAS}]"

# ─── Aggressive cleanup post-install ────────────────────────────────────────
# Removes ~150-300 MB of bytecode caches, debug symbols, test files,
# and pip metadata that's not needed at runtime.
RUN find /opt/venv -type f -name "*.pyc" -delete && \
    find /opt/venv -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true && \
    find /opt/venv -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true && \
    find /opt/venv -type d -name "test" -exec rm -rf {} + 2>/dev/null || true && \
    find /opt/venv -type f -name "*.dist-info" -path "*/RECORD" -delete && \
    find /opt/venv -type f -name "*.so" -exec strip --strip-unneeded {} \; 2>/dev/null || true && \
    rm -rf /root/.cache/pip /tmp/* /var/tmp/*

# =============================================================================
# Stage 2: RUNTIME
# =============================================================================
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

ARG EXTRAS
LABEL org.opencontainers.image.title="DC-EPMS PRO" \
      org.opencontainers.image.description="AI-native edge ops platform for Tier IV AI factories - A3-Alpha 67MW simulator" \
      org.opencontainers.image.vendor="a3semi (A-Cubed Semiconductor Systems Inc.)" \
      org.opencontainers.image.source="local-only-no-github" \
      org.opencontainers.image.licenses="Proprietary" \
      org.opencontainers.image.authors="Wilmer Y. Angel Beltran" \
      a3semi.facility="A3-Alpha Toronto Area" \
      a3semi.scale="67 MW AI factory hyperscale" \
      a3semi.compliance="IEC 62443 zone-and-conduit segregation" \
      a3semi.extras="${EXTRAS}" \
      a3semi.cpu_only="true (V9 Decision: GPU usage delegated to host LM Studio)"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    PYTHONFAULTHANDLER=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8080 \
    UVICORN_HOST=0.0.0.0 \
    UVICORN_PORT=8080 \
    UVICORN_WORKERS=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
        tini \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

ARG APP_UID=10001
ARG APP_GID=10001
RUN groupadd --system --gid ${APP_GID} epms && \
    useradd --system --uid ${APP_UID} --gid epms --shell /usr/sbin/nologin --create-home epms

COPY --from=builder --chown=epms:epms /opt/venv /opt/venv

WORKDIR /app

COPY --chown=epms:epms backend/ ./backend/
COPY --chown=epms:epms config/ ./config/
COPY --chown=epms:epms frontend/ ./frontend/
COPY --chown=epms:epms pyproject.toml ./

RUN mkdir -p /app/data /app/logs && \
    chown -R epms:epms /app

USER epms

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=60s \
    CMD curl --fail --silent --max-time 4 http://localhost:8080/api/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]

CMD ["uvicorn", "backend.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8080", \
     "--workers", "1", \
     "--access-log", \
     "--log-level", "info"]
