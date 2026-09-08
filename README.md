# Grand Gateway 66 Agent

**Live demo:** https://grand-gateway-agent-production.up.railway.app
(text chat works out of the box; voice narration needs the demo's ElevenLabs
billing to be active — falls back to text-only if not, rather than erroring)

A bilingual (Chinese/English) conversational guide for Grand Gateway 66
(港汇恒隆广场), Shanghai. Given a photo or a typed question, it identifies a
store/facility, narrates a grounded introduction aloud, and answers visitor
follow-up questions — refusing to guess when it doesn't actually know.

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

The agent also builds its own spatial understanding of the mall
incrementally, rather than relying on a hand-fed map: `learn_location`
extracts spatial facts from free-text descriptions and merges them into a
graph, and `get_directions` does real pathfinding over whatever's been
learned so far — returning "I don't have a confirmed route yet" rather than
inventing one when two places aren't actually connected in the graph. This
caught a real bug during development: an early version of the seed data
grouped every venue under a shared "floor" node for organizational
convenience, which let pathfinding treat "same floor number" as "walkable
connection" and confidently invent a route between two towers that were
never actually confirmed to connect. Fixed by making zones (floor+tower)
the smallest unit assumed walkable, with cross-zone connections only added
once actually confirmed.

## Architecture

```
backend/frontend/index.html  one-page chat UI, plain JS (lives inside backend/ so it deploys together with it)
backend/main.py          FastAPI app: /chat, /identify, /health
backend/agent.py         the Claude tool-use loop (the "agent")
backend/tools.py         retrieve_info, identify_exhibit, speak, get_directions, learn_location
backend/spatial_graph.py graph store + pathfinding for the wayfinding feature
backend/seed_graph.py    seeds the spatial graph from knowledge/*.json (run once, or after adding entries)
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
- [x] Real knowledge base content — 20 F&B entries at Grand Gateway 66
- [x] Spatial wayfinding: `learn_location` + `get_directions`, tested including a caught-and-fixed false-connectivity bug
- [x] TTS and vision endpoints verified live (TTS needs ElevenLabs billing set up to actually speak; degrades gracefully to text-only if it fails)
- [x] Any tool failure degrades gracefully instead of crashing the whole turn
- [x] Deployed demo link (Railway) — see top of this file
- [ ] Fuller eval iteration history documented below

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
- Spatial graph only knows what's been seeded from the knowledge base or
  explicitly taught via `learn_location` — it will correctly say "I don't
  have a confirmed route" for anything not yet connected, rather than
  guess.
