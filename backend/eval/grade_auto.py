"""Rule-based grading for questions marked "grading": "auto" in test_questions.json.

Unlike judge() in run_eval.py (an LLM call scoring against a prose `expects`
description), this never calls the model — it checks the reply text (and,
for Amap questions, whether the right tool actually got called) against a
structured `auto_grade` spec on the question. That's the point: Factual
lookup, Amap API, Knowledge base boundary, and Adversarial all have a
checkable ground truth (a fact in the knowledge base, a tool call that
either happened or didn't, a refusal that either happened or didn't), so a
regex/keyword check is both cheaper and more reproducible than an LLM judge
for these four categories. Synthesis, Chit-chat, and Multi-turn stay on the
judge() path since "did it synthesize well" isn't a keyword match.

auto_grade spec fields (all optional, combined with AND — every present
field must pass for the question to pass):
  keywords_all:        each regex must be found somewhere in the reply
  keywords_any:        at least one regex must be found in the reply
  keywords_forbidden:  none of these regexes may be found in the reply
  requires_tool_call:  name of a tool that must appear as a tool_use block
                        somewhere in the conversation (e.g. "get_transit_directions")

All regex matching is case-insensitive substring search (re.search), not
full-string match, and each pattern may itself use "|" to cover equivalent
phrasings (e.g. "22:?00|晚上?\\s*10\\s*点").
"""
import re


# The agent loop's own fallback strings (see agent.py) for a blank reply or
# a run that hit the hard turn cap without resolving. Neither is a real
# answer, no matter what auto_grade spec the question carries or whether a
# tool got called along the way — so these always fail a case outright.
FALLBACK_REPLIES = [
    r"got cut off there",
    r"got stuck reasoning about that",
]


def _search(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.IGNORECASE) is not None


def _tool_was_called(messages: list, tool_name: str) -> bool:
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            block_type = getattr(block, "type", None)
            block_name = getattr(block, "name", None)
            if block_type is None and isinstance(block, dict):
                block_type = block.get("type")
                block_name = block.get("name")
            if block_type == "tool_use" and block_name == tool_name:
                return True
    return False


def grade_auto(question: dict, outcome: dict) -> dict:
    """Returns a dict shaped like judge()'s output: {grounded, on_task, note}.

    grounded and on_task are always equal here (2 or 0) since a rule-based
    check doesn't distinguish "wrong content" from "off-role" the way an LLM
    judge can — it's a single pass/fail per question.
    """
    spec = question.get("auto_grade", {})
    reply = outcome.get("reply") or ""
    reasons = []
    passed = True

    if any(_search(p, reply) for p in FALLBACK_REPLIES):
        return {
            "grounded": 0,
            "on_task": 0,
            "note": "auto-grade failed: agent returned a loop/error fallback reply, not a real answer",
        }

    if "requires_tool_call" in spec:
        tool_name = spec["requires_tool_call"]
        if not _tool_was_called(outcome.get("messages", []), tool_name):
            passed = False
            reasons.append(f"never called {tool_name}")

    if "keywords_all" in spec:
        missing = [p for p in spec["keywords_all"] if not _search(p, reply)]
        if missing:
            passed = False
            reasons.append(f"missing required pattern(s): {missing}")

    if "keywords_any" in spec:
        if not any(_search(p, reply) for p in spec["keywords_any"]):
            passed = False
            reasons.append(f"none of the expected alternatives found: {spec['keywords_any']}")

    if "keywords_forbidden" in spec:
        hit = [p for p in spec["keywords_forbidden"] if _search(p, reply)]
        if hit:
            passed = False
            reasons.append(f"contains forbidden pattern(s): {hit}")

    score = 2 if passed else 0
    note = "auto-grade passed" if passed else "auto-grade failed: " + "; ".join(reasons)
    return {"grounded": score, "on_task": score, "note": note}
