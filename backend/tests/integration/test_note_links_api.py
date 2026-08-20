"""KAN-566's two routes end to end, against a real Postgres and a faked pandan.

The unit layer proves what the SQL *says* and what the pure record builder *decides*. This file
proves the three things only rows and a container can prove, and all three are SLICES §V5
`[mutate]` criteria:

- **`kaya backlinks NOTE-3` lists every note linking to it, answered from kaya's own database with
  pandan down.** The whole route is one join, so this is a claim about there being no network call
  on the path — asserted by stopping pandan *and* by asserting the upstream saw zero calls, because
  a route that made one and swallowed the failure would pass the first half alone.
- **Renaming a note leaves existing backlinks to it intact.** The rename criterion is the reason
  KAN-563 recorded an id at all (Q19), and it is invisible to any test that never renames anything.
  Its positive control is the test below it: NULL out one `resolved_id` and the backlink disappears,
  which is what proves the match key is the id rather than something that merely correlates with it.
- **Resolution uses the caller's PAT: a note referencing a card the reader cannot see renders
  unresolved rather than leaking the title.** Two callers, one ref, two answers.

Plus the guarantee with no visible symptom until it matters: `/links` does not hold a Postgres
connection across the upstream call (`app/api/links.py`'s `_release_the_connection`).

**No `import app.*` at module top** — see the package docstring, and pandan's PR #17 trap: a
top-level `app` import runs at collection, before the `database_url` fixture sets `DATABASE_URL`.
"""

import uuid
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

BACKEND_ROOT = Path(__file__).resolve().parents[2]

# Shapeless on purpose: kaya has no token format (ADR 0002), so a PAT-shaped fixture would quietly
# assert the opposite of the thing under test. Same reasoning as `test_pandan_down.py`.
ALICE_TOKEN = "a-caller-supplied-string-kaya-does-not-parse"
BOB_TOKEN = "a-different-caller-supplied-string"
ALICE_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
BOB_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")

NOTES = "/api/v1/notes"


class FakeCardEpicUpstream:
    """`CardEpicUpstream`, answering **per bearer**, counting every call.

    Per bearer is what makes the caller's-PAT criterion assertable at all: two bearers can see two
    different sets of cards, which is exactly what pandan's own owner-scoping does. Lifted from
    `tests/unit/test_card_resolution.py` rather than reinvented — the shape is that file's, so a
    change to the seam breaks one fake and not two.
    """

    def __init__(self) -> None:
        self.cards_by_bearer: dict[str, dict[str, Any]] = {}
        self.epics_by_bearer: dict[str, list[Any]] = {}
        self.card_calls: list[tuple[str, tuple[str, ...]]] = []
        self.epic_calls: list[str] = []
        self.available = True
        self.on_call: Any = None
        """Run just before a reachable call answers. The seam the connection-release test needs:
        it is the only moment at which "is kaya holding a database connection right now?" has a
        meaningful answer."""

    def _entered(self) -> None:
        from app.integrations.card_resolution import CardEpicUnavailable

        if self.on_call is not None:
            self.on_call()
        if not self.available:
            raise CardEpicUnavailable("https://pandan.invalid is unreachable")

    def fetch_cards(self, bearer: str, refs: Sequence[str]) -> Any:
        from app.integrations.card_resolution import CardBatch

        self.card_calls.append((bearer, tuple(refs)))
        self._entered()
        known = self.cards_by_bearer.get(bearer, {})
        return CardBatch(
            cards=tuple(known[ref] for ref in refs if ref in known),
            unresolved_refs=tuple(ref for ref in refs if ref not in known),
        )

    def fetch_epics(self, bearer: str) -> Sequence[Any]:
        self.epic_calls.append(bearer)
        self._entered()
        return tuple(self.epics_by_bearer.get(bearer, []))

    @property
    def call_count(self) -> int:
        return len(self.card_calls) + len(self.epic_calls)


class FakeIdentityUpstream:
    """Pandan's `GET /api/v1/me`, faked. `available = False` is a stopped process, so `introspect`
    raises rather than returning `None` — returning `None` for an outage surfaces as a `401` and
    reads as "your token is bad" (`test_pandan_down.py` makes the same point at length)."""

    def __init__(self) -> None:
        self.known: dict[str, Any] = {}
        self.available = True

    def introspect(self, bearer: str) -> Any:
        from app.auth.principal import UpstreamUnavailable

        if not self.available:
            raise UpstreamUnavailable("https://pandan.invalid/api/v1/me is unreachable")
        return self.known.get(bearer)


def _alembic_config() -> Any:
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


def card(ticket: str, title: str, column: str = "in_progress") -> Any:
    from app.integrations.card_resolution import ResolvedTicket

    return ResolvedTicket(kind="card", id=1, ticket_number=ticket, title=title, column=column)


def epic(ticket: str, title: str) -> Any:
    from app.integrations.card_resolution import ResolvedTicket

    return ResolvedTicket(kind="epic", id=3, ticket_number=ticket, title=title, column=None)


@pytest.fixture
def identity() -> FakeIdentityUpstream:
    return FakeIdentityUpstream()


@pytest.fixture
def pandan() -> FakeCardEpicUpstream:
    return FakeCardEpicUpstream()


@pytest.fixture
def client(
    database_url: str, identity: FakeIdentityUpstream, pandan: FakeCardEpicUpstream
) -> Iterator[Any]:
    """The real app with two dependencies overridden: identity, and card/epic resolution.

    Both caches are fresh per test and both are dropped afterwards, for the reason
    `test_notes_api.py` gives about the principal cache: they are process-wide by design, and one
    surviving a `TRUNCATE` serves an answer about rows that no longer exist. The resolution cache
    also has to be fresh for a *second* reason specific to this file — a warm entry would make the
    "no upstream call happened" assertions pass for the wrong reason.
    """
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
    from app.db import get_sessionmaker
    from app.integrations.card_resolution import CardEpicCache, CardEpicResolver
    from app.integrations.dependencies import get_card_epic_resolver, reset_card_resolution
    from app.main import app

    command.upgrade(_alembic_config(), "head")

    def empty() -> None:
        with get_sessionmaker()() as session:
            session.execute(text('TRUNCATE TABLE note_link, note, "user" CASCADE'))
            session.commit()

    empty()
    reset_auth()
    reset_card_resolution()

    identity.known[ALICE_TOKEN] = Principal(id=ALICE_ID, email="alice@example.com")
    identity.known[BOB_TOKEN] = Principal(id=BOB_ID, email="bob@example.com")

    cache = PrincipalCache(positive_ttl=60.0, negative_ttl=10.0)
    single_flight = SingleFlight()
    card_cache = CardEpicCache(ttl=300.0)

    from app.db import get_session

    def identity_resolver(session: Annotated[Session, Depends(get_session)]) -> PrincipalResolver:
        return PrincipalResolver(
            upstream=identity,
            mirror=SqlAlchemyPrincipalMirror(session),
            cache=cache,
            single_flight=single_flight,
        )

    def card_resolver() -> CardEpicResolver:
        return CardEpicResolver(
            pandan,
            card_cache,
            max_selectors_per_request=100,
            max_upstream_requests=5,
            total_deadline_seconds=8.0,
        )

    app.dependency_overrides[get_resolver] = identity_resolver
    app.dependency_overrides[get_card_epic_resolver] = card_resolver
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        reset_auth()
        reset_card_resolution()
        empty()


def auth(token: str = ALICE_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create(client: Any, token: str = ALICE_TOKEN, **fields: str) -> dict[str, Any]:
    fields.setdefault("title", "a note")
    response = client.post(NOTES, json=fields, headers=auth(token))
    assert response.status_code == 201, response.text
    return response.json()


def links(client: Any, ref: str, token: str = ALICE_TOKEN) -> list[dict[str, Any]]:
    response = client.get(f"{NOTES}/{ref}/links", headers=auth(token))
    assert response.status_code == 200, response.text
    return response.json()["links"]


def backlinks(client: Any, ref: str, token: str = ALICE_TOKEN) -> list[dict[str, Any]]:
    response = client.get(f"{NOTES}/{ref}/backlinks", headers=auth(token))
    assert response.status_code == 200, response.text
    return response.json()["notes"]


# --- `kaya backlinks NOTE-3` with pandan down: SLICES §V5, [mutate] ------------------------------


def test_backlinks_are_answered_from_kayas_own_database_with_pandan_down(
    client: Any, identity: FakeIdentityUpstream, pandan: FakeCardEpicUpstream
) -> None:
    """SLICES §V5's e2e row, word for word: "lists every note linking to it, answered from kaya's
    own database with pandan down". **[mutate]**

    Two halves, and the second is the one that stops this passing for the wrong reason. Stopping
    pandan proves the route did not *need* it; asserting `pandan.call_count == 0` proves the route
    did not *call* it — a `/backlinks` that resolved something and swallowed the failure would pass
    the first assertion and be exactly the ADR 0003 violation this criterion exists to rule out.

    The principal cache is warmed first, with pandan reachable, because authentication is the one
    dependency ADR 0002 accepts knowingly — see `test_pandan_down.py`, which argues that boundary at
    length and draws it in the same place.
    """
    target = create(client, title="Deploy runbook", body="the steps")
    create(client, title="Monday", body="see [[Deploy runbook]] before standup")
    create(client, title="Tuesday", body="still [[Deploy runbook]], plus [[KAN-501]]")
    create(client, title="Unrelated", body="no links here")

    identity.available = False
    pandan.available = False

    found = backlinks(client, target["ref"])

    assert [note["title"] for note in found] == ["Tuesday", "Monday"], (
        "every note linking to the target, newest first, and nothing else"
    )
    assert pandan.call_count == 0, (
        "a backlinks read is a join over two of kaya's own tables and must make no upstream call "
        "at all — not even one whose failure it swallows (ADR 0003)"
    )


def test_backlinks_omit_another_users_note_rather_than_returning_an_empty_list(
    client: Any,
) -> None:
    """The scoping property, over rows, with somebody else's linking note actually present.

    Bob's note links to a title Alice also uses. Two notes exist with that title — one per owner —
    so Bob's link resolves to *Bob's* note. Asserting Bob's own backlinks are non-empty is the
    positive control: a scoping test against rows that were never written passes for the wrong
    reason.

    **What this test does not prove, stated because the mutation said so.** Dropping the owner
    clause
    from `notes_linking_to` leaves it green. `app/note_links.py` scopes both of its resolution
    passes, so the `resolved_id` values here are already partitioned by owner and an unscoped query
    returns the same rows. This is the *shape* a reader expects to see and it is worth keeping;
    `test_a_cross_owner_resolved_id_is_still_not_a_backlink` below is the one that actually holds
    the clause down.
    """
    alice_target = create(client, ALICE_TOKEN, title="Shared Title", body="alice's")
    create(client, ALICE_TOKEN, title="Alice links", body="[[Shared Title]]")

    bob_target = create(client, BOB_TOKEN, title="Shared Title", body="bob's")
    create(client, BOB_TOKEN, title="Bob links", body="[[Shared Title]]")

    assert [n["title"] for n in backlinks(client, alice_target["ref"], ALICE_TOKEN)] == [
        "Alice links"
    ]
    assert [n["title"] for n in backlinks(client, bob_target["ref"], BOB_TOKEN)] == ["Bob links"], (
        "bob's linking note must actually exist, or the assertion above proves nothing"
    )


def test_a_cross_owner_resolved_id_is_still_not_a_backlink(client: Any) -> None:
    """The owner clause, tested against a row that makes it **load-bearing**.

    The test above it is honest but vacuous for this mutation, and finding that out was worth more
    than the test was. `app/note_links.py` scopes *both* of its resolution passes — `notes_titled`
    forward, `note_ids_owned_by` backward — so a `resolved_id` written by that module never crosses
    an owner boundary in the first place. Which means dropping `notes_owned_by` from
    `notes_linking_to` entirely leaves every assertion up there green: the ids were already
    partitioned by owner, so an unscoped query returns exactly the same rows. Watched failing to
    confirm it (see the PR body).

    So this manufactures the state the *schema* permits and nothing prevents: `resolved_id` is
    deliberately not a `ForeignKey` (`app/models/note_link.py`), so a row can name a note somebody
    else owns, and the only thing standing between that and Alice learning who links to her notes is
    the clause under test. Written directly, because the API has no route that produces one — which
    is the point: a defence that is currently unreachable through the front door is exactly the
    defence a later card removes as dead weight.
    """
    from sqlalchemy import text as sql

    from app.db import get_sessionmaker

    alices = create(client, ALICE_TOKEN, title="Alice's target", body="target")
    bobs = create(client, BOB_TOKEN, title="Bob's private note", body="[[Alice's target]]")

    with get_sessionmaker()() as session:
        alice_id = session.execute(
            sql("SELECT id FROM note WHERE ref = :ref"), {"ref": alices["ref"]}
        ).scalar_one()
        bob_id = session.execute(
            sql("SELECT id FROM note WHERE ref = :ref"), {"ref": bobs["ref"]}
        ).scalar_one()
        updated = session.execute(
            sql(
                "UPDATE note_link SET resolved_id = :target "
                "WHERE source_note_id = :source AND target_kind = 'NOTE'"
            ),
            {"target": alice_id, "source": bob_id},
        )
        session.commit()
        assert updated.rowcount == 1, (
            "the cross-owner row this test is about must exist, or the assertion below passes "
            "because there was nothing to leak"
        )

    found = backlinks(client, alices["ref"], ALICE_TOKEN)

    assert found == [], "a note_link row naming another owner's note is not a backlink to it"
    assert "Bob's private note" not in str(found)


def test_a_note_that_links_to_its_own_title_appears_in_its_own_backlinks(client: Any) -> None:
    """Not a special case being allowed through — the absence of one. The note genuinely contains a
    link that resolves to it (`app/note_links.py` resolves a self-link on the first save, on
    purpose), and excluding it here would be a rule the parser and the reconciler both disagree
    with."""
    note = create(client, title="Index", body="this is the [[Index]]")

    assert [n["ref"] for n in backlinks(client, note["ref"])] == [note["ref"]]


def test_a_note_nobody_links_to_has_an_empty_backlinks_list(client: Any) -> None:
    note = create(client, title="Lonely", body="nothing points here")

    assert backlinks(client, note["ref"]) == []


def test_backlinks_for_a_missing_note_is_the_same_404_as_every_other_ref_route(
    client: Any,
) -> None:
    """ADR 0008 through `NoteFromRef`, with no ref handling in the route to get wrong — and the two
    spellings byte-identical on a miss, which is the property the resolver exists for."""
    prefixed = client.get(f"{NOTES}/NOTE-9999/backlinks", headers=auth())
    bare = client.get(f"{NOTES}/9999/backlinks", headers=auth())

    assert prefixed.status_code == bare.status_code == 404
    assert prefixed.json() == bare.json() == {
        "error": {"code": "note_not_found", "message": "no such note"}
    }


def test_backlinks_for_another_users_note_is_403_not_404(client: Any) -> None:
    """`authorize_note` goes to real trouble to keep "not yours" and "not there" apart, and a new
    ref-taking route must not collapse them by fetching scoped."""
    bobs = create(client, BOB_TOKEN, title="Bob's note")

    response = client.get(f"{NOTES}/{bobs['ref']}/backlinks", headers=auth(ALICE_TOKEN))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "note_forbidden"


def test_a_hash_prefixed_ref_is_a_400_on_backlinks_too(client: Any) -> None:
    """`#NOTE-12` is a usage error by design (ADR 0008 §Decision), and the new route inherits it
    from the resolver rather than restating it."""
    response = client.get(f"{NOTES}/%23NOTE-1/backlinks", headers=auth())

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_note_ref"


# --- Renaming leaves backlinks intact: SLICES §V5, [mutate] -------------------------------------


def test_renaming_a_note_leaves_existing_backlinks_to_it_intact(client: Any) -> None:
    """SLICES §V5's e2e row: "Renaming a note leaves existing backlinks to it intact." **[mutate]**

    This is what Q19's "resolve by title, record the id" was decided *for*, arriving at the layer
    that reads the id back. The linking note's body is never touched — ADR 0008 forbids link
    rewriting — so the only thing that can carry the edge across the rename is `resolved_id`, and a
    `/backlinks` keyed on `target_ref` would return the linking note before the rename and nothing
    after it.

    Both halves are asserted: the backlink survives, **and** the payload states the divergence
    (`target_ref` still says what was typed, `title` says what the note is called now), because a
    backlink that survived while `/links` claimed the body had changed would be half a fix.
    """
    target = create(client, title="Old Name", body="the target")
    linking = create(client, title="Points at it", body="see [[Old Name]] for details")

    assert [n["ref"] for n in backlinks(client, target["ref"])] == [linking["ref"]], (
        "the backlink must exist before the rename, or the assertion after it proves nothing"
    )

    renamed = client.patch(
        f"{NOTES}/{target['ref']}", json={"title": "New Name"}, headers=auth()
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["title"] == "New Name"

    assert [n["ref"] for n in backlinks(client, target["ref"])] == [linking["ref"]], (
        "renaming the target must not break a backlink to it (SLICES §V5, Q19)"
    )

    [link] = links(client, linking["ref"])
    assert link["target_ref"] == "Old Name", "the body still says what the author typed"
    assert link["resolved_ref"] == target["ref"]
    assert link["title"] == "New Name", "and the payload reports the target's current title"


def test_the_body_of_the_linking_note_is_not_rewritten_by_a_rename(client: Any) -> None:
    """ADR 0008, asserted on the prose rather than on the edge. A "helpful" rename that fixed up
    every `[[Old Name]]` would make the criterion above pass for a reason the ADR forbids."""
    target = create(client, title="Old Name")
    linking = create(client, title="Points at it", body="see [[Old Name]]")

    renamed = client.patch(
        f"{NOTES}/{target['ref']}", json={"title": "New Name"}, headers=auth()
    )
    assert renamed.status_code == 200, renamed.text

    read = client.get(f"{NOTES}/{linking['ref']}", headers=auth())
    assert read.json()["body"] == "see [[Old Name]]", (
        "a rename touches one column of one note and rewrites no prose anywhere (ADR 0008)"
    )


def test_the_backlink_disappears_if_the_recorded_id_is_removed(client: Any) -> None:
    """The positive control for the rename test, and the whole reason it is trustworthy.

    The rename test would stay green under an implementation keyed on *either* column, because
    before a rename `target_ref` and the target's title agree. So this one breaks the agreement from
    the other side: NULL the `resolved_id` out from under a row whose `target_ref` still matches the
    target's title exactly. Keyed on the id, the backlink is gone. Keyed on the title, it is still
    there — and that is the mutation this pair was written to catch.
    """
    from sqlalchemy import text as sql

    from app.db import get_sessionmaker

    target = create(client, title="Still Named This", body="target")
    linking = create(client, title="Linker", body="[[Still Named This]]")

    assert [n["ref"] for n in backlinks(client, target["ref"])] == [linking["ref"]]

    with get_sessionmaker()() as session:
        updated = session.execute(
            sql("UPDATE note_link SET resolved_id = NULL WHERE target_kind = 'NOTE'")
        )
        session.commit()
        assert updated.rowcount == 1, "the row this test edits must exist"

    assert backlinks(client, target["ref"]) == [], (
        "an unresolved title edge is a link to a title, not to this note — matching it against "
        "`Note.title` as a fallback would reintroduce the rename bug through the back door"
    )


def test_a_kan_edge_whose_resolved_id_collides_with_a_note_id_is_not_a_backlink(
    client: Any,
) -> None:
    """The `target_kind` filter, which is unreachable today and load-bearing anyway.

    `resolved_id` is deliberately not a `ForeignKey` because which table it references depends on
    `target_kind` (`app/models/note_link.py`). Nothing writes a KAN-kind `resolved_id` at the
    moment, so this test manufactures the state a later card could: a card edge carrying an integer
    that happens to be a note's id. Without the kind filter that note would gain a backlink from a
    note whose body never mentioned it.
    """
    from sqlalchemy import text as sql

    from app.db import get_sessionmaker

    target = create(client, title="Collides", body="target")
    linking = create(client, title="Mentions a card", body="tracked in [[KAN-501]]")

    with get_sessionmaker()() as session:
        note_id = session.execute(
            sql("SELECT id FROM note WHERE ref = :ref"), {"ref": target["ref"]}
        ).scalar_one()
        updated = session.execute(
            sql("UPDATE note_link SET resolved_id = :id WHERE target_kind = 'KAN'"),
            {"id": note_id},
        )
        session.commit()
        assert updated.rowcount == 1, "the KAN edge this test edits must exist"

    assert backlinks(client, target["ref"]) == [], (
        "two id namespaces, one column: a card id must never resolve to a note"
    )
    # And the edge is still there, still a card link — the filter excludes it from *backlinks*, it
    # does not delete it.
    assert [link["target_ref"] for link in links(client, linking["ref"])] == ["KAN-501"]


# --- /links: resolution with the caller's own PAT, SLICES §V5 [mutate] --------------------------


def test_resolution_uses_the_callers_pat_so_an_unreadable_cards_title_never_leaks(
    client: Any, pandan: FakeCardEpicUpstream
) -> None:
    """SLICES §V5's integration row: "a note referencing a card the reader cannot see renders
    unresolved rather than leaking the title." **[mutate]**

    Both callers write a note naming `KAN-501`. Only Alice's bearer can see that card upstream, so
    Alice gets the title and Bob gets three nulls — and the assertion checks Bob's *whole response
    body* for the title string, not just the `title` key, because a leak that arrived under another
    name would satisfy a key-wise assertion.

    The two things this rules out are a kaya-owned service credential (there is none: the bearer is
    the caller's own, forwarded) and a cache keyed on the bare ticket number, which would hand Bob
    Alice's answer. Alice goes **first**, deliberately: a cache that leaked would be warm by the
    time Bob asks, so the ordering is what makes the second assertion mean anything.
    """
    pandan.cards_by_bearer[ALICE_TOKEN] = {"KAN-501": card("KAN-501", "MCP read tools")}
    pandan.cards_by_bearer[BOB_TOKEN] = {}

    alices = create(client, ALICE_TOKEN, title="Alice's note", body="tracked in [[KAN-501]]")
    bobs = create(client, BOB_TOKEN, title="Bob's note", body="also [[KAN-501]]")

    [alice_link] = links(client, alices["ref"], ALICE_TOKEN)
    assert alice_link["title"] == "MCP read tools"
    assert alice_link["column"] == "in_progress"

    response = client.get(f"{NOTES}/{bobs['ref']}/links", headers=auth(BOB_TOKEN))
    assert response.status_code == 200, response.text
    [bob_link] = response.json()["links"]

    assert bob_link["target_ref"] == "KAN-501", "the edge is still reported"
    assert (bob_link["resolved_ref"], bob_link["title"], bob_link["column"]) == (None, None, None)
    assert "MCP read tools" not in response.text, (
        "the title must not reach a caller pandan would not show it to, under any key"
    )
    assert [bearer for bearer, _ in pandan.card_calls] == [ALICE_TOKEN, BOB_TOKEN], (
        "Bob's read must reach pandan with Bob's own bearer rather than being served from Alice's "
        "cache entry — the cache is keyed on (sha256(bearer), ticket_number) for this reason"
    )


def test_a_second_read_of_the_same_note_costs_no_upstream_request(
    client: Any, pandan: FakeCardEpicUpstream
) -> None:
    """Spike 0001's acceptance line, at the endpoint that finally has a caller. The cache is
    process-wide (`app/integrations/dependencies.py`), so the saving is across requests, which is
    the only place a note render happens twice."""
    pandan.cards_by_bearer[ALICE_TOKEN] = {"KAN-501": card("KAN-501", "MCP read tools")}
    note = create(client, title="Tracked", body="[[KAN-501]] and [[KAN-501]] again")

    first = links(client, note["ref"])
    calls_after_first = pandan.call_count
    second = links(client, note["ref"])

    assert first == second
    assert calls_after_first == 1, "one distinct ref, one request, however often the body says it"
    assert pandan.call_count == 1, "and the second render of the same note asks nothing"


def test_links_stay_a_200_with_unresolved_rows_when_pandan_is_stopped(
    client: Any, identity: FakeIdentityUpstream, pandan: FakeCardEpicUpstream
) -> None:
    """ADR 0003 at the endpoint that is allowed to call pandan: with pandan stopped, `/links` is a
    `200` carrying every edge, unresolved. Never a `503`, never an empty list, never a `500`.

    The note-to-note edge in the same body resolves *anyway*, because that resolution is a local
    `SELECT` — which is what makes this a test about the pandan half rather than about the route
    failing safely as a whole.
    """
    create(client, title="Deploy runbook", body="steps")
    note = create(
        client, title="Monday", body="see [[Deploy runbook]], [[KAN-501]] and [[EPIC-3]]"
    )

    identity.available = False
    pandan.available = False

    found = links(client, note["ref"])

    by_ref = {link["target_ref"]: link for link in found}
    assert set(by_ref) == {"Deploy runbook", "KAN-501", "EPIC-3"}
    assert by_ref["Deploy runbook"]["resolved_ref"].startswith("NOTE-"), (
        "note-to-note resolution is a local SELECT and must not need pandan"
    )
    assert by_ref["KAN-501"]["resolved_ref"] is None
    assert by_ref["EPIC-3"]["resolved_ref"] is None
    assert by_ref["KAN-501"]["title"] is None


def test_an_outage_is_not_remembered_as_a_ref_that_does_not_exist(
    client: Any, pandan: FakeCardEpicUpstream
) -> None:
    """`resolve` does not cache a negative it got from an outage, and the endpoint inherits that.

    The failure this rules out is the nasty one: a `/links` read during a thirty-second pandan blip
    poisoning the cache for its whole TTL, so the link stays unresolved long after pandan came back.
    """
    pandan.cards_by_bearer[ALICE_TOKEN] = {"KAN-501": card("KAN-501", "MCP read tools")}
    note = create(client, title="Tracked", body="[[KAN-501]]")

    pandan.available = False
    assert links(client, note["ref"])[0]["resolved_ref"] is None

    pandan.available = True
    assert links(client, note["ref"])[0]["title"] == "MCP read tools", (
        "an outage is not evidence a ref does not exist, so it must not be cached as one"
    )


def test_an_epic_resolves_with_no_column_rather_than_an_invented_one(
    client: Any, pandan: FakeCardEpicUpstream
) -> None:
    pandan.epics_by_bearer[ALICE_TOKEN] = [epic("EPIC-3", "The V5 slice")]
    note = create(client, title="Tracked", body="part of [[EPIC-3]]")

    [link] = links(client, note["ref"])

    assert (link["resolved_ref"], link["title"], link["column"]) == ("EPIC-3", "The V5 slice", None)


def test_a_note_edge_whose_target_was_deleted_renders_unresolved_rather_than_500(
    client: Any,
) -> None:
    """`resolved_id` is not a `ForeignKey`, so deleting the *target* cascades nothing and nulls
    nothing — the id is left dangling. A route that trusted it would turn an ordinary delete into a
    `500` on every note that had linked to it."""
    target = create(client, title="Doomed", body="target")
    linking = create(client, title="Linker", body="see [[Doomed]]")

    assert links(client, linking["ref"])[0]["resolved_ref"] == target["ref"]

    assert client.delete(f"{NOTES}/{target['ref']}", headers=auth()).status_code == 204

    [link] = links(client, linking["ref"])
    assert link["target_ref"] == "Doomed"
    assert (link["resolved_ref"], link["title"]) == (None, None)


def test_a_note_with_no_wikilinks_is_an_empty_links_list(client: Any) -> None:
    note = create(client, title="Plain", body="no brackets anywhere")

    assert links(client, note["ref"]) == []


def test_links_are_ordered_deterministically_rather_than_by_insertion(
    client: Any, pandan: FakeCardEpicUpstream
) -> None:
    """Insertion order is not reproducible: the reconciler builds its insert list from a `set` of
    `(kind, ref)` pairs and Python randomises string hashing per process, so the same body saved on
    two workers stores its edges in two orders. `(target_kind, target_ref)` is a total order here,
    by the table's own unique constraint."""
    create(client, title="Zebra", body="a note")
    create(client, title="Apple", body="another")
    note = create(
        client,
        title="Many links",
        body="[[KAN-9]] [[Zebra]] [[EPIC-1]] [[Apple]] [[KAN-1]]",
    )

    found = [(link["target_kind"], link["target_ref"]) for link in links(client, note["ref"])]

    assert found == [
        ("EPIC", "EPIC-1"),
        ("KAN", "KAN-1"),
        ("KAN", "KAN-9"),
        ("NOTE", "Apple"),
        ("NOTE", "Zebra"),
    ]


def test_links_for_another_users_note_is_403_and_asks_pandan_nothing(
    client: Any, pandan: FakeCardEpicUpstream
) -> None:
    """The refusal happens in `NoteFromRef`, before the route body runs, so a caller cannot use
    `/links` to make kaya resolve refs out of a note they may not read."""
    pandan.cards_by_bearer[BOB_TOKEN] = {"KAN-501": card("KAN-501", "secret")}
    bobs = create(client, BOB_TOKEN, title="Bob's note", body="[[KAN-501]]")

    response = client.get(f"{NOTES}/{bobs['ref']}/links", headers=auth(ALICE_TOKEN))

    assert response.status_code == 403
    assert pandan.call_count == 0


# --- The guarantee with no visible symptom: no connection held across the upstream call ----------


def test_links_does_not_hold_a_postgres_connection_across_the_upstream_call(
    client: Any, pandan: FakeCardEpicUpstream
) -> None:
    """`app/api/links.py`'s `_release_the_connection`, asserted at the only moment it is decidable.

    Sync handlers run in Starlette's 40-thread pool and kaya's engine has SQLAlchemy's default pool
    (5, plus 10 overflow). If `/links` held its connection while waiting on pandan, roughly fifteen
    concurrent reads against a merely *slow* pandan would exhaust the pool and the next note
    **save** would block on a connection — ADR 0003's rule broken from inside kaya, by a
    decoration, for a request that never touches the note being saved.

    A concurrency test would be the direct proof and would be slow and flaky. This asserts the
    mechanism instead: the fake upstream reports the engine's checked-out count at the instant it is
    called. The positive control is in the same test — the count is non-zero *before* the request,
    inside a session that has run a statement — so a `checkedout()` that simply always returned zero
    could not satisfy both halves.
    """
    from sqlalchemy import text as sql

    from app.db import get_engine, get_sessionmaker

    pandan.cards_by_bearer[ALICE_TOKEN] = {"KAN-501": card("KAN-501", "MCP read tools")}
    note = create(client, title="Tracked", body="[[KAN-501]]")

    with get_sessionmaker()() as probe:
        probe.execute(sql("SELECT 1"))
        assert get_engine().pool.checkedout() > 0, (
            "the probe is the positive control: an open transaction must show as checked out, or "
            "the assertion below would pass against a metric that never moves"
        )

    observed: list[int] = []
    pandan.on_call = lambda: observed.append(get_engine().pool.checkedout())

    assert links(client, note["ref"])[0]["title"] == "MCP read tools"

    assert observed == [0], (
        "no pooled connection may be held while kaya is waiting on pandan (ADR 0003, and "
        "`app/auth/single_flight.py` for the shape of the failure it causes)"
    )
