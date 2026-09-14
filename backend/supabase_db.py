"""
Thin PostgREST client for our own backend-owned tables (dessert_logs,
community_notes). Always uses the service-role secret key, which bypasses
Row Level Security — this backend is the trusted gatekeeper for who's
allowed to read/write which rows (see main.py's _resolve_user_id), the same
trust model as the local-SQLite version this replaced.
"""
import os

import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY", "")

_HEADERS = {
    "apikey": SUPABASE_SECRET_KEY,
    "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
    "Content-Type": "application/json",
}


def _url(table: str) -> str:
    return f"{SUPABASE_URL}/rest/v1/{table}"


def insert_row(table: str, data: dict) -> dict:
    response = requests.post(
        _url(table),
        json=data,
        headers={**_HEADERS, "Prefer": "return=representation"},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()[0]


def select_rows(table: str, params: dict) -> list[dict]:
    response = requests.get(_url(table), params=params, headers=_HEADERS, timeout=10)
    response.raise_for_status()
    return response.json()


def update_rows(table: str, filters: dict, patch: dict) -> list[dict]:
    response = requests.patch(
        _url(table),
        params=filters,
        json=patch,
        headers={**_HEADERS, "Prefer": "return=representation"},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def delete_rows(table: str, filters: dict) -> list[dict]:
    """Returns the deleted rows (empty list if nothing matched)."""
    response = requests.delete(
        _url(table),
        params=filters,
        headers={**_HEADERS, "Prefer": "return=representation"},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()
