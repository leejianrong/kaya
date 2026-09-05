<!--
title: "Reference"
description: Where kaya's API schema actually lives — a running instance's own /docs, not a page here.
-->

# Reference

kaya has no separate hosted API reference. The schema lives on the running instance itself, and
that's the authoritative, always-current source — not a copy maintained on this site:

```
GET /docs          # interactive OpenAPI UI
GET /openapi.json  # the raw schema
```

Point either at whichever instance you're talking to — the maintainer's own hosted kaya, or one you
run yourself. This is deliberate, not an oversight: kaya is one FastAPI app serving `/api/v1` directly
([ADR 0001](https://github.com/leejianrong/kaya/blob/main/docs/adr/0001-stack-inherited-from-pandan.md)),
and every route's request/response shape is already generated from the same Pydantic models the app
runs with. A second, hand-maintained copy of that surface on this site would drift from the code the
moment either one changed, and there's no mechanism that would catch it. The running instance's own
`/docs` cannot drift from itself.

## What's here instead

This page is a map to where the real reference material lives, not a restatement of it:

| What you want | Where it is |
| --- | --- |
| The full endpoint list, request/response schemas, status codes | A running instance's `/docs` and `/openapi.json` |
| How note identity works (`NOTE-n` refs, why path isn't identity) | [ADR 0008](https://github.com/leejianrong/kaya/blob/main/docs/adr/0008-note-identity.md) |
| How authentication resolves a caller | [ADR 0002](https://github.com/leejianrong/kaya/blob/main/docs/adr/0002-identity-pandan-as-provider.md), and [Agents & MCP → Authentication](../agents/index.md#authentication) |
| Every CLI verb and its exit codes | [Using the CLI](../cli/index.md), [Errors and exit codes](../cli/errors-and-exit-codes.md) |
| Every MCP tool and the CLI verb behind it | [`mcp/README.md`](https://github.com/leejianrong/kaya/blob/main/mcp/README.md) |
| Why kaya's decisions are shaped the way they are | [About](../about/index.md) |

## Trying a request

Every `/api/v1` request needs a bearer token — the same `pandan_pat_…` token from
[get started](../get-started/index.md#get-a-token):

```bash
curl -H "Authorization: Bearer $KAYA_TOKEN" \
  https://your-kaya-instance/api/v1/notes
```

`401` means the token didn't resolve against pandan; `403` means it resolved but doesn't own (or
share a team with) the note in question; `404` means no such note exists at all. The exact shape of
every error body — `{"error": {"code", "message", …}}`, everywhere, including a route the framework
itself returns a bare 404/405 for — is worth relying on precisely because it's uniform; see a running
instance's `/openapi.json` for the schema behind it rather than this page's word for it.
