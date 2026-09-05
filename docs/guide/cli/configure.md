<!--
title: "Configuration"
description: How the CLI resolves its settings, how kaya config set writes the file safely, and the token-safety rules.
-->

# Configuration

The CLI resolves three keys: an API origin, a pandan token, and how much prose a read returns
before it's cut.

## Where settings come from

Two tiers, checked **independently per key**, first non-empty value wins:

1. Environment variables — `KAYA_API_URL`, `KAYA_TOKEN`, `KAYA_MAX_TEXT_CHARS`
2. The config file — `$XDG_CONFIG_HOME/kaya/config.json`, or `~/.config/kaya/config.json`

"Independently" is the load-bearing word: a shell that exports only `KAYA_TOKEN` does not thereby
discard the `api_url` you already wrote to the file, because each key is resolved on its own.

!!! note "A third tier is named but not built"

    kaya's design leaves room for a third tier — the nearest `.mcp.json` up the directory tree,
    matching how pandan reads one for its own CLI. It was deliberately not implemented: which entry
    in an MCP host's config file names kaya is a guess until there's a server to be named, and
    building a reader before that would fix the answer in a package that can't yet see the
    question. An MCP host that launches a server usually exports its `env` block anyway, which
    already reaches the CLI through tier one.

## Setting a token

```bash
kaya config set --api-url https://kaya-jian.fly.dev --token 'pandan_pat_…'
```

`--token` puts the secret in argv, which is visible in shell history and briefly to `ps`. It's
offered anyway because the alternative — hand-editing the JSON file — is a config file people
corrupt, and the file is written `0600` either way. If that trade doesn't suit you, prefer the
environment variable instead: `KAYA_TOKEN` never touches disk and wins over the file regardless.

!!! danger "There is no other way to clear a value"

    `config set` only ever adds or overwrites a key. To remove one, edit the JSON file directly —
    kaya has no `config unset`.

### The read-modify-write merge

`config set` writes only the keys you name, and preserves every other key already in the file —
including one `kaya config set` has no flag for at all, like `max_text_chars`, which you can only
set by hand or via the environment variable. That preservation is the whole reason the file is
JSON and not hand-rolled: a writer that serialized only what it was told about would silently
delete anything it didn't recognise, on the first `config set` after you'd hand-edited the file.

The write itself is atomic — written to a sibling temporary file and renamed into place — so an
interrupted write leaves the old file intact rather than truncated.

## Inspecting the effective configuration

```console
$ kaya config show
api_url         https://kaya-jian.fly.dev      file
token           set                            file
max_text_chars  500                            default

3 settings

help: kaya config set --api-url <url> --token <pat>
```

There's no header row — `key`/`value`/`source` are the columns, in that order, on every line.

The `source` column answers "why is this the value?" — `environment`, `file`, or `default`. Without
it, a file you've just edited and a shell that still exports the old value look identical; with it,
the mismatch is one column, not a guess.

**The token's row is always `set` or `not set`, never a value or a fragment of one.** A truncated
token is still a token, so there is no prefix, no suffix, and no length shown. The only honest way
to check whether the token you *think* is configured is the right one is to make a request and read
the `401` if it isn't.

```console
$ kaya config path
path    /home/you/.config/kaya/config.json
exists  true

help: kaya config set --api-url <url> --token <pat>
```

`config path` answers even when the file's contents can't be parsed, or don't exist yet — the verb
whose whole job is "which file do I fix?" must never be the verb that refuses to run.

## No token configured

```console
$ kaya note list
error	no_credential	no kaya token configured — set KAYA_TOKEN to a pandan personal access token, or put one under 'token' in the config file	KAYA_TOKEN
$ echo $?
1
```

That's exit `1`, not `3`. Nothing was refused, because nothing was asked — a script that reacted to
`3` here would be minting a fresh PAT to fix a missing line of configuration.

## Truncation limit

Prose (a note's `body`) is cut at **500 characters** by default, with a hint saying how much was
dropped. Raise or disable the limit for every command:

```bash
export KAYA_MAX_TEXT_CHARS=2000    # a higher cap
export KAYA_MAX_TEXT_CHARS=0       # no truncation at all
```

`0` is a value, not an absence — it's what `--full` resolves to for a single command. A value
that isn't a non-negative whole number is a usage error naming which tier it came from. See
[output formats](output-formats.md#truncation) for how the hint itself reads.

## Recap

```bash
# one-time setup
kaya config set --api-url https://kaya-jian.fly.dev --token 'pandan_pat_…'

# check it
kaya config show
kaya config path
```

Settings resolve independently, environment first and the config file second. Keep the token in
the file for a machine you use daily; use the environment variable in CI, where you don't want a
credential on disk at all.
