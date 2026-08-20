"""``note_link`` against a real Postgres — KAN-562, SLICES §V5's integration row. KAN-563 adds
note-to-note resolution by title, still against the same real database.

The fast layer (``tests/unit/test_note_links.py``) proves the diff and the wrapper's calls to a fake
session. What only a real database can show: that an untouched edge really is the same **row** —
same primary key, same `created_at` — across two saves rather than a delete-and-reinsert that merely
looks identical; that `ON DELETE CASCADE` actually removes a note's edges when the note goes; and
that the whole thing happens through the real routes (`POST`/`PATCH /api/v1/notes`), the same shape
`tests/integration/test_note_search_vector.py` uses for KAN-557/558.

KAN-563's own share of that argument: whether a title match happens *at all* is a database property
in exactly the same way, and SLICES §V5's own test plan places "resolves once a matching note is
created" under **End-to-end**, not Unit — the fast layer proves the pure value logic
(`resolved_ids_for_additions`) and the wrapper's wiring against a fake title map, and this file is
what proves the map itself is a real, owner-scoped, exact-match query rather than an assumption.

**No ``import app.*`` at module top** — see the package docstring, and pandan's PR #17 trap.
"""

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

BACKEND_ROOT = Path(__file__).resolve().parents[2]

ALICE_TOKEN = "a-caller-supplied-string-kaya-does-not-parse"
ALICE_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")

BOB_TOKEN = "a-different-callers-string-kaya-also-does-not-parse"
BOB_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")

NOTES = "/api/v1/notes"

READ_LINKS = text(
    "SELECT id, target_kind, target_ref, resolved_id, created_at FROM note_link "
    "WHERE source_note_id = :source_note_id ORDER BY target_kind, target_ref"
)


class FakeUpstream:
    """Pandan, faked at the HTTP boundary (ADR 0002's Protocol seam). Kaya holds no credential."""

    def __init__(self) -> None:
        self.known: dict[str, Any] = {}

    def introspect(self, bearer: str) -> Any:
        return self.known.get(bearer)


def _alembic_config() -> Any:
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


@pytest.fixture
def upstream() -> FakeUpstream:
    return FakeUpstream()


@pytest.fixture
def engine(database_url: str) -> Any:
    """The schema at head, for reading ``note_link`` directly."""
    from alembic import command

    from app.db import get_engine

    command.upgrade(_alembic_config(), "head")
    return get_engine()


@pytest.fixture
def client(database_url: str, upstream: FakeUpstream) -> Iterator[Any]:
    """The real app with pandan swapped out, exactly as ``test_notes_api.py`` builds it."""
    from typing import Annotated

    from alembic import command
    from fastapi import Depends
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from app.auth.cache import PrincipalCache
    from app.auth.dependencies import get_resolver, reset_auth
    from app.auth.mirror import SqlAlchemyPrincipalMirror
    from app.auth.principal import Principal
    from app.auth.resolver import PrincipalResolver
    from app.auth.single_flight import SingleFlight
    from app.db import get_session, get_sessionmaker
    from app.main import app

    command.upgrade(_alembic_config(), "head")

    def empty() -> None:
        with get_sessionmaker()() as session:
            session.execute(text('TRUNCATE TABLE note, "user" CASCADE'))
            session.commit()

    empty()
    reset_auth()
    upstream.known[ALICE_TOKEN] = Principal(id=ALICE_ID, email="alice@example.com")
    cache = PrincipalCache(positive_ttl=60.0, negative_ttl=10.0)
    single_flight = SingleFlight()

    def resolver(session: Annotated[Session, Depends(get_session)]) -> PrincipalResolver:
        return PrincipalResolver(
            upstream=upstream,
            mirror=SqlAlchemyPrincipalMirror(session),
            cache=cache,
            single_flight=single_flight,
        )

    app.dependency_overrides[get_resolver] = resolver
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        reset_auth()
        empty()


def auth(token: str = ALICE_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create(client: Any, *, token: str = ALICE_TOKEN, **fields: str) -> dict[str, Any]:
    fields.setdefault("title", "a note")
    response = client.post(NOTES, json=fields, headers=auth(token))
    assert response.status_code == 201, response.text
    return response.json()


def links_of(engine: Any, note_id: int) -> list[Any]:
    with engine.connect() as connection:
        return list(connection.execute(READ_LINKS, {"source_note_id": note_id}))


# --- A note created with wikilinks gets rows ----------------------------------------------------


def test_a_note_created_with_wikilinks_gets_rows(client: Any, engine: Any) -> None:
    created = create(client, title="runbook", body="blocked by [[KAN-1]], see also [[EPIC-2]]")

    rows = links_of(engine, created["id"])

    assert [(r.target_kind, r.target_ref) for r in rows] == [("EPIC", "EPIC-2"), ("KAN", "KAN-1")]
    assert all(r.resolved_id is None for r in rows), "ADR 0003: nothing is resolved by this card"


def test_a_note_created_with_no_wikilinks_gets_no_rows(client: Any, engine: Any) -> None:
    created = create(client, title="plain", body="just prose, no brackets anywhere")

    assert links_of(engine, created["id"]) == []


def test_repeated_occurrences_of_the_same_target_collapse_to_one_row(
    client: Any, engine: Any
) -> None:
    created = create(client, title="repeats", body="see [[KAN-1]] and again [[KAN-1]] right here")

    rows = links_of(engine, created["id"])

    assert len(rows) == 1
    assert (rows[0].target_kind, rows[0].target_ref) == ("KAN", "KAN-1")


# --- Editing reconciles: removed disappear, added appear, unchanged is untouched ------------------


def test_editing_the_body_adds_new_links_and_removes_missing_ones(client: Any, engine: Any) -> None:
    created = create(client, title="edited", body="[[KAN-1]]")
    assert [(r.target_kind, r.target_ref) for r in links_of(engine, created["id"])] == [
        ("KAN", "KAN-1")
    ]

    edited = client.patch(
        f"{NOTES}/{created['ref']}", json={"body": "[[EPIC-9]]"}, headers=auth()
    )
    assert edited.status_code == 200, edited.text

    rows = links_of(engine, created["id"])
    assert [(r.target_kind, r.target_ref) for r in rows] == [("EPIC", "EPIC-9")]


def test_an_unchanged_links_row_is_the_same_row_not_deleted_and_reinserted(
    client: Any, engine: Any
) -> None:
    """SLICES §V5's own wording: "unchanged ones aren't churned." Same primary key and the same
    `created_at`, which a delete-then-reinsert could not produce (a fresh row gets a fresh id and a
    fresh `now()`)."""
    created = create(client, title="mixed edit", body="[[KAN-1]] and [[KAN-2]]")
    before = {(r.target_kind, r.target_ref): r for r in links_of(engine, created["id"])}
    kan_1_before = before[("KAN", "KAN-1")]

    edited = client.patch(
        f"{NOTES}/{created['ref']}",
        json={"body": "[[KAN-1]] and [[KAN-3]] now"},
        headers=auth(),
    )
    assert edited.status_code == 200, edited.text

    after = {(r.target_kind, r.target_ref): r for r in links_of(engine, created["id"])}

    assert set(after) == {("KAN", "KAN-1"), ("KAN", "KAN-3")}, "KAN-2 gone, KAN-3 arrived"
    kan_1_after = after[("KAN", "KAN-1")]
    assert kan_1_after.id == kan_1_before.id, "the untouched edge is not a new row"
    assert kan_1_after.created_at == kan_1_before.created_at, "nor was it touched at all"


def test_deleting_every_link_from_the_body_removes_every_row(client: Any, engine: Any) -> None:
    created = create(client, title="cleared", body="[[KAN-1]] and [[EPIC-2]]")
    assert links_of(engine, created["id"]) != []

    edited = client.patch(
        f"{NOTES}/{created['ref']}", json={"body": "no links now"}, headers=auth()
    )
    assert edited.status_code == 200, edited.text

    assert links_of(engine, created["id"]) == []


def test_a_title_or_path_only_edit_does_not_touch_note_link(client: Any, engine: Any) -> None:
    """`find_wikilinks` reads the body; a save that never changed it cannot change what the body
    links to, so the reconciler must not run at all — checked here by the row surviving with its
    identity and its timestamp both untouched."""
    created = create(client, title="renamed later", body="[[KAN-1]]")
    before = links_of(engine, created["id"])[0]

    renamed = client.patch(
        f"{NOTES}/{created['ref']}", json={"title": "a new title"}, headers=auth()
    )
    assert renamed.status_code == 200, renamed.text
    moved = client.patch(
        f"{NOTES}/{created['ref']}", json={"path": "archive/moved.md"}, headers=auth()
    )
    assert moved.status_code == 200, moved.text

    after = links_of(engine, created["id"])
    assert len(after) == 1
    assert after[0].id == before.id
    assert after[0].created_at == before.created_at


# --- An unresolvable link is stored UNRESOLVED, never dropped for that reason ---------------------


def test_an_unresolvable_link_stays_stored_as_unresolved_rather_than_being_dropped(
    client: Any, engine: Any
) -> None:
    """Nothing checks pandan (ADR 0003, and this module makes no network call at all), so a
    reference to a card number nothing can vouch for is stored exactly like any other — `resolved_id
    IS NULL` — and is not pruned just for staying that way across a second save."""
    created = create(client, title="maybe bogus", body="blocked on [[KAN-999999999]]")
    first = links_of(engine, created["id"])
    assert len(first) == 1
    assert first[0].resolved_id is None

    # A second save that does not touch the link at all: it must still be there afterwards,
    # unresolved, rather than having been silently swept up as "not real".
    resaved = client.patch(
        f"{NOTES}/{created['ref']}",
        json={"body": "blocked on [[KAN-999999999]] still"},
        headers=auth(),
    )
    assert resaved.status_code == 200, resaved.text

    second = links_of(engine, created["id"])
    assert len(second) == 1
    assert second[0].resolved_id is None
    assert second[0].target_ref == "KAN-999999999"


# --- Recording an edge is local: it never blocks on pandan, never touches the network -------------


def test_a_note_with_a_wikilink_saves_even_though_pandan_is_never_asked(
    client: Any, engine: Any
) -> None:
    """ADR 0003, made concrete: the fake upstream in this file only ever answers the identity
    lookup it is wired for (``introspect``) — there is no route by which a save could reach it to
    ask about a card, so a save succeeding at all here is partial evidence, and the stronger proof
    is architectural (nothing in ``app/note_links.py`` imports an HTTP client). Both are worth
    having: this test is the one that would go red first if that ever changed."""
    created = create(client, title="never phones home", body="[[KAN-1]] [[EPIC-2]] [[KAN-3]]")

    assert created["body"] == "[[KAN-1]] [[EPIC-2]] [[KAN-3]]"
    assert len(links_of(engine, created["id"])) == 3


# --- The foreign key: deleting a note takes its edges with it -------------------------------------


def test_deleting_a_note_removes_its_note_link_rows(client: Any, engine: Any) -> None:
    """``ON DELETE CASCADE``: an edge has no meaning independent of the note whose body produced it
    (``app/models/note_link.py``)."""
    created = create(client, title="doomed", body="[[KAN-1]]")
    assert links_of(engine, created["id"]) != []

    deleted = client.delete(f"{NOTES}/{created['ref']}", headers=auth())
    assert deleted.status_code == 204

    assert links_of(engine, created["id"]) == []


# --- KAN-563: note-to-note resolution by title, with the id recorded ------------------------------


def link_row(engine: Any, note_id: int) -> Any:
    """The single ``note_link`` row for a note that is only expected to have exactly one."""
    rows = links_of(engine, note_id)
    assert len(rows) == 1, rows
    return rows[0]


def test_a_note_title_link_gets_a_note_kind_row_unresolved_when_no_such_title_exists_yet(
    client: Any, engine: Any
) -> None:
    created = create(client, title="linker", body="see [[A Title Nobody Has Yet]] for background")

    row = link_row(engine, created["id"])
    assert (row.target_kind, row.target_ref) == ("NOTE", "A Title Nobody Has Yet")
    assert row.resolved_id is None


def test_linking_to_an_existing_notes_title_resolves_immediately_on_creation(
    client: Any, engine: Any
) -> None:
    """KAN-563's forward pass: no second save required — the target already exists when the link
    is written, so the row is born resolved."""
    target = create(client, title="Existing Note", body="")

    linker = create(client, title="linker", body="see [[Existing Note]] for background")

    row = link_row(engine, linker["id"])
    assert row.resolved_id == target["id"]


def test_a_link_to_a_title_that_doesnt_exist_yet_resolves_once_a_matching_note_is_created(
    client: Any, engine: Any
) -> None:
    """SLICES §V5's own wording, verbatim. This is the property nothing would prove without a
    backward pass: note A's own row is never revisited by anything A does again, so the only thing
    that can ever fill it in is note B's own creation looking backward for A."""
    linker = create(client, title="linker", body="blocked on [[Future Note]]")
    unresolved = link_row(engine, linker["id"])
    assert unresolved.resolved_id is None

    target = create(client, title="Future Note", body="")

    resolved = link_row(engine, linker["id"])
    assert resolved.id == unresolved.id, "the same row, filled in — not a new one"
    assert resolved.resolved_id == target["id"]


def test_renaming_a_note_into_a_title_resolves_other_notes_pending_links_too(
    client: Any, engine: Any
) -> None:
    """The backward pass fires on a rename as well as on a creation — a link can be waiting for a
    title that already exists under a different name."""
    linker = create(client, title="linker", body="blocked on [[Some Title]]")
    target = create(client, title="Something Else", body="")
    assert link_row(engine, linker["id"]).resolved_id is None

    renamed = client.patch(
        f"{NOTES}/{target['ref']}", json={"title": "Some Title"}, headers=auth()
    )
    assert renamed.status_code == 200, renamed.text

    assert link_row(engine, linker["id"]).resolved_id == target["id"]


def test_renaming_the_resolved_target_note_leaves_the_backlink_intact(
    client: Any, engine: Any
) -> None:
    """SLICES §V5's own wording: "renaming a note leaves existing backlinks to it intact." The
    pointer is `resolved_id`, an id — it survived being *written* as a title lookup, and it must
    just as certainly survive the target changing its title afterward, and `target_ref` (what the
    *linking* note actually typed) is not "helpfully" rewritten to track the target's new title
    either — that would substitute a display convenience for the historical record SLICES §V5
    asks this card to keep.

    `[mutate]` per SLICES, verified by hand rather than automated here (CLAUDE.md's guard-mutation
    convention): temporarily add, at the end of `resolve_pending_note_links`, a second
    `session.execute` — one more `update(NoteLink)` matching `resolved_id == note.id` and setting
    `target_ref=note.title` — the "helpfully keep the reference's label in sync with a rename"
    feature nobody asked for. This test's `after.target_ref == "Original Title"` assertion then
    goes red, naming the row whose `target_ref` moved to "Renamed Later" out from under the note
    that wrote it. Restore immediately after."""
    target = create(client, title="Original Title", body="")
    linker = create(client, title="linker", body="see [[Original Title]] for background")
    before = link_row(engine, linker["id"])
    assert before.resolved_id == target["id"]

    renamed = client.patch(
        f"{NOTES}/{target['ref']}", json={"title": "Renamed Later"}, headers=auth()
    )
    assert renamed.status_code == 200, renamed.text

    after = link_row(engine, linker["id"])
    assert after.id == before.id
    assert after.resolved_id == target["id"], "the id-based pointer outlives the target's rename"
    assert after.target_ref == "Original Title", "what the linking note typed is untouched too"


def test_title_matching_is_exact_and_case_sensitive(client: Any, engine: Any) -> None:
    """A decision this card had to make and did: two titles differing only in case are not the same
    edge, the same way `Note.title` is stored and compared byte for byte everywhere else."""
    create(client, title="Reading List", body="")

    linker = create(client, title="linker", body="see [[reading list]] please")

    assert link_row(engine, linker["id"]).resolved_id is None


def test_resolution_never_crosses_an_owner_boundary(
    client: Any, engine: Any, upstream: Any
) -> None:
    """A title match is scoped to the *linking* note's own owner — Bob having a note titled
    "Shared Title" must never resolve (or, worse, silently name) Alice's link to that title, the
    same "another user's note must never appear" property `notes_owned_by` enforces for a list."""
    from app.auth.principal import Principal

    upstream.known[BOB_TOKEN] = Principal(id=BOB_ID, email="bob@example.com")
    create(client, token=BOB_TOKEN, title="Shared Title", body="")

    linker = create(client, title="linker", body="see [[Shared Title]] for background")

    assert link_row(engine, linker["id"]).resolved_id is None


def test_an_ambiguous_title_resolves_to_the_newest_matching_note(
    client: Any, engine: Any
) -> None:
    """Title is not unique (`app/models/note.py`). The module docstring argues for "newest wins"
    as the same tie-break direction this codebase uses everywhere else one is needed; this is that
    argument, proven against real auto-incrementing ids rather than assumed from the query's
    shape."""
    older = create(client, title="Duplicate Title", body="")
    newer = create(client, title="Duplicate Title", body="")
    assert newer["id"] > older["id"], "the fixture's own assumption, made explicit"

    linker = create(client, title="linker", body="see [[Duplicate Title]] for background")

    assert link_row(engine, linker["id"]).resolved_id == newer["id"]


def test_a_note_can_link_to_its_own_title_and_resolve_on_its_first_save(
    client: Any, engine: Any
) -> None:
    """The note being created is itself a candidate for its own forward-resolution lookup: by the
    time `reconcile_note_links` queries, the note has already been flushed, so it is visible to its
    own query inside the same transaction."""
    created = create(client, title="Self Reference", body="see also [[Self Reference]]")

    assert link_row(engine, created["id"]).resolved_id == created["id"]


def test_a_note_title_link_and_a_pandan_reference_coexist_and_resolve_independently(
    client: Any, engine: Any
) -> None:
    """The two kinds share one table and one reconcile pass, and nothing about handling one
    disturbs the other — a NOTE-kind row may resolve locally while a KAN-kind row sitting right
    beside it stays `NULL`, exactly as it did before this card (ADR 0003, KAN-564's alone to fill
    in)."""
    target = create(client, title="Runbook", body="")

    linker = create(client, title="linker", body="[[KAN-1]] and also [[Runbook]]")

    rows = {(r.target_kind, r.target_ref): r for r in links_of(engine, linker["id"])}
    assert rows[("KAN", "KAN-1")].resolved_id is None
    assert rows[("NOTE", "Runbook")].resolved_id == target["id"]


def test_editing_a_body_to_add_a_note_title_link_resolves_it_on_that_save_too(
    client: Any, engine: Any
) -> None:
    """The forward pass is not create-only: `reconcile_note_links` runs on every body-touching
    edit, so a link added later resolves exactly as promptly as one written at creation."""
    target = create(client, title="Existing Note", body="")
    linker = create(client, title="linker", body="no links yet")
    assert links_of(engine, linker["id"]) == []

    edited = client.patch(
        f"{NOTES}/{linker['ref']}", json={"body": "now see [[Existing Note]]"}, headers=auth()
    )
    assert edited.status_code == 200, edited.text

    assert link_row(engine, linker["id"]).resolved_id == target["id"]
