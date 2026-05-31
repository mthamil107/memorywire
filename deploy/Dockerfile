# syntax=docker/dockerfile:1.7
#
# Multi-stage build for the memwire Governance UI hosted demo.
#
# Stage 1 (builder): pulls the protocol + UI sources, resolves the locked
# dependency tree with uv, and builds both wheels.
# Stage 2 (runtime): a slim Python image with only the runtime deps + the
# two wheels installed, running as a non-root uid.
#
# Built from the repository root:
#
#     docker build -f deploy/Dockerfile -t memwire-ui:test .
#
# Target image size: <250 MB. Achieved by using python:3.13-slim, skipping
# dev deps (no pytest / ruff / mypy), and avoiding sentence-transformers
# (the UI never embeds, ensure_schema() injects a no-op embedder).

# ---------------------------------------------------------------------------
# Stage 1 â€” builder
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Install uv via the official standalone installer (faster + reproducible
# than pip-installing it). Pinned at copy time via the lockfile downstream.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates build-essential \
    && rm -rf /var/lib/apt/lists/* \
    && curl -LsSf https://astral.sh/uv/install.sh | sh \
    && mv /root/.local/bin/uv /usr/local/bin/uv

WORKDIR /build

# Copy only the files needed to resolve + build wheels. Source files come
# next; this layering lets Docker cache the dep-install layer across
# unrelated source edits.
COPY pyproject.toml uv.lock README.md LICENSE NOTICE ./
COPY src/ ./src/
COPY ui/ ./ui/

# Resolve + install the protocol + UI deps into a single venv inside /build.
# --frozen guarantees the lockfile is the source of truth; --no-dev skips
# pytest/ruff/mypy; the ui extra pulls in starlette / uvicorn / jinja2 /
# python-multipart.
#
# We intentionally do NOT install the [sqlite-vec] extra's
# sentence-transformers component â€” the UI never embeds (ensure_schema
# passes a no-op embedder). To keep the image under 250 MB we install
# only the sqlite-vec native module itself as an explicit additional
# package rather than via the heavyweight extra.
ENV VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:${PATH}
RUN uv venv /opt/venv \
    && uv export --frozen --no-dev --extra ui --no-hashes -o /tmp/requirements.txt \
    && uv pip install --python /opt/venv/bin/python --no-cache --requirement /tmp/requirements.txt \
    && uv pip install --python /opt/venv/bin/python --no-cache sqlite-vec \
    && uv pip install --python /opt/venv/bin/python --no-cache --no-deps ./ \
    && uv pip install --python /opt/venv/bin/python --no-cache --no-deps ./ui

# ---------------------------------------------------------------------------
# Stage 2 â€” runtime
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}" \
    MEMWIRE_UI_HOST=0.0.0.0 \
    MEMWIRE_UI_PORT=8765 \
    MEMWIRE_UI_AGENT_ID=demo-agent \
    MEMWIRE_UI_DB_PATH=/app/data/demo.db

# Install only the OS-level runtime essentials. curl is kept for the
# Docker HEALTHCHECK probe.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1001 memwire \
    && useradd  --system --uid 1001 --gid 1001 --home /app --shell /usr/sbin/nologin memwire \
    && mkdir -p /app/data \
    && chown -R 1001:1001 /app

# Copy the resolved venv (protocol + UI wheels + their runtime deps) from
# the builder. The shebangs in /opt/venv/bin reference /opt/venv/bin/python
# which we also bring across implicitly via the venv layout.
COPY --from=builder /opt/venv /opt/venv

# Boot shim that idempotently seeds the demo DB before exec()ing into the
# real entrypoint. Owned by the unprivileged uid so the runtime user can
# read it.
COPY --chown=1001:1001 deploy/seed-on-boot.py /app/deploy/seed-on-boot.py

USER 1001:1001
WORKDIR /app

EXPOSE 8765

# The UI does not ship a dedicated /healthz endpoint at v0 (flagged for
# v0.2 â€” see deploy/README.md). The Pending Approvals page at GET / is
# the cheapest healthcheck we have: it touches the DB, exercises the
# CSRF middleware, and renders a template.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl --fail --silent --show-error --max-time 4 \
        "http://127.0.0.1:${MEMWIRE_UI_PORT}/" > /dev/null || exit 1

# seed-on-boot.py ensures /app/data/demo.db exists with the seeded fixture
# content, then execs `python -m memwire_ui` to hand control over to the real
# entrypoint. Running it as PID 1 means signals (SIGTERM from Fly.io's
# rolling deploy) reach uvicorn directly after exec().
CMD ["python", "/app/deploy/seed-on-boot.py"]
