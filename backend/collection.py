"""
Personal dessert collection: users log what they've eaten, see their history,
and get a short taste-summary generated from their own logged entries.

Stored in Supabase Postgres (not the in-memory session store, and not local
SQLite) so it survives a server restart or redeploy — local disk isn't
persistent on the hosts this app runs on.
"""
import uuid
from datetime import datetime, timezone

import dashscope

from supabase_db import delete_rows, insert_row, select_rows, update_rows
from supabase_storage import delete_file, upload_file
from tools import DASHSCOPE_API_KEY

MODEL = "qwen-plus"
TABLE = "dessert_logs"
PHOTO_BUCKET = "dessert-photos"


def save_photo(contents: bytes, suffix: str) -> str:
    """Upload a photo to Supabase Storage and return its public URL."""
    filename = f"{uuid.uuid4().hex}{suffix or '.jpg'}"
    return upload_file(PHOTO_BUCKET, filename, contents)


def _delete_photo(photo_url: str | None) -> None:
    if not photo_url:
        return
    delete_file(PHOTO_BUCKET, photo_url.rsplit("/", 1)[-1])


def add_log(
    user_id: str,
    dessert_name: str,
    store_name: str | None = None,
    rating: int | None = None,
    note: str | None = None,
    photo_url: str | None = None,
    photo_urls: list[str] | None = None,
    status: str = "eaten",
    planned_date: str | None = None,
) -> dict:
    created_at = datetime.now(timezone.utc).isoformat()
    return insert_row(
        TABLE,
        {
            "user_id": user_id,
            "dessert_name": dessert_name,
            "store_name": store_name,
            "rating": rating,
            "note": note,
            "photo_url": photo_url,
            "photo_urls": photo_urls,
            "created_at": created_at,
            "status": status,
            "planned_date": planned_date,
        },
    )


def mark_log_eaten(
    user_id: str,
    log_id: int,
    rating: int | None = None,
    note: str | None = None,
    photo_url: str | None = None,
) -> dict | None:
    """Graduate a planned reminder into a real eaten log, timestamped now."""
    patch = {"status": "eaten", "created_at": datetime.now(timezone.utc).isoformat()}
    if rating is not None:
        patch["rating"] = rating
    if note is not None:
        patch["note"] = note
    if photo_url is not None:
        patch["photo_url"] = photo_url
    rows = update_rows(TABLE, {"id": f"eq.{log_id}", "user_id": f"eq.{user_id}"}, patch)
    return rows[0] if rows else None


def update_log(
    user_id: str,
    log_id: int,
    dessert_name: str | None = None,
    store_name: str | None = None,
    rating: int | None = None,
    note: str | None = None,
    planned_date: str | None = None,
) -> dict | None:
    """Edit an existing entry's own fields (not a status change — see mark_log_eaten
    for graduating a planned entry to eaten)."""
    patch = {}
    if dessert_name is not None:
        patch["dessert_name"] = dessert_name
    if store_name is not None:
        patch["store_name"] = store_name or None
    if rating is not None:
        patch["rating"] = rating
    if note is not None:
        patch["note"] = note or None
    if planned_date is not None:
        patch["planned_date"] = planned_date or None
    if not patch:
        return None
    rows = update_rows(TABLE, {"id": f"eq.{log_id}", "user_id": f"eq.{user_id}"}, patch)
    return rows[0] if rows else None


def list_logs(user_id: str) -> list[dict]:
    return select_rows(TABLE, {"user_id": f"eq.{user_id}", "order": "created_at.desc"})


def delete_log(user_id: str, log_id: int) -> bool:
    rows = delete_rows(TABLE, {"id": f"eq.{log_id}", "user_id": f"eq.{user_id}"})
    if rows:
        _delete_photo(rows[0].get("photo_url"))
        _delete_photo(rows[0].get("photo_cutout_url"))
        for url in rows[0].get("photo_urls") or []:
            _delete_photo(url)
    return bool(rows)


def get_taste_history(user_id: str) -> list[dict]:
    """This user's own eaten-log entries, trimmed to what's useful for the
    chat agent to personalize recommendations with (no ids, photo paths, or
    other internal bookkeeping)."""
    logs = [log for log in list_logs(user_id) if log["status"] != "planned"]
    return [
        {
            "dessert_name": log["dessert_name"],
            "store_name": log["store_name"],
            "rating": log["rating"],
            "note": log["note"],
        }
        for log in logs
    ]


def summarize_taste(user_id: str) -> str:
    logs = [log for log in list_logs(user_id) if log["status"] != "planned"]
    if not logs:
        return "You haven't logged any desserts yet — add a few and I'll spot the patterns."

    lines = []
    for log in logs:
        parts = [log["dessert_name"]]
        if log["store_name"]:
            parts.append(f"at {log['store_name']}")
        if log["rating"] is not None:
            parts.append(f"rated {log['rating']}/5")
        if log["note"]:
            parts.append(f"note: {log['note']}")
        lines.append(" — ".join(parts))
    log_text = "\n".join(lines)

    response = dashscope.Generation.call(
        api_key=DASHSCOPE_API_KEY,
        model=MODEL,
        result_format="message",
        messages=[
            {
                "role": "system",
                "content": (
                    "You summarize someone's dessert taste from their own logged entries. "
                    "Be specific and concrete — call out actual flavors/patterns you see in "
                    "the data (e.g. concentration preferences, sweetness tolerance, favorite "
                    "categories), not generic praise. Only state patterns the data actually "
                    "supports — with few entries, say so rather than overgeneralizing. Plain "
                    "conversational text, no markdown, 2-4 sentences, reply in the same "
                    "language as the entries (Chinese or English)."
                ),
            },
            {
                "role": "user",
                "content": f"Here are the desserts I've logged:\n{log_text}\n\nWhat's my taste profile?",
            },
        ],
    )
    if response.status_code != 200:
        raise RuntimeError(f"Qwen error {response.status_code}: {response.message}")
    return response.output.choices[0].message.content
