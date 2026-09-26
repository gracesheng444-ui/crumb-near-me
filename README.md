# Crumb Near Me

**Live demo:** https://crumbnearme.com (also reachable at
https://grand-gateway-agent-production.up.railway.app).

A conversational guide to dessert spots across Shanghai — chocolate, cakes,
gelato, Chinese sweet soups, bubble tea, and more. Given a photo or a typed
question, it identifies a shop, narrates a grounded introduction aloud,
gives real metro/bus directions, and answers visitor follow-up questions —
refusing to guess when it doesn't actually know. Visitors can also keep a
personal dessert log (with mandatory photos for anything marked "eaten",
multi-photo entries, and a wishlist) and leave community notes on a place.
The UI itself is bilingual (中文/English, toggled from the login screen or
Settings), and the chat agent replies in whichever language the visitor's
own message is written in.

Accounts are handled by Supabase Auth, with an unauthenticated guest mode (a
`localStorage`-generated id) also supported so visitors can use it without
signing up.

Built independently, informed by evaluation work during an internship
building/testing a similar TTS exhibit-guide system (no internal content,
scripts, or data from that internship were reused — this knowledge base and
codebase are original).

## Why this exists

Most "AI agent" demos are a single prompt-and-response call with no way to
check whether the answer is real. This one is built around a single rule:
never state a fact the agent hasn't actually retrieved. The model
(`qwen-plus`, via DashScope) decides when to call `retrieve_info` before
answering, refuses when the knowledge base doesn't have what's being asked,
and calls `speak` only once a reply is grounded. Groundedness is verified
with a "canary" technique — a deliberately fabricated fact planted in the
knowledge base (see `backend/knowledge/example_canary.json`) that the agent
can only get right by actually retrieving it, not by pattern-matching a
plausible-sounding answer.

That rule turned out to need more than a single system-prompt instruction
to hold up — especially under open-ended questions like "what should I
try?", where there's no one retrieved fact to check the reply against.
`backend/eval/first_refinement.md` documents the specific ways it broke
(inventing a shop outright, or stretching a real one with fabricated
supporting detail) and the post-hoc verification checks added to catch
those before a reply reaches the user.

Directions follow the same rule, just for wayfinding instead of facts:
`get_transit_directions` calls Amap's real transit-routing API for
metro/bus directions between two places, rather than letting the model
guess a line or a bus number — and says so plainly if Amap can't resolve a
place or find a route, instead of inventing turns.

## Architecture

```
backend/frontend/index.html  one-page app UI (chat + dessert log/notebook), plain JS, bilingual (中文/English)
backend/main.py          FastAPI app: /chat, /identify, /log, /notes, /profile, /config, /health
backend/agent.py         the Qwen (qwen-plus) tool-use loop (the "agent")
backend/tools.py         retrieve_info, identify_exhibit, speak, get_transit_directions (Amap-backed)
backend/auth.py          verifies Supabase Auth bearer tokens
backend/collection.py    personal dessert log (Supabase Postgres + Storage)
backend/community.py     visitor-submitted place notes (Supabase Postgres)
backend/profile.py       display name/avatar (Supabase Postgres + Storage)
backend/supabase_db.py   thin PostgREST client (insert/select/update/delete)
backend/supabase_storage.py  Supabase Storage client for uploaded photos
backend/knowledge/*.json the grounding source of truth for retrieve_info
backend/eval/            test questions + auto/LLM-judge scoring harness (see EVAL_TAXONOMY.md)
```

## Setup

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env   # then fill in your real API keys
```

`AMAP_API_KEY` is optional — `get_transit_directions` degrades gracefully
(tells the visitor it doesn't have a route right now) if it's left blank.
It requires a real-name-verified Amap Open Platform developer account
(`lbs.amap.com`), a Chinese regulatory requirement for API access, not
something specific to this project.

The three `SUPABASE_*` keys are required — the app uses Supabase for auth,
Postgres (dessert logs, community notes, profiles), and Storage (uploaded
photos). Create a project at supabase.com, grab `SUPABASE_URL` and the
publishable/secret keys from Settings > API, and create the
`dessert_logs`, `community_notes`, and `profiles` tables plus a
`dessert-photos` storage bucket (see the `insert_row`/`select_rows` calls
in `collection.py`/`community.py`/`profile.py` for the exact columns each
table needs). Guest visitors (no account) still work without Supabase Auth — they get a
`localStorage`-generated id instead — but the log/notes/profile features
still need a real Supabase project behind them to actually persist
anything.

Run it:

```bash
cd backend
uvicorn main:app --reload
```

Open http://localhost:8000

## Running the eval suite

```bash
cd backend
python -m eval.run_eval
```

Scores are saved to `backend/eval/results/` with a timestamp — the point is
to watch the average `grounded`/`on_task` score go up as you tighten the
system prompt and retrieval logic, not just to run it once.

## Eval design

The eval suite is designed in three parts — **text**, **vision**, and
**audio** — each targeting a different surface of the agent (chat replies,
photo identification, and voice input). Full reasoning is written up at
[gracesheng444-ui.github.io/crumb-near-me](https://gracesheng444-ui.github.io/crumb-near-me/);
the question bank itself is drafted in
[`backend/eval/design/`](backend/eval/design/).

- **Text** — 50 single-turn questions crossing 7 capabilities (factual
  lookup, synthesis, Amap routing, chit-chat, knowledge-base-boundary
  refusals, adversarial probing, recommendation) against 4 phrasing styles
  (short/long/multi-intent/ambiguous), weighted toward the capabilities
  repeat sampling found fragile — plus a 34-question multi-turn track
  (needs-history-to-parse, distance-erosion, personalization-recall).
- **Vision** — still on the way: a redesigned 12-case bank against real
  photos, concentrated on documented failure modes (brand mismatches,
  degraded-quality photos, out-of-domain images, visual prompt injection).
- **Audio** — still on the way: tests the voice-input transcription layer
  (Qwen3-ASR-Flash) and, separately, whether the chat agent stays grounded
  when handed a plausible mistranscription.

### What's actually running today

`backend/eval/test_questions.json` is an earlier, 47-question version —
crossing 8 capabilities (the 7 above, plus multi-turn bundled in as its own
capability) against the same 4 phrasing styles — graded either by
rule-based auto-checks or an LLM judge depending on whether the capability
has a checkable ground truth. There's also a separate 6-case vision eval
(`backend/eval/vision_questions.json`) against real photos, covering
`identify_exhibit`'s brand/food/not-in-KB matching. Neither has been
replaced by the redesign above yet.

The full taxonomy for what's running today — what each capability/phrasing
cell tests, how the weighting was chosen, and which cells are auto- vs.
judge-graded — is in
[`backend/eval/EVAL_TAXONOMY.md`](backend/eval/EVAL_TAXONOMY.md). Findings
from running it against Qwen, and the fixes each one led to, are in
[`backend/eval/first_refinement.md`](backend/eval/first_refinement.md) —
including several still-open gaps (a no-signal recommendation question
occasionally inventing a fake shop, non-deterministic dropped tool calls,
and the judge itself occasionally hallucinating in its own grading
rationale).

## Status

- [x] Project scaffold, bilingual agent loop (now on Qwen, `qwen-plus`), keyword-based retrieval, TTS/vision tools wired
- [x] Real knowledge base content — 5 brands (14 branch entries) hand-verified so far, growing as more are added
- [x] Live transit directions via Amap — verified working end-to-end (metro/bus routing)
- [x] TTS and vision endpoints verified live (TTS needs ElevenLabs billing set up to actually speak; degrades gracefully to text-only if it fails)
- [x] Any tool failure degrades gracefully instead of crashing the whole turn
- [x] Migrated auth to Supabase (accounts + guest mode); personal dessert log, wishlist, and community notes shipped
- [x] Deployed to Railway (crumbnearme.com)
- [x] Eval expanded to 47 weighted text questions + a 6-case vision eval, with documented findings (`backend/eval/first_refinement.md`)
- [ ] Next eval iteration drafted (50 single-turn + 34 multi-turn questions, reweighted toward documented failure modes) — design finished, not yet wired into the running suite

## Eval iteration history

Raw runs are in `backend/eval/results/`. The average `grounded`/`on_task`
score (out of 2) across the test set, after the knowledge base grew to 5
brands (Azabuya, Drunk Baker, Pie Bird, EAU Café, bebaked) — run numbering
continues from earlier prototype iterations:

| Run | grounded | on_task | What changed |
|---|---|---|---|
| 5 | 1.00 | 1.00 | Baseline — same 3 test questions, updated knowledge base |
| 6 | 1.83 | 2.00 | Fixed 3 bugs found by this run: a stale, scope-mismatched reference left in `retrieve_info`'s tool description, `max_tokens` too small once extended thinking is in play (blank replies), and the canary's own `"canary": true`/`"example"` metadata leaking into the model's tool result (see bugs below) |

The score isn't the interesting part on its own — it's that each change maps
to a specific, diagnosed cause, not prompt-tweaking by vibes.

Run 6's remaining gap from a perfect score is the judge docking
`canary_01`'s Chinese answer for citing the canary entry's `address` field
— which is real KB content, not an invented detail — because the test's
`expects` text didn't mention address. A rubric-wording quirk, not an
agent bug. (This test's `id` was later renamed to `factual_short_01` to
match its category's naming convention — same question, same `"type":
"canary"`, just a different label.)

## Real bugs found during development (and how)

- **Chinese retrieval silently returned nothing.** Naive `\w+` tokenization
  swallowed an entire Chinese sentence as one token (no spaces to split on),
  so it never matched anything. Found by testing a real Chinese query
  end-to-end, not by code review. Fixed with character-bigram tokenization
  for CJK text.
- **The agent invented a walking route between two towers with zero
  evidence they connect** (from the original mall-wayfinding feature,
  since retired in favor of live Amap transit routing) — early seed data
  grouped all venues on a floor under one shared node, and pathfinding
  treated that as "walkable." Found by deliberately testing a cross-tower
  directions query. Fixed by making zone (floor+tower) the smallest unit
  assumed walkable.
- **A relation-vocabulary gap silently distorted taught facts** (same
  retired feature) — teaching the agent about a "walkway" got stored as
  "connected via escalator" because that was the closest option in a
  too-narrow enum. Fixed by widening the vocabulary.
- **Any single tool failure crashed the entire chat turn** (found via a
  real ElevenLabs billing error) — fixed so the agent degrades to a text
  answer and says what didn't work, instead of a raw 500 error.
- **Deploy-only bugs**: a path mismatch meant the frontend wasn't included
  in what actually got uploaded to Railway (worked locally, 404'd in
  prod), and the public domain was pointed at the wrong port. Both only
  surfaced by testing the live deployed URL, not the local dev server.
- **The agent hallucinated out-of-scope venue references on plain dessert
  questions.** `retrieve_info`'s tool description still described an
  earlier, narrower scope — leftover text a prior system-prompt rewrite had
  missed. The model took that description at face value and worked the
  stale reference into answers about shops that had nothing to do with it.
  Found by the `unknown_fact_01` eval case; fixed by rewriting the tool
  description.
- **The agent sometimes returned a completely blank reply.** `max_tokens`
  was set to 1024, but extended-thinking tokens count against that same
  budget — on a harder judgment call the model spent the entire 1024
  tokens thinking and hit `stop_reason=max_tokens` before writing any
  reply text, so the user got nothing back. Reproduced 3 times out of 6
  runs of the same question. Found by re-running the eval and noticing an
  empty `reply` field, confirmed by inspecting the raw API response's
  `stop_reason` and `usage.output_tokens_details`. Fixed by raising
  `max_tokens` to 4096, plus a fallback message so a blank reply can never
  reach a real user even if it happens again on some other edge case.
- **The canary test flip-flopped between pass and fail for no code
  reason.** `retrieve_info` returned each knowledge-base entry's raw JSON
  to the model verbatim, including the `"canary": true` field and the
  `"canary"`/`"example"` tags — internal bookkeeping meant only for a
  human deciding what to strip before a public demo. About half the time,
  the model read its own tool result, noticed the entry was tagged as
  test data, and correctly (but unhelpfully, for testing purposes) refused
  to state it as fact. Fixed by stripping that metadata out of what
  `retrieve_info` returns to the model.

## Known limitations (intentional scope cuts)

- Retrieval is keyword-overlap, not embeddings — fine at this knowledge-base
  size, would need upgrading if this grew past ~50 entries.
- No live data (opening hours, promotions) — static knowledge base only.
- Web search is wired in (`enable_search=True`) for questions about real
  places outside the curated knowledge base, but with no ad/sponsorship
  detection on what it surfaces — replies attribute web-sourced info as
  such (see `agent.py` rules 2-3) rather than presenting it with the same
  confidence as a curated KB fact, but a heuristic ad-classifier on top of
  that was scoped out deliberately; it can't honestly claim validated
  accuracy without real labeled data.
- Directions only work for places that are either in the knowledge base or
  resolvable by Amap's place search — it will correctly say "couldn't
  locate" or "no route found" rather than guess.
