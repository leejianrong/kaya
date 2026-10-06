<!--
title: "Get started"
description: Sign in, install the kaya CLI, and write your first note.
-->

# Get started

kaya is a cloud-hosted markdown notes app, API-first and agent-drivable. The web UI is one client
among several: a REST API sits underneath it, and this page is about the command-line client on
top of that API, `kaya`.

By the end of this page `kaya note list` will print your notes.

## Sign in

kaya has its own accounts and its own tokens. You sign in to the web app with GitHub, and kaya
never needs pandan to do that or anything else on this page. Open your deployment (the hosted one
is [kaya-jian.fly.dev](https://kaya-jian.fly.dev)) and choose **Sign in with GitHub**. That
creates your kaya account the first time and starts a browser session after that.

The web app has three ways to look at a note, switched with the **Read | Edit | Split** control.
Split puts the editor and the rendered note side by side and only appears on wide screens. On a
phone the list and the note are separate screens, and a formatting toolbar sits above the keyboard
while you edit. The CLI and the browser read the same notes.

The CLI and agents use a `kaya_pat_…` personal access token instead of a browser session. There
are two ways to get one, and the next sections cover both.

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
kaya 0.22.0 (b2ce2eff8b9be351660cbc1e79fe114ed5a1a88d)
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
kaya 0.22.0 (source checkout, not a released build)
```

## Point it at a deployment and sign in

With nothing configured, kaya talks to `http://localhost:8000`, which is what `make up` and
`make dev` serve from a checkout. Point it at a real deployment first:

```bash
kaya config set --api-url https://kaya-jian.fly.dev
```

Then sign in with the device flow:

```bash
kaya auth login
```

It prints a link and a short code, tries to open your browser, and waits. Approve the request on
the page that opens (you sign in with GitHub there if you are not already). The CLI then writes
the `kaya_pat_…` token it was given straight into the config file. The token is never printed,
so there is nothing to copy. `--scope read` requests the `read` scope instead of the default `write`.

!!! tip "Prefer to mint a token by hand?"

    Open **Settings > Tokens** in the web app (the page lives at `/tokens`), name a token after
    the machine or agent that will use it, pick `read` or `write`, and copy the `kaya_pat_…`
    secret. It is shown once, because kaya stores only a hash. Lose it and you revoke it from the
    same page and mint another. Then save it with
    `kaya config set --token 'kaya_pat_…'`. This is also where you revoke a token you no longer
    trust, including one `kaya auth login` made for you.

Two more auth verbs round it out. `kaya auth check` says whether a token is configured and where
it comes from (`environment` or `file`), and `kaya auth logout` removes the stored token from the
config file. Logout cannot revoke a token that came from `KAYA_TOKEN`, and it does not revoke the
token on the server either, so revoke it under Settings > Tokens if you want it dead.

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

Notice the token's row: it is `set` or `not set`, never a value or a fragment of one. A truncated
token is still a token, and the honest way to check *which* one you have is to make a request and
read the `401` if it's wrong.

!!! tip "Prefer an environment variable?"

    `KAYA_API_URL` and `KAYA_TOKEN` work too, and win over the config file if both are set —
    resolution happens independently per key. That's the better fit for CI, where you don't want a
    token written to disk:

    ```bash
    export KAYA_API_URL=https://kaya-jian.fly.dev
    export KAYA_TOKEN='kaya_pat_…'
    ```

See [Configuration](../cli/configure.md) for the full precedence and every key kaya reads.

## Your first commands

```console
$ kaya --version
kaya 0.22.0 (b2ce2eff8b9be351660cbc1e79fe114ed5a1a88d)

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
# 1. install the CLI
mkdir -p ~/.local/bin
curl -fsSL -o ~/.local/bin/kaya \
  https://github.com/leejianrong/kaya/releases/latest/download/kaya-linux-x86_64
chmod +x ~/.local/bin/kaya

# 2. point it at a deployment and sign in through the browser
kaya config set --api-url https://kaya-jian.fly.dev
kaya auth login

# 3. write and read your first note
kaya note create "Groceries" --body $'milk\neggs' --path home/groceries.md
kaya note list
```

pandan is optional. If you also keep a pandan board, you can link a pandan account under
**Settings > Pandan connection** so that board embeds and `[[KAN-n]]` wikilinks show live cards.
Nothing else needs it, and without the link those wikilinks simply render as unresolved. See
[Agents and MCP](../agents/index.md) if you want an agent to use kaya, over the hosted MCP
endpoint or the CLI.

From here, [Using the CLI](../cli/index.md) covers every verb, all three output formats, and the
exit codes a script can branch on.
