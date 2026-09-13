# Qwen Findings & Improvement Plan

Based on three full eval runs (47 weighted questions, 8 capabilities) against the Shanghai Dessert Guide agent after migrating it from Claude to Qwen (`qwen-plus` for chat, `qwen-vl-max` for vision).

## What the eval revealed about Qwen's ability

### 1. Grounding under open-ended generation is weaker than expected
When a question has a single clear fact to look up, Qwen grounds it reliably (Factual lookup: 1.86/2). But for open-ended "recommend something" questions — no single fact to retrieve, just a judgment call — it sometimes skips calling `retrieve_info` entirely and invents a plausible-sounding shop instead. In the worst case caught, it explicitly said *"I checked your history and it's empty... the knowledge base didn't return any entries"* — correctly reporting it found nothing — **then invented a fake shop anyway.** This persisted across repeated sampling of the identical prompt (roughly 1-in-3 to 1-in-4), and lowering temperature to 0.2 did not fix it. This is a rule-adherence gap, not a randomness artifact.

### 2. "Stretching" a real fact to cover a gap
When no knowledge-base entry actually matches a specific request (e.g. a French macaron specialist that doesn't exist in the data), Qwen doesn't reliably say so. Instead it sometimes picks an unrelated real store and invents supporting "evidence" — in the case caught, a fabricated *"many customers say this tastes close to a professional macaron shop"* claim — to make the stretch sound credible. Reproduced identically across two separate runs. This is arguably worse than plain invention: it wraps a false claim around a real store's real, accurate details, which makes it more convincing rather than less.

### 3. Over-elaboration on low-stakes prompts
Chit-chat was the single worst-scoring capability (0.80/2) in every run. Brief, casual questions ("do you like dessert?") reliably get long, embellished replies — invented personal history, fabricated shop tips, and twice, fully invented pseudo-scientific citations (a fake "2026 study," fake "China Youth Daily" references) — when the expected behavior was a short, natural, in-persona remark.

### 4. Self-grading (LLM-as-judge) is a real, demonstrated weakness
Using `qwen-plus` to judge its own answers produced at least two confirmed cases where the judge asserted a real knowledge-base entry ("EAU Café") was "invented" or "non-existent" — a hallucination in the grading rationale itself, separate from whatever it was grading. This isn't a theoretical same-model-bias concern; it showed up directly in the data.

### 5. Occasional dropped tool calls
A minority of transit-routing questions didn't trigger `get_transit_directions` at all, non-deterministically — same question, different outcome across runs. Not yet root-caused the way the retrieval bug below was.

### 6. Minor output-level quirks
- Qwen defaults to curly/smart punctuation (’) rather than straight ASCII — cosmetic, but it broke naive string-matching checks that assumed a straight apostrophe.
- It occasionally names its own internal tool (`retrieve_info`) by name while explaining a refusal — a small architecture-detail leak, not a full prompt leak, but worth noting.

### 7. What it does well (for balance)
- **Multi-turn context retention: perfect (2.00/2)** across every phrasing tested.
- **Factual lookup: strong (1.86/2).**
- Once given complete information, it aggregates correctly: fixing a retrieval bug (not a Qwen problem — see below) took Synthesis from 1.07/2 to 1.50/2. The earlier failure was as much a retrieval/context-completeness problem as a model-reasoning one — worth separating "Qwen reasons badly" from "Qwen wasn't given what it needed" before blaming the model.

## Planned next steps

1. ~~**Recommendation/stretching hallucination**~~ **— done, verified.** Added a post-hoc check in `agent.py` (`_looks_like_unverified_shop_claim`): after a draft reply, flag it if it makes a concrete claim (price/address/distance, or a bolded/quoted proper noun) about a shop that isn't a real knowledge-base brand and isn't attributed to a web search/community note — then force exactly one corrective retry with an automated notice, rather than trusting the prompt alone. Verified with 8 fresh samples of the hardest no-signal case: 0 fabrications (was fabricating in nearly every sample before). Directly observed the correction firing live — a caught draft's corrected reply opened with *"you're right, I didn't follow the rules just now"* before giving a properly grounded answer.

   **Escalates finding #4 below**: a judge-graded batch run scored this fix at 0.40/2, apparently regressed — but the underlying replies showed the judge calling a real, repeatedly-verified brand ("EAU Café") "fabricated" while describing text that never even mentioned it. Direct verification against real data is currently more trustworthy than the judge score for this capability.

2. **"Stretching" a real entry with fake support — partially addressed as a side effect.** While testing #1, found the same fabricated-testimonial pattern occurring even in an otherwise-correctly-grounded reply (a real store, wrapped in an invented "许多顾客反馈..." quote). Extended the same check to also flag unattributed testimonial phrasing. Not yet given its own dedicated eval case — that's still open.

3. ~~**Chit-chat over-elaboration**~~ **— done, verified.** Added rule 9 (1-2 sentences for casual turns, no invented personal history, no invented supporting "facts" of any kind) and extended the same post-hoc verification from #1/#2 with a citation/biochemistry-term detector — this app's knowledge base has zero nutrition/psychology content, so any unattributed study/statistic claim is essentially always fabricated. Verified: re-ran the full 5-question capability (10 cases) — **0.80/2 → 1.80/2**. The one remaining "failure" looks like judge inconsistency, not a real issue (the identical claim passed in English, failed in Chinese, for the same question). Did not end up needing the `max_tokens` structural approach floated below — the rule + verification combination was enough.

4. **Judge reliability** — either accept the same-family limitation as a documented tradeoff (cheapest), or have the judge quote the specific fact it's disputing before scoring, forcing it to ground its own criticism rather than assert freely. Now backed by three separate confirmed cases of the judge asserting something flatly false, not two.

5. **Dropped tool calls** — not yet root-caused. Next step is comparing tool-call presence across repeated identical calls to see if it correlates with phrasing/language before deciding on a fix, the same way the retrieval bug was isolated.

6. **General practice** — re-run the eval suite as changes land and compare against the saved timestamped results, rather than assuming a fix worked. Every claim in this document was verified this way, not asserted from a single sample.
