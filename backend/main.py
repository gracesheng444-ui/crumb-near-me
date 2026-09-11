import base64
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # must run before agent/tools read env vars at import time

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agent import run_agent
from collection import add_log, delete_log, list_logs, summarize_taste
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
def create_log(
    user_id: str = Form(...),
    dessert_name: str = Form(...),
    store_name: str = Form(""),
    rating: int | None = Form(None),
    note: str = Form(""),
):
    return add_log(
        user_id=user_id,
        dessert_name=dessert_name,
        store_name=store_name or None,
        rating=rating,
        note=note or None,
    )


@app.get("/log")
def get_logs(user_id: str):
    return list_logs(user_id)


@app.delete("/log/{log_id}")
def remove_log(log_id: int, user_id: str):
    deleted = delete_log(user_id, log_id)
    return {"deleted": deleted}


@app.get("/log/summary")
def get_summary(user_id: str):
    return {"summary": summarize_taste(user_id)}


app.mount("/audio", StaticFiles(directory=str(AUDIO_DIR)), name="audio")
