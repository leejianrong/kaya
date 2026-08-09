"""The verbs. `kaya note list` and `kaya note get <ref>`, and deliberately nothing else (KAN-541).

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

### The ref is passed through untouched

`kaya note get note-12` sends ``note-12``. ADR 0008 puts every spelling through one resolver in
`backend/app/api/refs.py`, so a missing note is the same `404` byte for byte whichever spelling
asked for it, and ``#NOTE-12`` is a `400` rather than a silent success. Normalising here would be a
second resolver, and the first thing a second resolver does is disagree with the first.

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
"""

from argparse import Namespace
from collections.abc import Callable, Mapping

from kaya_client import KayaClient, Payload, open_client

NOTE = "note"
LIST = "list"
GET = "get"

Verb = Callable[[KayaClient, Namespace], Payload]


def _note_list(client: KayaClient, _args: Namespace) -> Payload:
    return client.list_notes()


def _note_get(client: KayaClient, args: Namespace) -> Payload:
    return client.get_note(args.ref)


VERBS: Mapping[tuple[str, str], Verb] = {
    (NOTE, LIST): _note_list,
    (NOTE, GET): _note_get,
}
"""``(command, subcommand)`` → the client method that answers it.

A table rather than an ``if`` chain, so `build_parser` and this module cannot drift about which
words exist: `tests/test_verbs.py` asserts that every parser word has a row and every row is a
parser word. V2b's write verbs are rows here plus subparsers there, and nothing else.
"""


def run(args: Namespace) -> Payload:
    """Dispatch one parsed invocation and return the payload it produced.

    Every failure leaves as a ``KayaError`` — ``MissingCredential`` from the configuration,
    ``TransportError`` or ``ApiError`` from the client — and ``main``'s single funnel turns it into
    a structured row and an exit number. This function catches nothing on purpose.
    """
    verb = VERBS[(args.command, args.note_command)]
    with open_client() as client:
        return verb(client, args)
