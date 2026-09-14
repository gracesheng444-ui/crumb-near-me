# Vision eval photos

`run_vision_eval.py` reads real photo files from this folder, matching the
filenames listed in `vision_questions.json`. None are checked into the
repo — unlike the text questions (which are just prose I can write),
these need to be actual photos of actual Shanghai shops, so pulling
random images off the web and presenting them as real test assets would
undermine the whole point of the eval.

Three to start (expand later, e.g. one per brand, or add more no-match
cases):

1. **`clear_match_azabuya_taikoohui.jpg`** — a photo that clearly shows
   this specific Azabuya branch: storefront/signage, or a cup/receipt
   with the branch name visible. Should identify unambiguously.
2. **`ambiguous_matcha_gelato.jpg`** — a matcha gelato cup/cone with no
   visible branch-identifying detail (no storefront, no receipt in
   frame). Any of the 5 Azabuya branch ids counts as a pass here — the
   thing being tested is whether the model still sounds certain when it
   can't actually tell which branch.
3. **`no_match_random_dessert.jpg`** — any dessert/food photo that isn't
   any knowledge-base entry (a home-baked item, an unrelated brand).
   Correct behavior is `"unknown"`, not a forced nearest-guess.

Your own photos work best here — e.g. something already in
`dessert_photos/` from using the app yourself, or a photo from an actual
visit — since you already have rights to them and they're guaranteed to
be real. Once photos are in place, run:

```bash
python -m eval.run_vision_eval
```
