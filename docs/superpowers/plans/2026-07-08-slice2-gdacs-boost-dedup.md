# Slice 2 (Multi-Hazard + Newsworthiness + Cross-Feed Dedup) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add GDACS multi-hazard ingest, a deterministic newsworthiness boost, cross-feed dedup + merge, and a grounded affected-population estimate to the Global Crisis Dashboard, crossing to the front end through one breaking bump of the JSON contract to `2.0.0`.

**Architecture:** Two halves joined only by the versioned JSON contract (ADR 0006). The Python pipeline stays a pure, off-network core (`pipeline/pipeline/`) behind one thin network layer (`pipeline/api/contract.py`): ingest → same-feed union → deterministic cross-feed dedup + merge → per-hazard severity + newsworthiness boost + score → emit contract v2. The Next.js front end is the sole read-only consumer. A flat hazard-generic `NormalizedEvent` + a plain parser registry (Approach A) replaces the EQ-specific `NormalizedQuake`.

**Tech Stack:** Pipeline — Python 3.12, uv, ruff, mypy, httpx, pytest, jsonschema. Front end — Next.js App Router, TypeScript (strict), Tailwind + shadcn/ui, react-leaflet + OSM tiles, pnpm, Vitest + React Testing Library.

## Global Constraints

- **Determinism is model-free** (CLAUDE.md conv. 1; ADR 0005): boost, dedup, severity, and the `major` gate are pure and reproducible — no model calls, no `Math.random`/wall-clock reads in the pure core; the clock `now` is injected.
- **One contract boundary, one bump** (ADR 0006): a single `schema_version` bump to `"2.0.0"` across three coupled constants — the JSON Schema `const`, pipeline `SCHEMA_VERSION`, and web `EXPECTED_SCHEMA_VERSION` (with regenerated `contract.types.ts`). `contract.v1.schema.json` stays frozen.
- **`additionalProperties: false` on every schema object.** Enums: `hazard` ∈ [EQ,TC,FL,VO,DR]; `feed`/`source` ∈ [usgs,gdacs]; `meta` window adds `events4app`.
- **Grounded AI only** (ADR 0007): the affected number is GDACS’s own, carried **verbatim**, never computed/derived; uncertainty explicit; UI wording is “population exposed,” never “affected/casualties.” No server-side LLM/embedding key is introduced (embeddings deferred).
- **Pure core off-network:** only `pipeline/api/contract.py` performs I/O. Tests mock **only** the three network edges (feeds, Embedder, LLM Provider) and control the clock; never test private internals.
- **Front end renders fully with no BYOK key** (ADR 0007); TypeScript strict; the FE never re-sorts — ordering has one home (the pipeline).
- **Adopted tuning constants (named, tunable later per ADR 0003):** `MAJOR_CUTOFF=60.0`; boost `BOOST_RADIUS_KM=300`, `MAX_BOOST=15`, `CAPITAL_BONUS=5`, `BOOST_CAP=20`; GDACS `colour_base={green:45,yellow:55,orange:75,red:90}`; dedup `MAX_MERGE_KM=100`, `MERGE_TIME_WINDOW_MIN=60`; GDACS detail fetch bounded to Orange/Red events.
- **Tooling note:** pipeline tests run via `uv run pytest` (on this machine `uv` may not be on PATH — tasks show the full-path invocation); web tests via `pnpm test`. Never commit or print secrets (`.env` is gitignored).
- **Commits:** conventional, scoped `feat(slice-2)`/`test(slice-2)`/`refactor(slice-2)`/`chore(slice-2)`/`docs(slice-2)`, each ending with the trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

### Task 1: Contract v2 schema + version constants

**Files:**
- Create: `contract/schema/contract.v2.schema.json`
- Create: `pipeline/tests/test_contract_v2_schema.py`
- Modify: `pipeline/pipeline/contract.py`
- Test: `pipeline/tests/test_contract_v2_schema.py`

**Interfaces:**
- Consumes: none — this is the first task in the slice. It reuses only pre-existing artefacts it does not define: `pipeline/pipeline/contract.py` (existing module exporting `SCHEMA_VERSION`) and the `jsonschema.Draft202012Validator` / `jsonschema.ValidationError` API already used by `pipeline/tests/test_contract_schema.py`.
- Produces (for later tasks): `contract/schema/contract.v2.schema.json` — the frozen v2 shape (draft 2020-12, `$id https://hadr.example/contract.v2.schema.json`, `schema_version` const `"2.0.0"`), consumed by Tasks 10–14 (build/affected/API seam tests validate against it) and by Task 15 (web `contract.types.ts` regenerated from it). `SCHEMA_VERSION = "2.0.0"` in `pipeline/pipeline/contract.py`, consumed by Task 10's `event_from_merged`/`build_contract` emit.

Steps:

- [ ] **Step 1: Write the failing schema + constant test.**
  Create `pipeline/tests/test_contract_v2_schema.py` with the full contents below. It loads the (not-yet-existing) v2 schema, asserts it is valid draft 2020-12, validates a hand-authored minimal conforming instance, proves `additionalProperties:false` and the `schema_version` const bite, and asserts the pipeline constant is bumped. Style mirrors the existing `pipeline/tests/test_contract_schema.py` (same `CONTRACT` path idiom, `Draft202012Validator`).

  ```python
  import json
  from pathlib import Path

  import pytest
  from jsonschema import Draft202012Validator, ValidationError

  from pipeline.contract import SCHEMA_VERSION

  CONTRACT = Path(__file__).resolve().parents[2] / "contract"
  SCHEMA = CONTRACT / "schema" / "contract.v2.schema.json"


  def _schema() -> dict:
      return json.loads(SCHEMA.read_text(encoding="utf-8"))


  MINIMAL_V2 = {
      "schema_version": "2.0.0",
      "generated_at": "2026-07-08T12:00:00Z",
      "meta": {
          "feeds": [
              {
                  "source": "gdacs",
                  "window": "events4app",
                  "status": "ok",
                  "fetched_at": "2026-07-08T12:00:00Z",
                  "event_count": 1,
                  "error": None,
              }
          ]
      },
      "events": [
          {
              "id": "gdacs:1550421",
              "hazard": "TC",
              "title": "Tropical Cyclone Example",
              "place": "Off the coast",
              "time": "2026-07-08T06:00:00Z",
              "geometry": {"lat": 12.3, "lon": 45.6, "depth_km": None},
              "magnitude": None,
              "severity": {
                  "level": "serious",
                  "score": 78.0,
                  "inputs": {"mag": None, "sig": None, "alert": "orange", "alert_score": 1.5},
                  "boost": {
                      "nearest_place": None,
                      "population": None,
                      "distance_km": None,
                      "applied": 0.0,
                  },
              },
              "major": True,
              "provisional": False,
              "sources": [
                  {
                      "feed": "gdacs",
                      "id": "1550421",
                      "url": "https://www.gdacs.org/report.aspx?eventid=1550421",
                  }
              ],
              "affected": {"estimate": 43996, "basis": "40 thousand in MMI IV", "source": "gdacs"},
          }
      ],
  }


  def test_v2_schema_is_valid_draft_2020_12() -> None:
      Draft202012Validator.check_schema(_schema())


  def test_minimal_v2_instance_validates() -> None:
      Draft202012Validator(_schema()).validate(MINIMAL_V2)


  def test_schema_rejects_unknown_property_and_wrong_version() -> None:
      validator = Draft202012Validator(_schema())
      with pytest.raises(ValidationError):
          validator.validate({**MINIMAL_V2, "surprise": 1})
      with pytest.raises(ValidationError):
          validator.validate({**MINIMAL_V2, "schema_version": "1.0.0"})


  def test_pipeline_schema_version_is_bumped() -> None:
      assert SCHEMA_VERSION == "2.0.0"
  ```

- [ ] **Step 2: Run the test and confirm it FAILS.**
  Command (uv is not on PATH on this machine — invoke via its full path, from the `pipeline/` dir):
  ```
  cd pipeline
  & "C:\Users\ngwei\AppData\Roaming\Python\Python314\Scripts\uv.exe" run pytest tests/test_contract_v2_schema.py -q
  ```
  Expected: **FAIL — `4 failed, 0 passed`**. The three schema tests fail with `FileNotFoundError` (`contract.v2.schema.json` does not exist yet, raised inside `_schema()`); `test_pipeline_schema_version_is_bumped` fails with `AssertionError` (`SCHEMA_VERSION` is still `"1.0.0"`).

- [ ] **Step 3: Author the v2 schema.**
  Create `contract/schema/contract.v2.schema.json` with the full contents below — the single authoritative shape from spec §4 (widened `hazard` enum, `feed`/`source` enums, `events4app` window, `severity.score`/`severity.boost`, nullable `magnitude`, `affected` object; `additionalProperties:false` everywhere; `schema_version` const `"2.0.0"`). Leave `contract.v1.schema.json` untouched (frozen).

  ```json
  {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://hadr.example/contract.v2.schema.json",
    "title": "Contract",
    "type": "object",
    "additionalProperties": false,
    "required": ["schema_version", "generated_at", "meta", "events"],
    "properties": {
      "schema_version": { "const": "2.0.0" },
      "generated_at": { "type": "string", "format": "date-time" },
      "meta": {
        "type": "object",
        "additionalProperties": false,
        "required": ["feeds"],
        "properties": {
          "feeds": { "type": "array", "items": { "$ref": "#/$defs/FeedHealth" } }
        }
      },
      "events": { "type": "array", "items": { "$ref": "#/$defs/CrisisEvent" } }
    },
    "$defs": {
      "FeedHealth": {
        "title": "FeedHealth",
        "type": "object",
        "additionalProperties": false,
        "required": ["source", "window", "status", "fetched_at", "event_count"],
        "properties": {
          "source": { "type": "string", "enum": ["usgs", "gdacs"] },
          "window": { "type": "string", "enum": ["all_day", "significant_week", "events4app"] },
          "status": { "type": "string", "enum": ["ok", "error"] },
          "fetched_at": { "type": "string", "format": "date-time" },
          "event_count": { "type": "integer", "minimum": 0 },
          "error": { "type": ["string", "null"] }
        }
      },
      "Geometry": {
        "title": "Geometry",
        "type": "object",
        "additionalProperties": false,
        "required": ["lat", "lon"],
        "properties": {
          "lat": { "type": "number", "minimum": -90, "maximum": 90 },
          "lon": { "type": "number", "minimum": -180, "maximum": 180 },
          "depth_km": { "type": ["number", "null"] }
        }
      },
      "SeverityInputs": {
        "title": "SeverityInputs",
        "type": "object",
        "additionalProperties": false,
        "required": ["mag", "sig", "alert", "alert_score"],
        "properties": {
          "mag": { "type": ["number", "null"] },
          "sig": { "type": ["integer", "null"] },
          "alert": { "type": ["string", "null"], "enum": ["green", "yellow", "orange", "red", null] },
          "alert_score": { "type": ["number", "null"] }
        }
      },
      "SeverityBoost": {
        "title": "SeverityBoost",
        "type": "object",
        "additionalProperties": false,
        "required": ["nearest_place", "population", "distance_km", "applied"],
        "properties": {
          "nearest_place": { "type": ["string", "null"] },
          "population": { "type": ["integer", "null"] },
          "distance_km": { "type": ["number", "null"] },
          "applied": { "type": "number", "minimum": 0 }
        }
      },
      "Severity": {
        "title": "Severity",
        "type": "object",
        "additionalProperties": false,
        "required": ["level", "score", "inputs", "boost"],
        "properties": {
          "level": { "type": "string", "enum": ["minor", "moderate", "serious", "severe"] },
          "score": { "type": "number", "minimum": 0 },
          "inputs": { "$ref": "#/$defs/SeverityInputs" },
          "boost": { "$ref": "#/$defs/SeverityBoost" }
        }
      },
      "FeedSource": {
        "title": "FeedSource",
        "type": "object",
        "additionalProperties": false,
        "required": ["feed", "id", "url"],
        "properties": {
          "feed": { "type": "string", "enum": ["usgs", "gdacs"] },
          "id": { "type": "string" },
          "url": { "type": "string", "format": "uri" }
        }
      },
      "Affected": {
        "title": "Affected",
        "type": "object",
        "additionalProperties": false,
        "required": ["estimate", "basis", "source"],
        "properties": {
          "estimate": { "type": ["integer", "null"], "minimum": 0 },
          "basis": { "type": "string" },
          "source": { "type": ["string", "null"], "enum": ["gdacs", null] }
        }
      },
      "CrisisEvent": {
        "title": "CrisisEvent",
        "type": "object",
        "additionalProperties": false,
        "required": ["id", "hazard", "title", "place", "time", "geometry", "magnitude", "severity", "major", "provisional", "sources", "affected"],
        "properties": {
          "id": { "type": "string", "pattern": "^[a-z]+:.+" },
          "hazard": { "type": "string", "enum": ["EQ", "TC", "FL", "VO", "DR"] },
          "title": { "type": "string" },
          "place": { "type": "string" },
          "time": { "type": "string", "format": "date-time" },
          "geometry": { "$ref": "#/$defs/Geometry" },
          "magnitude": { "type": ["number", "null"] },
          "severity": { "$ref": "#/$defs/Severity" },
          "major": { "type": "boolean" },
          "provisional": { "type": "boolean" },
          "sources": { "type": "array", "minItems": 1, "items": { "$ref": "#/$defs/FeedSource" } },
          "affected": { "$ref": "#/$defs/Affected" }
        }
      }
    }
  }
  ```

- [ ] **Step 4: Bump the pipeline `SCHEMA_VERSION` constant.**
  In `pipeline/pipeline/contract.py`, change the one constant line (leave the imports and `event_from_quake` unchanged — the emit code is conformed in Task 10):
  - Before: `SCHEMA_VERSION = "1.0.0"`
  - After: `SCHEMA_VERSION = "2.0.0"`

- [ ] **Step 5: Run the test and confirm it PASSES.**
  ```
  cd pipeline
  & "C:\Users\ngwei\AppData\Roaming\Python\Python314\Scripts\uv.exe" run pytest tests/test_contract_v2_schema.py -q
  ```
  Expected: **PASS — `4 passed`**. `check_schema` accepts the v2 schema, the minimal instance validates, the unknown-property and `1.0.0` bodies raise `ValidationError`, and `SCHEMA_VERSION == "2.0.0"`.

- [ ] **Step 6: Commit.**
  ```
  git add contract/schema/contract.v2.schema.json pipeline/pipeline/contract.py pipeline/tests/test_contract_v2_schema.py
  git commit -m "feat(slice-2): add contract v2 schema and bump pipeline SCHEMA_VERSION to 2.0.0

  Author frozen contract.v2.schema.json (multi-hazard enum, feed/source
  enums, events4app window, severity.score + auditable severity.boost,
  nullable magnitude, affected block; additionalProperties:false throughout)
  and bump pipeline SCHEMA_VERSION. contract.v1.schema.json left frozen.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 2: NormalizedEvent model + USGS parser migration

**Files:**
- Modify: `pipeline/pipeline/models.py`
- Modify: `pipeline/pipeline/feeds/usgs.py`
- Test: `pipeline/tests/test_usgs_parser.py`

**Interfaces:**
- Consumes: nothing from earlier tasks — depends only on the stdlib (`dataclasses`, `datetime`) and the existing `parse_usgs` call shape. (`NormalizedQuake` is being superseded here.)
- Produces (for later tasks — signatures copied exactly from the INTERFACE CONTRACT):
  - `@dataclass(frozen=True) NormalizedEvent` in `models.py` with fields, in this order: `feed:str, source_id:str, hazard:str, title:str, place:str, time:datetime, updated:datetime, lat:float, lon:float, url:str, status:str, depth_km:float|None, mag:float|None, sig:int|None, alert:str|None, alert_score:float|None, glide:str|None, external_ids:frozenset[str], iso3:str|None, country:str|None, affected_population:int|None, affected_basis:str|None`. (Supersedes `NormalizedQuake`.)
  - `parse_usgs(feed_json: dict) -> list[NormalizedEvent]` in `feeds/usgs.py` — `feed="usgs"`, `hazard="EQ"`, `external_ids` parsed from `properties.ids`, all GDACS-only fields `None`.

> Scope note: `build.py`, `contract.py`, `dedup.py` (and `tests/test_dedup.py`) still import `NormalizedQuake` and will break — expected, fixed in later tasks. Every run command below is scoped to `tests/test_usgs_parser.py` so this task is independently green. All commands run from the `pipeline/` directory.

---

- [ ] **Step 1: Write the failing tests for the new model fields.**
  Append these two test functions to the end of `pipeline/tests/test_usgs_parser.py` (the existing 4 tests and the `_feature` helper stay exactly as-is — they touch only preserved field names and must remain green):

  ```python
  def test_sets_feed_hazard_and_gdacs_only_fields_none():
      q = parse_usgs({"features": [_feature(id="us1")]})[0]
      assert q.feed == "usgs"
      assert q.hazard == "EQ"
      # every GDACS-only signal is None for a USGS event
      assert q.alert_score is None
      assert q.glide is None
      assert q.iso3 is None
      assert q.country is None
      assert q.affected_population is None
      assert q.affected_basis is None


  def test_parses_external_ids_from_comma_delimited_ids_string():
      # USGS properties.ids is a comma-delimited string with leading/trailing commas
      populated = parse_usgs({"features": [_feature(id="us1", ids=",us1,us6000t9kz,")]})[0]
      assert populated.external_ids == frozenset({"us1", "us6000t9kz"})
      # absent `ids` property -> empty frozenset, never None
      bare = parse_usgs({"features": [_feature(id="us2")]})[0]
      assert bare.external_ids == frozenset()
  ```

- [ ] **Step 2: Run the new tests and confirm they FAIL.**
  Command: `uv run pytest tests/test_usgs_parser.py -q`
  Expected: exit non-zero, `2 failed, 4 passed`. The two new tests error with `AttributeError: 'NormalizedQuake' object has no attribute 'feed'` and `AttributeError: 'NormalizedQuake' object has no attribute 'external_ids'` (the old model lacks the new fields).

- [ ] **Step 3: Rename the model to `NormalizedEvent` with the flat hazard-generic superset.**
  Replace the entire contents of `pipeline/pipeline/models.py` with:

  ```python
  from dataclasses import dataclass
  from datetime import datetime


  @dataclass(frozen=True)
  class NormalizedEvent:
      """A single hazard event normalized from a feed, independent of any source's wire format.

      Flat, hazard-generic superset (supersedes NormalizedQuake). EQ-only signals
      (mag, sig, depth_km) are Optional and None for non-earthquake hazards; GDACS-only
      signals (alert_score, glide, iso3, country, affected_*) are None for USGS events.
      """

      feed: str
      source_id: str
      hazard: str
      title: str
      place: str
      time: datetime
      updated: datetime
      lat: float
      lon: float
      url: str
      status: str
      depth_km: float | None
      mag: float | None
      sig: int | None
      alert: str | None
      alert_score: float | None
      glide: str | None
      external_ids: frozenset[str]
      iso3: str | None
      country: str | None
      affected_population: int | None
      affected_basis: str | None
  ```

- [ ] **Step 4: Migrate `parse_usgs` to return `list[NormalizedEvent]`.**
  Replace the entire contents of `pipeline/pipeline/feeds/usgs.py` with the following. The defensive skips and every existing field value are preserved byte-for-byte; only the import, return type, the new `_parse_ids` helper, and the added fields (`feed`/`hazard`/`external_ids` + the `None` GDACS-only fields) change:

  ```python
  """USGS earthquake GeoJSON parser. Kept separate and swappable (one module per source)."""

  from datetime import datetime, timezone
  from typing import Any

  from pipeline.models import NormalizedEvent


  def _from_ms(ms: int | float) -> datetime:
      return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


  def _parse_ids(raw: str | None) -> frozenset[str]:
      """USGS `properties.ids` is a comma-delimited string with leading/trailing commas."""
      if not raw:
          return frozenset()
      return frozenset(tok for tok in raw.split(",") if tok)


  def parse_usgs(feed_json: dict[str, Any]) -> list[NormalizedEvent]:
      """Turn a USGS GeoJSON FeatureCollection into normalized events (hazard="EQ").

      Features missing magnitude, coordinates, an origin time, or an id are skipped
      defensively rather than crashing the whole parse.
      """
      out: list[NormalizedEvent] = []
      for feat in feed_json.get("features", []):
          props = feat.get("properties") or {}
          coords = (feat.get("geometry") or {}).get("coordinates") or []
          source_id = feat.get("id")
          mag = props.get("mag")
          time_ms = props.get("time")
          if not source_id or mag is None or time_ms is None or len(coords) < 2:
              continue
          if coords[0] is None or coords[1] is None:
              continue
          updated_ms = props.get("updated") or time_ms
          depth = coords[2] if len(coords) > 2 and coords[2] is not None else None
          out.append(
              NormalizedEvent(
                  feed="usgs",
                  source_id=str(source_id),
                  hazard="EQ",
                  title=props.get("title") or "",
                  place=props.get("place") or "",
                  time=_from_ms(time_ms),
                  updated=_from_ms(updated_ms),
                  lat=float(coords[1]),
                  lon=float(coords[0]),
                  url=props.get("url") or f"https://earthquake.usgs.gov/earthquakes/eventpage/{source_id}",
                  status=props.get("status") or "",
                  depth_km=float(depth) if depth is not None else None,
                  mag=float(mag),
                  sig=props.get("sig"),
                  alert=props.get("alert"),
                  alert_score=None,
                  glide=None,
                  external_ids=_parse_ids(props.get("ids")),
                  iso3=None,
                  country=None,
                  affected_population=None,
                  affected_basis=None,
              )
          )
      return out
  ```

- [ ] **Step 5: Run the parser tests and confirm they PASS.**
  Command: `uv run pytest tests/test_usgs_parser.py -q`
  Expected: exit 0, `6 passed`. (The 4 original assertions are unchanged and still green; the 2 new tests now find `feed`, `hazard`, `external_ids`, and the `None` GDACS-only fields.)

- [ ] **Step 6: Commit the model rename and parser migration.**
  Commands:
  ```bash
  git add pipeline/pipeline/models.py pipeline/pipeline/feeds/usgs.py pipeline/tests/test_usgs_parser.py
  git commit -m "refactor(slice-2): rename NormalizedQuake to NormalizedEvent, migrate USGS parser

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 3: Great-circle distance helper (`geo.py`)

**Files:**
- Create: `pipeline/pipeline/geo.py`
- Test: `pipeline/tests/test_geo.py`

**Interfaces:**
- Consumes: nothing from earlier tasks — stdlib `math` only (leaf module).
- Produces:
  - `EARTH_RADIUS_KM: float = 6371.0088` (module constant)
  - `great_circle_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float` — haversine great-circle distance in kilometres; pure, deterministic. Later consumed by `boost.py` (§7.2) and `dedup.py` tier-3 (`same_event`, §7.4).

- [ ] **Step 1: Write the failing test for `great_circle_km`.**
  Create `pipeline/tests/test_geo.py` with the full contents below (matches the existing flat-import, plain-`assert` style of `pipeline/tests/test_severity.py`). Covers a known city pair within 1 km (§7.1 example), the identity (same point → `0.0`), and argument-order symmetry (determinism — distance semantics must not drift):

  ```python
  from pipeline.geo import great_circle_km


  def test_known_city_pair_london_to_paris():
      # London (51.5074, -0.1278) -> Paris (48.8566, 2.3522) is ~343.5 km.
      dist = great_circle_km(51.5074, -0.1278, 48.8566, 2.3522)
      assert abs(dist - 343.5) < 1.0


  def test_identity_same_point_is_zero():
      assert great_circle_km(51.5074, -0.1278, 51.5074, -0.1278) == 0.0


  def test_symmetric_in_argument_order():
      ab = great_circle_km(51.5074, -0.1278, 48.8566, 2.3522)
      ba = great_circle_km(48.8566, 2.3522, 51.5074, -0.1278)
      assert ab == ba
  ```

- [ ] **Step 2: Run the test and confirm it FAILS.**
  From the `pipeline/` directory run:
  ```
  uv run pytest tests/test_geo.py -q
  ```
  Expected: collection error — `ModuleNotFoundError: No module named 'pipeline.geo'` (the module does not exist yet), reported as an error during collection, `0 passed`.

- [ ] **Step 3: Write the minimal implementation `geo.py`.**
  Create `pipeline/pipeline/geo.py` with the full contents below (module docstring in the same voice as `pipeline/pipeline/severity.py`; a named radius constant to match the codebase's named-constant convention; stdlib `math` only):

  ```python
  """Great-circle distance on a spherical Earth (haversine).

  Kept as one implementation, shared by the newsworthiness boost (§7.2) and the
  dedup tier-3 geo test (§7.4), so distance semantics can't drift between ranking
  and merging. Pure and deterministic; stdlib `math` only.
  """

  import math

  EARTH_RADIUS_KM = 6371.0088


  def great_circle_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
      phi1 = math.radians(lat1)
      phi2 = math.radians(lat2)
      dphi = math.radians(lat2 - lat1)
      dlambda = math.radians(lon2 - lon1)
      a = (
          math.sin(dphi / 2) ** 2
          + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
      )
      return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))
  ```

- [ ] **Step 4: Run the test and confirm it PASSES (and nothing regressed).**
  From the `pipeline/` directory run:
  ```
  uv run pytest tests/test_geo.py -q
  ```
  Expected: `3 passed`. Then confirm the module is clean and typed:
  ```
  uv run ruff check pipeline/geo.py && uv run mypy pipeline/geo.py
  ```
  Expected: ruff reports `All checks passed!` and mypy reports `Success: no issues found in 1 source file`.

- [ ] **Step 5: Commit.**
  From the repo root run:
  ```
  git add pipeline/pipeline/geo.py pipeline/tests/test_geo.py
  git commit -m "feat(slice-2): great-circle distance helper (geo.py)

  Haversine great_circle_km(lat1,lon1,lat2,lon2) -> float, R=6371.0088,
  stdlib math only. Shared by the newsworthiness boost and dedup tier-3
  so distance semantics stay single-sourced (spec §7.1).

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```
  Expected: one commit created touching exactly `pipeline/pipeline/geo.py` and `pipeline/tests/test_geo.py`.

---

### Task 4: Newsworthiness boost + committed cities dataset (`boost.py`)

**Files:**
- Create: `pipeline/pipeline/data/cities.csv` (committed, trimmed GeoNames dataset)
- Create: `pipeline/pipeline/data/NOTICE.md` (CC BY 4.0 provenance + exact trim recipe)
- Create: `pipeline/pipeline/boost.py`
- Test: `pipeline/tests/test_boost.py`

**Interfaces:**
- Consumes: `great_circle_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float` from `pipeline/pipeline/geo.py` (Task 3).
- Produces:
  - Constants in `boost.py`: `BOOST_RADIUS_KM: float = 300.0`, `MAX_BOOST: float = 15.0`, `CAPITAL_BONUS: float = 5.0`, `BOOST_CAP: float = 20.0`.
  - `compute_boost(lat: float, lon: float) -> dict[str, Any]` returning keys `{"nearest_place": str|None, "population": int|None, "distance_km": float|None, "applied": float}` — copied verbatim into `severity.boost` by `contract.event_from_merged` (Task 10).
  - Internal (not part of the contract): `_load_cities() -> tuple[_City, ...]` (`lru_cache`d, `__file__`-relative).

Notes for the executor: all `pytest`/`ruff`/`mypy`/build commands run from `C:\Users\ngwei\OneDrive\Desktop\Workbench\hadr-starter\pipeline`; all `git` commands run from `C:\Users\ngwei\OneDrive\Desktop\Workbench\hadr-starter`. Per the local-toolchain-quirks memory, `uv` is not on PATH — invoke it via its full path `C:\Users\ngwei\AppData\Roaming\Python\Python314\Scripts\uv.exe`. `geo.py` (Task 3) must already exist. The dataset is a committed input **asset**; TDD applies to `boost.py` (the code under test), so the asset is built first.

- [ ] **Step 1: Build the committed `cities.csv` from GeoNames (one-off, network only at build time).**
  Write this throwaway builder to the scratchpad (it is NOT committed — its recipe lives in `NOTICE.md`):

  File `C:\Users\ngwei\AppData\Local\Temp\claude\C--Users-ngwei-OneDrive-Desktop-Workbench-hadr-starter\c66e5d5e-dd0e-45b3-a8ea-31d75060673c\scratchpad\build_cities.py`:
  ```python
  """One-off builder for pipeline/pipeline/data/cities.csv (NOT committed).

  Downloads GeoNames cities15000, filters to population >= 100000 OR national capitals
  (feature_code == "PPLC"), and writes the six-column committed dataset. See
  pipeline/pipeline/data/NOTICE.md for the license and the reproducible recipe.
  """

  import csv
  import io
  import urllib.request
  import zipfile
  from pathlib import Path

  URL = "https://download.geonames.org/export/dump/cities15000.zip"
  OUT = Path(
      r"C:\Users\ngwei\OneDrive\Desktop\Workbench\hadr-starter\pipeline\pipeline\data\cities.csv"
  )


  def main() -> None:
      OUT.parent.mkdir(parents=True, exist_ok=True)
      raw = urllib.request.urlopen(URL, timeout=180).read()  # noqa: S310 (trusted GeoNames host)
      with zipfile.ZipFile(io.BytesIO(raw)) as zf:
          text = zf.read("cities15000.txt").decode("utf-8")

      rows: list[tuple[str, str, str, str, str, str]] = []
      for line in text.splitlines():
          f = line.split("\t")
          if len(f) < 19:
              continue
          asciiname, lat, lon = f[2], f[4], f[5]
          feature_code, country = f[7], f[8]
          population = int(f[14] or "0")
          is_capital = feature_code == "PPLC"
          if population >= 100000 or is_capital:
              rows.append(
                  (asciiname, country, lat, lon, str(population), "1" if is_capital else "0")
              )

      rows.sort(key=lambda r: (r[0], r[1]))  # stable, diff-friendly committed file
      with OUT.open("w", encoding="utf-8", newline="") as fh:
          w = csv.writer(fh)
          w.writerow(["name", "country", "lat", "lon", "population", "capital"])
          w.writerows(rows)
      print(f"wrote {len(rows)} rows -> {OUT}")


  if __name__ == "__main__":
      main()
  ```
  Run it (uses the pinned 3.12 venv's interpreter, stdlib only):
  ```
  C:\Users\ngwei\AppData\Roaming\Python\Python314\Scripts\uv.exe run python "C:\Users\ngwei\AppData\Local\Temp\claude\C--Users-ngwei-OneDrive-Desktop-Workbench-hadr-starter\c66e5d5e-dd0e-45b3-a8ea-31d75060673c\scratchpad\build_cities.py"
  ```
  Expected output: `wrote NNNN rows -> ...\cities.csv` where NNNN is roughly 4,000–5,000, and the file `pipeline/pipeline/data/cities.csv` now exists (~300 KB) with header `name,country,lat,lon,population,capital`.

- [ ] **Step 2: Record provenance, license, and the exact trim recipe in `NOTICE.md`.**
  Create `pipeline/pipeline/data/NOTICE.md`:
  ```markdown
  # cities.csv — provenance & license

  `cities.csv` is a trimmed, column-reduced extract of the **GeoNames** `cities15000` gazetteer.

  - **Source:** https://download.geonames.org/export/dump/cities15000.zip
    (all populated places with population ≥ 15,000; one tab-separated file `cities15000.txt`).
  - **License:** Creative Commons Attribution 4.0 (**CC BY 4.0**) —
    https://creativecommons.org/licenses/by/4.0/. © GeoNames (https://www.geonames.org/).
    This project redistributes a filtered, column-reduced extract under the same license;
    attribution is retained here.

  ## Trim recipe (exactly reproducible)

  From `cities15000.txt` (19 tab-separated GeoNames columns, no header line):

  1. Keep a row when **population (col 14) ≥ 100000 OR feature_code (col 7) == "PPLC"**
     (PPLC = national capital).
  2. Emit six columns: `name` (asciiname, col 2), `country` (country code, col 8),
     `lat` (col 4), `lon` (col 5), `population` (col 14),
     `capital` (`1` when feature_code == "PPLC", else `0`).
  3. Sort rows by `(name, country)` for a stable, diff-friendly file; prepend the header row.

  Produced by the one-off builder in the Slice-2 plan (Task 4, Step 1). No runtime code
  downloads GeoNames — `boost.py` reads only this committed file, so the boost stays
  deterministic and offline (CLAUDE.md conv. 1; spec §7.2).
  ```

- [ ] **Step 3: Commit the committed dataset asset.**
  ```
  git add pipeline/pipeline/data/cities.csv pipeline/pipeline/data/NOTICE.md
  git commit -m "chore(slice-2): commit trimmed GeoNames cities dataset for newsworthiness boost" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```
  Expected: one commit created adding two files under `pipeline/pipeline/data/`.

- [ ] **Step 4: Write the failing test file (full).**
  Create `pipeline/tests/test_boost.py`:
  ```python
  import csv
  from pathlib import Path

  from pipeline import boost
  from pipeline.boost import BOOST_CAP, BOOST_RADIUS_KM, compute_boost

  DATA_CSV = Path(boost.__file__).parent / "data" / "cities.csv"


  def _rows() -> list[dict[str, str]]:
      with DATA_CSV.open(encoding="utf-8", newline="") as fh:
          return list(csv.DictReader(fh))


  def test_dataset_is_committed_and_loads_locally():
      assert DATA_CSV.exists()
      rows = _rows()
      assert list(rows[0].keys()) == ["name", "country", "lat", "lon", "population", "capital"]
      assert len(rows) > 1000  # trimmed cities15000 is still thousands of rows
      # A valid result with only this committed file present proves compute_boost works offline.
      result = compute_boost(0.0, 0.0)
      assert set(result) == {"nearest_place", "population", "distance_km", "applied"}


  def test_near_capital_gets_high_boost():
      caps = [r for r in _rows() if r["capital"] == "1"]
      top = max(caps, key=lambda r: int(r["population"]))
      b = compute_boost(float(top["lat"]), float(top["lon"]))
      assert b["nearest_place"] == top["name"]
      assert b["population"] == int(top["population"])
      assert b["distance_km"] == 0.0
      assert 18.0 <= b["applied"] <= BOOST_CAP


  def test_remote_point_zero_boost_but_nearest_still_populated():
      # Point Nemo — oceanic pole of inaccessibility, thousands of km from any city.
      b = compute_boost(-48.876667, -123.393333)
      assert b["applied"] == 0.0
      assert isinstance(b["nearest_place"], str) and b["nearest_place"]
      assert isinstance(b["population"], int)
      assert isinstance(b["distance_km"], float)
      assert b["distance_km"] > BOOST_RADIUS_KM


  def test_closer_scores_at_least_as_high():
      # Honolulu is the only Hawaiian city above the 100k cut, so within ~1000 km it is
      # unambiguously the nearest; stepping south into open ocean only increases distance.
      base_lat, base_lon = 21.3069, -157.8583
      b0 = compute_boost(base_lat, base_lon)
      b1 = compute_boost(base_lat - 1.0, base_lon)
      b2 = compute_boost(base_lat - 2.0, base_lon)
      assert b0["nearest_place"] == b1["nearest_place"] == b2["nearest_place"]
      assert b0["distance_km"] <= b1["distance_km"] <= b2["distance_km"]
      assert b0["applied"] >= b1["applied"] >= b2["applied"]


  def test_larger_population_scores_at_least_as_high():
      non_caps = [r for r in _rows() if r["capital"] == "0" and int(r["population"]) > 0]
      big = max(non_caps, key=lambda r: int(r["population"]))
      small = min(non_caps, key=lambda r: int(r["population"]))
      b_big = compute_boost(float(big["lat"]), float(big["lon"]))
      b_small = compute_boost(float(small["lat"]), float(small["lon"]))
      assert b_big["population"] >= b_small["population"]
      assert b_big["applied"] >= b_small["applied"]


  def test_deterministic_same_input_twice():
      first = compute_boost(35.0, 139.0)
      second = compute_boost(35.0, 139.0)
      assert first == second
  ```

- [ ] **Step 5: Run the test and confirm it FAILS for the right reason.**
  ```
  C:\Users\ngwei\AppData\Roaming\Python\Python314\Scripts\uv.exe run pytest tests/test_boost.py -q
  ```
  Expected FAIL: collection error `ModuleNotFoundError: No module named 'pipeline.boost'` (0 passed, 1 error) — `boost.py` does not exist yet.

- [ ] **Step 6: Implement `boost.py` (full, minimal).**
  Create `pipeline/pipeline/boost.py`:
  ```python
  """Deterministic, model-free newsworthiness boost from a committed population-centres dataset.

  Pure function of ``(lat, lon)`` and the static committed ``data/cities.csv`` (trimmed GeoNames
  ``cities15000`` — see ``data/NOTICE.md``). The dataset is loaded once, ``__file__``-relative, so
  the boost never touches the network (CLAUDE.md conv. 1; spec §7.2). The returned dict is copied
  verbatim into ``severity.boost``.
  """

  import csv
  import math
  from functools import lru_cache
  from pathlib import Path
  from typing import Any, NamedTuple

  from pipeline.geo import great_circle_km

  BOOST_RADIUS_KM = 300.0
  MAX_BOOST = 15.0
  CAPITAL_BONUS = 5.0
  BOOST_CAP = 20.0

  _CITIES_CSV = Path(__file__).parent / "data" / "cities.csv"


  class _City(NamedTuple):
      name: str
      lat: float
      lon: float
      population: int
      capital: bool


  @lru_cache(maxsize=1)
  def _load_cities() -> tuple[_City, ...]:
      with _CITIES_CSV.open(encoding="utf-8", newline="") as fh:
          return tuple(
              _City(
                  name=row["name"],
                  lat=float(row["lat"]),
                  lon=float(row["lon"]),
                  population=int(row["population"]),
                  capital=row["capital"] == "1",
              )
              for row in csv.DictReader(fh)
          )


  def compute_boost(lat: float, lon: float) -> dict[str, Any]:
      """Newsworthiness boost (points on the 0–100 severity scale) for an event at ``(lat, lon)``.

      Finds the nearest committed population centre (argmin over the dataset, tiebroken by
      ``(round(distance, 6), -population, name)`` to defeat libm ULP noise), then scores
      proximity × population, plus a capital bonus, capped at ``BOOST_CAP``. ``applied`` is
      ``0.0`` beyond ``BOOST_RADIUS_KM`` but ``nearest_place``/``population``/``distance_km`` are
      still populated so the ranking stays auditable ("nearest is X, N km away, no boost").
      """
      cities = _load_cities()
      if not cities:
          return {"nearest_place": None, "population": None, "distance_km": None, "applied": 0.0}
      nearest = min(
          cities,
          key=lambda c: (round(great_circle_km(lat, lon, c.lat, c.lon), 6), -c.population, c.name),
      )
      distance = great_circle_km(lat, lon, nearest.lat, nearest.lon)
      proximity = max(0.0, 1.0 - distance / BOOST_RADIUS_KM)
      pop_weight = min(1.0, math.log10(max(nearest.population, 1)) / 7.0)
      applied = MAX_BOOST * proximity * pop_weight
      if nearest.capital:
          applied += CAPITAL_BONUS * proximity
      applied = min(applied, BOOST_CAP)
      return {
          "nearest_place": nearest.name,
          "population": nearest.population,
          "distance_km": round(distance, 1),
          "applied": round(applied, 3),
      }
  ```

- [ ] **Step 7: Run the test and confirm it PASSES.**
  ```
  C:\Users\ngwei\AppData\Roaming\Python\Python314\Scripts\uv.exe run pytest tests/test_boost.py -q
  ```
  Expected PASS: `6 passed` in well under a second.

- [ ] **Step 8: Format and type-check the new module.**
  ```
  C:\Users\ngwei\AppData\Roaming\Python\Python314\Scripts\uv.exe run ruff format pipeline/boost.py tests/test_boost.py
  C:\Users\ngwei\AppData\Roaming\Python\Python314\Scripts\uv.exe run ruff check pipeline/boost.py tests/test_boost.py
  C:\Users\ngwei\AppData\Roaming\Python\Python314\Scripts\uv.exe run mypy pipeline/boost.py
  ```
  Expected: ruff format reports `2 files left unchanged` (or reformats them); ruff check prints `All checks passed!`; mypy prints `Success: no issues found in 1 source file`.

- [ ] **Step 9: Commit the implementation and its test.**
  ```
  git add pipeline/pipeline/boost.py pipeline/tests/test_boost.py
  git commit -m "feat(slice-2): newsworthiness proximity boost (boost.py) over committed cities dataset" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```
  Expected: one commit adding `pipeline/pipeline/boost.py` and `pipeline/tests/test_boost.py`.

---

### Task 5: Per-hazard severity + EQ regression (severity.py)

**Files:**
- Modify: `pipeline/pipeline/severity.py`
- Test: `pipeline/tests/test_severity.py`

**Interfaces:**
- Consumes: nothing from earlier tasks — depends only on the Python stdlib. Operates on a plain `inputs: dict[str, Any]` carrying the four keys `{"mag", "sig", "alert", "alert_score"}` (the same shape later emitted as `severity.inputs`; each value may be `None`).
- Produces (used by the contract/build tasks):
  - `MAJOR_CUTOFF = 60.0`
  - `severity_level(mag: float, sig: int | None, alert: str | None) -> Level` (FROZEN EQ level band, byte-identical to v1)
  - `base_signal(hazard: str, inputs: dict[str, Any]) -> float` (0–100 numeric base, routed by hazard)
  - `level_for(hazard: str, inputs: dict[str, Any]) -> Level` (base band, routed by hazard)
  - `is_major(score: float) -> bool` = `score >= MAJOR_CUTOFF` — **replaces** the v1 `is_major(mag, sig, alert)`; its remaining callers (`contract.py`, `build.py`) are rewired in their own tasks, so this task only runs `tests/test_severity.py`.

Notes: `uv` is not on PATH on this machine — if `uv` fails, invoke the full path `C:/Users/ngwei/AppData/Roaming/Python/Python314/Scripts/uv.exe`. All commands run from the pipeline package root `C:/Users/ngwei/OneDrive/Desktop/Workbench/hadr-starter/pipeline`.

- [ ] **Step 1: Write the failing test (replace the entire contents of `pipeline/tests/test_severity.py`).**
  Keeps the 14 EQ band rows verbatim, adds the EQ `base_signal ≥ 60 ⇔ v1-is_major` truth table (incl. the green-EQ→major quirk), the `is_major` threshold, GDACS per-hazard band rows, and the within-colour `alert_score` monotonicity+clamp check.
  ```python
  import pytest

  from pipeline.severity import (
      MAJOR_CUTOFF,
      base_signal,
      is_major,
      level_for,
      severity_level,
  )


  @pytest.mark.parametrize(
      "mag,sig,alert,level",
      [
          (7.5, 100, None, "severe"),      # mag >= 7.0
          (5.0, 100, "orange", "severe"),  # alert orange
          (5.0, 1000, None, "severe"),     # sig >= 1000
          (6.2, 100, None, "serious"),     # mag >= 6.0
          (5.0, 700, None, "serious"),     # sig >= 600
          (5.0, 100, "yellow", "serious"), # alert yellow
          (4.5, 100, None, "moderate"),    # mag >= 4.5
          (3.0, 300, None, "moderate"),    # sig >= 300
          (3.2, 158, None, "minor"),       # below all
          (2.4, None, None, "minor"),      # null sig treated as 0
          (7.0, 100, None, "severe"),      # mag exactly 7.0 -> severe
          (6.0, 100, None, "serious"),     # mag exactly 6.0 -> serious
          (5.0, 600, None, "serious"),     # sig exactly 600 -> serious
          (4.0, 100, "green", "minor"),    # green alert falls through band checks -> minor
      ],
  )
  def test_severity_bands(mag, sig, alert, level):
      assert severity_level(mag, sig, alert) == level


  @pytest.mark.parametrize(
      "mag,sig,alert,expected_major",
      [
          (5.5, 0, None, True),        # mag threshold, inclusive
          (5.49, 0, None, False),
          (4.0, 600, None, True),      # sig threshold, inclusive
          (4.0, 599, None, False),
          (4.0, 0, "green", True),     # green EQ -> major, v1 quirk preserved
          (4.0, 0, None, False),
          (4.0, None, None, False),    # null sig, null alert
          (7.5, 100, "red", True),     # strongest arm dominates
      ],
  )
  def test_eq_base_signal_regression(mag, sig, alert, expected_major):
      inputs = {"mag": mag, "sig": sig, "alert": alert, "alert_score": None}
      score = base_signal("EQ", inputs)
      # Cross-check each row against the literal v1 rule, then prove the equivalence.
      v1_is_major = mag >= 5.5 or (sig or 0) >= 600 or alert is not None
      assert v1_is_major is expected_major
      assert (score >= MAJOR_CUTOFF) is expected_major


  def test_is_major_threshold():
      assert is_major(59.999) is False
      assert is_major(60.0) is True
      assert is_major(100.0) is True


  @pytest.mark.parametrize(
      "hazard,alert,expected_level,expected_major",
      [
          ("TC", "green", "minor", False),     # base 45 < 60
          ("FL", "yellow", "moderate", False), # base 55 < 60
          ("TC", "orange", "serious", True),   # base 75 >= 60
          ("VO", "red", "severe", True),       # base 90 >= 60
      ],
  )
  def test_gdacs_bands(hazard, alert, expected_level, expected_major):
      inputs = {"mag": None, "sig": None, "alert": alert, "alert_score": 0.0}
      assert level_for(hazard, inputs) == expected_level
      assert is_major(base_signal(hazard, inputs)) is expected_major


  def test_gdacs_alert_score_monotonic_and_clamped_within_colour():
      hazard = "FL"

      def sig_in(alert_score):
          return {"mag": None, "sig": None, "alert": "green", "alert_score": alert_score}

      scores = [base_signal(hazard, sig_in(a)) for a in (0.0, 1.0, 2.0, 3.0)]
      # monotonic non-decreasing in alert_score, within the green colour
      assert scores == sorted(scores)
      assert scores[0] == 45.0
      assert scores[-1] == 54.0
      # clamp at 3.0: a larger alert_score cannot push base past the +9 ceiling
      assert base_signal(hazard, sig_in(99.0)) == 54.0
      # green never crosses the major cutoff and the level band never moves off "minor"
      assert all(not is_major(s) for s in scores)
      assert {level_for(hazard, sig_in(a)) for a in (0.0, 1.5, 3.0, 99.0)} == {"minor"}
  ```

- [ ] **Step 2: Run the test and confirm it FAILS.**
  Command:
  ```bash
  cd C:/Users/ngwei/OneDrive/Desktop/Workbench/hadr-starter/pipeline && uv run pytest tests/test_severity.py -q
  ```
  Expected: a collection error (the old `severity.py` has no `MAJOR_CUTOFF`/`base_signal`/`level_for`) —
  `ERROR tests/test_severity.py - ImportError: cannot import name 'base_signal' from 'pipeline.severity'` and a summary line `1 error` (nonzero exit).

- [ ] **Step 3: Write the minimal implementation (replace the entire contents of `pipeline/pipeline/severity.py`).**
  Keeps `severity_level` byte-identical; adds the hazard-routed numeric base, the band router, the score gate, and `MAJOR_CUTOFF`. The EQ arms are constructed so `base_signal ≥ 60 ⇔ (mag≥5.5 or sig≥600 or alert is not None)`.
  ```python
  """Deterministic per-hazard severity: base band (`level`) + 0–100 `base_signal` + `major` gate.

  Routes by *hazard*, not feed (ADR 0003). `level` (the frozen 4-value band) and the numeric
  `base_signal` (which feeds `score = base_signal + boost.applied` and gates `major`) stay
  separate. `severity_level` is FROZEN verbatim from Slice 1. The EQ `base_signal` arms are
  constructed so `base_signal >= MAJOR_CUTOFF` holds IFF the v1 rule
  `is_major(mag>=5.5 or sig>=600 or alert is not None)` held — a provable regression that
  preserves the v1 "green EQ -> major" quirk (deviation §10.6).
  """

  from typing import Any

  Level = str  # one of: "minor" | "moderate" | "serious" | "severe"

  MAJOR_CUTOFF = 60.0

  # EQ arm: any non-null PAGER alert already cleared the v1 gate, so every colour maps >= 60.
  _EQ_ALERT_ARM: dict[str | None, float] = {
      None: 0.0,
      "green": 60.0,
      "yellow": 70.0,
      "orange": 85.0,
      "red": 100.0,
  }

  # GDACS non-EQ colour -> base points and base band. alert_score (clamped to 0–3) only refines
  # ordering *within* a colour; it never crosses a level band.
  _COLOUR_BASE: dict[str, float] = {"green": 45.0, "yellow": 55.0, "orange": 75.0, "red": 90.0}
  _COLOUR_LEVEL: dict[str, Level] = {
      "green": "minor",
      "yellow": "moderate",
      "orange": "serious",
      "red": "severe",
  }


  def _clamp(x: float, lo: float, hi: float) -> float:
      return max(lo, min(hi, x))


  def severity_level(mag: float, sig: int | None, alert: str | None) -> Level:
      s = sig or 0
      if alert in ("orange", "red") or mag >= 7.0 or s >= 1000:
          return "severe"
      if alert == "yellow" or mag >= 6.0 or s >= 600:
          return "serious"
      if mag >= 4.5 or s >= 300:
          return "moderate"
      return "minor"


  def base_signal(hazard: str, inputs: dict[str, Any]) -> float:
      """Numeric 0–100 base signal, routed by hazard. The boost is added later (contract.py)."""
      if hazard == "EQ":
          mag = float(inputs.get("mag") or 0.0)
          sig = inputs.get("sig") or 0
          mag_arm = _clamp(mag / 5.5 * 60.0, 0.0, 100.0)
          sig_arm = _clamp(sig * 0.1, 0.0, 100.0)
          alert_arm = _EQ_ALERT_ARM.get(inputs.get("alert"), 0.0)
          return max(mag_arm, sig_arm, alert_arm)
      base = _COLOUR_BASE.get(inputs.get("alert"), 0.0)
      return base + _clamp(inputs.get("alert_score") or 0.0, 0.0, 3.0) * 3.0


  def level_for(hazard: str, inputs: dict[str, Any]) -> Level:
      """Base band (`level`), routed by hazard. Never moved by the boost."""
      if hazard == "EQ":
          mag = float(inputs.get("mag") or 0.0)
          return severity_level(mag, inputs.get("sig"), inputs.get("alert"))
      return _COLOUR_LEVEL.get(inputs.get("alert"), "minor")


  def is_major(score: float) -> bool:
      return score >= MAJOR_CUTOFF
  ```

- [ ] **Step 4: Run the test and confirm it PASSES.**
  Command:
  ```bash
  cd C:/Users/ngwei/OneDrive/Desktop/Workbench/hadr-starter/pipeline && uv run pytest tests/test_severity.py -q
  ```
  Expected: all green — `28 passed` (14 band rows + 8 EQ-regression rows + 1 threshold + 4 GDACS band rows + 1 monotonicity), exit 0.

- [ ] **Step 5: Lint and type-check the two touched files.**
  Command:
  ```bash
  cd C:/Users/ngwei/OneDrive/Desktop/Workbench/hadr-starter/pipeline && uv run ruff check pipeline/severity.py tests/test_severity.py && uv run mypy pipeline/severity.py
  ```
  Expected: `All checks passed!` from ruff, then `Success: no issues found in 1 source file` from mypy (strict), exit 0.

- [ ] **Step 6: Commit.**
  Command:
  ```bash
  cd C:/Users/ngwei/OneDrive/Desktop/Workbench/hadr-starter && git add pipeline/pipeline/severity.py pipeline/tests/test_severity.py && git commit -m "feat(slice-2): per-hazard severity base_signal + level_for; score-based is_major

  Freeze the EQ level band verbatim; add base_signal/level_for routed by hazard and a
  score>=MAJOR_CUTOFF gate. EQ arms preserve the v1 major rule (incl. the green-EQ quirk);
  GDACS non-EQ maps colour->base+level with a clamped alert_score refinement.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```
  Expected: one commit created recording the two changed files.

---

### Task 6: GDACS parser + PARSERS registry

**Files:**
- Create: `pipeline/pipeline/feeds/gdacs.py`
- Modify: `pipeline/pipeline/feeds/__init__.py`
- Modify: `pipeline/pipeline/build.py`
- Test: `pipeline/tests/test_gdacs_parser.py`

**Interfaces:**
- Consumes (from Task 2, `pipeline/pipeline/models.py`): `@dataclass(frozen=True) NormalizedEvent` with fields `feed:str, source_id:str, hazard:str, title:str, place:str, time:datetime, updated:datetime, lat:float, lon:float, url:str, status:str, depth_km:float|None, mag:float|None, sig:int|None, alert:str|None, alert_score:float|None, glide:str|None, external_ids:frozenset[str], iso3:str|None, country:str|None, affected_population:int|None, affected_basis:str|None`.
- Consumes (already present, v1): `pipeline/pipeline/feeds/usgs.py` `parse_usgs(feed_json: dict[str, Any]) -> list[NormalizedEvent]`; `pipeline/pipeline/dedup.py` `union_by_id`; `pipeline/pipeline/contract.py` `SCHEMA_VERSION, event_from_quake, to_iso`.
- Produces: `pipeline/pipeline/feeds/gdacs.py` `parse_gdacs(feed_json: dict[str, Any]) -> list[NormalizedEvent]`; `pipeline/pipeline/feeds/__init__.py` `Parser = Callable[[dict[str, Any]], list[NormalizedEvent]]` and `PARSERS: dict[str, Parser] = {"usgs": parse_usgs, "gdacs": parse_gdacs}`.

> Scope note: this task adds the GDACS parser and the `PARSERS` registry ONLY — it does not touch `build.py`. The `FeedFetch` rename and `PARSERS` dispatch happen in Task 10, where `build.py`, `contract.py`, and `dedup.py` are migrated together (after Task 2 removed `NormalizedQuake`, those three modules are un-importable until then). All run commands below are scoped to `tests/test_gdacs_parser.py` and run from the `pipeline/` directory.

- [ ] **Step 1: Write the failing GDACS parser tests.**
  Create `pipeline/tests/test_gdacs_parser.py`:
  ```python
  from datetime import datetime, timezone

  import pytest

  from pipeline.feeds.gdacs import parse_gdacs


  def _feature(**props):
      """A single valid GDACS EVENTS4APP feature; kwargs override individual properties."""
      base = {
          "eventtype": "EQ",
          "eventid": 1550421,
          "glide": "",
          "name": "Earthquake in Japan",
          "alertlevel": "Green",
          "alertscore": 1,
          "istemporary": "false",
          "country": "Japan",
          "fromdate": "2026-07-06T11:29:36",
          "datemodified": "2026-07-06T12:09:48",
          "iso3": "JPN",
          "source": "NEIC",
          "url": {"report": "https://www.gdacs.org/report.aspx?eventid=1550421"},
      }
      base.update(props)
      return {
          "type": "Feature",
          "geometry": {"type": "Point", "coordinates": [141.845, 40.4353]},
          "properties": base,
      }


  def _one(**props):
      events = parse_gdacs({"features": [_feature(**props)]})
      assert len(events) == 1
      return events[0]


  def test_parses_core_fields_lonlat_order_and_utc_times():
      e = _one()
      assert e.feed == "gdacs"
      assert e.source_id == "1550421"
      assert e.hazard == "EQ"
      assert e.title == "Earthquake in Japan"
      assert e.place == "Japan" and e.country == "Japan" and e.iso3 == "JPN"
      # coordinates arrive [lon, lat]
      assert e.lat == 40.4353 and e.lon == 141.845
      assert e.depth_km is None and e.mag is None and e.sig is None
      assert e.url == "https://www.gdacs.org/report.aspx?eventid=1550421"
      assert e.external_ids == frozenset()
      assert e.affected_population is None and e.affected_basis is None
      # naive GDACS ISO strings are assumed UTC
      assert e.time == datetime(2026, 7, 6, 11, 29, 36, tzinfo=timezone.utc)
      assert e.updated == datetime(2026, 7, 6, 12, 9, 48, tzinfo=timezone.utc)
      assert e.time.tzinfo == timezone.utc and e.updated.tzinfo == timezone.utc


  @pytest.mark.parametrize("hazard", ["EQ", "TC", "FL", "VO", "DR"])
  def test_maps_each_modelled_hazard_type(hazard):
      assert _one(eventtype=hazard).hazard == hazard


  def test_skips_wildfire_and_unknown_eventtypes():
      feats = [
          _feature(eventtype="WF", eventid=1),
          _feature(eventtype="XX", eventid=2),
          _feature(eventtype="TC", eventid=3),
      ]
      events = parse_gdacs({"features": feats})
      assert [e.source_id for e in events] == ["3"]
      assert events[0].hazard == "TC"


  def test_lowercases_alert_colour_and_reads_score():
      e = _one(alertlevel="Orange", alertscore=1.5)
      assert e.alert == "orange" and e.alert_score == 1.5


  def test_empty_glide_becomes_none_but_real_glide_kept():
      assert _one(glide="").glide is None
      assert _one(glide="EQ-2026-000123").glide == "EQ-2026-000123"


  def test_skips_features_missing_eventid_coords_or_unparseable_date():
      good = _feature(eventid=999)
      no_id = _feature()
      no_id["properties"].pop("eventid")
      no_coords = _feature(eventid=1001)
      no_coords["geometry"] = {"type": "Point", "coordinates": []}
      bad_date = _feature(eventid=1002, fromdate="not-a-date")
      events = parse_gdacs({"features": [good, no_id, no_coords, bad_date]})
      assert [e.source_id for e in events] == ["999"]


  def test_empty_or_missing_features_yield_nothing():
      assert parse_gdacs({"features": []}) == []
      assert parse_gdacs({}) == []
  ```

- [ ] **Step 2: Run the parser tests and confirm they FAIL.**
  Command (from `pipeline/`): `uv run pytest tests/test_gdacs_parser.py -q`
  Expected: collection error — `ModuleNotFoundError: No module named 'pipeline.feeds.gdacs'` (0 passed, errors).

- [ ] **Step 3: Implement the GDACS parser (minimal).**
  Create `pipeline/pipeline/feeds/gdacs.py`:
  ```python
  """GDACS EVENTS4APP GeoJSON parser. Kept separate and swappable (one module per source)."""

  from datetime import datetime, timezone
  from typing import Any

  from pipeline.models import NormalizedEvent

  # The five hazard types we model; GDACS wildfire (WF) and anything unknown are skipped.
  _HAZARDS = frozenset({"EQ", "TC", "FL", "VO", "DR"})


  def _parse_gdacs_dt(raw: Any) -> datetime | None:
      """Parse a naive GDACS ISO-8601 timestamp, assumed UTC. Returns None if unparseable."""
      if not isinstance(raw, str):
          return None
      try:
          return datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
      except ValueError:
          return None


  def parse_gdacs(feed_json: dict[str, Any]) -> list[NormalizedEvent]:
      """Turn a GDACS EVENTS4APP FeatureCollection into normalized events.

      Only the five modelled hazard types (EQ/TC/FL/VO/DR) are kept; wildfire (WF) and any
      unknown eventtype are skipped defensively. Features missing an eventid, coordinates, or a
      parseable origin time are skipped rather than crashing the whole parse (mirrors USGS).
      Population exposure is NOT in this list feed — it comes from the detail feed later, so
      affected_* stay None here. `istemporary` is carried on `status` for the merge step.
      """
      out: list[NormalizedEvent] = []
      for feat in feed_json.get("features", []):
          props = feat.get("properties") or {}
          hazard = props.get("eventtype")
          if hazard not in _HAZARDS:
              continue
          source_id = props.get("eventid")
          coords = (feat.get("geometry") or {}).get("coordinates") or []
          if not source_id or len(coords) < 2 or coords[0] is None or coords[1] is None:
              continue
          time = _parse_gdacs_dt(props.get("fromdate"))
          if time is None:
              continue
          updated = _parse_gdacs_dt(props.get("datemodified")) or time
          alert = props.get("alertlevel")
          alert_score = props.get("alertscore")
          glide = props.get("glide")
          out.append(
              NormalizedEvent(
                  feed="gdacs",
                  source_id=str(source_id),
                  hazard=hazard,
                  title=props.get("name") or "",
                  place=props.get("country") or "",
                  time=time,
                  updated=updated,
                  lat=float(coords[1]),
                  lon=float(coords[0]),
                  url=(props.get("url") or {}).get("report") or "",
                  status=str(props.get("istemporary") or "").lower(),
                  depth_km=None,
                  mag=None,
                  sig=None,
                  alert=alert.lower() if isinstance(alert, str) else None,
                  alert_score=float(alert_score) if alert_score is not None else None,
                  glide=glide or None,
                  external_ids=frozenset(),
                  iso3=props.get("iso3"),
                  country=props.get("country"),
                  affected_population=None,
                  affected_basis=None,
              )
          )
      return out
  ```

- [ ] **Step 4: Run the parser tests and confirm they PASS.**
  Command (from `pipeline/`): `uv run pytest tests/test_gdacs_parser.py -q`
  Expected: `11 passed`.

- [ ] **Step 5: Commit the parser.**
  ```
  git add pipeline/pipeline/feeds/gdacs.py pipeline/tests/test_gdacs_parser.py
  git commit -m "feat(slice-2): GDACS EVENTS4APP parser mapping all five hazard types" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

- [ ] **Step 6: Add the failing PARSERS registry tests.**
  Edit `pipeline/tests/test_gdacs_parser.py` — add the import under the existing `from pipeline.feeds.gdacs import parse_gdacs` line:
  ```python
  from pipeline.feeds import PARSERS
  from pipeline.feeds.gdacs import parse_gdacs
  ```
  Then append at the end of the file:
  ```python
  def test_parsers_registry_exposes_both_feeds():
      assert set(PARSERS) == {"usgs", "gdacs"}
      assert PARSERS["gdacs"] is parse_gdacs


  def test_registry_dispatch_parses_gdacs_feature():
      events = PARSERS["gdacs"]({"features": [_feature()]})
      assert len(events) == 1 and events[0].feed == "gdacs"
  ```

- [ ] **Step 7: Run the tests and confirm the registry tests FAIL.**
  Command (from `pipeline/`): `uv run pytest tests/test_gdacs_parser.py -q`
  Expected: collection error — `ImportError: cannot import name 'PARSERS' from 'pipeline.feeds'` (the package `__init__.py` is still empty).

- [ ] **Step 8: Implement the parser registry.**
  Replace the contents of `pipeline/pipeline/feeds/__init__.py` (currently empty) with:
  ```python
  """Feed parser registry — one module per source, joined only by NormalizedEvent (ADR 0006)."""

  from collections.abc import Callable
  from typing import Any

  from pipeline.feeds.gdacs import parse_gdacs
  from pipeline.feeds.usgs import parse_usgs
  from pipeline.models import NormalizedEvent

  Parser = Callable[[dict[str, Any]], list[NormalizedEvent]]

  PARSERS: dict[str, Parser] = {"usgs": parse_usgs, "gdacs": parse_gdacs}
  ```

- [ ] **Step 9: Run the tests and confirm they PASS.**
  Command (from `pipeline/`): `uv run pytest tests/test_gdacs_parser.py -q`
  Expected: `13 passed`.

- [ ] **Step 10: Commit the registry.**
  ```
  git add pipeline/pipeline/feeds/__init__.py pipeline/tests/test_gdacs_parser.py
  git commit -m "feat(slice-2): parser registry (PARSERS) joining USGS and GDACS" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 7: Cross-feed deterministic dedup (dedup.py)

**Files:**
- Modify: `pipeline/pipeline/dedup.py`
- Test: `pipeline/tests/test_dedup.py`

**Interfaces:**
- Consumes:
  - `pipeline/pipeline/models.py` → `@dataclass(frozen=True) NormalizedEvent(feed: str, source_id: str, hazard: str, title: str, place: str, time: datetime, updated: datetime, lat: float, lon: float, url: str, status: str, depth_km: float | None, mag: float | None, sig: int | None, alert: str | None, alert_score: float | None, glide: str | None, external_ids: frozenset[str], iso3: str | None, country: str | None, affected_population: int | None, affected_basis: str | None)` (supersedes `NormalizedQuake`)
  - `pipeline/pipeline/geo.py` → `great_circle_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float`
- Produces:
  - `MAX_MERGE_KM: float = 100.0`, `MERGE_TIME_WINDOW_MIN: float = 60.0`
  - `union_by_id(events: Iterable[NormalizedEvent]) -> list[NormalizedEvent]` (re-keyed on `(feed, source_id)`, max `updated`)
  - `same_event(a: NormalizedEvent, b: NormalizedEvent) -> bool` (three tiers, first hit)
  - `cross_feed_clusters(events: list[NormalizedEvent]) -> list[list[NormalizedEvent]]` (union-find, order-independent)

Steps:

- [ ] **Step 1: Rewrite the failing test file `pipeline/tests/test_dedup.py`.** Replace the entire file (the old `NormalizedQuake`-based version) with the full test below. It exercises `union_by_id` re-keying, the three `same_event` tiers with their boundaries, and `cross_feed_clusters` order-independence + transitivity.

```python
from datetime import datetime, timedelta, timezone

from pipeline.dedup import (
    MAX_MERGE_KM,
    MERGE_TIME_WINDOW_MIN,
    cross_feed_clusters,
    same_event,
    union_by_id,
)
from pipeline.models import NormalizedEvent

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def _ev(
    *,
    feed: str = "usgs",
    source_id: str = "id",
    hazard: str = "EQ",
    time: datetime = NOW,
    updated: datetime = NOW,
    lat: float = 0.0,
    lon: float = 0.0,
    glide: str | None = None,
    external_ids: frozenset[str] = frozenset(),
    mag: float | None = 5.0,
) -> NormalizedEvent:
    return NormalizedEvent(
        feed=feed,
        source_id=source_id,
        hazard=hazard,
        title="t",
        place="p",
        time=time,
        updated=updated,
        lat=lat,
        lon=lon,
        url="http://u",
        status="reviewed",
        depth_km=None,
        mag=mag,
        sig=None,
        alert=None,
        alert_score=None,
        glide=glide,
        external_ids=external_ids,
        iso3=None,
        country=None,
        affected_population=None,
        affected_basis=None,
    )


def _shape(clusters: list[list[NormalizedEvent]]) -> set[frozenset[tuple[str, str]]]:
    return {frozenset((e.feed, e.source_id) for e in c) for c in clusters}


# --- union_by_id: re-keyed on (feed, source_id) ---

def test_union_collapses_same_feed_and_id_keeping_max_updated():
    old = _ev(feed="usgs", source_id="shared", updated=NOW, mag=5.0)
    new = _ev(feed="usgs", source_id="shared", updated=NOW + timedelta(minutes=10), mag=5.4)
    result = union_by_id([old, new])
    assert len(result) == 1
    assert result[0].mag == 5.4  # the newer record won


def test_union_newer_wins_regardless_of_order():
    old = _ev(feed="usgs", source_id="shared", updated=NOW, mag=5.0)
    new = _ev(feed="usgs", source_id="shared", updated=NOW + timedelta(minutes=10), mag=5.4)
    result = union_by_id([new, old])  # newer placed FIRST — must still win
    assert len(result) == 1
    assert result[0].mag == 5.4


def test_union_does_not_collapse_across_feeds():
    u = _ev(feed="usgs", source_id="shared")
    g = _ev(feed="gdacs", source_id="shared")
    result = union_by_id([u, g])
    assert {(e.feed, e.source_id) for e in result} == {("usgs", "shared"), ("gdacs", "shared")}


def test_union_empty_input():
    assert union_by_id([]) == []


# --- same_event tier 1: GLIDE + same hazard ---

def test_tier1_glide_match_same_hazard():
    a = _ev(feed="usgs", source_id="a", hazard="FL", glide="FL-2026-01", lat=0.0, lon=0.0)
    b = _ev(feed="gdacs", source_id="b", hazard="FL", glide="fl-2026-01", lat=80.0, lon=80.0)
    assert same_event(a, b) is True  # normalized-equal glide wins even far apart & non-EQ


def test_tier1_glide_requires_same_hazard():
    a = _ev(source_id="a", hazard="FL", glide="G-1")
    b = _ev(source_id="b", hazard="TC", glide="G-1")
    assert same_event(a, b) is False


def test_empty_glide_does_not_match():
    a = _ev(source_id="a", hazard="FL", glide=None, lat=0.0, lon=0.0)
    b = _ev(source_id="b", hazard="FL", glide=None, lat=0.0, lon=0.0)
    assert same_event(a, b) is False


# --- same_event tier 2: shared external ids ---

def test_tier2_external_ids_intersection():
    a = _ev(feed="usgs", source_id="a", hazard="EQ",
            external_ids=frozenset({"ci123", "us456"}), lat=0.0, lon=0.0)
    b = _ev(feed="gdacs", source_id="b", hazard="TC",
            external_ids=frozenset({"us456"}), lat=80.0, lon=80.0)
    assert same_event(a, b) is True  # tier 2 ignores hazard & distance


def test_tier2_no_intersection_no_merge():
    a = _ev(source_id="a", hazard="FL", external_ids=frozenset({"x"}), lat=0.0, lon=0.0)
    b = _ev(source_id="b", hazard="FL", external_ids=frozenset({"y"}), lat=0.0, lon=0.0)
    assert same_event(a, b) is False


# --- same_event tier 3: EQ-only geo + time ---

def test_tier3_distance_boundary_inclusive(monkeypatch):
    monkeypatch.setattr("pipeline.dedup.great_circle_km", lambda *a: MAX_MERGE_KM)
    a = _ev(feed="usgs", source_id="a", hazard="EQ", time=NOW)
    b = _ev(feed="gdacs", source_id="b", hazard="EQ", time=NOW)
    assert same_event(a, b) is True  # 100.0 km is IN


def test_tier3_distance_boundary_exclusive(monkeypatch):
    monkeypatch.setattr("pipeline.dedup.great_circle_km", lambda *a: MAX_MERGE_KM + 0.1)
    a = _ev(feed="usgs", source_id="a", hazard="EQ", time=NOW)
    b = _ev(feed="gdacs", source_id="b", hazard="EQ", time=NOW)
    assert same_event(a, b) is False  # 100.1 km is OUT


def test_tier3_time_boundary_inclusive():
    a = _ev(feed="usgs", source_id="a", hazard="EQ", time=NOW, lat=0.0, lon=0.0)
    b = _ev(feed="gdacs", source_id="b", hazard="EQ",
            time=NOW + timedelta(minutes=MERGE_TIME_WINDOW_MIN), lat=0.0, lon=0.0)
    assert same_event(a, b) is True  # 60 min is IN


def test_tier3_time_boundary_exclusive():
    a = _ev(feed="usgs", source_id="a", hazard="EQ", time=NOW, lat=0.0, lon=0.0)
    b = _ev(feed="gdacs", source_id="b", hazard="EQ",
            time=NOW + timedelta(minutes=MERGE_TIME_WINDOW_MIN + 1), lat=0.0, lon=0.0)
    assert same_event(a, b) is False  # 61 min is OUT


def test_tier3_requires_eq_different_hazard_no_merge():
    a = _ev(source_id="a", hazard="EQ", time=NOW, lat=0.0, lon=0.0)
    b = _ev(source_id="b", hazard="FL", time=NOW, lat=0.0, lon=0.0)
    assert same_event(a, b) is False


def test_tc_never_tier3_merges():
    a = _ev(source_id="a", hazard="TC", time=NOW, lat=0.0, lon=0.0)
    b = _ev(source_id="b", hazard="TC", time=NOW, lat=0.0, lon=0.0)
    assert same_event(a, b) is False


# --- cross_feed_clusters: union-find, order-independent, transitive ---

def test_cross_feed_clusters_order_independent():
    a = _ev(feed="usgs", source_id="a", hazard="EQ", time=NOW, lat=0.0, lon=0.0)
    b = _ev(feed="gdacs", source_id="b", hazard="EQ", time=NOW, lat=0.0, lon=0.0)
    c = _ev(feed="usgs", source_id="c", hazard="TC", time=NOW, lat=50.0, lon=50.0)
    forward = _shape(cross_feed_clusters([a, b, c]))
    reverse = _shape(cross_feed_clusters([c, b, a]))
    assert forward == reverse
    assert forward == {
        frozenset({("usgs", "a"), ("gdacs", "b")}),
        frozenset({("usgs", "c")}),
    }


def test_cross_feed_clusters_transitivity():
    a = _ev(feed="usgs", source_id="a", hazard="EQ", glide="G-9", lat=0.0, lon=0.0)
    b = _ev(feed="gdacs", source_id="b", hazard="EQ", glide="g-9",
            external_ids=frozenset({"link"}), lat=80.0, lon=80.0)
    c = _ev(feed="other", source_id="c", hazard="TC",
            external_ids=frozenset({"link"}), lat=-80.0, lon=-80.0)
    clusters = cross_feed_clusters([a, b, c])  # a~b (glide), b~c (ext id), a≁c directly
    assert len(clusters) == 1
    assert _shape(clusters) == {frozenset({("usgs", "a"), ("gdacs", "b"), ("other", "c")})}
```

- [ ] **Step 2: Run the test and confirm it FAILS.** From the `pipeline/` directory run:
  `C:\Users\ngwei\AppData\Roaming\Python\Python314\Scripts\uv.exe run pytest tests/test_dedup.py -q`
  Expected: **FAIL** — a collection/ImportError, because the current `dedup.py` still does `from pipeline.models import NormalizedQuake` (removed in the models rework) and does not yet export `MAX_MERGE_KM`, `MERGE_TIME_WINDOW_MIN`, `same_event`, or `cross_feed_clusters`. Message: `ImportError: cannot import name 'NormalizedQuake' from 'pipeline.models'`.

- [ ] **Step 3: Rewrite `pipeline/pipeline/dedup.py` with the minimal implementation.** Replace the entire file with the code below (re-keyed `union_by_id`, three-tier `same_event`, union-find `cross_feed_clusters`). `great_circle_km` is imported as a module global so the tier-3 boundary test can `monkeypatch` it.

```python
"""Same-feed union-by-id + deterministic cross-feed dedup (ADR 0005 layer-1).

`union_by_id` collapses same-feed overlap (e.g. the USGS `all_day` vs
`significant_week` windows) keyed on `(feed, source_id)`, keeping the record with
the greatest `updated`. `same_event` / `cross_feed_clusters` implement the
deterministic three-tier cross-feed merge — matching GLIDE, shared external ids,
or an EQ-only geographic+temporal coincidence. Semantic embedding dedup
(layer-2) is deferred.
"""

from collections.abc import Iterable

from pipeline.geo import great_circle_km
from pipeline.models import NormalizedEvent

MAX_MERGE_KM = 100.0
MERGE_TIME_WINDOW_MIN = 60.0


def union_by_id(events: Iterable[NormalizedEvent]) -> list[NormalizedEvent]:
    best: dict[tuple[str, str], NormalizedEvent] = {}
    for e in events:
        key = (e.feed, e.source_id)
        current = best.get(key)
        if current is None or e.updated > current.updated:
            best[key] = e
    return list(best.values())


def _norm_glide(glide: str | None) -> str:
    return glide.strip().upper() if glide else ""


def same_event(a: NormalizedEvent, b: NormalizedEvent) -> bool:
    # Tier 1 — matching GLIDE codes on the same hazard.
    ga, gb = _norm_glide(a.glide), _norm_glide(b.glide)
    if ga and gb and ga == gb and a.hazard == b.hazard:
        return True
    # Tier 2 — a shared external source id.
    if a.external_ids & b.external_ids:
        return True
    # Tier 3 — EQ-only geographic + temporal coincidence.
    if a.hazard == "EQ" and b.hazard == "EQ":
        distance = great_circle_km(a.lat, a.lon, b.lat, b.lon)
        minutes = abs((a.time - b.time).total_seconds()) / 60.0
        if distance <= MAX_MERGE_KM and minutes <= MERGE_TIME_WINDOW_MIN:
            return True
    return False


def cross_feed_clusters(events: list[NormalizedEvent]) -> list[list[NormalizedEvent]]:
    n = len(events)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)

    for i in range(n):
        for j in range(i + 1, n):
            if same_event(events[i], events[j]):
                union(i, j)

    clusters: dict[int, list[NormalizedEvent]] = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(events[i])
    return list(clusters.values())
```

- [ ] **Step 4: Run the test and confirm it PASSES.** From the `pipeline/` directory run:
  `C:\Users\ngwei\AppData\Roaming\Python\Python314\Scripts\uv.exe run pytest tests/test_dedup.py -q`
  Expected: **PASS** — `17 passed`.

- [ ] **Step 5: Commit.** From the repo root run:
  `git add pipeline/pipeline/dedup.py pipeline/tests/test_dedup.py`
  then
  `git commit -m "feat(slice-2): cross-feed deterministic dedup (union-find, 3-tier same_event)" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"`

---

### Task 8: Cluster merge + canonical event (merge.py)

**Files:**
- Create: `pipeline/pipeline/merge.py`
- Test: `pipeline/tests/test_merge.py`

**Interfaces:**
- Consumes:
  - `pipeline/pipeline/models.py`: `@dataclass(frozen=True) NormalizedEvent` with fields `feed: str, source_id: str, hazard: str, title: str, place: str, time: datetime, updated: datetime, lat: float, lon: float, url: str, status: str, depth_km: float | None, mag: float | None, sig: int | None, alert: str | None, alert_score: float | None, glide: str | None, external_ids: frozenset[str], iso3: str | None, country: str | None, affected_population: int | None, affected_basis: str | None` (from Task 1; supersedes `NormalizedQuake`).
- Produces:
  - `pipeline/pipeline/merge.py`: `@dataclass(frozen=True) SourceLink(feed: str, id: str, url: str)`; `@dataclass(frozen=True) MergedEvent(event: NormalizedEvent, sources: tuple[SourceLink, ...])`; `FEED_PRIORITY: tuple[str, ...] = ("usgs", "gdacs")`; `merge_cluster(members: list[NormalizedEvent]) -> MergedEvent`.

Steps:

- [ ] **Step 1: Write the failing test file `pipeline/tests/test_merge.py`.**
  Create `pipeline/tests/test_merge.py` with the full contents below. It constructs `NormalizedEvent` values via a local `_ev` helper (all 22 fields, sensible defaults) and asserts the canonical field preference, source ordering/retention, id-driving identity, single-member and GDACS-only passthrough, order-independence, and same-feed tiebreaks.

  ```python
  from datetime import datetime, timezone

  from pipeline.merge import FEED_PRIORITY, MergedEvent, SourceLink, merge_cluster
  from pipeline.models import NormalizedEvent


  def _ev(
      feed: str,
      source_id: str,
      *,
      hazard: str = "EQ",
      updated_min: int = 0,
      lat: float = 40.0,
      lon: float = 142.0,
      depth_km: float | None = None,
      mag: float | None = None,
      sig: int | None = None,
      alert: str | None = None,
      alert_score: float | None = None,
      affected_population: int | None = None,
      affected_basis: str | None = None,
      status: str = "reviewed",
      url: str = "http://example",
  ) -> NormalizedEvent:
      return NormalizedEvent(
          feed=feed,
          source_id=source_id,
          hazard=hazard,
          title=f"{feed}-title",
          place=f"{feed}-place",
          time=datetime(2026, 7, 6, 11, 0, tzinfo=timezone.utc),
          updated=datetime(2026, 7, 6, 11, updated_min, tzinfo=timezone.utc),
          lat=lat,
          lon=lon,
          url=url,
          status=status,
          depth_km=depth_km,
          mag=mag,
          sig=sig,
          alert=alert,
          alert_score=alert_score,
          glide=None,
          external_ids=frozenset(),
          iso3=None,
          country=None,
          affected_population=affected_population,
          affected_basis=affected_basis,
      )


  def test_feed_priority_is_usgs_then_gdacs():
      assert FEED_PRIORITY == ("usgs", "gdacs")


  def test_usgs_gdacs_cluster_prefers_correct_fields():
      usgs = _ev(
          "usgs", "us6000takd", mag=6.0, sig=640, lat=40.47, lon=142.03,
          depth_km=35.0, status="reviewed", url="http://usgs",
      )
      gdacs = _ev(
          "gdacs", "1550421", mag=None, sig=None, lat=40.40, lon=141.80,
          depth_km=None, alert="orange", alert_score=1.5,
          affected_population=43996, affected_basis="40 thousand in MMI IV",
          url="http://gdacs",
      )
      merged = merge_cluster([usgs, gdacs])
      # magnitude / geometry / sig from the USGS member
      assert merged.event.mag == 6.0
      assert merged.event.sig == 640
      assert merged.event.lat == 40.47
      assert merged.event.lon == 142.03
      assert merged.event.depth_km == 35.0
      # alert / alert_score / affected_* from the GDACS member
      assert merged.event.alert == "orange"
      assert merged.event.alert_score == 1.5
      assert merged.event.affected_population == 43996
      assert merged.event.affected_basis == "40 thousand in MMI IV"
      # canonical identity is USGS -> drives id "usgs:us6000takd"
      assert merged.event.feed == "usgs"
      assert merged.event.source_id == "us6000takd"
      # sources: USGS-first, both retained
      assert [s.feed for s in merged.sources] == ["usgs", "gdacs"]
      assert len(merged.sources) == 2
      assert merged.sources[0] == SourceLink("usgs", "us6000takd", "http://usgs")
      assert merged.sources[1] == SourceLink("gdacs", "1550421", "http://gdacs")


  def test_single_member_cluster_passthrough():
      usgs = _ev("usgs", "us6000takd", mag=5.5, lat=1.0, lon=2.0, url="http://usgs")
      merged = merge_cluster([usgs])
      assert merged.event == usgs
      assert merged.sources == (SourceLink("usgs", "us6000takd", "http://usgs"),)


  def test_gdacs_only_cluster_id_is_gdacs():
      gdacs = _ev(
          "gdacs", "1550421", hazard="TC", mag=None, alert="orange",
          alert_score=2.0, affected_population=1000,
          affected_basis="1 thousand exposed", url="http://gdacs",
      )
      merged = merge_cluster([gdacs])
      assert merged.event.feed == "gdacs"
      assert merged.event.source_id == "1550421"
      assert merged.event.alert == "orange"
      assert merged.event.affected_population == 1000
      assert merged.sources == (SourceLink("gdacs", "1550421", "http://gdacs"),)


  def test_merge_is_order_independent():
      usgs = _ev("usgs", "us6000takd", mag=6.0, lat=40.47, lon=142.03, url="http://usgs")
      gdacs = _ev(
          "gdacs", "1550421", alert="orange", affected_population=43996,
          url="http://gdacs",
      )
      forward = merge_cluster([usgs, gdacs])
      backward = merge_cluster([gdacs, usgs])
      assert forward == backward
      assert isinstance(forward, MergedEvent)


  def test_same_feed_tie_prefers_max_updated():
      older = _ev("usgs", "usAAA", updated_min=1, mag=5.0, url="http://a")
      newer = _ev("usgs", "usBBB", updated_min=9, mag=6.0, url="http://b")
      merged = merge_cluster([older, newer])
      # newer (max updated) is canonical and sources[0]
      assert merged.event.source_id == "usBBB"
      assert merged.event.mag == 6.0
      assert [s.id for s in merged.sources] == ["usBBB", "usAAA"]


  def test_same_feed_equal_updated_breaks_by_source_id():
      a = _ev("usgs", "usAAA", updated_min=5, mag=5.0, url="http://a")
      b = _ev("usgs", "usBBB", updated_min=5, mag=6.0, url="http://b")
      merged = merge_cluster([b, a])
      # equal updated -> lexicographically smallest source_id wins
      assert merged.event.source_id == "usAAA"
      assert merged.event.mag == 5.0
      assert [s.id for s in merged.sources] == ["usAAA", "usBBB"]
  ```

- [ ] **Step 2: Run the test and confirm it FAILS.**
  From `pipeline/` run: `uv run pytest tests/test_merge.py -q`
  Expected: a collection error — `ModuleNotFoundError: No module named 'pipeline.merge'` — reported as `ERRORS` with exit code 1 (the `pipeline.models` import already resolves once Task 1 lands `NormalizedEvent`; only `pipeline.merge` is missing).

- [ ] **Step 3: Write the minimal implementation `pipeline/pipeline/merge.py`.**
  Create `pipeline/pipeline/merge.py` with exactly the contents below.

  ```python
  """Collapse a cross-feed cluster into one canonical MergedEvent, keeping all source links.

  Runs after same-feed union and cross-feed clustering (dedup.py) and before severity/boost,
  so the merged record is the sole gate driver (ADR 0005; spec §7.4). Field preference:
  magnitude/geometry/time/title/place/sig from the USGS member; alert/alert_score/affected_*
  from the GDACS member; status from USGS when present else the priority member. Deterministic
  regardless of input order.
  """

  from dataclasses import dataclass, replace

  from pipeline.models import NormalizedEvent

  FEED_PRIORITY: tuple[str, ...] = ("usgs", "gdacs")


  @dataclass(frozen=True)
  class SourceLink:
      """A single feed's provenance link for a merged event."""

      feed: str
      id: str
      url: str


  @dataclass(frozen=True)
  class MergedEvent:
      """A canonical reconciled event plus every source link that fed it (ordered primary-first)."""

      event: NormalizedEvent
      sources: tuple[SourceLink, ...]


  def _rank(feed: str) -> int:
      return FEED_PRIORITY.index(feed) if feed in FEED_PRIORITY else len(FEED_PRIORITY)


  def _order(members: list[NormalizedEvent]) -> list[NormalizedEvent]:
      # FEED_PRIORITY, then within a feed max(updated), then lexicographic source_id.
      return sorted(
          members,
          key=lambda e: (_rank(e.feed), -e.updated.timestamp(), e.source_id),
      )


  def merge_cluster(members: list[NormalizedEvent]) -> MergedEvent:
      ordered = _order(members)
      primary = ordered[0]
      usgs = next((m for m in ordered if m.feed == "usgs"), None)
      gdacs = next((m for m in ordered if m.feed == "gdacs"), None)

      geo = usgs or primary
      alert = gdacs or primary
      status = usgs or primary

      canonical = replace(
          primary,
          title=geo.title,
          place=geo.place,
          time=geo.time,
          lat=geo.lat,
          lon=geo.lon,
          depth_km=geo.depth_km,
          mag=geo.mag,
          sig=geo.sig,
          alert=alert.alert,
          alert_score=alert.alert_score,
          affected_population=alert.affected_population,
          affected_basis=alert.affected_basis,
          status=status.status,
      )
      sources = tuple(SourceLink(m.feed, m.source_id, m.url) for m in ordered)
      return MergedEvent(event=canonical, sources=sources)
  ```

- [ ] **Step 4: Run the test and confirm it PASSES.**
  From `pipeline/` run: `uv run pytest tests/test_merge.py -q`
  Expected: `7 passed` and exit code 0.

- [ ] **Step 5: Commit.**
  From the repo root run:
  ```
  git add pipeline/pipeline/merge.py pipeline/tests/test_merge.py
  git commit -m "feat(slice-2): cluster merge into canonical MergedEvent

  merge_cluster reconciles a cross-feed cluster: geometry/magnitude/sig/time/
  title/place from USGS, alert/alert_score/affected_* from GDACS, status from
  USGS when present; sources ordered by FEED_PRIORITY with same-feed ties broken
  by max updated then lexicographic source_id. Deterministic given any input order.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 9: Affected-exposure extraction (affected.py)

**Files:**
- Create: `pipeline/pipeline/affected.py`
- Create: `pipeline/tests/fixtures/gdacs_detail_eq.json`
- Modify: `feeds/gdacs.md`
- Test: `pipeline/tests/test_affected.py`

**Interfaces:**
- Consumes: nothing from earlier tasks — pure module, stdlib `typing.Any` only. Reads the GDACS `geteventdata` detail JSON shape (a GeoJSON Feature/FeatureCollection whose `properties.earthquakedetails.rapidpop` + `rapidpopdescription` hold the API-verified EQ exposure figure).
- Produces (later tasks `contract.py` `event_from_merged` and `api/contract.py` consume these):
  - `extract_exposure(hazard: str, detail_json: dict[str, Any]) -> tuple[int | None, str]`
  - `affected_block(population: int | None, basis_text: str | None) -> dict[str, Any]`

Steps:

- [ ] **Step 1: Author the API-verified EQ detail fixture.** This is a test input (a captured/curated GDACS `geteventdata` EQ response pinned to the §7.5 API-verified values). Write `pipeline/tests/fixtures/gdacs_detail_eq.json`:

```json
{
  "type": "Feature",
  "geometry": { "type": "Point", "coordinates": [142.03, 40.47] },
  "properties": {
    "eventtype": "EQ",
    "eventid": 1550421,
    "name": "Earthquake in Japan",
    "alertlevel": "Orange",
    "alertscore": 1.5,
    "country": "Japan",
    "fromdate": "2026-07-06T11:29:36",
    "datemodified": "2026-07-06T12:09:48",
    "earthquakedetails": {
      "magnitude": 6.0,
      "depth": 35.0,
      "rapidpop": 43996,
      "rapidpopdescription": "40 thousand in MMI IV"
    }
  }
}
```

- [ ] **Step 2: Write the failing test file (full code).** Create `pipeline/tests/test_affected.py` (mirrors the fixture-loading style in `test_build_contract.py`; synthetic inline dicts for the negative cases, per §9.1 "captured/synthetic detail fixtures"):

```python
import json
from pathlib import Path

from pipeline.affected import affected_block, extract_exposure

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text("utf-8"))


def test_extract_eq_exposure_verbatim_from_detail():
    pop, basis = extract_exposure("EQ", _load("gdacs_detail_eq.json"))
    assert pop == 43996            # GDACS rapidpop, carried verbatim
    assert isinstance(pop, int)
    assert "MMI IV" in basis       # rapidpopdescription text


def test_eq_exposure_is_the_raw_field_not_derived():
    detail = _load("gdacs_detail_eq.json")
    raw = detail["properties"]["earthquakedetails"]["rapidpop"]
    pop, _ = extract_exposure("EQ", detail)
    assert pop == int(raw)         # identical to the source field, never recomputed


def test_extract_eq_without_rapidpop_returns_none_and_reason():
    detail = {"properties": {"eventtype": "EQ", "earthquakedetails": {"magnitude": 5.0}}}
    pop, basis = extract_exposure("EQ", detail)
    assert pop is None
    assert basis and isinstance(basis, str)


def test_extract_unquantified_hazard_returns_none_and_reason():
    detail = {"properties": {"eventtype": "DR", "name": "Drought in Somewhere"}}
    pop, basis = extract_exposure("DR", detail)
    assert pop is None
    assert "drought" in basis.lower()


def test_affected_block_null_is_grounded_and_sourceless():
    assert affected_block(None, None) == {
        "estimate": None,
        "basis": "no GDACS exposure figure available",
        "source": None,
    }


def test_affected_block_carries_number_and_gdacs_provenance():
    assert affected_block(43996, "40 thousand in MMI IV") == {
        "estimate": 43996,
        "basis": "40 thousand in MMI IV",
        "source": "gdacs",
    }
```

- [ ] **Step 3: Run the test and confirm it FAILS.** From `C:\Users\ngwei\OneDrive\Desktop\Workbench\hadr-starter\pipeline`:

```
uv run pytest tests/test_affected.py -q
```

Expected: collection error, exits non-zero — `ModuleNotFoundError: No module named 'pipeline.affected'` (the module does not exist yet).

- [ ] **Step 4: Implement `affected.py` (full code).** Create `pipeline/pipeline/affected.py`:

```python
"""GDACS per-event exposure ("affected") extraction — carried verbatim, never computed (ADR 0007)."""

from typing import Any

# Per-hazard population-EXPOSURE fields inside the GDACS `geteventdata` properties, as
# (detail_object_key, population_field, description_field). EQ is API-verified
# (earthquakedetails.rapidpop + rapidpopdescription). The non-EQ hazards use GDACS's
# `severitydata` block (population + severitytext) — the EXPECTED path, CONFIRMED or corrected
# per hazard against captured detail fixtures in Step 8-9 (feeds/gdacs.md records the final map).
# If a detail lacks its pinned field, extract_exposure returns (None, reason): we carry the
# figure VERBATIM and never fabricate or derive one (ADR 0007). Any hazard we cannot verify is
# removed from this map (ships null + reason) rather than shipping an unverified extraction path.
_EXPOSURE_FIELDS: dict[str, tuple[str, str, str]] = {
    "EQ": ("earthquakedetails", "rapidpop", "rapidpopdescription"),
    "TC": ("severitydata", "population", "severitytext"),
    "FL": ("severitydata", "population", "severitytext"),
    "VO": ("severitydata", "population", "severitytext"),
    # DR (drought) is intentionally absent: GDACS publishes no per-event population count for
    # droughts, so DR always ships (None, reason). Confirmed by the Step 8 capture.
}

_NO_FIGURE_REASON: dict[str, str] = {
    "EQ": "GDACS earthquake detail carried no rapidpop figure",
    "TC": "GDACS tropical-cyclone detail publishes no exposed-population figure",
    "FL": "GDACS flood detail publishes no exposed-population figure",
    "VO": "GDACS volcano detail publishes no exposed-population figure",
    "DR": "GDACS drought detail publishes no exposed-population figure",
}
_UNKNOWN_REASON = "no GDACS exposure figure for this hazard"


def _properties(detail_json: dict[str, Any]) -> dict[str, Any]:
    """Locate the event `properties` in a GDACS geteventdata response.

    geteventdata returns a GeoJSON Feature (properties inline) or, defensively, a
    FeatureCollection; a bare properties dict is also accepted. Mirrors the parsers'
    defensive shape-reading (feeds/usgs.py).
    """
    if "features" in detail_json:
        feats = detail_json.get("features") or []
        first = feats[0] if feats else {}
        props: dict[str, Any] = first.get("properties") or {}
        return props
    inline: dict[str, Any] = detail_json.get("properties") or detail_json
    return inline


def extract_exposure(hazard: str, detail_json: dict[str, Any]) -> tuple[int | None, str]:
    """Return (population_exposed, basis_text) read VERBATIM from a GDACS geteventdata detail.

    A hazard GDACS does not quantify, or a detail missing its exposure field, returns
    (None, <documented reason>) — never a computed or derived number (ADR 0007).
    """
    fields = _EXPOSURE_FIELDS.get(hazard)
    if fields is not None:
        obj_key, pop_field, desc_field = fields
        detail: dict[str, Any] = _properties(detail_json).get(obj_key) or {}
        pop = detail.get(pop_field)
        if pop is not None:
            desc = detail.get(desc_field)
            return int(pop), (str(desc) if desc is not None else "")
    return None, _NO_FIGURE_REASON.get(hazard, _UNKNOWN_REASON)


def affected_block(population: int | None, basis_text: str | None) -> dict[str, Any]:
    """Shape the contract `affected` object (always present; FE branches on estimate===null)."""
    if population is None:
        return {
            "estimate": None,
            "basis": basis_text or "no GDACS exposure figure available",
            "source": None,
        }
    return {"estimate": int(population), "basis": basis_text or "", "source": "gdacs"}
```

- [ ] **Step 5: Run the test and confirm it PASSES.** From `C:\Users\ngwei\OneDrive\Desktop\Workbench\hadr-starter\pipeline`:

```
uv run pytest tests/test_affected.py -q
```

Expected: `6 passed` (exit 0).

- [ ] **Step 6: Lint & type-check the new module.** From `C:\Users\ngwei\OneDrive\Desktop\Workbench\hadr-starter\pipeline`:

```
uv run ruff check pipeline/affected.py
uv run mypy pipeline/affected.py
```

Expected: ruff prints `All checks passed!`; mypy prints `Success: no issues found in 1 source file`.

- [ ] **Step 7: Commit the core.** From the repo root `C:\Users\ngwei\OneDrive\Desktop\Workbench\hadr-starter`:

```
git add pipeline/pipeline/affected.py pipeline/tests/test_affected.py pipeline/tests/fixtures/gdacs_detail_eq.json
git commit -m "feat(slice-2): verbatim GDACS exposure extraction (affected.py)

extract_exposure reads earthquakedetails.rapidpop + rapidpopdescription for EQ
(API-verified); unquantified hazards / missing figures return (None, reason).
affected_block shapes the always-present contract affected object; numbers are
never recomputed (ADR 0007).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 8: One-time capture of the non-EQ detail fixtures + record the per-hazard field map.** Write the throwaway capture script to `C:\Users\ngwei\AppData\Local\Temp\claude\C--Users-ngwei-OneDrive-Desktop-Workbench-hadr-starter\c66e5d5e-dd0e-45b3-a8ea-31d75060673c\scratchpad\capture_gdacs_details.py` (NOT committed as source):

```python
import json
from pathlib import Path

import httpx

OUT = Path(r"C:\Users\ngwei\OneDrive\Desktop\Workbench\hadr-starter\pipeline\tests\fixtures")
LIST_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/EVENTS4APP"
DETAIL_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventdata"

with httpx.Client(timeout=30.0) as client:
    feats = client.get(LIST_URL).json().get("features", [])
    seen: dict[str, dict] = {}
    for f in feats:
        p = f.get("properties") or {}
        et = p.get("eventtype")
        if et in ("TC", "FL", "VO", "DR") and et not in seen:
            seen[et] = p
    for et, p in seen.items():
        detail = client.get(DETAIL_URL, params={"eventtype": et, "eventid": p["eventid"]}).json()
        (OUT / f"gdacs_detail_{et.lower()}.json").write_text(
            json.dumps(detail, indent=2), encoding="utf-8"
        )
        props = detail.get("properties") or detail
        print(et, p["eventid"], "-> property keys:", sorted(props.keys()))
```

Run it once (network, from `C:\Users\ngwei\OneDrive\Desktop\Workbench\hadr-starter\pipeline`):

```
uv run python "C:\Users\ngwei\AppData\Local\Temp\claude\C--Users-ngwei-OneDrive-Desktop-Workbench-hadr-starter\c66e5d5e-dd0e-45b3-a8ea-31d75060673c\scratchpad\capture_gdacs_details.py"
```

Expected: writes `gdacs_detail_tc.json`, `gdacs_detail_fl.json`, `gdacs_detail_vo.json`, `gdacs_detail_dr.json` and prints each hazard's property keys. Inspect each fixture for a countable exposed-population field. Then append this section to `feeds/gdacs.md`, filling the "exposure field" column from what you actually observed (write "none published" where a hazard carries no exposed-population count):

```markdown
## Detail feed — population-exposure fields (per hazard)

`geteventdata?eventtype=<T>&eventid=<ID>` is the ONLY grounded source of an exposed-population
figure (the EVENTS4APP list carries none — corrects the truncated sample above). Figures are
carried verbatim, never derived (ADR 0007). Pinned from captured fixtures in
`pipeline/tests/fixtures/gdacs_detail_<hazard>.json`.

| Hazard | Exposure field (under `properties`)        | Notes                                  |
|--------|--------------------------------------------|----------------------------------------|
| EQ     | `earthquakedetails.rapidpop` (+ `rapidpopdescription`) | API-verified; MMI-band exposure |
| TC     | `severitydata.population` (+ `severitytext`) | Confirm against `gdacs_detail_tc.json`; if the field is absent, mark "confirmed absent → null + reason". |
| FL     | `severitydata.population` (+ `severitytext`) | Confirm against `gdacs_detail_fl.json`; else "confirmed absent → null + reason". |
| VO     | `severitydata.population` (+ `severitytext`) | Confirm against `gdacs_detail_vo.json`; else "confirmed absent → null + reason". |
| DR     | — (GDACS publishes no per-event count)     | Ships `null` + documented reason; Step 8 capture confirms absence. |
```

If the GDACS API is unreachable in this environment, do not block: REMOVE the three non-EQ lines (TC/FL/VO) from `_EXPOSURE_FIELDS` (leaving EQ only), record "detail not captured — network unavailable this slice; ships null + reason until verified" for TC/FL/VO/DR in the table above, and skip the capture. `extract_exposure` then returns `(None, reason)` for every non-EQ hazard so the base tests stay green — and no unverified extraction path ships (ADR 0007).

- [ ] **Step 9: Confirm (and correct if needed) the pre-pinned non-EQ fields against the captured fixtures, with a verbatim test per quantified hazard.** For each non-EQ hazard, open its `gdacs_detail_<hazard>.json` from Step 8 and check whether `properties.severitydata.population` holds a countable exposed-population figure. **(a)** If YES and the path matches the pre-pinned `("severitydata", "population", "severitytext")`, leave `_EXPOSURE_FIELDS` as-is and add a verbatim fixture-backed test, e.g. for TC:

```python
def test_extract_tc_exposure_verbatim_from_detail():
    detail = _load("gdacs_detail_tc.json")
    raw = detail["properties"]["severitydata"]["population"]
    pop, basis = extract_exposure("TC", detail)
    assert pop == int(raw)         # verbatim, not recomputed
    assert isinstance(pop, int) and isinstance(basis, str)
```

**(b)** If the real figure sits under a DIFFERENT key, correct that hazard's tuple in `_EXPOSURE_FIELDS` to the observed `(object_key, population_field, description_field)` and write the same verbatim test against the corrected path. **(c)** If the hazard's detail carries NO exposed-population figure, DELETE that hazard's line from `_EXPOSURE_FIELDS` (so `extract_exposure` returns `(None, reason)`), record "confirmed absent → null + reason" in the `feeds/gdacs.md` table, and rely on the existing `test_extract_unquantified_hazard_returns_none_and_reason`. Numbers are always carried verbatim — never derived (ADR 0007). Then run the full affected suite from `C:\Users\ngwei\OneDrive\Desktop\Workbench\hadr-starter\pipeline`:

```
uv run pytest tests/test_affected.py -q
uv run ruff check pipeline/affected.py
uv run mypy pipeline/affected.py
```

Expected: all affected tests pass (`6 passed`, or `7 passed` etc. if you added quantifying-hazard tests); ruff `All checks passed!`; mypy `Success: no issues found in 1 source file`.

- [ ] **Step 10: Commit the captured fixtures, field map, and any pinned entries.** From the repo root `C:\Users\ngwei\OneDrive\Desktop\Workbench\hadr-starter` (add only the detail fixtures that were actually captured):

```
git add feeds/gdacs.md pipeline/tests/fixtures/gdacs_detail_*.json pipeline/pipeline/affected.py pipeline/tests/test_affected.py
git commit -m "feat(slice-2): pin GDACS per-hazard exposure fields from captured detail fixtures

Capture one geteventdata detail per non-EQ hazard, record the exposure field map
in feeds/gdacs.md (corrects the list-feed population claim), and pin any hazard
GDACS quantifies into _EXPOSURE_FIELDS with a verbatim fixture-backed test.
Hazards with no published figure emit (None, documented reason) — no fabrication (ADR 0007).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

If Step 9 added no code (no non-EQ hazard quantified), drop `pipeline/pipeline/affected.py pipeline/tests/test_affected.py` from the `git add` and use `chore(slice-2): capture GDACS non-EQ detail fixtures + record exposure field map` as the subject (keep the same trailer).

---

### Task 10: Contract emit + build wiring + hard-duplicate seam test

**Files:**
- Modify: `pipeline/pipeline/contract.py`
- Modify: `pipeline/pipeline/build.py`
- Create: `pipeline/tests/fixtures/gdacs_dup_of_usgs.json`
- Create: `pipeline/tests/fixtures/gdacs_events4app.json`
- Modify: `pipeline/tests/fixtures/usgs_all_day.json`
- Test: `pipeline/tests/test_build_contract.py` (rewrite v1 → v2)
- Test: `pipeline/tests/test_eq_regression.py` (create)

**Interfaces:**
- Consumes (from earlier tasks, exact names):
  - `pipeline/models.py`: `@dataclass(frozen=True) NormalizedEvent(feed, source_id, hazard, title, place, time, updated, lat, lon, url, status, depth_km, mag, sig, alert, alert_score, glide, external_ids, iso3, country, affected_population, affected_basis)`
  - `pipeline/feeds/__init__.py`: `PARSERS: dict[str, Parser] = {"usgs": parse_usgs, "gdacs": parse_gdacs}`
  - `pipeline/dedup.py`: `union_by_id(events: Iterable[NormalizedEvent]) -> list[NormalizedEvent]`; `cross_feed_clusters(events: list[NormalizedEvent]) -> list[list[NormalizedEvent]]`
  - `pipeline/merge.py`: `@dataclass(frozen=True) SourceLink(feed:str, id:str, url:str)`; `@dataclass(frozen=True) MergedEvent(event: NormalizedEvent, sources: tuple[SourceLink, ...])`; `merge_cluster(members: list[NormalizedEvent]) -> MergedEvent`
  - `pipeline/severity.py`: `base_signal(hazard: str, inputs: dict) -> float`; `level_for(hazard: str, inputs: dict) -> str`; `is_major(score: float) -> bool`; `severity_level(mag, sig, alert) -> str` (frozen EQ path)
  - `pipeline/boost.py`: `compute_boost(lat: float, lon: float) -> dict` → `{"nearest_place", "population", "distance_km", "applied"}`
  - `pipeline/affected.py`: `extract_exposure(hazard: str, detail_json: dict) -> tuple[int|None, str]`; `affected_block(population: int|None, basis_text: str|None) -> dict`
  - `contract/schema/contract.v2.schema.json` ($id `.../contract.v2.schema.json`, draft 2020-12, `schema_version` const `"2.0.0"`)
- Produces (for later tasks / the API route task):
  - `pipeline/pipeline/contract.py`: `SCHEMA_VERSION = "2.0.0"`; `to_iso(dt: datetime) -> str`; `event_from_merged(m: MergedEvent, now: datetime) -> dict[str, Any]` (replaces `event_from_quake`)
  - `pipeline/pipeline/build.py`: `@dataclass(frozen=True) FeedFetch(source: str, window: str, status: str, fetched_at: datetime, payload: dict[str, Any] | None, error: str | None)`; `build_contract(fetches: list[FeedFetch], detail_map: dict[str, dict[str, Any]], now: datetime) -> dict[str, Any]`

> Note on test scope: sibling modules (`pipeline/api/contract.py` + `tests/test_api_route.py`) still import the v1 `WindowFetch`/`build_response` and are migrated by the separate API-route task; run commands below are scoped to this task's two test files so PASS/FAIL claims are exact regardless of that task's ordering. `uv` is invoked by full path per local toolchain quirks.

- [ ] **Step 1: Author the hard USGS-duplicate GDACS fixture.** Write `pipeline/tests/fixtures/gdacs_dup_of_usgs.json` — one GDACS EVENTS4APP EQ feature at `[lon,lat]=[142.03,40.47]` (≈16 km from the relocated `us6000takd`), Orange, `fromdate` 2 min after the USGS origin (2026-07-07T01:28:45Z; USGS origin is 01:26:45Z), empty `glide`, so dedup tier-3 (EQ + ≤100 km + ≤60 min) fires:

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": { "type": "Point", "coordinates": [142.03, 40.47] },
      "properties": {
        "eventtype": "EQ",
        "eventid": "1550421",
        "name": "Earthquake off the east coast of Honshu, Japan",
        "country": "Japan",
        "fromdate": "2026-07-07T01:28:45",
        "todate": "2026-07-07T01:28:45",
        "datemodified": "2026-07-07T02:06:45",
        "alertlevel": "Orange",
        "episodealertlevel": "Orange",
        "alertscore": 1.5,
        "glide": "",
        "source": "NEIC",
        "istemporary": "false",
        "url": { "report": "https://www.gdacs.org/report.aspx?eventid=1550421&eventtype=EQ" }
      }
    }
  ]
}
```

- [ ] **Step 2: Author the multi-hazard GDACS list fixture.** Write `pipeline/tests/fixtures/gdacs_events4app.json` — four non-EQ hazards (TC/FL/VO/DR) so no accidental cross-feed EQ merge; each is `magnitude: null` after parse and exercises the GDACS colour→base band + `alert_score` refinement:

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": { "type": "Point", "coordinates": [83.3, 17.7] },
      "properties": {
        "eventtype": "TC", "eventid": "1000001", "name": "Tropical Cyclone NILAM",
        "country": "India", "fromdate": "2026-07-06T00:00:00", "todate": "2026-07-07T00:00:00",
        "datemodified": "2026-07-07T06:00:00", "alertlevel": "Orange", "alertscore": 2.0,
        "glide": "TC-2026-000123-IND", "istemporary": "false",
        "url": { "report": "https://www.gdacs.org/report.aspx?eventid=1000001&eventtype=TC" }
      }
    },
    {
      "type": "Feature",
      "geometry": { "type": "Point", "coordinates": [68.4, 27.5] },
      "properties": {
        "eventtype": "FL", "eventid": "1000002", "name": "Floods in Pakistan",
        "country": "Pakistan", "fromdate": "2026-07-04T00:00:00", "todate": "2026-07-07T00:00:00",
        "datemodified": "2026-07-07T05:00:00", "alertlevel": "Red", "alertscore": 2.5,
        "glide": "FL-2026-000045-PAK", "istemporary": "false",
        "url": { "report": "https://www.gdacs.org/report.aspx?eventid=1000002&eventtype=FL" }
      }
    },
    {
      "type": "Feature",
      "geometry": { "type": "Point", "coordinates": [155.2, 50.3] },
      "properties": {
        "eventtype": "VO", "eventid": "1000003", "name": "Volcano Sarychev Peak",
        "country": "Russia", "fromdate": "2026-07-05T00:00:00", "todate": "2026-07-07T00:00:00",
        "datemodified": "2026-07-07T04:00:00", "alertlevel": "Green", "alertscore": 0.5,
        "glide": "", "istemporary": "false",
        "url": { "report": "https://www.gdacs.org/report.aspx?eventid=1000003&eventtype=VO" }
      }
    },
    {
      "type": "Feature",
      "geometry": { "type": "Point", "coordinates": [37.9, 0.5] },
      "properties": {
        "eventtype": "DR", "eventid": "1000004", "name": "Drought in the Horn of Africa",
        "country": "Kenya", "fromdate": "2026-05-01T00:00:00", "todate": "2026-07-07T00:00:00",
        "datemodified": "2026-07-07T03:00:00", "alertlevel": "Orange", "alertscore": 1.0,
        "glide": "DR-2026-000009-KEN", "istemporary": "false",
        "url": { "report": "https://www.gdacs.org/report.aspx?eventid=1000004&eventtype=DR" }
      }
    }
  ]
}
```

- [ ] **Step 3: Extend `usgs_all_day.json` — relocate `us6000takd` next to Hachinohe (the merge target) and add a remote equal-magnitude mid-ocean quake.** Apply these four edits to `pipeline/tests/fixtures/usgs_all_day.json`.

  Edit A — place:
```
        "place": "296 km SSE of Ushuaia, Argentina",
```
→
```
        "place": "20 km S of Hachinohe, Japan",
```
  Edit B — title:
```
        "title": "M 7.2 - 296 km SSE of Ushuaia, Argentina"
```
→
```
        "title": "M 7.2 - 20 km S of Hachinohe, Japan"
```
  Edit C — `us6000takd` coordinates (this `[-66.7593, -57.3319, 10]` block is unique to that feature):
```
        "coordinates": [
          -66.7593,
          -57.3319,
          10
        ]
```
→
```
        "coordinates": [
          141.845,
          40.4353,
          35.0
        ]
```
  Edit D — append the remote mid-ocean quake before the features array closes:
```
      "id": "uw714040221"
    }
  ]
}
```
→
```
      "id": "uw714040221"
    },
    {
      "type": "Feature",
      "properties": {
        "mag": 7.2,
        "place": "South Pacific Ocean (remote)",
        "time": 1783380000000,
        "updated": 1783380000000,
        "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us6000ocpc",
        "alert": "red",
        "status": "reviewed",
        "sig": 1400,
        "ids": ",us6000ocpc,",
        "type": "earthquake",
        "title": "M 7.2 - South Pacific Ocean (remote)"
      },
      "geometry": {
        "type": "Point",
        "coordinates": [
          -140.0,
          -40.0,
          10.0
        ]
      },
      "id": "us6000ocpc"
    }
  ]
}
```

- [ ] **Step 4: Write the v2 build seam test (fails first).** Replace the entire contents of `pipeline/tests/test_build_contract.py` with:

```python
import json
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator

from pipeline.build import FeedFetch, build_contract
from pipeline.severity import base_signal

CONTRACT = Path(__file__).resolve().parents[2] / "contract"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
NOW = datetime(2026, 7, 8, 12, 0, 0, tzinfo=timezone.utc)

# GDACS EQ detail (geteventdata) shape per spec §7.5: earthquakedetails.rapidpop + description.
EQ_DETAIL = {"earthquakedetails": {"rapidpop": 43996,
                                   "rapidpopdescription": "40 thousand in MMI IV or higher"}}


def _schema() -> dict:
    return json.loads((CONTRACT / "schema" / "contract.v2.schema.json").read_text("utf-8"))


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text("utf-8"))


def _fetch(source: str, window: str, status: str = "ok",
           payload: dict | None = None, error: str | None = None) -> FeedFetch:
    return FeedFetch(source=source, window=window, status=status,
                     payload=payload, error=error, fetched_at=NOW)


def _only(feed: dict, event_id: str) -> dict:
    return {"type": "FeatureCollection",
            "features": [f for f in feed["features"] if f["id"] == event_id]}


def test_hard_usgs_gdacs_duplicate_collapses_to_one_merged_event():
    usgs_one = _only(_load("usgs_all_day.json"), "us6000takd")
    contract = build_contract(
        [_fetch("usgs", "all_day", payload=usgs_one),
         _fetch("gdacs", "events4app", payload=_load("gdacs_dup_of_usgs.json"))],
        {"1550421": EQ_DETAIL},
        NOW,
    )
    Draft202012Validator(_schema()).validate(contract)          # whole contract valid vs v2
    assert len(contract["events"]) == 1                          # collapsed to exactly one
    ev = contract["events"][0]
    assert ev["id"] == "usgs:us6000takd"                         # USGS-present id wins
    assert {s["feed"] for s in ev["sources"]} == {"usgs", "gdacs"}
    assert ev["sources"][0]["feed"] == "usgs"                    # primary is USGS
    assert len(ev["sources"]) == 2
    assert ev["magnitude"] == 7.2                                # magnitude/geometry from USGS
    assert ev["severity"]["inputs"]["alert"] == "orange"         # alert from GDACS
    assert ev["affected"]["estimate"] == 43996                   # affected from GDACS detail
    assert ev["affected"]["source"] == "gdacs"
    assert "MMI IV" in ev["affected"]["basis"]


def test_near_city_outscores_equal_magnitude_mid_ocean_and_emits_boost_audit():
    contract = build_contract(
        [_fetch("usgs", "all_day", payload=_load("usgs_all_day.json"))], {}, NOW,
    )
    by_id = {e["id"]: e for e in contract["events"]}
    near = by_id["usgs:us6000takd"]      # 20 km S of Hachinohe
    ocean = by_id["usgs:us6000ocpc"]     # remote South Pacific, same magnitude
    assert near["magnitude"] == ocean["magnitude"] == 7.2
    assert near["severity"]["score"] > ocean["severity"]["score"]
    assert ocean["severity"]["boost"]["applied"] == 0.0
    boost = near["severity"]["boost"]
    assert set(boost) == {"nearest_place", "population", "distance_km", "applied"}
    assert boost["applied"] > 0.0
    base = base_signal("EQ", near["severity"]["inputs"])
    assert near["severity"]["score"] == base + boost["applied"]  # score = base + applied


def test_multi_hazard_null_magnitude_event_validates():
    contract = build_contract(
        [_fetch("gdacs", "events4app", payload=_load("gdacs_events4app.json"))], {}, NOW,
    )
    Draft202012Validator(_schema()).validate(contract)
    tc = next(e for e in contract["events"] if e["hazard"] == "TC")
    assert tc["magnitude"] is None
    assert tc["geometry"]["depth_km"] is None
    assert tc["severity"]["inputs"]["mag"] is None


def test_events_sorted_by_score_descending():
    contract = build_contract(
        [_fetch("usgs", "all_day", payload=_load("usgs_all_day.json")),
         _fetch("gdacs", "events4app", payload=_load("gdacs_events4app.json"))],
        {}, NOW,
    )
    scores = [e["severity"]["score"] for e in contract["events"]]
    assert scores == sorted(scores, reverse=True)


def test_meta_feeds_carries_all_three_rows_including_gdacs():
    contract = build_contract(
        [_fetch("usgs", "all_day", payload=_load("usgs_all_day.json")),
         _fetch("usgs", "significant_week", payload=_load("usgs_significant_week.json")),
         _fetch("gdacs", "events4app", payload=_load("gdacs_events4app.json"))],
        {}, NOW,
    )
    rows = {(f["source"], f["window"]) for f in contract["meta"]["feeds"]}
    assert rows == {("usgs", "all_day"), ("usgs", "significant_week"), ("gdacs", "events4app")}
    assert len(contract["meta"]["feeds"]) == 3


def test_one_feed_down_still_emits_others_and_marks_meta():
    contract = build_contract(
        [_fetch("usgs", "all_day", payload=_load("usgs_all_day.json")),
         _fetch("gdacs", "events4app", status="error", error="HTTP 503")],
        {}, NOW,
    )
    Draft202012Validator(_schema()).validate(contract)
    meta = {f["source"]: f for f in contract["meta"]["feeds"]}
    assert meta["gdacs"]["status"] == "error"
    assert meta["gdacs"]["error"] == "HTTP 503"
    assert meta["usgs"]["status"] == "ok"
    assert any(e["id"].startswith("usgs:") for e in contract["events"])
    assert all(not e["id"].startswith("gdacs:") for e in contract["events"])
```

  Run (from `pipeline/`): `cd pipeline && "C:/Users/ngwei/AppData/Roaming/Python/Python314/Scripts/uv.exe" run pytest tests/test_build_contract.py -q` → **FAIL**: collection error `ImportError: cannot import name 'FeedFetch' from 'pipeline.build'` (build.py is still v1 `WindowFetch`).

- [ ] **Step 5: Write the EQ regression test (fails first).** Create `pipeline/tests/test_eq_regression.py`:

```python
import json
from datetime import datetime, timezone
from pathlib import Path

from pipeline.build import FeedFetch, build_contract
from pipeline.severity import severity_level

FIXTURES = Path(__file__).resolve().parent / "fixtures"
NOW = datetime(2026, 7, 8, 12, 0, 0, tzinfo=timezone.utc)

# v1 golden EQ semantics carried unchanged through the v2 build (level/id/geometry/
# magnitude/provisional are boost-free). `major` is only boost-free where applied == 0,
# so it is asserted conditionally against GOLDEN_MAJOR.
GOLDEN = {
    "usgs:us6000takd": {"level": "severe", "magnitude": 7.2, "provisional": True,
                        "geometry": {"lat": 40.4353, "lon": 141.845, "depth_km": 35.0}},
    "usgs:ci41288735": {"level": "minor", "magnitude": 1.49, "provisional": True,
                        "geometry": {"lat": 35.2941666666667, "lon": -117.807, "depth_km": 7.34}},
    "usgs:uw714040221": {"level": "serious", "magnitude": 3.8, "provisional": False,
                         "geometry": {"lat": 48.2888333333333, "lon": -122.6065, "depth_km": 25.38}},
    "usgs:us6000ocpc": {"level": "severe", "magnitude": 7.2, "provisional": False,
                        "geometry": {"lat": -40.0, "lon": -140.0, "depth_km": 10.0}},
    "usgs:us6000t9bg": {"level": "serious", "magnitude": 6.1, "provisional": False,
                        "geometry": {"lat": 37.8295, "lon": 95.3273, "depth_km": 10.0}},
}
GOLDEN_MAJOR = {
    "usgs:us6000takd": True, "usgs:ci41288735": False, "usgs:uw714040221": True,
    "usgs:us6000ocpc": True, "usgs:us6000t9bg": True,
}


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text("utf-8"))


def _fetch(source: str, window: str, payload: dict) -> FeedFetch:
    return FeedFetch(source=source, window=window, status="ok",
                     payload=payload, error=None, fetched_at=NOW)


def _usgs_only_events() -> dict:
    contract = build_contract(
        [_fetch("usgs", "all_day", _load("usgs_all_day.json")),
         _fetch("usgs", "significant_week", _load("usgs_significant_week.json"))],
        {}, NOW,
    )
    return {e["id"]: e for e in contract["events"]}


def test_usgs_only_level_id_geometry_magnitude_provisional_match_v1():
    events = _usgs_only_events()
    assert set(events) == set(GOLDEN)
    for eid, want in GOLDEN.items():
        e = events[eid]
        assert e["severity"]["level"] == want["level"]
        assert e["magnitude"] == want["magnitude"]
        assert e["provisional"] == want["provisional"]
        assert e["geometry"] == want["geometry"]


def test_major_unchanged_for_every_unboosted_event():
    events = _usgs_only_events()
    unboosted = {eid: e for eid, e in events.items()
                 if e["severity"]["boost"]["applied"] == 0.0}
    assert unboosted  # at least the mid-ocean quake carries no boost
    for eid, e in unboosted.items():
        assert e["major"] == GOLDEN_MAJOR[eid]


def test_boost_never_changes_level():
    near = _usgs_only_events()["usgs:us6000takd"]
    assert near["severity"]["boost"]["applied"] > 0.0            # this event IS boosted
    inputs = near["severity"]["inputs"]
    assert near["severity"]["level"] == severity_level(
        inputs["mag"], inputs["sig"], inputs["alert"])           # band = the frozen EQ path
```

  Run: `cd pipeline && "C:/Users/ngwei/AppData/Roaming/Python/Python314/Scripts/uv.exe" run pytest tests/test_eq_regression.py -q` → **FAIL**: same `ImportError: cannot import name 'FeedFetch' from 'pipeline.build'`.

- [ ] **Step 6: Migrate `contract.py` to v2 `event_from_merged`.** Replace the entire contents of `pipeline/pipeline/contract.py` with:

```python
"""Map a merged event to a contract v2 event, and time formatting for the contract."""

from datetime import datetime, timezone
from typing import Any

from pipeline.affected import affected_block
from pipeline.boost import compute_boost
from pipeline.merge import MergedEvent
from pipeline.severity import base_signal, is_major, level_for

SCHEMA_VERSION = "2.0.0"


def to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def event_from_merged(m: MergedEvent, now: datetime) -> dict[str, Any]:
    e = m.event
    inputs = {"mag": e.mag, "sig": e.sig, "alert": e.alert, "alert_score": e.alert_score}
    boost = compute_boost(e.lat, e.lon)
    score = base_signal(e.hazard, inputs) + boost["applied"]
    primary = m.sources[0]
    return {
        "id": f"{primary.feed}:{primary.id}",
        "hazard": e.hazard,
        "title": e.title,
        "place": e.place,
        "time": to_iso(e.time),
        "geometry": {"lat": e.lat, "lon": e.lon, "depth_km": e.depth_km},
        "magnitude": e.mag,
        "severity": {
            "level": level_for(e.hazard, inputs),
            "score": score,
            "inputs": inputs,
            "boost": boost,
        },
        "major": is_major(score),
        # USGS "automatic" or GDACS istemporary "true" both mean provisional (spec §7.4)
        "provisional": e.status in ("automatic", "true"),
        "sources": [{"feed": s.feed, "id": s.id, "url": s.url} for s in m.sources],
        "affected": affected_block(e.affected_population, e.affected_basis),
    }
```

  Run: `cd pipeline && "C:/Users/ngwei/AppData/Roaming/Python/Python314/Scripts/uv.exe" run pytest tests/test_build_contract.py tests/test_eq_regression.py -q` → **still FAIL**: `build.py` is still v1 and now errors at import (`ImportError: cannot import name 'event_from_quake' from 'pipeline.contract'` / no `FeedFetch`).

- [ ] **Step 7: Migrate `build.py` — `FeedFetch` + the full pure pipeline (parse → enrich affected → union → cluster → merge → emit → sort).** Replace the entire contents of `pipeline/pipeline/build.py` with:

```python
"""The pure pipeline core: already-fetched feed windows + GDACS detail -> contract v2. No network."""

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from pipeline.affected import extract_exposure
from pipeline.contract import SCHEMA_VERSION, event_from_merged, to_iso
from pipeline.dedup import cross_feed_clusters, union_by_id
from pipeline.feeds import PARSERS
from pipeline.merge import merge_cluster
from pipeline.models import NormalizedEvent


@dataclass(frozen=True)
class FeedFetch:
    """The result of fetching one feed window — success carries raw payload, failure an error."""

    source: str
    window: str
    status: str
    fetched_at: datetime
    payload: dict[str, Any] | None
    error: str | None


def _with_exposure(
    e: NormalizedEvent, detail_map: dict[str, dict[str, Any]]
) -> NormalizedEvent:
    """Carry GDACS's verbatim exposure onto the GDACS member from its detail payload."""
    if e.feed != "gdacs" or e.source_id not in detail_map:
        return e
    population, basis = extract_exposure(e.hazard, detail_map[e.source_id])
    return replace(e, affected_population=population, affected_basis=basis)


def build_contract(
    fetches: list[FeedFetch],
    detail_map: dict[str, dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    feeds_meta: list[dict[str, Any]] = []
    events_in: list[NormalizedEvent] = []
    for f in fetches:
        if f.status == "ok" and f.payload is not None:
            parsed = PARSERS[f.source](f.payload)
            events_in.extend(parsed)
            feeds_meta.append({
                "source": f.source, "window": f.window, "status": "ok",
                "fetched_at": to_iso(f.fetched_at), "event_count": len(parsed),
                "error": None,
            })
        else:
            feeds_meta.append({
                "source": f.source, "window": f.window, "status": "error",
                "fetched_at": to_iso(f.fetched_at), "event_count": 0,
                "error": f.error or "fetch failed",
            })

    enriched = [_with_exposure(e, detail_map) for e in events_in]
    clusters = cross_feed_clusters(union_by_id(enriched))
    events = [event_from_merged(merge_cluster(c), now) for c in clusters]
    # Ordering lives here (score desc, time desc, id asc) via stable successive sorts.
    events.sort(key=lambda e: e["id"])
    events.sort(key=lambda e: e["time"], reverse=True)
    events.sort(key=lambda e: e["severity"]["score"], reverse=True)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": to_iso(now),
        "meta": {"feeds": feeds_meta},
        "events": events,
    }
```

  Run: `cd pipeline && "C:/Users/ngwei/AppData/Roaming/Python/Python314/Scripts/uv.exe" run pytest tests/test_build_contract.py tests/test_eq_regression.py -q` → **PASS** (9 passed: 6 build-seam + 3 EQ-regression).

- [ ] **Step 8: Commit.** From the repo root:

```
git add pipeline/tests/fixtures/gdacs_dup_of_usgs.json \
        pipeline/tests/fixtures/gdacs_events4app.json \
        pipeline/tests/fixtures/usgs_all_day.json \
        pipeline/pipeline/contract.py \
        pipeline/pipeline/build.py \
        pipeline/tests/test_build_contract.py \
        pipeline/tests/test_eq_regression.py
git commit -m "feat(slice-2): wire pure core to contract v2 with hard-duplicate seam + EQ regression tests

Replace event_from_quake with event_from_merged (severity{level,score,inputs,boost},
major, sources, affected, id from primary feed); rebuild build_contract as FeedFetch ->
parse/enrich-affected/union/cluster/merge/emit sorted score-desc; add the hard USGS+GDACS
duplicate, boost-ranking, multi-hazard, meta and EQ-regression seam tests.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: Two-phase network fetch + API route (`api/contract.py`)

**Files:**
- Modify: `pipeline/api/contract.py`
- Test: `pipeline/tests/test_api_route.py`

**Interfaces:**
- Consumes (from Task 10, `pipeline/pipeline/build.py`): `@dataclass(frozen=True) FeedFetch(source: str, window: str, status: str, fetched_at: datetime, payload: dict | None, error: str | None)`; `build_contract(fetches: list[FeedFetch], detail_map: dict[str, dict], now: datetime) -> dict[str, Any]` (parses via `PARSERS`, unions, clusters, merges, enriches GDACS members from `detail_map` keyed on the GDACS `source_id`, emits contract v2).
- Consumes (artifact from the contract task): `contract/schema/contract.v2.schema.json` (draft 2020-12, `schema_version` const `"2.0.0"`).
- Produces: `USGS_URLS: dict[str, str]`; `GDACS_LIST_URL: str`; `GDACS_DETAIL_URL: str`; `build_response(client: httpx.Client, now: datetime) -> dict[str, Any]`; `class handler(BaseHTTPRequestHandler)` with `do_GET`. `detail_map` returned by the fetch layer is keyed on `str(eventid)` so it lines up with each GDACS event's `source_id`.

Steps:

- [ ] **Step 1: Replace the API-route test with the two-phase v2 tests (write the failing test).** Overwrite `pipeline/tests/test_api_route.py` with the full contents below. It routes all four network edges through one `httpx.MockTransport` factory (`_route`): both USGS window URLs (served from the existing fixtures), the GDACS EVENTS4APP list (inline), and the per-event `geteventdata` detail endpoint (matched by path, recording each requested `eventid`). The inline GDACS list carries one **Orange** EQ that coincides with USGS `us6000takd` (coords `[142.03, 40.47]`, ~16 km from the relocated `us6000takd` at `[141.845, 40.4353]`; `fromdate` 13 min after the USGS `time` → both inside the ≤100 km / ≤60 min tier-3 window, so they cross-feed merge) plus one **Green** flood that must never trigger a detail GET.

```python
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
from jsonschema import Draft202012Validator

from api.contract import GDACS_LIST_URL, USGS_URLS, build_response  # top-level `api` pkg (pythonpath=".")

CONTRACT = Path(__file__).resolve().parents[2] / "contract"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
NOW = datetime(2026, 7, 8, 12, 0, 0, tzinfo=timezone.utc)

# GDACS EVENTS4APP list: one Orange EQ duplicating USGS us6000takd (coords + time aligned ->
# tier-3 cross-feed merge) + one Green flood that must NOT trigger a phase-2 detail GET.
GDACS_LIST = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [142.03, 40.47]},
            "properties": {
                "eventtype": "EQ",
                "eventid": 1550421,
                "glide": "",
                "name": "Earthquake near Hachinohe, Japan",
                "alertlevel": "Orange",
                "alertscore": 1.5,
                "istemporary": "false",
                "country": "Japan",
                "fromdate": "2026-07-07T01:40:00",
                "datemodified": "2026-07-07T02:00:00",
                "iso3": "JPN",
                "source": "NEIC",
                "url": {
                    "report": "https://www.gdacs.org/report.aspx?eventid=1550421&eventtype=EQ",
                    "details": "https://www.gdacs.org/gdacsapi/api/events/geteventdata?eventtype=EQ&eventid=1550421",
                },
            },
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [90.4, 23.7]},
            "properties": {
                "eventtype": "FL",
                "eventid": 1550999,
                "glide": "",
                "name": "Flood in Bangladesh",
                "alertlevel": "Green",
                "alertscore": 0.5,
                "istemporary": "false",
                "country": "Bangladesh",
                "fromdate": "2026-07-06T00:00:00",
                "datemodified": "2026-07-06T06:00:00",
                "iso3": "BGD",
                "source": "GDACS",
                "url": {
                    "report": "https://www.gdacs.org/report.aspx?eventid=1550999&eventtype=FL",
                    "details": "https://www.gdacs.org/gdacsapi/api/events/geteventdata?eventtype=FL&eventid=1550999",
                },
            },
        },
    ],
}

# GDACS geteventdata (EQ) — exposure lives in the detail feed, not the list feed (spec §7.5).
GDACS_DETAIL_EQ = {
    "earthquakedetails": {
        "rapidpop": 43996,
        "rapidpopdescription": "40 thousand in MMI IV or higher",
    },
}


def _schema() -> dict:
    return json.loads((CONTRACT / "schema" / "contract.v2.schema.json").read_text("utf-8"))


def _client(route):
    return httpx.Client(transport=httpx.MockTransport(route))


def _route(gdacs_list, detail_status, detail_calls):
    def route(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == USGS_URLS["all_day"]:
            return httpx.Response(
                200,
                content=(FIXTURES / "usgs_all_day.json").read_text("utf-8"),
                headers={"content-type": "application/json"},
            )
        if url == USGS_URLS["significant_week"]:
            return httpx.Response(
                200,
                content=(FIXTURES / "usgs_significant_week.json").read_text("utf-8"),
                headers={"content-type": "application/json"},
            )
        if url == GDACS_LIST_URL:
            if gdacs_list is None:
                return httpx.Response(503)
            return httpx.Response(200, json=gdacs_list)
        if request.url.path.endswith("/geteventdata"):
            detail_calls.append(request.url.params["eventid"])
            if detail_status != 200:
                return httpx.Response(detail_status)
            return httpx.Response(200, json=GDACS_DETAIL_EQ)
        raise AssertionError(f"unexpected request: {url}")

    return route


def test_urls_cover_both_windows():
    assert set(USGS_URLS) == {"all_day", "significant_week"}


def test_gdacs_list_url_is_events4app():
    assert GDACS_LIST_URL.endswith("/geteventlist/EVENTS4APP")


def test_build_response_success_merges_and_affected():
    calls: list[str] = []
    contract = build_response(_client(_route(GDACS_LIST, 200, calls)), NOW)

    Draft202012Validator(_schema()).validate(contract)
    assert contract["schema_version"] == "2.0.0"

    feeds = {f["window"]: f for f in contract["meta"]["feeds"]}
    assert set(feeds) == {"all_day", "significant_week", "events4app"}
    assert feeds["events4app"]["source"] == "gdacs"
    assert feeds["events4app"]["status"] == "ok"

    by_id = {e["id"]: e for e in contract["events"]}
    merged = by_id["usgs:us6000takd"]
    assert {s["feed"] for s in merged["sources"]} == {"usgs", "gdacs"}
    assert merged["sources"][0]["feed"] == "usgs"
    assert merged["affected"]["source"] == "gdacs"
    assert merged["affected"]["estimate"] == 43996
    assert "MMI IV" in merged["affected"]["basis"]

    # phase-2 is bounded to Orange/Red — the Green flood is never fetched
    assert calls == ["1550421"]


def test_gdacs_list_down_marks_error_usgs_present():
    calls: list[str] = []
    contract = build_response(_client(_route(None, 200, calls)), NOW)

    Draft202012Validator(_schema()).validate(contract)
    feeds = {f["window"]: f for f in contract["meta"]["feeds"]}
    assert feeds["events4app"]["source"] == "gdacs"
    assert feeds["events4app"]["status"] == "error"
    assert feeds["all_day"]["status"] == "ok"
    assert feeds["significant_week"]["status"] == "ok"

    by_id = {e["id"]: e for e in contract["events"]}
    assert "usgs:us6000takd" in by_id  # USGS events survive a GDACS outage
    assert len(by_id["usgs:us6000takd"]["sources"]) == 1
    assert calls == []  # no list -> no detail fetches


def test_detail_down_nulls_affected():
    calls: list[str] = []
    contract = build_response(_client(_route(GDACS_LIST, 500, calls)), NOW)

    Draft202012Validator(_schema()).validate(contract)
    by_id = {e["id"]: e for e in contract["events"]}
    merged = by_id["usgs:us6000takd"]
    # merge is list-driven, so it still happens; only affected degrades
    assert {s["feed"] for s in merged["sources"]} == {"usgs", "gdacs"}
    assert merged["affected"]["estimate"] is None
    assert merged["affected"]["source"] is None
    assert calls == ["1550421"]  # detail was attempted, then failed
```

- [ ] **Step 2: Run the new test and confirm it FAILS.** Command: `cd pipeline && uv run pytest tests/test_api_route.py -q`. Expected: a collection **ERROR** — `ImportError: cannot import name 'GDACS_LIST_URL' from 'api.contract'` (the old `api/contract.py` is still the v1 single-phase USGS route and additionally references the pre-Task-11 `WindowFetch`/2-arg `build_contract`). RED.

- [ ] **Step 3: Rewrite `pipeline/api/contract.py` to the two-phase fetch (minimal implementation).** Overwrite the whole file with:

```python
"""Vercel Python serverless entrypoint: two-phase USGS+GDACS fetch -> contract v2 JSON.

This is the only network-touching code. All decisions live in the pure core (pipeline.build);
this file fetches (phase-1 USGS windows + GDACS list, phase-2 bounded GDACS detail),
serializes, and degrades each network edge independently — a failed detail GET only nulls
that event's `affected`, it never crashes the build.
"""

import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from typing import Any

import httpx

from pipeline.build import FeedFetch, build_contract

USGS_URLS = {
    "all_day": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson",
    "significant_week": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_week.geojson",
}
GDACS_LIST_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/EVENTS4APP"
GDACS_DETAIL_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventdata"
DETAIL_ALERT_LEVELS = frozenset({"orange", "red"})
TIMEOUT = 10.0


def _fetch_usgs(client: httpx.Client, window: str, now: datetime) -> FeedFetch:
    try:
        resp = client.get(USGS_URLS[window], timeout=TIMEOUT)
        resp.raise_for_status()
        return FeedFetch(
            source="usgs", window=window, status="ok",
            fetched_at=now, payload=resp.json(), error=None,
        )
    except Exception as exc:  # noqa: BLE001 — any fetch/parse failure degrades this window only
        return FeedFetch(
            source="usgs", window=window, status="error",
            fetched_at=now, payload=None, error=str(exc),
        )


def _fetch_gdacs_list(client: httpx.Client, now: datetime) -> FeedFetch:
    try:
        resp = client.get(GDACS_LIST_URL, timeout=TIMEOUT)
        resp.raise_for_status()
        return FeedFetch(
            source="gdacs", window="events4app", status="ok",
            fetched_at=now, payload=resp.json(), error=None,
        )
    except Exception as exc:  # noqa: BLE001 — a down GDACS list degrades only its own feed row
        return FeedFetch(
            source="gdacs", window="events4app", status="error",
            fetched_at=now, payload=None, error=str(exc),
        )


def _detail_targets(list_payload: dict[str, Any] | None) -> list[tuple[str, str]]:
    """(eventtype, eventid) for Orange/Red events — the only ones that can clear `major` (§7.5)."""
    if not list_payload:
        return []
    targets: list[tuple[str, str]] = []
    for feature in list_payload.get("features", []):
        props = feature.get("properties", {})
        if str(props.get("alertlevel", "")).lower() not in DETAIL_ALERT_LEVELS:
            continue
        eventtype = props.get("eventtype")
        eventid = props.get("eventid")
        if eventtype and eventid is not None:
            targets.append((str(eventtype), str(eventid)))
    return targets


def _fetch_detail_map(client: httpx.Client, targets: list[tuple[str, str]]) -> dict[str, Any]:
    """Bounded phase-2 GETs. A failed detail is omitted -> that event's affected stays null."""
    detail_map: dict[str, Any] = {}
    for eventtype, eventid in targets:
        try:
            resp = client.get(
                GDACS_DETAIL_URL,
                params={"eventtype": eventtype, "eventid": eventid},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            detail_map[eventid] = resp.json()
        except Exception:  # noqa: BLE001 — degrade this event only; never crash the build
            continue
    return detail_map


def build_response(client: httpx.Client, now: datetime) -> dict[str, Any]:
    fetches = [_fetch_usgs(client, w, now) for w in ("all_day", "significant_week")]
    gdacs_list = _fetch_gdacs_list(client, now)
    fetches.append(gdacs_list)
    detail_map = _fetch_detail_map(client, _detail_targets(gdacs_list.payload))
    return build_contract(fetches, detail_map, now)


class handler(BaseHTTPRequestHandler):  # noqa: N801 — Vercel requires the name `handler`
    def do_GET(self) -> None:  # noqa: N802
        now = datetime.now(timezone.utc)
        try:
            with httpx.Client() as client:
                contract = build_response(client, now)
            body = json.dumps(contract).encode("utf-8")
            status = 200
        except Exception as exc:  # noqa: BLE001 — fail loud; no last-good store this slice
            body = json.dumps({"error": str(exc)}).encode("utf-8")
            status = 500
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")  # for local cross-origin e2e (Task 12)
        self.end_headers()
        self.wfile.write(body)
```

- [ ] **Step 4: Run the new test and confirm it PASSES.** Command: `cd pipeline && uv run pytest tests/test_api_route.py -q`. Expected: `5 passed` (`test_urls_cover_both_windows`, `test_gdacs_list_url_is_events4app`, `test_build_response_success_merges_and_affected`, `test_gdacs_list_down_marks_error_usgs_present`, `test_detail_down_nulls_affected`). GREEN.

- [ ] **Step 5: Run the full pipeline suite plus lint/type checks and confirm all clean.** Commands: `cd pipeline && uv run pytest -q` then `cd pipeline && uv run ruff check . && uv run ruff format --check .` then `cd pipeline && uv run mypy .`. Expected: pytest reports all tests passing with **0 failures**; `ruff check` prints `All checks passed!` and `ruff format --check` reports the two touched files already formatted; `mypy` prints `Success: no issues found`.

- [ ] **Step 6: Commit the reworked route and its tests.** Commands: `cd pipeline && git add api/contract.py tests/test_api_route.py` then
```
git commit -m "$(cat <<'EOF'
feat(slice-2): two-phase USGS+GDACS fetch with bounded detail GETs in api route

Phase-1 GETs both USGS windows + the GDACS EVENTS4APP list; light-parses the
list for Orange/Red eventids; phase-2 issues bounded geteventdata detail GETs
into a {eventid: detail} map passed to build_contract. Any detail failure nulls
only that event's affected block; a down GDACS list degrades to its feed row.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```
Expected: one commit created on the current branch containing exactly `pipeline/api/contract.py` and `pipeline/tests/test_api_route.py`.

---

### Task 12: FE — v2 shared fixtures, types regen, and loud schema-version guard

**Files:**
- Create: `contract/fixtures/contract.v2.example.json`
- Create: `contract/fixtures/contract.v2.no-major.json`
- Create: `contract/fixtures/contract.v2.feed-down.json`
- Modify: `web/package.json` (repoint the codegen script at the v2 schema)
- Modify: `web/lib/contract.types.ts` (regenerated — never hand-edited)
- Modify: `web/lib/contract.ts` (add `EXPECTED_SCHEMA_VERSION` + guard)
- Test: `web/tests/contract.test.ts`

**Interfaces:**
- Consumes:
  - `contract/schema/contract.v2.schema.json` (Task 1) — draft 2020-12, `schema_version` const `"2.0.0"`; `FeedHealth.source` enum `["usgs","gdacs"]`, `FeedHealth.window` enum `["all_day","significant_week","events4app"]`; `CrisisEvent.hazard` enum `["EQ","TC","FL","VO","DR"]`, `CrisisEvent.magnitude: number|null`, `Severity.score`, `Severity.inputs.alert_score`, `Severity.boost`, `CrisisEvent.affected`.
  - `json-schema-to-typescript@^15.0.4` (the `json2ts` bin) — already in `web/package.json` devDependencies.
  - `loadContract(url?: string): Promise<Contract>` — current `web/lib/contract.ts` (no guard yet).
- Produces (for later FE tasks 13–17):
  - `contract/fixtures/contract.v2.example.json` — 4 events, 3 major, score-desc order (`usgs:us6000severe`, `gdacs:1550421`, `usgs:us6000serious`, `usgs:us6000minor`).
  - `contract/fixtures/contract.v2.no-major.json` — 1 sub-threshold event, all feeds ok.
  - `contract/fixtures/contract.v2.feed-down.json` — no events, `gdacs` feed `status: "error"`.
  - `web/lib/contract.types.ts` (regenerated): `Contract`, `FeedHealth`, `CrisisEvent`, `Geometry`, `Severity`, `FeedSource`, `Affected`.
  - `web/lib/contract.ts`: `EXPECTED_SCHEMA_VERSION = "2.0.0"`; `loadContract` throws `contract schema mismatch: expected 2.0.0, got <v>` when `data.schema_version !== EXPECTED_SCHEMA_VERSION`.

> Migration note: this is a **breaking** contract bump. After this task the whole web suite is still green (the v1 tests read the still-present v1 fixtures and vitest does not type-check). During Tasks 13–16 a *whole-suite* run may be transiently RED — e.g. once Task 13 removes `feedsDown`, the not-yet-migrated `page.tsx`/`page.test.tsx` cannot resolve it — but **each FE task keeps its own file(s) green**, and Task 17 restores the whole suite to green. The Pipeline suite (`uv run pytest`) is a separate seam and is unaffected throughout.

Steps:

- [ ] **Step 1: Author the shared v2 example fixture (4 events, 3 major, score-desc).** Create `contract/fixtures/contract.v2.example.json`. event[0] `usgs:us6000severe` (EQ, severe, USGS-only, `affected.estimate: null`); event[1] `gdacs:1550421` (TC, `magnitude: null`, affected set); event[2] `usgs:us6000serious` (EQ, merged usgs+gdacs, affected set); event[3] `usgs:us6000minor` (non-major, `applied: 0`, affected null):
  ```json
  {
    "schema_version": "2.0.0",
    "generated_at": "2026-07-08T12:00:00Z",
    "meta": {
      "feeds": [
        { "source": "usgs", "window": "all_day", "status": "ok", "fetched_at": "2026-07-08T12:00:00Z", "event_count": 3, "error": null },
        { "source": "usgs", "window": "significant_week", "status": "ok", "fetched_at": "2026-07-08T12:00:00Z", "event_count": 1, "error": null },
        { "source": "gdacs", "window": "events4app", "status": "ok", "fetched_at": "2026-07-08T12:00:00Z", "event_count": 2, "error": null }
      ]
    },
    "events": [
      {
        "id": "usgs:us6000severe",
        "hazard": "EQ",
        "title": "M 7.1 - 40 km W of Testville",
        "place": "40 km W of Testville",
        "time": "2026-07-08T09:00:00Z",
        "geometry": { "lat": -19.1, "lon": -70.9, "depth_km": 34.2 },
        "magnitude": 7.1,
        "severity": {
          "level": "severe",
          "score": 94.732,
          "inputs": { "mag": 7.1, "sig": 850, "alert": null, "alert_score": null },
          "boost": { "nearest_place": "Iquique", "population": 191000, "distance_km": 42.0, "applied": 9.732 }
        },
        "major": true,
        "provisional": true,
        "sources": [
          { "feed": "usgs", "id": "us6000severe", "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us6000severe" }
        ],
        "affected": { "estimate": null, "basis": "No GDACS exposure data (USGS-only event)", "source": null }
      },
      {
        "id": "gdacs:1550421",
        "hazard": "TC",
        "title": "Tropical Cyclone Mawar",
        "place": "Guam",
        "time": "2026-07-07T18:00:00Z",
        "geometry": { "lat": 13.5, "lon": 144.8, "depth_km": null },
        "magnitude": null,
        "severity": {
          "level": "serious",
          "score": 90.305,
          "inputs": { "mag": null, "sig": null, "alert": "orange", "alert_score": 2.0 },
          "boost": { "nearest_place": "Dededo", "population": 44943, "distance_km": 20.0, "applied": 9.305 }
        },
        "major": true,
        "provisional": false,
        "sources": [
          { "feed": "gdacs", "id": "1550421", "url": "https://www.gdacs.org/report.aspx?eventid=1550421&eventtype=TC" }
        ],
        "affected": { "estimate": 150000, "basis": "150 thousand people in Category 1 wind zone", "source": "gdacs" }
      },
      {
        "id": "usgs:us6000serious",
        "hazard": "EQ",
        "title": "M 6.0 - 12 km S of Sampletown",
        "place": "12 km S of Sampletown",
        "time": "2026-07-08T06:30:00Z",
        "geometry": { "lat": 35.7, "lon": 139.7, "depth_km": 10.0 },
        "magnitude": 6.0,
        "severity": {
          "level": "serious",
          "score": 89.037,
          "inputs": { "mag": 6.0, "sig": 640, "alert": "yellow", "alert_score": 1.5 },
          "boost": { "nearest_place": "Tokyo", "population": 8336599, "distance_km": 12.0, "applied": 19.037 }
        },
        "major": true,
        "provisional": false,
        "sources": [
          { "feed": "usgs", "id": "us6000serious", "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us6000serious" },
          { "feed": "gdacs", "id": "1500789", "url": "https://www.gdacs.org/report.aspx?eventid=1500789&eventtype=EQ" }
        ],
        "affected": { "estimate": 43996, "basis": "40 thousand people in MMI IV or higher", "source": "gdacs" }
      },
      {
        "id": "usgs:us6000minor",
        "hazard": "EQ",
        "title": "M 3.2 - 5 km NE of Quietville",
        "place": "5 km NE of Quietville",
        "time": "2026-07-08T11:00:00Z",
        "geometry": { "lat": 51.9, "lon": -176.6, "depth_km": 8.0 },
        "magnitude": 3.2,
        "severity": {
          "level": "minor",
          "score": 34.909,
          "inputs": { "mag": 3.2, "sig": 158, "alert": null, "alert_score": null },
          "boost": { "nearest_place": "Unalaska", "population": 4700, "distance_km": 450.0, "applied": 0.0 }
        },
        "major": false,
        "provisional": false,
        "sources": [
          { "feed": "usgs", "id": "us6000minor", "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us6000minor" }
        ],
        "affected": { "estimate": null, "basis": "No GDACS exposure data (USGS-only event)", "source": null }
      }
    ]
  }
  ```

- [ ] **Step 2: Author the v2 no-major and feed-down fixtures.** Create `contract/fixtures/contract.v2.no-major.json` (one sub-threshold event; all feeds `ok` so `downFeeds` is empty):
  ```json
  {
    "schema_version": "2.0.0",
    "generated_at": "2026-07-08T12:00:00Z",
    "meta": {
      "feeds": [
        { "source": "usgs", "window": "all_day", "status": "ok", "fetched_at": "2026-07-08T12:00:00Z", "event_count": 1, "error": null },
        { "source": "usgs", "window": "significant_week", "status": "ok", "fetched_at": "2026-07-08T12:00:00Z", "event_count": 0, "error": null },
        { "source": "gdacs", "window": "events4app", "status": "ok", "fetched_at": "2026-07-08T12:00:00Z", "event_count": 0, "error": null }
      ]
    },
    "events": [
      {
        "id": "usgs:us6000quiet",
        "hazard": "EQ",
        "title": "M 2.4 - 3 km E of Calmborough",
        "place": "3 km E of Calmborough",
        "time": "2026-07-08T11:45:00Z",
        "geometry": { "lat": 61.2, "lon": -149.9, "depth_km": 20.0 },
        "magnitude": 2.4,
        "severity": {
          "level": "minor",
          "score": 26.182,
          "inputs": { "mag": 2.4, "sig": 89, "alert": null, "alert_score": null },
          "boost": { "nearest_place": "Anchorage", "population": 291826, "distance_km": 350.0, "applied": 0.0 }
        },
        "major": false,
        "provisional": false,
        "sources": [
          { "feed": "usgs", "id": "us6000quiet", "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us6000quiet" }
        ],
        "affected": { "estimate": null, "basis": "No GDACS exposure data (USGS-only event)", "source": null }
      }
    ]
  }
  ```
  Create `contract/fixtures/contract.v2.feed-down.json` (USGS `ok`, GDACS `error` → `downFeeds` returns `["gdacs"]`, matching spec §9.2):
  ```json
  {
    "schema_version": "2.0.0",
    "generated_at": "2026-07-08T12:00:00Z",
    "meta": {
      "feeds": [
        { "source": "usgs", "window": "all_day", "status": "ok", "fetched_at": "2026-07-08T12:00:00Z", "event_count": 0, "error": null },
        { "source": "usgs", "window": "significant_week", "status": "ok", "fetched_at": "2026-07-08T12:00:00Z", "event_count": 0, "error": null },
        { "source": "gdacs", "window": "events4app", "status": "error", "fetched_at": "2026-07-08T12:00:00Z", "event_count": 0, "error": "HTTP 503" }
      ]
    },
    "events": []
  }
  ```

- [ ] **Step 3: Commit the shared v2 fixtures.** They are inert until the tests below import them:
  ```
  git add contract/fixtures/contract.v2.example.json contract/fixtures/contract.v2.no-major.json contract/fixtures/contract.v2.feed-down.json
  git commit -m "chore(slice-2): shared v2 web fixtures (4 events / 3 major, no-major, feed-down)" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

- [ ] **Step 4: Repoint the codegen script at the v2 schema.** Edit `web/package.json` — change the `gen:contract-types` script from the v1 to the v2 schema path:
  ```
  old: "gen:contract-types": "json2ts ../contract/schema/contract.v1.schema.json -o lib/contract.types.ts"
  new: "gen:contract-types": "json2ts ../contract/schema/contract.v2.schema.json -o lib/contract.types.ts"
  ```

- [ ] **Step 5: Regenerate the types from the v2 schema.** Run the generator (cwd → `web` via `--dir`):
  ```
  pnpm --dir web run gen:contract-types
  ```
  Expected: `json2ts` exits 0, overwriting `web/lib/contract.types.ts`. The regenerated content is the deterministic `json2ts` render of the v2 schema (do not hand-edit):
  ```ts
  /* eslint-disable */
  /**
   * This file was automatically generated by json-schema-to-typescript.
   * DO NOT MODIFY IT BY HAND. Instead, modify the source JSONSchema file,
   * and run json-schema-to-typescript to regenerate this file.
   */

  export interface Contract {
    schema_version: "2.0.0";
    generated_at: string;
    meta: {
      feeds: FeedHealth[];
    };
    events: CrisisEvent[];
  }
  export interface FeedHealth {
    source: "usgs" | "gdacs";
    window: "all_day" | "significant_week" | "events4app";
    status: "ok" | "error";
    fetched_at: string;
    event_count: number;
    error?: string | null;
  }
  export interface CrisisEvent {
    id: string;
    hazard: "EQ" | "TC" | "FL" | "VO" | "DR";
    title: string;
    place: string;
    time: string;
    geometry: Geometry;
    magnitude: number | null;
    severity: Severity;
    major: boolean;
    provisional: boolean;
    /**
     * @minItems 1
     */
    sources: [FeedSource, ...FeedSource[]];
    affected: Affected;
  }
  export interface Geometry {
    lat: number;
    lon: number;
    depth_km?: number | null;
  }
  export interface Severity {
    level: "minor" | "moderate" | "serious" | "severe";
    score: number;
    inputs: {
      mag: number | null;
      sig: number | null;
      alert: "green" | "yellow" | "orange" | "red" | null;
      alert_score: number | null;
    };
    boost: {
      nearest_place: string | null;
      population: number | null;
      distance_km: number | null;
      applied: number;
    };
  }
  export interface FeedSource {
    feed: "usgs" | "gdacs";
    id: string;
    url: string;
  }
  export interface Affected {
    estimate: number | null;
    basis: string;
    source: "gdacs" | null;
  }
  ```
  Verify the regen landed the coupled constant and the new feed enum:
  ```
  pnpm --dir web exec grep -nE "schema_version: \"2.0.0\"|\"gdacs\"" lib/contract.types.ts
  ```
  Expected: matches on the `schema_version: "2.0.0";` line and the `FeedHealth.source` / `FeedSource.feed` `"gdacs"` lines (grep exits 0). If either is absent, the Task 1 v2 schema is wrong — stop and fix that first.

- [ ] **Step 6: Commit the regen + script change.** The full suite is still green here (`loadContract` has no guard yet; the pre-existing `contract.test.ts` still imports the v1 fixture; vitest does not type-check, so the new v2 types do not break other tests at runtime):
  ```
  git add web/package.json web/lib/contract.types.ts
  git commit -m "chore(slice-2): regenerate web contract types from v2 schema" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

- [ ] **Step 7: Write the failing guard test.** Replace the entire contents of `web/tests/contract.test.ts` (migrate the import to the v2 fixture, re-baseline the count 3 → 4, add the mismatch case, keep the non-200 case):
  ```ts
  import { describe, expect, it, vi, afterEach } from "vitest";
  import example from "../../contract/fixtures/contract.v2.example.json";
  import { loadContract } from "@/lib/contract";

  afterEach(() => vi.restoreAllMocks());

  describe("loadContract", () => {
    it("returns the parsed contract on a 2.0.0 body", async () => {
      vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(example), { status: 200 })));
      const contract = await loadContract("/api/contract");
      expect(contract.schema_version).toBe("2.0.0");
      expect(contract.events.length).toBe(4);
    });

    it("rejects a stale 1.0.0 body with a loud schema mismatch", async () => {
      const stale = { ...example, schema_version: "1.0.0" };
      vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(stale), { status: 200 })));
      await expect(loadContract("/api/contract")).rejects.toThrow(/schema mismatch/);
    });

    it("throws on a non-200 response", async () => {
      vi.stubGlobal("fetch", vi.fn(async () => new Response("boom", { status: 503 })));
      await expect(loadContract("/api/contract")).rejects.toThrow(/503/);
    });
  });
  ```

- [ ] **Step 8: Run the test and confirm RED.**
  ```
  pnpm --dir web test tests/contract.test.ts
  ```
  Expected: FAIL — `Test Files 1 failed (1)`, `Tests 1 failed | 2 passed (3)`. The failing case is `loadContract › rejects a stale 1.0.0 body with a loud schema mismatch` — `promise resolved` instead of rejecting (no guard exists yet). The `2.0.0 body` and `non-200` cases pass.

- [ ] **Step 9: Implement the guard.** Rewrite `web/lib/contract.ts` in full — add the exported constant and throw on mismatch after parse:
  ```ts
  import type { Contract } from "./contract.types";

  export const CONTRACT_URL = process.env.NEXT_PUBLIC_CONTRACT_URL ?? "/api/contract";
  export const EXPECTED_SCHEMA_VERSION = "2.0.0";

  export async function loadContract(url: string = CONTRACT_URL): Promise<Contract> {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) throw new Error(`contract fetch failed: ${res.status}`);
    const data = (await res.json()) as Contract;
    if (data.schema_version !== EXPECTED_SCHEMA_VERSION) {
      throw new Error(
        "contract schema mismatch: expected " + EXPECTED_SCHEMA_VERSION + ", got " + data.schema_version,
      );
    }
    return data;
  }
  ```

- [ ] **Step 10: Run the test and confirm GREEN.**
  ```
  pnpm --dir web test tests/contract.test.ts
  ```
  Expected: PASS — `Test Files 1 passed (1)`, `Tests 3 passed (3)`.

- [ ] **Step 11: Commit the guard + migrated test.**
  ```
  git add web/lib/contract.ts web/tests/contract.test.ts
  git commit -m "feat(slice-2): loud schema_version guard in loadContract" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 13: FE — v2 presentation helpers (score-based markers, hazard/feed labels, downFeeds, formatAffected)

**Files:**
- Modify: `web/lib/presentation.ts`
- Test: `web/tests/presentation.test.ts`

**Interfaces:**
- Consumes:
  - `web/lib/contract.types.ts` (Task 12, regenerated): `Contract { schema_version: "2.0.0"; generated_at: string; meta: { feeds: FeedHealth[] }; events: CrisisEvent[] }`; `FeedHealth { source: "usgs"|"gdacs"; window: "all_day"|"significant_week"|"events4app"; status: "ok"|"error"; ... }`; `CrisisEvent { hazard: "EQ"|"TC"|"FL"|"VO"|"DR"; magnitude: number|null; severity: Severity; major: boolean; affected: { estimate: number|null; basis: string; source: "gdacs"|null } }`; `Severity { level: "minor"|"moderate"|"serious"|"severe"; score: number; inputs; boost }`.
  - `contract/fixtures/contract.v2.example.json`, `contract/fixtures/contract.v2.feed-down.json` (Task 12).
- Produces (for Tasks 14–17):
  - `severityColor(level: Severity["level"]): string` (UNCHANGED)
  - `markerRadius(score: number): number` = `Math.max(4, Math.min(22, Math.round(4 + score * 0.18)))`
  - `hazardLabel(hazard: string): string`
  - `feedLabel(feed: string): string`
  - `downFeeds(contract: Contract): string[]`
  - `formatAffected(affected: CrisisEvent["affected"]): string`
  - `defaultMajorEvents(contract: Contract): CrisisEvent[]` (filter `e.major`, preserve order)

Steps:

- [ ] **Step 1: Write the failing v2 presentation test.** Replace the entire contents of `web/tests/presentation.test.ts` (currently imports v1 fixtures + `feedsDown` + magnitude-based `markerRadius`) with:
  ```ts
  import { describe, expect, it } from "vitest";
  import example from "../../contract/fixtures/contract.v2.example.json";
  import feedDown from "../../contract/fixtures/contract.v2.feed-down.json";
  import type { Contract } from "@/lib/contract.types";
  import {
    defaultMajorEvents,
    downFeeds,
    feedLabel,
    formatAffected,
    hazardLabel,
    markerRadius,
    severityColor,
  } from "@/lib/presentation";

  describe("presentation helpers", () => {
    it("maps every severity level to a distinct colour", () => {
      const colours = new Set(
        ["minor", "moderate", "serious", "severe"].map((l) => severityColor(l as never)),
      );
      expect(colours.size).toBe(4);
    });

    it("sizes markers off score: monotonic, floor 4, cap 22, handles 0", () => {
      expect(markerRadius(0)).toBe(4);
      expect(markerRadius(6.0)).toBeGreaterThan(markerRadius(0));
      expect(markerRadius(71.3)).toBeGreaterThan(markerRadius(6.0));
      expect(markerRadius(1000)).toBe(22);
    });

    it("labels hazards (5 distinct) with a raw-code fallback", () => {
      expect(hazardLabel("EQ")).toBe("Earthquake");
      expect(hazardLabel("TC")).toBe("Tropical Cyclone");
      expect(hazardLabel("FL")).toBe("Flood");
      expect(hazardLabel("VO")).toBe("Volcano");
      expect(hazardLabel("DR")).toBe("Drought");
      expect(new Set(["EQ", "TC", "FL", "VO", "DR"].map(hazardLabel)).size).toBe(5);
      expect(hazardLabel("WF")).toBe("WF");
    });

    it("labels feeds", () => {
      expect(feedLabel("usgs")).toBe("USGS");
      expect(feedLabel("gdacs")).toBe("GDACS");
    });

    it("returns the source codes of feeds in error", () => {
      expect(downFeeds(example as Contract)).toEqual([]);
      expect(downFeeds(feedDown as Contract)).toEqual(["gdacs"]);
    });

    it("formats the affected estimate for both branches", () => {
      expect(
        formatAffected({ estimate: 43996, basis: "40 thousand in MMI IV", source: "gdacs" }),
      ).toBe("Est. population exposed ≈ 44K · GDACS");
      expect(
        formatAffected({ estimate: null, basis: "no exposure figure for USGS-only event", source: null }),
      ).toBe("Not estimated — no exposure figure for USGS-only event");
    });

    it("keeps only major events, preserving contract order", () => {
      const majors = defaultMajorEvents(example as Contract);
      expect(majors.length).toBe(3);
      expect(majors.every((e) => e.major)).toBe(true);
      expect(majors.map((e) => e.id)).toEqual(
        (example as Contract).events.filter((e) => e.major).map((e) => e.id),
      );
    });
  });
  ```

- [ ] **Step 2: Run the test and confirm RED.**
  ```
  pnpm --dir web test tests/presentation.test.ts
  ```
  Expected: FAIL — the file errors before assertions because the named imports `downFeeds`, `hazardLabel`, `feedLabel`, `formatAffected` are not exported by the current `web/lib/presentation.ts` (only `feedsDown` and the magnitude-based `markerRadius` exist): Vitest reports `does not provide an export named 'downFeeds'`.

- [ ] **Step 3: Rewrite `web/lib/presentation.ts` with the v2 helpers.** Replace the entire file (current `markerRadius(magnitude)` + `feedsDown`) with:
  ```ts
  import type { Contract, CrisisEvent, Severity } from "./contract.types";

  const COLORS: Record<Severity["level"], string> = {
    severe: "#dc2626",
    serious: "#ea580c",
    moderate: "#ca8a04",
    minor: "#6b7280",
  };

  export function severityColor(level: Severity["level"]): string {
    return COLORS[level];
  }

  export function markerRadius(score: number): number {
    return Math.max(4, Math.min(22, Math.round(4 + score * 0.18)));
  }

  const HAZARD_LABELS: Record<string, string> = {
    EQ: "Earthquake",
    TC: "Tropical Cyclone",
    FL: "Flood",
    VO: "Volcano",
    DR: "Drought",
  };

  export function hazardLabel(hazard: string): string {
    return HAZARD_LABELS[hazard] ?? hazard;
  }

  const FEED_LABELS: Record<string, string> = {
    usgs: "USGS",
    gdacs: "GDACS",
  };

  export function feedLabel(feed: string): string {
    return FEED_LABELS[feed] ?? feed;
  }

  export function downFeeds(contract: Contract): string[] {
    const seen = new Set<string>();
    for (const f of contract.meta.feeds) {
      if (f.status === "error") seen.add(f.source);
    }
    return [...seen];
  }

  function abbreviatePopulation(n: number): string {
    if (n >= 1_000_000) return `${Math.round(n / 1_000_000)}M`;
    if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
    return `${n}`;
  }

  export function formatAffected(affected: CrisisEvent["affected"]): string {
    if (affected.estimate === null) {
      return `Not estimated — ${affected.basis}`;
    }
    const count = abbreviatePopulation(affected.estimate);
    const source = affected.source ? feedLabel(affected.source) : "";
    return `Est. population exposed ≈ ${count} · ${source}`;
  }

  export function defaultMajorEvents(contract: Contract): CrisisEvent[] {
    return contract.events.filter((e) => e.major);
  }
  ```

- [ ] **Step 4: Run the test and confirm GREEN.**
  ```
  pnpm --dir web test tests/presentation.test.ts
  ```
  Expected: PASS — `Test Files 1 passed (1)`, `Tests 7 passed (7)`.

- [ ] **Step 5: Commit the v2 presentation helpers.**
  ```
  git add web/lib/presentation.ts web/tests/presentation.test.ts
  git commit -m "feat(slice-2): v2 presentation helpers — score-based markers, hazard/feed labels, downFeeds, formatAffected" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 14: FE — hazard divIcon markers + MapLegend overlay

**Files:**
- Create: `web/components/MapLegend.tsx`
- Create: `web/tests/MapLegend.test.tsx`
- Modify: `web/components/CrisisMap.tsx`
- Test: `web/tests/CrisisMap.test.tsx`

**Interfaces:**
- Consumes:
  - `web/lib/presentation.ts` (Task 13): `markerRadius(score: number): number`, `severityColor(level: string): string`, `hazardLabel(hazard: string): string`.
  - `web/lib/contract.types.ts` (Task 12): `Contract`, `CrisisEvent` (`hazard: "EQ"|"TC"|"FL"|"VO"|"DR"`, `severity: { level, score, inputs, boost }`, `magnitude: number|null`, `geometry: { lat, lon, ... }`).
  - `contract/fixtures/contract.v2.example.json` (Task 12) — 4 events, 3 major; the TC major event is `gdacs:1550421` with `magnitude: null`.
- Produces (for Task 17):
  - `CrisisMap({ events: CrisisEvent[]; selectedId: string | null; onSelect: (id: string) => void })` — reworked to render one `react-leaflet` `Marker` per event backed by `L.divIcon` (SSR-safe HTML badge: colour = `severityColor(level)`, size = `markerRadius(score)`, 2-letter hazard glyph, selection ring class).
  - `MapLegend()` — a no-prop React component: absolutely-positioned, theme-aware HTML overlay with 5 hazard rows, 4 severity swatches, and a size-encoding note.

Steps:

- [ ] **Step 1: Write the failing MapLegend test.** Create `web/tests/MapLegend.test.tsx`:
  ```tsx
  import { render, screen } from "@testing-library/react";
  import { describe, expect, it } from "vitest";
  import { MapLegend } from "@/components/MapLegend";
  import { hazardLabel } from "@/lib/presentation";

  describe("MapLegend", () => {
    it("lists all five hazard labels", () => {
      render(<MapLegend />);
      for (const code of ["EQ", "TC", "FL", "VO", "DR"] as const) {
        expect(screen.getByText(hazardLabel(code))).toBeInTheDocument();
      }
    });

    it("shows four severity colour swatches", () => {
      render(<MapLegend />);
      expect(screen.getAllByTestId("legend-swatch")).toHaveLength(4);
    });

    it("notes that marker size encodes newsworthiness", () => {
      render(<MapLegend />);
      expect(screen.getByText(/newsworthiness score/i)).toBeInTheDocument();
    });
  });
  ```

- [ ] **Step 2: Run the MapLegend test and confirm RED.**
  ```
  pnpm --dir web test tests/MapLegend.test.tsx
  ```
  Expected: the run errors before any assertion with `Failed to resolve import "@/components/MapLegend"` (file does not exist yet) — `Test Files 1 failed (1)`.

- [ ] **Step 3: Implement MapLegend.** Create `web/components/MapLegend.tsx`:
  ```tsx
  import { hazardLabel, severityColor } from "@/lib/presentation";

  const HAZARDS = ["EQ", "TC", "FL", "VO", "DR"] as const;
  const LEVELS = ["severe", "serious", "moderate", "minor"] as const;

  export function MapLegend() {
    return (
      <div
        aria-label="map legend"
        style={{
          position: "absolute",
          right: "0.75rem",
          bottom: "0.75rem",
          zIndex: 1000,
          maxWidth: "12rem",
          padding: "0.5rem 0.625rem",
          borderRadius: "0.375rem",
          border: "1px solid currentColor",
          background: "var(--background)",
          color: "var(--foreground)",
          fontSize: "0.75rem",
          lineHeight: 1.4,
          opacity: 0.95,
        }}
      >
        <strong>Hazards</strong>
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {HAZARDS.map((code) => (
            <li key={code}>
              <span style={{ fontWeight: 700, marginRight: "0.375rem" }}>{code}</span>
              <span>{hazardLabel(code)}</span>
            </li>
          ))}
        </ul>
        <strong>Severity</strong>
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {LEVELS.map((level) => (
            <li key={level} style={{ display: "flex", alignItems: "center", gap: "0.375rem" }}>
              <span
                data-testid="legend-swatch"
                data-color={severityColor(level)}
                style={{
                  display: "inline-block",
                  width: "0.75rem",
                  height: "0.75rem",
                  borderRadius: "50%",
                  background: severityColor(level),
                }}
              />
              <span>{level}</span>
            </li>
          ))}
        </ul>
        <p style={{ margin: "0.375rem 0 0" }}>Marker size &#8733; newsworthiness score</p>
      </div>
    );
  }
  ```

- [ ] **Step 4: Run the MapLegend test and confirm GREEN.**
  ```
  pnpm --dir web test tests/MapLegend.test.tsx
  ```
  Expected: PASS — `Test Files 1 passed (1)`, `Tests 3 passed (3)`.

- [ ] **Step 5: Commit the MapLegend component + test.**
  ```
  git add web/components/MapLegend.tsx web/tests/MapLegend.test.tsx
  git commit -m "feat(slice-2): MapLegend hazard + severity overlay" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

- [ ] **Step 6: Rewrite the CrisisMap test for divIcon markers.** Replace the full contents of `web/tests/CrisisMap.test.tsx` (migrated to the v2 fixture and the new `react-leaflet`/`leaflet` mocks) with:
  ```tsx
  import { render, screen } from "@testing-library/react";
  import userEvent from "@testing-library/user-event";
  import { describe, expect, it, vi } from "vitest";
  import example from "../../contract/fixtures/contract.v2.example.json";
  import type { Contract } from "@/lib/contract.types";
  import { markerRadius, severityColor } from "@/lib/presentation";

  /* eslint-disable @typescript-eslint/no-explicit-any -- mock props mirror react-leaflet's / leaflet's own loosely-typed props */
  vi.mock("leaflet", () => ({
    divIcon: (opts: any) => ({ options: opts }),
  }));

  vi.mock("react-leaflet", () => ({
    MapContainer: ({ children }: any) => <div data-testid="map">{children}</div>,
    TileLayer: () => null,
    Tooltip: ({ children }: any) => <span>{children}</span>,
    Marker: ({ position, icon, eventHandlers }: any) => (
      <button
        data-testid="marker"
        data-lat={position[0]}
        data-lon={position[1]}
        onClick={eventHandlers.click}
        dangerouslySetInnerHTML={{ __html: icon.options.html }}
      />
    ),
  }));
  /* eslint-enable @typescript-eslint/no-explicit-any */

  import { CrisisMap } from "@/components/CrisisMap";

  const major = (example as Contract).events.filter((e) => e.major);

  describe("CrisisMap", () => {
    it("renders one marker per event with the hazard glyph and level colour, in order", async () => {
      render(<CrisisMap events={major} selectedId={null} onSelect={() => {}} />);
      const markers = await screen.findAllByTestId("marker");
      expect(markers).toHaveLength(major.length);
      const rendered = markers.map((m) => {
        const badge = m.querySelector("[data-color]") as HTMLElement;
        return { glyph: badge.textContent, color: badge.getAttribute("data-color") };
      });
      const expected = major.map((e) => ({
        glyph: e.hazard,
        color: severityColor(e.severity.level),
      }));
      expect(rendered).toEqual(expected);
    });

    it("sizes each marker from severity.score", async () => {
      render(<CrisisMap events={major} selectedId={null} onSelect={() => {}} />);
      const markers = await screen.findAllByTestId("marker");
      markers.forEach((m, i) => {
        const badge = m.querySelector("[data-color]") as HTMLElement;
        expect(badge.getAttribute("data-size")).toBe(String(markerRadius(major[i].severity.score)));
      });
    });

    it("marks the selected event with the ring class and leaves others unringed", async () => {
      render(<CrisisMap events={major} selectedId="gdacs:1550421" onSelect={() => {}} />);
      await screen.findAllByTestId("marker");
      expect(screen.getByText("TC").className).toContain("crisis-marker--selected");
      expect(screen.getAllByText("EQ")[0].className).not.toContain("crisis-marker--selected");
    });

    it("calls onSelect with the event id when a marker is clicked", async () => {
      const onSelect = vi.fn();
      render(<CrisisMap events={major} selectedId={null} onSelect={onSelect} />);
      const markers = await screen.findAllByTestId("marker");
      await userEvent.click(markers[0]);
      expect(onSelect).toHaveBeenCalledWith(major[0].id);
    });
  });
  ```

- [ ] **Step 7: Run the CrisisMap test and confirm RED.**
  ```
  pnpm --dir web test tests/CrisisMap.test.tsx
  ```
  Expected: all 4 tests error — the current component imports `CircleMarker` (absent from the new `react-leaflet` mock, so `undefined`) and renders `<CircleMarker>`, so React throws `Element type is invalid: expected a string ... but got: undefined` and `findAllByTestId("marker")` never resolves. `Test Files 1 failed (1)`, `Tests 4 failed (4)`.

- [ ] **Step 8: Rework CrisisMap to divIcon markers.** Replace the full contents of `web/components/CrisisMap.tsx` with:
  ```tsx
  "use client";

  import { useEffect, useState } from "react";
  import { MapContainer, Marker, TileLayer, Tooltip } from "react-leaflet";
  import { divIcon } from "leaflet";
  import "leaflet/dist/leaflet.css";
  import type { CrisisEvent } from "@/lib/contract.types";
  import { markerRadius, severityColor } from "@/lib/presentation";

  // SSR-safe HTML badge: colour = level, size = markerRadius(score), 2-letter hazard glyph,
  // ring when selected. All styling inline so no image asset or stylesheet is required.
  function markerBadge(e: CrisisEvent, selected: boolean, size: number): string {
    const color = severityColor(e.severity.level);
    const cls = selected ? "crisis-marker crisis-marker--selected" : "crisis-marker";
    const ring = selected ? `box-shadow:0 0 0 2px #ffffff,0 0 0 5px ${color};` : "";
    return `<div class="${cls}" data-color="${color}" data-size="${size}" style="width:${size}px;height:${size}px;line-height:${size}px;border-radius:50%;background:${color};color:#ffffff;font-size:${Math.max(8, Math.round(size * 0.5))}px;font-weight:700;text-align:center;border:1px solid #ffffff;${ring}">${e.hazard}</div>`;
  }

  export function CrisisMap({
    events,
    selectedId,
    onSelect,
  }: {
    events: CrisisEvent[];
    selectedId: string | null;
    onSelect: (id: string) => void;
  }) {
    const [mounted, setMounted] = useState(false);
    // SSR-safe mount gate: react-leaflet touches window/document, so render is deferred
    // until after hydration.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    useEffect(() => setMounted(true), []);
    if (!mounted) return <div data-testid="map-loading" style={{ height: "100%" }} />;

    return (
      <MapContainer center={[20, 0]} zoom={2} style={{ height: "100%", width: "100%" }}>
        <TileLayer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution="&copy; OpenStreetMap contributors"
        />
        {events.map((e) => {
          const selected = e.id === selectedId;
          const size = markerRadius(e.severity.score);
          const icon = divIcon({
            html: markerBadge(e, selected, size),
            className: "crisis-marker-icon",
            iconSize: [size, size],
            iconAnchor: [size / 2, size / 2],
          });
          return (
            <Marker
              key={e.id}
              position={[e.geometry.lat, e.geometry.lon]}
              icon={icon}
              eventHandlers={{ click: () => onSelect(e.id) }}
            >
              <Tooltip>{e.title}</Tooltip>
            </Marker>
          );
        })}
      </MapContainer>
    );
  }
  ```

- [ ] **Step 9: Run the CrisisMap test and confirm GREEN.**
  ```
  pnpm --dir web test tests/CrisisMap.test.tsx
  ```
  Expected: PASS — `Test Files 1 passed (1)`, `Tests 4 passed (4)`.

- [ ] **Step 10: Commit the CrisisMap rework + test.**
  ```
  git add web/components/CrisisMap.tsx web/tests/CrisisMap.test.tsx
  git commit -m "feat(slice-2): hazard divIcon markers on CrisisMap" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 15: FE — EventList glyph + score + multi-source badge

**Files:**
- Modify: `web/components/EventList.tsx`
- Test: `web/tests/EventList.test.tsx`

**Interfaces:**
- Consumes:
  - `web/lib/contract.types.ts` (Task 12): `CrisisEvent` with `id: string; hazard: "EQ"|"TC"|"FL"|"VO"|"DR"; title: string; severity: { level; score: number; ... }; major: boolean; provisional: boolean; sources: [FeedSource, ...FeedSource[]]`; `Contract`.
  - `web/lib/presentation.ts` (Task 13): `severityColor(level: Severity["level"]): string` (UNCHANGED).
  - `web/components/ProvisionalBadge.tsx` (existing): `ProvisionalBadge({ provisional }: { provisional: boolean })` — renders `data-testid="provisional-badge"` only when `provisional`.
  - `contract/fixtures/contract.v2.example.json` (Task 12): 4 events, 3 major; `usgs:us6000severe` M7.1 single-source provisional, `gdacs:1550421` TC single-source, `usgs:us6000serious` M6.0 **merged usgs+gdacs** (`sources.length === 2`), `usgs:us6000minor` non-major.
- Produces (for Task 17):
  - `EventList({ events, selectedId, onSelect }: { events: CrisisEvent[]; selectedId: string | null; onSelect: (id: string) => void }): JSX.Element` — signature UNCHANGED; each row additionally renders the 2-letter hazard glyph, the rounded `severity.score`, and a multi-source badge when `sources.length > 1`. Contract order preserved; `aria-label="event list"` and per-row `aria-current` retained.

Steps:

- [ ] **Step 1: Write the failing test.** Replace the entire contents of `web/tests/EventList.test.tsx` (migrate to the v2 fixture; add glyph/score/multi-source assertions):
  ```tsx
  import { render, screen, within } from "@testing-library/react";
  import userEvent from "@testing-library/user-event";
  import { describe, expect, it, vi } from "vitest";
  import example from "../../contract/fixtures/contract.v2.example.json";
  import type { Contract } from "@/lib/contract.types";
  import { EventList } from "@/components/EventList";

  const events = (example as Contract).events.filter((e) => e.major);

  describe("EventList", () => {
    it("renders one row per major event with title, hazard glyph, and score", () => {
      render(<EventList events={events} selectedId={null} onSelect={() => {}} />);

      expect(screen.getAllByRole("button")).toHaveLength(events.length);
      expect(screen.getByText(/M 7.1/)).toBeInTheDocument();
      expect(screen.getByText(/M 6.0/)).toBeInTheDocument();

      const glyphs = screen.getAllByTestId("hazard-glyph").map((el) => el.textContent);
      expect(glyphs).toEqual(events.map((e) => e.hazard));

      const scores = screen.getAllByTestId("event-score").map((el) => el.textContent);
      expect(scores).toEqual(events.map((e) => String(Math.round(e.severity.score))));
    });

    it("shows the multi-source badge only on the merged (multi-source) event", () => {
      render(<EventList events={events} selectedId={null} onSelect={() => {}} />);

      const merged = events.filter((e) => e.sources.length > 1);
      const single = events.filter((e) => e.sources.length === 1);
      expect(screen.getAllByTestId("multi-source-badge")).toHaveLength(merged.length);

      const mergedRow = screen.getByText(merged[0].title).closest("button") as HTMLElement;
      expect(within(mergedRow).queryByTestId("multi-source-badge")).toBeInTheDocument();

      const singleRow = screen.getByText(single[0].title).closest("button") as HTMLElement;
      expect(within(singleRow).queryByTestId("multi-source-badge")).not.toBeInTheDocument();
    });

    it("badges provisional events only", () => {
      render(<EventList events={events} selectedId={null} onSelect={() => {}} />);
      const expected = events.filter((e) => e.provisional).length;
      expect(screen.queryAllByTestId("provisional-badge")).toHaveLength(expected);
    });

    it("calls onSelect with the event id when a row is clicked", async () => {
      const onSelect = vi.fn();
      render(<EventList events={events} selectedId={null} onSelect={onSelect} />);
      await userEvent.click(screen.getByText(/M 7.1/));
      expect(onSelect).toHaveBeenCalledWith("usgs:us6000severe");
    });

    it("marks the selected row via aria-current", () => {
      render(<EventList events={events} selectedId="usgs:us6000serious" onSelect={() => {}} />);
      expect(screen.getByRole("button", { current: true })).toHaveTextContent(/M 6.0/);
    });
  });
  ```

- [ ] **Step 2: Run the test and confirm RED.**
  ```
  pnpm --dir web test tests/EventList.test.tsx
  ```
  Expected: FAIL — `Test Files 1 failed (1)`, `Tests 2 failed | 3 passed (5)`. The first two tests error with `Unable to find an element by: [data-testid="hazard-glyph"]` and `[data-testid="multi-source-badge"]` (the current component renders neither glyph, score, nor multi-source badge); the provisional / onSelect / aria-current tests still pass.

- [ ] **Step 3: Implement the component change.** Replace the entire contents of `web/components/EventList.tsx` with:
  ```tsx
  import type { CrisisEvent } from "@/lib/contract.types";
  import { severityColor } from "@/lib/presentation";
  import { ProvisionalBadge } from "./ProvisionalBadge";

  export function EventList({
    events,
    selectedId,
    onSelect,
  }: {
    events: CrisisEvent[];
    selectedId: string | null;
    onSelect: (id: string) => void;
  }) {
    return (
      <ul aria-label="event list">
        {events.map((e) => (
          <li key={e.id}>
            <button type="button" aria-current={e.id === selectedId} onClick={() => onSelect(e.id)}>
              <span data-testid="hazard-glyph" className="glyph" aria-hidden>
                {e.hazard}
              </span>
              <span>{e.title}</span>
              <span style={{ color: severityColor(e.severity.level) }}>{e.severity.level}</span>
              <span data-testid="event-score">{Math.round(e.severity.score)}</span>
              <ProvisionalBadge provisional={e.provisional} />
              {e.sources.length > 1 && (
                <span
                  data-testid="multi-source-badge"
                  className="badge"
                  title="Reported by multiple feeds"
                >
                  multi-source
                </span>
              )}
            </button>
          </li>
        ))}
      </ul>
    );
  }
  ```

- [ ] **Step 4: Run the test and confirm GREEN.**
  ```
  pnpm --dir web test tests/EventList.test.tsx
  ```
  Expected: PASS — `Test Files 1 passed (1)`, `Tests 5 passed (5)`.

- [ ] **Step 5: Commit.**
  ```
  git add web/components/EventList.tsx web/tests/EventList.test.tsx
  git commit -m "feat(slice-2): EventList hazard glyph, score, and multi-source badge" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 16: FE — EventDetail hazard label, boost audit, multi-source links, affected exposure

**Files:**
- Modify: `web/components/EventDetail.tsx`
- Test: `web/tests/EventDetail.test.tsx`

**Interfaces:**
- Consumes:
  - `web/lib/presentation.ts` (Task 13): `severityColor(level: string): string`, `hazardLabel(hazard: string): string`, `feedLabel(feed: string): string`, `formatAffected(affected): string`.
  - `web/lib/contract.types.ts` (Task 12): `CrisisEvent` with `hazard`, `magnitude: number|null`, `severity.level`, `severity.score: number`, `severity.boost: { nearest_place: string|null; population: number|null; distance_km: number|null; applied: number }`, `sources: FeedSource[]` (`FeedSource = { feed: "usgs"|"gdacs"; id: string; url: string }`), `affected: { estimate: number|null; basis: string; source: "gdacs"|null }`; `Contract`.
  - `web/components/ProvisionalBadge.tsx` (existing): `ProvisionalBadge({ provisional }: { provisional: boolean })`.
  - `contract/fixtures/contract.v2.example.json` (Task 12) — array order: `[0]` `usgs:us6000severe` (EQ, magnitude present, USGS-only, `affected.estimate: null`); `[1]` `gdacs:1550421` (TC, `magnitude: null`, affected set); `[2]` `usgs:us6000serious` (EQ, merged usgs+gdacs, `boost.applied > 0`, GDACS affected); `[3]` `usgs:us6000minor` (non-major, `boost.applied === 0`, affected null).
- Produces (for Task 17):
  - `EventDetail({ event }: { event: CrisisEvent | null }): JSX.Element` — same signature, reworked body.

> Sequencing fix vs. the draft: the draft's index comments (`merged = events[1]`, `cyclone = events[2]`) contradict the canonical fixture order authored in Task 12 (TC is `[1]`, merged is `[2]`). The test below binds `cyclone = events[1]` and `merged = events[2]` to match the fixture.

Steps:

- [ ] **Step 1: Write the failing v2 test.** Replace the entire contents of `web/tests/EventDetail.test.tsx` with:
  ```tsx
  import { render, screen } from "@testing-library/react";
  import { describe, expect, it } from "vitest";
  import example from "../../contract/fixtures/contract.v2.example.json";
  import type { Contract } from "@/lib/contract.types";
  import { feedLabel, formatAffected, hazardLabel } from "@/lib/presentation";
  import { EventDetail } from "@/components/EventDetail";

  const events = (example as Contract).events;
  const severe = events[0]; // usgs:us6000severe — EQ, magnitude present, USGS-only, affected null
  const cyclone = events[1]; // gdacs:1550421 — TC, magnitude null, affected set
  const merged = events[2]; // usgs:us6000serious — EQ merged usgs+gdacs, boost applied, GDACS affected
  const minor = events[3]; // usgs:us6000minor — non-major, boost.applied === 0, affected null

  describe("EventDetail", () => {
    it("prompts to select when no event is given", () => {
      render(<EventDetail event={null} />);
      expect(screen.getByLabelText("event detail")).toHaveTextContent(/select an event/i);
    });

    it("shows the human hazard label, not the raw code", () => {
      render(<EventDetail event={cyclone} />);
      expect(screen.getByText(hazardLabel(cyclone.hazard))).toBeInTheDocument();
      expect(screen.queryByText(cyclone.hazard)).not.toBeInTheDocument();
    });

    it("shows the severity level and numeric score", () => {
      render(<EventDetail event={merged} />);
      const aside = screen.getByLabelText("event detail");
      expect(aside).toHaveTextContent(/score/i);
      expect(aside).toHaveTextContent(String(merged.severity.score));
      expect(screen.getByText(merged.severity.level)).toBeInTheDocument();
    });

    it("renders one source link per feed for a merged event", () => {
      render(<EventDetail event={merged} />);
      const usgs = merged.sources.find((s) => s.feed === "usgs")!;
      const gdacs = merged.sources.find((s) => s.feed === "gdacs")!;
      expect(screen.getAllByRole("link")).toHaveLength(merged.sources.length);
      expect(screen.getByRole("link", { name: new RegExp(feedLabel("usgs")) })).toHaveAttribute(
        "href",
        usgs.url,
      );
      expect(screen.getByRole("link", { name: new RegExp(feedLabel("gdacs")) })).toHaveAttribute(
        "href",
        gdacs.url,
      );
    });

    it("shows the boost-audit block with nearest place and distance", () => {
      render(<EventDetail event={merged} />);
      const why = screen.getByRole("region", { name: /why this ranks here/i });
      expect(why).toHaveTextContent(merged.severity.boost.nearest_place!);
      expect(why).toHaveTextContent(String(merged.severity.boost.distance_km));
    });

    it("shows the no-boost line without crashing when applied === 0", () => {
      render(<EventDetail event={minor} />);
      const why = screen.getByRole("region", { name: /why this ranks here/i });
      expect(why).toHaveTextContent(/no boost applied/i);
      expect(why).toHaveTextContent(minor.severity.boost.nearest_place!);
    });

    it("shows magnitude for an EQ and hides it for a TC", () => {
      const { unmount } = render(<EventDetail event={severe} />);
      expect(screen.getByText(/magnitude/i)).toBeInTheDocument();
      expect(screen.getByText(String(severe.magnitude))).toBeInTheDocument();
      unmount();
      render(<EventDetail event={cyclone} />);
      expect(screen.queryByText(/magnitude/i)).not.toBeInTheDocument();
    });

    it("shows a GDACS-tagged exposure estimate, and 'Not estimated' when null", () => {
      const { unmount } = render(<EventDetail event={merged} />);
      expect(screen.getByText(formatAffected(merged.affected))).toBeInTheDocument();
      const aside = screen.getByLabelText("event detail");
      expect(aside).toHaveTextContent(/GDACS/);
      expect(aside).toHaveTextContent(/population exposed/i);
      unmount();
      render(<EventDetail event={severe} />);
      expect(screen.getByText(/not estimated/i)).toBeInTheDocument();
    });
  });
  ```

- [ ] **Step 2: Run the test and confirm RED.**
  ```
  pnpm --dir web test tests/EventDetail.test.tsx
  ```
  Expected: FAIL — the "prompts to select" case passes, but the new cases fail: the current component renders the raw code (so `getByText("Tropical Cyclone")` is not found), exposes no `region` named "Why this ranks here", renders only one `<a>USGS source</a>` (so `getAllByRole("link")` length is 1, not 2), and renders no score/magnitude/affected text. `Test Files 1 failed (1)`, `Tests 7 failed | 1 passed (8)`.

- [ ] **Step 3: Rework the component.** Replace the entire contents of `web/components/EventDetail.tsx` with:
  ```tsx
  import type { CrisisEvent } from "@/lib/contract.types";
  import { feedLabel, formatAffected, hazardLabel, severityColor } from "@/lib/presentation";
  import { ProvisionalBadge } from "./ProvisionalBadge";

  export function EventDetail({ event }: { event: CrisisEvent | null }) {
    if (!event) {
      return <aside aria-label="event detail">Select an event</aside>;
    }
    const { boost, level, score } = event.severity;
    return (
      <aside aria-label="event detail">
        <h2>{event.title}</h2>
        <dl>
          <dt>Hazard</dt>
          <dd>{hazardLabel(event.hazard)}</dd>
          <dt>Severity</dt>
          <dd>
            <span style={{ color: severityColor(level) }}>{level}</span>
            {" · score "}
            {score}
          </dd>
          {event.magnitude !== null && (
            <>
              <dt>Magnitude</dt>
              <dd>{event.magnitude}</dd>
            </>
          )}
          <dt>Location</dt>
          <dd>{event.place}</dd>
          <dt>Time</dt>
          <dd>{event.time}</dd>
          <dt>Population exposed</dt>
          <dd>
            <span>{formatAffected(event.affected)}</span>
            <small className="muted">{event.affected.basis}</small>
          </dd>
        </dl>
        <section aria-label="Why this ranks here">
          <h3>Why this ranks here</h3>
          {boost.applied === 0 ? (
            <p>
              nearest population center: {boost.nearest_place} ({boost.distance_km} km) — no boost
              applied
            </p>
          ) : (
            <p>
              +{boost.applied} boost from {boost.nearest_place} ({boost.distance_km} km · pop{" "}
              {boost.population?.toLocaleString()})
            </p>
          )}
        </section>
        <ProvisionalBadge provisional={event.provisional} />
        <ul aria-label="sources">
          {event.sources.map((s) => (
            <li key={`${s.feed}:${s.id}`}>
              <a href={s.url}>{feedLabel(s.feed)} source</a>
            </li>
          ))}
        </ul>
      </aside>
    );
  }
  ```

- [ ] **Step 4: Run the test and confirm GREEN.**
  ```
  pnpm --dir web test tests/EventDetail.test.tsx
  ```
  Expected: PASS — `Test Files 1 passed (1)`, `Tests 8 passed (8)`: human hazard label shown and raw code absent; level + score rendered; both USGS/GDACS source links present with correct `href`s; boost region shows nearest place + distance; the `applied === 0` event renders the "no boost applied" line without crashing; magnitude shown for the EQ and absent for the null-magnitude TC; the GDACS estimate string and the "Not estimated" null case both render.

- [ ] **Step 5: Commit.**
  ```
  git add web/components/EventDetail.tsx web/tests/EventDetail.test.tsx
  git commit -m "feat(slice-2): EventDetail hazard label, boost audit, multi-source links, affected exposure" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 17: FE — per-feed outage banner, MapLegend wiring, and v1 fixture retirement

**Files:**
- Modify: `web/app/page.tsx`
- Test: `web/tests/page.test.tsx`
- Delete: `contract/fixtures/contract.v1.example.json`, `contract/fixtures/contract.v1.no-major.json`, `contract/fixtures/contract.v1.feed-down.json`

**Interfaces:**
- Consumes:
  - `web/lib/presentation.ts` (Task 13): `downFeeds(contract: Contract): string[]`, `feedLabel(feed: string): string`, `defaultMajorEvents(contract: Contract): CrisisEvent[]`.
  - `web/lib/contract.ts` (Task 12): `loadContract(url?: string): Promise<Contract>`.
  - `web/lib/contract.types.ts` (Task 12): `Contract`, `CrisisEvent`.
  - `web/components/MapLegend.tsx` (Task 14): `MapLegend` (no props).
  - `web/components/CrisisMap.tsx` (Task 14): `CrisisMap`; `web/components/EventList.tsx` (Task 15): `EventList`; `web/components/EventDetail.tsx` (Task 16): `EventDetail`.
  - `contract/fixtures/contract.v2.example.json`, `contract.v2.no-major.json`, `contract.v2.feed-down.json` (Task 12).
- Produces:
  - Updated `web/app/page.tsx` — per-feed outage banner (`role="alert"`, from `downFeeds` + `feedLabel`) + `MapLegend` wired into `.map-pane`.

> This task does NOT touch the presentation/CrisisMap/EventList/EventDetail/contract test files — each was migrated in its own task. Its final step deletes the v1 fixtures, which is safe because every suite now reads v2. After this task the whole web suite is green again.

Steps:

- [ ] **Step 1: Write the failing page test.** Replace the entire contents of `web/tests/page.test.tsx` — swap fixtures to v2, add the `MapLegend` stub, re-baseline the button / `data-count` to 3, and add the legend + no-key + per-feed banner assertions:
  ```tsx
  import { render, screen, waitFor } from "@testing-library/react";
  import userEvent from "@testing-library/user-event";
  import { afterEach, describe, expect, it, vi } from "vitest";
  import example from "../../contract/fixtures/contract.v2.example.json";
  import noMajor from "../../contract/fixtures/contract.v2.no-major.json";
  import feedDown from "../../contract/fixtures/contract.v2.feed-down.json";

  // vi.mock factories are hoisted above top-level const declarations, so the mock fn
  // must be created via vi.hoisted to avoid a TDZ ReferenceError at runtime.
  const { loadContract } = vi.hoisted(() => ({ loadContract: vi.fn() }));
  vi.mock("@/lib/contract", () => ({ loadContract, CONTRACT_URL: "/api/contract" }));

  // Stub next/dynamic so the map is a black box here (its own test covers it).
  /* eslint-disable @typescript-eslint/no-explicit-any -- mock props mirror next/dynamic's own loosely-typed component props */
  vi.mock("next/dynamic", () => ({
    default: () => (props: any) => <div data-testid="map-stub" data-count={props.events.length} />,
  }));
  /* eslint-enable @typescript-eslint/no-explicit-any */

  // Stub the legend — its own test covers its content; here we only assert it is wired in.
  vi.mock("@/components/MapLegend", () => ({ MapLegend: () => <div data-testid="map-legend" /> }));

  import Page from "@/app/page";

  afterEach(() => vi.clearAllMocks());

  describe("dashboard page", () => {
    it("renders map + list from the contract, major-only, with no key", async () => {
      loadContract.mockResolvedValue(example);
      render(<Page />);
      await screen.findByLabelText("event list");
      expect(screen.getAllByRole("button").length).toBe(3); // 3 major events, no key entry anywhere
      expect(screen.getByTestId("map-stub")).toHaveAttribute("data-count", "3");
    });

    it("renders the map legend alongside the map", async () => {
      loadContract.mockResolvedValue(example);
      render(<Page />);
      expect(await screen.findByTestId("map-legend")).toBeInTheDocument();
    });

    it("renders the full picture with no BYOK key set", async () => {
      loadContract.mockResolvedValue(example);
      render(<Page />);
      await screen.findByLabelText("event list");
      expect(screen.getByTestId("map-stub")).toBeInTheDocument();
      // Slice 2 renders map/list/detail with no BYOK — there is no key input anywhere.
      expect(screen.queryByRole("textbox")).toBeNull();
    });

    it("syncs selection: clicking a list row fills the detail card", async () => {
      loadContract.mockResolvedValue(example);
      render(<Page />);
      await userEvent.click(await screen.findByText(/M 6.0/));
      expect(screen.getByLabelText("event detail")).toHaveTextContent(/12 km S of Sampletown/);
    });

    it("shows 'no major events' when the default view is empty", async () => {
      loadContract.mockResolvedValue(noMajor);
      render(<Page />);
      expect(await screen.findByText(/no major events/i)).toBeInTheDocument();
    });

    it("shows a per-feed outage banner naming the down feed", async () => {
      loadContract.mockResolvedValue(feedDown);
      render(<Page />);
      expect(await screen.findByRole("alert")).toHaveTextContent(/GDACS unavailable/i);
    });

    it("shows an error state when the contract fails to load", async () => {
      loadContract.mockRejectedValue(new Error("503"));
      render(<Page />);
      await waitFor(() => expect(screen.getByText(/failed to load/i)).toBeInTheDocument());
    });
  });
  ```

- [ ] **Step 2: Run the page test and confirm RED.**
  ```
  pnpm --dir web test tests/page.test.tsx
  ```
  Expected: FAIL — all 7 cases error at import. `web/app/page.tsx` still imports `feedsDown` from `@/lib/presentation`, which Task 13 removed (replaced by `downFeeds`), so Vitest reports `does not provide an export named 'feedsDown'` and `Page` fails to load. `Test Files 1 failed (1)`.

- [ ] **Step 3: Rewrite `web/app/page.tsx`.** Replace the whole file (keeps the existing `useEffect`/`loadContract` flow; swaps `feedsDown` for `downFeeds` + `feedLabel`; wires `MapLegend` inside `.map-pane`):
  ```tsx
  "use client";

  import dynamic from "next/dynamic";
  import { useEffect, useState } from "react";
  import { EventDetail } from "@/components/EventDetail";
  import { EventList } from "@/components/EventList";
  import { MapLegend } from "@/components/MapLegend";
  import type { Contract } from "@/lib/contract.types";
  import { loadContract } from "@/lib/contract";
  import { defaultMajorEvents, downFeeds, feedLabel } from "@/lib/presentation";

  const CrisisMap = dynamic(() => import("@/components/CrisisMap").then((m) => m.CrisisMap), {
    ssr: false,
  });

  export default function Page() {
    const [contract, setContract] = useState<Contract | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [selectedId, setSelectedId] = useState<string | null>(null);

    useEffect(() => {
      loadContract()
        .then(setContract)
        .catch((e: unknown) => setError(String(e)));
    }, []);

    if (error) return <main>Failed to load the crisis picture: {error}</main>;
    if (!contract) return <main>Loading…</main>;

    const visible = defaultMajorEvents(contract);
    const selected = visible.find((e) => e.id === selectedId) ?? null;
    const down = downFeeds(contract);

    return (
      <main>
        {down.length > 0 && (
          <div role="alert">
            {down.map(feedLabel).join(", ")} unavailable — picture may be incomplete.
          </div>
        )}
        <p>Last updated {contract.generated_at}</p>
        <div className="dashboard">
          <div className="map-pane">
            <CrisisMap events={visible} selectedId={selectedId} onSelect={setSelectedId} />
            <MapLegend />
          </div>
          <div className="side-pane">
            {visible.length === 0 ? (
              <p>No major events right now.</p>
            ) : (
              <EventList events={visible} selectedId={selectedId} onSelect={setSelectedId} />
            )}
            <EventDetail event={selected} />
          </div>
        </div>
      </main>
    );
  }
  ```

- [ ] **Step 4: Run the page test and confirm GREEN.**
  ```
  pnpm --dir web test tests/page.test.tsx
  ```
  Expected: PASS — all 7 `dashboard page` tests green (banner reads "GDACS unavailable — picture may be incomplete.", `map-legend` present, 3 buttons + `data-count="3"`, no `textbox`, selection sync fills the detail with "12 km S of Sampletown", no-major and error states render).

- [ ] **Step 5: Run the full web suite and confirm GREEN.** Every suite is now on v2:
  ```
  pnpm --dir web test
  ```
  Expected: PASS — `page`, `presentation`, `contract`, `CrisisMap`, `EventList`, `EventDetail`, `MapLegend` all green.

- [ ] **Step 6: Retire the v1 fixtures (final step — safe now that every suite is on v2).**
  ```
  git rm contract/fixtures/contract.v1.*.json
  ```
  Re-run the suite to prove nothing referenced a deleted fixture:
  ```
  pnpm --dir web test
  ```
  Expected: PASS — unchanged green result; no `Failed to resolve import` for any `contract.v1.*` path.

- [ ] **Step 7: Commit the banner + legend wiring + v1 retirement.**
  ```
  git add web/app/page.tsx web/tests/page.test.tsx contract/fixtures/contract.v1.example.json contract/fixtures/contract.v1.no-major.json contract/fixtures/contract.v1.feed-down.json
  git commit -m "feat(slice-2): per-feed outage banner, MapLegend wiring, retire v1 fixtures" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 18: Docs: deviations log + GDACS field map

**Files:**
- Modify: `implementation-notes.md`
- Modify: `feeds/gdacs.md`
- Test: none (documentation task — no code under test; verified by grep + a final `git show`)

**Interfaces:**
- Consumes (names the doc entries cross-reference, all defined by earlier tasks): `boost.py:compute_boost` and constants `MAX_BOOST/CAPITAL_BONUS/BOOST_CAP/BOOST_RADIUS_KM`; `severity.py:base_signal`, `level_for`, `is_major`, `MAJOR_CUTOFF`; `severity.inputs` keys `{"mag","sig","alert","alert_score"}`; `merge.py:FEED_PRIORITY=("usgs","gdacs")`; `affected.py:extract_exposure(hazard, detail_json) -> tuple[int|None, str]` and its per-hazard field map; `contract.py:SCHEMA_VERSION="2.0.0"`; `api/contract.py` two-phase Orange/Red detail fetch.
- Produces: no code symbols (documentation only). Downstream consumers: none.

- [ ] **Step 1: Append the Slice 2 deviations + bookkeeping block to `implementation-notes.md`.**
  The current Deviations section ends with entry `(f)` on the last line of the file. Append a new `### Slice 2 (Task 18)` subsection after it. Edit `C:\Users\ngwei\OneDrive\Desktop\Workbench\hadr-starter\implementation-notes.md`:

  old_string:
  ```
    `react-leaflet`/`next/dynamic` (`@typescript-eslint/no-explicit-any`).
  ```
  new_string:
  ```
    `react-leaflet`/`next/dynamic` (`@typescript-eslint/no-explicit-any`).

### Slice 2 (Tasks 1–18)

- **ADR 0003 boost gap CLOSED (bookkeeping — no ADR change).** The newsworthiness
  boost was accepted "from v1" in ADR 0003 but was **absent and unlogged** through
  Slice 1. Slice 2 lands it: `severity.score = base_signal + boost.applied` and an
  auditable `severity.boost` object (`pipeline/pipeline/boost.py`,
  `MAX_BOOST/CAPITAL_BONUS/BOOST_CAP/BOOST_RADIUS_KM`). ADR 0003 is now *honored*,
  not changed — no superseding ADR needed. (Spec §10.1, §7.2; ADR 0003.)
- **Deviation (d) hazard glyph CLOSED.** Slice 1 (d) deferred the map glyph "until a
  second hazard type is ingested." GDACS (EQ/TC/FL/VO/DR) makes that true, so the
  2-letter hazard glyph on `CrisisMap` markers + the new `MapLegend` now ship.
  (Spec §10.2, §8.)
- **New — GDACS detail fetch for `affected`.** Departs from Slice 1's list-only
  ingest: the EVENTS4APP list carries no population, so `pipeline/api/contract.py`
  makes bounded per-event `geteventdata` GETs (Orange/Red only — the sole events that
  can clear `major` and be displayed) to source the verbatim exposure figure via
  `affected.py:extract_exposure`. Per-hazard *physical* metrics (wind/flood-area/VEI)
  stay deferred. Grounded, never computed. (Spec §10.3, §7.5; ADR 0007.)
- **New — `severity.inputs` reshaped under the 2.0.0 bump.** Gained `alert_score`;
  `mag`/`sig`/`alert` are now all nullable and always-present (keys
  `{"mag","sig","alert","alert_score"}`). EQ identity is preserved **semantically**
  (level, `major`, and the values of mag/sig/alert), not as literal byte-identity of
  the v1 object — legitimate under a breaking bump; locked decision 3 freezes only the
  4-value `level` band. (Spec §10.4, §4.1.)
- **New — top-level `magnitude` is now `number|null`, always present** (null for
  TC/FL/VO/DR) rather than the v1 EQ-only required number. Uniform with the
  always-present `boost`/`affected`; the front end guards null and sizes markers off
  `severity.score` (`markerRadius`). (Spec §10.5, §4.1.)
- **Contained tension logged — v1 "green EQ → major" quirk preserved.** EQ
  `base_signal` is constructed so `base_signal ≥ 60 ⇔ old is_major`, which keeps the
  v1 quirk that a green-alert EQ can be `major`. This conflicts with ADR 0003's
  "hide green" applied to GDACS-sourced green colours on the non-EQ path (`colour_base`
  green = 45 < `MAJOR_CUTOFF` 60). **If kept long-term this needs a superseding ADR;**
  Slice 2 only logs it and revisits under ADR 0003 tuning. (Spec §10.6, §7.3;
  ADR 0003.)
- **New — canonical `id` can churn `gdacs:… → usgs:…`.** A GDACS-only event that later
  gains a USGS match flips its canonical `id` to the USGS one
  (`merge.py:FEED_PRIORITY = ("usgs","gdacs")`, present-wins). Acceptable this slice
  because revisions / history / id-stability across runs are out of scope. (Spec
  §10.7, §7.4.)
- **`feeds/gdacs.md` updated.** Documented the `geteventdata` detail feed's per-hazard
  exposure fields and corrected the truncated sample's implication that population
  lives in the EVENTS4APP list feed (it does not). (Spec §10.8, §7.5.)
  ```

- [ ] **Step 2: Document the GDACS detail feed and correct the list-feed population implication in `feeds/gdacs.md`.**
  Insert a clarifying note plus a `## Detail feed (geteventdata)` section immediately after the example response and before `## Open questions`. Edit `C:\Users\ngwei\OneDrive\Desktop\Workbench\hadr-starter\feeds\gdacs.md`:

  old_string:
  ```
  ## Open questions
  ```
  new_string:
  ```
  > **Note — the list feed carries no population / exposure figure.** EVENTS4APP gives
  > only the colour signal (`alertlevel` / `alertscore`). The truncated sample above has
  > no population field, and none exists in the list feed — do not read exposure off it.
  > Any affected-population number comes from the per-event **detail feed** below.

  ## Detail feed (`geteventdata`) — population exposure

  Per-event detail hangs off `properties.url.details`:

      https://www.gdacs.org/gdacsapi/api/events/geteventdata?eventtype=EQ&eventid=1550421

  The affected-population estimate is **GDACS's own** and is carried **verbatim** into
  the contract's `affected` block (never recomputed — ADR 0007). Slice 2 captured one
  detail fixture per hazard and pinned the exposure field for each. The canonical map
  lives in `pipeline/pipeline/affected.py` (`extract_exposure`); reconcile to it if any
  field string below drifts.

  | Hazard | Exposure count (detail JSON)      | Basis text (detail JSON)                | Notes |
  |--------|-----------------------------------|-----------------------------------------|-------|
  | EQ     | `earthquakedetails.rapidpop`      | `earthquakedetails.rapidpopdescription` | API-verified (e.g. 43996 → "…in MMI IV"). |
  | TC     | `severitydata.population`         | `severitydata.severitytext`             | Population in the wind-exposure band. |
  | FL     | `severitydata.population`         | `severitydata.severitytext`             | Population in the flood footprint. |
  | VO     | `severitydata.population`         | `severitydata.severitytext`             | Population within the affected radius. |
  | DR     | — (GDACS publishes no count)      | —                                       | → `affected.estimate: null` + documented reason. |

  Only **Orange/Red** events are detail-fetched (§7.5): they are the only ones that can
  clear the `major` gate and be displayed. Any detail-fetch failure degrades to
  `affected.estimate: null` + a reason basis — it never blocks the build. Wording is
  always **"population exposed," never "affected / casualties"**: `rapidpop` measures
  exposure, not impact (ADR 0007).

  ## Open questions
  ```

- [ ] **Step 3: Verify both edits landed.** Run:
  ```
  cd "C:/Users/ngwei/OneDrive/Desktop/Workbench/hadr-starter" && grep -c "Slice 2 (Tasks 1–18)" implementation-notes.md && grep -c "Detail feed (\`geteventdata\`)" feeds/gdacs.md && grep -c "list feed carries no population" feeds/gdacs.md
  ```
  Expected output — three lines, each `1` (the new deviations heading present once, the new detail-feed heading present once, the list-feed correction note present once).

- [ ] **Step 4: Commit the docs.** Run:
  ```
  cd "C:/Users/ngwei/OneDrive/Desktop/Workbench/hadr-starter" && git add implementation-notes.md feeds/gdacs.md && git commit -m "chore(slice-2): log Slice 2 deviations + document GDACS detail exposure fields

- append 8 deviation/bookkeeping entries: ADR 0003 boost gap closed, glyph
  deviation (d) closed, GDACS detail fetch, severity.inputs reshape, magnitude
  now number|null, green-EQ->major tension, canonical id churn, gdacs.md update
  (spec §10)
- feeds/gdacs.md: document geteventdata per-hazard exposure field map and correct
  the list-feed population implication (spec §7.5)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```
  Expected output — a commit summary line reporting `2 files changed` (both `implementation-notes.md` and `feeds/gdacs.md`), with insertions and no deletions.
