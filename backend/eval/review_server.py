"""Local-only eval review tool: browse questions, edit ground-truth key
points / reference answers, trigger a fresh agent run + model grade for a
single question, and record your own manual grade alongside it.

Deliberately NOT part of main.py / the deployed app: this reads and writes
eval/test_questions.json directly and makes paid LLM calls on click, so it
must never be reachable from the public site. Run it standalone and only
open it on localhost:

    cd backend && .venv/bin/python3 -m eval.review_server

Then open http://127.0.0.1:8010/ in a browser.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
for _p in (HERE, HERE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from dotenv import load_dotenv

load_dotenv(HERE.parent.parent / ".env")

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent import run_agent
from collection import add_log, delete_log, list_logs
from grade_auto import grade_auto
from grade_checklist import grade_checklist
from run_eval import judge

QUESTIONS_PATH = HERE / "test_questions.json"
RESULTS_DIR = HERE / "results"
MANUAL_GRADES_PATH = RESULTS_DIR / "manual_grades.json"

app = FastAPI()


def _load_questions() -> list:
    return json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))


def _save_questions(questions: list) -> None:
    QUESTIONS_PATH.write_text(json.dumps(questions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_manual_grades() -> dict:
    if not MANUAL_GRADES_PATH.exists():
        return {}
    return json.loads(MANUAL_GRADES_PATH.read_text(encoding="utf-8"))


def _save_manual_grades(grades: dict) -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    MANUAL_GRADES_PATH.write_text(json.dumps(grades, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _latest_results() -> dict:
    """Merges the most recent eval_*.json results file by "id/lang" key, so
    the UI can show the last known reply without needing a fresh run."""
    files = sorted(RESULTS_DIR.glob("eval_*.json"))
    if not files:
        return {}
    data = json.loads(files[-1].read_text(encoding="utf-8"))
    return {f"{r['id']}/{r['lang']}": r for r in data}


def _seed_history(user_id: str, entries: list) -> None:
    for existing in list_logs(user_id):
        delete_log(user_id, existing["id"])
    for entry in entries:
        add_log(user_id=user_id, **entry)


@app.get("/api/questions")
def get_questions():
    questions = _load_questions()
    latest = _latest_results()
    manual = _load_manual_grades()
    out = []
    for q in questions:
        for lang in ("en", "zh"):
            key = f"{q['id']}/{lang}"
            entry = dict(q)
            entry["lang"] = lang
            entry["question_text"] = (
                " → ".join(q[f"turns_{lang}"]) if f"turns_{lang}" in q else q.get(f"question_{lang}", "")
            )
            entry["last_result"] = latest.get(key)
            entry["manual_grade"] = manual.get(key)
            out.append(entry)
    return out


class QuestionUpdate(BaseModel):
    ground_truth: dict | None = None
    expects: str | None = None


@app.post("/api/questions/{question_id}")
def update_question(question_id: str, update: QuestionUpdate):
    questions = _load_questions()
    for q in questions:
        if q["id"] == question_id:
            if update.ground_truth is not None:
                q["ground_truth"] = update.ground_truth
            if update.expects is not None:
                q["expects"] = update.expects
            _save_questions(questions)
            return {"ok": True}
    raise HTTPException(status_code=404, detail=f"question {question_id!r} not found")


class RunRequest(BaseModel):
    id: str
    lang: str


@app.post("/api/run")
def run_question(req: RunRequest):
    questions = _load_questions()
    q = next((q for q in questions if q["id"] == req.id), None)
    if q is None:
        raise HTTPException(status_code=404, detail=f"question {req.id!r} not found")
    lang = req.lang

    user_id = ""
    if "seed_history" in q:
        user_id = f"eval-{q['id']}"
        _seed_history(user_id, q["seed_history"])

    if f"turns_{lang}" in q:
        turns = q[f"turns_{lang}"]
        history: list = []
        outcome = None
        for turn_text in turns:
            outcome = run_agent(turn_text, history, user_id=user_id)
            history = outcome["messages"]
        question_text = " → ".join(turns)
    else:
        question_text = q[f"question_{lang}"]
        outcome = run_agent(question_text, user_id=user_id)

    grading = q.get("grading", "judge")
    if grading == "auto":
        score = grade_auto(q, outcome)
    elif grading == "checklist":
        score = grade_checklist(q, question_text, outcome)
    else:
        score = judge(question_text, q.get("expects", ""), outcome["reply"])

    return {"question_text": question_text, "reply": outcome["reply"], "score": score}


class ManualGradeRequest(BaseModel):
    id: str
    lang: str
    grounded: int | None = None
    on_task: int | None = None
    note: str = ""


@app.post("/api/manual_grade")
def save_manual_grade(req: ManualGradeRequest):
    grades = _load_manual_grades()
    grades[f"{req.id}/{req.lang}"] = {
        "grounded": req.grounded,
        "on_task": req.on_task,
        "note": req.note,
    }
    _save_manual_grades(grades)
    return {"ok": True}


app.mount("/", StaticFiles(directory=str(HERE), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8010)
