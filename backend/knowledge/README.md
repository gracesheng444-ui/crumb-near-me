# Knowledge base

Each file here is one JSON entry describing a store, F&B spot, or facility at
Grand Gateway 66. The agent's `retrieve_info` tool searches across all of
these — it never answers from anything outside this folder.

## Schema

```json
{
  "id": "unique_slug",
  "category": "retail | dining | facility",
  "floor": "e.g. B1, L1, L5",
  "name_en": "English name",
  "name_zh": "中文名称",
  "description_en": "1-3 sentences, factual, written by you.",
  "description_zh": "同上，中文。",
  "tags": ["free-text tags to help retrieval, e.g. 'bubble tea', 'kids'"],
  "canary": false
}
```

## Canary entries

Set `"canary": true` on a small number of entries containing a detail that
is **made up and could not be known any other way** (see
`example_canary.json`). These exist purely to test whether the agent is
actually retrieving from this knowledge base rather than guessing from
Claude's general knowledge. Strip canary entries out before any real public
demo — keep them for your own eval runs only.

## Adding real content

Replace `example_entry.json` and add one file per store/facility you're
confident about. Quality > coverage — 10-15 accurate entries beat 40 vague
ones.
