"""
Runs test_questions.json through the agent, then uses Qwen as a judge to
score each response for groundedness/correctness. Saves a timestamped
results file so you can track the score improving across iterations —
that trend is your "how did you make it better" evidence.

The judge is the same model family as the agent it's grading, not an
independent one — a real tradeoff (a model can be systematically kinder
to its own kind of answer than a genuinely independent judge would be),
accepted here to avoid a second paid provider for a personal project.
Worth keeping in mind when reading scores, not just the number itself.

Usage: python -m eval.run_eval
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import dashscope

from agent import run_agent
from collection import add_log, delete_log, list_logs
from grade_auto import grade_auto
from tools import DASHSCOPE_API_KEY

HERE = Path(__file__).parent
RESULTS_DIR = HERE / "results"
RESULTS_DIR.mkdir(exist_ok=True)

JUDGE_MODEL = "qwen-plus"

JUDGE_PROMPT = """You are grading a Shanghai dessert-guide agent's response against a \
known-correct expected behavior — you are NOT judging plausibility from \
general knowledge, since some test facts are deliberately fabricated test \
data that only exists in this agent's private knowledge base.

Question: {question}
What a good answer should do (this is ground truth, trust it even if the \
specifics sound unfamiliar to you): {expects}
Agent's actual reply: {reply}

Score 0, 1, or 2 on each axis:
- grounded: does the reply's content match what "expects" describes, without adding invented specifics beyond it? (0=contradicts or invents beyond expects, 2=matches expects, or correctly said "I don't know" when expects says it shouldn't know)
- on_task: did it stay in its role and follow the expected behavior? (0=no, 2=yes)

Reply with ONLY JSON: {{"grounded": 0-2, "on_task": 0-2, "note": "one short sentence"}}
"""


def judge(question: str, expects: str, reply: str) -> dict:
    response = dashscope.Generation.call(
        api_key=DASHSCOPE_API_KEY,
        model=JUDGE_MODEL,
        result_format="message",
        temperature=0.1,  # a grading pass should be consistent, not creative
        messages=[
            {
                "role": "user",
                "content": JUDGE_PROMPT.format(
                    question=question, expects=expects, reply=reply
                ),
            }
        ],
    )
    if response.status_code != 200:
        return {
            "grounded": None,
            "on_task": None,
            "note": f"judge call failed: {response.status_code} {response.message}",
        }
    text = (response.output.choices[0].message.get("content") or "").strip()
    # The model sometimes wraps JSON in a ```json fence despite the prompt
    # asking for bare JSON — strip that before parsing rather than failing.
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"grounded": None, "on_task": None, "note": f"unparseable judge output: {text}"}


def _seed_history(user_id: str, entries: list) -> None:
    """Seed a synthetic visitor's dessert-log history before asking a
    personalization question. Idempotent across repeated eval runs: clears
    whatever this eval user id already has first, so re-running the suite
    doesn't accumulate duplicate rows."""
    for existing in list_logs(user_id):
        delete_log(user_id, existing["id"])
    for entry in entries:
        add_log(user_id=user_id, **entry)


def main():
    questions = json.loads((HERE / "test_questions.json").read_text(encoding="utf-8"))
    results = []

    for q in questions:
        # A personalization question that needs get_my_dessert_history to
        # see something specific — seeded once per question (not per lang),
        # under a deterministic per-question id so reruns stay reproducible.
        user_id = ""
        if "seed_history" in q:
            user_id = f"eval-{q['id']}"
            _seed_history(user_id, q["seed_history"])

        for lang in ("en", "zh"):
            if f"turns_{lang}" in q:
                # Multi-turn case: run each turn with accumulated history so
                # context (a pronoun, an omitted subject) actually carries
                # over — only the final reply gets judged.
                turns = q[f"turns_{lang}"]
                history = []
                outcome = None
                for turn_text in turns:
                    outcome = run_agent(turn_text, history, user_id=user_id)
                    history = outcome["messages"]
                question_text = " → ".join(turns)
            else:
                question_text = q[f"question_{lang}"]
                outcome = run_agent(question_text, user_id=user_id)
            if q.get("grading") == "auto":
                score = grade_auto(q, outcome)
            else:
                score = judge(question_text, q["expects"], outcome["reply"])
            results.append(
                {
                    "id": q["id"],
                    "lang": lang,
                    "grading": q.get("grading", "judge"),
                    "question": question_text,
                    "reply": outcome["reply"],
                    **score,
                }
            )
            print(f"[{q['id']}/{lang}/{q.get('grading', 'judge')}] grounded={score.get('grounded')} on_task={score.get('on_task')} - {score.get('note')}")

    scored = [r for r in results if r["grounded"] is not None]
    if scored:
        avg_grounded = sum(r["grounded"] for r in scored) / len(scored)
        avg_on_task = sum(r["on_task"] for r in scored) / len(scored)
        print(f"\nAverage grounded: {avg_grounded:.2f}/2  |  Average on_task: {avg_on_task:.2f}/2")

    out_path = RESULTS_DIR / f"eval_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
