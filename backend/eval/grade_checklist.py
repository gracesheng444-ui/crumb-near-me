"""LLM-checked grading against a `ground_truth` checklist on the question.

Unlike grade_auto()'s regex patterns (fragile against phrasing variance —
e.g. "black\\s*sesame" never matched a hyphenated "black-sesame", and a
"推荐...#5" proximity pattern couldn't tell a recommendation from a warning)
and unlike judge()'s freeform prose "expects" (the model just holistically
eyeballs it against the whole reply), this checks a short list of concrete
points — each one hand-derived from the actual knowledge-base entry the
question is about, not paraphrased — against the reply one at a time. The
0/2 score is computed in code from the per-point verdicts, not asked of the
model, so scoring stays deterministic once the verdicts are in.

A `ground_truth` spec has two lists:
  must_state:     facts the reply needs to state (satisfied/missing/contradicted)
  must_not_state: claims the reply must avoid (violated/clear)

For amap questions, requires_tool_call is still checked first (mechanical,
not worth an LLM call), and the actual get_transit_directions result from
this turn is included in the grading prompt so the model can check the
reply's numbers against real tool output instead of a hand-typed number
that would go stale as Amap's live traffic estimates change run to run.
"""
import json

import dashscope

from grade_auto import FALLBACK_REPLIES, _search, _tool_was_called

GRADE_MODEL = "qwen-plus"

CHECKLIST_PROMPT = """You are checking a Shanghai dessert-guide agent's reply against a checklist of ground-truth points, each derived directly from the actual knowledge-base entry (or tool result) the question is about — trust these points as verified even if a specific detail sounds unfamiliar to you.

Question asked: {question}
{tool_context}
Points the reply MUST state (each is a verified fact):
{must_state}

Points the reply must NOT state (each would be a fabrication or a wrong claim):
{must_not_state}

Agent's actual reply: {reply}

For each "must state" point in order, decide one of: "satisfied" (the reply clearly states this, even in different words), "missing" (the reply doesn't address it), "contradicted" (the reply states something that conflicts with it).
For each "must not state" point in order, decide one of: "violated" (the reply does state this), "clear" (it doesn't).

Reply with ONLY JSON in this shape:
{{"must_state_results": ["satisfied"|"missing"|"contradicted", ...], "must_not_state_results": ["violated"|"clear", ...], "on_task": 0-2, "note": "one short sentence"}}

on_task: did the reply directly attempt to address what was actually asked (independent of the checklist above)? 0=no, 1=partially, 2=yes.
Keep each results list in the same order as the points listed, one verdict per point, same length as the input list (empty list if none given).
"""


def _get_tool_result_text(messages: list, tool_name: str) -> str | None:
    """Pulls the actual tool-result content for the most recent call to
    tool_name this conversation, so the grader can check reply numbers
    against real (possibly traffic-dependent) tool output instead of a
    hand-typed reference that would go stale."""
    call_id_to_result = {}
    last_call_id = None
    for msg in messages:
        if msg.get("role") == "assistant":
            for tc in msg.get("tool_calls") or []:
                if (tc.get("function") or {}).get("name") == tool_name:
                    last_call_id = tc.get("id")
        if msg.get("role") == "tool" and msg.get("tool_call_id") == last_call_id:
            call_id_to_result[last_call_id] = msg.get("content")
    return call_id_to_result.get(last_call_id)


def _parse_json_reply(text: str) -> dict | None:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def grade_checklist(question: dict, question_text: str, outcome: dict) -> dict:
    """Returns a dict shaped like judge()'s/grade_auto()'s output:
    {grounded, on_task, note}, plus the raw per-point verdicts for the
    review UI to display."""
    reply = outcome.get("reply") or ""
    messages = outcome.get("messages", [])

    if any(_search(p, reply) for p in FALLBACK_REPLIES):
        return {
            "grounded": 0,
            "on_task": 0,
            "note": "checklist-grade failed: agent returned a loop/error fallback reply, not a real answer",
        }

    spec = question.get("auto_grade", {})
    tool_context = ""
    if "requires_tool_call" in spec:
        tool_name = spec["requires_tool_call"]
        if not _tool_was_called(messages, tool_name):
            return {
                "grounded": 0,
                "on_task": 0,
                "note": f"checklist-grade failed: never called {tool_name}",
            }
        tool_result = _get_tool_result_text(messages, tool_name)
        if tool_result:
            tool_context = f"\nThis turn's actual {tool_name} tool result (the real ground truth for any distance/time claim): {tool_result}\n"

    ground_truth = question.get("ground_truth", {})
    must_state = ground_truth.get("must_state", [])
    must_not_state = ground_truth.get("must_not_state", [])
    if not must_state and not must_not_state:
        return {"grounded": None, "on_task": None, "note": "no ground_truth points defined for this question"}

    prompt = CHECKLIST_PROMPT.format(
        question=question_text,
        tool_context=tool_context,
        must_state="\n".join(f"{i + 1}. {p}" for i, p in enumerate(must_state)) or "(none)",
        must_not_state="\n".join(f"{i + 1}. {p}" for i, p in enumerate(must_not_state)) or "(none)",
        reply=reply,
    )

    from tools import DASHSCOPE_API_KEY  # deferred: avoids import cycles at module load

    response = dashscope.Generation.call(
        api_key=DASHSCOPE_API_KEY,
        model=GRADE_MODEL,
        result_format="message",
        temperature=0.1,
        messages=[{"role": "user", "content": prompt}],
    )
    if response.status_code != 200:
        return {
            "grounded": None,
            "on_task": None,
            "note": f"grader call failed: {response.status_code} {response.message}",
        }

    parsed = _parse_json_reply(response.output.choices[0].message.get("content") or "")
    if parsed is None:
        return {"grounded": None, "on_task": None, "note": "unparseable grader output"}

    ms_results = parsed.get("must_state_results", [])
    mns_results = parsed.get("must_not_state_results", [])
    satisfied = sum(1 for r in ms_results if r == "satisfied")
    contradicted = any(r == "contradicted" for r in ms_results)
    violated = any(r == "violated" for r in mns_results)
    total_required = len(must_state)

    if contradicted or violated:
        grounded = 0
    elif total_required == 0 or satisfied == total_required:
        grounded = 2
    elif satisfied >= total_required / 2:
        grounded = 1
    else:
        grounded = 0

    return {
        "grounded": grounded,
        "on_task": parsed.get("on_task"),
        "note": parsed.get("note", ""),
        "must_state_results": ms_results,
        "must_not_state_results": mns_results,
    }
