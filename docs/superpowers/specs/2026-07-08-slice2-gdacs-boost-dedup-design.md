# Slice 2 — Multi-hazard, newsworthiness boost, cross-feed dedup & affected estimate

- **Status:** Approved (design), pre-implementation
- **Date:** 2026-07-08
- **Feature:** GitHub issues #4 (newsworthiness boost + ranking) **and** #5 (GDACS +
  cross-feed dedup, merge & affected estimate), bundled into one slice, under PRD #2.
- **Authoritative constraints:** ADR 0003 (severity / major / newsworthiness boost from v1),
  0005 (two-layer dedup — deterministic layer is the sole gate driver), 0006 (stack & hosting /
  the one versioned JSON contract), 0007 (client-side BYOK, grounded AI); `CLAUDE.md`
  conventions.
- **Builds on:** Slice 1 (PR #13) — the USGS→contract→map spine and frozen contract v1.

## 1. Goal

Turn the earthquake-only walking skeleton into a **multi-hazard, editorially-ranked** crisis
map. Add a second feed (GDACS, all hazard types), rank events by **newsworthiness** (proximity
to population) rather than raw magnitude, **collapse the same real-world event** reported by
both feeds into one canonical event with merged provenance, and surface a **grounded
affected-population estimate**. All of this crosses to the front end through **one breaking bump
of the JSON contract to `2.0.0`** — the two halves still meet only at that seam.

### In scope (issues #4 + #5, bundled)
- **GDACS ingest** — the EVENTS4APP GeoJSON feed, **all hazard types**: earthquake (EQ),
  tropical cyclone (TC), flood (FL), volcano (VO), drought (DR). Parser kept separate and
  swappable alongside USGS (ADR 0006).
- **Newsworthiness boost** — deterministic, model-free proximity boost from a committed
  population-centres/capitals dataset; a numeric `severity.score` (base signal + boost) that
  drives default ordering **and** the `major` gate; the boost inputs **retained in the contract**
  for auditability (issue #4: "not a black box").
- **Cross-feed deterministic dedup + merge** — ADR 0005 layer-1 only (GLIDE / shared source IDs /
  same-hazard + ~100 km + time-window). Merge into one canonical event, all source links kept.
  The merged record is the **sole gate driver**. Embeddings (layer-2) deferred.
- **Affected estimate** — GDACS-derived population-exposure figure carried **verbatim** with its
  GDACS basis text and provenance; grounded per ADR 0007 (never fabricated, uncertainty explicit).
  Investigated for **all five hazards** (see §7.5).
- **Front end** — hazard-generic markers (colour = level, size = score, glyph = hazard) + legend;
  score + boost-audit block; multi-source provenance; affected display; per-feed health copy; a
  loud `schema_version` guard. Renders fully **with no key**.
- **Tests at the seam** — `pytest` (feed fixtures → v2 contract, incl. the hard USGS+GDACS
  duplicate) and `vitest`+RTL (v2 fixture → render).

### Out of scope
Semantic embedding dedup (ADR 0005 layer-2) + the server-side embedding key; change-detection
gate / republish-if-unchanged / state-history store; analytics stage; morning report / AI /
insights; GDACS per-hazard **physical** metrics (wind speed, flood area, VEI); revisions /
history / id-stability across runs; user-facing filters & "show all" toggle; live Vercel deploy
wiring.

## 2. Locked decisions (approved with the user)

1. **Scope** — one slice bundling all four pieces above (issues #4 + #5).
2. **Contract** — exactly **one** breaking bump to `2.0.0` covering every shape change; the two
   halves stay joined only by this versioned JSON contract (ADR 0006).
3. **Boost shape** — keep the base 4-value `severity.level` band unchanged; add a numeric
   `severity.score` (= base signal + proximity boost) driving ordering **and** the `major` gate;
   add an auditable `severity.boost` object retaining inputs. The boost is a deterministic pure
   function of `(lat, lon, static committed dataset)` — model-free (CLAUDE.md conv. 1; ADR 0005).
4. **Multi-hazard model** — a hazard-generic normalized record (Approach A, §3); parsers stay
   separate/swappable.
5. **Dedup** — deterministic layer-1 **only** this slice; embeddings deferred; no server-side
   embedding key introduced.
6. **Affected estimate** — included; GDACS-derived and grounded (ADR 0007); investigated for
   **all five hazards**, shipping real numbers wherever GDACS publishes an exposure figure and a
   documented `null` + reason only where it genuinely does not.
7. **Scoring constants** — adopt the designed defaults (§7.2–7.3); flagged tunable against real
   feed volume per ADR 0003. No pre-implementation review of the numbers.

## 3. Architecture — data model & parser wiring (Approach A)

**Chosen:** one flat, hazard-generic `NormalizedEvent` frozen dataclass + a small parser
registry.

- `pipeline/pipeline/models.py`: `NormalizedQuake → NormalizedEvent`, a **flat superset**.
  - Shared: `feed, source_id, hazard, title, place, time, updated, lat, lon, depth_km, url,
    status`.
  - Per-feed optional signals: `mag, sig` (USGS); `alert, alert_score, glide,
    external_ids: frozenset[str], iso3, country, affected_population: int|None,
    affected_basis: str|None`. EQ-only fields (`mag, sig, depth_km`) become `Optional`, `None`
    for other hazards.
- `pipeline/pipeline/feeds/__init__.py` (currently empty): a plain dict
  `PARSERS: dict[str, Parser] = {"usgs": parse_usgs, "gdacs": parse_gdacs}` where
  `Parser = Callable[[dict], list[NormalizedEvent]]`. No decorators / auto-discovery.
- `pipeline/pipeline/build.py`: rename `WindowFetch → FeedFetch` (add `source`); loop fetches and
  dispatch `PARSERS[f.source]`; label `meta.feeds` from `f.source`/`f.window`.
- **Consequence:** internal dedup keys on `(feed, source_id)` — a bare `source_id` is no longer
  globally unique across feeds.

**Rejected:** (B) minimal stretch of `NormalizedQuake` — the name would lie and a hardcoded
second branch in `build_contract` is exactly the swap-friction ADR 0006 warns against;
(C) two models + adapter/protocol — generalization ahead of need for two feeds; the merge step
still needs one common shape, so the adapter just reintroduces A with extra indirection.

## 4. Contract v2 (the one seam)

One breaking bump to `2.0.0`. Every object keeps `additionalProperties: false`. The annotated
sketch below is the **single authoritative shape**.

```jsonc
{
  "schema_version": "2.0.0",                 // const; loud guard on the FE side
  "generated_at": "2026-07-08T12:00:00Z",    // injected clock → fixed in tests
  "meta": {
    "feeds": [
      { "source": "usgs",  "window": "all_day",         "status": "ok", "fetched_at": "…", "event_count": 12, "error": null },
      { "source": "usgs",  "window": "significant_week", "status": "ok", "fetched_at": "…", "event_count": 3,  "error": null },
      { "source": "gdacs", "window": "events4app",       "status": "ok", "fetched_at": "…", "event_count": 20, "error": null }
    ]
    // FeedHealth.source enum → ["usgs","gdacs"]; window enum → ["all_day","significant_week","events4app"]
  },
  "events": [
    {
      "id": "usgs:us6000serious",            // pattern ^[a-z]+:.+  (usgs:… present-wins; else gdacs:…)
      "hazard": "EQ",                        // enum ["EQ","TC","FL","VO","DR"]  (required)
      "title": "M 6.0 - 20 km S of …",
      "place": "…",
      "time": "2026-07-06T11:29:36Z",        // ISO-8601 UTC
      "geometry": { "lat": 40.4353, "lon": 141.845, "depth_km": 35.0 },  // depth_km number|null (null for non-EQ)
      "magnitude": 6.0,                      // number|null, REQUIRED & always present (null for TC/FL/VO/DR)
      "severity": {
        "level": "serious",                  // enum minor|moderate|serious|severe — BASE band, UNCHANGED, never moved by boost
        "score": 71.3,                       // number ≥0 on a 0–100 scale = base_signal + boost.applied
        "inputs": {                          // always present; all four keys required & nullable
          "mag": 6.0,                        // number|null  (USGS)
          "sig": 640,                        // integer|null (USGS)
          "alert": "orange",                 // string|null enum green|yellow|orange|red|null (USGS PAGER or GDACS colour)
          "alert_score": 1.5                 // number|null  (GDACS only; null for USGS-only EQ)
        },
        "boost": {                           // REQUIRED, always present (never null); applied=0 when remote
          "nearest_place": "Hachinohe",      // string|null (populated in practice)
          "population": 231000,              // integer|null
          "distance_km": 42.0,               // number|null
          "applied": 11.3                    // number ≥0 (points on the 0–100 scale)
        }
      },
      "major": true,                         // = severity.score >= 60.0
      "provisional": false,                  // USGS status governs when USGS present; else GDACS istemporary
      "sources": [                           // ordered, sources[0] = primary (USGS-first); minItems 1, often ≥2 after merge
        { "feed": "usgs",  "id": "us6000serious", "url": "https://earthquake.usgs.gov/…" },
        { "feed": "gdacs", "id": "1550421",       "url": "https://www.gdacs.org/report.aspx?…" }
      ],
      "affected": {                          // REQUIRED, always present; branch on estimate===null (never on absence)
        "estimate": 43996,                   // integer|null ≥0 — GDACS's verbatim exposure count
        "basis": "40 thousand in MMI IV",    // string, REQUIRED (reason string when estimate is null)
        "source": "gdacs"                    // enum ["gdacs", null]
      }
    }
  ]
}
```

### 4.1 Reconciliations baked in (each was an adversarial-critique blocker)

- **`severity.score` scale = 0–100, `MAJOR_CUTOFF = 60.0`.** The single scale that calibrates all
  five hazards and lets the boost (points on the *same* scale) actually tip a sub-threshold event
  over 60. (The component drafts had clashed on 0–10 vs 0–100, which would have made the boost
  inert or the markers pinned.)
- **`severity.base_signal` is NOT emitted.** Auditability holds via
  `base_signal = score − boost.applied`, with `inputs` **and** `boost` both retained.
  `Severity.required = [level, score, inputs, boost]`.
- **`inputs` always-present, all-nullable, canonical name `alert_score`.** EQ sets
  `alert_score: null`. The EQ regression guarantee is **semantic** (level, major, and the values
  of mag/sig/alert), not literal byte-identity of the object — legitimate under a 2.0.0 bump;
  locked decision 3 only freezes the 4-value *level* band.
- **`magnitude` kept `number|null`, REQUIRED & always present** (null for non-EQ). Uniform with
  `boost`/`affected`'s always-present philosophy; the front end guards null and sizes markers off
  `score`.
- **`boost` always present, never null;** `nearest_place/population/distance_km` nullable but
  populated in practice; `applied = 0` for remote events. Field name is `applied` everywhere.
- **`affected` always present;** value field `estimate`, provenance `source` (`"gdacs"|null`),
  `basis` required. Front end/tests read `affected.estimate`/`affected.source`.

### 4.2 Versioning mechanics

- **New file** `contract/schema/contract.v2.schema.json` (`$id …/contract.v2.schema.json`),
  draft 2020-12. `contract.v1.schema.json` kept **frozen** (append-only ethos, ADR 0006).
- **Three coupled constants move together:** schema `schema_version` const `"2.0.0"`; pipeline
  `pipeline/contract.py` `SCHEMA_VERSION = "2.0.0"`; regenerated TS literal in
  `web/lib/contract.types.ts` plus a new `EXPECTED_SCHEMA_VERSION = "2.0.0"` in
  `web/lib/contract.ts`.
- **Fixtures migrate in lockstep:** author `contract.v2.example.json` against the final schema,
  plus `contract.v2.no-major.json` and `contract.v2.feed-down.json`; delete the three v1
  fixtures; regenerate `contract.types.ts`. All count assertions re-baselined in the **same
  commit** (see §8).

## 5. Pipeline flow

```
ingest (fetch USGS×2 windows + GDACS list + bounded GDACS detail)
  → parse (PARSERS[source] → NormalizedEvent)
  → union_by_id  (same-feed, keyed on (feed, source_id), max updated)
  → cross_feed_clusters + merge  (deterministic layer-1 → canonical MergedEvent)
  → severity + boost + score + major  (computed on the merged record)
  → emit contract v2  (sorted score desc, time desc, id asc)
```

Only `pipeline/api/contract.py` touches the network. `build_contract(fetches, detail_map, now)`
stays pure and deterministic given its inputs (injected clock).

## 6. GDACS ingest — `pipeline/pipeline/feeds/gdacs.py` (new)

`parse_gdacs(feed_json) -> list[NormalizedEvent]`:
- `eventtype → hazard` (EQ/TC/FL/VO/DR passed through; **WF and unknown types skipped
  defensively**).
- `coordinates [lon, lat] → lat/lon`; `depth_km = None`.
- `fromdate → time`, `datemodified → updated` via `_parse_gdacs_dt` (naive ISO **assumed UTC**).
- `alertlevel → alert` (lowercased colour); `alertscore → alert_score`.
- `glide '' → None`; `eventid → source_id`; `url.report → url`; `country → place`; `name → title`.
- `mag/sig = None`. Skip features missing `eventid`, coordinates, or an unparseable date (mirror
  the USGS parser's defensive skips).

`feeds/gdacs.md` to be updated (deviation §9.8): the truncated sample wrongly implies population
lives in the list feed; it does not (§7.5).

## 7. Ranking, severity & affected (pipeline pure core)

### 7.1 `geo.py` — shared distance
`great_circle_km(lat1, lon1, lat2, lon2)` haversine (`R = 6371.0088`), stdlib `math` only.
**Shared** by the boost and dedup tier-3 so distance semantics can't drift.

### 7.2 Newsworthiness boost — `boost.py`
Deterministic, model-free, pure function of `(lat, lon, committed dataset)`.
- **Dataset:** `pipeline/pipeline/data/cities.csv` — trimmed GeoNames `cities15000`, filtered
  `population ≥ 100000 OR feature_code == 'PPLC'` (capitals); columns
  `name,country,lat,lon,population,capital` (~300 KB). Provenance + CC BY 4.0 + trim recipe in
  `pipeline/pipeline/data/NOTICE.md`. Loaded once, `__file__`-relative (no network).
- **Nearest city** = argmin over the dataset with tiebreak `(round(distance,6), -population, name)`
  to stabilize the argmin against libm ULP noise (determinism).
- **Formula (points on the 0–100 scale; named tunable constants):**
  - `proximity = max(0, 1 − distance_km / BOOST_RADIUS_KM)`, `BOOST_RADIUS_KM = 300`
  - `pop_weight = min(1.0, log10(max(population, 1)) / 7.0)`
  - `applied = MAX_BOOST · proximity · pop_weight (+ CAPITAL_BONUS · proximity if capital)`,
    capped at `BOOST_CAP`
  - `MAX_BOOST = 15.0`, `CAPITAL_BONUS = 5.0`, `BOOST_CAP = 20.0`; `applied` rounded 3 dp,
    `distance_km` 1 dp.
  - `applied = 0.0` beyond the radius; `nearest_place/population/distance_km` still populated
    (auditable "nearest is X, 2100 km, no boost").
- **Return:** `{nearest_place, population, distance_km, applied}` → `severity.boost` verbatim.

### 7.3 Per-hazard severity & GDACS mapping — `severity.py`
Route by **hazard**, not feed. `level` (base band) and `score` (`base_signal + boost.applied`,
gates `major`) stay separate.
- `MAJOR_CUTOFF = 60.0`; `is_major(score: float) -> bool` is hazard-agnostic (`score >= 60`).
- `severity_level(mag, sig, alert)` **frozen** as the EQ level path.
- **EQ `base_signal` = max of three arms:** `mag_arm = clamp(mag/5.5·60, 0, 100)`,
  `sig_arm = clamp((sig or 0)·0.1, 0, 100)`,
  `alert_arm = {None:0, green:60, yellow:70, orange:85, red:100}`. Constructed so
  **`base_signal ≥ 60 ⇔ old is_major(mag≥5.5 OR sig≥600 OR alert≠null)`** — a *provable* EQ
  regression that preserves the v1 "green EQ → major" quirk.
- **GDACS non-EQ:** `base = colour_base[alert] + clamp(alert_score, 0, 3)·3.0` with
  `colour_base = {green:45, yellow:55, orange:75, red:90}` and
  `colour_level = {green:minor, yellow:moderate, orange:serious, red:severe}`. Green (45–54) < 60
  → not major (hidden by default, ADR 0003); orange/red major. The `[0,3]` clamp means
  `alert_score` only refines ordering *within* a colour, never crosses a band boundary.
- Public entry points the builder calls: `base_signal(hazard, inputs)` and
  `level_for(hazard, inputs)`.

### 7.4 Cross-feed dedup & merge — `dedup.py` + `merge.py`
Runs **after** same-feed union, **before** severity/boost, so the merged record is the sole gate
driver (ADR 0005).
- `union_by_id` re-keyed on `(feed, source_id)`.
- `cross_feed_clusters(events)` = **union-find** over a boolean `same_event(a, b)`, O(n²) —
  input-order-independent (determinism).
- **Three tiers, first hit wins:**
  1. both `glide` non-empty & equal (normalized) **AND** same hazard;
  2. `external_ids` intersection non-empty;
  3. `hazard == "EQ"` **AND** `great_circle_km ≤ MAX_MERGE_KM (100.0)` **AND**
     `|time_a − time_b| ≤ MERGE_TIME_WINDOW_MIN (60)`. **Tier 3 is EQ-only** (GDACS is the sole
     feed for TC/FL/VO/DR — nothing to cross-merge, and a large flood legitimately spans >100 km).
- **Tier 2 is opportunistic only.** EVENTS4APP exposes the agency string `"NEIC"`, not the NEIC
  event id, so the real USGS↔GDACS EQ join is tier-3 geo+time. We do **not** build GDACS-side
  NEIC-id extraction, nor a test asserting tier 2 fires.
- **`merge_cluster(members) -> MergedEvent`:** canonical `id`/`sources` order via
  `FEED_PRIORITY = ('usgs','gdacs')` (USGS-present keeps its v1 id — no churn). Field preference:
  `magnitude, geometry, time, title, place, sig ← USGS`; `alert, alert_score, affected_* ← GDACS`;
  `provisional ← USGS status when USGS present, else GDACS istemporary == 'true'` (preserves
  Slice-1 continuity). All source links retained. Same-feed tie within a cluster → max `updated`,
  then lexicographic `source_id`.
- `event_from_merged(m)` (replaces `event_from_quake`) computes severity/boost/score/major on the
  reconciled record.
- **Ordering has one home (the pipeline):** `build.py` sorts `(severity.score desc, time desc,
  id asc)`. No layer-2 embeddings, no embedding key.

### 7.5 Affected estimate — `affected.py` + `api/contract.py`
The number is **GDACS's own, carried verbatim** — never recomputed (ADR 0007).
- **List feed carries no population** (verified live); exposure lives in the per-event **detail**
  feed (`geteventdata`). EQ = `earthquakedetails.rapidpop` + `rapidpopdescription` (API-verified).
- **All five hazards investigated (locked decision #6).** During implementation, capture a detail
  fixture per hazard (EQ/TC/FL/VO/DR) and pin the exposure field name for each. Ship a **real**
  number wherever GDACS publishes an exposure/exposed-population figure; where a hazard genuinely
  has none, emit `estimate: null` + a **documented per-hazard reason** — never a fabricated or
  derived number (ADR 0007). The per-hazard field map is recorded in `feeds/gdacs.md`.
- **Two-phase fetch in `api/contract.py`** (the only network layer): phase-1 list fetch → light
  parse to find **Orange/Red** GDACS `eventid`s (the only ones that can clear the `major` gate and
  be displayed) → phase-2 bounded per-event detail GETs → pass a `{eventid: detail}` map into
  `build_contract`. Any detail failure degrades to `estimate: null` + reason — never crashes or
  blocks the build.
- **`affected_block(population, basis_text) -> dict`** (pure): non-null →
  `{estimate, basis: <GDACS text>, source: "gdacs"}`; null →
  `{estimate: null, basis: <reason>, source: null}`. Does **not** gate: `score`/`major` stay
  boost-driven, so population is never double-counted.
- **Merge survival:** the GDACS cluster member supplies `affected`; USGS-only clusters →
  `estimate: null`.

## 8. Front end — sole read-only consumer

Regenerate `web/lib/contract.types.ts` from the v2 schema (never hand-edit).
- **Loud schema guard** (`contract.ts`): `EXPECTED_SCHEMA_VERSION = "2.0.0"`; after parse,
  `throw new Error("contract schema mismatch: expected 2.0.0, got " + data.schema_version)` on
  inequality — surfaces in the existing page error state. (No full runtime validator; out of
  scope.)
- **Markers** (`CrisisMap.tsx`): `CircleMarker → Marker` backed by `L.divIcon` HTML badge
  (SSR-safe, no image assets). Four channels: **colour = `severityColor(level)`**,
  **size = `markerRadius(score)`** = `clamp(4, round(4 + score·0.18), 22)` (handles
  `magnitude: null`), **glyph = 2-letter hazard code**, **ring = selection**.
- **`MapLegend.tsx` (new):** HTML overlay in `.map-pane` (SSR-safe, testable) — 5 hazard
  code→label rows, 4 level colour swatches, "marker size ∝ newsworthiness score" note.
  Theme-aware. Closes deviation (d).
- **Ordering has one home:** the front end renders the contract array order **verbatim**;
  `defaultMajorEvents` filters `e.major` and preserves order (no client re-sort).
- **`EventList.tsx`:** rows in received order; hazard glyph prefix; show `severity.score`;
  **multi-source badge when `sources.length > 1`**.
- **`EventDetail.tsx`:** `hazardLabel(hazard)` (fallback to raw code); show `score` + a
  **"Why this ranks here" boost-audit block** (`nearest_place`, `distance_km`, `population`,
  `applied`; when `applied === 0` render "nearest population center: X (N km) — no boost
  applied"); render **magnitude only when non-null**; **iterate all `sources[]`** with
  `feedLabel(feed)` links + a multi-source indicator (replaces the `sources[0]`/"USGS source"
  hardcode).
- **Affected display (`formatAffected`):** `affected.estimate === null` → "Not estimated" +
  `basis` (muted, never a bare number); else "Est. population exposed ≈ 44K · GDACS" with the
  GDACS `basis`. Wording is **"population exposed," never "affected/casualties"** (ADR 0007 —
  `rapidpop` measures exposure).
- **Per-feed health copy (`page.tsx`):** outage banner from `downFeeds(contract)` + `feedLabel`,
  e.g. "USGS, GDACS unavailable — picture may be incomplete," `role="alert"` (replaces the
  hardcoded "USGS unavailable").
- **No BYOK key introduced or required** to render map/list/affected.

## 9. Testing plan — at the two existing highest seams

Mock only at the three network edges (feeds, Embedder, LLM Provider — the latter two untouched);
control the clock (fixed `NOW`; no time-relative dedup this slice).

### 9.1 Pipeline (`uv run pytest`) — fixtures in, v2 contract out
- **Hard USGS+GDACS duplicate (issue #5 DoD):** `usgs_all_day.json` (`us6000takd`) + new
  `gdacs_dup_of_usgs.json` (EQ, NEIC, Orange, coords ~`[142.03, 40.47]`, `fromdate` within
  minutes, empty glide) → `build_contract` yields **exactly one** event; `id == "usgs:us6000takd"`;
  `{s.feed} == {"usgs","gdacs"}`; `sources[0].feed == "usgs"`; `len(sources) == 2`; validates
  against v2. Field preference: `magnitude`/geometry from USGS, `inputs.alert == "orange"` from
  GDACS, `affected` from the GDACS member.
- **New units:** `test_gdacs_parser.py` (all five hazards, `[lon,lat]`, UTC parse, colour
  lowercase, glide, WF/malformed skipped); `test_boost.py` (haversine known pair, deterministic,
  `applied` monotonic in nearness & population, capital bonus, `applied == 0` beyond radius,
  dataset loads without network); dedup boundary + order-independence (>100 km / outside window /
  different hazard → no merge; `dedup(a,b) == dedup(b,a)`; GLIDE + geo+time paths; transitivity).
- **Severity:** keep the 14 EQ band rows verbatim; rewrite the 6 gate rows to assert
  `eq_base_signal(...) ≥ 60 ⇔ old is_major` truth table; add GDACS per-hazard band rows +
  `alert_score` clamp monotonicity; `is_major(59.999) == False`, `is_major(60.0) == True`.
- **EQ regression (`test_eq_regression.py`):** drive **only** USGS fixtures through the v2 build;
  assert `level/id/geometry/magnitude/provisional` identical to v1 and `major` identical for every
  event with `boost.applied == 0`. Plus `test_boost_never_changes_level`.
- **Build seam:** score-desc ordering (replaces newest-first); near-city event out-scores an
  equal-magnitude mid-ocean quake **and** emits all four `boost` inputs with `score == base +
  applied`; multi-hazard + null-magnitude event validates; `meta.feeds` carries all three rows;
  one-feed-down still emits the others.
- **Affected seam:** `gdacs_detail_eq_*.json` fixture → `affected == {estimate: 43996,
  basis contains "MMI IV", source: "gdacs"}`; no-exposure detail → `estimate: null, source: null`
  + reason basis; USGS-only → null. Add a captured detail fixture + assertion per non-EQ hazard
  that GDACS quantifies.
- **API route:** `httpx.MockTransport` branches both USGS URLs + GDACS EVENTS4APP + the **detail**
  endpoint; add a GDACS-down case (503 → `gdacs status = "error"`, USGS ok, events still present).

### 9.2 Front end (`pnpm test`, Vitest + RTL) — v2 fixture in, render out
- `contract.test.ts`: a 2.0.0 body parses; a **1.0.0 body rejects** `/schema mismatch/`.
- `presentation.test.ts`: `markerRadius` monotonic in score, floor 4, handles null magnitude;
  `hazardLabel` 5 distinct; `defaultMajorEvents` preserves contract score-desc order & all major;
  `downFeeds(feed-down) === ["gdacs"]`; `formatAffected` GDACS-tagged string vs "Not estimated".
- Components: `CrisisMap` (per-hazard glyph, colour by level, size by score, ring, `onSelect`);
  `EventList` (glyph per row, multi-source badge only on merged event); `EventDetail` (human
  hazard label, score + boost block, both source links, affected with provenance/uncertainty,
  magnitude shown for EQ / hidden for TC, null-boost line doesn't crash); `MapLegend`; `page`
  (per-feed banner, legend present, no-key render).

### 9.3 Shared fixture re-baseline (one commit)
Author **one** `contract.v2.example.json` = **4 events, 3 major**: (1) `usgs:us6000severe` M7.1
severe USGS-only, `affected.estimate: null`; (2) `usgs:us6000serious` M6.0 **merged** usgs+gdacs,
`affected` set; (3) `gdacs:1550421` TC orange major, `magnitude: null`, `affected` set;
(4) `usgs:us6000minor` M3.2 non-major, `applied: 0`, affected null. This moves the hardcoded major
count **2 → 3**; re-baseline together: `page.test` button count + map `data-count`,
`presentation.test` `defaultMajorEvents` length, `CrisisMap` markers length, `contract.test`
events length (3 → 4).

## 10. Deviations & ADR bookkeeping (`implementation-notes.md`)

1. **ADR 0003 boost gap CLOSED.** The newsworthiness boost was accepted "from v1" but was
   **absent & unlogged** in Slice 1; v2 lands `severity.score` + auditable `severity.boost`.
   ADR 0003 is now *honored*, not changed — no superseding ADR needed.
2. **Deviation (d) hazard glyph CLOSED.** Deferred "until a second hazard type is ingested"; now
   true — glyph + legend added.
3. **New — GDACS detail fetch for `affected`.** Departs from list-only ingest; reason: EVENTS4APP
   carries no population, detail (`geteventdata`) is the only grounded source. Bounded to
   Orange/Red events; per-hazard physical `metrics` object still deferred.
4. **New — `severity.inputs` reshaped** (gained `alert_score`, `mag` now nullable) under the
   2.0.0 bump; EQ identity is **semantic** (level/major/input values), not literal byte-identity.
5. **New — top-level `magnitude` now `number|null`** (present-always) rather than EQ-only
   required-number.
6. **Contained tension logged — v1 "green EQ → major" quirk preserved** for EQ regression, which
   conflicts with ADR 0003's "hide green" for GDACS-sourced green colours reaching the EQ path.
   **If kept long-term it needs a superseding ADR;** this slice only logs it and revisits under
   ADR 0003 tuning.
7. **New — canonical `id` can churn `gdacs: → usgs:`** if a GDACS-only event later gains a USGS
   match (revisions/history out of scope this slice).
8. **Update `feeds/gdacs.md`** to document the detail-feed population fields (per hazard) — the
   truncated sample wrongly implies population is in the list feed.

No existing ADR is rewritten. ADRs 0005/0006/0007 are respected as-is.

## 11. Adopted tuning defaults (flagged tunable, ADR 0003)

`MAJOR_CUTOFF = 60.0`; boost `MAX_BOOST = 15`, `CAPITAL_BONUS = 5`, `BOOST_CAP = 20`,
`BOOST_RADIUS_KM = 300`; GDACS `colour_base = {green:45, yellow:55, orange:75, red:90}`;
dedup `MAX_MERGE_KM = 100`, `MERGE_TIME_WINDOW_MIN = 60`; detail fetch bounded to Orange/Red.
All named constants, tuned against real feed volume in a later pass — not pre-tuned here.
