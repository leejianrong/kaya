# kaya's MCP server: a thin adapter over kaya-client, run over stdio (mcp/README.md).
#
# Same rule as the root Dockerfile, for the same reason: every base pinned by DIGEST, never a tag
# — pandan's KAN-475, the mistake that card was written not to repeat and the reason KAN-573 exists
# in this repo at all. See ../Dockerfile's header for the full argument against a floating base;
# this file states only what is different about it.
#
#     `scripts/check-image-pins.sh` scans every Dockerfile under the repo, this one included, and
#     fails the build if a digest is ever dropped from here.
#
# There is no HTTP surface to expose and no registry this pushes to: an MCP host launches this
# image as a subprocess and talks to it over stdin/stdout (`src/kaya_mcp/__main__.py`'s
# `server.run()`), exactly the way it would launch a bare `kaya-mcp` console script. So this image
# is a local build only — `make mcp-image` / `scripts/mcp-image-build.sh` — never published, the
# same shape ../Dockerfile is today (`make image` / `make up` / `make k3d`, no publish workflow).
#
# Build with that script, not a bare `docker build`: the provenance labels below are only true if
# something computes them, same as ../Dockerfile.
#
#     docker buildx imagetools inspect python:3.12-slim | head -3
#     docker buildx imagetools inspect ghcr.io/astral-sh/uv:0.9.16 | head -3
#
# Reusing ../Dockerfile's exact pins rather than re-resolving: they name the same two bases this
# repo already trusts, and re-resolving them here would just be a second way to spell the same
# digest.
ARG PYTHON_BASE=python:3.12-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36
ARG UV_BASE=ghcr.io/astral-sh/uv:0.9.16@sha256:ae9ff79d095a61faf534a882ad6378e8159d2ce322691153d68d2afac7422840


# --- 1. uv, pinned like everything else ------------------------------------------------------------
FROM ${UV_BASE} AS uv


# --- 2. dependencies --------------------------------------------------------------------------------
# mcp/pyproject.toml's [tool.uv.sources] names kaya-client by a *relative* path, `../kaya-client`
# (ADR 0004: adapters depend on the client, never the reverse), so it has to sit at that path in
# this stage's filesystem — and it needs its own source, not just its manifest: a path dependency
# is a regular dependency uv builds a wheel for, so it is not the "current project"
# `--no-install-project` skips below. It is copied in before the first sync for exactly that
# reason, where the root Dockerfile's equivalent (`backend/app`) only has to arrive before the
# *second* one.
FROM ${PYTHON_BASE} AS deps

COPY --from=uv /uv /usr/local/bin/uv

# UV_PYTHON_DOWNLOADS=never: see ../Dockerfile's identical line for why — use the interpreter this
# base ships, so the venv copied into the runtime stage matches exactly what will run it.
ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/kaya-mcp/venv

WORKDIR /src
COPY kaya-client/pyproject.toml kaya-client/README.md ./kaya-client/
COPY kaya-client/src ./kaya-client/src
COPY mcp/pyproject.toml mcp/uv.lock mcp/README.md ./mcp/

WORKDIR /src/mcp

# Two syncs, the same layer boundary as the root Dockerfile's `deps` stage: this one resolves and
# installs *dependencies* — kaya-client included, per the note above — and is invalidated only by
# mcp/uv.lock or a change under kaya-client/, so editing a tool body does not re-resolve `mcp` the
# SDK or httpx.
#
# --frozen: fail rather than silently re-resolve if uv.lock disagrees with pyproject.toml.
# --no-editable: kaya-client's own pyproject.toml marks it `editable = true` for local development
#   (`uv sync` from a checkout), but an editable install is a reference back to this build stage's
#   /src, which will not exist in the runtime image. Force a real, non-editable install here, the
#   same correction ../Dockerfile's `backend` stage makes for its own project.
RUN uv sync --frozen --no-dev --no-install-project --no-editable

COPY mcp/src ./src
# And this one installs kaya-mcp itself, non-editable, so `kaya_mcp` lands in site-packages **with
# its dist-info** — the `kaya-mcp` console script `[project.scripts]` declares comes from that
# metadata, and it is the one thing the runtime stage's ENTRYPOINT depends on existing.
RUN uv sync --frozen --no-dev --no-editable


# --- 3. the runtime ------------------------------------------------------------------------------
FROM ${PYTHON_BASE} AS runtime

ARG PYTHON_BASE
ARG VERSION=unknown
ARG GIT_REVISION=unknown
ARG BUILD_DATE=unknown

# Provenance, checkable rather than decorative — see ../Dockerfile's LABEL block for what each key
# means; unchanged here except for the two identifying the package.
LABEL org.opencontainers.image.title="kaya-mcp" \
      org.opencontainers.image.description="kaya's MCP server -- a thin adapter over kaya-client" \
      org.opencontainers.image.source="https://github.com/leejianrong/kaya" \
      org.opencontainers.image.url="https://github.com/leejianrong/kaya" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.vendor="kayatoast" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${GIT_REVISION}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.base.name="${PYTHON_BASE}"

ENV PATH=/opt/kaya-mcp/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# A fixed numeric uid for the same reason ../Dockerfile picks one: nothing here asserts
# `runAsUser`, but a name-only USER is still one more thing a caller would have to look up rather
# than read off this file.
RUN groupadd --system --gid 10001 kaya-mcp \
 && useradd --system --uid 10001 --gid kaya-mcp --home-dir /srv/kaya-mcp --shell /usr/sbin/nologin kaya-mcp

WORKDIR /srv/kaya-mcp

# The venv carries the application: `kaya_mcp` and `kaya_client` are installed into it, not copied
# alongside it — same reasoning as ../Dockerfile's runtime stage.
COPY --from=deps /opt/kaya-mcp/venv /opt/kaya-mcp/venv

USER 10001:10001

# No EXPOSE and no HEALTHCHECK: there is no HTTP surface here, only stdin/stdout, and a container
# HEALTHCHECK has no protocol-free way to ask a stdio JSON-RPC server "are you alive" without
# itself becoming a client of the very protocol under test. `scripts/mcp-image-build.sh` proves
# liveness after every build instead, by actually speaking `initialize` + `tools/list` to a
# container it starts and tears down — a real proof once per build, rather than a probe that would
# either always pass (an unconditional process check) or need its own MCP client wired into a
# shell HEALTHCHECK.
#
# KAYA_API_URL / KAYA_TOKEN are read at runtime from the environment (PLAN §Config's tier one,
# `kaya_client.config`) — an MCP host launching this as a subprocess exports the `env` block it was
# configured with, the same as it would for a bare `kaya-mcp` console script.
ENTRYPOINT ["kaya-mcp"]
