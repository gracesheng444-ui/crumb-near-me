"""
Community notes: visitors can leave a freeform tip about a place (a closure,
a menu change, a recommendation) that's genuinely separate from the curated
knowledge base — these are unverified, third-party claims, never treated as
grounded fact. The agent may surface them, but must disclose that they're
community-sourced, same as it discloses web_search results. See agent.py's
system prompt for the disclosure rule.
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from tools import _tokenize

DB_PATH = Path(__file__).parent / "community.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS community_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                place_name TEXT NOT NULL,
                note TEXT NOT NULL,
                author_name TEXT,
                photo_url TEXT,
                created_at TEXT NOT NULL
            )
            """
        )


init_db()


def add_note(
    place_name: str,
    note: str,
    user_id: str | None = None,
    author_name: str | None = None,
    photo_url: str | None = None,
) -> dict:
    created_at = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO community_notes (user_id, place_name, note, author_name, photo_url, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, place_name, note, author_name, photo_url, created_at),
        )
        row_id = cur.lastrowid
    return {
        "id": row_id,
        "user_id": user_id,
        "place_name": place_name,
        "note": note,
        "author_name": author_name,
        "photo_url": photo_url,
        "created_at": created_at,
    }


def list_notes(limit: int = 100) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM community_notes ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def delete_note(user_id: str, note_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM community_notes WHERE id = ? AND user_id = ?",
            (note_id, user_id),
        )
        return cur.rowcount > 0


def search_notes(query: str, top_k: int = 3) -> list[dict]:
    """Keyword-overlap search over place_name + note text — same approach as
    tools.retrieve_info, but over unverified community-submitted notes."""
    query_tokens = _tokenize(query)
    with _connect() as conn:
        rows = [dict(row) for row in conn.execute("SELECT * FROM community_notes")]
    scored = []
    for row in rows:
        haystack = f"{row['place_name']} {row['note']}"
        score = len(query_tokens & _tokenize(haystack))
        if score > 0:
            scored.append((score, row))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [row for _, row in scored[:top_k]]
