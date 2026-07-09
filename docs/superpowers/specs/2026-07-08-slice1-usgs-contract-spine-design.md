# Slice 1 — USGS earthquakes end-to-end (feed → contract → map)

- **Status:** Approved (design), pre-implementation
- **Date:** 2026-07-08
- **Feature:** GitHub issue #3 (Slice 1), under PRD #2
- **Authoritative constraints:** ADR 0003 (severity/major), 0005 (two-layer dedup), 0006
  (stack & hosting / the JSON contract), 0007 (client-side BYOK AI); `CLAUDE.md` conventions.

## 1. Goal

A hosted, read-only page shows current **major USGS earthquakes** on a world map, driven end
to end by a **versioned JSON contract**. Slice 1 exists to **define and freeze contract v1 —
the single seam** — and prove both halves can be built (TDD) against it independently. It is
the walking skeleton for the whole system.

### In scope
- USGS ingest: `all_day` (live picture) **and** `significant_week` (context).
- Emit **JSON contract v1**: `schema_version`, `generated_at`, canonical EQ events (identity,
  hazard, geometry, time, Severity + inputs, `major`, `provisional`, source link), and minimal
  per-feed health `meta`.
- Severity + `major` gate per ADR 0003 (base signal only — **no** newsworthiness boost).
- Same-source **union-by-id** dedup across the two windows (the degenerate dedup case).
- Front end (Next.js + react-leaflet + OSM): markers (colour = Severity, icon = hazard, size =
  magnitude) + right-hand event list, synced selection, click → detail card, provisional badge.
- Renders fully **with no key**.
- Tests at the seam: `pytest` (feed fixtures → contract) and `vitest`+RTL (contract fixture →
  render).

### Out of scope (per issue #3)
Newsworthiness boost / ranking (Slice 2); GDACS / ReliefWeb; cross-feed dedup; affected
estimate; revisions / history / active-window; analytics; morning report; AI / insights;
scheduling / change-detection gate; user-facing filters & "show all" toggle. Live Vercel
deploy is a **fast-follow**, not part of the DoD (see §8).

## 2. Fulcrum decisions (approved)

1. **Contract form — JSON Schema is the source of truth.** A committed
   `contract.v1.schema.json` *is* the contract (matches `CLAUDE.md`: "the contract schema is
   the shared artefact" + the "bump schema version on breaking change" rule). The pipeline's
   output is validated against it in tests; the front end's TS types are generated from it.
   A golden fixture instance is loaded by both suites.
2. **Layout + runtime wiring — three dirs + a live serverless route.** `contract/` +
   `pipeline/` (pure core + a thin Vercel Python `/api/contract` route) + `web/` (Next.js
   reading `/api/contract`). This is ADR 0006's on-demand refresh route at minimum size, minus
   the gate/cache/state. The pure core stays off-network, so the TDD seam is unaffected.
3. **"Done" = local e2e + green tests.** Both suites green, pure core + `/api/contract` +
   page wired and running locally against live USGS, schema + fixtures committed. Actual
   Vercel deploy is an immediate fast-follow.

## 3. Contract v1 (the seam)

### 3.1 Golden instance (fixture shape)

```jsonc
{
  "schema_version": "1.0.0",
  "generated_at": "2026-07-08T12:00:00Z",    // server clock at build time (injected → fixed in tests)
  "meta": {
    "feeds": [
      { "source": "usgs", "window": "all_day",         "status": "ok", "fetched_at": "2026-07-08T12:00:00Z", "event_count": 214 },
      { "source": "usgs", "window": "significant_week", "status": "ok", "fetched_at": "2026-07-08T12:00:00Z", "event_count": 11 }
    ]
  },
  "events": [
    {
      "id": "usgs:us6000tafd",               // canonical id = "<feed>:<sourceId>" (1:1 this slice)
      "hazard": "EQ",
      "title": "M 6.4 - 25 km SSW of Foo",
      "place": "25 km SSW of Foo",           // detail-card 'location'
      "time": "2026-07-08T03:14:07Z",        // origin time (USGS epoch-ms → ISO-UTC)
      "geometry": { "lat": -19.1, "lon": -70.9, "depth_km": 34.2 },
      "magnitude": 6.4,                      // display + marker size
      "severity": {
        "level": "severe",                   // ordinal → marker colour
        "inputs": { "mag": 6.4, "sig": 631, "alert": "orange" }
      },
      "major": true,                         // gate: mag≥5.5 OR sig≥600 OR alert≠null
      "provisional": false,                  // USGS status == "automatic"
      "sources": [
        { "feed": "usgs", "id": "us6000tafd", "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us6000tafd" }
      ]
    }
  ]
}
```

### 3.2 Schema field reference (what `contract.v1.schema.json` encodes — JSON Schema draft 2020-12)

Top level — required: `schema_version`, `generated_at`, `meta`, `events`.
- `schema_version`: string, `const "1.0.0"`.
- `generated_at`: string, `format: date-time` (UTC).
- `meta`: object, required `feeds`.
  - `feeds`: array of feed-health objects.
    - `source`: enum `["usgs"]`.
    - `window`: enum `["all_day", "significant_week"]`.
    - `status`: enum `["ok", "error"]`.
    - `fetched_at`: date-time.
    - `event_count`: integer ≥ 0.
    - `error`: string (present only when `status == "error"`).
- `events`: array of event objects.
  - required: `id`, `hazard`, `title`, `place`, `time`, `geometry`, `magnitude`, `severity`,
    `major`, `provisional`, `sources`.
  - `id`: string, pattern `^[a-z]+:.+` (Slice 1 always `usgs:…`).
  - `hazard`: enum `["EQ"]`.
  - `title`, `place`: string.
  - `time`: date-time (UTC).
  - `geometry`: object, required `lat`, `lon`; `lat` number [−90, 90]; `lon` number
    [−180, 180]; `depth_km` number or null.
  - `magnitude`: number.
  - `severity`: object, required `level`, `inputs`.
    - `level`: enum `["minor", "moderate", "serious", "severe"]`.
    - `inputs`: object — `mag` number; `sig` integer or null; `alert` enum
      `["green","yellow","orange","red"]` or null.
  - `major`: boolean.
  - `provisional`: boolean.
  - `sources`: array, `minItems: 1`, of `{ feed: enum ["usgs"], id: string, url: string
    (format uri) }`.

`additionalProperties: false` on every object, so drift is caught structurally.

### 3.3 Severity band (initial, tunable — ADR 0003 says these tune against real feed volume during Slice 1)

First match wins, evaluated high → low:

| `level`    | marker colour | EQ rule                                             |
|------------|---------------|----------------------------------------------------|
| `severe`   | red           | `alert` ∈ {orange, red} OR mag ≥ 7.0 OR sig ≥ 1000  |
| `serious`  | orange        | `alert` == yellow OR mag ≥ 6.0 OR sig ≥ 600         |
| `moderate` | amber         | mag ≥ 4.5 OR sig ≥ 300                              |
| `minor`    | grey/green    | otherwise                                          |

### 3.4 `major` gate (ADR 0003 — computed independently of `level`)

`major = (mag ≥ 5.5) OR (sig ≥ 600) OR (alert is not null)`. Kept a separate boolean so the
gate (default-view membership) and the measure (`level`, colour) stay decoupled.

### 3.5 Contract semantics (approved calls)
- **Canonical id** = `"<feed>:<sourceId>"`; 1:1 this slice (no cross-feed dedup).
- **Union-by-id across windows.** `all_day` and `significant_week` overlap; a recent
  significant quake appears in both. Merge by USGS `id`, preferring the record with the higher
  `updated`. This is the degenerate case of the dedup layer — in scope and necessary; it is
  *not* the cross-feed dedup that is out of scope.
- **Carry every quake.** Below-threshold (non-`major`) events are present in the contract,
  flagged `major:false`; the front end renders `major:true` by default. Minors ride along for
  forward-compat even though the "show all" toggle is Slice 2. The contract is full-fidelity
  from day one.
- **`magnitude` appears twice** — top level (display/size) and in `severity.inputs.mag`
  (provenance). Intentional; honors "Severity + its inputs".
- **All times ISO-8601 UTC.**
- **Defensive skip:** a feature missing `mag` or coordinates is skipped, not emitted; it never
  crashes the whole contract.

## 4. Architecture — three units, joined only by `contract/`

No shared runtime code crosses the seam (ADR 0006). Directory layout:

```
contract/
  schema/contract.v1.schema.json     ← THE seam
  fixtures/
    contract.v1.example.json         ← golden instance (front-end renders this)
    contract.v1.no-major.json        ← quiet cycle (degradation)
    contract.v1.feed-down.json       ← USGS unavailable
pipeline/            (Python 3.12 · uv · ruff · mypy · httpx)
  pipeline/feeds/usgs.py             ← USGS GeoJSON → normalized EQ records (separate & swappable)
  pipeline/severity.py               ← severity band + major gate (pure functions)
  pipeline/dedup.py                  ← same-source union-by-id
  pipeline/contract.py               ← assemble records → contract dict; owns schema_version
  pipeline/models.py                 ← Pydantic mirror of the schema; validated against schema in tests
  pipeline/build.py                  ← build_contract(all_day, significant_week, now) -> dict  (pure)
  api/contract.py                    ← Vercel Python fn: fetch USGS (httpx) → build_contract → JSON
  tests/                             ← feed fixtures in → assert contract out
web/                 (Node pinned · pnpm · Next.js App Router · TS strict · Tailwind + shadcn/ui)
  lib/contract.types.ts              ← generated from schema (pnpm gen:contract-types)
  lib/contract.ts                    ← loadContract() → GET /api/contract
  components/{CrisisMap,EventList,EventDetail,SeverityMarker,ProvisionalBadge}
  app/page.tsx                       ← map + right-hand list, synced selection
  tests/                             ← contract fixture in → assert render
```

**The pure core is the testable heart.** `build_contract(all_day_json, significant_week_json,
now) → dict` is deterministic, off-network, and takes an injected clock. `api/contract.py` is a
*thin* adapter (fetch both windows, call `build_contract`, serialize) — the only
network-touching code is that one small file. Keep the USGS parser separate and swappable so a
later feed is a contained addition.

## 5. Runtime data flow

Browser → `GET /api/contract` → httpx fetches USGS `all_day` + `significant_week` → parse →
union-by-id → severity / major / provisional per event → assemble contract v1 (`generated_at`
= server clock; `meta.feeds` health) → JSON → `loadContract()` → render map + list + detail.
No key is involved anywhere (AI is out of scope), so "renders with no key" holds by
construction; the front-end test still asserts it explicitly.

## 6. Error handling (no state store this slice → no "last-good")

- **Per-window fetch failure** → that entry `status:"error"` (+ `error` message) in
  `meta.feeds`, its events dropped; the other window still emits. **Both fail** → `events: []`,
  both flagged error; the page shows "USGS unavailable — picture may be incomplete" and still
  renders an empty map (graceful degradation, PRD #40).
- **Malformed feature** (missing `mag`/coordinates) → skipped defensively; the rest of the
  contract is unaffected.
- **Emit that fails schema validation** = a bug → tests fail loudly; at runtime the route 500s
  with a clear error (fail-loud, PRD #46). No silent stale data (there is no stored data to go
  stale this slice).

## 7. Testing — the schema is the shared oracle

Per `CLAUDE.md`: test external behaviour at the highest seam; mock only network edges; control
(don't mock) the clock; never test private internals.

- **Pipeline — `uv run pytest`.** Real saved `all_day` + `significant_week` samples →
  `build_contract` → assert the output **validates against `contract.v1.schema.json`** and has
  the expected events / flags / severity / dedup. Fixed clock injected. Mock nothing except
  `httpx` in one thin `api/contract.py` route test. Negative fixtures: window overlap-dup,
  feed-down (per-window and both), malformed feature.
- **Front end — `pnpm test` (Vitest + RTL).** Load `contract/fixtures/*.json` → render → assert
  markers / list / detail, **major-only default view**, provisional badge, severity colour, and
  **renders with no key**. Mock only the `/api/contract` fetch. Leaflet needs DOM (jsdom); the
  map component is stubbed to assert the props it receives (colour/size/position/selection).
- **No type drift by construction:** front-end types are *generated from* the same schema the
  pipeline output is *validated against*.

## 8. Build order — the orchestrator payoff of schema-first

1. **Freeze the seam** (one focused pass): write `contract.v1.schema.json` + the three golden
   fixtures + saved real USGS feed samples. Commit. This is the only true dependency.
2. **Fan out, isolated** — two agents in separate git worktrees, each doing superpowers TDD,
   each binding **only** to `contract/`, so they cannot collide:
   - **A — pipeline:** red-green `build_contract` from feed fixtures against the frozen schema,
     then the thin `/api/contract` route (httpx mocked).
   - **B — front end:** generate types from schema, then red-green components from the golden
     fixture.
3. **Integrate & verify e2e locally** — run the real route against live USGS, load the page,
   confirm the map renders (verification-before-completion + the `verify` skill).
4. **Vercel deploy** — fast-follow, out of Slice 1 DoD.

## 9. Deviations to log (`implementation-notes.md`, per CLAUDE.md policy)

These are notes, not new ADRs (no architecture decision changes):
- (a) `meta.feeds` health added ahead of the gate/analytics slices (forward-compat seam).
- (b) Below-threshold events carried in the contract before the "show all" filter exists
  (forward-compat seam).
- (c) Issue #3's DoD says "hosted"; by explicit decision the live Vercel deploy is a
  fast-follow and Slice 1's DoD is local e2e + green tests (§2.3, §8). Narrows the issue's
  wording, not the architecture (ADR 0006 still stands).
- (d) Markers carry no hazard glyph (spec §7 lists `icon = hazard`); with a single hazard
  type (EQ) the icon conveys nothing, so it is deferred until a second hazard exists —
  forward-compat narrowing, not an ADR change.

## 10. Tunable knobs / open items carried into implementation
- Severity band thresholds (§3.3) — tune against real `all_day` volume during the slice.
- Confirm USGS `alert` value space seen in live data matches the enum
  `{green, yellow, orange, red}` (nullable); widen the enum only if real data demands it.
- `all_day` payload size (hundreds of minor quakes carried) — confirmed acceptable for Slice 1;
  revisit only if it bloats the response noticeably.
