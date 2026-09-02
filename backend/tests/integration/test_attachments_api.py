"""``/api/v1/notes/{ref}/attachments`` end to end, against a real Postgres and a faked R2 — R14,
KAN-1067/1068/1069.

`app.integrations.dependencies.get_object_storage` is overridden with `FakeObjectStorage`, the same
technique `test_note_links_api.py` uses for pandan: a real bucket is a manual ops step outside any
PR's scope (`app/integrations/storage.py`'s module docstring), and this route's own correctness —
authorization, key namespacing, the wire shape — needs no live R2 to prove.

**No `import app.*` at module top** — see the package docstring, and pandan's PR #17 trap: a
top-level `app` import runs at collection, before the `database_url` fixture sets `DATABASE_URL`.
"""

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]

# Shapeless on purpose, same reasoning as `test_note_links_api.py`'s tokens (ADR 0002: kaya has no
# token format, so a PAT-shaped fixture would quietly assert the opposite of the thing under test).
ALICE_TOKEN = "a-caller-supplied-string-kaya-does-not-parse"
BOB_TOKEN = "a-different-caller-supplied-string"
ALICE_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
BOB_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")

NOTES = "/api/v1/notes"


class FakeIdentityUpstream:
    """Pandan's `GET /api/v1/me`, faked — lifted from `test_note_links_api.py` rather than
    reinvented, so a change to the seam breaks one fake and not two."""

    def __init__(self) -> None:
        self.known: dict[str, Any] = {}
        self.available = True

    def introspect(self, bearer: str) -> Any:
        from app.auth.principal import UpstreamUnavailable

        if not self.available:
            raise UpstreamUnavailable("https://pandan.invalid/api/v1/me is unreachable")
        return self.known.get(bearer)


class FakeObjectStorage:
    """An `ObjectStorage` backed by a dict, counting every call — the same shape
    `FakeCardEpicUpstream` gives pandan, aimed at R2 instead."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.put_calls: list[tuple[str, str]] = []
        self.get_calls: list[str] = []
        self.available = True

    def put(self, key: str, body: Any, *, content_type: str) -> None:
        from app.integrations.storage import ObjectStorageUnavailable

        self.put_calls.append((key, content_type))
        if not self.available:
            raise ObjectStorageUnavailable("https://r2.invalid is unreachable")
        self.objects[key] = (body.read(), content_type)

    def get(self, key: str) -> Any:
        from app.integrations.storage import ObjectStorageUnavailable, StoredObject

        self.get_calls.append(key)
        if not self.available:
            raise ObjectStorageUnavailable("https://r2.invalid is unreachable")
        found = self.objects.get(key)
        return None if found is None else StoredObject(body=found[0], content_type=found[1])


def _alembic_config() -> Any:
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


@pytest.fixture
def identity() -> FakeIdentityUpstream:
    return FakeIdentityUpstream()


@pytest.fixture
def storage() -> FakeObjectStorage:
    return FakeObjectStorage()


@pytest.fixture
def client(
    database_url: str, identity: FakeIdentityUpstream, storage: FakeObjectStorage
) -> Iterator[Any]:
    """The real app with two dependencies overridden: identity, and object storage. Both are
    process-wide singletons by design, so both are reset around the test the way
    `test_note_links_api.py`'s `client` fixture resets the principal and resolution caches."""
    from alembic import command
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from app.auth.cache import PrincipalCache
    from app.auth.dependencies import get_resolver, reset_auth
    from app.auth.mirror import SqlAlchemyPrincipalMirror
    from app.auth.principal import Principal
    from app.auth.resolver import PrincipalResolver
    from app.auth.single_flight import SingleFlight
    from app.db import get_session, get_sessionmaker
    from app.integrations.dependencies import get_object_storage, reset_object_storage
    from app.main import app

    command.upgrade(_alembic_config(), "head")

    def empty() -> None:
        with get_sessionmaker()() as session:
            session.execute(text('TRUNCATE TABLE attachment, note_link, note, "user" CASCADE'))
            session.commit()

    empty()
    reset_auth()
    reset_object_storage()

    identity.known[ALICE_TOKEN] = Principal(id=ALICE_ID, email="alice@example.com")
    identity.known[BOB_TOKEN] = Principal(id=BOB_ID, email="bob@example.com")

    cache = PrincipalCache(positive_ttl=60.0, negative_ttl=10.0)
    single_flight = SingleFlight()

    from typing import Annotated

    from fastapi import Depends
    from sqlalchemy.orm import Session

    def identity_resolver(session: Annotated[Session, Depends(get_session)]) -> PrincipalResolver:
        return PrincipalResolver(
            upstream=identity,
            mirror=SqlAlchemyPrincipalMirror(session),
            cache=cache,
            single_flight=single_flight,
        )

    app.dependency_overrides[get_resolver] = identity_resolver
    app.dependency_overrides[get_object_storage] = lambda: storage
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        reset_auth()
        reset_object_storage()
        empty()


def auth(token: str = ALICE_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_note(client: Any, token: str = ALICE_TOKEN, **fields: str) -> dict[str, Any]:
    fields.setdefault("title", "a note")
    response = client.post(NOTES, json=fields, headers=auth(token))
    assert response.status_code == 201, response.text
    return response.json()


def upload(
    client: Any, ref: str, token: str = ALICE_TOKEN, *, filename: str = "photo.png",
    content: bytes = b"pretend-image-bytes", content_type: str = "image/png",
) -> Any:
    return client.post(
        f"{NOTES}/{ref}/attachments",
        headers=auth(token),
        files={"file": (filename, content, content_type)},
    )


# --- upload: KAN-1067 -----------------------------------------------------------------------------


def test_uploading_streams_to_storage_and_returns_a_markdown_reference(
    client: Any, storage: FakeObjectStorage
) -> None:
    note = create_note(client, title="Screenshots")

    response = upload(client, note["ref"])

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["content_type"] == "image/png"
    assert body["size_bytes"] == len(b"pretend-image-bytes")
    assert body["markdown"] == f"![photo.png](/api/v1/notes/{note['ref']}/attachments/{body['id']})"
    assert len(storage.put_calls) == 1
    (key, content_type) = storage.put_calls[0]
    assert content_type == "image/png"
    assert key.startswith(f"{note['id']}/")


def test_the_caller_supplied_filename_never_reaches_the_object_key(
    client: Any, storage: FakeObjectStorage
) -> None:
    """R14's own stated requirement: never the filename verbatim — a path-traversal-shaped name
    must not become a path-traversal-shaped key."""
    note = create_note(client)

    upload(client, note["ref"], filename="../../etc/passwd.png")

    (key, _content_type) = storage.put_calls[0]
    assert "passwd" not in key
    assert ".." not in key
    assert key.count("/") == 1


def test_uploading_to_another_users_note_is_403_and_never_reaches_storage(
    client: Any, storage: FakeObjectStorage
) -> None:
    bobs = create_note(client, BOB_TOKEN, title="Bob's note")

    response = upload(client, bobs["ref"], token=ALICE_TOKEN)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "note_forbidden"
    assert storage.put_calls == []


def test_storage_being_unreachable_is_503_and_writes_no_row(
    client: Any, storage: FakeObjectStorage
) -> None:
    from sqlalchemy import text

    from app.db import get_sessionmaker

    note = create_note(client)
    storage.available = False

    response = upload(client, note["ref"])

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "attachment_storage_unavailable"
    with get_sessionmaker()() as session:
        count = session.execute(text("SELECT count(*) FROM attachment")).scalar_one()
    assert count == 0, "a refused upload must not leave a row pointing at nothing"


def test_uploading_to_a_missing_note_is_the_same_404_as_every_other_ref_route(client: Any) -> None:
    prefixed = upload(client, "NOTE-9999")
    bare = upload(client, "9999")

    assert prefixed.status_code == bare.status_code == 404
    assert prefixed.json() == bare.json() == {
        "error": {"code": "note_not_found", "message": "no such note"}
    }


def test_an_oversized_upload_is_413_and_never_reaches_storage(
    client: Any, storage: FakeObjectStorage
) -> None:
    """`KAYA_R2_UPLOAD_MAX_BYTES` overridden down to a few bytes so the test does not have to move
    25 MiB (the real default) through the test client to prove the cap fires."""
    from app.config import Settings, get_settings
    from app.main import app

    note = create_note(client)

    app.dependency_overrides[get_settings] = lambda: Settings(  # type: ignore[call-arg]
        _env_file=None, KAYA_R2_UPLOAD_MAX_BYTES="4"
    )
    try:
        response = upload(client, note["ref"], content=b"more than four bytes")
    finally:
        del app.dependency_overrides[get_settings]

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "attachment_too_large"
    assert storage.put_calls == []


# --- render: KAN-1068 ------------------------------------------------------------------------


def test_fetching_an_attachment_returns_its_bytes_and_content_type(client: Any) -> None:
    note = create_note(client)
    created = upload(client, note["ref"], content=b"the actual bytes", content_type="image/webp")
    attachment_id = created.json()["id"]

    response = client.get(f"{NOTES}/{note['ref']}/attachments/{attachment_id}", headers=auth())

    assert response.status_code == 200
    assert response.content == b"the actual bytes"
    assert response.headers["content-type"].startswith("image/webp")


def test_fetching_a_missing_attachment_id_on_your_own_note_is_404(client: Any) -> None:
    note = create_note(client)

    response = client.get(f"{NOTES}/{note['ref']}/attachments/999999", headers=auth())

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "attachment_not_found"


def test_a_row_whose_object_is_gone_from_storage_is_404_not_500(
    client: Any, storage: FakeObjectStorage
) -> None:
    """The row can exist with nothing behind it — an upload that never finished, or an object
    deleted bucket-side. A dangling reference degrades to the same 404 a genuinely missing
    attachment gets, never a 500."""
    note = create_note(client)
    created = upload(client, note["ref"])
    storage.objects.clear()

    response = client.get(
        f"{NOTES}/{note['ref']}/attachments/{created.json()['id']}", headers=auth()
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "attachment_not_found"


def test_fetching_an_attachment_on_another_users_note_is_403(client: Any) -> None:
    bobs = create_note(client, BOB_TOKEN, title="Bob's note")
    created = upload(client, bobs["ref"], token=BOB_TOKEN)

    response = client.get(
        f"{NOTES}/{bobs['ref']}/attachments/{created.json()['id']}", headers=auth(ALICE_TOKEN)
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "note_forbidden"


# --- KAN-1069: the auth guardrail, [mutate] ------------------------------------------------------


def test_an_attachment_is_unreachable_through_a_note_that_does_not_own_it(
    client: Any, storage: FakeObjectStorage
) -> None:
    """SLICES-style `[mutate]` criterion: fetching another owner's attachment 404s rather than
    leaking its bytes. **[mutate]**

    Bob owns his own note and knows its ref — that part is legitimate, `NoteFromRef` authorizes it
    and lets the request through. What Bob does *not* own is the attachment id he supplies: it names
    a file Alice uploaded to a note of her own. `attachment` has no owner column
    (`app/models/attachment.py`) — the only thing standing between "Bob's own, authorized note" and
    "any attachment in the database" is `get_attachment`'s `Attachment.note_id == note.id` clause.

    This is the mutation CLAUDE.md's convention calls for, run for real and recorded in the PR body:
    delete that clause from `app/api/attachments.py` (`select(Attachment).where(Attachment.id ==
    attachment_id)`, dropping the `note_id` half of the filter) and this test goes from a `404` to a
    `200` carrying Alice's bytes — confirming the failure names the real leak — before the change is
    reverted with `git apply -R` on a tree that had this test's own work committed first.
    """
    alice_note = create_note(client, ALICE_TOKEN, title="Alice's private note")
    alice_upload = upload(
        client, alice_note["ref"], token=ALICE_TOKEN, content=b"alices-secret-diagram"
    )
    assert alice_upload.status_code == 201, alice_upload.text
    alice_attachment_id = alice_upload.json()["id"]

    bobs_note = create_note(client, BOB_TOKEN, title="Bob's own note")

    response = client.get(
        f"{NOTES}/{bobs_note['ref']}/attachments/{alice_attachment_id}", headers=auth(BOB_TOKEN)
    )

    assert response.status_code == 404, (
        "an attachment id that does not belong to the note in the URL must be unreachable through "
        "it, whoever owns either row"
    )
    assert response.json()["error"]["code"] == "attachment_not_found"
    assert b"alices-secret-diagram" not in response.content


def test_the_caller_own_bearer_never_reaches_storage_as_a_credential(
    client: Any, storage: FakeObjectStorage
) -> None:
    """A sanity check for the fake itself: `ObjectStorage` never sees a bearer at all — only a key
    and bytes — so there is no credential-shaped value on this seam for a leak to carry."""
    note = create_note(client)
    upload(client, note["ref"])

    assert all(ALICE_TOKEN not in str(call) for call in storage.put_calls)
