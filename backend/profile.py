"""
Display profile (nickname + avatar) shown in Settings and set once during
onboarding. Stored in Supabase Postgres, one row per user — see
collection.py's module docstring for why local storage isn't durable enough.

`avatar` holds either a plain emoji character or a public Supabase Storage
URL for an uploaded photo — the frontend tells them apart by checking for
an "http" prefix, so no separate column is needed for the two avatar kinds.
"""
import uuid

from supabase_db import insert_row, select_rows, update_rows
from supabase_storage import delete_file, upload_file

TABLE = "user_profiles"
AVATAR_BUCKET = "avatars"


def get_profile(user_id: str) -> dict | None:
    rows = select_rows(TABLE, {"user_id": f"eq.{user_id}"})
    return rows[0] if rows else None


def save_avatar_photo(contents: bytes, suffix: str) -> str:
    """Upload a chosen album photo to Supabase Storage and return its public URL."""
    filename = f"{uuid.uuid4().hex}{suffix or '.jpg'}"
    return upload_file(AVATAR_BUCKET, filename, contents)


def save_profile(user_id: str, display_name: str, avatar: str) -> dict:
    existing = get_profile(user_id)
    if existing:
        old_avatar = existing.get("avatar") or ""
        if old_avatar.startswith("http") and old_avatar != avatar:
            delete_file(AVATAR_BUCKET, old_avatar.rsplit("/", 1)[-1])
        rows = update_rows(
            TABLE,
            {"user_id": f"eq.{user_id}"},
            {"display_name": display_name, "avatar": avatar},
        )
        return rows[0]
    return insert_row(
        TABLE, {"user_id": user_id, "display_name": display_name, "avatar": avatar}
    )
