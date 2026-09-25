<!--
title: "Get started"
description: Install the kaya CLI, get a pandan token, and write your first note.
-->

# Get started

kaya is a cloud-hosted markdown notes app, API-first and agent-drivable. The web UI is one client
among several — a REST API sits underneath it, and this page is about the command-line client on
top of that API, `kaya`.

By the end of this page `kaya note list` will print your notes.

## Get a token

kaya has no login of its own. It has no account system, no password, and no token format it mints
itself — every request is authenticated by forwarding your bearer to
[pandan](https://github.com/leejianrong/pandan)'s `GET /api/v1/me` and trusting pandan's answer.
One account and one set of personal access tokens cover both apps, which is the whole point: an
agent maintaining a note about a card uses the same credential it uses to move the card.

So before you can talk to kaya, you need a pandan account and a pandan personal access token
(`pandan_pat_…`):

1. Log in to a pandan board — the hosted one at
   [simple-kanban-jian.fly.dev](https://simple-kanban-jian.fly.dev), or your own self-hosted
   instance.
2. Open the **Tokens** tab in pandan's top bar.
3. Create a token, name it after the machine or agent that will use it, and copy the
   `pandan_pat_…` secret. It is shown once.

!!! danger "The secret is shown once"

    pandan stores only a hash of the token, so it cannot show it to you again. Lose it and you
    revoke it and mint another, from the same Tokens tab.

Hold on to that token — you'll hand it to kaya in a moment. If pandan is ever unreachable, an
already-cached token keeps working for a short while, but a token kaya has never seen before
cannot authenticate until pandan answers. That is the one thing in kaya that depends on pandan
being up.

## Install the CLI

=== "Prebuilt binary"

    The release ships a single self-contained executable — no Python, no virtualenv.

    ```bash
    mkdir -p ~/.local/bin
    curl -fsSL -o ~/.local/bin/kaya \
      https://github.com/leejianrong/kaya/releases/latest/download/kaya-linux-x86_64
    chmod +x ~/.local/bin/kaya
    ```

    **Linux x86_64, glibc 2.28 or newer** only — Ubuntu 20.04+, Debian 11+, RHEL/Rocky/Alma 8+,
    Amazon Linux 2023. There is no macOS or Windows build: the asset is a PyInstaller `--onefile`
    executable, which is per-platform by construction, and the pipeline claims only what one build
    can prove. On an older distribution, or on musl (Alpine), install with `uv` instead.

    !!! tip "`kaya` not found?"

        `~/.local/bin` has to be on your `PATH`. If it isn't:

        ```bash
        echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && exec bash
        ```

=== "uv tool install"

    Needs Python and [uv](https://docs.astral.sh/uv/). `kaya-cli` isn't published to PyPI yet, so
    install straight from the repository — `uv` resolves the sibling `kaya-client` package from
    the same checkout, so there is nothing to clone by hand:

    ```bash
    uv tool install "git+https://github.com/leejianrong/kaya.git#subdirectory=kaya-cli"
    ```

    This is the path to pick on a platform with no prebuilt asset — macOS, Windows, an Intel Mac,
    or Alpine/musl.

### Check it worked

```console
$ kaya --version
kaya 0.15.0 (b2ce2eff8b9be351660cbc1e79fe114ed5a1a88d)
```

The parenthesised value is the commit the binary was built from — this is why the release exists
at all ([ADR 0007](https://github.com/leejianrong/kaya/blob/main/docs/adr/0007-release-provenance-from-the-first-release.md)):
a binary on `PATH` that can't say which commit it came from is indistinguishable from stale source,
which cost the sibling project two false bug reports before anyone suspected the binary. Paste this
line into any bug report you file.

A source checkout prints the honest alternative instead, never a bare number and never an invented
sha:

```console
$ kaya --version
kaya 0.15.0 (source checkout, not a released build)
```

## Point it at a deployment and save your token

With nothing configured, kaya talks to `http://localhost:8000` — what `make up` and `make dev`
serve from a checkout. Point it at a real deployment and save your token in one command:

```bash
kaya config set --api-url https://kaya-jian.fly.dev --token 'pandan_pat_…'
```

`config set` is a read-modify-write: it merges the keys you named into
`$XDG_CONFIG_HOME/kaya/config.json` (or `~/.config/kaya/config.json`) without touching anything
else already in the file, and writes it `0600` so only you can read it. Check what actually
resolved:

```console
$ kaya config show
api_url         https://kaya-jian.fly.dev      file
token           set                            file
max_text_chars  500                            default

3 settings
```

(There's no header row — `key`/`value`/`source` are the columns, in that order, on every line.)

Notice the token's row: it is `set` or `not set`, never a value or a fragment of one — a truncated
token is still a token, and the honest way to check *which* one you have is to make a request and
read the `401` if it's wrong.

!!! tip "Prefer an environment variable?"

    `KAYA_API_URL` and `KAYA_TOKEN` work too, and win over the config file if both are set —
    resolution happens independently per key. That's the better fit for CI, where you don't want a
    token written to disk:

    ```bash
    export KAYA_API_URL=https://kaya-jian.fly.dev
    export KAYA_TOKEN='pandan_pat_…'
    ```

See [Configuration](../cli/configure.md) for the full precedence and every key kaya reads.

## Your first commands

```console
$ kaya --version
kaya 0.15.0 (b2ce2eff8b9be351660cbc1e79fe114ed5a1a88d)

$ kaya note create "Groceries" --body $'milk\neggs' --path home/groceries.md
ref          NOTE-12
title        Groceries
path         home/groceries.md
created_at   2026-09-05T04:12:03+00:00
updated_at   2026-09-05T04:12:03+00:00

milk
eggs

help: kaya note edit <ref> --body-file <path>

$ kaya note list
NOTE-12  Groceries  home/groceries.md

1 note

help: kaya note get <ref>
help: kaya note create <title>
```

The ref, `NOTE-12`, is the note's identity from here on — its path is just metadata, and moving it
later never changes the ref. Read it back with `note get`, in whichever format suits the caller:

```console
$ kaya note get NOTE-12 --format json
{"ref":"NOTE-12","id":12,"title":"Groceries","body":"milk\neggs","path":"home/groceries.md","created_at":"2026-09-05T04:12:03+00:00","updated_at":"2026-09-05T04:12:03+00:00","team_id":null}
```

The `help:` lines above are suggestions for what to run next — every result carries them under the
default `human` format, so an agent can find its way around without a manual.

## Recap

```bash
# 1. mint a pandan_pat_… token in pandan's Tokens tab

# 2. install the CLI
curl -fsSL -o ~/.local/bin/kaya \
  https://github.com/leejianrong/kaya/releases/latest/download/kaya-linux-x86_64
chmod +x ~/.local/bin/kaya

# 3. point it at a deployment and save the token
kaya config set --api-url https://kaya-jian.fly.dev --token 'pandan_pat_…'

# 4. write and read your first note
kaya note create "Groceries" --body $'milk\neggs' --path home/groceries.md
kaya note list
```

From here, [Using the CLI](../cli/index.md) covers every verb, all three output formats, and the
exit codes a script can branch on.
