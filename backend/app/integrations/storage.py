"""Object storage for note attachments — Cloudflare R2, behind a seam (R14, KAN-1067/1068/1069).

Follows ``app/auth/principal.py``'s pattern exactly: a ``Protocol`` two calls wide, a real
S3-compatible implementation (R2 speaks the S3 API), and a fake used in every unit and integration
test — the same "seam fakeable at the boundary" shape ``app/integrations/card_resolution.py`` and
``app/integrations/board_embed.py`` already use for pandan, applied to a second runtime dependency
this suite should not need a network — or a real bucket — for.

**There is no live Cloudflare account or R2 bucket wired into this repository or its CI secrets.**
Provisioning one is a manual step for the maintainer's own Cloudflare account, outside any PR's
scope; every test in this repository exercises the real request-shaping code in
``R2ObjectStorage`` only up to the boundary a fake `boto3` client can stand in for
(``tests/unit/test_storage.py``), and exercises the route/authorization behaviour above this module
entirely against ``FakeObjectStorage`` (``tests/integration/test_attachments_api.py``).

## Why `boto3`

R2 is S3-compatible: point an S3 SDK at ``https://<account>.r2.cloudflarestorage.com`` with SigV4
credentials and it works (Cloudflare's own docs). `backend/pyproject.toml` had no S3 client before
this card — `boto3` is the standard one, and hand-rolling SigV4 signing over `httpx` (this
package's only existing HTTP dependency) would be reimplementing what `botocore` already does
correctly, for a client this repo does not otherwise need to keep thin. Unlike `httpx`, which
doubles as `fastapi.testclient`'s transport (`backend/pyproject.toml`'s own comment), `boto3` has
no second job here — it exists for exactly this one seam.

## What this module deliberately does not do

No caching: an upload and a fetch are each one-shot, unlike `CardEpicCache`'s repeated reads of the
same ticket. No retry loop of its own — `botocore`'s client already retries transient errors, and a
second layer on top would just be a second place that policy lives. No presigned URLs and no
redirect to R2 directly: R14 is explicit that a note's attachment is **never** addressed by a
direct R2 URL — every read goes through kaya's own authorization
(`app/api/attachments.py`), so nothing here ever mints a URL a browser could reach without a kaya
bearer.
"""

from dataclasses import dataclass
from typing import Any, BinaryIO, Protocol

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from app.config import Settings

# Codes R2/S3 answer a missing-key `GetObject` with, across the two shapes botocore's error parsing
# has been observed to produce for this case (a strict AWS-style 404 vs. R2's own S3-compatible
# response) — verified against botocore's own `ClientError.response["Error"]["Code"]` shape rather
# than assumed, since a wrong guess here would surface a genuine miss as a 503 instead of a 404.
MISSING_KEY_CODES = frozenset({"NoSuchKey", "404"})


class ObjectStorageUnavailable(Exception):
    """R2 could not be reached, or refused a request for a reason that is not "this key does not
    exist" (`get` reports that case as `None` instead — see `ObjectStorage.get`). Carries no
    credential, mirroring `app.auth.principal.UpstreamUnavailable` and
    `app.integrations.card_resolution.CardEpicUnavailable`."""


@dataclass(frozen=True, slots=True)
class StoredObject:
    """What `ObjectStorage.get` hands back on a hit: the bytes, and the content type they were
    stored with."""

    body: bytes
    content_type: str


class ObjectStorage(Protocol):
    """The two calls an attachment needs, behind a seam fakeable at the boundary — the same
    reasoning `CardEpicUpstream`/`BoardEmbedUpstream` give for pandan, aimed at R2 instead."""

    def put(self, key: str, body: BinaryIO, *, content_type: str) -> None:
        """Upload ``body`` under ``key``, overwriting any existing object at that key. ``body`` is
        read progressively by the underlying client rather than required to already be a `bytes`
        object, so a large attachment does not have to be materialised twice."""
        ...

    def get(self, key: str) -> StoredObject | None:
        """The object at ``key``, or ``None`` if there is none. ``None`` rather than raising: a
        missing key is an ordinary, expected outcome (the row was deleted, or the object never
        finished uploading), not the network failure `ObjectStorageUnavailable` reports."""
        ...


class R2ObjectStorage:
    """`ObjectStorage` over a real bucket, via `boto3`'s S3 client pointed at R2's S3-compatible
    endpoint. See the module docstring for why `boto3` and why there is nothing here presigning a
    URL."""

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        region: str = "auto",
        client: Any = None,
    ) -> None:
        self._bucket = bucket
        # `client` passed in (tests only) carries its own configuration; built here otherwise —
        # the same asymmetry `PandanCardEpicUpstream`'s constructor comment argues for its client.
        self._client = client if client is not None else boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
            config=BotoConfig(signature_version="s3v4"),
        )

    def put(self, key: str, body: BinaryIO, *, content_type: str) -> None:
        try:
            self._client.upload_fileobj(
                body, self._bucket, key, ExtraArgs={"ContentType": content_type}
            )
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStorageUnavailable(f"could not upload {key!r} to R2") from exc

    def get(self, key: str) -> StoredObject | None:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in MISSING_KEY_CODES:
                return None
            raise ObjectStorageUnavailable(f"could not fetch {key!r} from R2") from exc
        except BotoCoreError as exc:
            raise ObjectStorageUnavailable(f"could not fetch {key!r} from R2") from exc

        content_type = response.get("ContentType") or "application/octet-stream"
        return StoredObject(body=response["Body"].read(), content_type=content_type)


def default_storage(settings: Settings) -> ObjectStorage:
    """Build the real client from `Settings`. Raises rather than degrading, unlike
    `card_resolution.py`'s `default_upstream` — that upstream *always* has somewhere to point
    (`pandan_url` has a real default); attachments have no such fallback when the four R2 fields are
    unset, so a route that reached this with nothing configured should fail loudly at first use, the
    same way a missing `DATABASE_URL` fails loudly rather than silently no-opping (`app/db.py`).
    ADR 0003's "nothing may block on pandan" is about kaya's own availability never depending on an
    upstream *it does not own*; it says nothing about a feature that has no storage configured
    behaving as though it works.
    """
    if (
        settings.r2_bucket is None
        or settings.r2_endpoint_url is None
        or settings.r2_access_key_id is None
        or settings.r2_secret_access_key is None
    ):
        raise RuntimeError(
            "attachments are not configured: set KAYA_R2_BUCKET, KAYA_R2_ENDPOINT_URL, "
            "KAYA_R2_ACCESS_KEY_ID and KAYA_R2_SECRET_ACCESS_KEY"
        )
    return R2ObjectStorage(
        bucket=settings.r2_bucket,
        endpoint_url=settings.r2_endpoint_url,
        access_key_id=settings.r2_access_key_id,
        secret_access_key=settings.r2_secret_access_key,
        region=settings.r2_region,
    )
