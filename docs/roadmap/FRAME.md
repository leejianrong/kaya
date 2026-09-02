---
shaping: true
---

# kaya: post-V6 direction — Frame

`docs/PLAN.md` and `docs/SLICES.md` are the ground truth for V1–V6, which is complete. This document
and its siblings in `docs/roadmap/` are a **separate** shaping pass for what comes next — kept apart
from the historical plan so the two don't collide or get confused with each other.

## Source

Verbatim, from the planning conversation on 2026-09-01:

> i want to chart out the direction for this project, including next milestones, epics, and stories
> that we can add to the kanban board. we should see what is the state of the pandan project and see
> which features need to include the pandan team in the discussions, and which features are just
> within kaya. let's make sure that the UI is enhanced so that i can edit notes etc. (parity with
> CLI/MCP) in the upcoming work. let's kick off the planning; interview me and also come up with
> discussion points so we can chart the direction for kaya

Interview answers:

> **Milestone focus (multi-select):** UI/CLI/MCP parity · Real hosted deployment · New standalone
> capabilities *(not selected: deeper pandan integration)*
>
> **Deploy timing vs. pandan's k8s homelab (KAN-439):** Pursue an independent host sooner — don't wait
> on the homelab.
>
> **Multi-user / sharing scope:** Yes, worth scoping now.
>
> **Top pain point (multi-select):** Can't author/manage notes in the browser — plus, verbatim:
> "I want pandan and kaya to be enterprise ready. ready for teams or companies with multiple teams to
> use. it should also be ready for teams that want to self host their own instance. that is the long
> term vision; let's work towards it."

## Problem

Two problems, one small and one large, surfaced in the same conversation:

1. **The SPA lags its own CLI/MCP.** A user who signs into the browser can read, search and edit an
   existing note's body — and nothing else. They cannot create a note, delete one, rename/move one,
   or edit a title, even though `kaya-cli` and the MCP server have done all four since V2b/V6. This
   was found by trying to use the product, not by reading a spec.
2. **kaya (and its sibling pandan) are single-tenant, single-operator tools being asked to become
   enterprise software.** Today: one owner per note (kaya), one owner or named member per board
   (pandan), no organization/team concept above that, no hosted deployment reachable by anyone who
   isn't running `make up` themselves, and no documented path for a third party to stand up their own
   instance. The stated long-term vision is companies with multiple internal teams using a
   self-hostable pandan+kaya, which is a different shape of software than what exists today.

## Outcome

- The browser is a first-class kaya client: create, delete, move and retitle a note without dropping
  to the CLI.
- kaya has an independently reachable hosted deployment that does not wait on pandan's own
  infrastructure timeline.
- There is a concrete, incrementally buildable path from "single owner, single operator" toward
  "multiple teams inside one company, deployable by a third party who self-hosts" — and every step on
  that path is labeled **kaya-only** or **needs coordinated pandan-repo work**, so the two codebases
  don't drift out of sync on identity, roles or deployment assumptions.
- New standalone capabilities (candidates below) are named but explicitly not yet prioritized against
  the above — see Discussion points.
