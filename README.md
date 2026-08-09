# kaya

A cloud-hosted, Obsidian-like **markdown notes** app, API-first and agent-drivable. It is the docs
half of the `kayatoast` suite, sibling to [pandan](https://github.com/leejianrong/pandan), the kanban
board. Where pandan tracks *work*, kaya holds the *knowledge*: specs, notes, runbooks, meeting notes,
cross-linked to the board.

> **Status: the CLI is finished; the product has no interface and nowhere to live.** A pandan PAT
> creates, reads, edits and deletes notes over `/api/v1/notes`, and the whole stack ships as one
> container image serving the SPA and the API from a single origin. **`kaya` drives all of it from a
> shell** — `note {list,get,create,edit,move,delete}` and `config {set,show,path}`, in `human`,
> `json` or `toon` — and ships as a downloadable binary. What is missing is the two ends: the SPA is
> still a shell page, the MCP adapter is still empty, and **there is no hosted deployment to point
> anything at** (see *Where to point it*, below).
> See [`docs/PLAN.md`](docs/PLAN.md) for what is being built,
> [`docs/SLICES.md`](docs/SLICES.md) for the order, and [`CLAUDE.md`](CLAUDE.md) for what is
> genuinely in each package today. Work is tracked on pandan board 18.

## Install the CLI

The [latest release](https://github.com/leejianrong/kaya/releases/latest) carries one asset,
`kaya-linux-x86_64`: a single self-contained executable, **Linux x86_64, glibc 2.28 or newer** —
Ubuntu 20.04+, Debian 11+, RHEL/Rocky/Alma 8+, Amazon Linux 2023. There is no macOS or Windows
build — a onefile artifact is per-platform, and the pipeline ships only what one build can prove.

```bash
mkdir -p ~/.local/bin
curl -fsSL -o ~/.local/bin/kaya \
  https://github.com/leejianrong/kaya/releases/latest/download/kaya-linux-x86_64
chmod +x ~/.local/bin/kaya
```

The asset is named for the downloads folder it lands in; the command is `kaya`. Check what you
actually got:

```console
$ kaya --version
kaya 0.9.0 (a1b2c3d)
```

The sha is the commit it was built from, and a build that did *not* come from the release pipeline
says `source checkout, not a released build` instead of staying quiet — that is the whole of
[ADR 0007](docs/adr/0007-release-provenance-from-the-first-release.md), and the line is worth
pasting into any bug report. Want a shorter name? `ln -sf ~/.local/bin/kaya ~/.local/bin/ky`; there
is deliberately no second console script.

### Where to point it

**There is no hosted kaya, so you have to run one.** This is [ADR
0010](docs/adr/0010-no-hosted-deploy-until-the-homelab.md) on purpose, not an omission: the image
and the Kubernetes manifests are built and exercised locally, and the k8s homelab is kaya's first
real deploy. Until then the only origin that exists is one you start yourself, from a checkout with
Docker:

```bash
make up                                     # db + migrate + the app image, one origin on :8000
```

If ports `5432` or `8000` are already taken on your machine, pass your own:
`KAYA_DB_PORT=5434 KAYA_APP_PORT=8010 make up`.

Then give the CLI an origin and a credential:

```bash
export KAYA_API_URL=http://localhost:8000   # the default, and what `make up` serves
export KAYA_TOKEN=…                         # a pandan PAT — kaya mints none of its own (ADR 0002)
kaya                                        # your five most recent notes, and what to do next
kaya note list --fields ref,title,path
kaya note create "A title" --body-file notes/draft.md
kaya note get NOTE-12 --format json
```

`kaya config set --api-url …` writes those to a config file instead, and `kaya config show`
reports what resolved and from which tier — it never prints the token, only whether there is one.
All nine verbs are live; [`kaya-cli/README.md`](kaya-cli/README.md) has the formats, the error
contract and the exit codes.

## What it will do

Write markdown in a real editor, organise notes in folders, search the full text, and link notes to
each other with `[[wikilinks]]`. A wikilink can also point at board work: `[[KAN-12]]` renders the
card's title and column inline, and a backlinks panel answers "which notes mention this card".

The same PAT that drives the board drives the notes, from the same config, with no second login and
no second token. An agent working `KAN-12` reads its spec note, edits it, and moves the card, using
one credential throughout.

## The plan

| Document | What it holds |
|---|---|
| [`docs/PLAN.md`](docs/PLAN.md) | Problem, solution, scope, requirements, the shape, affordances, testing approach, open risks |
| [`docs/SLICES.md`](docs/SLICES.md) | Seven vertical slices, each with a build plan and acceptance criteria |
| [`docs/QUESTIONS.md`](docs/QUESTIONS.md) | The decision register: what was decided, what is a default, what is deferred |
| [`docs/adr/`](docs/adr/) | Ten architectural decisions, with what was rejected and why |
| [`docs/kaya-vision.md`](docs/kaya-vision.md) | The founding statement of intent, kept verbatim |

Start with `PLAN.md`. The ADRs worth reading first are
[0002 (identity)](docs/adr/0002-identity-pandan-as-provider.md) and
[0004 (why payload shaping lives in the shared client)](docs/adr/0004-shaping-lives-in-the-shared-client.md).
Between them they carry most of what makes this project different from a generic notes app.

## Development

Needs `uv` (Python 3.12), Node 20.19+ and Docker.

```bash
make hooks         # install the pre-push gate (do this once)
make install       # uv sync every Python package, npm ci the SPA
make dev           # Postgres, backend on :8000, SPA on :5173
make up            # the whole stack from the container image, one origin on :8000
make k3d           # deploy/k8s on a local k3d cluster, then prove the pod serves
make test          # the fast, no-infra layer
make check         # everything pre-push runs
make help          # every target, including the one still stubbed
```

There is no hosted deployment, on purpose: the image and the Kubernetes manifests are built and
exercised locally, and the k8s homelab is kaya's first and only deploy
([ADR 0010](docs/adr/0010-no-hosted-deploy-until-the-homelab.md)).

Five packages in one repo (`backend/`, `frontend/`, `kaya-client/`, `kaya-cli/`, `mcp/`) with the
dependency arrow pointing one way: adapters depend on the client, and nothing depends on an adapter
([ADR 0001](docs/adr/0001-stack-inherited-from-pandan.md)).

Conventions, commands and the traps worth knowing live in [`CLAUDE.md`](CLAUDE.md), which is written
for coding agents and is equally the fastest orientation for a person.

## Licence

Apache License 2.0. The full text is in [`LICENSE`](LICENSE).
