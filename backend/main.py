import base64
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # must run before agent/tools read env vars at import time

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agent import run_agent
from auth import get_user_id_for_token
from collection import (
    add_log,
    delete_log,
    list_logs,
    mark_log_eaten,
    save_photo,
    summarize_taste,
    update_log,
)
from community import add_note, delete_note, list_notes, update_note
from profile import get_profile, save_avatar_photo, save_profile
from tools import AUDIO_DIR, describe_unmatched_photo, identify_exhibit

app = FastAPI(title="Shanghai Dessert Guide Agent")

# In-memory session store keyed by a client-generated session id.
# Fine for a one-week demo; not meant to survive a server restart.
_sessions: dict[str, list[dict]] = {}


def _resolve_user_id(authorization: str | None, fallback: str) -> str:
    """Prefer the real, server-verified user id from a bearer token over
    whatever user_id a client form field claims — signed-in users can't be
    impersonated by someone guessing their id this way. Falls back to the
    client-supplied id (the existing anonymous/guest behavior) only when
    there's no valid session, so guest mode keeps working unchanged."""
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
        user_id = get_user_id_for_token(token)
        if user_id:
            return user_id
    return fallback


@app.get("/config")
def get_config():
    """Public config the frontend needs to talk to Supabase directly for
    signup/login/logout — both values are meant to be embedded client-side,
    same as Supabase's own docs show, so serving them isn't a secret leak."""
    return {
        "supabase_url": os.environ.get("SUPABASE_URL", ""),
        "supabase_publishable_key": os.environ.get("SUPABASE_PUBLISHABLE_KEY", ""),
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "frontend" / "index.html")


@app.get("/icon.png")
def icon():
    return FileResponse(Path(__file__).parent / "frontend" / "icon.png")


@app.post("/chat")
def chat(
    message: str = Form(...),
    session_id: str = Form("default"),
    user_id: str = Form(""),
    authorization: str | None = Header(None),
):
    user_id = _resolve_user_id(authorization, user_id)
    history = _sessions.get(session_id, [])
    result = run_agent(message, history, user_id=user_id)
    _sessions[session_id] = result["messages"]
    return {
        "reply": result["reply"],
        "audio_url": f"/audio/{result['audio_path'].split('/')[-1]}"
        if result["audio_path"]
        else None,
    }


@app.post("/identify")
async def identify(image: UploadFile = File(...)):
    image_bytes = await image.read()
    image_b64 = base64.b64encode(image_bytes).decode()
    media_type = image.content_type or "image/jpeg"
    match = identify_exhibit(image_b64, media_type=media_type)
    if match["id"] == "unknown":
        guess = describe_unmatched_photo(image_b64, media_type=media_type)
        match["description"] = guess["description"]
        match["confidence"] = guess["confidence"]
    return match


@app.post("/log")
async def create_log(
    user_id: str = Form(...),
    dessert_name: str = Form(...),
    store_name: str = Form(""),
    rating: int | None = Form(None),
    note: str = Form(""),
    photo: UploadFile | None = File(None),
    status: str = Form("eaten"),
    planned_date: str = Form(""),
    authorization: str | None = Header(None),
):
    user_id = _resolve_user_id(authorization, user_id)
    if status == "eaten" and (photo is None or not photo.filename):
        raise HTTPException(status_code=422, detail="a photo is required for an eaten log")
    photo_url = None
    if photo is not None and photo.filename:
        contents = await photo.read()
        photo_url = save_photo(contents, Path(photo.filename).suffix)
    return add_log(
        user_id=user_id,
        dessert_name=dessert_name,
        store_name=store_name or None,
        rating=rating,
        note=note or None,
        photo_url=photo_url,
        status=status,
        planned_date=planned_date or None,
    )


@app.get("/log")
def get_logs(user_id: str, authorization: str | None = Header(None)):
    return list_logs(_resolve_user_id(authorization, user_id))


@app.delete("/log/{log_id}")
def remove_log(log_id: int, user_id: str, authorization: str | None = Header(None)):
    deleted = delete_log(_resolve_user_id(authorization, user_id), log_id)
    return {"deleted": deleted}


@app.patch("/log/{log_id}")
def edit_log(
    log_id: int,
    user_id: str = Form(...),
    dessert_name: str = Form(...),
    store_name: str = Form(""),
    rating: int | None = Form(None),
    note: str = Form(""),
    planned_date: str = Form(""),
    authorization: str | None = Header(None),
):
    user_id = _resolve_user_id(authorization, user_id)
    updated = update_log(
        user_id=user_id,
        log_id=log_id,
        dessert_name=dessert_name,
        store_name=store_name,
        rating=rating,
        note=note,
        planned_date=planned_date,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="log entry not found")
    return updated


@app.post("/log/{log_id}/complete")
async def complete_log(
    log_id: int,
    user_id: str = Form(...),
    rating: int | None = Form(None),
    note: str = Form(""),
    photo: UploadFile | None = File(None),
    authorization: str | None = Header(None),
):
    """Graduate a planned reminder into a real eaten log."""
    user_id = _resolve_user_id(authorization, user_id)
    photo_url = None
    if photo is not None and photo.filename:
        contents = await photo.read()
        photo_url = save_photo(contents, Path(photo.filename).suffix)
    updated = mark_log_eaten(
        user_id=user_id,
        log_id=log_id,
        rating=rating,
        note=note or None,
        photo_url=photo_url,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="log entry not found")
    return updated


@app.get("/log/summary")
def get_summary(user_id: str, authorization: str | None = Header(None)):
    return {"summary": summarize_taste(_resolve_user_id(authorization, user_id))}


@app.post("/notes")
async def create_note(
    place_name: str = Form(...),
    note: str = Form(...),
    user_id: str = Form(""),
    author_name: str = Form(""),
    photo: UploadFile | None = File(None),
    authorization: str | None = Header(None),
):
    user_id = _resolve_user_id(authorization, user_id)
    photo_url = None
    if photo is not None and photo.filename:
        contents = await photo.read()
        photo_url = save_photo(contents, Path(photo.filename).suffix)
    return add_note(
        place_name=place_name,
        note=note,
        user_id=user_id or None,
        author_name=author_name or None,
        photo_url=photo_url,
    )


@app.get("/notes")
def get_notes():
    return list_notes()


@app.delete("/notes/{note_id}")
def remove_note(note_id: int, user_id: str, authorization: str | None = Header(None)):
    deleted = delete_note(_resolve_user_id(authorization, user_id), note_id)
    return {"deleted": deleted}


@app.patch("/notes/{note_id}")
def edit_note(
    note_id: int,
    user_id: str = Form(...),
    place_name: str = Form(...),
    note: str = Form(...),
    authorization: str | None = Header(None),
):
    user_id = _resolve_user_id(authorization, user_id)
    updated = update_note(user_id=user_id, note_id=note_id, place_name=place_name, note=note)
    if updated is None:
        raise HTTPException(status_code=404, detail="note not found")
    return updated


@app.get("/profile")
def read_profile(user_id: str, authorization: str | None = Header(None)):
    return get_profile(_resolve_user_id(authorization, user_id)) or {}


@app.post("/profile")
async def write_profile(
    user_id: str = Form(...),
    display_name: str = Form(...),
    avatar: str = Form(""),
    photo: UploadFile | None = File(None),
    authorization: str | None = Header(None),
):
    if photo is not None and photo.filename:
        contents = await photo.read()
        avatar = save_avatar_photo(contents, Path(photo.filename).suffix)
    return save_profile(_resolve_user_id(authorization, user_id), display_name.strip(), avatar)


app.mount("/audio", StaticFiles(directory=str(AUDIO_DIR)), name="audio")
