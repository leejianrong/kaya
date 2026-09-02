"""``R2ObjectStorage`` against a fake `boto3` S3 client — R14, KAN-1067/1068.

Mirrors `test_pandan_upstream.py`/`test_board_embed_upstream.py`'s shape: the request this class
puts on the SDK is asserted directly against a stand-in for `boto3`'s own client, rather than
against a real bucket — there is no live Cloudflare account or R2 bucket in this environment, see
`app/integrations/storage.py`'s module docstring.
"""

import io
from typing import Any

import pytest
from botocore.exceptions import ClientError

from app.integrations.storage import (
    ObjectStorageUnavailable,
    R2ObjectStorage,
    StoredObject,
)


class FakeBotoS3Client:
    """Just enough of `boto3`'s S3 client surface for `R2ObjectStorage` to drive, recording every
    call it receives the way `FakeCardEpicUpstream`/`FakeBoardEmbedUpstream` record theirs."""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], tuple[bytes, str]] = {}
        self.upload_calls: list[tuple[str, str, dict[str, Any]]] = []
        self.get_calls: list[tuple[str, str]] = []
        self.available = True

    def upload_fileobj(
        self, fileobj: Any, bucket: str, key: str, ExtraArgs: dict[str, Any] | None = None
    ) -> None:
        extra = ExtraArgs or {}
        self.upload_calls.append((bucket, key, extra))
        if not self.available:
            raise ClientError({"Error": {"Code": "500", "Message": "down"}}, "PutObject")
        self.objects[(bucket, key)] = (fileobj.read(), extra.get("ContentType", ""))

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        self.get_calls.append((Bucket, Key))
        if not self.available:
            raise ClientError({"Error": {"Code": "500", "Message": "down"}}, "GetObject")
        found = self.objects.get((Bucket, Key))
        if found is None:
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "not found"}}, "GetObject"
            )
        body, content_type = found
        return {"Body": io.BytesIO(body), "ContentType": content_type}


@pytest.fixture
def client() -> FakeBotoS3Client:
    return FakeBotoS3Client()


@pytest.fixture
def storage(client: FakeBotoS3Client) -> R2ObjectStorage:
    return R2ObjectStorage(
        bucket="kaya-attachments",
        endpoint_url="https://example.r2.cloudflarestorage.com",
        access_key_id="AKIAEXAMPLE",
        secret_access_key="a-caller-supplied-string-kaya-does-not-parse",
        client=client,
    )


# --- put ------------------------------------------------------------------------------------------


def test_put_uploads_under_the_given_key_with_its_content_type(
    storage: R2ObjectStorage, client: FakeBotoS3Client
) -> None:
    storage.put("42/abc.png", io.BytesIO(b"pixels"), content_type="image/png")

    assert client.upload_calls == [
        ("kaya-attachments", "42/abc.png", {"ContentType": "image/png"})
    ]
    assert client.objects[("kaya-attachments", "42/abc.png")] == (b"pixels", "image/png")


def test_put_raises_object_storage_unavailable_on_a_client_error(
    storage: R2ObjectStorage, client: FakeBotoS3Client
) -> None:
    client.available = False

    with pytest.raises(ObjectStorageUnavailable):
        storage.put("42/abc.png", io.BytesIO(b"pixels"), content_type="image/png")


# --- get ------------------------------------------------------------------------------------------


def test_get_returns_the_stored_bytes_and_content_type(
    storage: R2ObjectStorage, client: FakeBotoS3Client
) -> None:
    storage.put("42/abc.png", io.BytesIO(b"pixels"), content_type="image/png")

    found = storage.get("42/abc.png")

    assert found == StoredObject(body=b"pixels", content_type="image/png")
    assert client.get_calls == [("kaya-attachments", "42/abc.png")]


def test_get_returns_none_for_a_missing_key_rather_than_raising(
    storage: R2ObjectStorage, client: FakeBotoS3Client
) -> None:
    """A missing key is an ordinary outcome (a deleted row's object, an upload that never
    finished) — `ObjectStorage.get`'s contract is `None`, not an exception, for this case."""
    assert storage.get("nothing/here.png") is None
    assert client.get_calls == [("kaya-attachments", "nothing/here.png")]


def test_get_raises_object_storage_unavailable_for_a_real_failure(
    storage: R2ObjectStorage, client: FakeBotoS3Client
) -> None:
    client.available = False

    with pytest.raises(ObjectStorageUnavailable):
        storage.get("42/abc.png")


# --- default_storage --------------------------------------------------------------------------


def test_default_storage_raises_when_r2_is_not_configured() -> None:
    """No R2 fields set: raises at first use rather than silently pretending a bucket exists —
    see `default_storage`'s own docstring for why this is not an ADR 0003 degradation."""
    from app.config import Settings
    from app.integrations.storage import default_storage

    # `_env_file=None` and the `KAYA_R2_*` aliases (not the Python field names) are the pattern
    # `test_card_resolution.py::test_settings_give_the_resolution_cache_its_own_env_var_and_default`
    # already uses — a `validation_alias` field only populates from its alias unless
    # `populate_by_name` is set, which `Settings` does not.
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    with pytest.raises(RuntimeError, match="KAYA_R2_BUCKET"):
        default_storage(settings)


def test_default_storage_builds_a_real_client_when_fully_configured() -> None:
    from app.config import Settings
    from app.integrations.storage import default_storage

    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        KAYA_R2_BUCKET="kaya-attachments",
        KAYA_R2_ENDPOINT_URL="https://example.r2.cloudflarestorage.com",
        KAYA_R2_ACCESS_KEY_ID="AKIAEXAMPLE",
        KAYA_R2_SECRET_ACCESS_KEY="a-caller-supplied-string-kaya-does-not-parse",
    )

    storage = default_storage(settings)

    assert isinstance(storage, R2ObjectStorage)
