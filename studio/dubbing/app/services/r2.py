"""
Cloudflare R2 client for dubbing media storage.

R2 is S3-compatible. This module is the only place in the dubbing
service that knows the bucket name, the endpoint URL, or the access
keys. Callers pass in a key path like:

    "dubbing/{workspace_id}/{job_id}/final.mp4"

and get back either an upload confirmation or a signed URL.

The bucket must be PRIVATE — public read is not what we want for
dubbed videos. Every download goes through a 5-minute signed URL.
"""
import os
import logging
from typing import Optional

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

R2_ENDPOINT = os.getenv("R2_ENDPOINT", "")           # e.g. https://<account>.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET = os.getenv("R2_BUCKET", "")
R2_PUBLIC_URL = os.getenv("R2_PUBLIC_URL", "")      # optional CDN URL, e.g. https://media.pird.com


def _client():
    if not (R2_ENDPOINT and R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY and R2_BUCKET):
        raise RuntimeError(
            "R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, and R2_BUCKET "
            "must all be set to use the R2 storage backend."
        )
    return boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4", region_name="auto"),
    )


def upload(
    key: str,
    file_bytes: bytes,
    mime: str = "application/octet-stream",
    cache_control: str = "private, max-age=300",
) -> str:
    """
    Upload bytes to R2 under the given key. Returns the key (not a URL).
    """
    client = _client()
    client.put_object(
        Bucket=R2_BUCKET,
        Key=key,
        Body=file_bytes,
        ContentType=mime,
        CacheControl=cache_control,
    )
    logger.info("[R2] Uploaded %d bytes to %s/%s", len(file_bytes), R2_BUCKET, key)
    return key


def upload_file(
    key: str,
    local_path: str,
    mime: str = "application/octet-stream",
) -> str:
    """Upload a file from disk to R2. Returns the key."""
    with open(local_path, "rb") as f:
        return upload(key, f.read(), mime=mime)


def download_file(key: str, local_path: str) -> None:
    """Download a file from R2 to local disk."""
    client = _client()
    client.download_file(R2_BUCKET, key, local_path)



def signed_url(
    key: str,
    ttl_seconds: int = 86400,
    filename: Optional[str] = None,
    inline: bool = True,
) -> str:
    """
    Generate a presigned URL valid for `ttl_seconds` (default 24 hours).
    Sets proper Content-Type and Content-Disposition response headers so browsers
    can stream/play videos natively in <video> elements and download with correct extensions.
    """
    client = _client()
    params: dict = {"Bucket": R2_BUCKET, "Key": key}

    lower_key = key.lower()
    if lower_key.endswith(".mp4"):
        params["ResponseContentType"] = "video/mp4"
    elif lower_key.endswith(".wav"):
        params["ResponseContentType"] = "audio/wav"
    elif lower_key.endswith(".mp3"):
        params["ResponseContentType"] = "audio/mpeg"
    elif lower_key.endswith(".zip"):
        params["ResponseContentType"] = "application/zip"

    disposition_type = "inline" if inline else "attachment"
    if filename:
        params["ResponseContentDisposition"] = f'{disposition_type}; filename="{filename}"'
    else:
        params["ResponseContentDisposition"] = disposition_type

    return client.generate_presigned_url(
        "get_object",
        Params=params,
        ExpiresIn=ttl_seconds,
    )


def signed_put_url(
    key: str,
    content_type: Optional[str] = None,
    ttl_seconds: int = 3600,
) -> str:
    """Generate a presigned PUT URL for direct client-to-R2 upload."""
    client = _client()
    params: dict = {
        "Bucket": R2_BUCKET,
        "Key": key,
    }
    if content_type:
        params["ContentType"] = content_type
    return client.generate_presigned_url(
        "put_object",
        Params=params,
        ExpiresIn=ttl_seconds,
    )



def delete(key: str) -> None:
    """Delete an object. Silently succeeds if the object doesn't exist."""
    try:
        _client().delete_object(Bucket=R2_BUCKET, Key=key)
        logger.info("[R2] Deleted %s/%s", R2_BUCKET, key)
    except ClientError as e:
        logger.warning("[R2] Delete failed for %s: %s", key, e)


def exists(key: str) -> bool:
    """Check if an object exists."""
    try:
        _client().head_object(Bucket=R2_BUCKET, Key=key)
        return True
    except ClientError:
        return False


def get_bytes(key: str) -> bytes:
    """Download an object as bytes. Use sparingly — prefer signed URLs for clients."""
    obj = _client().get_object(Bucket=R2_BUCKET, Key=key)
    return obj["Body"].read()


def dubbing_key(workspace_id: str, job_id: str, filename: str) -> str:
    """Build a standard R2 key for a dubbing artifact."""
    return f"dubbing/{workspace_id}/{job_id}/{filename}"


def chunk_key(workspace_id: str, job_id: str, chunk_id: str, kind: str = "tts") -> str:
    """Build a standard R2 key for a per-chunk artifact (raw TTS, assembled, etc)."""
    return f"dubbing/{workspace_id}/{job_id}/chunks/{kind}_{chunk_id}.wav"


def voice_ref_key(workspace_id: str, voice_id: str) -> str:
    """Build a standard R2 key for a stored voice reference audio."""
    return f"voice-refs/{workspace_id}/{voice_id}.wav"
