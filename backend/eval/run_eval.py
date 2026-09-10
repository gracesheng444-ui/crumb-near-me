"""
Runs test_questions.json through the agent, then uses Claude as a judge to
score each response for groundedness/correctness. Saves a timestamped
results file so you can track the score improving across iterations —
that trend is your "how did you make it better" evidence.

Usage: python -m eval.run_eval
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from agent import run_agent
from tools import get_client

HERE = Path(__file__).parent
RESULTS_DIR = HERE / "results"
RESULTS_DIR.mkdir(exist_ok=True)

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
    response = get_client().messages.create(
        model="claude-sonnet-5",
        max_tokens=200,
        messages=[
            {
                "role": "user",
                "content": JUDGE_PROMPT.format(
                    question=question, expects=expects, reply=reply
                ),
            }
        ],
    )
    text = "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"grounded": None, "on_task": None, "note": f"unparseable judge output: {text}"}


def main():
    questions = json.loads((HERE / "test_questions.json").read_text(encoding="utf-8"))
    results = []

    for q in questions:
        for lang in ("en", "zh"):
            question_text = q[f"question_{lang}"]
            outcome = run_agent(question_text)
            score = judge(question_text, q["expects"], outcome["reply"])
            results.append(
                {
                    "id": q["id"],
                    "lang": lang,
                    "question": question_text,
                    "reply": outcome["reply"],
                    **score,
                }
            )
            print(f"[{q['id']}/{lang}] grounded={score.get('grounded')} on_task={score.get('on_task')} - {score.get('note')}")

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
