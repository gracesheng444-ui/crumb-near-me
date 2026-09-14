"""
Photo storage in Supabase Storage (public bucket `dessert-photos`) instead
of local disk — local disk isn't persistent on the hosts this app runs on
(e.g. Render's free tier wipes it on every redeploy/restart), but Supabase
Storage is.
"""
import os
from pathlib import Path

import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY", "")

_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".heic": "image/heic",
}


def upload_file(bucket: str, filename: str, contents: bytes) -> str:
    """Uploads to a public bucket and returns the publicly-servable URL."""
    content_type = _CONTENT_TYPES.get(Path(filename).suffix.lower(), "application/octet-stream")
    response = requests.post(
        f"{SUPABASE_URL}/storage/v1/object/{bucket}/{filename}",
        data=contents,
        headers={
            "apikey": SUPABASE_SECRET_KEY,
            "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
            "Content-Type": content_type,
        },
        timeout=15,
    )
    response.raise_for_status()
    return f"{SUPABASE_URL}/storage/v1/object/public/{bucket}/{filename}"


def delete_file(bucket: str, filename: str) -> None:
    requests.delete(
        f"{SUPABASE_URL}/storage/v1/object/{bucket}/{filename}",
        headers={
            "apikey": SUPABASE_SECRET_KEY,
            "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
        },
        timeout=10,
    )
