"""Where a ``KayaClient`` gets its origin and its bearer. PLAN §Config's environment tier, and only
that tier.

PLAN fixes the scheme: a per-app prefix, each key resolved independently from the first source that
supplies it — **environment → user config file → nearest ``.mcp.json``** — over ``KAYA_API_URL``,
``KAYA_TOKEN``, ``KAYA_PANDAN_URL`` and ``KAYA_MAX_TEXT_CHARS``. This module implements the first
source and names the three keys the verbs need so far. The file tiers and the
``config {set,show,path}`` verbs are KAN-551's (SLICES §V2b step 6), and they extend the functions
below rather than replacing them: a caller asks for ``token()``, not for an environment variable.
``config show``'s "effective value" is whatever `max_text_chars` returns, which is the reason that
function exists here rather than as a line inside an adapter.

### Why this is in the shared client and not in `kaya-cli`

ADR 0004's review question is "would V6's MCP adapter have to reimplement this to be correct?", and
here the answer is plainly yes — an MCP server started from the same shell reads the same keys, and
a second resolver is a second answer to "which deployment am I talking to?" (and, since KAN-547, to
"how much prose is a read allowed to return?"). Contrast
`kaya_cli.parsing`, which owns argv: an adapter owns *how it gets its arguments*, and an environment
variable is not an argument, it is the deployment.

It is deliberately **not** shaping and does not go near ``render``.

### The token, and the one rule that outranks every other consideration here

``KAYA_TOKEN`` holds a pandan PAT. This module reads it, hands it to ``KayaClient``, and does
nothing else with it: it is never logged, never echoed, never included in an exception message and
never returned as part of a diagnostic. ``MissingCredential`` names the *variable*, never a value —
a truncated token is still a token (Q41/Q42). ADR 0002 buys kaya the property that it holds no
replayable credential, and a config layer that printed what it resolved would give that away for a
convenience nobody asked for.

### Why ``KAYA_API_URL`` has a default and ``KAYA_TOKEN`` does not

``make up`` serves the whole stack on ``:8000`` from one origin, and the SPA's dev proxy points at
the same place, so ``http://localhost:8000`` is the address a checkout is already using. Defaulting
to it means a developer configures exactly one thing, and that one thing is the one kaya cannot
invent: ADR 0002 gives kaya no token format and no way to mint one, so a missing PAT is a refusal
and never a fallback.
"""

import os
from collections.abc import Mapping

import httpx

from kaya_client.client import DEFAULT_TIMEOUT, KayaClient
from kaya_client.errors import MissingCredential, UsageError
from kaya_client.truncation import DEFAULT_TEXT_LIMIT

API_URL_ENV = "KAYA_API_URL"
"""The kaya deployment to talk to. PLAN §Config."""

TOKEN_ENV = "KAYA_TOKEN"
"""The caller's pandan PAT, forwarded byte-for-byte and never parsed (ADR 0002)."""

MAX_TEXT_CHARS_ENV = "KAYA_MAX_TEXT_CHARS"
"""How much prose a read returns before the truncation hint (KAN-547). PLAN §Config."""

DEFAULT_API_URL = "http://localhost:8000"
"""What ``make up`` and ``make dev`` serve. A default, not a fallback — see the module docstring."""


def api_url(env: Mapping[str, str] | None = None) -> str:
    """The configured origin, or the local default.

    ``env`` defaults to ``os.environ`` **at call time** rather than at import, so a test's
    ``monkeypatch.setenv`` and a real shell are the same code path — the same reasoning
    `kaya_cli.failures.report` uses for ``stream``.
    """
    environment = os.environ if env is None else env
    return (environment.get(API_URL_ENV) or "").strip() or DEFAULT_API_URL


def token(env: Mapping[str, str] | None = None) -> str:
    """The caller's bearer, or a refusal naming the variable that would supply one.

    Whitespace-only is treated as absent. An exported-but-empty variable is the common shape of a
    misconfigured shell profile, and a blank bearer would otherwise reach the API and come back as a
    `401` — exit `3`, telling the caller to re-authenticate a credential they never set.
    """
    environment = os.environ if env is None else env
    value = (environment.get(TOKEN_ENV) or "").strip()
    if not value:
        raise MissingCredential(
            f"no kaya token configured — set {TOKEN_ENV} to a pandan personal access token",
            arg=TOKEN_ENV,
        )
    return value


def max_text_chars(env: Mapping[str, str] | None = None) -> int:
    """The effective ``text_limit`` for this process: ``KAYA_MAX_TEXT_CHARS``, or 500.

    This is the number ADR 0005 §contract 6 is about, resolved in one place so that both adapters
    truncate identically and KAN-551's ``config show`` has something to report rather than a rule to
    restate. The default is `truncation.DEFAULT_TEXT_LIMIT` rather than a literal ``500`` written
    again here — two copies of one number is how a config layer starts disagreeing with the thing it
    configures.

    **``0`` is a value, not an absence.** It disables truncation, which is ADR 0005's ``--full`` as
    a deployment setting, so it must survive a falsy check that ``""`` and an unset variable do
    not. Whitespace-only is treated as unset, for the reason `token` gives: an exported-but-empty
    variable is the common shape of a misconfigured shell profile.

    A value that is not a whole number, or is negative, is a ``UsageError`` — ADR 0005 §contract 4's
    exit `2`, "the caller's input was rejected". It names the variable in ``arg`` the way
    ``MissingCredential`` does, so the row a consumer reads names the thing to fix. It is
    deliberately *not* the ``ValueError``/``TypeError`` `truncation.check_text_limit` raises at the
    seam: those are caller bugs in code and reach a person as a traceback, whereas this one is a
    shell someone can correct, and ``main``'s funnel only catches ``KayaError``.
    """
    environment = os.environ if env is None else env
    raw = (environment.get(MAX_TEXT_CHARS_ENV) or "").strip()
    if not raw:
        return DEFAULT_TEXT_LIMIT

    try:
        value = int(raw)
    except ValueError:
        raise UsageError(
            f"{MAX_TEXT_CHARS_ENV} must be a whole number of characters — {raw!r} is not one, "
            f"and 0 disables truncation",
            arg=MAX_TEXT_CHARS_ENV,
        ) from None

    if value < 0:
        raise UsageError(
            f"{MAX_TEXT_CHARS_ENV} must be 0 or more — 0 already disables truncation",
            arg=MAX_TEXT_CHARS_ENV,
        )
    return value


def open_client(
    env: Mapping[str, str] | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
) -> KayaClient:
    """A ``KayaClient`` for the configured deployment — the one call an adapter makes for a session.

    ``transport`` is the injection seam, and it is the same one ``KayaClient(client=…)`` already
    offers one layer down: tests drive the CLI end to end against an ``httpx.MockTransport`` so that
    a `404` is a real `404` travelling the real code path, with no network and no PAT anywhere near
    this repository. Nothing in shipped code passes it.
    """
    bearer = token(env)
    # `timeout=DEFAULT_TIMEOUT` because this is the injected-client branch, and `KayaClient` does
    # not — cannot — reach into a client it was handed to set one (see its `__init__`). Without it
    # this path would quietly run on httpx's own 5 s default and break KAN-716's invariant on the
    # one code path no test would notice, since a `MockTransport` never blocks long enough to fire
    # any deadline at all.
    client = None
    if transport is not None:
        client = httpx.Client(transport=transport, timeout=DEFAULT_TIMEOUT)
    return KayaClient(api_url(env), bearer, client=client)
