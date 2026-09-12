---
name: eval-question-generator
description: Generates new eval questions for backend/eval/test_questions.json against the weighted capability x phrasing taxonomy in backend/eval/EVAL_TAXONOMY.md, grounded in the real knowledge base.
---

# Eval question generator

Writes new test cases for the Shanghai dessert guide agent's eval suite.
Use this when a taxonomy cell is under its target weight, when a new
knowledge-base entry needs coverage, or when the user asks to "add more
eval questions" / "fill out the eval set" / "generate questions for X".

**A new knowledge-base entry is not a reason to run this whole skill.**
This skill fills the abstract capability × phrasing grid, which has
nothing to do with any one store. See "Adding a new knowledge-base
entry" in `EVAL_TAXONOMY.md` for what a new store actually needs —
this skill only covers its step 3 (a couple of targeted new questions
for that store) and step 4 (a new Synthesis question, only if the
addition creates a genuinely new cross-entry pattern). Steps 1
(regression) and 2 (re-validating existing Synthesis `expects`) are not
this skill's job.

## Inputs to read first, every time

1. `backend/eval/EVAL_TAXONOMY.md` — the "Weighting" table is the target
   count for every (capability × phrasing) cell, and "Grading — auto vs.
   judge" says which of the two output shapes a new question needs.
2. `backend/eval/test_questions.json` — the current implemented set.
   Count existing entries per `(capability, phrasing)` pair and diff
   against the weight table to find what's actually missing. Never
   trust the taxonomy doc's prose examples as a proxy for what's
   implemented — count the JSON directly.
3. `backend/knowledge/*.json` — the only source of ground truth. Every
   fact a question's `expects` or `auto_grade` field references (branch
   counts, hours, prices, addresses, flavors) must come from here, never
   invented. Read the specific entries you're grounding a question in
   before writing it.

## What makes a good new question

- **Grounded**: every claim you bake into `expects`/`auto_grade` traces
  to a specific knowledge-base field you actually read this session.
- **Distinct from existing cases**: don't just reword an existing
  question in the same cell — pick a different brand/branch/fact so a
  failure would reveal something a passing existing case didn't already
  cover.
- **Phrasing matches its Axis B definition**: Short = one clean clause;
  Long = one intent wrapped in real-world context/constraints;
  Multi-intent = two or more distinct asks bundled in one message;
  Ambiguous = hedging/filler/indirect description instead of a name.
  Don't let a "Long" question secretly become multi-intent, or vice
  versa — that's a real design bug this project already hit once.
- **Multi-turn questions** use `turns_en`/`turns_zh` (lists, not a
  single string) instead of `question_en`/`question_zh` — see any
  existing `multiturn_*` entry for the shape. Turn 2 can itself be any
  Axis B phrasing (Multi-turn crosses with phrasing like every other
  row — it only gets its own Axis A row because it needs accumulated
  `history` across API calls, not because it's phrasing-exempt).

## Output shape

Every new entry needs: `id` (unique, `<capability>_<phrasing>_NN`),
`type` (short capability slug), `capability`, `phrasing`, `grading`
(`"auto"` or `"judge"`, per the taxonomy's grading table),
`question_en`/`question_zh` (or `turns_en`/`turns_zh` for multiturn),
and:

- **`grading: "judge"`** → an `expects` string: a prose ground-truth
  description an LLM judge scores the reply against. State the correct
  answer AND what a wrong answer would look like (dropping part of a
  multi-intent ask, inventing a fact, picking the wrong branch).
- **`grading: "auto"`** → an `auto_grade` object instead of (or with a
  documentation-only) `expects`. See `grade_auto.py`'s docstring for the
  field spec (`keywords_all`/`keywords_any`/`keywords_forbidden`/
  `requires_tool_call`). Keep regexes loose enough to survive real
  phrasing variance — a pattern that only matches the one exact string
  you imagined is fragile. Test any new pattern against a real reply
  before trusting it (see the grading-agent skill's verification step).

## Process

1. Read the three inputs above.
2. Compute the gap: for each `(capability, phrasing)` cell, `target
   weight - current count`. Only write for cells with a positive gap
   unless the user asked for something else specifically.
3. Draft each new question, grounding facts in the actual knowledge JSON
   you read.
4. Append to `test_questions.json` (don't rewrite unrelated entries).
   Validate it's still valid JSON with unique `id`s afterward.
5. Update `EVAL_TAXONOMY.md`'s "How many questions is that" section if
   the total implemented count changed.
6. Report back: how many added, to which cells, and what's still open.

Do not run the eval suite as part of generation — that's the grading
agent's job, and it costs real API calls. Generating questions should
be free of side effects beyond the two files above.
