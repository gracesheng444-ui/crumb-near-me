"""
Personal dessert collection: users log what they've eaten, see their history,
and get a short taste-summary generated from their own logged entries.

SQLite, not the in-memory session store — this has to survive a server
restart, unlike chat history.
"""
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from tools import get_client

DB_PATH = Path(__file__).parent / "collection.db"
PHOTO_DIR = Path(__file__).parent.parent / "dessert_photos"
PHOTO_DIR.mkdir(exist_ok=True)

MODEL = "claude-sonnet-5"

_rembg_session = None


def save_photo(contents: bytes, suffix: str) -> str:
    """Write an uploaded photo to disk and return its served URL."""
    filename = f"{uuid.uuid4().hex}{suffix or '.jpg'}"
    (PHOTO_DIR / filename).write_bytes(contents)
    return f"/dessert-photos/{filename}"


def save_photo_cutout(contents: bytes) -> str | None:
    """Run background removal on an uploaded photo and save the cutout as a
    transparent PNG. Returns None (never raises) if removal fails for any
    reason — a broken image or a first-run model-download hiccup should
    never block saving the original photo/log entry."""
    global _rembg_session
    try:
        from rembg import new_session, remove

        if _rembg_session is None:
            _rembg_session = new_session("u2net")
        cutout_bytes = remove(contents, session=_rembg_session)
        filename = f"{uuid.uuid4().hex}.png"
        (PHOTO_DIR / filename).write_bytes(cutout_bytes)
        return f"/dessert-photos/{filename}"
    except Exception as exc:  # noqa: BLE001 — background removal is a nice-to-have, never fatal
        print(f"background removal failed: {exc}", file=sys.stderr)
        return None


def _delete_photo(photo_url: str | None) -> None:
    if not photo_url:
        return
    (PHOTO_DIR / photo_url.rsplit("/", 1)[-1]).unlink(missing_ok=True)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dessert_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                dessert_name TEXT NOT NULL,
                store_name TEXT,
                rating INTEGER,
                note TEXT,
                photo_url TEXT,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'eaten',
                planned_date TEXT,
                photo_cutout_url TEXT
            )
            """
        )
        # migrations for DBs created before these columns existed
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(dessert_logs)")}
        if "photo_url" not in cols:
            conn.execute("ALTER TABLE dessert_logs ADD COLUMN photo_url TEXT")
        if "status" not in cols:
            conn.execute("ALTER TABLE dessert_logs ADD COLUMN status TEXT NOT NULL DEFAULT 'eaten'")
        if "planned_date" not in cols:
            conn.execute("ALTER TABLE dessert_logs ADD COLUMN planned_date TEXT")
        if "photo_cutout_url" not in cols:
            conn.execute("ALTER TABLE dessert_logs ADD COLUMN photo_cutout_url TEXT")


init_db()


def add_log(
    user_id: str,
    dessert_name: str,
    store_name: str | None = None,
    rating: int | None = None,
    note: str | None = None,
    photo_url: str | None = None,
    status: str = "eaten",
    planned_date: str | None = None,
    photo_cutout_url: str | None = None,
) -> dict:
    created_at = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO dessert_logs
                (user_id, dessert_name, store_name, rating, note, photo_url, created_at, status, planned_date, photo_cutout_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, dessert_name, store_name, rating, note, photo_url, created_at, status, planned_date, photo_cutout_url),
        )
        row_id = cur.lastrowid
    return {
        "id": row_id,
        "user_id": user_id,
        "dessert_name": dessert_name,
        "store_name": store_name,
        "rating": rating,
        "note": note,
        "photo_url": photo_url,
        "created_at": created_at,
        "status": status,
        "planned_date": planned_date,
        "photo_cutout_url": photo_cutout_url,
    }


def mark_log_eaten(
    user_id: str,
    log_id: int,
    rating: int | None = None,
    note: str | None = None,
    photo_url: str | None = None,
    photo_cutout_url: str | None = None,
) -> dict | None:
    """Graduate a planned reminder into a real eaten log, timestamped now."""
    created_at = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        cur = conn.execute(
            """
            UPDATE dessert_logs
            SET status = 'eaten',
                created_at = ?,
                rating = COALESCE(?, rating),
                note = COALESCE(?, note),
                photo_url = COALESCE(?, photo_url),
                photo_cutout_url = COALESCE(?, photo_cutout_url)
            WHERE id = ? AND user_id = ?
            """,
            (created_at, rating, note, photo_url, photo_cutout_url, log_id, user_id),
        )
        if cur.rowcount == 0:
            return None
        row = conn.execute("SELECT * FROM dessert_logs WHERE id = ?", (log_id,)).fetchone()
    return dict(row)


def list_logs(user_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM dessert_logs WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def delete_log(user_id: str, log_id: int) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT photo_url, photo_cutout_url FROM dessert_logs WHERE id = ? AND user_id = ?",
            (log_id, user_id),
        ).fetchone()
        cur = conn.execute(
            "DELETE FROM dessert_logs WHERE id = ? AND user_id = ?", (log_id, user_id)
        )
    if row is not None:
        _delete_photo(row["photo_url"])
        _delete_photo(row["photo_cutout_url"])
    return cur.rowcount > 0


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

    response = get_client().messages.create(
        model=MODEL,
        max_tokens=300,
        system=(
            "You summarize someone's dessert taste from their own logged entries. "
            "Be specific and concrete — call out actual flavors/patterns you see in "
            "the data (e.g. concentration preferences, sweetness tolerance, favorite "
            "categories), not generic praise. Only state patterns the data actually "
            "supports — with few entries, say so rather than overgeneralizing. Plain "
            "conversational text, no markdown, 2-4 sentences, reply in the same "
            "language as the entries (Chinese or English)."
        ),
        messages=[
            {
                "role": "user",
                "content": f"Here are the desserts I've logged:\n{log_text}\n\nWhat's my taste profile?",
            }
        ],
    )
    return "".join(block.text for block in response.content if block.type == "text")
