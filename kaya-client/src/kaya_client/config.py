"""Where a ``KayaClient`` gets its origin and its bearer, and where `kaya config` reads and writes.

PLAN fixes the scheme: a per-app prefix, each key resolved **independently** from the first source
that supplies it — **environment → user config file → nearest ``.mcp.json``** — over
``KAYA_API_URL``, ``KAYA_TOKEN``, ``KAYA_PANDAN_URL`` and ``KAYA_MAX_TEXT_CHARS``.
"Independently" is the load-bearing word: a shell that exports only ``KAYA_TOKEN`` does not
thereby discard the ``api_url`` in the file, because the tiers are consulted per key and not per
source.

**Two of the three tiers are implemented, and the third is named with its reason** (KAN-551):

- **environment** — KAN-541's tier, unchanged.
- **user config file** — this card. JSON at ``$XDG_CONFIG_HOME/kaya/config.json``, read by every
  resolver below and written by ``write_settings``.
- **nearest ``.mcp.json``** — deliberately not built. That file is an MCP *host's* configuration and
  its shape is a map of server names to launch specs; reading one means deciding which server entry
  is kaya's, which is a guess until there is a server to be named, and V6 is the card that names it
  (ADR 0006 freezes the tool set, not the server key). Building a reader now would fix the answer to
  that question in a package that cannot yet see it, so the tier arrives with the surface it exists
  to configure. Note also that an MCP host launching a server usually *exports* the ``env`` block it
  finds, in which case tier one already covers the common case.

``KAYA_PANDAN_URL`` is in PLAN's list and is deliberately absent from this module: it is
`backend/app/config.py`'s, naming the identity provider kaya's *server* introspects against
(ADR 0002). A CLI reporting it as an "effective value" would be reporting a setting that changes
nothing about what the CLI does.

### Why this is in the shared client and not in `kaya-cli`

ADR 0004's review question is "would V6's MCP adapter have to reimplement this to be correct?", and
here the answer is plainly yes — an MCP server started from the same shell reads the same keys, and
a second resolver is a second answer to "which deployment am I talking to?" (and, since KAN-547, to
"how much prose is a read allowed to return?"). For the *file* the answer is yes twice over: the
path, the format, the precedence and the read-modify-write merge are all things a second
implementation would get subtly differently, and the first symptom would be one surface writing a
file the other cannot read. Contrast `kaya_cli.parsing`, which owns argv: an adapter owns *how it
gets its arguments*, and an environment variable is not an argument, it is the deployment.

So `kaya-cli` contributes exactly the subparsers and the flag values. The three ``config`` verbs
return a ``Payload`` from this module and print through ``render`` like every other verb — a config
verb with its own printer would be the ADR 0004 leak in the one place it is easiest to excuse.

### The file format is JSON, and the reason is the writer

Pandan keeps ``~/.config/pandan/config.toml`` and suite consistency would argue for TOML here.
Python 3.12 reads TOML (``tomllib``) and **cannot write it**, and ``kaya-client`` has exactly one
runtime dependency (SLICES §V2a) which is not being spent on a serializer. That leaves two options:
hand-roll a TOML writer, or use the format the standard library can do both halves of.

A hand-rolled writer is the wrong one specifically because of this card's named trap. ``config set``
must preserve keys it has no flag for, which means it round-trips values it does not understand —
and a writer that emits only the shapes its author thought of will one day meet a hand-written
table, an array or a multi-line string and rewrite the file into something the reader rejects. A
config layer that can read a format it cannot faithfully write is a config layer whose ``set`` verb
destroys hand-edited files. ``json`` reads and writes the same value domain, so the round trip is
total.

### The token, and the one rule that outranks every other consideration here

``KAYA_TOKEN`` holds a pandan PAT. This module reads it, hands it to ``KayaClient``, and does
nothing else with it: it is never logged, never echoed, never included in an exception message and
never returned as part of a diagnostic. ``MissingCredential`` names the *variable*, never a value —
a truncated token is still a token (Q41/Q42). ADR 0002 buys kaya the property that it holds no
replayable credential, and a config layer that printed what it resolved would give that away for a
convenience nobody asked for.

**``config show`` therefore prints ``set`` and not a fragment.** The sibling tool is the reference
behaviour for the *verb* and not for this detail: `pandan config show` prints a token row reading
``set (…c_DE)``, and those four characters are a contiguous fragment of a live credential, on
somebody's terminal, in a command whose whole selling point is that it is safe to paste into an
issue.
``tests/test_config_file.py`` checks every fragment of six characters or more against the rendered
output in all three formats, the same way `backend/tests/unit/test_log_redaction.py` does, because
the tempting diagnostic ("is it the right token?") is exactly what the rule forbids.

### Why ``KAYA_API_URL`` has a default and ``KAYA_TOKEN`` does not

``make up`` serves the whole stack on ``:8000`` from one origin, and the SPA's dev proxy points at
the same place, so ``http://localhost:8000`` is the address a checkout is already using. Defaulting
to it means a developer configures exactly one thing, and that one thing is the one kaya cannot
invent: ADR 0002 gives kaya no token format and no way to mint one, so a missing PAT is a refusal
and never a fallback.
"""

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx

from kaya_client.client import DEFAULT_TIMEOUT, KayaClient
from kaya_client.errors import KayaError, MissingCredential, UsageError
from kaya_client.payloads import Payload
from kaya_client.truncation import DEFAULT_TEXT_LIMIT

API_URL_ENV = "KAYA_API_URL"
"""The kaya deployment to talk to. PLAN §Config."""

TOKEN_ENV = "KAYA_TOKEN"
"""The caller's pandan PAT, forwarded byte-for-byte and never parsed (ADR 0002)."""

MAX_TEXT_CHARS_ENV = "KAYA_MAX_TEXT_CHARS"
"""How much prose a read returns before the truncation hint (KAN-547). PLAN §Config."""

SETTINGS: tuple[str, ...] = (API_URL_ENV, TOKEN_ENV, MAX_TEXT_CHARS_ENV)
"""Every key this package resolves, in the order ``config show`` lists them.

One tuple rather than three mentions, so a fourth setting is a row here and a resolver below, and
cannot be added to one without the other noticing. ``KAYA_PANDAN_URL`` is absent for the reason in
the module docstring: it configures the server, not this client."""

DEFAULT_API_URL = "http://localhost:8000"
"""What ``make up`` and ``make dev`` serve. A default, not a fallback — see the module docstring."""

PREFIX = "KAYA_"
"""The per-app prefix PLAN §Config specifies. Also the whole of the environment-name ↔ file-key
mapping: see `file_key`."""

CONFIG_HOME_ENV = "XDG_CONFIG_HOME"
HOME_ENV = "HOME"
"""How the config file's directory is located, in that order. The XDG variable first because it is
the one a user sets *deliberately*; ``HOME`` is the fallback every tool already assumes.

Neither is a kaya setting and neither goes through the tiers — they say where configuration lives,
so reading them from configuration would be circular. It is also what makes the test suite hermetic:
a test that sets ``XDG_CONFIG_HOME`` to a ``tmp_path`` cannot reach a developer's real file, and
because a subprocess inherits the environment, that holds for the CLI's subprocess tests too."""

CONFIG_DIR = "kaya"
CONFIG_FILE = "config.json"


def file_key(env_name: str) -> str:
    """The config file's spelling of an environment key: ``KAYA_API_URL`` → ``api_url``.

    **Mechanical rather than a table.** A lookup dict would be a second place a new setting has to
    be registered, and the failure of forgetting it is silent — the key resolves from the
    environment, is invisible in the file, and ``config set`` writes something nothing reads.
    """
    return env_name.removeprefix(PREFIX).lower()


# ---------------------------------------------------------------------------- the file tier

ENVIRONMENT_SOURCE = "environment"
FILE_SOURCE = "file"
DEFAULT_SOURCE = "default"
UNSET_SOURCE = "unset"
"""What ``config show``'s third column says, and the vocabulary a consumer branches on.

It answers the question a two-column ``show`` cannot: *why* is ``api_url`` that value? A user who
has written the file and still sees the old origin is looking at an exported variable, and without
this column the only way to find that out is to read the tier order in a document."""


def config_path(env: Mapping[str, str] | None = None) -> Path:
    """Where the user config file lives, whether or not it exists.

    ``$XDG_CONFIG_HOME/kaya/config.json``, or ``$HOME/.config/kaya/config.json``. Derived from the
    supplied ``env`` rather than from ``Path.home()``, which reads the real process environment and
    would make every test that passes an explicit mapping reach the developer's own file.

    An environment naming **neither** variable is a ``KayaError`` rather than a guess. There is no
    honest default: a container with no ``HOME`` has no user configuration directory, and inventing
    ``/config.json`` or the current directory would put a credential somewhere the user did not ask
    for. `read_settings_file` catches this and degrades to "no file", so a shell with everything in
    environment variables still works; the ``config`` verbs report it, because their whole subject
    is the file.
    """
    environment = os.environ if env is None else env

    configured = (environment.get(CONFIG_HOME_ENV) or "").strip()
    if configured:
        return Path(configured) / CONFIG_DIR / CONFIG_FILE

    home = (environment.get(HOME_ENV) or "").strip()
    if home:
        return Path(home) / ".config" / CONFIG_DIR / CONFIG_FILE

    raise KayaError(
        f"no configuration directory — neither {CONFIG_HOME_ENV} nor {HOME_ENV} is set",
        arg=HOME_ENV,
    )


def read_settings_file(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """The config file's contents, or ``{}`` when there is no file to read.

    Absent file, absent directory and absent home are all "no file", because none of them is an
    error: configuring nothing is a supported way to run kaya and the defaults exist for it.

    **A file that exists and cannot be parsed is a refusal, not a shrug**, and that is the important
    decision here. Ignoring a malformed file would make ``kaya note list`` quietly talk to
    ``localhost`` while the user's file named a production deployment — and worse, ``config set``
    would then merge onto ``{}`` and *overwrite* the file whose syntax error is the only surviving
    copy of what they meant. Failing loudly costs one confusing invocation; failing quietly costs
    the file.

    The message names the path and never the contents. A config file holds a PAT, so the tempting
    "expected ``,`` near ``…``" excerpt is a credential in a diagnostic (Q41/Q42), and the parser's
    own exception is dropped with ``from None`` rather than chained for the same reason.
    """
    try:
        path = config_path(env)
    except KayaError:
        return {}

    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise KayaError(f"{path} could not be read: {exc.strerror}", arg=str(path)) from None

    try:
        loaded = json.loads(text)
    except ValueError:
        raise KayaError(
            f"{path} is not valid JSON — fix it or remove it; nothing was changed",
            arg=str(path),
        ) from None

    if not isinstance(loaded, dict):
        raise KayaError(f"{path} must hold a JSON object of settings", arg=str(path))
    return loaded


def write_settings(
    updates: Mapping[str, str | None],
    env: Mapping[str, str] | None = None,
) -> Payload:
    """Merge ``updates`` into the config file and return the effective settings afterwards.

    ``updates`` is keyed by **environment name** (``{API_URL_ENV: "https://…"}``) so that one
    vocabulary names a setting everywhere in this package; `file_key` translates at the boundary.
    A ``None`` value means "the caller did not ask about this key" and is dropped.

    ### The read-modify-write merge is the point of this function

    ``{**current, **changes}`` rather than ``dict(changes)``. This is KAN-551's named trap: a config
    file can carry keys ``config set`` has no flag for — ``max_text_chars``, which is deliberately
    hand-set, and anything a later version of kaya adds or a user left a note to themselves in — and
    a writer that serialized only what it was passed would delete every one of them. The failure is
    silent, arrives on an unrelated command, and its evidence is gone. ``tests/test_config_file.py``
    pins it with a key **this module has never heard of**, because the rule is about unknown keys
    generally and a test that only used ``max_text_chars`` would pass against a writer that had
    special-cased the one key somebody remembered.

    A malformed file makes this raise **before** anything is written, via `read_settings_file`, for
    the reason given there: merging onto ``{}`` would replace a file the user cannot re-derive.

    ### The write is atomic and the file is private

    Written to a sibling temporary file and ``os.replace``d, so an interrupted write leaves the old
    file intact rather than a truncated one — the file holds the credential that makes every other
    command work. ``0o600`` before the rename, not after, so there is no window in which a
    world-readable file contains a PAT. The directory is created ``0o700`` for the same reason.
    """
    changes = {name: value for name, value in updates.items() if value is not None}
    if not changes:
        raise UsageError(
            f"nothing to set — name at least one of {', '.join(file_key(k) for k in SETTINGS)}",
            arg="config",
        )

    for name, value in changes.items():
        if not value.strip():
            raise UsageError(
                f"{file_key(name)} was given an empty value — remove the key from the file to "
                f"unset it, rather than blanking it",
                arg=file_key(name),
            )

    path = config_path(env)
    merged = {**read_settings_file(env), **{file_key(k): v for k, v in changes.items()}}

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, path)

    return settings_payload(env)


# ------------------------------------------------------------------------- resolution

def _resolved(env_name: str, env: Mapping[str, str] | None) -> tuple[str, str]:
    """One setting as ``(value, source)``, environment first and the file second.

    Whitespace-only is treated as absent at **both** tiers. An exported-but-empty variable is the
    common shape of a misconfigured shell profile, and a ``""`` left in a hand-edited file is the
    same mistake with a different spelling — neither should mask the tier below it, and neither
    should reach the API as a blank bearer that comes back a `401`.

    ``str(...)`` around the file's value is deliberate: JSON has numbers, so ``max_text_chars`` can
    arrive as ``500`` or as ``"500"``, and both go through the one parser in `max_text_chars`
    instead of two type-dependent paths that could disagree about what ``0`` means.
    """
    environment = os.environ if env is None else env

    value = (environment.get(env_name) or "").strip()
    if value:
        return value, ENVIRONMENT_SOURCE

    stored = read_settings_file(env).get(file_key(env_name))
    if stored is not None and str(stored).strip():
        return str(stored).strip(), FILE_SOURCE

    return "", UNSET_SOURCE


def api_url(env: Mapping[str, str] | None = None) -> str:
    """The configured origin, or the local default.

    ``env`` defaults to ``os.environ`` **at call time** rather than at import, so a test's
    ``monkeypatch.setenv`` and a real shell are the same code path — the same reasoning
    `kaya_cli.failures.report` uses for ``stream``. The config file is read at call time for the
    same reason, and because a long-lived MCP server should see a ``config set`` that happened while
    it was running.
    """
    value, _ = _resolved(API_URL_ENV, env)
    return value or DEFAULT_API_URL


def token(env: Mapping[str, str] | None = None) -> str:
    """The caller's bearer, or a refusal naming what would supply one.

    The refusal names the environment variable and the file key, and **no part of any value**. This
    class exists on the path where there is no token, so there is nothing here to leak; the rule is
    stated anyway because the tempting next diagnostic ("the token in the file looks wrong") is one
    edit away and would be the leak (Q41/Q42).
    """
    value, _ = _resolved(TOKEN_ENV, env)
    if not value:
        raise MissingCredential(
            f"no kaya token configured — set {TOKEN_ENV} to a pandan personal access token, or "
            f"put one under {file_key(TOKEN_ENV)!r} in the config file",
            arg=TOKEN_ENV,
        )
    return value


def max_text_chars(env: Mapping[str, str] | None = None) -> int:
    """The effective ``text_limit`` for this process: ``KAYA_MAX_TEXT_CHARS``, the file, or 500.

    This is the number ADR 0005 §contract 6 is about, resolved in one place so that both adapters
    truncate identically and ``config show`` has something to report rather than a rule to restate.
    The default is `truncation.DEFAULT_TEXT_LIMIT` rather than a literal ``500`` written again here
    — two copies of one number is how a config layer starts disagreeing with the thing it
    configures.

    **``0`` is a value, not an absence.** It disables truncation, which is ADR 0005's ``--full`` as
    a deployment setting, so it must survive a falsy check that ``""`` and an unset key do not.

    A value that is not a whole number, or is negative, is a ``UsageError`` — ADR 0005 §contract 4's
    exit `2`, "the caller's input was rejected". It names the variable in ``arg`` and the source in
    the message, because "which of my two configurations is wrong?" is the next question and the
    tiers exist precisely so that both can hold a value. It is deliberately *not* the
    ``ValueError``/``TypeError`` `truncation.check_text_limit` raises at the seam: those are caller
    bugs in code and reach a person as a traceback, whereas this one is configuration someone can
    correct, and ``main``'s funnel only catches ``KayaError``.
    """
    raw, source = _resolved(MAX_TEXT_CHARS_ENV, env)
    if not raw:
        return DEFAULT_TEXT_LIMIT

    where = "the config file" if source == FILE_SOURCE else "the environment"
    try:
        value = int(raw)
    except ValueError:
        raise UsageError(
            f"{MAX_TEXT_CHARS_ENV} must be a whole number of characters — {raw!r} from {where} is "
            f"not one, and 0 disables truncation",
            arg=MAX_TEXT_CHARS_ENV,
        ) from None

    if value < 0:
        raise UsageError(
            f"{MAX_TEXT_CHARS_ENV} must be 0 or more ({raw!r} from {where}) — 0 already disables "
            f"truncation",
            arg=MAX_TEXT_CHARS_ENV,
        )
    return value


# --------------------------------------------------------------------- the config verbs

KEY_COLUMN = "key"
VALUE_COLUMN = "value"
SOURCE_COLUMN = "source"
SETTING_COLUMNS = (KEY_COLUMN, VALUE_COLUMN, SOURCE_COLUMN)

SETTING_NOUN = "setting"
SETTING_ENVELOPE = "settings"

TOKEN_SET = "set"
TOKEN_UNSET = "not set"
"""The only two things ``config show`` will ever say about a bearer.

Not a prefix, not a suffix, not a length: a truncated token is still a token, and a length narrows
a search. "Is it *the right* token?" is the question a fragment would answer and the one this
refuses — the honest way to answer it is to make a request and read the `401`."""

PATH_COLUMN = "path"
EXISTS_COLUMN = "exists"
CONFIG_NOUN = "config file"
CONFIG_ENVELOPE = "config"


def settings_payload(env: Mapping[str, str] | None = None) -> Payload:
    """Every setting, its effective value and where that value came from — ``config show``.

    A collection of ``{key, value, source}`` rather than one object of key/value pairs, and the
    third column is the reason. The tiers exist so that a file can be overridden by a shell, and the
    failure that produces is a user editing a file and seeing nothing change; a ``source`` column
    turns that from a support question into a row they can read. Uniform rows are also the shape
    ``toon`` is measurably good at (CLAUDE.md: `note list` −11.3%), which a single object is not.

    **The token's row carries ``set``/``not set`` and never a value.** See ``TOKEN_SET``.

    ``max_text_chars`` is here because SLICES §V2b requires ``config show`` to report the
    *effective* value — the acceptance criterion KAN-547 could not meet on its own, since half of
    "effective" was this file tier. The number is `max_text_chars`'s, not re-derived: a
    ``config show`` that computed it separately could report a value the truncator does not use,
    which is the one thing this verb must not do.
    """
    rows = []
    for env_name in SETTINGS:
        value, source = _shown(env_name, env)
        rows.append({KEY_COLUMN: file_key(env_name), VALUE_COLUMN: value, SOURCE_COLUMN: source})

    return Payload.collection(
        noun=SETTING_NOUN,
        envelope_key=SETTING_ENVELOPE,
        records=rows,
        columns=SETTING_COLUMNS,
    )


def _shown(env_name: str, env: Mapping[str, str] | None) -> tuple[str, str]:
    """One row's ``(value, source)``, with the resolver's own answer rather than a second reading.

    ``api_url`` and ``max_text_chars`` fall back to their documented defaults, and say so; the token
    is redacted here and nowhere else, so there is exactly one line in this package that decides
    what a bearer looks like on a terminal.
    """
    raw, source = _resolved(env_name, env)

    if env_name == TOKEN_ENV:
        if not raw:
            return TOKEN_UNSET, UNSET_SOURCE
        return TOKEN_SET, source

    if env_name == MAX_TEXT_CHARS_ENV:
        # `max_text_chars` rather than `raw`, so a value the truncator would refuse refuses this
        # verb too — with a message naming the variable and the tier it came from. A `config show`
        # that printed the unparsed string would be the one command that reports a broken setting
        # as if it worked.
        return str(max_text_chars(env)), source if raw else DEFAULT_SOURCE

    if not raw:
        return DEFAULT_API_URL, DEFAULT_SOURCE
    return raw, source


def path_payload(env: Mapping[str, str] | None = None) -> Payload:
    """Where the config file is, and whether it is there yet — ``config path``.

    **It prints the path it *would* use when no file exists**, rather than refusing. The verb's
    whole job is to tell a caller where to write, and the moment that matters most is before the
    file exists: ``mkdir -p $(dirname $(kaya config path))`` has to work on a fresh machine, and a
    refusal would make the one useful case the one that fails. ``exists`` keeps it honest, so a
    script can still tell "here is where it goes" from "here is where it is" without stat-ing a
    path it had to parse out of an error message.
    """
    path = config_path(env)
    return Payload.entity(
        noun=CONFIG_NOUN,
        envelope_key=CONFIG_ENVELOPE,
        record={PATH_COLUMN: str(path), EXISTS_COLUMN: path.exists()},
        columns=(PATH_COLUMN, EXISTS_COLUMN),
    )


# ------------------------------------------------------------------------- the session

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
