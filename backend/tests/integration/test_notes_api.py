"""``/api/v1/notes`` end to end: real routes, real Postgres, real HTTP. Only pandan is faked.

This is SLICES §V1's end-to-end list, minus the two rows other cards own (`409` is KAN-537, `k3d` is
KAN-538). Everything reaches the app the way a caller does — through Starlette's `Authorization`
parsing, the principal resolver, the ref resolver and a JSON body — so what is asserted is the wire
contract rather than a function's return value.

**No real PAT, and CI never needs one.** ADR 0002 made the upstream a Protocol so pandan could be
faked at exactly this seam; the fixtures below inject a dict. The token strings are deliberately
shapeless, because kaya has no token format and a PAT-shaped fixture would quietly assert the
opposite (and trip ``scripts/secret-scan.sh``, correctly).

**No ``import app.*`` at module top** — see the package docstring, and pandan's PR #17 trap.
"""

import uuid
from collections.abc import Iterator
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

    def resolver(session: Annotated[Session, Depends(get_session)]) -> PrincipalResolver:
        return PrincipalResolver(
            upstream=upstream,
            mirror=SqlAlchemyPrincipalMirror(session),
            cache=cache,
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
    so `curl` works without a read-first dance. KAN-537 adds the branch for a write that *does*
    carry one.
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
        client.get("/api/v1/nope", headers=auth(ALICE_TOKEN)),  # 404 from Starlette
        client.put(f"{NOTES}/{hers['ref']}", headers=auth(ALICE_TOKEN)),  # 405 from Starlette
    ]

    assert [r.status_code for r in refusals] == [401, 401, 403, 404, 400, 422, 404, 405]
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
