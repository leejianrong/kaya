"""``/api/v1/notes`` end to end: real routes, real Postgres, real HTTP. Only pandan is faked.

This is SLICES §V1's end-to-end list, minus the one row another card owns (`k3d` is KAN-538).
Everything reaches the app the way a caller does — through Starlette's `Authorization` parsing, the
principal resolver, the ref resolver and a JSON body — so what is asserted is the wire contract
rather than a function's return value.

**No real PAT, and CI never needs one.** ADR 0002 made the upstream a Protocol so pandan could be
faked at exactly this seam; the fixtures below inject a dict. The token strings are deliberately
shapeless, because kaya has no token format and a PAT-shaped fixture would quietly assert the
opposite (and trip ``scripts/secret-scan.sh``, correctly).

**No ``import app.*`` at module top** — see the package docstring, and pandan's PR #17 trap.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
from sqlalchemy import text

BACKEND_ROOT = Path(__file__).resolve().parents[2]

ALICE_TOKEN = "a-caller-supplied-string-kaya-does-not-parse"
BOB_TOKEN = "a-different-caller-supplied-string"
ALICE_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
BOB_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")

NOTES = "/api/v1/notes"


class FakeUpstream:
    """Pandan, faked at the HTTP boundary. Kaya still holds no credential of its own."""

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
    """The **real** app — ``app.main.app``, router and error handlers — with pandan swapped out.

    Only ``get_resolver`` is overridden, and only so the fake upstream and a *fresh* cache get in.
    Fresh matters: the principal cache is process-wide by design, and a cache surviving a test that
    truncated the ``user`` table would serve a principal whose mirror row no longer exists, so the
    next INSERT would fail on the foreign key. That is the classic "passes alone, fails in a full
    run" auth flake ``reset_auth`` exists for.
    """
    from typing import Annotated

    from alembic import command
    from fastapi import Depends
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from app.auth.cache import PrincipalCache
    from app.auth.dependencies import get_resolver, reset_auth
    from app.auth.mirror import SqlAlchemyPrincipalMirror
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
def alice(upstream: FakeUpstream) -> Any:
    from app.auth.principal import Principal

    principal = Principal(id=ALICE_ID, email="alice@example.com")
    upstream.known[ALICE_TOKEN] = principal
    return principal


@pytest.fixture
def bob(upstream: FakeUpstream) -> Any:
    from app.auth.principal import Principal

    principal = Principal(id=BOB_ID, email="bob@example.com")
    upstream.known[BOB_TOKEN] = principal
    return principal


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create(client: Any, token: str, **fields: str) -> dict[str, Any]:
    fields.setdefault("title", "a note")
    response = client.post(NOTES, json=fields, headers=auth(token))
    assert response.status_code == 201, response.text
    return response.json()


# --- The demo, as a test --------------------------------------------------------------------------


@pytest.mark.usefixtures("alice")
def test_a_pat_creates_reads_edits_and_deletes_with_no_kaya_side_credential(client: Any) -> None:
    """SLICES §V1's first end-to-end row, and V1's demo without the `curl`.

    The only credential anywhere in this test is the caller's, forwarded to a pandan that kaya does
    not authenticate against (ADR 0002). Kaya mints nothing, stores nothing, and needs nothing
    configured.
    """
    created = create(client, ALICE_TOKEN, title="runbook", body="# steps", path="ops/runbook.md")

    assert created["ref"].startswith("NOTE-")
    assert created["title"] == "runbook"
    assert created["body"] == "# steps"

    read = client.get(f"{NOTES}/{created['ref']}", headers=auth(ALICE_TOKEN))
    assert read.status_code == 200
    assert read.json() == created

    edited = client.patch(
        f"{NOTES}/{created['ref']}",
        json={"body": "# steps\n1. do the thing"},
        headers=auth(ALICE_TOKEN),
    )
    assert edited.status_code == 200
    assert edited.json()["body"] == "# steps\n1. do the thing"
    assert edited.json()["title"] == "runbook", "an omitted field is left alone"

    deleted = client.delete(f"{NOTES}/{created['ref']}", headers=auth(ALICE_TOKEN))
    assert deleted.status_code == 204
    assert deleted.content == b""

    assert client.get(f"{NOTES}/{created['ref']}", headers=auth(ALICE_TOKEN)).status_code == 404


@pytest.mark.usefixtures("alice")
def test_the_location_header_names_the_note_in_a_form_the_resolver_accepts(client: Any) -> None:
    response = client.post(NOTES, json={"title": "located"}, headers=auth(ALICE_TOKEN))
    location = response.headers["Location"]

    assert location == f"{NOTES}/{response.json()['ref']}"
    assert client.get(location, headers=auth(ALICE_TOKEN)).status_code == 200


@pytest.mark.usefixtures("alice")
def test_a_title_alone_is_a_complete_request(client: Any) -> None:
    """``body`` and ``path`` have server defaults (migration `0001`), so the API can honour that."""
    created = create(client, ALICE_TOKEN, title="bare")

    assert created["body"] == ""
    assert created["path"] == ""
    assert created["created_at"] == created["updated_at"]


# --- ADR 0008: two names, one note ----------------------------------------------------------------


@pytest.mark.usefixtures("alice")
def test_the_same_note_by_ref_and_by_id_returns_byte_identical_bodies(client: Any) -> None:
    """SLICES §V1: "both forms return **byte-identical** bodies".

    Compared as raw bytes rather than as parsed JSON, which is the stronger claim and the cheaper
    one: key order, timestamp formatting and float rendering are all things two code paths can
    disagree about while `==` on two dicts stays happy.
    """
    created = create(client, ALICE_TOKEN, title="two names", body="prose")

    by_ref = client.get(f"{NOTES}/{created['ref']}", headers=auth(ALICE_TOKEN))
    by_id = client.get(f"{NOTES}/{created['id']}", headers=auth(ALICE_TOKEN))
    lowercased = client.get(f"{NOTES}/{created['ref'].lower()}", headers=auth(ALICE_TOKEN))

    assert by_ref.status_code == by_id.status_code == lowercased.status_code == 200
    assert by_ref.content == by_id.content
    assert by_ref.content == lowercased.content


@pytest.mark.usefixtures("alice")
def test_a_missing_note_is_the_same_404_however_it_was_addressed(client: Any) -> None:
    """SLICES §V1, **[mutate]**: "A missing note returns `404` with the same error code whether
    addressed as `NOTE-9999` or `9999`."

    Pandan shipped the version where these two disagreed — ``get 999999`` exited `1` and ``get
    KAN-999999`` exited `5` — so this is a regression test for a bug that has actually happened in
    the sibling, not a hypothetical. The body is compared byte for byte, not just the code: an
    identical code with a message naming the identifier would still leak the divergence into
    anything that logs or matches on the text.
    """
    prefixed = client.get(f"{NOTES}/NOTE-9999", headers=auth(ALICE_TOKEN))
    bare = client.get(f"{NOTES}/9999", headers=auth(ALICE_TOKEN))
    lowercased = client.get(f"{NOTES}/note-9999", headers=auth(ALICE_TOKEN))

    assert prefixed.status_code == bare.status_code == lowercased.status_code == 404
    assert prefixed.content == bare.content == lowercased.content
    assert prefixed.json()["error"]["code"] == "note_not_found"


@pytest.mark.usefixtures("alice")
def test_every_ref_taking_verb_agrees_on_a_missing_note(client: Any) -> None:
    """The reason the resolver is central rather than per call site: one implementation covers the
    verbs that exist and the ones V5 adds (`/links`, `/backlinks`, KAN-566)."""
    for call in (
        lambda ref: client.get(f"{NOTES}/{ref}", headers=auth(ALICE_TOKEN)),
        lambda ref: client.patch(f"{NOTES}/{ref}", json={"title": "x"}, headers=auth(ALICE_TOKEN)),
        lambda ref: client.delete(f"{NOTES}/{ref}", headers=auth(ALICE_TOKEN)),
    ):
        prefixed, bare = call("NOTE-9999"), call("9999")
        assert prefixed.status_code == bare.status_code == 404
        assert prefixed.content == bare.content


@pytest.mark.usefixtures("alice")
def test_everything_the_api_prints_is_accepted_back(client: Any) -> None:
    """ADR 0008's round-trip contract: "anything the tool prints must be accepted back".

    List, take each printed identifier **verbatim**, feed it to every ref-taking verb, assert
    success. Both identifiers in the payload are addressing forms, which is why both are here.
    """
    create(client, ALICE_TOKEN, title="round trip")

    listed = client.get(NOTES, headers=auth(ALICE_TOKEN)).json()["notes"]
    assert len(listed) == 1
    printed = [str(listed[0]["ref"]), str(listed[0]["id"])]

    for identifier in printed:
        assert client.get(f"{NOTES}/{identifier}", headers=auth(ALICE_TOKEN)).status_code == 200
        patched = client.patch(
            f"{NOTES}/{identifier}", json={"title": f"via {identifier}"}, headers=auth(ALICE_TOKEN)
        )
        assert patched.status_code == 200

    assert client.delete(f"{NOTES}/{printed[-1]}", headers=auth(ALICE_TOKEN)).status_code == 204


@pytest.mark.usefixtures("alice")
def test_a_leading_hash_is_a_usage_error_rather_than_a_miss(client: Any) -> None:
    """ADR 0008 pins this one by name. `400`, so the caller learns it mistyped instead of hunting a
    note that was never named."""
    response = client.get(f"{NOTES}/{quote('#NOTE-1', safe='')}", headers=auth(ALICE_TOKEN))

    assert response.status_code == 400
    assert response.status_code != 404
    assert response.json()["error"]["code"] == "invalid_note_ref"


@pytest.mark.usefixtures("alice")
def test_an_id_too_big_for_the_column_is_a_404_and_not_a_500(client: Any) -> None:
    """``note.id`` is an ``INTEGER``. Without the clamp in the resolver this is psycopg raising,
    which would be a `500` for one spelling and a `404` for the other."""
    huge = str(2**31)

    bare = client.get(f"{NOTES}/{huge}", headers=auth(ALICE_TOKEN))
    prefixed = client.get(f"{NOTES}/NOTE-{huge}", headers=auth(ALICE_TOKEN))

    assert bare.status_code == prefixed.status_code == 404
    assert bare.content == prefixed.content


@pytest.mark.usefixtures("alice")
def test_a_deleted_notes_ref_is_never_handed_to_another_note(client: Any) -> None:
    """Refs are immutable and never reused (ADR 0008), so a stale wikilink stays a dead link rather
    than silently pointing at somebody's new note."""
    gone = create(client, ALICE_TOKEN, title="deleted")
    client.delete(f"{NOTES}/{gone['ref']}", headers=auth(ALICE_TOKEN))

    replacement = create(client, ALICE_TOKEN, title="new")

    assert replacement["ref"] != gone["ref"]
    assert client.get(f"{NOTES}/{gone['ref']}", headers=auth(ALICE_TOKEN)).status_code == 404


# --- Authorization --------------------------------------------------------------------------------


@pytest.mark.usefixtures("alice", "bob")
def test_another_users_note_is_a_403_and_is_omitted_from_the_list(client: Any) -> None:
    """SLICES §V1: `403` on the note, and the list **omits** it rather than returning an empty page.

    Both halves in one test on purpose. A `403` proves the note exists, so the empty list beside it
    cannot be passing because the database is empty — which is the way a scoping test usually passes
    for the wrong reason.
    """
    hers = create(client, ALICE_TOKEN, title="alice's private planning note")

    for identifier in (hers["ref"], str(hers["id"])):
        forbidden = client.get(f"{NOTES}/{identifier}", headers=auth(BOB_TOKEN))
        assert forbidden.status_code == 403
        assert forbidden.json()["error"]["code"] == "note_forbidden"
        assert hers["title"] not in forbidden.text, "a refusal must not disclose the note"

    assert client.get(NOTES, headers=auth(BOB_TOKEN)).json() == {"notes": []}
    assert len(client.get(NOTES, headers=auth(ALICE_TOKEN)).json()["notes"]) == 1


@pytest.mark.usefixtures("alice", "bob")
def test_another_users_note_cannot_be_written_or_deleted_either(client: Any) -> None:
    hers = create(client, ALICE_TOKEN, title="alice's", body="untouched")

    assert client.patch(
        f"{NOTES}/{hers['ref']}", json={"body": "bob was here"}, headers=auth(BOB_TOKEN)
    ).status_code == 403
    assert client.delete(f"{NOTES}/{hers['ref']}", headers=auth(BOB_TOKEN)).status_code == 403

    still_hers = client.get(f"{NOTES}/{hers['ref']}", headers=auth(ALICE_TOKEN))
    assert still_hers.json()["body"] == "untouched"


@pytest.mark.usefixtures("alice")
def test_a_note_is_filed_against_the_caller_and_there_is_no_field_to_say_otherwise(
    client: Any,
) -> None:
    response = client.post(
        NOTES, json={"title": "spoofed", "owner_id": str(BOB_ID)}, headers=auth(ALICE_TOKEN)
    )

    assert response.status_code == 422, "an unknown key is refused, not ignored"
    assert response.json()["error"]["code"] == "invalid_request"


@pytest.mark.parametrize("method", ["get", "post", "patch", "delete"])
def test_every_route_requires_a_bearer(client: Any, method: str) -> None:
    """PLAN: auth-required on every route. Parametrised so a route added without the dependency is
    caught here rather than in review."""
    target = NOTES if method in {"get", "post"} else f"{NOTES}/NOTE-1"
    response = getattr(client, method)(target, **({"json": {}} if method == "patch" else {}))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"
    assert response.headers["WWW-Authenticate"] == "Bearer"


# --- The list -------------------------------------------------------------------------------------


@pytest.mark.usefixtures("alice")
def test_the_list_is_an_envelope_with_a_named_key(client: Any) -> None:
    """PLAN §Implementation decisions fixes the shape up front, so `summary` and `next_cursor` are
    additive when V2b and a paging card arrive rather than a breaking change to a bare array."""
    empty = client.get(NOTES, headers=auth(ALICE_TOKEN))

    assert empty.json() == {"notes": []}, "an empty page is a definitive zero state"

    create(client, ALICE_TOKEN, title="one")
    filled = client.get(NOTES, headers=auth(ALICE_TOKEN)).json()

    assert set(filled) == {"notes"}
    assert set(filled["notes"][0]) == {
        "ref",
        "id",
        "title",
        "body",
        "path",
        "created_at",
        "updated_at",
    }


@pytest.mark.usefixtures("alice")
def test_a_list_row_is_the_same_object_a_single_read_returns(client: Any) -> None:
    """One shape for a note, wherever it appears. Projection is ``render()``'s job in the client
    (ADR 0004), not something the API does differently per verb."""
    created = create(client, ALICE_TOKEN, title="same shape", body="x" * 2000)

    (listed,) = client.get(NOTES, headers=auth(ALICE_TOKEN)).json()["notes"]
    read = client.get(f"{NOTES}/{created['ref']}", headers=auth(ALICE_TOKEN)).json()

    assert listed == read


@pytest.mark.usefixtures("alice")
def test_the_list_is_newest_first_with_a_deterministic_tie_break(client: Any) -> None:
    refs = [create(client, ALICE_TOKEN, title=f"note {n}")["ref"] for n in range(5)]

    listed = [note["ref"] for note in client.get(NOTES, headers=auth(ALICE_TOKEN)).json()["notes"]]

    assert listed == list(reversed(refs))
    assert listed == [
        note["ref"] for note in client.get(NOTES, headers=auth(ALICE_TOKEN)).json()["notes"]
    ], "the same query twice gives the same order"


# --- Writes: ADR 0009's no-precondition case ------------------------------------------------------


@pytest.mark.usefixtures("alice")
def test_a_write_that_omits_the_precondition_is_a_plain_overwrite(client: Any) -> None:
    """SLICES §V1: "A write omitting the precondition is accepted as a plain overwrite."

    ADR 0009 §Decision is explicit that this is the specified behaviour and not a gap: the
    precondition is "a guarantee available to any client that wants it, not a tax on every caller",
    so `curl` works without a read-first dance. The branch for a write that *does* carry one is
    below.
    """
    note = create(client, ALICE_TOKEN, title="contended", body="first")

    first = client.patch(f"{NOTES}/{note['ref']}", json={"body": "one"}, headers=auth(ALICE_TOKEN))
    second = client.patch(f"{NOTES}/{note['ref']}", json={"body": "two"}, headers=auth(ALICE_TOKEN))

    assert first.status_code == second.status_code == 200
    assert second.json()["body"] == "two"
    assert second.json()["updated_at"] > note["updated_at"], "the token moves on every real write"


@pytest.mark.usefixtures("alice")
def test_moving_a_note_is_a_patch_to_one_column(client: Any) -> None:
    """ADR 0008's whole point. No move endpoint, no link rewriting, nothing else touched."""
    note = create(client, ALICE_TOKEN, title="moved", body="prose", path="inbox/moved.md")

    moved = client.patch(
        f"{NOTES}/{note['ref']}", json={"path": "archive/2026/moved.md"}, headers=auth(ALICE_TOKEN)
    )

    assert moved.status_code == 200
    assert moved.json()["path"] == "archive/2026/moved.md"
    assert moved.json()["ref"] == note["ref"], "identity survives the move"
    assert moved.json()["id"] == note["id"]
    assert moved.json()["title"] == "moved"
    assert moved.json()["body"] == "prose"


@pytest.mark.usefixtures("alice")
def test_an_empty_patch_changes_nothing_including_the_concurrency_token(client: Any) -> None:
    """``updated_at`` is ADR 0009's token. Restamping it for a write that changed nothing would
    invalidate every other client's precondition for no reason."""
    note = create(client, ALICE_TOKEN, title="untouched")

    unchanged = client.patch(f"{NOTES}/{note['ref']}", json={}, headers=auth(ALICE_TOKEN))

    assert unchanged.status_code == 200
    assert unchanged.json() == note


@pytest.mark.usefixtures("alice")
def test_a_null_is_refused_rather_than_treated_as_omitted_or_as_a_clear(client: Any) -> None:
    """All three columns are ``NOT NULL``, so ``null`` means neither "leave it" nor "empty it".
    Guessing either way is a silent no-op or a silent edit."""
    note = create(client, ALICE_TOKEN, title="kept")

    refused = client.patch(
        f"{NOTES}/{note['ref']}", json={"title": None}, headers=auth(ALICE_TOKEN)
    )

    assert refused.status_code == 422
    assert client.get(f"{NOTES}/{note['ref']}", headers=auth(ALICE_TOKEN)).json() == note


@pytest.mark.usefixtures("alice")
def test_a_value_longer_than_its_column_is_a_422_rather_than_a_500(client: Any) -> None:
    """The limits come from migration `0001`, so psycopg never gets to raise a ``DataError``."""
    over_length = client.post(NOTES, json={"title": "t" * 256}, headers=auth(ALICE_TOKEN))

    assert over_length.status_code == 422
    assert over_length.json()["error"]["field"] == "title"


@pytest.mark.usefixtures("alice")
def test_an_unbounded_body_really_is_unbounded(client: Any) -> None:
    """``body`` is ``TEXT`` and deliberately uncapped — a length cap on prose is a cap on the
    product (``app/models/note.py``)."""
    long_prose = "paragraph. " * 20_000

    created = create(client, ALICE_TOKEN, title="long", body=long_prose)

    assert created["body"] == long_prose


# --- Writes: ADR 0009's precondition --------------------------------------------------------------


@pytest.mark.usefixtures("alice")
def test_two_writers_read_one_note_and_the_second_gets_a_409_with_both_bodies(client: Any) -> None:
    """SLICES §V1's end-to-end row, **[mutate]**, and the whole reason ADR 0009 deviates from pandan
    ADR 0007.

    Under pure last-write-wins the second write wins and the first writer's paragraph is gone with
    no error, no notification and no copy of what was overwritten. Here it is refused, and refused
    with enough in the body for a human to resolve it — which is the only correct resolution for
    prose.

    The assertions are on the two bodies rather than on the status code alone, deliberately. A test
    that checks only `409` still passes against an implementation that rejects the write and tells
    the caller nothing, and that implementation is *worse* than LWW: the work is still lost, and now
    the caller knows only that it happened.
    """
    note = create(client, ALICE_TOKEN, title="runbook", body="the original three thousand words")

    # Both writers read. One page in a browser, one agent appending while it works a card — ADR
    # 0009's actual scenario, not a contrived one.
    hers = client.get(f"{NOTES}/{note['ref']}", headers=auth(ALICE_TOKEN)).json()
    theirs = client.get(f"{NOTES}/{note['ref']}", headers=auth(ALICE_TOKEN)).json()
    assert hers["updated_at"] == theirs["updated_at"], "both read the same version"

    first = client.patch(
        f"{NOTES}/{note['ref']}",
        json={"body": "her rewrite", "if_updated_at": hers["updated_at"]},
        headers=auth(ALICE_TOKEN),
    )
    second = client.patch(
        f"{NOTES}/{note['ref']}",
        json={"body": "his rewrite", "if_updated_at": theirs["updated_at"]},
        headers=auth(ALICE_TOKEN),
    )

    assert first.status_code == 200
    assert second.status_code == 409

    conflict = second.json()["error"]
    assert conflict["code"] == "note_conflict"
    assert conflict["attempted"]["body"] == "his rewrite", "what the caller tried to write"
    assert conflict["stored"]["body"] == "her rewrite", "what is there now"

    # And the refusal is a refusal: the row is exactly what the first write left.
    assert client.get(f"{NOTES}/{note['ref']}", headers=auth(ALICE_TOKEN)).json() == first.json()


@pytest.mark.usefixtures("alice")
def test_the_409_carries_enough_to_send_the_write_again(client: Any) -> None:
    """"Keep mine" in KAN-556's banner is this same `PATCH` again — ``attempted``'s body with
    ``stored``'s token — so the `409` has to carry both. Asserted by *doing* it, because a payload
    that merely looks sufficient is the kind that turns out not to be when the UI is written."""
    note = create(client, ALICE_TOKEN, title="contended", body="original")
    stale = note["updated_at"]

    client.patch(
        f"{NOTES}/{note['ref']}",
        json={"body": "theirs", "if_updated_at": stale},
        headers=auth(ALICE_TOKEN),
    )
    refused = client.patch(
        f"{NOTES}/{note['ref']}",
        json={"body": "mine", "if_updated_at": stale},
        headers=auth(ALICE_TOKEN),
    ).json()["error"]

    keep_mine = client.patch(
        f"{NOTES}/{note['ref']}",
        json={
            "body": refused["attempted"]["body"],
            "if_updated_at": refused["stored"]["updated_at"],
        },
        headers=auth(ALICE_TOKEN),
    )

    assert keep_mine.status_code == 200, keep_mine.text
    assert keep_mine.json()["body"] == "mine"


@pytest.mark.usefixtures("alice")
def test_a_matching_precondition_lets_the_write_through_and_moves_the_token(client: Any) -> None:
    """The other half, and the half a `409`-only test cannot distinguish from a broken feature: an
    implementation that refuses *everything* passes every conflict assertion above."""
    note = create(client, ALICE_TOKEN, title="uncontended", body="original")

    written = client.patch(
        f"{NOTES}/{note['ref']}",
        json={"body": "revised", "if_updated_at": note["updated_at"]},
        headers=auth(ALICE_TOKEN),
    )

    assert written.status_code == 200, written.text
    assert written.json()["body"] == "revised"
    assert written.json()["updated_at"] > note["updated_at"], "the token moves on a real write"

    # And the token it just returned is immediately usable as the next precondition, which is what
    # a read-modify-write loop (`kaya note edit`, the SPA's autosave) actually does.
    again = client.patch(
        f"{NOTES}/{note['ref']}",
        json={"body": "revised twice", "if_updated_at": written.json()["updated_at"]},
        headers=auth(ALICE_TOKEN),
    )
    assert again.status_code == 200, again.text


@pytest.mark.usefixtures("alice")
def test_the_precondition_round_trips_through_json_to_the_microsecond(client: Any) -> None:
    """The failure mode that would break the feature completely while passing a sloppier test.

    ``updated_at`` is ``timestamptz`` and Postgres stores **microseconds**. The client reads that
    value as JSON, holds it, and sends it back. Lose one microsecond anywhere in the loop —
    serialization, JSON, parsing, or a comparison that goes through a coarser type — and every
    correct write mismatches, so the feature rejects everything. A test using a round-numbered
    timestamp would never see it, so this one pins the row's stamp to ``.123456`` and then asserts
    both directions: the exact value is accepted, and a value one microsecond away is not.
    """
    from app.db import get_sessionmaker

    note = create(client, ALICE_TOKEN, title="precise", body="original")

    pinned = datetime(2026, 8, 7, 10, 11, 12, 123456, tzinfo=UTC)
    with get_sessionmaker()() as session:
        session.execute(
            text("UPDATE note SET updated_at = :stamp WHERE ref = :ref"),
            {"stamp": pinned, "ref": note["ref"]},
        )
        session.commit()

    printed = client.get(f"{NOTES}/{note['ref']}", headers=auth(ALICE_TOKEN)).json()["updated_at"]
    assert "123456" in printed, f"the microseconds did not survive the read: {printed}"
    assert datetime.fromisoformat(printed) == pinned

    off_by_one = (pinned + timedelta(microseconds=1)).isoformat()
    refused = client.patch(
        f"{NOTES}/{note['ref']}",
        json={"body": "mine", "if_updated_at": off_by_one},
        headers=auth(ALICE_TOKEN),
    )
    assert refused.status_code == 409, "a microsecond of drift is a mismatch, not a rounding error"

    accepted = client.patch(
        f"{NOTES}/{note['ref']}",
        json={"body": "mine", "if_updated_at": printed},
        headers=auth(ALICE_TOKEN),
    )
    assert accepted.status_code == 200, (
        "the value the API printed was refused when handed straight back — the round trip lost "
        f"precision somewhere: {accepted.text}"
    )


@pytest.mark.usefixtures("alice")
def test_the_stored_version_in_a_409_is_the_same_object_a_read_returns(client: Any) -> None:
    """One shape for a note wherever it appears, including inside an error. A `409` whose ``stored``
    were serialized differently from a `GET` would hand KAN-556 a value it could not send back."""
    note = create(client, ALICE_TOKEN, title="same shape", body="original")
    stale = note["updated_at"]
    client.patch(
        f"{NOTES}/{note['ref']}",
        json={"body": "theirs"},
        headers=auth(ALICE_TOKEN),
    )

    refused = client.patch(
        f"{NOTES}/{note['ref']}",
        json={"body": "mine", "if_updated_at": stale},
        headers=auth(ALICE_TOKEN),
    )
    read = client.get(f"{NOTES}/{note['ref']}", headers=auth(ALICE_TOKEN))

    assert refused.json()["error"]["stored"] == read.json()


# --- ADR 0009: which writes the precondition guards -----------------------------------------------


@pytest.mark.usefixtures("alice")
def test_a_stale_precondition_on_a_metadata_only_write_is_still_a_plain_write(client: Any) -> None:
    """ADR 0009 §Decision: "Metadata-only writes (title, path) stay plain LWW, because they're
    card-shaped fields where the original reasoning holds."

    So a rename carrying a precondition the body has moved past is **not** a conflict. The reasoning
    the ADR is pointing at is the payload one — a lost title is visible and cheap to redo, a lost
    3,000 words is neither — and the SPA "sends it always", so a `409` on a rename would be a banner
    a user learns to dismiss before the one that matters arrives.
    """
    note = create(client, ALICE_TOKEN, title="original title", body="original")
    stale = note["updated_at"]

    client.patch(
        f"{NOTES}/{note['ref']}", json={"body": "somebody else's edit"}, headers=auth(ALICE_TOKEN)
    )

    renamed = client.patch(
        f"{NOTES}/{note['ref']}",
        json={"title": "renamed", "if_updated_at": stale},
        headers=auth(ALICE_TOKEN),
    )
    moved = client.patch(
        f"{NOTES}/{note['ref']}",
        json={"path": "archive/2026/moved.md", "if_updated_at": stale},
        headers=auth(ALICE_TOKEN),
    )

    assert renamed.status_code == 200, renamed.text
    assert moved.status_code == 200, moved.text
    assert moved.json()["title"] == "renamed"
    assert moved.json()["body"] == "somebody else's edit", "the other writer's prose is untouched"


@pytest.mark.usefixtures("alice")
def test_a_stale_write_touching_both_metadata_and_the_body_is_refused_whole(client: Any) -> None:
    """The combination the ADR does not spell out. It is guarded, because it writes the body — and
    nothing is applied, because applying the title half of a refused write would be a second silent
    edit in the opposite direction, and would leave the caller unable to say what happened."""
    note = create(client, ALICE_TOKEN, title="original title", body="original")
    stale = note["updated_at"]
    client.patch(f"{NOTES}/{note['ref']}", json={"body": "theirs"}, headers=auth(ALICE_TOKEN))

    refused = client.patch(
        f"{NOTES}/{note['ref']}",
        json={"title": "renamed", "body": "mine", "if_updated_at": stale},
        headers=auth(ALICE_TOKEN),
    )

    assert refused.status_code == 409
    assert refused.json()["error"]["attempted"]["title"] == "renamed", "the diff shows the rename"

    current = client.get(f"{NOTES}/{note['ref']}", headers=auth(ALICE_TOKEN)).json()
    assert current["title"] == "original title", "no half of a refused write lands"
    assert current["body"] == "theirs"


@pytest.mark.usefixtures("alice")
def test_an_empty_patch_carrying_a_stale_precondition_is_a_no_op_not_a_conflict(
    client: Any,
) -> None:
    """A write that changes nothing loses nothing, so there is nothing to refuse."""
    note = create(client, ALICE_TOKEN, title="untouched", body="original")
    client.patch(f"{NOTES}/{note['ref']}", json={"body": "theirs"}, headers=auth(ALICE_TOKEN))

    unchanged = client.patch(
        f"{NOTES}/{note['ref']}",
        json={"if_updated_at": note["updated_at"]},
        headers=auth(ALICE_TOKEN),
    )

    assert unchanged.status_code == 200
    assert unchanged.json()["body"] == "theirs"


@pytest.mark.usefixtures("alice")
def test_a_naive_precondition_is_a_422_naming_the_field_rather_than_a_500(client: Any) -> None:
    """A timestamp without an offset cannot be compared against an aware one — Python raises, which
    would be a `500`. Guessing UTC would be worse still: the token would be silently shifted and the
    caller would see a `409` it could never clear. So it is a `422` that says which field."""
    note = create(client, ALICE_TOKEN, title="naive", body="original")

    refused = client.patch(
        f"{NOTES}/{note['ref']}",
        json={"body": "mine", "if_updated_at": "2026-08-07T10:11:12.123456"},
        headers=auth(ALICE_TOKEN),
    )

    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["field"] == "if_updated_at"


@pytest.mark.usefixtures("alice")
def test_a_precondition_under_another_name_is_refused_rather_than_ignored(client: Any) -> None:
    """``extra="forbid"`` matters more here than anywhere else on this route: a client that sends
    ``updated_at`` instead of ``if_updated_at`` would otherwise be silently unguarded — believing it
    had the guarantee, and wrong in the direction that loses work."""
    note = create(client, ALICE_TOKEN, title="misspelled", body="original")

    refused = client.patch(
        f"{NOTES}/{note['ref']}",
        json={"body": "mine", "updated_at": note["updated_at"]},
        headers=auth(ALICE_TOKEN),
    )

    assert refused.status_code == 422, refused.text


# --- ADR 0009: the assumptions the precondition rests on ------------------------------------------


@pytest.mark.usefixtures("alice")
def test_the_conflict_is_decided_against_what_is_committed_not_what_was_read(client: Any) -> None:
    """The precondition is checked against a **re-read** of the row, not against the copy the ref
    resolver loaded earlier in the same transaction.

    Without that, the guard contains the bug it exists to prevent. Two writers that both read before
    either committed would each compare against their own stale snapshot, both pass, and the second
    would overwrite the first — silently, which is the entire failure ADR 0009 closes. HTTP cannot
    stage that (one request, one transaction, serialised by the test client), so it is staged at the
    session level, where the stale snapshot is the ORM identity map.
    """
    from fastapi import HTTPException

    from app.api.concurrency import enforce_precondition
    from app.api.schemas import NoteUpdate
    from app.db import get_sessionmaker
    from app.models import Note

    created = create(client, ALICE_TOKEN, title="raced", body="original")
    sessions = get_sessionmaker()

    with sessions() as reader:
        mine = reader.get(Note, created["id"])
        assert mine is not None
        token = mine.updated_at

        with sessions() as writer:
            theirs = writer.get(Note, created["id"])
            assert theirs is not None
            theirs.body = "theirs, committed while the other writer was thinking"
            writer.commit()

        # `mine.updated_at` still says what it said before the other writer committed.
        assert mine.updated_at == token

        with pytest.raises(HTTPException) as raised:
            enforce_precondition(reader, mine, NoteUpdate(body="mine", if_updated_at=token))

        assert raised.value.status_code == 409
        assert raised.value.detail["error"]["stored"].body.startswith("theirs")


@pytest.mark.usefixtures("alice")
def test_two_writes_in_one_transaction_share_one_stamp(client: Any) -> None:
    """`now()` is **transaction** start time, so two writes inside one transaction stamp the same
    ``updated_at``. This test asserts that as it is, rather than fixing it, and the distinction is
    the point.

    As the contract ships it is correct: every request is its own transaction, so the token moves on
    every write a caller can make. `clock_timestamp()` would change it to statement time and would
    also stop `created_at == updated_at` holding on a freshly created note (``app/models/note.py``),
    which is a real property another test relies on.

    What it would not survive is a batch endpoint that writes one note twice in a single
    transaction: both writes would stamp the same value and the precondition would be silently
    defeated. That failure is invisible in review, so the assumption is pinned here — the day
    somebody writes that endpoint, this test fails in front of them and names the escape hatch.
    """
    from app.db import get_sessionmaker
    from app.models import Note

    created = create(client, ALICE_TOKEN, title="batched", body="original")
    sessions = get_sessionmaker()

    with sessions() as session:
        note = session.get(Note, created["id"])
        assert note is not None

        note.body = "first write"
        session.flush()
        first = note.updated_at

        note.body = "second write"
        session.flush()
        second = note.updated_at

        session.commit()

    assert first == second, (
        "`now()` is transaction start time. If this now fails, the stamp has become statement-time "
        "— which is fine for the precondition but breaks `created_at == updated_at` on create; "
        "see app/models/note.py."
    )

    # And across transactions it does move, which is what the contract as specified relies on.
    later = client.patch(
        f"{NOTES}/{created['ref']}", json={"body": "a third write"}, headers=auth(ALICE_TOKEN)
    )
    assert datetime.fromisoformat(later.json()["updated_at"]) > second


# --- The error contract on the wire ---------------------------------------------------------------


@pytest.mark.usefixtures("alice", "bob")
def test_no_refusal_reaches_the_wire_nested_under_detail(client: Any) -> None:
    """KAN-536's error-shape decision, asserted across every failure the surface can produce.

    ``detail`` is FastAPI's word. Un-nesting it here is what lets ``kaya-client`` (KAN-540) forward
    an API error object straight into ADR 0005's structured error rather than unwrapping one shape
    into another.
    """
    hers = create(client, ALICE_TOKEN, title="alice's")
    refusals = [
        client.get(NOTES),  # 401, no bearer
        client.get(NOTES, headers=auth("a-token-pandan-has-never-heard-of")),  # 401, rejected
        client.get(f"{NOTES}/{hers['ref']}", headers=auth(BOB_TOKEN)),  # 403
        client.get(f"{NOTES}/NOTE-9999", headers=auth(ALICE_TOKEN)),  # 404
        client.get(f"{NOTES}/{quote('#1', safe='')}", headers=auth(ALICE_TOKEN)),  # 400
        client.post(NOTES, json={}, headers=auth(ALICE_TOKEN)),  # 422
        client.patch(  # 409, ADR 0009's stale precondition
            f"{NOTES}/{hers['ref']}",
            json={"body": "mine", "if_updated_at": "2000-01-01T00:00:00+00:00"},
            headers=auth(ALICE_TOKEN),
        ),
        client.get("/api/v1/nope", headers=auth(ALICE_TOKEN)),  # 404 from Starlette
        client.put(f"{NOTES}/{hers['ref']}", headers=auth(ALICE_TOKEN)),  # 405 from Starlette
    ]

    assert [r.status_code for r in refusals] == [401, 401, 403, 404, 400, 422, 409, 404, 405]
    for response in refusals:
        assert set(response.json()) == {"error"}, f"{response.request.url} answered {response.text}"
        assert response.json()["error"]["code"], "every refusal carries a non-empty code"


@pytest.mark.usefixtures("alice")
def test_no_response_ever_echoes_the_token(client: Any) -> None:
    """Every path a token can take out of `/api/v1`, checked in one place (ADR 0002 / Q33)."""
    note = create(client, ALICE_TOKEN, title="a note")
    bodies = [
        client.get(NOTES, headers=auth(ALICE_TOKEN)).text,
        client.get(f"{NOTES}/{note['ref']}", headers=auth(ALICE_TOKEN)).text,
        client.get(f"{NOTES}/NOTE-9999", headers=auth(ALICE_TOKEN)).text,
        client.get(NOTES, headers=auth("a-stray-header-a-scanner-left-behind")).text,
        client.post(NOTES, json={"title": None}, headers=auth(ALICE_TOKEN)).text,
    ]

    for body in bodies:
        assert ALICE_TOKEN not in body
        assert "a-stray-header-a-scanner-left-behind" not in body
