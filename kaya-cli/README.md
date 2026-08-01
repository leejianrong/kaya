# kaya-cli

The `kaya` console script. Distribution name `kaya-notes`, one entry point, no verbs yet.

```bash
uv sync --all-extras
uv run kaya            # prints what it is and what hasn't landed, exits 0
uv run pytest -q
uv run ruff check .
```

An adapter's whole job is turning argv into a `kaya-client` call and printing what comes back
([ADR 0004](../docs/adr/0004-shaping-lives-in-the-shared-client.md)). Projection, truncation,
aggregates and serialization all live in `kaya-client`'s `render()`. If a formatting rule starts
growing in this package, that is the bug ADR 0004 exists to prevent.

Verbs, `--format {human,json,toon}`, the named exit-code table and the build-stamped `--version`
all arrive in V2a. Until then this is a skeleton with one command in it.
