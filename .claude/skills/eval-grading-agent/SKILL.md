---
name: eval-grading-agent
description: Runs backend/eval/run_eval.py against the Shanghai dessert guide agent and reports results, using rule-based auto-grading (grade_auto.py) for Factual lookup/Amap/Knowledge base boundary/Adversarial and LLM-judge grading for Synthesis/Chit-chat/Multi-turn.
---

# Eval grading agent

Runs the eval suite and reports what passed, what failed, and why. Use
this when the user asks to "run the eval", "check the eval results", or
after knowledge-base or prompt changes that should be re-verified.

## How grading actually works here

`backend/eval/run_eval.py` reads each question's `"grading"` field and
branches:

- **`"auto"`** (Factual lookup, Amap API, Knowledge base boundary,
  Adversarial) → `grade_auto()` in `backend/eval/grade_auto.py`. No LLM
  call. Checks the reply text against the question's `auto_grade` spec
  (`keywords_all`/`keywords_any`/`keywords_forbidden` regexes, plus
  `requires_tool_call` for Amap questions, which inspects the actual
  tool-use blocks in the conversation, not just the final text). Also
  hard-fails any reply matching `agent.py`'s own loop/error fallback
  strings, regardless of what else the spec checks — a stuck-reasoning
  or blank reply is never a pass.
- **`"judge"`** (Synthesis, Chit-chat, Multi-turn) → `judge()`, an LLM
  call scoring the reply against the question's prose `expects` field.

Both paths return the same shape (`{grounded, on_task, note}`) so
results report uniformly regardless of which grader ran.

## Running it

```
cd backend && python -m eval.run_eval
```

This costs real Anthropic API calls (agent + judge, ×2 for en/zh per
question) — 42 questions × 2 languages is 84 agent runs plus ~32 judge
calls (auto-graded ones skip the judge call entirely). Confirm with the
user before running the full suite if they haven't explicitly asked for
it this turn; running a filtered subset (see below) is cheaper and
often enough to verify a specific fix.

To run a subset (e.g. just-added questions, or just one capability),
don't edit `run_eval.py` — write a small throwaway script that loads
`test_questions.json`, filters by `id`/`capability`, and calls
`run_agent` + the appropriate grader directly (see `run_eval.py`'s
`main()` for the exact pattern to copy). Keep it in the scratchpad, not
the repo.

## Verifying a new or changed `auto_grade` spec before trusting it

A regex that looks right can still miss real phrasing. Before relying
on a new pattern:

1. Run the actual question through `run_agent` once, in Chinese (the
   agent always replies in Chinese regardless of input language, so
   ground every pattern in Chinese phrasing, not the English gloss).
2. Feed that real reply through `grade_auto()` directly and check the
   verdict matches what a human would say.
3. If it doesn't, broaden the pattern (add alternation for equivalent
   phrasings) rather than narrowing the test case to fit the regex.

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
