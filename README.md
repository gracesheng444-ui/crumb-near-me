# Shanghai Dessert Guide Agent

**Live demo:** https://grand-gateway-agent-production.up.railway.app
(text chat works out of the box; voice narration needs the demo's ElevenLabs
billing to be active — falls back to text-only if not, rather than erroring.
**Note:** this project was just repurposed from a single-mall guide to a
city-wide dessert guide — the live demo above still reflects the old
single-mall version until redeployed.)

A bilingual (Chinese/English) conversational guide to dessert spots across
Shanghai — chocolate, cakes, gelato, Chinese sweet soups, bubble tea, and
more. Given a photo or a typed question, it identifies a shop, narrates a
grounded introduction aloud, gives real metro/bus directions, and answers
visitor follow-up questions — refusing to guess when it doesn't actually
know.

This project started scoped to a single mall (Grand Gateway 66, 港汇恒隆广场)
and was later broadened into a general Shanghai dessert guide once the core
pattern (grounded retrieval, real routing, graceful degradation) proved out.
The original mall-tenant entries are preserved in
`backend/knowledge/_archive_grand_gateway_66/` for reference — they're
outside `retrieve_info`'s glob, so they're not loaded.

Built independently, informed by evaluation work during an internship
building/testing a similar TTS exhibit-guide system (no internal content,
scripts, or data from that internship were reused — this knowledge base and
codebase are original).

## Why this exists

Most "AI agent" demos are a single prompt-and-respond call. This one is
actually agentic: Claude decides when to call `retrieve_info` before
stating a fact, refuses to answer ungrounded questions, and calls `speak`
only once a reply is grounded. Groundedness is verified with a "canary"
technique — a deliberately fabricated fact planted in the knowledge base
(see `backend/knowledge/example_canary.json`) that the agent can only get
right by actually retrieving it.

Directions work on the same grounding principle: `get_transit_directions`
calls Amap's real transit-routing API for metro/bus directions between two
places, rather than letting the model guess a line or a bus number. If Amap
can't resolve a place or find a route, the agent says so plainly instead of
inventing turns — same philosophy as `retrieve_info`, just for wayfinding
instead of facts.

## Architecture

```
backend/frontend/index.html  one-page chat UI, plain JS (lives inside backend/ so it deploys together with it)
backend/main.py          FastAPI app: /chat, /identify, /health
backend/agent.py         the Claude tool-use loop (the "agent")
backend/tools.py         retrieve_info, identify_exhibit, speak, get_transit_directions (Amap-backed)
backend/knowledge/*.json the grounding source of truth for retrieve_info
backend/eval/            test questions + LLM-judge scoring harness
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

## Status

- [x] Project scaffold, bilingual agent loop, keyword-based retrieval, TTS/vision tools wired
- [x] Repurposed from a single-mall guide to a city-wide Shanghai dessert guide
- [x] Real knowledge base content — 6 dessert entries carried over so far, growing as more are added
- [ ] Live transit directions via Amap — code wired (`get_transit_directions`), pending a real-name-verified Amap API key
- [x] TTS and vision endpoints verified live (TTS needs ElevenLabs billing set up to actually speak; degrades gracefully to text-only if it fails)
- [x] Any tool failure degrades gracefully instead of crashing the whole turn
- [ ] Redeploy demo (Railway) to reflect the new dessert-guide scope
- [x] Eval iteration history documented below (from the original single-mall version)

## Eval iteration history

Runs 1-4 below are from the original single-mall version, before the pivot
to a city-wide dessert guide — kept as the historical record of how the
score moved with each diagnosed fix. New runs against the dessert-scoped
eval questions (`backend/eval/test_questions.json`) will start a fresh
baseline.

Raw runs are in `backend/eval/results/`. The average `grounded`/`on_task`
score (out of 2) across the test set, run to run:

| Run | grounded | on_task | What changed |
|---|---|---|---|
| 1 | 1.33 | 1.50 | Baseline after first working end-to-end version |
| 2 | 1.67 | 1.67 | Fixed the system prompt to require confident, consistent grounding regardless of reply language (it was hedging on retrieved facts in Chinese but not English); fixed the eval judge, which was penalizing correct answers it couldn't independently verify as plausible |
| 3 | 1.50 | 1.67 | Real content replaced placeholder/canary-only data — score dipped because Chinese-language retrieval was silently broken (see bug list below), which the smaller placeholder set hadn't exposed |
| 4 | 1.67 | 1.67 | Fixed the Chinese tokenizer bug; fixed a crash in the judge caused by extended-thinking response blocks; corrected an eval question's expected-answer field that was too narrow, causing the judge to dock credit for additional true details |

The score isn't the interesting part on its own — it's that each change maps
to a specific, diagnosed cause, not prompt-tweaking by vibes.

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

## Known limitations (intentional scope cuts)

- Retrieval is keyword-overlap, not embeddings — fine at this knowledge-base
  size, would need upgrading if this grew past ~50 entries.
- No live data (opening hours, promotions) — static knowledge base only.
- No web-sourced food recommendations with ad/sponsorship detection. All
  recommendations come from the hand-curated, trusted knowledge base
  (`retrieve_info` already handles "recommend me X" queries against it fine).
  Reaching beyond it to the open web and flagging likely-sponsored content
  was scoped out deliberately — it needs a separate web-search API
  dependency, and a heuristic ad-classifier can't honestly claim validated
  accuracy without real labeled data (see eval notes on that distinction).
- Directions only work for places that are either in the knowledge base or
  resolvable by Amap's place search — it will correctly say "couldn't
  locate" or "no route found" rather than guess.
