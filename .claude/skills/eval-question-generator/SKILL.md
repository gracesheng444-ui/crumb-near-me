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

1. `backend/eval/EVAL_TAXONOMY.md` — the "Weighting" table is the
   *relative* target for every (capability × phrasing) cell, and
   "Grading — auto vs. checklist vs. judge" says which of the three
   output shapes a new question needs.
2. `backend/eval/test_questions.json` — the current implemented set.
   Count existing entries per `(capability, phrasing)` pair, and tally
   `entities` usage frequency across the *whole* file (not just the
   target cell — see "Avoiding repeats" below). Never trust the
   taxonomy doc's prose examples as a proxy for what's implemented —
   count the JSON directly.
3. `backend/knowledge/*.json` — the only source of ground truth. Every
   fact a question's `expects` or `auto_grade` field references (branch
   counts, hours, prices, addresses, flavors) must come from here, never
   invented. Read the specific entries you're grounding a question in
   before writing it.

## Scaling to a target count

The weight table's numbers (currently summing to 47 — recompute this from
the table directly, don't trust this number as it drifts every time a cell
changes) are a *ratio*, not a hard cap. When the user asks for a bigger
set — "generate 94 questions", "I want another set of 47", "double the
eval set" — scale every cell's weight by `requested_total / current_total`
and round to the nearest integer (e.g. requesting double doubles every
cell exactly: Factual lookup 2/1/2/2 → 4/2/4/4). If rounding doesn't land
exactly on the requested total, adjust the highest-weighted cells first
(Adversarial, Knowledge base boundary) rather than the flattest ones
(Chit-chat) — that keeps the "spend effort where it's costliest to get
wrong" intent from the original rubric intact at any scale.

A request phrased as "N sets of 47" (rather than "a set of 4×N") most
often means "I'm worried about running out of distinct questions, not
that I literally want N separate files" — confirm which one before
generating if it's unclear, since the two imply different structure
(one combined pool that scales targets vs. genuinely separate labeled
sets, e.g. for a dev/held-out split).

## Avoiding repeats when generating more

Every question carries an `entities` field: the `backend/knowledge/*.json`
id(s) it's grounded in (e.g. `["azabuya_taikoohui"]`), or `[]` for
questions that aren't grounded in any specific entry (Knowledge base
boundary questions probe an *absence*; Chit-chat and blunt Adversarial
questions aren't grounded in the KB at all). For Synthesis questions,
`entities` lists the current qualifying set for that question's claim
(e.g. every brand that has a matcha item) — this is *also* exactly the
set to re-check whenever the knowledge base changes, tying back to
"Adding a new knowledge-base entry" in `EVAL_TAXONOMY.md`.

Before writing new questions for a cell:

1. Tally how many existing questions (across the *entire* file, not
   just this cell) reference each entity id.
2. Prefer the least-used entities for the new questions — don't write a
   fourth question about `azabuya_taikoohui` when `pie_bird_pac` or
   `drunk_baker` have barely been used at all.
3. Only reuse a heavily-used entity if the knowledge base genuinely
   doesn't have enough distinct entries to cover the requested count
   for that capability (e.g. Knowledge base boundary questions have no
   real entities to spread across, so vary the *fictitious name and
   category* instead — a French bakery, a bubble tea chain, a dessert
   festival — rather than the same "made-up shop" phrasing twice).
4. Set `entities` on every new question so the next generation run (by
   you or anyone else) can do this same check without re-reading every
   question's prose by hand.

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
(`"auto"`, `"checklist"`, or `"judge"`, per the taxonomy's grading table),
`entities` (see "Avoiding repeats" above), `question_en`/`question_zh` (or
`turns_en`/`turns_zh` for multiturn), and:

- **`grading: "judge"`** → an `expects` string: a prose ground-truth
  description an LLM judge scores the reply against. State the correct
  answer AND what a wrong answer would look like (dropping part of a
  multi-intent ask, inventing a fact, picking the wrong branch).
- **`grading: "checklist"`** → a `ground_truth` object with `must_state`
  and `must_not_state` lists, each point hand-derived from the actual
  knowledge-base entry (not paraphrased from the question you just wrote —
  go back to the source JSON). See `grade_checklist.py`'s docstring for
  the exact spec. Use this over `judge` when the correct answer is a
  handful of concrete, checkable facts rather than an open-ended "did it
  reason about this well"; use it over `auto` when a plain regex would be
  too fragile against real phrasing variance (this is what Factual lookup
  and Knowledge base boundary questions use today).
- **`grading: "auto"`** → an `auto_grade` object instead of (or with a
  documentation-only) `expects`. See `grade_auto.py`'s docstring for the
  field spec (`keywords_all`/`keywords_any`/`keywords_forbidden`/
  `requires_tool_call`). Keep regexes loose enough to survive real
  phrasing variance — a pattern that only matches the one exact string
  you imagined is fragile. Test any new pattern against a real reply
  before trusting it (see the grading-agent skill's verification step).

## Process

1. Read the three inputs above.
2. If the user requested a bigger total, scale the weight table per
   "Scaling to a target count" above; otherwise use the table as-is.
3. Compute the gap: for each `(capability, phrasing)` cell, `target
   weight - current count`. Only write for cells with a positive gap
   unless the user asked for something else specifically.
4. Tally `entities` usage (see "Avoiding repeats") and draft each new
   question against under-used entities, grounding every fact in the
   actual knowledge JSON you read.
5. Append to `test_questions.json` (don't rewrite unrelated entries).
   Validate it's still valid JSON with unique `id`s afterward.
6. Update `EVAL_TAXONOMY.md`'s "How many questions is that" section if
   the total implemented count changed.
7. Report back: how many added, to which cells, which entities they
   used (so the next run — anyone's — doesn't need to recompute the
   whole tally from scratch), and what's still open.

Do not run the eval suite as part of generation — that's the grading
agent's job, and it costs real API calls. Generating questions should
be free of side effects beyond the two files above.
