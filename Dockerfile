# kaya's one deployable artifact: the built SPA and the API, from a single origin (ADR 0010).
#
# Build it with `scripts/image-build.sh`, not with a bare `docker build` — the provenance labels
# below are only true if something computes them, and that script is the something.
#
# ---------------------------------------------------------------------------------------------
# Every base is pinned by DIGEST, and that is this file's reason to be careful rather than a
# stylistic preference.
#
# A tag is a mutable pointer. `FROM python:3.12-slim` resolves to a different image next Tuesday,
# so `org.opencontainers.image.revision` records the commit of *kaya's* source while saying
# nothing whatsoever about the other 99% of the bytes in the artifact — and a provenance label
# that is silently wrong is worse than no label, because it is believed. Pandan's image floats on
# `uv:latest` and `python:3.12-slim` underneath its own labels, which is its KAN-475 and the
# mistake this card was written not to repeat.
#
# `scripts/check-image-pins.sh` fails the build if a digest is ever dropped from here, from
# `docker-compose.yml`, or from `deploy/k8s/base/`.
#
# To bump a base: resolve the new digest and paste it here, in the same commit as the tag change.
#
#     docker buildx imagetools inspect python:3.12-slim | head -3
#
# The tag in front of the `@` is documentation for a human — Docker ignores it entirely and
# resolves the digest — so keeping the two in agreement is a discipline, not a mechanism.
# ---------------------------------------------------------------------------------------------

ARG PYTHON_BASE=python:3.12-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36
ARG NODE_BASE=node:20-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0
ARG UV_BASE=ghcr.io/astral-sh/uv:0.9.16@sha256:ae9ff79d095a61faf534a882ad6378e8159d2ce322691153d68d2afac7422840


# --- 1. the SPA ---------------------------------------------------------------------------------
# `npm ci`, not `npm install`: the lockfile is the input, and a build that is free to resolve a
# newer dependency is a build whose output nobody can reproduce.
FROM ${NODE_BASE} AS spa

WORKDIR /spa
# The manifest and the lockfile alone, so the dependency layer is cached against every change to
# the SPA's own source.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


# --- 2. uv, pinned like everything else ----------------------------------------------------------
# A stage rather than a `COPY --from=<ref>`, because a stage name is resolved by BuildKit at graph
# time and an inline image reference in a COPY is not a place a digest is easy to keep honest.
FROM ${UV_BASE} AS uv


# --- 3. the backend's dependencies ---------------------------------------------------------------
FROM ${PYTHON_BASE} AS deps

COPY --from=uv /uv /usr/local/bin/uv

# UV_PYTHON_DOWNLOADS=never: use the interpreter this base image ships, so the venv copied into the
# runtime stage is built against exactly the Python that will run it. Left on `auto`, uv would
# happily fetch a *different* 3.12 and the pinned base would stop meaning anything.
ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/kaya/venv

WORKDIR /src
# README.md is here because pyproject.toml names it as the project readme; without it uv refuses to
# read the metadata at all.
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./

# Two syncs, and the split is the layer boundary: this one resolves and installs *dependencies*
# and is invalidated by uv.lock alone, so editing a route does not re-download SQLAlchemy.
#
# --frozen: fail if uv.lock disagrees with pyproject.toml rather than silently re-resolving, the
#   same promise `npm ci` makes above and the same one CI makes.
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/app ./app
# And this one installs kaya itself, non-editable, so `app` lands in site-packages **with its
# dist-info**. That metadata is not bookkeeping: `app/__init__.py` reads the version out of it with
# `importlib.metadata`, and without it `/health` and the OpenAPI document both report `0.0.0` while
# `org.opencontainers.image.version` on this very image says `0.1.0`. An image whose labels
# disagree with the thing running inside it is the exact failure this card exists to avoid, so the
# runtime stage below copies the venv and nothing else — one copy of the code, and it is the
# installed one.
RUN uv sync --frozen --no-dev --no-editable


# --- 4. the runtime ------------------------------------------------------------------------------
FROM ${PYTHON_BASE} AS runtime

# Re-declared: a global ARG is in scope for `FROM` lines, but a stage has to ask for it by name
# before it can be interpolated into a LABEL.
ARG PYTHON_BASE
ARG VERSION=unknown
ARG GIT_REVISION=unknown
ARG BUILD_DATE=unknown

# Provenance, and the claims are checkable rather than decorative:
#   .revision  — the exact commit, suffixed `-dirty` by scripts/image-build.sh when the tree it
#                built from had uncommitted changes. A sha that does not describe the bytes is
#                the failure this card names, so the script would rather be embarrassing.
#   .created   — the moment of the build, in RFC 3339, from the build machine's clock.
#   .base.name — the fully pinned base, digest included. `docker inspect` therefore answers "what
#                is underneath this?" without anyone having to find this file.
LABEL org.opencontainers.image.title="kaya" \
      org.opencontainers.image.description="Markdown notes, API-first and agent-drivable" \
      org.opencontainers.image.source="https://github.com/leejianrong/kaya" \
      org.opencontainers.image.url="https://github.com/leejianrong/kaya" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.vendor="kayatoast" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${GIT_REVISION}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.base.name="${PYTHON_BASE}"

ENV PATH=/opt/kaya/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    KAYA_SPA_DIST=/srv/kaya/static

# A fixed numeric uid, because the Kubernetes manifests assert `runAsUser: 10001` and a
# `runAsNonRoot` pod with a name-only USER cannot be validated by the kubelet before it starts.
RUN groupadd --system --gid 10001 kaya \
 && useradd --system --uid 10001 --gid kaya --home-dir /srv/kaya --shell /usr/sbin/nologin kaya

WORKDIR /srv/kaya

# The venv carries the application: `app` is installed into it, not copied alongside it.
COPY --from=deps /opt/kaya/venv /opt/kaya/venv

# Alembic's scripts are data rather than code and are not part of the wheel, so they come across as
# files. `alembic.ini` sets `prepend_sys_path = .`, which is why WORKDIR matters here.
COPY backend/alembic.ini ./alembic.ini
COPY backend/alembic ./alembic

# The SPA, at the path KAYA_SPA_DIST names above. Beside the venv rather than inside the installed
# package: a site-packages path contains the interpreter's minor version, and pinning a base image
# is not a good enough reason to write `python3.12` into a COPY destination.
#
# `app.spa` guesses no location and falls back to none, so an image built without this line serves
# the API alone — which is a visibly missing SPA rather than a silently stale one.
COPY --from=spa /spa/dist ./static

USER 10001:10001
EXPOSE 8000

# Python rather than curl: `python:3.12-slim` has no curl, and installing one to answer a health
# check adds a package, a CVE feed and an apt layer for a request the interpreter can already make.
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=6 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]

# No migration here, deliberately. `alembic upgrade head` is a separate invocation of this same
# image — an initContainer in `deploy/k8s/`, a one-shot service in `docker-compose.yml` — so that
# "the schema is current" is a visible step with its own exit code, rather than something the web
# server does on the way up and swallows.
#
# Proxy headers are left at uvicorn's default. Under an Ingress that is not yet right, and ADR 0010
# §Consequences names this exact class of bug as one the MVP knowingly leaves unproven until the
# homelab. Nothing kaya returns today is an absolute URL, so it does not bite yet.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
