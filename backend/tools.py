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

import dashscope
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

AMAP_KEY = os.environ.get("AMAP_API_KEY")
DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY")

# International (Singapore) DashScope accounts need a workspace-scoped
# endpoint instead of the flat mainland one — set only when that env var is
# present, so a mainland account (no workspace id needed) is unaffected.
_DASHSCOPE_WORKSPACE_ID = os.environ.get("DASHSCOPE_WORKSPACE_ID")
if _DASHSCOPE_WORKSPACE_ID:
    dashscope.base_http_api_url = (
        f"https://{_DASHSCOPE_WORKSPACE_ID}.ap-southeast-1.maas.aliyuncs.com/api/v1"
    )

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"
AUDIO_DIR = Path(__file__).parent.parent / "audio_output"
AUDIO_DIR.mkdir(exist_ok=True)

def load_knowledge_base(include_canary: bool = True) -> list[dict]:
    entries = []
    for path in KNOWLEDGE_DIR.glob("*.json"):
        with open(path, encoding="utf-8") as f:
            entry = json.load(f)
        if entry.get("canary") and not include_canary:
            continue
        entries.append(entry)
    return entries


_BRANCH_SUFFIX_RE = re.compile(r"[（(].*$")
_real_brand_names_cache: list[str] | None = None


def get_real_brand_names() -> list[str]:
    """Brand-root names (branch suffix stripped) for every real knowledge-base
    entry, e.g. "麻布屋 Azabuya（乌鲁木齐中路店）" -> "麻布屋 Azabuya". Used to
    verify a reply that names a specific shop isn't naming one that doesn't
    exist — see agent.py's post-reply grounding check. Cached: the knowledge
    base is static per process, loaded from disk once."""
    global _real_brand_names_cache
    if _real_brand_names_cache is None:
        names = set()
        for entry in load_knowledge_base(include_canary=False):
            for field in ("name_zh", "name_en"):
                raw = entry.get(field, "")
                stripped = _BRANCH_SUFFIX_RE.sub("", raw).strip()
                if stripped:
                    names.add(stripped)
        _real_brand_names_cache = sorted(names)
    return _real_brand_names_cache


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


def retrieve_info(query: str, top_k: int = 20) -> list[dict]:
    """Naive keyword-overlap retrieval across the knowledge base.

    Returns the top_k entries with the highest token overlap against the
    query, each tagged with its source id so responses can cite it.

    top_k defaults well above the current ~15-entry knowledge base size —
    not exposed to the model as a tool parameter, so this was the only
    thing controlling it. A lower default (6) caused a real, confirmed
    eval failure: a brand with 5 separate near-identical branch entries
    (each scoring high on any query about that brand) crowded other
    genuinely relevant brands out of the results entirely, and left only
    one arbitrary survivor among that brand's own branches — so a
    location-constrained question ("near Jing'an") had no way to compare
    branches against each other, since it only ever saw whichever one
    branch happened to survive the cutoff. Only entries that score above
    0 are ever returned, so raising this doesn't inject irrelevant noise
    — it just stops truncating genuine matches once the KB is bigger than
    the cap. Revisit if the knowledge base grows enough that returning
    most/all of it stops being cheap or useful.
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
    # "canary" and the "canary"/"example" tags are internal bookkeeping (see
    # knowledge/README.md) — leaking them into the tool result lets the model
    # see its own test data flagged as fake and refuse to state it confidently.
    results = []
    for _, entry in scored[:top_k]:
        clean = {k: v for k, v in entry.items() if k != "canary"}
        clean["tags"] = [t for t in clean.get("tags", []) if t not in ("canary", "example")]
        results.append(clean)
    return results


def _brand_key(entry: dict) -> str:
    return entry["name_en"].split(" (")[0].strip().lower()


def _food_matches_menu(visible_food: str, candidate: dict) -> bool:
    """A second, cheap text-only call to check whether a specific dish the
    vision model claims to see is actually plausible for this candidate's
    real menu — plain keyword overlap isn't reliable here, since generic
    words like "pie" or "cream" trivially overlap with a pie shop's menu
    even when the specific flavor (e.g. banana) isn't on it at all."""
    if not visible_food:
        return True
    menu_text = f"{candidate.get('description_en', '')}\n{candidate.get('description_zh', '')}"
    response = dashscope.Generation.call(
        api_key=DASHSCOPE_API_KEY,
        model="qwen-plus",
        result_format="message",
        temperature=0.1,
        messages=[
            {
                "role": "user",
                "content": (
                    f'A photo appears to show this dish: "{visible_food}".\n'
                    f"Here is a specific store's real menu:\n{menu_text}\n\n"
                    "Ignoring plating/garnish/presentation details, does this "
                    "store's actual menu include the same core dish or flavor "
                    "(e.g. a matcha-flavored item photo counts as a match for "
                    "a store that sells matcha items, even if the exact "
                    "plating differs)? A photo showing a fundamentally "
                    "different dessert type or flavor not on this menu at all "
                    "(e.g. cheesecake at a gelato-only shop, or a flavor "
                    "never listed) should NOT match. Reply with ONLY 'yes' or "
                    "'no'."
                ),
            }
        ],
    )
    if response.status_code != 200:
        return False
    answer = (response.output.choices[0].message.get("content") or "").strip().lower()
    return answer.startswith("y")


def identify_exhibit(image_base64: str, media_type: str = "image/jpeg") -> dict:
    """Ask Qwen-VL to match a photo against the knowledge base entries.

    An earlier version just asked "which id, or unknown" and trusted the
    answer — live testing with real photos showed it almost never actually
    said unknown, instead confidently naming the nearest-looking entry even
    across food categories (a Basque cheesecake photo matched to a
    matcha-only gelato brand) or guessing one specific branch from a photo
    that only showed the brand, not the branch (a bare logo/cup, no address
    in frame — a different branch guessed each time re-tested). Same
    false-confidence shape as the text agent's stretching bug, just on the
    vision side.

    Fix: ask for the specific evidence visible (a dish, an address/sign)
    instead of trusting a bare id, then verify that evidence before trusting
    the match. A food claim not actually on the candidate's own menu is
    rejected outright. A location claim that can't confirm the specific
    branch, when sibling branches of the same brand exist, downgrades to an
    "ambiguous" result listing the real candidates instead of guessing one —
    mirroring how get_transit_directions already handles an ambiguous place.
    """
    entries = load_knowledge_base(include_canary=False)
    catalogue = "\n".join(
        f"- {e['id']}: {e['name_en']} / {e['name_zh']} ({e['category']}, {e.get('address', '')})"
        for e in entries
    )
    response = dashscope.MultiModalConversation.call(
        api_key=DASHSCOPE_API_KEY,
        model="qwen-vl-max",
        messages=[
            {
                "role": "user",
                "content": [
                    {"image": f"data:{media_type};base64,{image_base64}"},
                    {
                        "text": (
                            "Here is the current catalogue of known stores/"
                            f"facilities:\n{catalogue}\n\n"
                            "Which entry id does this photo most likely show? "
                            "Only answer with a specific id if you can point "
                            "to real visible evidence — a legible store name/"
                            "logo, an address/mall/street sign in frame, or a "
                            "specific dish. Reply with ONLY this JSON, no "
                            "other text: "
                            '{"candidate_id": "<id, or \\"unknown\\">", '
                            '"visible_food": "<specific dish/item you can '
                            'see, or empty string>", '
                            '"visible_location": "<any address/mall/street/'
                            'sign text you can read, or empty string>"}'
                        )
                    },
                ],
            }
        ],
    )
    if response.status_code != 200:
        raise RuntimeError(f"Qwen-VL error {response.status_code}: {response.message}")
    text = response.output.choices[0].message.content[0]["text"].strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"id": "unknown"}

    candidate = next(
        (e for e in entries if e["id"] == (parsed.get("candidate_id") or "").strip()), None
    )
    if candidate is None:
        return {"id": "unknown"}

    visible_food = (parsed.get("visible_food") or "").strip()
    if not _food_matches_menu(visible_food, candidate):
        return {"id": "unknown"}

    visible_location = (parsed.get("visible_location") or "").strip()
    location_confirmed = bool(
        visible_location and _tokenize(visible_location) & _tokenize(candidate.get("address", ""))
    )

    siblings = [e for e in entries if e["id"] != candidate["id"] and _brand_key(e) == _brand_key(candidate)]
    if not location_confirmed and siblings:
        options = [candidate] + siblings
        return {
            "id": "ambiguous",
            "brand_en": _brand_key(candidate).title(),
            "brand_zh": candidate["name_zh"].split("（")[0].strip(),
            "options": [
                {
                    "id": o["id"],
                    "name_en": o["name_en"],
                    "name_zh": o["name_zh"],
                    "address": o.get("address", ""),
                }
                for o in options
            ],
        }

    clean = {k: v for k, v in candidate.items() if k != "canary"}
    clean["tags"] = [t for t in clean.get("tags", []) if t not in ("canary", "example")]
    return clean


def describe_unmatched_photo(image_base64: str, media_type: str = "image/jpeg") -> dict:
    """When identify_exhibit finds no knowledge-base match, ask Qwen-VL for a
    plain-language description instead — a store name if signage is visible,
    or the dish/food type otherwise. Fed into a normal chat turn afterward so
    the existing agent (retrieve_info/web-search/attribution rules) handles
    it like any other question, rather than dead-ending on "no match".

    Still requires a legible name before naming a brand (no guessing from
    packaging style alone — same evidence bar as identify_exhibit, just
    without a knowledge-base candidate to check it against). What changed is
    tone and a confidence field: state it directly ("这是Godiva的黑巧克力松
    露") instead of hedging with "the image shows text reading...", and
    report how sure that reading is so the frontend can label it as a guess
    rather than pass it off as a verified match.
    """
    response = dashscope.MultiModalConversation.call(
        api_key=DASHSCOPE_API_KEY,
        model="qwen-vl-max",
        messages=[
            {
                "role": "user",
                "content": [
                    {"image": f"data:{media_type};base64,{image_base64}"},
                    {
                        "text": (
                            "This photo didn't match any entry in a curated "
                            "dessert-shop database. State what it shows "
                            "directly and confidently, like a knowledgeable "
                            "friend naming it on sight — not a clinical "
                            "description of pixels or text you see. If a "
                            "store/brand name is legible on signage or "
                            "packaging, say outright what it is (e.g. "
                            '"这是Godiva的黑巧克力松露"), don\'t hedge with '
                            '"appears to show" or "text reading X". If no '
                            "brand name is legible anywhere, just name the "
                            "food/dish confidently — don't invent a brand. "
                            "Reply in Chinese unless the visible text is "
                            "English. Reply with ONLY this JSON, no other "
                            "text: "
                            '{"description": "<one short confident '
                            'sentence>", "confidence": "<high|medium|low>"}'
                            "\n\nconfidence is ONLY about whether a store/"
                            "brand NAME is legible in the photo — it is NOT "
                            "about how sure you are what the food/dish is. "
                            "high = a store/brand name is clearly legible; "
                            "medium = a store/brand name is partially "
                            "legible or small/blurry but you're fairly sure "
                            "what it says; low = no store/brand name is "
                            "legible anywhere in the photo, even if you're "
                            "completely certain what the food itself is — "
                            "being sure this is, say, a Basque cheesecake "
                            "is NOT high confidence, since no brand backs "
                            "that claim. Default to low whenever in doubt."
                        )
                    },
                ],
            }
        ],
    )
    if response.status_code != 200:
        raise RuntimeError(f"Qwen-VL error {response.status_code}: {response.message}")
    text = response.output.choices[0].message.content[0]["text"].strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"description": text, "confidence": "low"}
    confidence = parsed.get("confidence")
    return {
        "description": (parsed.get("description") or "").strip(),
        "confidence": confidence if confidence in ("high", "medium", "low") else "low",
    }


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


def _resolve_place(query: str) -> tuple[str | None, list[str] | None]:
    """If the query matches known knowledge-base entries, resolve to the
    real name + address for geocoding precision. If multiple entries tie
    for the top match (e.g. a brand with several locations), that's
    ambiguous — return the candidate names instead of silently picking
    one. Returns (resolved_place, None) on a clean resolution/passthrough,
    or (None, [candidate names]) when ambiguous."""
    matches = retrieve_info(query, top_k=5)
    if not matches:
        return query, None

    top_score = len(_tokenize(query) & _tokenize(" ".join(
        [matches[0].get("name_en", ""), matches[0].get("name_zh", ""),
         matches[0].get("description_en", ""), matches[0].get("description_zh", ""),
         " ".join(matches[0].get("tags", []))]
    )))
    tied = [
        m for m in matches
        if len(_tokenize(query) & _tokenize(" ".join(
            [m.get("name_en", ""), m.get("name_zh", ""),
             m.get("description_en", ""), m.get("description_zh", ""),
             " ".join(m.get("tags", []))]
        ))) == top_score
    ]
    if len(tied) > 1:
        names = [m.get("name_zh") or m.get("name_en", "") for m in tied]
        if len(set(names)) > 1 or len(tied) > 1:
            return None, [f"{n} — {m.get('address', '')}" for n, m in zip(names, tied)]

    entry = matches[0]
    name = entry.get("name_zh") or entry.get("name_en", "")
    return f"{name} {entry.get('address', '')}".strip(), None


def _amap_geocode(place: str) -> tuple[float, float] | None:
    """Resolve a free-text place name/address to (lng, lat) via Amap's POI
    text search, scoped to Shanghai. Returns None if unresolvable or if no
    Amap key is configured — callers must treat that as 'don't know',
    never fall back to guessing coordinates."""
    if not AMAP_KEY:
        return None
    resp = requests.get(
        "https://restapi.amap.com/v3/place/text",
        params={
            "key": AMAP_KEY,
            "keywords": place,
            "city": "上海",
            "citylimit": "true",
            "offset": 1,
        },
        timeout=10,
    )
    resp.raise_for_status()
    pois = resp.json().get("pois") or []
    if not pois:
        return None
    lng, lat = pois[0]["location"].split(",")
    return float(lng), float(lat)


def get_transit_directions(from_place: str, to_place: str) -> dict:
    """Real public-transit (metro/bus) directions between two Shanghai
    places, via Amap's transit routing API. Never invents a route — returns
    found=false if either place can't be located or Amap has no route."""
    if not AMAP_KEY:
        return {
            "found": False,
            "reason": "transit routing isn't configured yet (no Amap API key)",
        }

    from_resolved, from_options = _resolve_place(from_place)
    to_resolved, to_options = _resolve_place(to_place)
    if from_options or to_options:
        return {
            "found": False,
            "ambiguous": True,
            "reason": (
                f"'{from_place if from_options else to_place}' matches multiple "
                "known locations — ask the visitor which one they mean before "
                "trying again"
            ),
            "options": from_options or to_options,
        }

    origin = _amap_geocode(from_resolved)
    dest = _amap_geocode(to_resolved)
    if not origin or not dest:
        unresolved = [p for p, c in [(from_place, origin), (to_place, dest)] if not c]
        return {"found": False, "reason": f"couldn't locate: {', '.join(unresolved)}"}

    resp = requests.get(
        "https://restapi.amap.com/v3/direction/transit/integrated",
        params={
            "key": AMAP_KEY,
            "origin": f"{origin[0]},{origin[1]}",
            "destination": f"{dest[0]},{dest[1]}",
            "city": "上海",
            "cityd": "上海",
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "1":
        return {"found": False, "reason": data.get("info", "Amap routing failed")}

    transits = data.get("route", {}).get("transits") or []
    if not transits:
        return {"found": False, "reason": "no transit route found between these two points"}

    best = transits[0]
    steps = []
    for segment in best.get("segments", []):
        walking = segment.get("walking") or {}
        if float(walking.get("distance") or 0) > 0:
            steps.append({"type": "walk", "distance_m": walking["distance"]})
        for busline in (segment.get("bus") or {}).get("buslines") or []:
            steps.append(
                {
                    "type": "transit",
                    "line": busline.get("name"),
                    "from_stop": (busline.get("departure_stop") or {}).get("name"),
                    "to_stop": (busline.get("arrival_stop") or {}).get("name"),
                    "num_stops": busline.get("via_num"),
                }
            )
    return {
        "found": True,
        "total_duration_min": round(int(best.get("duration", 0)) / 60),
        "steps": steps,
    }
