# Routine prompt — scheduled `events.html` generation

Paste the block below as the **prompt for a Claude Code routine session**. It runs
autonomously in a fresh clone of this repo: fetch feeds → update SQLite memory → render →
commit both back so the next run has memory.

> Account/environment setup (`/web-setup`, `/schedule`, network access allowing
> `earthquake.usgs.gov` + `www.gdacs.org`, `pip install -r requirements.txt`) is done
> separately and is **not** part of this prompt.

---

## Prompt

```
You are running the disaster-feed pipeline for this repository on a schedule. Work from the
repo root. Be deterministic and grounded; never fabricate numbers.

FILES (all at repo root)
- feeds.db              SQLite memory — events + articles + runs; the source of record
- feeds_store.py        store CLI: init/dump/ingest/render/prune
- report.html.j2        Jinja template (pure presentation)
- world_land_path.txt   map path (read automatically by render)
- events.html           the rendered report (output)

STEPS
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

4. DIFF vs MEMORY (trend, one grounded note each)
   NEW · ONGOING since {first_flagged} · ESCALATED from {old band} · DE-ESCALATED · REVISED
   (was {old signal}) · AFTERSHOCK/RELATED (same hazard, ~150 km, <=14 days after a prior
   serious+ event). Compute counts: new / escalated / cleared. Reference only values from the
   dump — never invent history.

5. ATTACH GROUND-REPORTING NEWS (grounded)
   For each flagged event (severe/serious first) WebSearch for on-the-ground reporting —
   casualties, evacuations, damage, eyewitness accounts. Keep {source, url, title, published}
   and a short grounded summary per useful result. Every claim must trace to a cited article;
   never fabricate casualty/damage/population figures; state uncertainty; if nothing ties to
   the event set no_news and skip. Re-use stored articles; only add new ones.

6. BUILD THE PAYLOAD
   Per event assemble band, band_label, hazard_label (EQ->EARTHQUAKE, TC->TROPICAL CYCLONE,
   FL->FLOOD, WF->WILDFIRE, VO->VOLCANO, DR->DROUGHT), alert_label, title, four feed_cells
   ({k,v}: Magnitude/Signal, Position, Time, Event ID), ground bullets ({lead,text} — a bullet
   may carry the Step-4 trend), optional forecast, optional no_news, impact chips
   ([{label,value}] grounded in cited articles; "None reported" where a figure is absent,
   never invented), articles (Step 5), and lat/lon so it plots on the map. Shape:
   report.seed.example.json. Convert USGS epoch-ms time to ISO-8601 UTC.

7. PERSIST + RENDER
   Write {run_at, counts, events:[...]} to a temp JSON, then:
   python feeds_store.py ingest --json <payload.json>
   python feeds_store.py render
   python feeds_store.py prune --days 30

8. COMMIT + PUSH (so memory and report survive to the next run)
   Stage feeds.db and events.html and commit:
   "chore(feeds): scheduled run <UTC timestamp> — <N> events, <new> new / <esc> escalated"
   then push. (feeds.db must be tracked, not gitignored, or memory resets each run.)

9. FINAL MESSAGE — print the fixed-format text summary:
   # Disaster Flag — <current UTC>
   <N> key event(s) · NEW <new> · ESCALATED <esc> · CLEARED <cleared> vs last run
   sources: USGS <ok|fail> · GDACS <ok|fail> · HTML -> events.html
   Then one block per event, most-severe first (Type / Signal / Trend / When / Where /
   Status / Source / Note). Empty window: "No key disasters (threshold M5.5)." — still run
   Step 7 so state is logged. Include the session link (CLAUDE_CODE_REMOTE_SESSION_ID).

RULES
- Grounded only: feed facts from feeds; historical claims from the DB; news claims from cited
  articles. Never invent numbers. State uncertainty (provisional/preliminary).
- The text format and the HTML format are both fixed — do not improvise new sections.
```
