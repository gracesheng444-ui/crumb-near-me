"""
Community notes: visitors can leave a freeform tip about a place (a closure,
a menu change, a recommendation) that's genuinely separate from the curated
knowledge base — these are unverified, third-party claims, never treated as
grounded fact. The agent may surface them, but must disclose that they're
community-sourced, same as it discloses web_search results. See agent.py's
system prompt for the disclosure rule.

Stored in Supabase Postgres, not local SQLite — see collection.py's module
docstring for why.
"""
from datetime import datetime, timezone

from supabase_db import delete_rows, insert_row, select_rows, update_rows
from tools import _tokenize

TABLE = "community_notes"


def add_note(
    place_name: str,
    note: str,
    user_id: str | None = None,
    author_name: str | None = None,
    photo_url: str | None = None,
) -> dict:
    created_at = datetime.now(timezone.utc).isoformat()
    return insert_row(
        TABLE,
        {
            "user_id": user_id,
            "place_name": place_name,
            "note": note,
            "author_name": author_name,
            "photo_url": photo_url,
            "created_at": created_at,
        },
    )


def update_note(
    user_id: str,
    note_id: int,
    place_name: str | None = None,
    note: str | None = None,
) -> dict | None:
    patch = {}
    if place_name is not None:
        patch["place_name"] = place_name
    if note is not None:
        patch["note"] = note
    if not patch:
        return None
    rows = update_rows(TABLE, {"id": f"eq.{note_id}", "user_id": f"eq.{user_id}"}, patch)
    return rows[0] if rows else None


def list_notes(limit: int = 100) -> list[dict]:
    return select_rows(TABLE, {"order": "created_at.desc", "limit": limit})


def delete_note(user_id: str, note_id: int) -> bool:
    rows = delete_rows(TABLE, {"id": f"eq.{note_id}", "user_id": f"eq.{user_id}"})
    return bool(rows)


def search_notes(query: str, top_k: int = 3) -> list[dict]:
    """Keyword-overlap search over place_name + note text — same approach as
    tools.retrieve_info, but over unverified community-submitted notes."""
    query_tokens = _tokenize(query)
    rows = select_rows(TABLE, {})
    scored = []
    for row in rows:
        haystack = f"{row['place_name']} {row['note']}"
        score = len(query_tokens & _tokenize(haystack))
        if score > 0:
            scored.append((score, row))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [row for _, row in scored[:top_k]]
