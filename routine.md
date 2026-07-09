# Routine prompt — scheduled `events.html` generation

Paste the block below as the **prompt for a Claude Code routine session**. Each run starts in
a fresh, empty environment with no repo checked out — the prompt itself clones it, fetches
feeds → updates SQLite memory → renders → commits both back so the next run has memory.

> Prerequisite: an env var `GH_TOKEN` set on the environment/routine — a GitHub token (fine-
> grained PAT scoped to `ytexplorer/crisis-events-report`, permission **Contents: Read and
> write**; or a classic PAT with the `repo` scope) with no branch-protection rules on `main`
> blocking direct pushes. This repo is public, so cloning and fetching don't need it — only
> the final push does. Network access allowing `earthquake.usgs.gov` + `www.gdacs.org` +
> `github.com` is assumed to be configured on the environment; that part is not this prompt's
> job.

---

## Prompt

```
You are running the disaster-feed pipeline for this repository on a schedule. Work from the
repo root. Be deterministic and grounded; never fabricate numbers.

FILES (all at repo root, once cloned)
- feeds.db              SQLite memory — events + articles + runs; the source of record
- feeds_store.py        store CLI: init/dump/ingest/render/prune
- report.html.j2        Jinja template (pure presentation)
- world_land_path.txt   map path (read automatically by render)
- events.html           the rendered report (output)

STEPS
0. ENSURE REPO PRESENT (the environment starts empty — nothing to skip here)
   If feeds_store.py is not in the working directory:
     git clone https://github.com/ytexplorer/crisis-events-report.git .
   else:
     git pull --ff-only origin main
   Then: pip install -r requirements.txt

1. READ MEMORY
   python feeds_store.py dump
   Use it for the trend/diff step. First run is empty (everything is NEW).

2. FETCH FEEDS (public, keyless)
   USGS : https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson
   GDACS: https://www.gdacs.org/gdacsapi/api/events/geteventlist/EVENTS4APP
   If a feed fails, mark it degraded and continue with the other.

3. SELECT KEY EVENTS (deterministic, MIN_MAG = 5.5)
   Flag if ANY: USGS mag>=5.5 OR alert not null OR sig>=600; GDACS alertlevel in {Orange,Red}.
   Band (first match): severe (USGS alert orange/red OR mag>=7.0 OR sig>=1000; GDACS Red) ·
   serious (USGS alert yellow OR mag>=6.0 OR sig>=600; GDACS Orange) · moderate (mag>=4.5 OR
   sig>=300) · minor (else — not flagged).

4. DEDUPLICATE ACROSS FEEDS (LLM judgment — same real-world event under different ids)
   Two feeds can report ONE event under different ids (a large quake often appears in both
   USGS and GDACS), or an id can shift between runs. Using judgment, collapse candidates that
   are the SAME real-world event, deciding from: same hazard type, coincident location (lat/lon
   within ~50 km), overlapping origin time (within a few hours), and consistent magnitude/
   signal. Be conservative — merge ONLY when clearly one event; when unsure, keep them separate.
   This is NOT the aftershock/related case in Step 5: near-but-distinct events stay separate and
   are only annotated there, never merged.
   For each merged group:
   - CANONICAL ID (must be stable across runs so memory persists): prefer an id already in
     memory (from the Step-1 dump); break any remaining tie by fixed feed precedence (USGS
     before GDACS) then the lexicographically smallest id. Never let it depend on feed ordering
     or on run time.
   - MERGE conservatively: take the highest band; keep the canonical feed's signal as the
     primary feed_cells and add the other feed's signal/id as one extra feed_cell (e.g.
     "Also GDACS <id> · alert <x>"); union the articles (dedup by url); use the best-located
     lat/lon and place. Never invent a value to reconcile a discrepancy — cite both feeds.
   - Ingest ONLY the canonical event, and add a ground bullet noting the merge (e.g.
     "Corroborated by GDACS <id>"). A superseded id that already exists in memory simply stops
     being refreshed and ages out via the Step-8 prune (30 d) — it is not deleted here.

5. DIFF vs MEMORY (trend, one grounded note each)
   NEW · ONGOING since {first_flagged} · ESCALATED from {old band} · DE-ESCALATED · REVISED
   (was {old signal}) · AFTERSHOCK/RELATED (same hazard, ~150 km, <=14 days after a prior
   serious+ event). Compute counts: new / escalated / cleared. Reference only values from the
   dump — never invent history.

6. ATTACH GROUND-REPORTING NEWS (grounded)
   For each flagged event (severe/serious first) WebSearch for on-the-ground reporting —
   casualties, evacuations, damage, eyewitness accounts. Keep {source, url, title, published}
   and a short grounded summary per useful result. Every claim must trace to a cited article;
   never fabricate casualty/damage/population figures; state uncertainty; if nothing ties to
   the event set no_news and skip. Re-use stored articles; only add new ones.

7. BUILD THE PAYLOAD
   Per event assemble band, band_label, hazard_label (EQ->EARTHQUAKE, TC->TROPICAL CYCLONE,
   FL->FLOOD, WF->WILDFIRE, VO->VOLCANO, DR->DROUGHT), alert_label, title, four feed_cells
   ({k,v}: Magnitude/Signal, Position, Time, Event ID), ground bullets ({lead,text} — a bullet
   may carry the Step-5 trend), optional forecast, optional no_news, impact chips
   ([{label,value}] grounded in cited articles; "None reported" where a figure is absent,
   never invented), articles (Step 6), and lat/lon so it plots on the map. Shape:
   report.seed.example.json. Convert USGS epoch-ms time to ISO-8601 UTC.

8. PERSIST + RENDER
   Write {run_at, counts, events:[...]} to a temp JSON, then:
   python feeds_store.py ingest --json <payload.json>
   python feeds_store.py render
   python feeds_store.py prune --days 30

9. COMMIT + PUSH (so memory and report survive to the next run)
   Stage feeds.db and events.html and commit:
   "chore(feeds): scheduled run <UTC timestamp> — <N> events, <new> new / <esc> escalated"
   then push using GH_TOKEN explicitly (the default remote may only carry read access):
     git push https://x-access-token:${GH_TOKEN}@github.com/ytexplorer/crisis-events-report.git HEAD:main
   (feeds.db must be tracked, not gitignored, or memory resets each run. If push fails with
   403, GH_TOKEN is missing/under-scoped or main has a protection rule blocking direct pushes
   — surface that clearly in the final message rather than silently dropping the update.)

10. FINAL MESSAGE — print the fixed-format text summary:
   # Disaster Flag — <current UTC>
   <N> key event(s) · NEW <new> · ESCALATED <esc> · CLEARED <cleared> vs last run
   sources: USGS <ok|fail> · GDACS <ok|fail> · HTML -> events.html
   Then one block per event, most-severe first (Type / Signal / Trend / When / Where /
   Status / Source / Note). Empty window: "No key disasters (threshold M5.5)." — still run
   Step 8 so state is logged. Include the session link (CLAUDE_CODE_REMOTE_SESSION_ID).

RULES
- Grounded only: feed facts from feeds; historical claims from the DB; news claims from cited
  articles. Never invent numbers. State uncertainty (provisional/preliminary).
- The text format and the HTML format are both fixed — do not improvise new sections.
```
