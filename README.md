# crisis-events-report

Standalone generator for **`events.html`** — an interactive disaster report (world map +
impact summaries + per-event news modal), built from public feeds and a SQLite memory.

Extracted from the Global Crisis Dashboard so it can run on its own, in a scheduled cloud
routine, with nothing else attached. The **only** thing this repo does is turn feed data +
memory into `events.html`.

```
public feeds ──► SQLite memory (events + articles) ──► Jinja template ──► events.html
   (USGS,          feeds.db (source of record)          report.html.j2      (rendered report)
    GDACS)
```

## Contents

| File | Role |
|---|---|
| `feeds_store.py` | SQLite store + CLI: `init` / `dump` / `ingest` / `render` / `prune`. The only code. |
| `report.html.j2` | Jinja template — pure presentation, so every run produces the same format. |
| `world_land_path.txt` | Natural Earth land as an equirectangular SVG path (injected at render). |
| `report.seed.example.json` | The ingest payload shape, and a 5-event seed for a first render. |
| `feeds.db` | SQLite memory. **Tracked, not ignored** — this is how a scheduled run keeps state. |
| `events.html` | The generated report (tracked so the latest render is always viewable). |
| `routine.md` | The prompt to paste into a scheduled Claude Code routine (fetch → render → commit). |

## Requirements

Python 3.12 + Jinja2. Nothing else — the feeds are public and keyless.

```
pip install -r requirements.txt
```

## Generate the report

The CLI defaults are repo-relative, so from the repo root:

```bash
# 1. read prior memory (for the diff/trend step)
python feeds_store.py dump

# 2. ...fetch feeds, select key events, attach news, and write a run payload...
#    (this data-gathering step is what the routine in routine.md performs; see below)

# 3. ingest the payload, render the HTML, prune stale events
python feeds_store.py ingest --json payload.json
python feeds_store.py render
python feeds_store.py prune --days 30
```

To reproduce the committed baseline from the seed:

```bash
python feeds_store.py ingest --json report.seed.example.json
python feeds_store.py render
```

Open `events.html` in a browser to view it.

## The data-gathering step

`feeds_store.py` never touches the network — it ingests a payload and renders. Fetching the
feeds, selecting key events (deterministic banding), diffing against memory for trend, and
attaching grounded ground-reporting news is done by a Claude Code routine. Paste `routine.md`
into a scheduled routine session; it performs steps 1–2 above, then ingests, renders, and
commits `feeds.db` + `events.html` back so the next run has memory.

## Data model (SQLite, indexed)

- `events` — one row per event: feed facts (`last_mag/alert/sig/band/time`, `lat/lon`,
  `peak_band`, `first_flagged`, `last_seen`, `seen_count`) + cached presentation
  (`title`, `feed_cells_json`, `ground_json`, `impact_json`, …).
  Indexes: `last_seen`, `peak_band`, `hazard`, `(lat,lon)`.
- `articles` — news per event `{source,url,title,summary,published,fetched_at}`,
  `UNIQUE(event_id,url)`, FK → `events` ON DELETE CASCADE. Indexes: `event_id`, `url`.
- `runs` — `{run_at, flagged_ids, new/esc/cleared counts}`.

## Grounding rules

Feed facts from feeds; historical claims from the DB; news claims from cited articles.
Never invent casualty/damage/population figures; state uncertainty. The text and HTML
formats are both fixed — do not improvise new sections.
