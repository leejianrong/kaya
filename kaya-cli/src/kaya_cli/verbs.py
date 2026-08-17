"""The verbs. `note {list,get,create,edit,move,delete}`, `config {set,show,path}`, and bare `kaya`.

### What a verb is allowed to be

Four lines, and ADR 0004 is the reason it is four rather than forty:

    open a session from the environment  →  call one client method  →  return the ``Payload``

``main`` renders and prints it. A verb never formats, never projects, never truncates, never counts,
never decides a column and never looks at ``--format``. Pandan put those decisions in its CLI, its
MCP adapter called the same client and inherited none of them, and one ``list_cards`` costs 44,902
tokens against 2,689 for the equivalent CLI read. **A formatting rule appearing in this file is a
bug, not a local optimisation** — the review question is "why isn't this in `kaya-client`?" and for
anything shaped like output the answer is always "it should be".

What is genuinely the adapter's, and is therefore here: which client method a word maps to, and how
the positional argument reaches it. That is "how an adapter gets its arguments", which is the one
thing ADR 0004 leaves to the adapter.

**KAN-551 quadrupled the verb count and this file gained no new kind of thing**, which is ADR 0005's
sequencing rule paying out on its own terms: "adding a verb is adding a verb". Every write below is
one client call, every argument is passed through, and nothing here knows what a `409` is.

**KAN-549 added a verb with no word.** ADR 0005 §contract 7's bare `kaya` is ``BARE`` in the table
below, dispatched by the same lookup as everything else, so "content-first" cost this file one row
and one four-line function. The two things a bare invocation has that a verb does not — a banner,
and a slice of the corpus — are both in `kaya_client`, and neither is in this package at all.

### Two tables, because a `config` verb has no session

`config show` has to work **when there is no token**, since finding that out is what it is for. So
the dispatch is split: ``VERBS`` holds the ones that talk to the API and are handed an open
``KayaClient``, ``LOCAL_VERBS`` holds the ones that only read and write the local configuration. One
table with a nullable client would have made every note verb check whether it had one, and the
mistake it invites — opening a session to run `config path` — is the one that makes the verb useless
on the machine where it is needed.

`tests/test_verbs.py` asserts the union of the two matches the parser exactly, and that they are
disjoint, so a word cannot be added to one table, forgotten in the other, and silently dispatch to
whichever was checked first.

### The ref is passed through untouched

`kaya note get note-12` sends ``note-12``. ADR 0008 puts every spelling through one resolver in
`backend/app/api/refs.py`, so a missing note is the same `404` byte for byte whichever spelling
asked for it, and ``#NOTE-12`` is a `400` rather than a silent success. Normalising here would be a
second resolver, and the first thing a second resolver does is disagree with the first. That now
applies to four verbs rather than one, and none of them may grow an opinion: `edit`, `move` and
`delete` hand ``args.ref`` to the client exactly as `get` does.

### The transport seam

``open_client`` is imported into this module's namespace and called by name, so a test replaces it
with ``monkeypatch.setattr(verbs, "open_client", …)`` and drives the whole CLI — argv, parser,
verb, client, ``render``, stdout, exit code — against an ``httpx.MockTransport``. That is what makes
SLICES §V2a's six failure classes provable end to end rather than at the seam: a `404` in
`tests/test_failure_classes.py` is a real `404` travelling the real path, with no network and no PAT
anywhere near this repository.

### No verb prompts, ever

ADR 0005 §contract 9 says a verb must not prompt when stdin is not a tty. Nothing here reads stdin
at all — not conditionally, not behind an ``isatty`` check — so there is no tty branch to get wrong
and a missing token is a structured refusal rather than a hang. `tests/test_no_prompting.py` guards
it from both sides: the process answers with stdin closed, and no interactive builtin appears in the
package's source.

That guard is the reason `note create` takes ``--body`` and ``--body-file`` and **not** a bare ``-``
for the standard input. A dash would be an explicit request rather than a prompt, so it would not
violate contract 9 as written — but implementing it means the string the structural half of that
test forbids appears in this package, and the guard would have to be relaxed from "there is no
interactive read anywhere" to "there is one and it is the right one". The stronger guard is worth
more than the convenience, and the convenience is not even lost: the shell already spells it,
``--body-file /dev/stdin``, with no code here at all.
"""

from argparse import Namespace
from collections.abc import Callable, Mapping

from kaya_client import (
    API_URL_ENV,
    TOKEN_ENV,
    KayaClient,
    Payload,
    open_client,
    path_payload,
    settings_payload,
    write_settings,
)

from kaya_cli.parsing import resolve_body

NOTE = "note"
LIST = "list"
GET = "get"
CREATE = "create"
EDIT = "edit"
MOVE = "move"
DELETE = "delete"

CONFIG = "config"
SET = "set"
SHOW = "show"
PATH = "path"

BARE: tuple[None, None] = (None, None)
"""ADR 0005 §contract 7's bare `kaya`, as a row in ``VERBS`` like everything else (KAN-549).

**It is a verb with no word**, which is the whole of how this card avoided a special case. The two
``None``s are what `build_parser`'s ``set_defaults`` leaves on the namespace when argv named no
command, so `run` below dispatches it through the same table lookup as `note list` — no branch, no
second session-opening path, and the client is closed by the same ``with``.

It is deliberately **not** reachable from the parser, so `tests/test_verbs.py`'s "every parser word
has a verb" assertion names it explicitly rather than deriving it. A word that dispatched here would
be a second spelling of a bare invocation.
"""

Verb = Callable[[KayaClient, Namespace], Payload]
LocalVerb = Callable[[Namespace], Payload]


# ------------------------------------------------------------------------------ notes


def _overview(client: KayaClient, _args: Namespace) -> Payload:
    """Bare `kaya`: the caller's most recent notes. **One client call, like every other verb.**

    The number of rows, the order and the fact that a slice happened at all are
    `KayaClient.recent_notes`' — see its docstring, and `payloads.Payload.limited_to` for why a
    slice is the client's business and not an adapter's. A ``[:5]`` written here instead would be
    exactly the projection rule this module's docstring says is a bug rather than a local
    optimisation, and V6's MCP server would inherit none of it.

    The banner above these rows is not this function's either, and it is not any payload's: see
    `kaya_cli.__main__.main`, which prints `kaya_client.overview` beside what ``render`` returned.
    """
    return client.recent_notes()


def _note_list(client: KayaClient, args: Namespace) -> Payload:
    """`note list`, with KAN-559's `--q` forwarded exactly as argv carried it.

    ``args.q`` is ``None`` when the flag was not given, which is the one value that makes
    ``KayaClient.list_notes`` add no query parameter at all — the same plain list this verb has
    always made. A present value, blank or not, goes to the client untouched: what a blank search
    term means is `app/api/search.py`'s decision, not this adapter's, and it comes back as an
    `ApiError` `render` already knows how to print.
    """
    return client.list_notes(args.q)


def _note_get(client: KayaClient, args: Namespace) -> Payload:
    return client.get_note(args.ref)


def _note_create(client: KayaClient, args: Namespace) -> Payload:
    return client.create_note(args.title, body=resolve_body(args), path=args.path)


def _note_edit(client: KayaClient, args: Namespace) -> Payload:
    return client.update_note(
        args.ref,
        title=args.title,
        body=resolve_body(args),
        path=args.path,
        if_updated_at=args.if_updated_at,
    )


def _note_move(client: KayaClient, args: Namespace) -> Payload:
    return client.move_note(args.ref, args.path)


def _note_delete(client: KayaClient, args: Namespace) -> Payload:
    return client.delete_note(args.ref)


# ----------------------------------------------------------------------------- config


def _config_show(_args: Namespace) -> Payload:
    return settings_payload()


def _config_path(_args: Namespace) -> Payload:
    return path_payload()


def _config_set(args: Namespace) -> Payload:
    """Write the named settings and return the effective configuration afterwards.

    Keyed by environment name because that is the one vocabulary `kaya_client.config` names a
    setting in; it translates to the file's spelling itself (`file_key`), so this package holds no
    opinion about what the file looks like.

    **What comes back is the effective configuration, not the file.** If a shell exports
    ``KAYA_API_URL`` and the caller then sets ``api_url`` in the file, the row still shows the
    exported value with ``source`` reading ``environment`` — which is the truth, and the one thing a
    caller in that situation most needs told. A verb that echoed the file back would confirm a write
    that changes nothing about the next command.
    """
    return write_settings({API_URL_ENV: args.api_url, TOKEN_ENV: args.token})


VERBS: Mapping[tuple[str | None, str | None], Verb] = {
    BARE: _overview,
    (NOTE, LIST): _note_list,
    (NOTE, GET): _note_get,
    (NOTE, CREATE): _note_create,
    (NOTE, EDIT): _note_edit,
    (NOTE, MOVE): _note_move,
    (NOTE, DELETE): _note_delete,
}
"""``(command, subcommand)`` → the client method that answers it, for the verbs that need a session.

A table rather than an ``if`` chain, so `build_parser` and this module cannot drift about which
words exist: `tests/test_verbs.py` asserts that every parser word has a row and every row is a
parser word — plus ``BARE``, the one row with no word, named there rather than derived.
"""

LOCAL_VERBS: Mapping[tuple[str, str], LocalVerb] = {
    (CONFIG, SET): _config_set,
    (CONFIG, SHOW): _config_show,
    (CONFIG, PATH): _config_path,
}
"""The verbs that never open a session. See this module's docstring for why they are a second table.

They still return a ``Payload`` and are still printed by ``render``: "local" is about the transport,
not about the output contract, and a `config show` that formatted itself would be exactly the ADR
0004 leak this package exists not to have.
"""


def run(args: Namespace) -> Payload:
    """Dispatch one parsed invocation and return the payload it produced.

    Every failure leaves as a ``KayaError`` — ``MissingCredential`` from the configuration,
    ``TransportError`` or ``ApiError`` from the client, ``UsageError`` from a write that named
    nothing to change — and ``main``'s single funnel turns it into a structured row and an exit
    number. This function catches nothing on purpose.

    A note verb resolves its credential *before* it reads a ``--body-file``, because the session is
    opened first. Both are refusals with their own exit code and neither hides the other across two
    runs, so the order is not worth an extra branch here.
    """
    word = (args.command, args.subcommand)

    local = LOCAL_VERBS.get(word)
    if local is not None:
        return local(args)

    verb = VERBS[word]
    with open_client() as client:
        return verb(client, args)
