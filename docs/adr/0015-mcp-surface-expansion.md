# ADR 0015 — Expand the MCP surface so an agent can run knowledge management

- **Status:** Accepted (2026-09-30)
- **Deciders:** Jian
- **Context source:** competitive research and vision, written up in pandan's
  `docs/competitive-research-and-vision-2026-09.md`. Amends ADR 0006 (MCP surface born narrow and
  frozen). Mirrors pandan ADRs 0019 (surface right-sizing), 0027 (agent token scopes) and 0028
  (approval policy).

## Context

ADR 0006 pinned the MCP at six tools (`list_notes`, `get_note`, `search_notes`, `get_backlinks`,
`create_note`, `edit_note`) and tied it to the CLI by a parity test. It rested on pandan's measurement
that resident schema was the small cost and per-call payload the large one. That reasoning still holds,
and it also says a wider surface is affordable if reads stay shaped.

The maintainer wants agents able to run the knowledge management: orient in a large corpus, edit a
section without rewriting a page, reorganise, and keep the wiki healthy. Six tools cannot do that. There
is no delete, move, version, or export tool, `GET /notes` has no paging, and `edit_note` replaces a whole
body. The research found the same direction elsewhere: Obsidian's heading-scoped PATCH and document map,
Outline's patch tool and breadcrumbs, Notion's markdown-first agent API.

## Decision (proposed)

1. **Grow to about 15 tools, and stay bounded.** Adding a tool remains an amendment to this ADR, not a
   fixture edit, and the resident schema is re-measured with the same script style pandan uses.
2. **Prefer few expressive tools over many narrow ones.** `edit_note` takes a list of operations
   (`replace_section`, `append_to_section`, `insert_after`, `set_frontmatter`, `replace_body`) instead
   of one tool per operation. `get_note` gains a `section` argument.
3. **Additions** (nine, taking the total from 6 to 15):

   | Tool | Purpose |
   |---|---|
   | `note_outline` | Heading map of one note, so an agent reads only what it needs |
   | `list_tree` | Folder tree with counts, paged |
   | `recent_changes` | What changed since a timestamp, with actor |
   | `move_note` | Rename or move, rewriting inbound wikilinks |
   | `delete_note` | Soft delete into a trash (see preconditions) |
   | `list_versions` | Version list with actor |
   | `diff_version` | Diff between two versions |
   | `restore_version` | Restore, recorded as a new version |
   | `health_check` | Orphans, unresolved wikilinks, stale notes, duplicate titles |

4. **CLI first.** Every new verb lands in the CLI before the MCP, and the parity test keeps MCP as a
   subset of the CLI.
5. **Every write is preconditioned and returns a compact receipt.** `if_updated_at` is required, the 409
   payload stays, and write responses do not echo the body.
6. **`health_check` is read-only.** It reports orphans, unresolved
   wikilinks with candidate matches, duplicate titles, empty notes, stale notes (threshold is an
   argument) and broken card refs, each with a short next-step hint. Card refs are reported as
   "unchecked" when pandan is unreachable, never as errors (ADR 0003). Agents fix findings with the
   ordinary tools, so every fix keeps its precondition, token scope, version and audit trail. A
   one-call fix mode is rejected: it would bypass per-edit review and make the widest possible write.
7. **`move_note` has a `dry_run` flag** that lists the links it would rewrite and changes nothing.
8. **Reads stay shaped.** `fields`, `full`, small default page sizes, breadcrumbs and summaries in list
   results. Shaping remains in `kaya-client` (ADR 0004).

## Preconditions, in order

1. **Actor on note versions** (who, and through which token). Without it a bad agent edit cannot be
   attributed.
2. **A trash** (soft delete and restore) before `delete_note` is exposed at all.
3. **Paging on `GET /notes`.**
4. **Kaya token presets** mirroring pandan ADR 0027: read-only, no-delete, and a scope for structural
   changes (move, delete).
5. **Re-measure resident tokens**, and record the number here as the new ceiling.

## Consequences

- Agents can maintain a knowledge base end to end, with undo available through versions and the trash.
- ADR 0006's "frozen at six" is superseded by "bounded and measured", and its parity rule stays.
- A follow-up ADR covers proposed edits (agent changes to critical notes arriving as diffs a human
  accepts). It would reuse pandan's approval mechanism (ADR 0028) and is out of scope here.

## Open questions

- Is `export` needed over MCP, or is it a CLI-only operation for humans?

## Alternatives considered

- **Keep six tools.** Leaves agents unable to reorganise or repair a corpus.
- **One `exec kaya` tool.** Rejected for the same reason as in pandan ADR 0019: the hosted server has no
  binary to exec.
- **A tool per edit operation.** Larger resident schema for no gain in expressiveness.

## Amendment (2026-10-02, KAN-1816): the format operation, before the operation list exists

Decision 2 (a list-of-operations `edit_note`) is accepted on paper only. Checked against
`mcp/src/kaya_mcp/` on this date: `edit_note` is still the single-operation tool ADR 0006 froze
(`ref`, `title`, `body`, `path`, `if_updated_at`), there is no operation list, no `note_outline`, and
the server still registers six tools.

The explicit markdown format pass (KAN-1813, server engine KAN-1814) needed an MCP spelling now. The
smallest compatible one is a `format` boolean on the existing `edit_note`: the same `PATCH` the CLI's
`kaya note format` makes, with the formatter on. `edit_note(ref, format=True)` is a format-only call.
It is not a 16th tool, and `mcp/tests/test_cli_parity.py` pins it as a subset of the CLI.

- **When the operation list lands, `format` folds into it** as one more operation beside
  `replace_section` and the rest, and the boolean is removed in the same change.
- Writes are never formatted implicitly. A create or edit whose saved body would change under format
  carries a `help` hint naming `kaya note format <ref>` and the changed line count; a formatted body
  carries nothing.
- **Resident schema, re-measured** with `mcp/scripts/measure_schema_compaction.py` (`o200k_base`):
  the whole `tools/list` reply goes 785 to 819 tokens (+34), input schemas alone 265 to 275. 819 is
  the ceiling for precondition 5 until the next tool or argument lands.
