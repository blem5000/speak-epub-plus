# Review — Adversary (Incompatible-but-Compliant Units)

**Lens:** Construct two units one level down that each obey every AD to the letter yet still build incompatibly

## Verdict: adequate — 1 hole found

### Attack 1 — Cache key divergence (AD-9)
Unit A caches by URL only; Unit B by URL+hash. Both obey "cache raw HTML" but disagree on key. On re-run with edited chapter, one reuses stale, other refetches — EPUBs diverge yet both claim AD-9 + AD-5 compliance.

**Hole:** AD-9 says keyed by url+hash [ASSUMPTION] but AD-5 only says _cache/<hash>/raw/ without defining hash source. Need tightening.

Fix: Amend AD-9 Rule to "Core owns cacheKey(url) = sha1(url) — adapters never compute keys." Add to Conventions cache key shape. Raw cache never filtered — test verifies.

### Attack 2 — Filter timing race (AD-2)
Unit A filters in clean.py; Unit B in epub.py. Both claim "applied once" but filter different layers. Wording already says "at EPUB build, on cleaned text after isolation" — tighten with test: raw cache contains filter phrase while EPUB text does not.

No other pair found; dependency direction and event bus block drift.

