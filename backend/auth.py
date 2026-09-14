"""
Verifies a Supabase-issued access token by asking Supabase's own
/auth/v1/user endpoint whether it's valid, rather than verifying the JWT
signature ourselves — this project uses Supabase's newer asymmetric JWT
signing keys, so there's no static shared secret to check locally, and
asking Supabase directly is simpler than fetching/caching its JWKS.

Signup, login, and logout all happen client-side via the Supabase JS SDK
(see frontend/index.html) — this module only answers "whose token is this."
"""
import os

import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_PUBLISHABLE_KEY = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "")


def get_user_id_for_token(token: str) -> str | None:
    if not token or not SUPABASE_URL:
        return None
    try:
        response = requests.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={"Authorization": f"Bearer {token}", "apikey": SUPABASE_PUBLISHABLE_KEY},
            timeout=5,
        )
    except requests.RequestException:
        return None
    if response.status_code != 200:
        return None
    return response.json().get("id")
