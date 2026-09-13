import asyncio
import base64
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # must run before agent/tools read env vars at import time

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agent import run_agent
from collection import (
    PHOTO_DIR,
    add_log,
    delete_log,
    list_logs,
    mark_log_eaten,
    save_photo,
    save_photo_cutout,
    summarize_taste,
)
from community import add_note, delete_note, list_notes
from tools import AUDIO_DIR, identify_exhibit

app = FastAPI(title="Shanghai Dessert Guide Agent")

# In-memory session store keyed by a client-generated session id.
# Fine for a one-week demo; not meant to survive a server restart.
_sessions: dict[str, list[dict]] = {}


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
def chat(message: str = Form(...), session_id: str = Form("default")):
    history = _sessions.get(session_id, [])
    result = run_agent(message, history)
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
    match = identify_exhibit(image_b64, media_type=image.content_type or "image/jpeg")
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
):
    photo_url = None
    photo_cutout_url = None
    if photo is not None and photo.filename:
        contents = await photo.read()
        photo_url = save_photo(contents, Path(photo.filename).suffix)
        photo_cutout_url = await asyncio.to_thread(save_photo_cutout, contents)
    return add_log(
        user_id=user_id,
        dessert_name=dessert_name,
        store_name=store_name or None,
        rating=rating,
        note=note or None,
        photo_url=photo_url,
        status=status,
        planned_date=planned_date or None,
        photo_cutout_url=photo_cutout_url,
    )


@app.get("/log")
def get_logs(user_id: str):
    return list_logs(user_id)


@app.delete("/log/{log_id}")
def remove_log(log_id: int, user_id: str):
    deleted = delete_log(user_id, log_id)
    return {"deleted": deleted}


@app.post("/log/{log_id}/complete")
async def complete_log(
    log_id: int,
    user_id: str = Form(...),
    rating: int | None = Form(None),
    note: str = Form(""),
    photo: UploadFile | None = File(None),
):
    """Graduate a planned reminder into a real eaten log."""
    photo_url = None
    photo_cutout_url = None
    if photo is not None and photo.filename:
        contents = await photo.read()
        photo_url = save_photo(contents, Path(photo.filename).suffix)
        photo_cutout_url = await asyncio.to_thread(save_photo_cutout, contents)
    updated = mark_log_eaten(
        user_id=user_id,
        log_id=log_id,
        rating=rating,
        note=note or None,
        photo_url=photo_url,
        photo_cutout_url=photo_cutout_url,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="log entry not found")
    return updated


@app.get("/log/summary")
def get_summary(user_id: str):
    return {"summary": summarize_taste(user_id)}


@app.post("/notes")
async def create_note(
    place_name: str = Form(...),
    note: str = Form(...),
    user_id: str = Form(""),
    author_name: str = Form(""),
    photo: UploadFile | None = File(None),
):
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
def remove_note(note_id: int, user_id: str):
    deleted = delete_note(user_id, note_id)
    return {"deleted": deleted}


app.mount("/audio", StaticFiles(directory=str(AUDIO_DIR)), name="audio")
app.mount("/dessert-photos", StaticFiles(directory=str(PHOTO_DIR)), name="dessert-photos")
