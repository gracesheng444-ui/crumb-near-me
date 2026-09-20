# Knowledge base

Each file here is one JSON entry describing a dessert spot in Shanghai. The
agent's `retrieve_info` tool searches across all of these — it never answers
from anything outside this folder.

## Schema

```json
{
  "id": "unique_slug",
  "category": "free-text dessert type, e.g. 'chocolate', 'Chinese sweet soup', 'bubble tea', 'bakery', 'gelato'",
  "address": "a name/address specific enough for Amap to geocode, e.g. '港汇恒隆广场, 徐汇区, 上海市' or a standalone street address",
  "name_en": "English name",
  "name_zh": "中文名称",
  "description_en": "1-3 sentences, factual, written by you — signature item, what makes it worth visiting.",
  "description_zh": "同上，中文。",
  "tags": ["free-text tags to help retrieval, e.g. 'matcha', 'must-try', 'long queue'"],
  "canary": false
}
```

`address` also feeds `get_transit_directions` — it's geocoded via Amap to
compute real metro/bus routes, so keep it accurate enough to resolve to the
right building.

## Canary entries

Set `"canary": true` on a small number of entries containing a detail that
is **made up and could not be known any other way** (see
`example_canary.json`). These exist purely to test whether the agent is
actually retrieving from this knowledge base rather than guessing from the
model's own general training knowledge. Strip canary entries out before any
real public demo — keep them for your own eval runs only.

## Adding real content

Add one file per dessert spot you're confident about. Quality > coverage —
10-15 accurate entries beat 40 vague ones.

## Archive

`_archive_grand_gateway_66/` holds the original mall-tenant entries (retail,
hotpot, etc.) from when this project was scoped to a single mall. They're
outside `retrieve_info`'s glob (non-recursive), so they're kept for
reference only and not loaded.
