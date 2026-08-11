"""``GET /api/v1/notes?q=`` against a real Postgres 17 — KAN-558, SLICES §V4.

Everything this card promises is a claim about what Postgres does with a ``tsquery``, so almost none
of it is assertable in the fast layer. ``tests/unit/test_note_search_query.py`` holds the parts that
are (the blank rule, the emitted SQL, the term being a bound parameter); what is here needs rows.

Four groups, and they are deliberately different claims:

1. **It finds notes**, by a word in the body and by a word in the title, stemmed and case-folded,
   with a title hit ranking above a body-only hit.
2. **Another user's matching note never appears** — with *two* real users, and with a positive
   control on every isolation assertion. A test that searches as Alice and receives Alice's notes
   proves nothing about Bob; a test where the term matches nothing at all passes for the wrong
   reason, which is the most common way an isolation test lies. So each one asserts that the term
   genuinely matches Bob's note when Bob asks.
3. **Identical queries return one order**, including when the ranks are *equal*. The tie is
   reproduced rather than hoped for: the fixture's two titles are measured to score identically, and
   only then is the order pinned. A tie-break asserted against data that never ties is not asserted.
4. **The hostile inputs SLICES §V4 names**, end to end: empty, whitespace, a stopword, punctuation
   only, an unbalanced operator, 5,000 characters, a quoted phrase, an exclusion, and ``%``/``_``.

**No ``import app.*`` at module top** — see the package docstring, and pandan's PR #17 trap.
"""

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

BACKEND_ROOT = Path(__file__).resolve().parents[2]

# Two callers, because one cannot prove the scoping (see the module docstring). Kaya does not parse
# a token (ADR 0002), so these are opaque strings the fake upstream knows about.
ALICE_TOKEN = "a-caller-supplied-string-kaya-does-not-parse"
ALICE_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
BOB_TOKEN = "another-caller-supplied-string-kaya-does-not-parse"
BOB_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")

NOTES = "/api/v1/notes"

# `user` is reserved in Postgres, so every hand-written statement against it quotes the name.
INSERT_USER = text('INSERT INTO "user" (id, email) VALUES (:id, :email)')

NOTE_PAYLOAD_KEYS = [
    "ref",
    "id",
    "title",
    "body",
    "path",
    "created_at",
    "updated_at",
]
"""``tests/unit/test_note_payload_keys.py``'s pin, repeated here because a search is a *different
code path returning the same schema* and the unit pin only ever sees ``NoteRead``. Duplicated rather
than imported: ``tests/`` is not a package, and the point of the copy is that this layer looks at
the bytes on the wire."""


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
def client(database_url: str, upstream: FakeUpstream) -> Iterator[Any]:
    """The real app with pandan swapped out, holding two users' mirror rows.

    A fresh ``PrincipalCache`` per test, because the cache is process-wide by design and one
    surviving a ``TRUNCATE`` serves a principal whose mirror row no longer exists — the next INSERT
    then fails on the foreign key, which reads as a flake and is not one.
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
    upstream.known[BOB_TOKEN] = Principal(id=BOB_ID, email="bob@example.com")
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


@pytest.fixture
def engine(database_url: str) -> Any:
    """A connection to the same database, for the assertions that have to look past the API."""
    from app.db import get_engine

    return get_engine()


def auth(token: str = ALICE_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create(client: Any, token: str = ALICE_TOKEN, **fields: str) -> dict[str, Any]:
    fields.setdefault("title", "a note")
    response = client.post(NOTES, json=fields, headers=auth(token))
    assert response.status_code == 201, response.text
    return response.json()


def search(client: Any, term: str | None, token: str = ALICE_TOKEN) -> Any:
    params = {} if term is None else {"q": term}
    return client.get(NOTES, params=params, headers=auth(token))


def titles(response: Any) -> list[str]:
    assert response.status_code == 200, response.text
    return [note["title"] for note in response.json()["notes"]]


def refs(response: Any) -> list[str]:
    assert response.status_code == 200, response.text
    return [note["ref"] for note in response.json()["notes"]]


# --- it finds notes -------------------------------------------------------------------------------


def test_a_word_in_the_body_finds_the_note(client: Any) -> None:
    """SLICES §V4's end-to-end row: a phrase present only in a body finds the note from the API."""
    create(client, title="an unremarkable title", body="the incident involved a runbook")
    create(client, title="something else", body="nothing to see")

    assert titles(search(client, "runbook")) == ["an unremarkable title"]


def test_a_word_in_the_title_finds_the_note(client: Any) -> None:
    create(client, title="the deployment runbook", body="no body worth indexing")
    create(client, title="something else", body="nothing to see")

    # Plural, and it still matches: the query is stemmed with the same dictionary as the vector.
    assert titles(search(client, "runbooks")) == ["the deployment runbook"]


def test_the_search_is_case_folded(client: Any) -> None:
    create(client, title="Searching for bugs")

    assert titles(search(client, "SEARCH")) == ["Searching for bugs"]


def test_a_title_hit_outranks_a_body_hit(client: Any) -> None:
    """The A/B weights KAN-557 put in the stored vector, arriving through the route.

    ``ts_rank`` reads them out of the vector with no arguments, so this is the assertion that the
    ranking is *relevance* rather than insertion order.
    """
    create(client, title="unrelated title", body="a passing mention of kubernetes")
    create(client, title="kubernetes", body="unrelated prose about nothing")

    assert titles(search(client, "kubernetes")) == ["kubernetes", "unrelated title"]


def test_a_term_matching_nothing_is_an_empty_list_rather_than_an_error(client: Any) -> None:
    create(client, title="Alpha")

    response = search(client, "nonexistentterm")
    assert response.status_code == 200
    assert response.json() == {"notes": []}


# --- another user's matching note never appears ---------------------------------------------------


def test_a_term_matching_only_another_users_note_returns_nothing(client: Any, engine: Any) -> None:
    """The card's second sentence, with the positive control that keeps it from lying.

    Bob's note is the *only* note in the table containing "unicorn". Alice's search must be empty —
    and the two controls below prove that emptiness is scoping rather than a term that matches
    nothing: Bob's own search finds it, and Postgres agrees one row matches.
    """
    create(client, BOB_TOKEN, title="Bob's plan", body="a secret unicorn strategy")
    create(client, title="Alice's plan", body="no mythical creatures here")

    assert titles(search(client, "unicorn")) == [], "another user's matching note appeared"

    # Positive control 1: the term genuinely matches, for the user who owns the note.
    assert titles(search(client, "unicorn", token=BOB_TOKEN)) == ["Bob's plan"]
    # Positive control 2: and it matches in the database, so the API is not the only witness.
    with engine.connect() as connection:
        matching = connection.execute(
            text(
                "SELECT count(*) FROM note "
                "WHERE search_vector @@ websearch_to_tsquery('english', 'unicorn')"
            )
        ).scalar_one()
    assert matching == 1, "the fixture's term matches no note at all; the test above is vacuous"


def test_a_shared_term_returns_only_the_callers_notes(client: Any, engine: Any) -> None:
    """The harder half: a term that matches *both* users' notes, where a missing ``WHERE`` returns
    something plausible instead of nothing."""
    create(client, BOB_TOKEN, title="bob on kaya", body="kaya is for notes")
    create(client, title="alice on kaya", body="kaya is for notes")
    create(client, title="alice on pandan", body="kaya is for notes too")

    assert sorted(titles(search(client, "kaya"))) == ["alice on kaya", "alice on pandan"]
    assert titles(search(client, "kaya", token=BOB_TOKEN)) == ["bob on kaya"]

    with engine.connect() as connection:
        matching = connection.execute(
            text(
                "SELECT count(*) FROM note "
                "WHERE search_vector @@ websearch_to_tsquery('english', 'kaya')"
            )
        ).scalar_one()
    assert matching == 3, "all three notes must match, or this proves nothing about the filter"


def test_another_users_prose_is_not_even_fetched(client: Any) -> None:
    """The distinction SLICES §V1 draws, at the level this layer can see it.

    A post-filter in Python would produce the same JSON, so what is asserted here is that the search
    statement is the *scoped* one: ``notes_matching`` composed onto ``notes_owned_by``. Running it
    for Alice and asking Postgres for the row count it returned is the closest a test gets to "Bob's
    body never crossed the wire" without reading the query log."""
    from app.auth.authorization import notes_matching
    from app.auth.principal import Principal
    from app.db import get_sessionmaker

    create(client, BOB_TOKEN, title="Bob's plan", body="a secret unicorn strategy")
    create(client, title="Alice's plan", body="a unicorn is a horse with a horn")

    alice = Principal(id=ALICE_ID, email="alice@example.com")
    with get_sessionmaker()() as session:
        rows = list(session.scalars(notes_matching(alice, "unicorn")))

    assert [note.title for note in rows] == ["Alice's plan"]
    assert all(note.owner_id == ALICE_ID for note in rows)


# --- identical queries, one order -----------------------------------------------------------------


@pytest.fixture
def a_genuine_rank_tie(client: Any, engine: Any) -> dict[str, Any]:
    """Two notes whose titles both match ``reading list`` with a **byte-identical** ``ts_rank``.

    Reproduced from the live ten-note corpus, where ``plainto_tsquery('english','reading list')``
    scored "A reading list" and "Reading list" at 0.9910 each: ``a`` is a stopword and ``ts_rank``
    ignores positions, so the two vectors rank the same however the titles are spelled. A ten-note
    corpus tying on a two-word query is why the tie-break is not theoretical.

    The equality is asserted here rather than assumed, so a future Postgres that scores these two
    differently fails *this* fixture — naming the reason — instead of quietly making every ordering
    test below pass without exercising the tie-break.
    """
    first = create(client, title="A reading list", body="one")
    second = create(client, title="Reading list", body="two")

    with engine.connect() as connection:
        ranked = connection.execute(
            text(
                "SELECT ref, ts_rank(search_vector, websearch_to_tsquery('english', :q)) AS rank "
                "FROM note WHERE ref IN (:a, :b)"
            ),
            {"q": "reading list", "a": first["ref"], "b": second["ref"]},
        ).all()

    ranks = {row.ref: row.rank for row in ranked}
    assert ranks[first["ref"]] == ranks[second["ref"]], (
        f"the fixture does not tie, so the tie-break is untested: {ranks}"
    )
    return {"first": first, "second": second, "rank": ranks[first["ref"]]}


def test_equal_ranks_are_ordered_by_id_descending(
    client: Any, a_genuine_rank_tie: dict[str, Any]
) -> None:
    """The tie-break, pinned. ``id`` is the only column that can promise this.

    ``updated_at`` cannot: ``now()`` is transaction start time, so two notes written in one
    transaction share a stamp and the tie merely moves to the same place. Descending, because kaya's
    unfiltered list is ``updated_at DESC, id DESC`` and one house order beats matching pandan's
    ascending ``id`` literally.
    """
    tie = a_genuine_rank_tie
    assert tie["second"]["id"] > tie["first"]["id"], "the fixture's ids are not in creation order"

    assert refs(search(client, "reading list")) == [tie["second"]["ref"], tie["first"]["ref"]]


def test_identical_queries_return_the_same_order(
    client: Any, a_genuine_rank_tie: dict[str, Any]
) -> None:
    """SLICES §V4's determinism row, over the pair that actually ties.

    Repetition is weak evidence on its own — an unordered query can return one order ten times in a
    row on a table this small — so this test earns its place next to the one above and next to
    KAN-558's mutation run, where removing ``Note.id.desc()`` is watched going red.
    """
    orders = {tuple(refs(search(client, "reading list"))) for _ in range(6)}

    assert len(orders) == 1, f"identical queries produced more than one order: {orders}"


def test_the_unfiltered_list_keeps_its_own_order(client: Any) -> None:
    """The other order, unchanged by this card: newest updated first, ``id DESC`` breaking the tie.

    ``KayaClient.list_notes``' docstring depends on it, and the two orders differing is a decision
    (``app/api/notes.py``) rather than an accident of two code paths.
    """
    first = create(client, title="oldest")
    second = create(client, title="middle")
    third = create(client, title="newest")

    listed = refs(search(client, None))

    assert listed == [third["ref"], second["ref"], first["ref"]]


# --- what ?q= with nothing in it means ------------------------------------------------------------


def test_an_absent_q_lists_every_note(client: Any) -> None:
    create(client, title="Alpha")
    create(client, title="Beta")

    assert sorted(titles(search(client, None))) == ["Alpha", "Beta"]


def test_an_empty_q_is_refused_rather_than_listing_everything(client: Any) -> None:
    """The decision in ``app/api/search.py``, and the failure it exists to prevent.

    Under pandan's no-op rule this returns the whole corpus, which is indistinguishable from a
    search that matched every note — so ``kaya note list --q "$TERM"`` with an unset variable would
    look like it worked. `400`, which ADR 0005's table maps to exit `2`."""
    create(client, title="Alpha")

    response = client.get(NOTES, params={"q": ""}, headers=auth())

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "empty_search_query"
    assert "notes" not in response.json(), "the refusal still returned a corpus"


def test_a_whitespace_only_q_is_refused_identically(client: Any) -> None:
    """``?q=%20%20`` is a shell-quoting accident, not a request for everything."""
    create(client, title="Alpha")

    refused = client.get(NOTES, params={"q": "   "}, headers=auth())
    empty = client.get(NOTES, params={"q": ""}, headers=auth())

    assert refused.status_code == 400
    assert refused.json() == empty.json(), "two spellings of blank, two different answers"


def test_the_refusal_is_the_one_error_shape(client: Any) -> None:
    response = client.get(NOTES, params={"q": ""}, headers=auth())

    assert set(response.json()) == {"error"}
    assert set(response.json()["error"]) == {"code", "message"}
    assert "detail" not in response.json(), "FastAPI's word must not reach the wire"


def test_an_unauthenticated_search_is_still_a_401(client: Any) -> None:
    """The refusal above must not be reachable before authentication: ``?q=`` is not a way to learn
    that a route exists without a credential (contrast ``/api/v1/meta``, KAN-555)."""
    assert client.get(NOTES, params={"q": ""}).status_code == 401
    assert client.get(NOTES, params={"q": "runbook"}).status_code == 401


# --- the hostile inputs ---------------------------------------------------------------------------


def test_a_stopword_only_search_matches_nothing_and_is_not_an_error(client: Any) -> None:
    """``websearch_to_tsquery('english','the')`` is the empty tsquery, and ``@@ ''`` is false.

    A `200` with no notes, deliberately: the caller typed a word, so they made a search, and the
    status code must not depend on the dictionary's stopword list.
    """
    create(client, title="the incident report", body="the pods restarted")

    response = search(client, "the")
    assert response.status_code == 200, response.text
    assert response.json() == {"notes": []}


def test_punctuation_only_is_a_search_that_matches_nothing(client: Any) -> None:
    """``&|!()`` is where ``to_tsquery`` raises ``SyntaxError`` and becomes a `500`. Measured on
    this card; it is the reason the parser is ``websearch_to_tsquery``."""
    create(client, title="Alpha", body="beta")

    for hostile in ("&|!()", "|", "!", "(", ")", ":*", "<->"):
        response = search(client, hostile)
        assert response.status_code == 200, f"{hostile!r}: {response.text}"
        assert response.json() == {"notes": []}, hostile


def test_an_unbalanced_operator_is_tolerated(client: Any) -> None:
    """``to_tsquery('english','foo &')`` raises "no operand in tsquery"; websearch reads it as
    ``'foo'`` and finds the note."""
    create(client, title="foo", body="bar")

    assert titles(search(client, "foo &")) == ["foo"]
    assert titles(search(client, '"foo')) == ["foo"]


def test_a_very_long_term_is_answered_rather_than_refused(client: Any) -> None:
    """5,000 characters of one token: Postgres discards a lexeme over 2,047 bytes, so the tsquery is
    empty and the answer is no notes. Not a `400`, not a `500`, and not a timeout."""
    create(client, title="Alpha")

    response = search(client, "x" * 5000)
    assert response.status_code == 200, response.text
    assert response.json() == {"notes": []}


def test_a_quoted_phrase_is_a_phrase(client: Any) -> None:
    """The grammar ``plainto_tsquery`` cannot express, which is half of why it was not chosen."""
    create(client, title="a reading list", body="one")
    create(client, title="a list of things worth reading", body="two")

    assert titles(search(client, '"reading list"')) == ["a reading list"]
    # And without the quotes both match, because bare words are AND-ed rather than adjacent.
    assert sorted(titles(search(client, "reading list"))) == [
        "a list of things worth reading",
        "a reading list",
    ]


def test_a_leading_minus_excludes(client: Any) -> None:
    """The other half of that grammar."""
    create(client, title="reading list", body="one")
    create(client, title="reading notes", body="two")

    assert titles(search(client, "reading -list")) == ["reading notes"]


def test_like_metacharacters_are_inert(client: Any) -> None:
    """``%`` and ``_`` are wildcards to ``LIKE`` and nothing at all to a ``tsquery``.

    If this test ever fails, the implementation has stopped being full-text search — which is
    exactly the mistake a hurried "make search work" patch makes, and it is invisible from the happy
    path."""
    create(client, title="99 problems", body="one")
    create(client, title="a_b coverage at 50%", body="two")

    for wildcard in ("%", "_", "%%", "_%_"):
        response = search(client, wildcard)
        assert response.status_code == 200, f"{wildcard!r}: {response.text}"
        assert response.json() == {"notes": []}, f"{wildcard!r} behaved like a wildcard"

    # A term that happens to contain them still searches for the words around them.
    assert titles(search(client, "coverage")) == ["a_b coverage at 50%"]


def test_a_quote_and_a_semicolon_are_data(client: Any) -> None:
    """The term is a bound parameter (pinned structurally in the unit layer); this is the end-to-end
    half — the statement runs, the table survives, and nothing is a `500`."""
    create(client, title="Alpha")

    response = search(client, "'; DROP TABLE note; --")
    assert response.status_code == 200, response.text
    assert titles(search(client, None)) == ["Alpha"], "the table did not survive"


# --- the vector stays out of the payload, and out of the row --------------------------------------


def test_a_search_response_carries_exactly_the_note_payload_keys(client: Any) -> None:
    """KAN-557's pin, re-asserted for a different code path returning the same schema.

    ``tests/unit/test_note_payload_keys.py`` proves ``NoteRead`` cannot carry the vector. What it
    cannot see is a route that started selecting columns of its own, which is exactly what a
    ranking query invites (``SELECT ..., ts_rank(...) AS rank``).
    """
    create(client, title="runbook", body="restart the pods")

    payload = search(client, "runbook").json()

    assert list(payload) == ["notes"]
    assert [list(note) for note in payload["notes"]] == [NOTE_PAYLOAD_KEYS]
    assert "search_vector" not in search(client, "runbook").text
    assert ":1A" not in search(client, "runbook").text, "a lexeme string reached the wire"
    assert "rank" not in search(client, "runbook").text, "the rank is a per-query artefact"


def test_the_search_query_does_not_load_the_vector(client: Any) -> None:
    """``deferred=True`` surviving a card that names the column twice — proven on a real row.

    The unit layer asserts the columns clause; this asserts the consequence, which is what actually
    matters: after the query, SQLAlchemy reports the attribute as **unloaded**, so the tsvector — a
    value the size of the note again — did not cross the wire from Postgres.
    """
    from sqlalchemy import inspect

    from app.auth.authorization import notes_matching
    from app.auth.principal import Principal
    from app.db import get_sessionmaker

    create(client, title="runbook", body="restart the pods " * 200)

    alice = Principal(id=ALICE_ID, email="alice@example.com")
    with get_sessionmaker()() as session:
        note = session.scalars(notes_matching(alice, "runbook")).one()
        unloaded = inspect(note).unloaded

        assert "search_vector" in unloaded, "the search query loaded the tsvector into the row"
        assert "body" not in unloaded, "the columns a caller wants must still be loaded"
        # And it is still readable on demand, so `deferred` is deferral rather than exclusion.
        assert "'runbook':1A" in note.search_vector


def test_the_predicate_can_use_the_gin_index(client: Any, engine: Any) -> None:
    """The index KAN-557 built, actually reachable by KAN-558's predicate.

    A ``@@`` against a stored ``tsvector`` is index-eligible; the same feature written with
    ``ILIKE`` would not be, and would look identical from every other test in this file. Postgres
    picks a sequential scan on a table this small whatever the plan costs, so ``enable_seqscan`` is
    off for the length of the transaction — making this a test of *eligibility*, not of the
    planner's taste.

    **Measured while writing it, and worth writing down:** with the owner scoping in the same
    ``WHERE``, the planner prefers ``ix_note_owner_id`` and applies the tsvector as a ``Filter``.
    That is the planner doing its job — on one caller's handful of rows the owner predicate is by
    far the more selective — and it is not a defect, so this test explains the composed plan rather
    than demanding a shape from it. It is the *predicate* that has to be index-eligible; which index
    wins on a real corpus is a cost estimate, and neither answer is a bug."""
    create(client, title="runbook", body="restart the pods")

    def plan_for(where: str, parameters: dict[str, Any]) -> str:
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL enable_seqscan = off"))
            return "\n".join(
                row[0]
                for row in connection.execute(
                    text(f"EXPLAIN SELECT id FROM note WHERE {where}"), parameters
                )
            )

    predicate_alone = plan_for(
        "search_vector @@ websearch_to_tsquery('english', :q)", {"q": "runbook"}
    )
    assert "ix_note_search_vector" in predicate_alone, (
        f"the GIN index is not usable by this predicate:\n{predicate_alone}"
    )

    composed = plan_for(
        "owner_id = :owner AND search_vector @@ websearch_to_tsquery('english', :q)",
        {"owner": ALICE_ID, "q": "runbook"},
    )
    assert "search_vector @@" in composed, f"the predicate vanished from the plan:\n{composed}"
    assert "Seq Scan" not in composed, f"neither index was used:\n{composed}"
