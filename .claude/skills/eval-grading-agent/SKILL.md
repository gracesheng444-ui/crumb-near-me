---
name: eval-grading-agent
description: Runs backend/eval/run_eval.py against the Shanghai dessert guide agent and reports results, using rule-based auto-grading (grade_auto.py) for Amap/Adversarial, checklist grading (grade_checklist.py) for Factual lookup/Knowledge base boundary, and LLM-judge grading for Synthesis/Chit-chat/Multi-turn (Recommendation splits across auto and judge).
---

# Eval grading agent

Runs the eval suite and reports what passed, what failed, and why. Use
this when the user asks to "run the eval", "check the eval results", or
after knowledge-base or prompt changes that should be re-verified.

**A newly added knowledge-base entry should always trigger a run of
this skill** (step 1 of "Adding a new knowledge-base entry" in
`EVAL_TAXONOMY.md`) before anyone writes new questions for it — a new
entry can regress existing lookups via token-overlap disambiguation
(see `_resolve_place` in `tools.py`), and the full suite is the cheapest
way to catch that before it ships.

## How grading actually works here

`backend/eval/run_eval.py` reads each question's `"grading"` field and
branches three ways:

- **`"auto"`** (Amap API, Adversarial, part of Recommendation) →
  `grade_auto()` in `backend/eval/grade_auto.py`. No LLM call. Checks the
  reply text against the question's `auto_grade` spec
  (`keywords_all`/`keywords_any`/`keywords_forbidden` regexes, plus
  `requires_tool_call` for Amap questions, which inspects the actual
  tool-use blocks in the conversation, not just the final text). Also
  hard-fails any reply matching `agent.py`'s own loop/error fallback
  strings, regardless of what else the spec checks — a stuck-reasoning
  or blank reply is never a pass.
- **`"checklist"`** (Factual lookup, Knowledge base boundary) →
  `grade_checklist()` in `backend/eval/grade_checklist.py`. One LLM call,
  but checks a short list of concrete `must_state`/`must_not_state` points
  (hand-derived from the actual knowledge-base entry) one at a time — the
  0/2 score is computed in code from those per-point verdicts, not asked
  of the model directly. Used where plain regex proved too fragile against
  phrasing variance but the underlying facts are still concrete.
- **`"judge"`** (Synthesis, Chit-chat, Multi-turn, part of Recommendation)
  → `judge()`, a freeform LLM call scoring the reply against the
  question's prose `expects` field.

All three paths return the same shape (`{grounded, on_task, note}`) so
results report uniformly regardless of which grader ran.

## Running it

```
cd backend && python -m eval.run_eval
```

This costs real DashScope (Qwen) API calls — the agent itself runs on
`qwen-plus`, and both `judge()` and `grade_checklist()` are additional LLM
calls, not free — ×2 for en/zh per question. 47 questions × 2 languages is
94 agent runs, plus ~38 judge calls and ~26 checklist-grading calls
(auto-graded questions, 15 of the 47, skip both). Confirm with the user
before running the full suite if they haven't explicitly asked for it this
turn; running a filtered subset (see below) is cheaper and often enough to
verify a specific fix.

To run a subset (e.g. just-added questions, or just one capability),
don't edit `run_eval.py` — write a small throwaway script that loads
`test_questions.json`, filters by `id`/`capability`, and calls
`run_agent` + the appropriate grader directly (see `run_eval.py`'s
`main()` for the exact pattern to copy). Keep it in the scratchpad, not
the repo.

## Verifying a new or changed `auto_grade` spec before trusting it

A regex that looks right can still miss real phrasing. Before relying
on a new pattern:

1. Run the actual question through `run_agent` once in Chinese and once
   in English — the agent replies in whichever language the visitor's own
   message is written in, and every question is tested in both, so a
   pattern only grounded in the Chinese phrasing will silently miss the
   English half.
2. Feed each real reply through `grade_auto()` directly and check the
   verdict matches what a human would say.
3. If it doesn't, broaden the pattern (add alternation for equivalent
   phrasings, in whichever language it was missing) rather than narrowing
   the test case to fit the regex.

This project has already hit two real bugs this way: a refusal-detection
regex too tight to match the agent's actual "没有找到...没有查到..." phrasing,
and an Amap auto-grade that wrongly passed a reply that was actually the
agent's stuck-in-a-loop fallback message (fixed by the fallback-string
guard in `grade_auto.py`). Expect more of this kind of thing — the
auto-grader is only as good as the patterns it's given.

## Reporting results

After a run, report grouped by capability (not just overall average) —
a flat "1.8/2 average" hides a capability that's failing 100% while
others are perfect. Break out auto vs. judge results separately too,
since a low auto-grade score points at a specific, reproducible
mechanism (a tool never got called, a fact was wrong, a leak happened),
while a low judge score is fuzzier and worth a second look at the
`expects` wording before assuming the agent is actually wrong.

Save results the same way `run_eval.py` already does (timestamped JSON
under `backend/eval/results/`) so score trends over time stay
comparable — don't invent a different output format.

## Out of scope for this skill

Deciding *what* to test is the question-generator skill's job, not
this one's. If a gap in coverage surfaces while grading (a capability
with no passing cases, a phrasing variant that's clearly under-tested),
name it in the report rather than silently writing new questions here.
