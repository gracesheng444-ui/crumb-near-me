# Vision eval photos

`run_vision_eval.py` reads real photo files from this folder, matching the
filenames listed in `vision_questions.json`. These (and `.gitignore`'d
local test photos like `dessert_photos/`) are the one part of the eval
suite that can't just be written as prose — unlike the text questions,
these need to be actual photos of actual Shanghai shops/dishes, so pulling
random images off the web and presenting them as real test assets would
undermine the whole point of the eval.

## What's here now — 6 photos across 3 categories

| File | Category | Tests |
|---|---|---|
| `brand_explicit_azabuya.png` | `brand_explicit` | Brand + storefront legible, but no address in frame — correct answer is `ambiguous` across the 5 real Azabuya branches, not a guessed single one. |
| `brand_logo_azabuya.png` | `brand_logo_only` | Only the abstract logo mark visible, no wordmark/storefront/address — `unknown` or `ambiguous` both pass; a specific wrong branch guess doesn't. |
| `food_basque_cheesecake.png` | `food_recognition` | A dish with no store evidence at all — must recommend real KB entries that actually sell it, not force-match to an unrelated brand. |
| `food_banana_pie.png` | `food_recognition` | Same shape, a flavor no KB entry's real menu documents — checks the model doesn't invent a menu item to make a match. |
| `notkb_real_baoshifu.png` | `not_in_kb_real` | A real, well-known chain (Bao's Pastry) that just isn't curated — must admit that and use web search, not invent a connection to an unrelated real KB brand. |
| `notkb_fictional_silvermooncake.png` | `not_in_kb_fictional` | A storefront that doesn't correspond to any real shop — must admit no match, not fabricate details for something that doesn't exist. |

See `vision_questions.json` for each case's exact expected behavior and
`EVAL_TAXONOMY.md`'s "Vision capability" section for the full design
rationale, plus `first_refinement.md` item 6 for what this suite has
already caught and fixed.

## Adding more

Known gaps, in priority order (see also the "what other kinds of photos"
discussion — same reasoning applies here): **a clean positive match** (a
photo where the correct answer is a specific single branch id, with a
legible address/branch detail in frame — every case above tests refusal or
ambiguity, so there's currently no case that would catch the model
becoming *too* cautious); an **off-topic/non-dessert photo** (tests
declining cleanly instead of forcing a dessert-shaped answer onto
unrelated content); and **multiple distinct items in one frame** (tests
whether it silently drops items it can't identify rather than inventing
details for them).

Your own photos work best here — e.g. something already in
`dessert_photos/` from using the app yourself, or a photo from an actual
visit — since you already have rights to them and they're guaranteed to
be real. Once new photos are in place, add a matching entry to
`vision_questions.json` and run:

```bash
python -m eval.run_vision_eval
```
