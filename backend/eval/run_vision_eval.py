"""
Runs vision_questions.json through identify_exhibit (Qwen-VL), and for
cases where identify_exhibit doesn't confirm a single specific match
(ambiguous or unknown), also runs the same follow-up message the frontend
sends in that situation through the actual chat agent and judges the
reply — since "did the chat agent recommend the right real shops" isn't
an id-equality check the way identify_exhibit's own output is.

The follow-up message templates below must stay in sync with
frontend/index.html's photoInput change handler by hand — there's no
shared source between the JS and this Python harness.

Test photos live in eval/vision_photos/ — see vision_photos/README.md for
what's needed. A question whose photo is missing is reported as skipped,
not silently dropped or failed.

Usage: python -m eval.run_vision_eval (from backend/), or
python run_vision_eval.py (from backend/eval/).
"""
import base64
import json
import mimetypes
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
for _p in (HERE, HERE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from agent import run_agent
from run_eval import judge
from tools import describe_unmatched_photo, identify_exhibit

RESULTS_DIR = HERE / "results"
RESULTS_DIR.mkdir(exist_ok=True)
PHOTOS_DIR = HERE / "vision_photos"


def _ambiguous_message(match: dict) -> str:
    brand = match.get("brand_zh") or match.get("brand_en")
    return f"我拍了一张{brand}的照片，但看不出是哪家分店，能告诉我这个品牌在上海的所有分店吗？"


def _unknown_message(description: str) -> str:
    return f"我拍了一张照片，知识库里没有直接匹配到，AI看到的大致是：{description}。你知道这是哪里吗，或者上海有没有类似的地方？"


def grade_identify(expects: dict, match: dict) -> dict:
    kind = expects["kind"]
    if kind == "unknown":
        return {"pass": match["id"] == "unknown", "actual": match["id"]}
    if kind == "unknown_or_ambiguous":
        return {"pass": match["id"] in ("unknown", "ambiguous"), "actual": match["id"]}
    if kind == "ambiguous":
        ok = match["id"] == "ambiguous" and match.get("brand_en", "").lower().find(
            expects.get("brand_contains", "").lower()
        ) != -1
        returned_ids = sorted(o["id"] for o in match.get("options", []))
        expected_ids = sorted(expects.get("expected_option_ids", []))
        ok = ok and returned_ids == expected_ids
        return {"pass": ok, "actual": match["id"], "returned_options": returned_ids}
    # kind == "match"
    return {"pass": match["id"] == expects.get("expected_id"), "actual": match["id"]}


def main():
    questions = json.loads((HERE / "vision_questions.json").read_text(encoding="utf-8"))
    results = []
    skipped = []

    for q in questions:
        image_path = PHOTOS_DIR / q["image"]
        if not image_path.exists():
            skipped.append(q["image"])
            continue

        image_b64 = base64.b64encode(image_path.read_bytes()).decode()
        media_type = mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
        match = identify_exhibit(image_b64, media_type=media_type)

        identify_score = grade_identify(q["expects_identify"], match)
        result = {
            "id": q["id"],
            "category": q["category"],
            "identify_result": match["id"],
            "identify_pass": identify_score["pass"],
        }

        if "expects_chat" in q:
            if match["id"] == "ambiguous":
                followup = _ambiguous_message(match)
            else:
                description = describe_unmatched_photo(image_b64, media_type=media_type)
                followup = _unknown_message(description)
            reply = run_agent(followup, user_id="")["reply"]
            chat_score = judge(followup, q["expects_chat"], reply)
            result.update(
                {
                    "followup_message": followup,
                    "reply": reply,
                    "grounded": chat_score.get("grounded"),
                    "on_task": chat_score.get("on_task"),
                    "note": chat_score.get("note"),
                }
            )
            print(
                f"[{q['id']}/{q['category']}] identify_pass={identify_score['pass']} "
                f"grounded={chat_score.get('grounded')} on_task={chat_score.get('on_task')} "
                f"- {chat_score.get('note')}"
            )
        else:
            print(f"[{q['id']}/{q['category']}] identify_pass={identify_score['pass']} (no chat follow-up)")

        results.append(result)

    if skipped:
        print(f"\nSkipped (photo not found in {PHOTOS_DIR}): {', '.join(skipped)}")
        print("See vision_photos/README.md to add them.")

    if results:
        id_passed = sum(1 for r in results if r["identify_pass"])
        print(f"\nidentify_exhibit: {id_passed}/{len(results)} passed")
        scored = [r for r in results if r.get("grounded") is not None]
        if scored:
            avg_grounded = sum(r["grounded"] for r in scored) / len(scored)
            avg_on_task = sum(r["on_task"] for r in scored) / len(scored)
            print(f"chat follow-up: avg grounded={avg_grounded:.2f}/2  avg on_task={avg_on_task:.2f}/2")

    out_path = RESULTS_DIR / f"vision_eval_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
