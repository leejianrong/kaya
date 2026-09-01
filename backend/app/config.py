"""Settings, resolved from the environment.

Per PLAN §Implementation decisions the app-level keys carry a ``KAYA_`` prefix.
``DATABASE_URL`` is deliberately unprefixed: it is the name Alembic, docker-compose and the
integration fixtures already use, and inventing a second spelling for it is how a test ends up
pointed at the wrong database.

Kaya holds no long-lived credential of its own, so nothing in here is a secret. It forwards the
caller's bearer upstream (ADR 0002); ``KAYA_PANDAN_URL`` is configuration.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DATABASE_URL = "postgresql+psycopg://kaya:kaya@localhost:5432/kaya"



class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(
        default=DEFAULT_DATABASE_URL,
        validation_alias="DATABASE_URL",
    )
    """SQLAlchemy URL. The ``+psycopg`` driver is psycopg v3 and is not interchangeable with
    ``+psycopg2``; ADR 0001 pins v3."""

    pandan_url: str = Field(
        default="https://simple-kanban-jian.fly.dev",
        validation_alias="KAYA_PANDAN_URL",
    )
    """Origin of the pandan deployment that resolves principals (ADR 0002).

    Read by ``app.auth`` to build the ``GET /api/v1/me`` URL. It is configuration, not a secret —
    it appears verbatim in the `503` body so a caller can see *which* upstream is down."""

    pandan_connect_timeout_seconds: float = Field(
        default=5.0,
        validation_alias="KAYA_PANDAN_CONNECT_TIMEOUT_SECONDS",
    )
    """How long kaya will wait to *reach* pandan: DNS, the TCP handshake, the TLS handshake.

    Short, because this phase says whether pandan's front door is answering, and that question does
    not get slower when the app behind the door is asleep — KAN-666 measured it (see the read budget
    below). A dead upstream fails inside this budget, so Q9's `503` still arrives promptly instead
    of a caller waiting out a read budget for a host that was never going to answer."""

    pandan_read_timeout_seconds: float = Field(
        default=30.0,
        validation_alias="KAYA_PANDAN_READ_TIMEOUT_SECONDS",
    )
    """How long kaya will wait for pandan's *answer* once the request is on the wire.

    Long, because pandan runs `min_machines_running = 0` and a cold start is a real wait rather than
    a fault. KAN-539 measured cold misses at 11–23 s against the single 10 s deadline these two
    fields replace, which is why a valid PAT used to get a `503`.

    **The two numbers exist separately because one number could not be right for both.** A single
    deadline conflates "pandan is down" with "pandan is asleep": short enough to report an outage
    promptly is too short to let a wake-up finish, and long enough for a wake-up makes an outage
    take half a minute to report. Split, each phase gets the deadline its own failure deserves.

    It is still *bounded*, and 30 s is not free: a sync route holds its Postgres session for the
    whole request (ADR 0001), so a long upstream call is a held connection. What makes it affordable
    is `app.auth.single_flight` — concurrent misses on one token become one call and one held
    worker, not forty. Raise this without that and ADR 0003's rule is broken by resource
    exhaustion."""

    principal_cache_ttl_seconds: float = Field(
        default=60.0,
        validation_alias="KAYA_PRINCIPAL_CACHE_TTL_SECONDS",
    )
    """How long a resolved principal is trusted without re-asking pandan (Q6, ASSUMED).

    This is exactly how far revocation lags, and it is the one constant to turn if that matters."""

    principal_negative_cache_ttl_seconds: float = Field(
        default=10.0,
        validation_alias="KAYA_PRINCIPAL_NEGATIVE_CACHE_TTL_SECONDS",
    )
    """How long a rejection is remembered (Q6, ASSUMED).

    Short, because it is load-shedding rather than a decision: a stray ``Authorization`` header on
    a retry loop must not become one pandan round trip per request. Kept well under the positive
    TTL so a token that was rejected because it hadn't been minted yet becomes usable quickly."""

    card_resolution_connect_timeout_seconds: float = Field(
        default=3.0,
        validation_alias="KAYA_CARD_RESOLUTION_CONNECT_TIMEOUT_SECONDS",
    )
    """Per-request connect budget for resolving `[[KAN-n]]`/`[[EPIC-n]]` wikilinks against pandan
    (KAN-564, spike 0001). Deliberately **not** `pandan_connect_timeout_seconds`: this budget
    protects a note *render*, which must return promptly with an unresolved link rather than wait
    out identity's much longer cold-start allowance (ADR 0003's "slow is worse than down" — a
    render blocking for 30s on a decoration is worse than the decoration simply not showing up).
    Sized off spike 0001's measured 1.3-1.7s page fetch, connect phase only."""

    card_resolution_read_timeout_seconds: float = Field(
        default=3.0,
        validation_alias="KAYA_CARD_RESOLUTION_READ_TIMEOUT_SECONDS",
    )
    """Per-request read budget for the same calls. ~3s, per spike 0001's recommendation — enough
    headroom over the measured 1.3-1.7s page fetch without being generous, because this budget can
    be spent several times over inside one render (see `card_resolution_max_upstream_requests`)."""

    card_resolution_total_deadline_seconds: float = Field(
        default=8.0,
        validation_alias="KAYA_CARD_RESOLUTION_TOTAL_DEADLINE_SECONDS",
    )
    """Wall-clock budget for one `CardEpicResolver.resolve()` call, across every request it makes.
    Refs still unresolved when this elapses render unresolved rather than the render hanging — the
    partial-resolution degradation spike 0001 calls for. This bounds when a **new** request may
    *start*; it does not cancel one already in flight, so worst-case wall time is this plus one
    request's own timeout, not a hard ceiling on its own (ADR 0001: no async engine, no cancellation
    primitive to reach for here)."""

    card_resolution_max_upstream_requests: int = Field(
        default=5,
        validation_alias="KAYA_CARD_RESOLUTION_MAX_UPSTREAM_REQUESTS",
    )
    """Hard cap on upstream requests inside one `resolve()` call, regardless of elapsed time —
    spike 0001's "five-page cap" carried over to a request-count cap. The mechanism changed (see
    `app/integrations/card_resolution.py`'s module docstring: pandan's `refs=`/`ids=` batch
    parameter, issue #254, shipped after the spike was written, so this is no longer a page walk),
    but the reason for a cap did not: a huge note or a huge board must degrade to partially
    resolved rather than to a long wait, deterministically rather than only via the deadline
    clock."""

    card_resolution_max_selectors_per_request: int = Field(
        default=100,
        validation_alias="KAYA_CARD_RESOLUTION_MAX_SELECTORS_PER_REQUEST",
    )
    """How many `KAN-n` refs go in one `GET /api/v1/cards?refs=...` request before the resolver
    chunks into a second one. Must not exceed pandan's own combined-selector cap
    (`MAX_CARD_SELECTORS`) or every ref in an over-sized chunk gets a `422` instead of an answer.
    Verified live against `GET /openapi.json` and the endpoint itself on 2026-08-18: pandan's
    default cap is 100, and this mirrors it rather than guessing a smaller, safer number, because a
    smaller chunk size only costs more requests for no benefit — the cap is enforced server-side
    either way. Epic refs never chunk: `GET /api/v1/epics` takes no `refs` parameter at all and
    returns every epic the caller can see in one unpaginated call (confirmed live), so there is
    nothing to chunk."""

    card_resolution_cache_ttl_seconds: float = Field(
        default=300.0,
        validation_alias="KAYA_CARD_RESOLUTION_CACHE_TTL_SECONDS",
    )
    """How long a resolved (or confirmed-absent) card/epic is trusted before `CardEpicResolver`
    asks pandan again. Separate from `principal_cache_ttl_seconds` by requirement (ADR 0003, spike
    0001, SLICES.md V5): a stale card title or column is cosmetic, unlike a stale identity, so this
    is generous — 5 minutes against identity's 60 seconds. One TTL rather than
    `PrincipalCache`'s positive/negative split: unlike a rejected credential, "this ticket doesn't
    exist or isn't yours" is not the kind of fact that flips back within minutes, so there is no
    argument here for two different half-lives."""

    board_embed_connect_timeout_seconds: float = Field(
        default=3.0,
        validation_alias="KAYA_BOARD_EMBED_CONNECT_TIMEOUT_SECONDS",
    )
    """Per-request connect budget for rendering a `pandan-board` embed (KAN-1049) — a saved view or
    column query against pandan, made fresh on every render (see
    `app/integrations/board_embed.py`'s module docstring for why this path is not cached). Its own
    field rather than reusing `card_resolution_connect_timeout_seconds`: the two protect different
    call shapes (one or two whole-response fetches here, versus a chunked `refs=` batch there) even
    though the underlying argument is the same one card resolution already made — this decorates a
    note render and must fail fast rather than borrow identity's cold-start allowance. Mirrors
    card resolution's default rather than guessing a different number, because the same "a few
    seconds is plenty for a live host, and a dead one should say so quickly" reasoning applies."""

    board_embed_read_timeout_seconds: float = Field(
        default=3.0,
        validation_alias="KAYA_BOARD_EMBED_READ_TIMEOUT_SECONDS",
    )
    """Per-request read budget for the same calls. See
    `board_embed_connect_timeout_seconds` for why this is a separate knob from card resolution's."""

    log_level: str = Field(
        default="INFO",
        validation_alias="KAYA_LOG_LEVEL",
    )
    """Threshold for the one stdout handler (``app/observability/logs.py``, Q41).

    ``INFO`` gives one JSON line per request. ``DEBUG`` adds the liveness probe, which is left out
    of ``INFO`` on purpose — the kubelet hits `/health` every few seconds forever and would
    otherwise be almost the whole log.

    Deliberately not validated against the known level names. ``Logger.setLevel`` already raises on
    an unknown one, with a message naming the string it was handed; a pydantic validator would
    duplicate that and turn a typo'd *log level* into a service that refuses to boot, which is the
    observability layer causing the outage it exists to explain."""

    r2_bucket: str | None = Field(
        default=None,
        validation_alias="KAYA_R2_BUCKET",
    )
    """The bucket attachments (R14, KAN-1067) are stored in. ``None`` — the default — means
    attachments are not configured at all: ``app/integrations/storage.py``'s ``default_storage``
    raises at first use rather than silently pretending a bucket exists, the same "fail loudly on a
    genuinely missing dependency" instinct `app/db.py` already has for `DATABASE_URL`.

    Provisioning a real Cloudflare R2 bucket and its credentials is a manual step outside any PR's
    scope (there is no live Cloudflare account wired into this environment or its CI secrets) — the
    code path is exercised against `app/integrations/storage.py`'s fake in every test."""

    r2_endpoint_url: str | None = Field(
        default=None,
        validation_alias="KAYA_R2_ENDPOINT_URL",
    )
    """R2's S3-compatible endpoint for the account holding ``r2_bucket``, e.g.
    ``https://<account-id>.r2.cloudflarestorage.com``. Not a secret — it is a hostname, not a
    credential — but it travels with the other R2 fields for the same reason `pandan_url` travels
    with the pandan timeouts: one feature's configuration, read together."""

    r2_access_key_id: str | None = Field(
        default=None,
        validation_alias="KAYA_R2_ACCESS_KEY_ID",
    )
    """R2 API token id. A credential, so it is in `_EXCLUDED_FROM_STARTUP_LOG` below — see that
    set's docstring for why a future credential-shaped field earns its own entry rather than being
    caught implicitly."""

    r2_secret_access_key: str | None = Field(
        default=None,
        validation_alias="KAYA_R2_SECRET_ACCESS_KEY",
    )
    """R2 API token secret. Same treatment as `r2_access_key_id`, and for the same reason."""

    r2_region: str = Field(
        default="auto",
        validation_alias="KAYA_R2_REGION",
    )
    """SigV4 needs a region even though R2 is not regional; Cloudflare's own docs say to send
    ``"auto"``, so that is the default rather than a value somebody has to remember to set."""

    r2_upload_max_bytes: int = Field(
        default=25 * 1024 * 1024,
        validation_alias="KAYA_R2_UPLOAD_MAX_BYTES",
    )
    """Per-attachment cap, enforced in `app/api/attachments.py` while the upload streams in — a
    note body has no length cap (`app/models/note.py`'s comment: "a length cap on prose is a cap on
    the product"), but an attachment is a binary blob with no such argument against bounding it. 25
    MiB is a round, generous number for "an image, most often" (R14's own framing) rather than a
    measurement; revisit if a real usage pattern asks for more."""

    spa_dist: Path | None = Field(
        default=None,
        validation_alias="KAYA_SPA_DIST",
    )
    """The directory holding the built SPA, served from this same origin (ADR 0010, KAN-538).

    ``None`` — unset — means the app serves the API alone, and that is the default on purpose.
    There is no directory guessed at, no ``../frontend/dist`` tried as a fallback: the one thing
    worse than not finding a build is silently serving a months-old one out of somebody's working
    tree on the day the image's copy step breaks. The container image sets this; ``make dev`` does
    not, because Vite serves the SPA on :5173 and proxies ``/api`` back.

    Set it to ``../frontend/dist`` to run the single-artifact layout from a checkout."""


_EXCLUDED_FROM_STARTUP_LOG = frozenset(
    {"database_url", "r2_access_key_id", "r2_secret_access_key"}
)
"""Fields ``effective_overrides`` never names, structurally rather than by review.

``database_url``'s default and every real value embed a username and password as URL userinfo —
``postgresql+psycopg://kaya:kaya@host:5432/kaya`` — so printing it whenever it differs from the
default would print a real database credential. Kaya otherwise keeps no long-lived credential of
its own (see this module's docstring and ADR 0002) — there is no ``token``/``bearer``/``KAYA_TOKEN``
field here, that name lives in ``kaya-client``'s own ``config.py`` on the CLI side of the process
boundary — until R14's R2 fields (KAN-1067), which are the first ``Settings`` fields that hold
kaya's *own* credential rather than a caller's forwarded bearer. This is therefore a three-entry
allow-list rather than a name pattern that could rot as fields are added; a future field whose value
could carry a credential earns its own entry here rather than being caught implicitly."""


def effective_overrides(settings: Settings) -> dict[str, Any]:
    """Every ``Settings`` field whose value differs from the field's own declared default.

    KAN-968: ``docker-compose.yml``'s ``app`` service forwards exactly two environment variables
    (``DATABASE_URL``, ``KAYA_PANDAN_URL``) into the container, so every other field here —
    ``KAYA_CARD_RESOLUTION_*``, the pandan timeout split, ``KAYA_MAX_TEXT_CHARS`` (kaya-client's,
    not this module's, but the same shape), ``KAYA_SPA_DIST`` — silently takes its default under
    `make up` however it is spelled in the caller's shell, with nothing warning that the knob never
    arrived. This does not fix that: a value that never reached the process cannot be named by
    inspecting the process, and `make up`'s two-variable forward is unchanged (see CLAUDE.md
    §Commands). What it buys is the general case — a value that *did* take effect, in any run
    (compose or a direct ``uvicorn``), is visible in the startup log without shelling into the
    container to run ``printenv``.
    """
    return {
        name: getattr(settings, name)
        for name, field in Settings.model_fields.items()
        if name not in _EXCLUDED_FROM_STARTUP_LOG and getattr(settings, name) != field.default
    }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings.

    Cached so the environment is read once per process. Tests that change the environment must
    call ``get_settings.cache_clear()`` — and so must ``get_engine.cache_clear()``.
    """
    return Settings()
