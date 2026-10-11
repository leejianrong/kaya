# ADR 0017 — Workspaces and a READ < WRITE < MANAGE access ladder

- **Status:** Accepted
- **Date:** 2026-10-11
- **Deciders:** Jian
- **Context source:** the 2026-10-11 auth-parity discussion (EPIC-326 on board 18, cards KAY-174 to
  KAY-176). **Supersedes [ADR 0011](0011-team-scoped-notes.md)** and amends
  [ADR 0003](0003-cross-linking-one-way-soft.md) and [ADR 0008](0008-note-identity.md). Mirrors pandan
  [ADR 0021](https://github.com/leejianrong/pandan/blob/main/docs/adr/0021-organization-workspace-tier.md)
  (the workspace tier) and [ADR 0013](https://github.com/leejianrong/pandan/blob/main/docs/adr/0013-board-authorization.md)
  (the `Access` ladder).

## Context

Kaya's authorization is binary: a note's owner, or (ADR 0011) a member of the note's pandan team. The
team half asks pandan on every request, soft-fails to "no access" when pandan is down, and has no
roles. The maintainer wants workspaces owned by kaya itself, with three access levels, so that a group
of people can read, write or manage a shared set of notes without kaya calling anyone.

The fork was how a workspace relates to notes, given that a folder is only a path prefix (ADR 0008's
2026-10-10 amendment says there is no folder table and must never be one):

- **A. The workspace owns notes explicitly** (`note.workspace_id`); folders stay a UI convention inside it.
- **B. The workspace owns path prefixes**, so a note's path decides who can read it.
- **C. A real `folder` table** carrying the workspace.

## Decision

**Option A.** A note belongs to a workspace by an explicit column, never by where its path points.

### Shape

- **`workspace`**: `id`, `name`, `created_at`, `updated_at`. No `owner_id`, like pandan: a workspace is
  administered by whoever holds the `owner` role.
- **`workspace_member`**: `workspace_id`, `user_id` (a `kaya_account.id`), `role`,
  `UNIQUE(workspace_id, user_id)`, both foreign keys `ON DELETE CASCADE`. Roles are `viewer`, `editor`,
  `owner`.
- **`note.workspace_id`**: nullable foreign key. `NULL` means a personal note, which is every note
  today. The foreign key is `ON DELETE RESTRICT`: a workspace that still holds notes cannot be deleted
  (`409`). Pandan unclaims boards with `SET NULL`, but unclaiming here would hand each note back to
  its creator as a personal note, a silent change of who can read it.
- **`note.team_id` and the `team` table are dropped** with their resolver, cache and upstream
  (`app/auth/team_*.py`). No data is carried over: kaya never held team membership, and every existing
  note's `owner_id` is already unreachable after the ADR 0012 cutover (BREADBOARD R19). The deploy
  checklist gets a step to count rows with `team_id IS NOT NULL` before the migration runs.

### The access ladder

`Access` is an ordered enum, `READ < WRITE < MANAGE`, and `authorize_note(principal, note, require)`
takes the level the action needs. The role mapping is pandan's: `viewer` → `READ`, `editor` → `WRITE`,
`owner` → `MANAGE`.

| Note | Check | Result |
|---|---|---|
| personal (`workspace_id IS NULL`) | `owner_id == principal.id` | `MANAGE` |
| personal | anyone else | `403` |
| in a workspace | the principal's `workspace_member` role, mapped | that level |
| in a workspace | not a member | `403` |
| any | missing | `404` |

Two differences from pandan, both deliberate:

1. **In a workspace, `note.owner_id` grants nothing.** It records who created the note. Access comes only
   from membership, so removing someone from a workspace removes their access to what they wrote there.
   Pandan's board owner keeps `MANAGE` regardless; a workspace note has no equivalent, because "I wrote
   it" should not outlive "I belong here".
2. **There is no explicit per-note share** to sit between the owner and the workspace default, as there
   is in pandan (`board_member`). Q8 stays: no per-note ACLs.

What each level allows:

| Level | Allows |
|---|---|
| `READ` | read, search, list, history, backlinks, attachments download |
| `WRITE` | create, edit, move within the workspace, format, delete a note, upload attachments |
| `MANAGE` | rename or delete the workspace, add, change or remove members |

`delete` is `WRITE`, as it is for pandan's cards. The `write-no-delete` token preset (KAY-141) already
caps that for agents. A workspace must always keep at least one `owner`; demoting or removing the last
one is a `409`.

Moving a note between containers (personal to workspace, or between workspaces) needs `MANAGE` on the
source and `WRITE` on the destination, and is its own verb, never a side effect of `PATCH path`.

### Paths and folders belong to a container

A `path` is relative to its container. The same folder names can exist in a personal space and in each
workspace and mean nothing across them. The tree the SPA draws is one container at a time, chosen with a
switcher. `POST /notes/move-folder` is scoped to a container the same way, and rewrites only that
container's notes. This keeps ADR 0008 intact: `path` is still a mutable label and moving a note inside a
container is still one `PATCH`. It also means there is no way to move a note into someone else's
workspace by dragging it onto a folder name.

### Queries

`notes_owned_by` becomes the one visibility query: personal notes the caller owns, **or** notes whose
`workspace_id` is in the caller's memberships, as a SQL subquery on `workspace_member`. Kaya now has the
membership table locally, so ADR 0011's "a plain set of integers, never a subquery" no longer applies and
the call-site plumbing that carried `team_ids` goes away. `test_no_unscoped_note_query.py` widens to accept
exactly this shape and nothing else.

### Wikilinks and the graph

A link is resolved within its source note's container: a workspace note resolves `[[Title]]` among that
workspace's notes, a personal note among its owner's personal notes. A link across containers stays
unresolved. Resolving across them would let a reader learn a title they cannot open. `note_link` keeps
its rule that a backlink is found by `resolved_id`, and a read still filters targets and sources through
`notes_owned_by`, so an edge to a note the caller cannot read is dropped from what they see. The graph is
the same query. Cross-container links are a known limitation, not a bug.

### Members

Added by `user_id` or email, owner-role only, as in pandan. An email with no kaya account is a `404`.
That lets a workspace owner test whether an email has signed in. Pandan accepts the same leak, the
endpoint sits under the `write` rate-limit tier (KAY-169), and an invite-by-link flow is the proper fix,
deferred.

### What pandan still does

Nothing about authorization. The linked pandan credential remains for board embeds and `[[KAN-n]]`
resolution only. The kaya `GET /api/v1/workspaces` is kaya's own; it has nothing to do with pandan's of
the same name.

## Consequences

- **Kaya's last authorization dependency on pandan is gone.** ADR 0003's rule "nothing in kaya may block
  on pandan" now holds for access control as well as identity. Permission questions are answered from
  kaya's own tables.
- **A big, additive-then-destructive migration**: new tables and column first, then the team drop. No
  data migration. Personal notes behave exactly as before.
- **Surface**: REST for workspaces and members, `kaya workspace …` CLI verbs, MCP tools (a subset of the
  CLI, per `mcp/README.md`), an SPA switcher with member management and role-aware controls. KAY-175.
- **Token narrowing** (a PAT allow-list of workspaces, pandan ADR 0024) is a later slice, KAY-176. A
  token's rights are then the intersection of the owner's role, the token scope and the allow-list, and
  it can only remove access.
- **Notifications, per-workspace limits, billing and a second tenant tier above workspaces** are out of
  scope, as in pandan ADR 0021.

## Alternatives considered

- **B, path-prefix ownership.** Closest to the original wording ("folders and the notes under them"), but
  it makes a note's ACL depend on a mutable label: one `PATCH path` or a folder rename silently moves a
  note across a permission boundary, and a mistyped path can publish it. It also breaks ADR 0008's
  "moving a note is one column and nothing else changes".
- **C, a folder table.** Ruled out by ADR 0008's amendment, and a large change to the tree, move-folder
  and the client-only placeholder logic for a benefit A already gives.
- **`SET NULL` on workspace delete.** Pandan's choice for boards. Rejected here, see Shape.
- **Keep teams and add roles to the pandan lookup.** Rejected: it keeps the soft-fail and the cache and
  gives roles pandan does not have.
- **A per-note explicit share.** Still not decided; nothing here forecloses a rung between the workspace
  default and `403` later.
