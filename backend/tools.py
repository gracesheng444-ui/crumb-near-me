"""
Tool implementations the agent can call: retrieve_info, identify_exhibit, speak.

retrieve_info uses plain keyword overlap for now (v0) — swap in embedding
similarity once the knowledge base is big enough that keyword matching starts
missing things. For ~15-20 entries, keyword overlap is honestly fine and
avoids a third API dependency on day one.
"""
import base64
import json
import os
import re
from pathlib import Path

import requests
from anthropic import Anthropic
from dotenv import load_dotenv

import spatial_graph as sg

load_dotenv(Path(__file__).parent.parent / ".env")

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"
AUDIO_DIR = Path(__file__).parent.parent / "audio_output"
AUDIO_DIR.mkdir(exist_ok=True)

_client = None


def get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic()  # reads ANTHROPIC_API_KEY from env
    return _client


def load_knowledge_base(include_canary: bool = True) -> list[dict]:
    entries = []
    for path in KNOWLEDGE_DIR.glob("*.json"):
        with open(path, encoding="utf-8") as f:
            entry = json.load(f)
        if entry.get("canary") and not include_canary:
            continue
        entries.append(entry)
    return entries


_WORD_RE = re.compile(r"[a-z0-9]+")
_CJK_RE = re.compile(r"[一-鿿]+")


def _tokenize(text: str) -> set[str]:
    """Latin/digit text tokenizes as whole words. Chinese has no spaces, so a
    naive \\w+ regex would swallow an entire sentence as one giant token that
    never matches anything — instead we use character bigrams for CJK runs,
    the standard lightweight substitute for a real segmenter (e.g. jieba)."""
    tokens = set(_WORD_RE.findall(text.lower()))
    for run in _CJK_RE.findall(text):
        if len(run) == 1:
            tokens.add(run)
        else:
            tokens.update(run[i : i + 2] for i in range(len(run) - 1))
    return tokens


def retrieve_info(query: str, top_k: int = 3) -> list[dict]:
    """Naive keyword-overlap retrieval across the knowledge base.

    Returns the top_k entries with the highest token overlap against the
    query, each tagged with its source id so responses can cite it.
    """
    query_tokens = _tokenize(query)
    entries = load_knowledge_base()
    scored = []
    for entry in entries:
        haystack = " ".join(
            [
                entry.get("name_en", ""),
                entry.get("name_zh", ""),
                entry.get("description_en", ""),
                entry.get("description_zh", ""),
                " ".join(entry.get("tags", [])),
            ]
        )
        score = len(query_tokens & _tokenize(haystack))
        if score > 0:
            scored.append((score, entry))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [entry for _, entry in scored[:top_k]]


def identify_exhibit(image_base64: str, media_type: str = "image/jpeg") -> dict:
    """Ask Claude to match a photo against the knowledge base entries."""
    entries = load_knowledge_base(include_canary=False)
    catalogue = "\n".join(
        f"- {e['id']}: {e['name_en']} / {e['name_zh']} ({e['category']}, {e['floor']})"
        for e in entries
    )
    response = get_client().messages.create(
        model="claude-sonnet-5",
        max_tokens=200,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_base64,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "Here is the current catalogue of known stores/"
                            f"facilities:\n{catalogue}\n\n"
                            "Which entry id does this photo most likely show? "
                            "Reply with ONLY the id, or 'unknown' if none match."
                        ),
                    },
                ],
            }
        ],
    )
    match_id = "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()
    match = next((e for e in entries if e["id"] == match_id), None)
    return match or {"id": "unknown"}


def speak(text: str, lang: str = "zh") -> str:
    """Call ElevenLabs TTS, save the audio, return the local file path."""
    api_key = os.environ["ELEVENLABS_API_KEY"]
    voice_id = os.environ.get(
        f"ELEVENLABS_VOICE_ID_{lang.upper()}"
    ) or "21m00Tcm4TlvDq8ikWAM"  # ElevenLabs default demo voice as fallback

    resp = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        headers={
            "xi-api-key": api_key,
            "Content-Type": "application/json",
        },
        json={
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        },
        timeout=30,
    )
    resp.raise_for_status()

    out_path = AUDIO_DIR / f"reply_{abs(hash(text))}.mp3"
    out_path.write_bytes(resp.content)
    return str(out_path)


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text)


def _resolve_node(graph: dict, query: str) -> str | None:
    """Match free-text like 'the hotpot place' to a node id — first by
    direct name match, then by falling back to the same retrieval used for
    Q&A (in case someone names a venue we haven't linked into the graph
    under that exact wording)."""
    q = query.lower().strip()
    for node_id, node in graph["nodes"].items():
        if q and (q in node.get("name_en", "").lower() or q in node.get("name_zh", "")):
            return node_id
    for match in retrieve_info(query, top_k=1):
        if match["id"] in graph["nodes"]:
            return match["id"]
    return None


def get_directions(from_place: str, to_place: str) -> dict:
    """Real graph pathfinding — never invents a route. If the two places
    aren't connected by anything learned so far, says so explicitly."""
    graph = sg.load()
    start_id = _resolve_node(graph, from_place)
    end_id = _resolve_node(graph, to_place)

    if not start_id or not end_id:
        unresolved = [p for p, i in [(from_place, start_id), (to_place, end_id)] if not i]
        return {
            "found": False,
            "reason": f"not yet in the spatial map: {', '.join(unresolved)}",
        }

    path = sg.find_path(graph, start_id, end_id)
    if not path:
        return {
            "found": False,
            "reason": (
                "both locations are known but no learned connection links them yet — "
                "say so honestly rather than guessing a route"
            ),
        }

    steps = []
    for node_id, relation, note in path:
        node = graph["nodes"][node_id]
        steps.append(
            {
                "name_en": node.get("name_en"),
                "name_zh": node.get("name_zh"),
                "type": node.get("type"),
                "via": relation,
                "note": note,
            }
        )
    return {"found": True, "steps": steps}


def learn_location(description: str) -> dict:
    """Extract spatial facts from a free-text description (or a summary of
    a photo) and merge them into the persistent spatial graph. Only records
    what's actually stated — never invents connections."""
    graph = sg.load()
    existing = [
        {"id": nid, "name_en": n.get("name_en"), "name_zh": n.get("name_zh")}
        for nid, n in graph["nodes"].items()
    ]

    prompt = f"""Extract spatial facts about Grand Gateway 66 mall from this \
description, to merge into a spatial graph.

Existing known nodes (reuse an id below if the description refers to the \
same place — do not create a duplicate node for something already listed):
{json.dumps(existing, ensure_ascii=False)}

Description: {description}

Return ONLY JSON, no markdown fences, in this schema:
{{
  "nodes": [{{"id": "new_snake_case_id", "name_en": "...", "name_zh": "...", \
"type": "entrance|elevator|escalator|landmark|venue", "floor": "e.g. L1 or null", \
"tower": "South Tower|North Tower|null"}}],
  "edges": [{{"from": "node_id", "to": "node_id", "relation": \
"connected_via_elevator|connected_via_escalator|connected_via_walkway|near|adjacent_to|same_floor|left_of|right_of", \
"note": "short free text"}}]
}}
Only include nodes/edges for facts actually stated or clearly implied. Do \
not invent connections the description doesn't mention. If there's nothing \
extractable, return {{"nodes": [], "edges": []}}."""

    response = get_client().messages.create(
        model="claude-sonnet-5",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(block.text for block in response.content if block.type == "text")
    data = _extract_json(text)

    for n in data.get("nodes", []):
        node_id = n.pop("id")
        sg.upsert_node(graph, node_id, **n)
    for e in data.get("edges", []):
        sg.add_edge(graph, e["from"], e["to"], e["relation"], e.get("note", ""))
    sg.save(graph)

    return {
        "added_nodes": len(data.get("nodes", [])),
        "added_edges": len(data.get("edges", [])),
    }
