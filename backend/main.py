import base64
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # must run before agent/tools read env vars at import time

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agent import run_agent
from tools import AUDIO_DIR, identify_exhibit

app = FastAPI(title="Grand Gateway 66 Agent")

# In-memory session store keyed by a client-generated session id.
# Fine for a one-week demo; not meant to survive a server restart.
_sessions: dict[str, list[dict]] = {}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent.parent / "frontend" / "index.html")


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


app.mount("/audio", StaticFiles(directory=str(AUDIO_DIR)), name="audio")
