# Slice 1 — USGS → Contract v1 → Map — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the walking skeleton — ingest USGS earthquakes, emit a versioned JSON contract, and render current major quakes on a world map — end to end, TDD'd against the contract seam.

**Architecture:** Three units joined only by `contract/` (a JSON Schema + golden fixtures). A pure Python core (`build_contract`) turns saved/fetched USGS GeoJSON into contract v1; a thin Vercel Python route `/api/contract` is the only network-touching adapter; a Next.js app is the sole, read-only consumer, with TS types generated from the same schema. The pipeline output is *validated against* the schema and the front end's types are *generated from* it, so drift is impossible by construction.

**Tech Stack:** Python 3.12 · uv · ruff · mypy (strict) · httpx · jsonschema (dev) · pytest. Next.js App Router · pnpm · TypeScript (strict) · Tailwind + shadcn/ui · react-leaflet + OSM · Vitest + React Testing Library · json-schema-to-typescript.

## Global Constraints

Every task's requirements implicitly include these (exact values from the spec / CLAUDE.md):

- **Python** 3.12; dependencies + venv via **uv** (`pyproject.toml` + committed `uv.lock`); lint/format **ruff**; types **mypy** with hints on public functions; HTTP via **httpx**. Keep feed parsers **separate and swappable** (one module per source).
- **Front end**: package manager **pnpm** (committed `pnpm-lock.yaml`); Node pinned via **`.nvmrc`**; TypeScript **strict**; lint/format ESLint (next) + Prettier; map via **react-leaflet + OSM tiles, no key**.
- **One boundary**: the versioned **`contract/schema/contract.v1.schema.json`**; `schema_version` is `"1.0.0"`; bump on any breaking change. No shared runtime code crosses the seam.
- **Determinism is model-free**: no model calls anywhere in Slice 1 (the Embedder and all AI are out of scope).
- **Testing**: test external behaviour at the highest seam — Pipeline `uv run pytest` (feed fixtures → assert emitted contract); Front end `pnpm test` (contract fixture → assert render, including no-key). **Mock only network edges** (here: `httpx` and the browser `fetch`); **control** (never mock) the clock — pass `now` in.
- **Contract semantics** (frozen in the spec §3): canonical id `"<feed>:<sourceId>"`; same-source **union-by-id** across the two USGS windows (higher `updated` wins); carry **every** quake, flagged `major`; front end renders `major:true` by default; all times **ISO-8601 UTC**; a feature missing `mag`/coords/`time` is **skipped defensively**.
- **Deviations** from the PRD/issue are logged in `implementation-notes.md` (Task 12).

**Parallelization:** Task 1 freezes the seam. After it, the **pipeline track (Tasks 2–6)** and **front-end track (Tasks 7–11)** depend only on the committed `contract/` and are fully independent — run them in parallel git worktrees. **Task 12** integrates and verifies e2e.

---

### Task 1: Freeze the seam — contract v1 schema, golden fixtures, pipeline test harness

**Files:**
- Create: `pipeline/pyproject.toml`
- Create: `pipeline/pipeline/__init__.py` (empty)
- Create: `pipeline/tests/__init__.py` (empty)
- Create: `contract/schema/contract.v1.schema.json`
- Create: `contract/fixtures/contract.v1.example.json`
- Create: `contract/fixtures/contract.v1.no-major.json`
- Create: `contract/fixtures/contract.v1.feed-down.json`
- Test: `pipeline/tests/test_contract_schema.py`

**Interfaces:**
- Produces: the committed contract seam. The schema's `$defs` are titled **`Contract`** (root), **`CrisisEvent`**, **`Severity`**, **`Geometry`**, **`FeedSource`**, **`FeedHealth`** — these titles become the generated TS interface names in Task 7 (note `CrisisEvent`/`FeedSource`, chosen to avoid clashing with the DOM globals `Event`/`EventSource`).

- [ ] **Step 1: Scaffold the pipeline project**

Create `pipeline/pyproject.toml` by hand (avoids depending on any `uv init` flag). `[tool.uv] package = false` marks this a non-installable application so `uv sync` only resolves deps:

```toml
[project]
name = "pipeline"
version = "0.1.0"
description = "HADR pipeline — USGS ingest to contract v1"
requires-python = ">=3.12"
dependencies = ["httpx>=0.27"]

[tool.uv]
package = false

[dependency-groups]
dev = ["pytest>=8", "ruff>=0.5", "mypy>=1.10", "jsonschema>=4.21"]

[tool.ruff]
line-length = 100

[tool.mypy]
python_version = "3.12"
strict = true

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

Then run `cd pipeline && uv sync` (creates `.venv` + `uv.lock`). Create empty `pipeline/pipeline/__init__.py` and `pipeline/tests/__init__.py`.

- [ ] **Step 2: Write the failing test**

`pipeline/tests/test_contract_schema.py`:

```python
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

CONTRACT = Path(__file__).resolve().parents[2] / "contract"
SCHEMA = CONTRACT / "schema" / "contract.v1.schema.json"
FIXTURES = [
    "contract.v1.example.json",
    "contract.v1.no-major.json",
    "contract.v1.feed-down.json",
]


def _schema() -> dict:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def test_schema_is_valid_draft_2020_12() -> None:
    Draft202012Validator.check_schema(_schema())


@pytest.mark.parametrize("name", FIXTURES)
def test_fixture_validates_against_schema(name: str) -> None:
    instance = json.loads((CONTRACT / "fixtures" / name).read_text(encoding="utf-8"))
    Draft202012Validator(_schema()).validate(instance)


def test_example_has_a_provisional_and_a_nonmajor_event() -> None:
    events = json.loads((CONTRACT / "fixtures" / "contract.v1.example.json").read_text("utf-8"))["events"]
    assert any(e["provisional"] for e in events), "need a provisional event to exercise the badge"
    assert any(not e["major"] for e in events), "need a below-threshold event carried in the contract"
    assert any(e["major"] for e in events), "need a major event for the default view"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd pipeline && uv run pytest tests/test_contract_schema.py -v`
Expected: FAIL — `FileNotFoundError` (schema/fixtures don't exist yet).

- [ ] **Step 4: Create the schema**

`contract/schema/contract.v1.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://hadr.example/contract.v1.schema.json",
  "title": "Contract",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version", "generated_at", "meta", "events"],
  "properties": {
    "schema_version": { "const": "1.0.0" },
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
        "source": { "type": "string", "enum": ["usgs"] },
        "window": { "type": "string", "enum": ["all_day", "significant_week"] },
        "status": { "type": "string", "enum": ["ok", "error"] },
        "fetched_at": { "type": "string", "format": "date-time" },
        "event_count": { "type": "integer", "minimum": 0 },
        "error": { "type": "string" }
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
    "Severity": {
      "title": "Severity",
      "type": "object",
      "additionalProperties": false,
      "required": ["level", "inputs"],
      "properties": {
        "level": { "type": "string", "enum": ["minor", "moderate", "serious", "severe"] },
        "inputs": {
          "type": "object",
          "additionalProperties": false,
          "required": ["mag", "sig", "alert"],
          "properties": {
            "mag": { "type": "number" },
            "sig": { "type": ["integer", "null"] },
            "alert": { "type": ["string", "null"], "enum": ["green", "yellow", "orange", "red", null] }
          }
        }
      }
    },
    "FeedSource": {
      "title": "FeedSource",
      "type": "object",
      "additionalProperties": false,
      "required": ["feed", "id", "url"],
      "properties": {
        "feed": { "type": "string", "enum": ["usgs"] },
        "id": { "type": "string" },
        "url": { "type": "string", "format": "uri" }
      }
    },
    "CrisisEvent": {
      "title": "CrisisEvent",
      "type": "object",
      "additionalProperties": false,
      "required": ["id", "hazard", "title", "place", "time", "geometry", "magnitude", "severity", "major", "provisional", "sources"],
      "properties": {
        "id": { "type": "string", "pattern": "^[a-z]+:.+" },
        "hazard": { "type": "string", "enum": ["EQ"] },
        "title": { "type": "string" },
        "place": { "type": "string" },
        "time": { "type": "string", "format": "date-time" },
        "geometry": { "$ref": "#/$defs/Geometry" },
        "magnitude": { "type": "number" },
        "severity": { "$ref": "#/$defs/Severity" },
        "major": { "type": "boolean" },
        "provisional": { "type": "boolean" },
        "sources": { "type": "array", "minItems": 1, "items": { "$ref": "#/$defs/FeedSource" } }
      }
    }
  }
}
```

- [ ] **Step 5: Create the three fixtures**

`contract/fixtures/contract.v1.example.json` (both feeds ok; a severe provisional major, a serious major, a minor non-major):

```json
{
  "schema_version": "1.0.0",
  "generated_at": "2026-07-08T12:00:00Z",
  "meta": {
    "feeds": [
      { "source": "usgs", "window": "all_day", "status": "ok", "fetched_at": "2026-07-08T12:00:00Z", "event_count": 3 },
      { "source": "usgs", "window": "significant_week", "status": "ok", "fetched_at": "2026-07-08T12:00:00Z", "event_count": 1 }
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
      "severity": { "level": "severe", "inputs": { "mag": 7.1, "sig": 1200, "alert": "red" } },
      "major": true,
      "provisional": true,
      "sources": [ { "feed": "usgs", "id": "us6000severe", "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us6000severe" } ]
    },
    {
      "id": "usgs:us6000serious",
      "hazard": "EQ",
      "title": "M 6.0 - 12 km S of Sampletown",
      "place": "12 km S of Sampletown",
      "time": "2026-07-08T06:30:00Z",
      "geometry": { "lat": 35.7, "lon": 139.7, "depth_km": 10.0 },
      "magnitude": 6.0,
      "severity": { "level": "serious", "inputs": { "mag": 6.0, "sig": 640, "alert": null } },
      "major": true,
      "provisional": false,
      "sources": [ { "feed": "usgs", "id": "us6000serious", "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us6000serious" } ]
    },
    {
      "id": "usgs:us6000minor",
      "hazard": "EQ",
      "title": "M 3.2 - 5 km NE of Quietville",
      "place": "5 km NE of Quietville",
      "time": "2026-07-08T11:00:00Z",
      "geometry": { "lat": 34.0, "lon": -118.2, "depth_km": 8.0 },
      "magnitude": 3.2,
      "severity": { "level": "minor", "inputs": { "mag": 3.2, "sig": 158, "alert": null } },
      "major": false,
      "provisional": false,
      "sources": [ { "feed": "usgs", "id": "us6000minor", "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us6000minor" } ]
    }
  ]
}
```

`contract/fixtures/contract.v1.no-major.json` (feeds ok, only a below-threshold event → default view empty):

```json
{
  "schema_version": "1.0.0",
  "generated_at": "2026-07-08T12:00:00Z",
  "meta": {
    "feeds": [
      { "source": "usgs", "window": "all_day", "status": "ok", "fetched_at": "2026-07-08T12:00:00Z", "event_count": 1 },
      { "source": "usgs", "window": "significant_week", "status": "ok", "fetched_at": "2026-07-08T12:00:00Z", "event_count": 0 }
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
      "severity": { "level": "minor", "inputs": { "mag": 2.4, "sig": 89, "alert": null } },
      "major": false,
      "provisional": false,
      "sources": [ { "feed": "usgs", "id": "us6000quiet", "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us6000quiet" } ]
    }
  ]
}
```

`contract/fixtures/contract.v1.feed-down.json` (both windows failed → empty events + error meta):

```json
{
  "schema_version": "1.0.0",
  "generated_at": "2026-07-08T12:00:00Z",
  "meta": {
    "feeds": [
      { "source": "usgs", "window": "all_day", "status": "error", "fetched_at": "2026-07-08T12:00:00Z", "event_count": 0, "error": "HTTP 503" },
      { "source": "usgs", "window": "significant_week", "status": "error", "fetched_at": "2026-07-08T12:00:00Z", "event_count": 0, "error": "HTTP 503" }
    ]
  },
  "events": []
}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd pipeline && uv run pytest tests/test_contract_schema.py -v`
Expected: PASS (schema valid; 3 fixtures conform; example has provisional + non-major + major).

- [ ] **Step 7: Commit**

```bash
git add contract/ pipeline/pyproject.toml pipeline/uv.lock pipeline/pipeline/__init__.py pipeline/tests/__init__.py pipeline/tests/test_contract_schema.py
git commit -m "feat(contract): freeze contract v1 schema + golden fixtures + pipeline harness"
```

---

### Task 2: USGS parser — GeoJSON → normalized EQ records

**Files:**
- Create: `pipeline/pipeline/models.py`
- Create: `pipeline/pipeline/feeds/__init__.py` (empty)
- Create: `pipeline/pipeline/feeds/usgs.py`
- Create: `pipeline/tests/fixtures/usgs_all_day.json`
- Create: `pipeline/tests/fixtures/usgs_significant_week.json`
- Test: `pipeline/tests/test_usgs_parser.py`

**Interfaces:**
- Produces: `NormalizedQuake` dataclass (frozen) and `parse_usgs(feed_json: dict) -> list[NormalizedQuake]`.
- `NormalizedQuake` fields: `source_id: str, title: str, place: str, time: datetime, updated: datetime, lat: float, lon: float, depth_km: float | None, mag: float, sig: int | None, alert: str | None, status: str, url: str`.

- [ ] **Step 1: Write the failing test**

`pipeline/tests/test_usgs_parser.py`:

```python
from datetime import datetime, timezone

from pipeline.feeds.usgs import parse_usgs


EPOCH_MS = 1_735_689_600_000  # 2025-01-01T00:00:00Z (clean, easily verified)


def _feature(**props):
    return {
        "type": "Feature",
        "id": props.pop("id", "usgsX"),
        "properties": {"time": EPOCH_MS, "updated": EPOCH_MS + 3_600_000,
                       "title": "M 5.0", "place": "somewhere", "status": "reviewed",
                       "mag": 5.0, "sig": 400, "alert": None, "url": "http://u", **props},
        "geometry": {"type": "Point", "coordinates": [10.0, 20.0, 5.0]},
    }


def test_parses_core_fields_and_utc_times():
    q = parse_usgs({"features": [_feature(id="us1")]})[0]
    assert q.source_id == "us1"
    assert q.lat == 20.0 and q.lon == 10.0 and q.depth_km == 5.0  # note: coords are [lon, lat, depth]
    assert q.mag == 5.0 and q.sig == 400 and q.alert is None and q.status == "reviewed"
    assert q.time == datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    assert q.time.tzinfo == timezone.utc


def test_keeps_null_alert_and_reads_status():
    q = parse_usgs({"features": [_feature(alert="orange", status="automatic")]})[0]
    assert q.alert == "orange" and q.status == "automatic"


def test_skips_features_missing_mag_or_coords_or_time():
    feats = [
        _feature(id="ok"),
        {"id": "nomag", "properties": {"time": 1, "updated": 1, "mag": None}, "geometry": {"coordinates": [1, 2]}},
        {"id": "nocoords", "properties": {"time": 1, "updated": 1, "mag": 5.0}, "geometry": {"coordinates": []}},
        {"id": "notime", "properties": {"time": None, "updated": 1, "mag": 5.0}, "geometry": {"coordinates": [1, 2]}},
    ]
    ids = [q.source_id for q in parse_usgs({"features": feats})]
    assert ids == ["ok"]


def test_empty_feature_collection_yields_nothing():
    assert parse_usgs({"features": []}) == []
    assert parse_usgs({}) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd pipeline && uv run pytest tests/test_usgs_parser.py -v`
Expected: FAIL — `ModuleNotFoundError: pipeline.feeds.usgs`.

- [ ] **Step 3: Write the models**

`pipeline/pipeline/models.py`:

```python
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class NormalizedQuake:
    """A single earthquake normalized from a feed, independent of any source's wire format."""

    source_id: str
    title: str
    place: str
    time: datetime
    updated: datetime
    lat: float
    lon: float
    depth_km: float | None
    mag: float
    sig: int | None
    alert: str | None
    status: str
    url: str
```

- [ ] **Step 4: Write the parser**

`pipeline/pipeline/feeds/usgs.py`:

```python
"""USGS earthquake GeoJSON parser. Kept separate and swappable (one module per source)."""

from datetime import datetime, timezone
from typing import Any

from pipeline.models import NormalizedQuake


def _from_ms(ms: int | float) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def parse_usgs(feed_json: dict[str, Any]) -> list[NormalizedQuake]:
    """Turn a USGS GeoJSON FeatureCollection into normalized quakes.

    Features missing magnitude, coordinates, an origin time, or an id are skipped
    defensively rather than crashing the whole parse.
    """
    out: list[NormalizedQuake] = []
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
            NormalizedQuake(
                source_id=str(source_id),
                title=props.get("title") or "",
                place=props.get("place") or "",
                time=_from_ms(time_ms),
                updated=_from_ms(updated_ms),
                lat=float(coords[1]),
                lon=float(coords[0]),
                depth_km=float(depth) if depth is not None else None,
                mag=float(mag),
                sig=props.get("sig"),
                alert=props.get("alert"),
                status=props.get("status") or "",
                url=props.get("url") or f"https://earthquake.usgs.gov/earthquakes/eventpage/{source_id}",
            )
        )
    return out
```

- [ ] **Step 5: Create small real-shaped feed fixtures**

Save trimmed **real** USGS samples (2–4 features each; fetch once from the live endpoints and cut down). `pipeline/tests/fixtures/usgs_all_day.json` must include: one M≥7 with `alert:"red"` and `status:"automatic"`; one below-threshold quake (e.g. M3.2, `alert:null`); and one quake whose `id` **also appears** in `usgs_significant_week.json` with a **higher `updated`** (to exercise union-by-id in Task 4/5). `usgs_significant_week.json` includes that shared-`id` quake (lower `updated`) plus one unique M≥6. Keep each a valid `{"type":"FeatureCollection","features":[...]}`. (Trimmed real payloads — not asserted field-by-field here; they drive Tasks 4–5.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd pipeline && uv run pytest tests/test_usgs_parser.py -v`
Expected: PASS (4 tests).

- [ ] **Step 7: Commit**

```bash
git add pipeline/pipeline/models.py pipeline/pipeline/feeds/ pipeline/tests/test_usgs_parser.py pipeline/tests/fixtures/usgs_all_day.json pipeline/tests/fixtures/usgs_significant_week.json
git commit -m "feat(pipeline): USGS GeoJSON parser -> normalized quakes"
```

---

### Task 3: Severity band + `major` gate (pure)

**Files:**
- Create: `pipeline/pipeline/severity.py`
- Test: `pipeline/tests/test_severity.py`

**Interfaces:**
- Produces: `severity_level(mag: float, sig: int | None, alert: str | None) -> str` returning one of `"minor" | "moderate" | "serious" | "severe"`; and `is_major(mag: float, sig: int | None, alert: str | None) -> bool`.

- [ ] **Step 1: Write the failing test**

`pipeline/tests/test_severity.py`:

```python
import pytest

from pipeline.severity import is_major, severity_level


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
    ],
)
def test_severity_bands(mag, sig, alert, level):
    assert severity_level(mag, sig, alert) == level


@pytest.mark.parametrize(
    "mag,sig,alert,expected",
    [
        (5.5, 0, None, True),        # mag threshold, inclusive
        (5.49, 0, None, False),
        (4.0, 600, None, True),      # sig threshold, inclusive
        (4.0, 599, None, False),
        (4.0, 0, "green", True),     # any non-null alert
        (4.0, None, None, False),    # null sig, null alert
    ],
)
def test_major_gate(mag, sig, alert, expected):
    assert is_major(mag, sig, alert) is expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd pipeline && uv run pytest tests/test_severity.py -v`
Expected: FAIL — `ModuleNotFoundError: pipeline.severity`.

- [ ] **Step 3: Write the implementation**

`pipeline/pipeline/severity.py`:

```python
"""Deterministic earthquake severity band and `major` gate (ADR 0003, base signal only)."""

Level = str  # one of: "minor" | "moderate" | "serious" | "severe"


def severity_level(mag: float, sig: int | None, alert: str | None) -> Level:
    s = sig or 0
    if alert in ("orange", "red") or mag >= 7.0 or s >= 1000:
        return "severe"
    if alert == "yellow" or mag >= 6.0 or s >= 600:
        return "serious"
    if mag >= 4.5 or s >= 300:
        return "moderate"
    return "minor"


def is_major(mag: float, sig: int | None, alert: str | None) -> bool:
    return mag >= 5.5 or (sig or 0) >= 600 or alert is not None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd pipeline && uv run pytest tests/test_severity.py -v`
Expected: PASS (16 parametrized cases).

- [ ] **Step 5: Commit**

```bash
git add pipeline/pipeline/severity.py pipeline/tests/test_severity.py
git commit -m "feat(pipeline): deterministic severity band + major gate"
```

---

### Task 4: Dedup — same-source union-by-id

**Files:**
- Create: `pipeline/pipeline/dedup.py`
- Test: `pipeline/tests/test_dedup.py`

**Interfaces:**
- Consumes: `NormalizedQuake` (Task 2).
- Produces: `union_by_id(quakes: Iterable[NormalizedQuake]) -> list[NormalizedQuake]` — one record per `source_id`, the one with the highest `updated` winning. Order not guaranteed (callers sort).

- [ ] **Step 1: Write the failing test**

`pipeline/tests/test_dedup.py`:

```python
from datetime import datetime, timezone

from pipeline.dedup import union_by_id
from pipeline.models import NormalizedQuake


def _q(source_id: str, updated_min: int, mag: float = 5.0) -> NormalizedQuake:
    return NormalizedQuake(
        source_id=source_id, title="t", place="p",
        time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated=datetime(2026, 1, 1, minute=updated_min, tzinfo=timezone.utc),
        lat=0.0, lon=0.0, depth_km=None, mag=mag, sig=None, alert=None,
        status="reviewed", url="http://u",
    )


def test_collapses_same_id_keeping_higher_updated():
    old = _q("shared", updated_min=1, mag=5.0)
    new = _q("shared", updated_min=9, mag=5.4)
    result = union_by_id([old, new])
    assert len(result) == 1
    assert result[0].mag == 5.4  # the newer record won


def test_distinct_ids_all_survive():
    result = union_by_id([_q("a", 1), _q("b", 1)])
    assert {q.source_id for q in result} == {"a", "b"}


def test_empty_input():
    assert union_by_id([]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd pipeline && uv run pytest tests/test_dedup.py -v`
Expected: FAIL — `ModuleNotFoundError: pipeline.dedup`.

- [ ] **Step 3: Write the implementation**

`pipeline/pipeline/dedup.py`:

```python
"""Same-source union-by-id — the degenerate case of dedup for a single feed across windows.

This is NOT cross-feed dedup (out of scope for Slice 1); it only collapses the overlap
between the USGS `all_day` and `significant_week` windows, which report the same quake.
"""

from collections.abc import Iterable

from pipeline.models import NormalizedQuake


def union_by_id(quakes: Iterable[NormalizedQuake]) -> list[NormalizedQuake]:
    best: dict[str, NormalizedQuake] = {}
    for q in quakes:
        current = best.get(q.source_id)
        if current is None or q.updated > current.updated:
            best[q.source_id] = q
    return list(best.values())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd pipeline && uv run pytest tests/test_dedup.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline/pipeline/dedup.py pipeline/tests/test_dedup.py
git commit -m "feat(pipeline): same-source union-by-id dedup"
```

---

### Task 5: Assemble the contract — `event_from_quake` + `build_contract`

**Files:**
- Create: `pipeline/pipeline/contract.py`
- Create: `pipeline/pipeline/build.py`
- Test: `pipeline/tests/test_build_contract.py`

**Interfaces:**
- Consumes: `parse_usgs` (T2), `severity_level`/`is_major` (T3), `union_by_id` (T4), `NormalizedQuake` (T2).
- Produces:
  - `to_iso(dt: datetime) -> str` (in `contract.py`) — UTC ISO-8601 with a trailing `Z`.
  - `event_from_quake(q: NormalizedQuake) -> dict` (in `contract.py`).
  - `WindowFetch` dataclass (frozen) in `build.py`: `window: str, ok: bool, payload: dict | None, error: str | None, fetched_at: datetime`.
  - `build_contract(fetches: list[WindowFetch], now: datetime) -> dict` (in `build.py`) — the pure core; deterministic; no network; `now` is injected.

- [ ] **Step 1: Write the failing test**

`pipeline/tests/test_build_contract.py`:

```python
import json
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator

from pipeline.build import WindowFetch, build_contract

CONTRACT = Path(__file__).resolve().parents[2] / "contract"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
NOW = datetime(2026, 7, 8, 12, 0, 0, tzinfo=timezone.utc)


def _schema() -> dict:
    return json.loads((CONTRACT / "schema" / "contract.v1.schema.json").read_text("utf-8"))


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text("utf-8"))


def _fetch(window: str, ok: bool = True, payload: dict | None = None, error: str | None = None) -> WindowFetch:
    return WindowFetch(window=window, ok=ok, payload=payload, error=error, fetched_at=NOW)


def test_emits_schema_valid_contract_from_both_windows():
    contract = build_contract(
        [_fetch("all_day", payload=_load("usgs_all_day.json")),
         _fetch("significant_week", payload=_load("usgs_significant_week.json"))],
        NOW,
    )
    Draft202012Validator(_schema()).validate(contract)
    assert contract["schema_version"] == "1.0.0"
    assert contract["generated_at"] == "2026-07-08T12:00:00Z"
    assert {f["window"] for f in contract["meta"]["feeds"]} == {"all_day", "significant_week"}


def test_union_by_id_across_windows_yields_no_duplicate_ids():
    contract = build_contract(
        [_fetch("all_day", payload=_load("usgs_all_day.json")),
         _fetch("significant_week", payload=_load("usgs_significant_week.json"))],
        NOW,
    )
    ids = [e["id"] for e in contract["events"]]
    assert len(ids) == len(set(ids))  # the shared quake appears once


def test_flags_and_ids_and_provisional_are_correct():
    contract = build_contract([_fetch("all_day", payload=_load("usgs_all_day.json"))], NOW)
    by_severity = {e["severity"]["level"] for e in contract["events"]}
    assert "severe" in by_severity
    assert all(e["id"].startswith("usgs:") for e in contract["events"])
    assert any(e["provisional"] for e in contract["events"])  # the automatic M7 red
    assert any(not e["major"] for e in contract["events"])    # the below-threshold quake
    assert all(e["hazard"] == "EQ" for e in contract["events"])


def test_events_sorted_newest_first():
    contract = build_contract([_fetch("all_day", payload=_load("usgs_all_day.json"))], NOW)
    times = [e["time"] for e in contract["events"]]
    assert times == sorted(times, reverse=True)


def test_one_window_down_still_emits_other_and_marks_meta():
    contract = build_contract(
        [_fetch("all_day", payload=_load("usgs_all_day.json")),
         _fetch("significant_week", ok=False, error="HTTP 503")],
        NOW,
    )
    Draft202012Validator(_schema()).validate(contract)
    meta = {f["window"]: f for f in contract["meta"]["feeds"]}
    assert meta["significant_week"]["status"] == "error"
    assert meta["significant_week"]["error"] == "HTTP 503"
    assert meta["all_day"]["status"] == "ok"
    assert len(contract["events"]) > 0


def test_all_windows_down_yields_empty_events():
    contract = build_contract(
        [_fetch("all_day", ok=False, error="HTTP 503"),
         _fetch("significant_week", ok=False, error="HTTP 503")],
        NOW,
    )
    Draft202012Validator(_schema()).validate(contract)
    assert contract["events"] == []
    assert all(f["status"] == "error" for f in contract["meta"]["feeds"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd pipeline && uv run pytest tests/test_build_contract.py -v`
Expected: FAIL — `ModuleNotFoundError: pipeline.build`.

- [ ] **Step 3: Write `contract.py`**

`pipeline/pipeline/contract.py`:

```python
"""Map a normalized quake to a contract event, and time formatting for the contract."""

from datetime import datetime, timezone
from typing import Any

from pipeline.models import NormalizedQuake
from pipeline.severity import is_major, severity_level

SCHEMA_VERSION = "1.0.0"


def to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def event_from_quake(q: NormalizedQuake) -> dict[str, Any]:
    return {
        "id": f"usgs:{q.source_id}",
        "hazard": "EQ",
        "title": q.title,
        "place": q.place,
        "time": to_iso(q.time),
        "geometry": {"lat": q.lat, "lon": q.lon, "depth_km": q.depth_km},
        "magnitude": q.mag,
        "severity": {
            "level": severity_level(q.mag, q.sig, q.alert),
            "inputs": {"mag": q.mag, "sig": q.sig, "alert": q.alert},
        },
        "major": is_major(q.mag, q.sig, q.alert),
        "provisional": q.status == "automatic",
        "sources": [{"feed": "usgs", "id": q.source_id, "url": q.url}],
    }
```

- [ ] **Step 4: Write `build.py`**

`pipeline/pipeline/build.py`:

```python
"""The pure pipeline core: already-fetched USGS windows -> contract v1 dict. No network."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pipeline.contract import SCHEMA_VERSION, event_from_quake, to_iso
from pipeline.dedup import union_by_id
from pipeline.feeds.usgs import parse_usgs
from pipeline.models import NormalizedQuake


@dataclass(frozen=True)
class WindowFetch:
    """The result of fetching one USGS window — success carries raw GeoJSON, failure an error."""

    window: str
    ok: bool
    payload: dict[str, Any] | None
    error: str | None
    fetched_at: datetime


def build_contract(fetches: list[WindowFetch], now: datetime) -> dict[str, Any]:
    feeds_meta: list[dict[str, Any]] = []
    all_quakes: list[NormalizedQuake] = []
    for f in fetches:
        if f.ok and f.payload is not None:
            quakes = parse_usgs(f.payload)
            all_quakes.extend(quakes)
            feeds_meta.append({
                "source": "usgs", "window": f.window, "status": "ok",
                "fetched_at": to_iso(f.fetched_at), "event_count": len(quakes),
            })
        else:
            feeds_meta.append({
                "source": "usgs", "window": f.window, "status": "error",
                "fetched_at": to_iso(f.fetched_at), "event_count": 0,
                "error": f.error or "fetch failed",
            })
    events = [event_from_quake(q) for q in union_by_id(all_quakes)]
    events.sort(key=lambda e: e["time"], reverse=True)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": to_iso(now),
        "meta": {"feeds": feeds_meta},
        "events": events,
    }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd pipeline && uv run pytest tests/test_build_contract.py -v`
Expected: PASS (6 tests). If a severity/flag assertion fails, adjust the **fixtures** (Task 2 Step 5) so they contain the required shapes — do not weaken the assertions.

- [ ] **Step 6: Commit**

```bash
git add pipeline/pipeline/contract.py pipeline/pipeline/build.py pipeline/tests/test_build_contract.py
git commit -m "feat(pipeline): assemble contract v1 from fetched USGS windows"
```

---

### Task 6: `/api/contract` serverless route (thin httpx adapter)

**Files:**
- Create: `pipeline/api/__init__.py` (empty)
- Create: `pipeline/api/contract.py`
- Test: `pipeline/tests/test_api_route.py`

**Interfaces:**
- Consumes: `WindowFetch`, `build_contract` (T5).
- Produces:
  - `USGS_URLS: dict[str, str]` mapping `"all_day"`/`"significant_week"` to the feed URLs.
  - `fetch_window(client: httpx.Client, window: str, now: datetime) -> WindowFetch`.
  - `build_response(client: httpx.Client, now: datetime) -> dict`.
  - `handler` (a `BaseHTTPRequestHandler` subclass) — the Vercel entrypoint; thin.

- [ ] **Step 1: Write the failing test** (mocks only the network edge, via `httpx.MockTransport`)

`pipeline/tests/test_api_route.py`:

```python
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
from jsonschema import Draft202012Validator

from api.contract import USGS_URLS, build_response  # top-level `api` package (pythonpath=".")

CONTRACT = Path(__file__).resolve().parents[2] / "contract"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
NOW = datetime(2026, 7, 8, 12, 0, 0, tzinfo=timezone.utc)


def _schema() -> dict:
    return json.loads((CONTRACT / "schema" / "contract.v1.schema.json").read_text("utf-8"))


def _client(route):
    return httpx.Client(transport=httpx.MockTransport(route))


def test_urls_cover_both_windows():
    assert set(USGS_URLS) == {"all_day", "significant_week"}


def test_build_response_returns_valid_contract_on_success():
    all_day = (FIXTURES / "usgs_all_day.json").read_text("utf-8")
    sig_week = (FIXTURES / "usgs_significant_week.json").read_text("utf-8")

    def route(request: httpx.Request) -> httpx.Response:
        body = all_day if request.url == USGS_URLS["all_day"] else sig_week
        return httpx.Response(200, content=body, headers={"content-type": "application/json"})

    contract = build_response(_client(route), NOW)
    Draft202012Validator(_schema()).validate(contract)
    assert len(contract["events"]) > 0


def test_build_response_marks_feed_error_on_non_200():
    def route(request: httpx.Request) -> httpx.Response:
        if request.url == USGS_URLS["all_day"]:
            return httpx.Response(503)
        return httpx.Response(200, json={"type": "FeatureCollection", "features": []})

    contract = build_response(_client(route), NOW)
    Draft202012Validator(_schema()).validate(contract)
    meta = {f["window"]: f for f in contract["meta"]["feeds"]}
    assert meta["all_day"]["status"] == "error"
    assert meta["significant_week"]["status"] == "ok"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd pipeline && uv run pytest tests/test_api_route.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api'`.

- [ ] **Step 3: Write the route**

`pipeline/api/contract.py`:

```python
"""Vercel Python serverless entrypoint: fetch USGS windows and return contract v1 JSON.

This is the only network-touching code. All logic lives in the pure core (pipeline.build);
this file just fetches and serializes.
"""

import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from typing import Any

import httpx

from pipeline.build import WindowFetch, build_contract

USGS_URLS = {
    "all_day": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson",
    "significant_week": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_week.geojson",
}


def fetch_window(client: httpx.Client, window: str, now: datetime) -> WindowFetch:
    try:
        resp = client.get(USGS_URLS[window], timeout=10.0)
        resp.raise_for_status()
        return WindowFetch(window=window, ok=True, payload=resp.json(), error=None, fetched_at=now)
    except Exception as exc:  # noqa: BLE001 — any fetch/parse failure degrades this window only
        return WindowFetch(window=window, ok=False, payload=None, error=str(exc), fetched_at=now)


def build_response(client: httpx.Client, now: datetime) -> dict[str, Any]:
    fetches = [fetch_window(client, w, now) for w in ("all_day", "significant_week")]
    return build_contract(fetches, now)


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

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd pipeline && uv run pytest -v` (whole suite)
Expected: PASS (all tests across Tasks 1–6).

- [ ] **Step 5: Lint & type-check the pipeline**

Run: `cd pipeline && uv run ruff check . && uv run mypy pipeline api`
Expected: no errors. Fix any before committing.

- [ ] **Step 6: Commit**

```bash
git add pipeline/api/ pipeline/tests/test_api_route.py
git commit -m "feat(pipeline): /api/contract route fetching USGS windows"
```

---

### Task 7: Front-end scaffold + generate contract types + contract loader

**Files:**
- Create: `web/` Next.js app (pnpm) — `package.json`, `.nvmrc`, `tsconfig.json`, `next.config.mjs`, Tailwind + PostCSS config (whatever `create-next-app` scaffolds — Tailwind v4 uses `@tailwindcss/postcss` + `@import "tailwindcss"` in `globals.css`, no `tailwind.config.ts`), `app/layout.tsx`, `app/globals.css`, `vitest.config.ts`, `vitest.setup.ts`, `.gitignore`
- Create: `web/lib/contract.types.ts` (generated from schema)
- Create: `web/lib/contract.ts`
- Test: `web/tests/contract.test.ts`

**Interfaces:**
- Consumes: `contract/schema/contract.v1.schema.json` (T1).
- Produces:
  - Generated types incl. `Contract`, `CrisisEvent`, `Severity`, `Geometry`, `FeedSource`, `FeedHealth` (from the schema `$defs` titles).
  - `CONTRACT_URL: string` and `loadContract(url?: string): Promise<Contract>` (throws on non-200).

- [ ] **Step 1: Scaffold the Next.js app**

Run: `pnpm create next-app@latest web --ts --app --tailwind --eslint --no-src-dir --import-alias "@/*" --use-pnpm` (accept defaults; if a flag is rejected by the installed create-next-app version, answer its interactive prompt to the same effect — App Router, Tailwind, ESLint, no `src/` dir, `@/*` alias). Then in `web/`:
- Add `web/.nvmrc` with the Node version (e.g. `20`).
- `pnpm add react-leaflet leaflet` and `pnpm add -D @types/leaflet vitest @vitejs/plugin-react @testing-library/react @testing-library/jest-dom @testing-library/user-event jsdom json-schema-to-typescript`.

- [ ] **Step 2: Configure Vitest**

`web/vitest.config.ts`:

```ts
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const root = dirname(fileURLToPath(import.meta.url)); // Windows-safe absolute path

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": root } },
  test: {
    environment: "jsdom",
    css: false,
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
  },
});
```

`web/vitest.setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
```

Add scripts to `web/package.json`:

```json
"scripts": {
  "dev": "next dev",
  "build": "next build",
  "start": "next start",
  "lint": "eslint",
  "test": "vitest run",
  "gen:contract-types": "json2ts ../contract/schema/contract.v1.schema.json -o lib/contract.types.ts"
}
```

Notes: the type-generator's CLI binary is **`json2ts`** (shipped by the `json-schema-to-typescript` package — the package name is not the command). Keep `lint` aligned with whatever `create-next-app` generated — Next 16 scaffolds `"lint": "eslint"` + a flat config; older versions used `next lint` (now removed) — don't reintroduce a removed command.

- [ ] **Step 3: Generate the contract types**

Run: `cd web && pnpm gen:contract-types`
Expected: `web/lib/contract.types.ts` is created and exports `Contract`, `CrisisEvent`, `Severity`, `Geometry`, `FeedSource`, `FeedHealth` (json-schema-to-typescript names interfaces from each schema `title`). **Verify the exact exported names** by opening the file; if the generator emitted a different name for any type, either adjust the schema `title` and regenerate, or add a one-line re-export alias at the bottom of `contract.ts` (e.g. `export type { CrisisEvent } from "./contract.types";`) so downstream imports in Tasks 8–11 resolve. Commit this generated file (regenerate whenever the schema changes).

- [ ] **Step 4: Write the failing test**

`web/tests/contract.test.ts`:

```ts
import { describe, expect, it, vi, afterEach } from "vitest";
import example from "../../contract/fixtures/contract.v1.example.json";
import { loadContract } from "@/lib/contract";

afterEach(() => vi.restoreAllMocks());

describe("loadContract", () => {
  it("returns the parsed contract on 200", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(example), { status: 200 })));
    const contract = await loadContract("/api/contract");
    expect(contract.schema_version).toBe("1.0.0");
    expect(contract.events.length).toBe(3);
  });

  it("throws on a non-200 response", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("boom", { status: 503 })));
    await expect(loadContract("/api/contract")).rejects.toThrow(/503/);
  });
});
```

- [ ] **Step 5: Run test to verify it fails**

Run: `cd web && pnpm test contract`
Expected: FAIL — `@/lib/contract` has no `loadContract`.

- [ ] **Step 6: Write the loader**

`web/lib/contract.ts`:

```ts
import type { Contract } from "./contract.types";

export const CONTRACT_URL = process.env.NEXT_PUBLIC_CONTRACT_URL ?? "/api/contract";

export async function loadContract(url: string = CONTRACT_URL): Promise<Contract> {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`contract fetch failed: ${res.status}`);
  return (await res.json()) as Contract;
}
```

- [ ] **Step 7: Run test to verify it passes, then commit**

Run: `cd web && pnpm test contract`
Expected: PASS (2 tests).

```bash
git add web/
git commit -m "feat(web): scaffold Next.js app, generate contract types, add loader"
```

---

### Task 8: Presentation + selection helpers (pure)

**Files:**
- Create: `web/lib/presentation.ts`
- Test: `web/tests/presentation.test.ts`

**Interfaces:**
- Consumes: `Contract`, `CrisisEvent`, `Severity` (T7).
- Produces:
  - `severityColor(level: Severity["level"]): string`
  - `markerRadius(magnitude: number): number`
  - `defaultMajorEvents(contract: Contract): CrisisEvent[]` (the `major:true` default view)
  - `feedsDown(contract: Contract): boolean`

- [ ] **Step 1: Write the failing test**

`web/tests/presentation.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import example from "../../contract/fixtures/contract.v1.example.json";
import feedDown from "../../contract/fixtures/contract.v1.feed-down.json";
import type { Contract } from "@/lib/contract.types";
import { defaultMajorEvents, feedsDown, markerRadius, severityColor } from "@/lib/presentation";

describe("presentation helpers", () => {
  it("maps every severity level to a distinct colour", () => {
    const colours = new Set(["minor", "moderate", "serious", "severe"].map((l) => severityColor(l as never)));
    expect(colours.size).toBe(4);
  });

  it("grows marker radius with magnitude and clamps a floor", () => {
    expect(markerRadius(7.1)).toBeGreaterThan(markerRadius(4.0));
    expect(markerRadius(0)).toBeGreaterThanOrEqual(4);
  });

  it("default view keeps only major events", () => {
    const majors = defaultMajorEvents(example as Contract);
    expect(majors.length).toBe(2);
    expect(majors.every((e) => e.major)).toBe(true);
  });

  it("detects feed outages from meta", () => {
    expect(feedsDown(example as Contract)).toBe(false);
    expect(feedsDown(feedDown as Contract)).toBe(true);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && pnpm test presentation`
Expected: FAIL — `@/lib/presentation` missing.

- [ ] **Step 3: Write the implementation**

`web/lib/presentation.ts`:

```ts
import type { Contract, CrisisEvent, Severity } from "./contract.types";

const COLORS: Record<Severity["level"], string> = {
  severe: "#dc2626",
  serious: "#ea580c",
  moderate: "#d97706",
  minor: "#6b7280",
};

export function severityColor(level: Severity["level"]): string {
  return COLORS[level];
}

export function markerRadius(magnitude: number): number {
  return Math.max(4, Math.round((magnitude - 2) * 3));
}

export function defaultMajorEvents(contract: Contract): CrisisEvent[] {
  return contract.events.filter((e) => e.major);
}

export function feedsDown(contract: Contract): boolean {
  return contract.meta.feeds.some((f) => f.status === "error");
}
```

- [ ] **Step 4: Run test to verify it passes, then commit**

Run: `cd web && pnpm test presentation`
Expected: PASS (4 tests).

```bash
git add web/lib/presentation.ts web/tests/presentation.test.ts
git commit -m "feat(web): severity colour, marker radius, default-view + feed-health helpers"
```

---

### Task 9: EventList, EventDetail, ProvisionalBadge

**Files:**
- Create: `web/components/ProvisionalBadge.tsx`
- Create: `web/components/EventList.tsx`
- Create: `web/components/EventDetail.tsx`
- Test: `web/tests/EventList.test.tsx`
- Test: `web/tests/EventDetail.test.tsx`

**Interfaces:**
- Consumes: `CrisisEvent` (T7); `severityColor` (T8).
- Produces:
  - `ProvisionalBadge({ provisional }: { provisional: boolean })` — renders a badge or `null`.
  - `EventList({ events, selectedId, onSelect }: { events: CrisisEvent[]; selectedId: string | null; onSelect: (id: string) => void })`.
  - `EventDetail({ event }: { event: CrisisEvent | null })`.

- [ ] **Step 1: Write the failing tests**

`web/tests/EventList.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import example from "../../contract/fixtures/contract.v1.example.json";
import type { Contract } from "@/lib/contract.types";
import { EventList } from "@/components/EventList";

const events = (example as Contract).events.filter((e) => e.major);

describe("EventList", () => {
  it("renders one row per event with its title", () => {
    render(<EventList events={events} selectedId={null} onSelect={() => {}} />);
    expect(screen.getByText(/M 7.1/)).toBeInTheDocument();
    expect(screen.getByText(/M 6.0/)).toBeInTheDocument();
  });

  it("badges provisional events only", () => {
    render(<EventList events={events} selectedId={null} onSelect={() => {}} />);
    expect(screen.getAllByTestId("provisional-badge").length).toBe(1);
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

`web/tests/EventDetail.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import example from "../../contract/fixtures/contract.v1.example.json";
import type { Contract } from "@/lib/contract.types";
import { EventDetail } from "@/components/EventDetail";

const severe = (example as Contract).events[0];

describe("EventDetail", () => {
  it("prompts to select when no event is given", () => {
    render(<EventDetail event={null} />);
    expect(screen.getByLabelText("event detail")).toHaveTextContent(/select an event/i);
  });

  it("shows title, hazard, severity, location, time, source link, provisional badge", () => {
    render(<EventDetail event={severe} />);
    expect(screen.getByRole("heading")).toHaveTextContent(/M 7.1/);
    expect(screen.getByText("EQ")).toBeInTheDocument();
    expect(screen.getByText("severe")).toBeInTheDocument();
    expect(screen.getByText("40 km W of Testville")).toBeInTheDocument(); // exact match: place is a substring of the title, so a regex would match both
    expect(screen.getByRole("link", { name: /source/i })).toHaveAttribute(
      "href",
      "https://earthquake.usgs.gov/earthquakes/eventpage/us6000severe",
    );
    expect(screen.getByTestId("provisional-badge")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && pnpm test EventList EventDetail`
Expected: FAIL — components missing.

- [ ] **Step 3: Write the components**

`web/components/ProvisionalBadge.tsx`:

```tsx
export function ProvisionalBadge({ provisional }: { provisional: boolean }) {
  if (!provisional) return null;
  return (
    <span data-testid="provisional-badge" title="Unreviewed automatic solution" className="badge">
      provisional
    </span>
  );
}
```

`web/components/EventList.tsx`:

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
            <span>{e.title}</span>
            <span style={{ color: severityColor(e.severity.level) }}>{e.severity.level}</span>
            <ProvisionalBadge provisional={e.provisional} />
          </button>
        </li>
      ))}
    </ul>
  );
}
```

`web/components/EventDetail.tsx`:

```tsx
import type { CrisisEvent } from "@/lib/contract.types";
import { severityColor } from "@/lib/presentation";
import { ProvisionalBadge } from "./ProvisionalBadge";

export function EventDetail({ event }: { event: CrisisEvent | null }) {
  if (!event) {
    return <aside aria-label="event detail">Select an event</aside>;
  }
  return (
    <aside aria-label="event detail">
      <h2>{event.title}</h2>
      <dl>
        <dt>Hazard</dt>
        <dd>{event.hazard}</dd>
        <dt>Severity</dt>
        <dd style={{ color: severityColor(event.severity.level) }}>{event.severity.level}</dd>
        <dt>Location</dt>
        <dd>{event.place}</dd>
        <dt>Time</dt>
        <dd>{event.time}</dd>
      </dl>
      <ProvisionalBadge provisional={event.provisional} />
      <a href={event.sources[0].url}>USGS source</a>
    </aside>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass, then commit**

Run: `cd web && pnpm test EventList EventDetail`
Expected: PASS (6 tests).

```bash
git add web/components/ProvisionalBadge.tsx web/components/EventList.tsx web/components/EventDetail.tsx web/tests/EventList.test.tsx web/tests/EventDetail.test.tsx
git commit -m "feat(web): event list, detail card, provisional badge"
```

---

### Task 10: CrisisMap (react-leaflet) with severity markers

**Files:**
- Create: `web/components/CrisisMap.tsx`
- Test: `web/tests/CrisisMap.test.tsx`

**Interfaces:**
- Consumes: `CrisisEvent` (T7); `severityColor`, `markerRadius` (T8).
- Produces: `CrisisMap({ events, selectedId, onSelect }: { events: CrisisEvent[]; selectedId: string | null; onSelect: (id: string) => void })`. Renders a placeholder until mounted (SSR-safe), then a CircleMarker per event (colour = severity, radius = magnitude, thicker stroke when selected), click → `onSelect`.

- [ ] **Step 1: Write the failing test** (mocks `react-leaflet` — the only "network/DOM edge" here)

`web/tests/CrisisMap.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import example from "../../contract/fixtures/contract.v1.example.json";
import type { Contract } from "@/lib/contract.types";

vi.mock("react-leaflet", () => ({
  MapContainer: ({ children }: any) => <div data-testid="map">{children}</div>,
  TileLayer: () => null,
  Tooltip: ({ children }: any) => <span>{children}</span>,
  CircleMarker: ({ center, radius, pathOptions, eventHandlers, children }: any) => (
    <button
      data-testid="marker"
      data-lat={center[0]}
      data-lon={center[1]}
      data-radius={radius}
      data-color={pathOptions.color}
      data-weight={pathOptions.weight}
      onClick={eventHandlers.click}
    >
      {children}
    </button>
  ),
}));

import { CrisisMap } from "@/components/CrisisMap";

const events = (example as Contract).events.filter((e) => e.major);

describe("CrisisMap", () => {
  it("renders one marker per event, coloured by severity", async () => {
    render(<CrisisMap events={events} selectedId={null} onSelect={() => {}} />);
    const markers = await screen.findAllByTestId("marker");
    expect(markers.length).toBe(2);
    expect(markers[0]).toHaveAttribute("data-color", "#dc2626"); // severe
  });

  it("thickens the selected marker's stroke", async () => {
    render(<CrisisMap events={events} selectedId="usgs:us6000severe" onSelect={() => {}} />);
    const selected = (await screen.findAllByTestId("marker")).find(
      (m) => m.getAttribute("data-lat") === "-19.1",
    );
    expect(Number(selected?.getAttribute("data-weight"))).toBeGreaterThan(1);
  });

  it("calls onSelect when a marker is clicked", async () => {
    const onSelect = vi.fn();
    render(<CrisisMap events={events} selectedId={null} onSelect={onSelect} />);
    await userEvent.click((await screen.findAllByTestId("marker"))[0]);
    expect(onSelect).toHaveBeenCalledWith("usgs:us6000severe");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && pnpm test CrisisMap`
Expected: FAIL — `@/components/CrisisMap` missing.

- [ ] **Step 3: Write the component**

`web/components/CrisisMap.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import { CircleMarker, MapContainer, TileLayer, Tooltip } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import type { CrisisEvent } from "@/lib/contract.types";
import { markerRadius, severityColor } from "@/lib/presentation";

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
  useEffect(() => setMounted(true), []);
  if (!mounted) return <div data-testid="map-loading" style={{ height: "100%" }} />;

  return (
    <MapContainer center={[20, 0]} zoom={2} style={{ height: "100%", width: "100%" }}>
      <TileLayer
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution="&copy; OpenStreetMap contributors"
      />
      {events.map((e) => (
        <CircleMarker
          key={e.id}
          center={[e.geometry.lat, e.geometry.lon]}
          radius={markerRadius(e.magnitude)}
          pathOptions={{ color: severityColor(e.severity.level), weight: e.id === selectedId ? 4 : 1 }}
          eventHandlers={{ click: () => onSelect(e.id) }}
        >
          <Tooltip>{e.title}</Tooltip>
        </CircleMarker>
      ))}
    </MapContainer>
  );
}
```

- [ ] **Step 4: Run test to verify it passes, then commit**

Run: `cd web && pnpm test CrisisMap`
Expected: PASS (3 tests).

```bash
git add web/components/CrisisMap.tsx web/tests/CrisisMap.test.tsx
git commit -m "feat(web): leaflet map with severity-coloured, magnitude-sized markers"
```

---

### Task 11: Dashboard page — compose map + list + detail, synced selection, graceful states

**Files:**
- Modify: `web/app/page.tsx` (replace the starter content)
- Create: `web/app/globals.css` additions for the two-column layout (append)
- Test: `web/tests/page.test.tsx`

**Interfaces:**
- Consumes: `loadContract` (T7); `defaultMajorEvents`, `feedsDown` (T8); `EventList`, `EventDetail` (T9); `CrisisMap` (T10).
- Produces: the default-exported `Page` client component. Loads the contract on mount; renders the outage banner when any feed errored; shows "No major events right now." when the default view is empty; keeps map + list + detail selection in sync.

- [ ] **Step 1: Write the failing test** (mocks `loadContract`; stubs the dynamically-imported map)

`web/tests/page.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import example from "../../contract/fixtures/contract.v1.example.json";
import noMajor from "../../contract/fixtures/contract.v1.no-major.json";
import feedDown from "../../contract/fixtures/contract.v1.feed-down.json";

const loadContract = vi.fn();
vi.mock("@/lib/contract", () => ({ loadContract, CONTRACT_URL: "/api/contract" }));

// Stub next/dynamic so the map is a black box here (its own test covers it).
vi.mock("next/dynamic", () => ({
  default: () => (props: any) => <div data-testid="map-stub" data-count={props.events.length} />,
}));

import Page from "@/app/page";

afterEach(() => vi.clearAllMocks());

describe("dashboard page", () => {
  it("renders map + list from the contract, major-only, with no key", async () => {
    loadContract.mockResolvedValue(example);
    render(<Page />);
    await screen.findByLabelText("event list");
    expect(screen.getAllByRole("button").length).toBe(2); // 2 major events, no key entry anywhere
    expect(screen.getByTestId("map-stub")).toHaveAttribute("data-count", "2");
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

  it("shows an outage banner when a feed errored", async () => {
    loadContract.mockResolvedValue(feedDown);
    render(<Page />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/USGS unavailable/i);
  });

  it("shows an error state when the contract fails to load", async () => {
    loadContract.mockRejectedValue(new Error("503"));
    render(<Page />);
    await waitFor(() => expect(screen.getByText(/failed to load/i)).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && pnpm test page`
Expected: FAIL — page still renders starter content.

- [ ] **Step 3: Write the page**

`web/app/page.tsx`:

```tsx
"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { EventDetail } from "@/components/EventDetail";
import { EventList } from "@/components/EventList";
import type { Contract } from "@/lib/contract.types";
import { loadContract } from "@/lib/contract";
import { defaultMajorEvents, feedsDown } from "@/lib/presentation";

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

  return (
    <main>
      {feedsDown(contract) && (
        <div role="alert">USGS unavailable — picture may be incomplete.</div>
      )}
      <p>Last updated {contract.generated_at}</p>
      <div className="dashboard">
        <div className="map-pane">
          <CrisisMap events={visible} selectedId={selectedId} onSelect={setSelectedId} />
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

Append to `web/app/globals.css`:

```css
.dashboard { display: grid; grid-template-columns: 2fr 1fr; gap: 1rem; height: 80vh; }
.map-pane { height: 100%; min-height: 24rem; }
.side-pane { overflow-y: auto; }
.badge { margin-left: 0.5rem; font-size: 0.75rem; border: 1px solid currentColor; border-radius: 0.25rem; padding: 0 0.25rem; }
```

- [ ] **Step 4: Run tests, lint, type-check, then commit**

Run: `cd web && pnpm test && pnpm lint && pnpm exec tsc --noEmit`
Expected: all pass; no TS/lint errors.

```bash
git add web/app/page.tsx web/app/globals.css web/tests/page.test.tsx
git commit -m "feat(web): dashboard page composing map + list + detail with graceful states"
```

---

### Task 12: Local end-to-end integration, deviations log, and verify

**Files:**
- Create: `pipeline/serve_local.py`
- Modify: `web/.env.local` (create; gitignored) — document, don't commit secrets
- Modify: `implementation-notes.md` (log deviations a/b/c)
- Modify: `README.md` (append a "Run Slice 1 locally" quickstart)

**Interfaces:** none new — this task wires the real route to the real page and proves the slice end to end.

- [ ] **Step 1: Add a local server for the route**

`pipeline/serve_local.py`:

```python
"""Serve /api/contract locally for end-to-end dev (Vercel serves api/contract.py in prod)."""

from http.server import HTTPServer

from api.contract import handler

if __name__ == "__main__":
    print("serving contract on http://localhost:8000/api/contract")  # noqa: T201
    HTTPServer(("127.0.0.1", 8000), handler).serve_forever()
```

- [ ] **Step 2: Point the web app at the local route**

Create `web/.env.local` (gitignored):

```
NEXT_PUBLIC_CONTRACT_URL=http://localhost:8000/api/contract
```

- [ ] **Step 3: Run both halves and verify live**

In two terminals:
- `cd pipeline && uv run python serve_local.py`
- `cd web && pnpm dev`

Then use the **superpowers:verification-before-completion** discipline and the `verify` skill: open `http://localhost:3000`, confirm (a) markers appear on the world map for current major quakes, (b) clicking a marker/list row fills the detail card and the selection is mirrored in both, (c) provisional quakes show the badge, (d) the page renders with no key and no key prompt exists. Capture the observation (screenshot or a note of the live event count) as evidence.

- [ ] **Step 4: Run the full test suites one more time**

Run: `cd pipeline && uv run pytest && cd ../web && pnpm test`
Expected: all green in both halves.

- [ ] **Step 5: Log the deviations**

Append to `implementation-notes.md` under Deviations (from spec §9):
- (a) `meta.feeds` health added to the contract ahead of the gate/analytics slices — forward-compat seam, not an ADR change.
- (b) Below-threshold events carried in the contract before the "show all" filter exists — forward-compat seam.
- (c) Issue #3's DoD says "hosted"; the live Vercel deploy is a deliberate fast-follow, so Slice 1's DoD is local e2e + green tests. Narrows the issue wording; ADR 0006 still stands.
- (d) Markers use a coloured, magnitude-sized CircleMarker with **no hazard glyph**; with a single hazard type (EQ) the spec's `icon = hazard` encoding carries no disambiguating information, so it is intentionally deferred until a second hazard type exists — forward-compat narrowing, not an ADR change.

- [ ] **Step 6: Add a quickstart to the README, then commit**

Append a "Run Slice 1 locally" section to `README.md` documenting the two commands from Step 3 and the `.env.local` variable.

```bash
git add pipeline/serve_local.py implementation-notes.md README.md web/.gitignore
git commit -m "chore(slice-1): local e2e wiring, deviations log, quickstart"
```

---

> **Deploy heads-up (fast-follow, not Slice 1 DoD):** Vercel discovers Python functions at the *project-root* `/api/**`, but this plan puts the route at `pipeline/api/contract.py`. The deploy step will need to set the Vercel project root to `pipeline/` (so `pipeline/api/contract.py` → `/api/contract`) or otherwise relocate the function, and export a `requirements.txt` (or a Vercel-supported `pyproject`) for the Python runtime. Out of scope here; noted so the fast-follow doesn't rediscover it.

---

## Definition of Done (maps to issue #3)

- [ ] Pipeline ingests USGS `all_day` **and** `significant_week` and emits **contract v1** (schema_version, generated_at, canonical EQ events with identity, geometry, time, Severity + inputs, `major`/`provisional`, source link) — Tasks 2–6.
- [ ] Severity per ADR 0003; `major` gated at M≥5.5 OR sig≥600 OR non-null `alert`; below-threshold events present but flagged — Tasks 3, 5.
- [ ] Front end renders markers (colour=Severity, size=magnitude; hazard icon deferred per deviation (d) — single hazard EQ) + right-hand list; map/list synced; click → detail card with provisional badge — Tasks 9–11.
- [ ] Renders with **no key** — Task 11 test.
- [ ] `pytest` asserts the contract from `all_day` + `significant_week` fixtures; `vitest`+RTL asserts rendering from a contract fixture — throughout, verified end to end in Task 12.
```
