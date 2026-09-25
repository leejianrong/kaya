<!--
title: "Errors and exit codes"
description: The CLI's exit-code table, its machine-readable error row, and how to branch on failure in a script.
-->

# Errors and exit codes

When the CLI fails it tells you two things: an exit code you can branch on, and a structured row
you can parse. Neither requires reading prose, and neither goes to stderr.

## Exit codes

| Code | Constant | Meaning | Typical cause |
| --- | --- | --- | --- |
| `0` | `EXIT_OK` | Success | |
| `1` | `EXIT_RUNTIME` | Generic failure | Unreachable API, no token configured, anything unmapped |
| `2` | `EXIT_USAGE` | Usage error | Unknown flag, bad `--format` value, `400`/`422` from the API |
| `3` | `EXIT_UNAUTHENTICATED` | Unauthorized (`401`) | Token missing, malformed, or revoked |
| `4` | `EXIT_FORBIDDEN` | Forbidden (`403`) | Valid token, but the note or team isn't yours |
| `5` | `EXIT_NOT_FOUND` | Not found (`404`) | No such note, including a ref that matches nothing |
| `6` | `EXIT_CONFLICT` | Conflict (`409`) | `--if-updated-at` was stale — the note changed under you |

The split between `3`, `4`, `5` and `6` is the point. A script can tell "my token is bad" from
"that note isn't mine" from "that ref doesn't exist" from "somebody else wrote to it first", and
react differently, without matching on message text.

The table is **add-only** — a row can be added, never renumbered, because a code string is a
published contract from the moment it reaches stdout. `kaya-cli/tests/test_exit_codes.py` pins
every shipped row by literal value, so a renumber would be a red test rather than a silent break.

!!! note "Where `2` and `1` split"

    `2` is specifically the caller's input being rejected — by argparse, or by the API's `400`
    and `422`. Both of those are things that can never succeed unmodified, however many times
    you retry them, which is why they're not the unmapped default: a malformed ref like
    `#NOTE-12` is exactly this case
    ([ADR 0008](https://github.com/leejianrong/kaya/blob/main/docs/adr/0008-note-identity.md)
    makes it a `400` by design, not a `404` about a string that isn't a ref at all).

    Everything the tables have no row for — an unreachable API, a `503`, a status nobody's added
    yet — is `1`. A script that retries `1` might succeed on the next attempt; retrying `2` never
    will.

!!! note "Why `6` exists, and why it's the one number kaya chose rather than inherited"

    Every other row in this table came from pandan's own exit-code convention verbatim, so an
    operator scripting both tools never has to remember which is which. `6` is the exception:
    kaya added it because a note body write can hit a genuinely **retryable** conflict
    ([ADR 0009](https://github.com/leejianrong/kaya/blob/main/docs/adr/0009-optimistic-concurrency-on-note-bodies.md)),
    and exit `1` made that unreachable — a script has to read `1` as "kaya failed", so it either
    retries the same stale precondition forever or abandons a conflict it had everything it needed
    to resolve. Not `2` either: the precondition was correct when you read it, so sending you back
    to re-read your own command line would be the wrong direction. pandan later added the
    identical row for its own `409`s, so the number means the same thing on both sides of the
    suite — though pandan's own conflicts are terminal, not retryable, which its docs are honest
    about.

## The error row

Errors print on **stdout**, as one tab-separated row, always four fields even when the last is
empty:

```console
$ kaya note get NOTE-99999
error	note_not_found	no such note	
$ echo $?
5
```

```console
$ kaya note list
error	no_credential	no kaya token configured — set KAYA_TOKEN to a pandan personal access token, or put one under 'token' in the config file	KAYA_TOKEN
$ echo $?
1
```

Four fields: the literal `error`, a stable machine code, a human message, and the offending
argument (blank when there isn't one, which is the case whenever the detail that would go there is
a whole object rather than a scalar — see the `409` example in
[writing notes](writing.md)).

!!! tip "Nothing important goes to stderr"

    You never have to merge streams with `2>&1` to catch a kaya error. Only argparse's own
    `usage:` text — for a genuinely malformed command line — goes to stderr, and even then the
    structured row is still on stdout beside it.

## Structured errors

Under `--format json` (or `--format toon`) the same failure comes back as an object, over every
key `error_payload` attached — `code`, `message` and `arg` always present, plus whatever extra
detail the failure carried:

```console
$ kaya note get NOTE-99999 --format json
{"error":{"code":"note_not_found","message":"no such note","arg":""}}
```

So branching is a one-liner:

```bash
code=$(kaya note get "$REF" --format json | jq -r '.error.code // "ok"')
```

Every `KayaError` a `KayaClient` can raise carries a stable `code` your script can match on
directly, without going through the exit-code table at all: `usage`, `no_credential`,
`unreachable`, plus whatever the API's own `code` vocabulary carries through unchanged
(`note_not_found`, `note_conflict`, `invalid_note_ref`, …).

## Handling failure in a script

Branch on the exit code:

```bash
#!/usr/bin/env bash
set -uo pipefail        # not -e — we want to inspect the code

kaya note get "$REF" >/tmp/note.txt
case $? in
  0) echo "found it" ;;
  3) echo "token is bad, check kaya config show"; exit 1 ;;
  4) echo "not yours, skipping"; exit 0 ;;
  5) echo "no such note, nothing to do"; exit 0 ;;
  6) echo "changed under us — re-read and retry"; exit 1 ;;
  *) echo "unexpected failure"; cat /tmp/note.txt; exit 1 ;;
esac
```

!!! warning "`set -e` and exit codes do not mix well here"

    With `set -e`, a `3` from `kaya` kills the script before you can distinguish it from a `5`.
    Drop `-e` around the calls you want to inspect, or guard them with `|| true` and read `$?`.

Distinguish "no results" from "failed" — an empty result is a success:

```console
$ kaya note list --q "no such term"
no notes
$ echo $?
0
```

A search that matches nothing exits `0` with a zero-count summary. Only a genuine failure is
non-zero, so `if kaya note list …` doesn't treat an empty result as broken.

## Nothing prompts

No verb in this CLI ever reads standard input or asks a question — not `note delete` (there's no
`--yes` to pass, because a flag you must always pass isn't a confirmation), not `config set`, none
of them. A CI job that runs `kaya` behind a closed stdin gets a structured refusal instead of a
hang, on every verb, without special-casing any of them.

## Recap

- `3`/`4`/`5`/`6` for unauthorized, forbidden, not-found, conflict. `2` for usage (including the
  API's `400`/`422`). `1` for everything else, including "no token configured".
- Errors are one tab-separated row on stdout, or `{"error": {…}}` under `json`/`toon`.
- An empty result is exit `0`, not a failure.
- Nothing ever prompts, on any verb.
