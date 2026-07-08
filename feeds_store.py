#!/usr/bin/env python3
"""SQLite-backed memory for the /feeds routine: events + their news articles.

Commands
    init    apply the schema (idempotent)
    dump    emit prior state as JSON (for the routine's diff/trend step)
    ingest  upsert a run payload (events + articles), log the run
    render  build the context from the DB and render report.html.j2 -> events.html
    prune   drop events (and their articles) not seen in N days

The DB is the source of record; the Jinja template is pure presentation, so the
same format renders every run. Feed facts and news articles are stored separately
and indexed. Nothing here fetches the network — the routine gathers data and feeds
it in, keeping ingestion grounded and testable.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS events (
    id             TEXT PRIMARY KEY,        -- e.g. "usgs:us6000talg" / "gdacs-TC-1001279"
    hazard         TEXT NOT NULL,
    place          TEXT,
    lat            REAL,
    lon            REAL,
    source_url     TEXT,
    first_flagged  TEXT NOT NULL,           -- ISO date, set once
    last_seen      TEXT NOT NULL,           -- ISO datetime, refreshed each run
    peak_band      TEXT,                    -- highest band ever reached
    seen_count     INTEGER NOT NULL DEFAULT 1,
    -- latest signal snapshot (feed facts)
    last_mag       REAL,
    last_alert     TEXT,
    last_sig       INTEGER,
    last_band      TEXT,
    last_time      TEXT,
    -- cached presentation (rebuilt when the event or its coverage changes)
    band           TEXT,                    -- lowercase, drives the card colour class
    band_label     TEXT,
    hazard_label   TEXT,
    alert_label    TEXT,
    title          TEXT,
    feed_cells_json TEXT,                   -- JSON: [{k,v}, ...]
    ground_json    TEXT,                    -- JSON: [{lead?, text}, ...]
    forecast_json  TEXT,                    -- JSON: {label, text} or null
    no_news        TEXT,
    impact_json    TEXT                     -- JSON: [{label, value}, ...] casualties/impact
);
CREATE INDEX IF NOT EXISTS idx_events_last_seen ON events(last_seen);
CREATE INDEX IF NOT EXISTS idx_events_peak_band ON events(peak_band);
CREATE INDEX IF NOT EXISTS idx_events_hazard    ON events(hazard);
CREATE INDEX IF NOT EXISTS idx_events_geo       ON events(lat, lon);

CREATE TABLE IF NOT EXISTS articles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id    TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    source      TEXT,                       -- outlet, e.g. "NPR"
    url         TEXT NOT NULL,
    title       TEXT,
    summary     TEXT,                       -- grounded ground-reporting summary
    published   TEXT,                       -- ISO date if known
    fetched_at  TEXT NOT NULL,
    UNIQUE(event_id, url)                   -- one row per (event, article)
);
CREATE INDEX IF NOT EXISTS idx_articles_event ON articles(event_id);
CREATE INDEX IF NOT EXISTS idx_articles_url   ON articles(url);

CREATE TABLE IF NOT EXISTS runs (
    run_at        TEXT PRIMARY KEY,
    flagged_ids   TEXT,                     -- JSON array of event ids flagged this run
    new_count     INTEGER DEFAULT 0,
    esc_count     INTEGER DEFAULT 0,
    cleared_count INTEGER DEFAULT 0
);
"""

BAND_RANK = {"severe": 0, "serious": 1, "moderate": 2, "minor": 3}
_SMALL = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six",
          7: "Seven", 8: "Eight", 9: "Nine", 10: "Ten"}


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript(SCHEMA)
    # migration: add columns introduced after a DB was first created
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(events)")}
    if "impact_json" not in cols:
        conn.execute("ALTER TABLE events ADD COLUMN impact_json TEXT")
    conn.commit()
    return conn


def _higher_band(a: str | None, b: str | None) -> str | None:
    cands = [x for x in (a, b) if x]
    if not cands:
        return None
    return min(cands, key=lambda x: BAND_RANK.get(x.lower(), 99))


def upsert_event(conn: sqlite3.Connection, ev: dict, run_at: str) -> None:
    row = conn.execute("SELECT first_flagged, seen_count, peak_band FROM events WHERE id = ?",
                       (ev["id"],)).fetchone()
    sig = ev.get("signal") or {}
    if row is None:
        first_flagged = run_at[:10]
        seen_count = 1
        peak_band = ev.get("band")
    else:
        first_flagged = row["first_flagged"]
        seen_count = row["seen_count"] + 1
        peak_band = _higher_band(row["peak_band"], ev.get("band"))
    conn.execute(
        """
        INSERT INTO events (id, hazard, place, lat, lon, source_url, first_flagged,
            last_seen, peak_band, seen_count, last_mag, last_alert, last_sig, last_band,
            last_time, band, band_label, hazard_label, alert_label, title,
            feed_cells_json, ground_json, forecast_json, no_news, impact_json)
        VALUES (:id, :hazard, :place, :lat, :lon, :source_url, :first_flagged,
            :last_seen, :peak_band, :seen_count, :last_mag, :last_alert, :last_sig, :last_band,
            :last_time, :band, :band_label, :hazard_label, :alert_label, :title,
            :feed_cells_json, :ground_json, :forecast_json, :no_news, :impact_json)
        ON CONFLICT(id) DO UPDATE SET
            hazard=excluded.hazard, place=excluded.place, lat=excluded.lat, lon=excluded.lon,
            source_url=excluded.source_url, last_seen=excluded.last_seen,
            peak_band=excluded.peak_band, seen_count=excluded.seen_count,
            last_mag=excluded.last_mag, last_alert=excluded.last_alert, last_sig=excluded.last_sig,
            last_band=excluded.last_band, last_time=excluded.last_time, band=excluded.band,
            band_label=excluded.band_label, hazard_label=excluded.hazard_label,
            alert_label=excluded.alert_label, title=excluded.title,
            feed_cells_json=excluded.feed_cells_json, ground_json=excluded.ground_json,
            forecast_json=excluded.forecast_json, no_news=excluded.no_news,
            impact_json=excluded.impact_json
        """,
        {
            "id": ev["id"], "hazard": ev.get("hazard"), "place": ev.get("place"),
            "lat": ev.get("lat"), "lon": ev.get("lon"), "source_url": ev.get("source_url"),
            "first_flagged": first_flagged, "last_seen": ev.get("observed_at", run_at),
            "peak_band": peak_band, "seen_count": seen_count,
            "last_mag": sig.get("mag"), "last_alert": sig.get("alert"), "last_sig": sig.get("sig"),
            "last_band": sig.get("band", ev.get("band")), "last_time": ev.get("event_time"),
            "band": ev.get("band"), "band_label": ev.get("band_label"),
            "hazard_label": ev.get("hazard_label"), "alert_label": ev.get("alert_label"),
            "title": ev.get("title"),
            "feed_cells_json": json.dumps(ev.get("feed_cells") or []),
            "ground_json": json.dumps(ev.get("ground") or []),
            "forecast_json": json.dumps(ev.get("forecast")) if ev.get("forecast") else None,
            "no_news": ev.get("no_news"),
            "impact_json": json.dumps(ev.get("impact") or []),
        },
    )
    for art in ev.get("articles") or []:
        conn.execute(
            """
            INSERT INTO articles (event_id, source, url, title, summary, published, fetched_at)
            VALUES (:event_id, :source, :url, :title, :summary, :published, :fetched_at)
            ON CONFLICT(event_id, url) DO UPDATE SET
                source=excluded.source, title=excluded.title, summary=excluded.summary,
                published=excluded.published, fetched_at=excluded.fetched_at
            """,
            {
                "event_id": ev["id"], "source": art.get("source"), "url": art["url"],
                "title": art.get("title"), "summary": art.get("summary"),
                "published": art.get("published"), "fetched_at": art.get("fetched_at", run_at),
            },
        )


def cmd_ingest(conn: sqlite3.Connection, payload: dict) -> None:
    run_at = payload.get("run_at") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    events = payload.get("events") or []
    for ev in events:
        upsert_event(conn, ev, run_at)
    counts = payload.get("counts") or {}
    conn.execute(
        "INSERT OR REPLACE INTO runs (run_at, flagged_ids, new_count, esc_count, cleared_count) "
        "VALUES (?, ?, ?, ?, ?)",
        (run_at, json.dumps([e["id"] for e in events]),
         counts.get("new", 0), counts.get("escalated", 0), counts.get("cleared", 0)),
    )
    conn.commit()
    print(f"ingested {len(events)} event(s), "
          f"{sum(len(e.get('articles') or []) for e in events)} article link(s) @ {run_at}")


def cmd_dump(conn: sqlite3.Connection) -> None:
    events = {r["id"]: dict(r) for r in conn.execute(
        "SELECT id, hazard, place, lat, lon, first_flagged, last_seen, peak_band, seen_count, "
        "last_mag, last_alert, last_sig, last_band, last_time FROM events")}
    last_run = conn.execute("SELECT run_at, flagged_ids FROM runs ORDER BY run_at DESC LIMIT 1").fetchone()
    out = {
        "events": events,
        "last_run": dict(last_run) if last_run else None,
        "prev_flagged_ids": json.loads(last_run["flagged_ids"]) if last_run else [],
    }
    json.dump(out, sys.stdout, indent=2)


def build_context(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        """
        SELECT * FROM events
        ORDER BY CASE band WHEN 'severe' THEN 0 WHEN 'serious' THEN 1
                           WHEN 'moderate' THEN 2 ELSE 3 END,
                 last_mag DESC, last_time DESC
        """
    ).fetchall()
    events = []
    feeds_seen: list[str] = []
    latest = ""
    for r in rows:
        latest = max(latest, r["last_seen"] or "")
        if (r["id"] or "").startswith("usgs") and "USGS" not in feeds_seen:
            feeds_seen.append("USGS")
        if (r["id"] or "").startswith("gdacs") and "GDACS" not in feeds_seen:
            feeds_seen.append("GDACS")
        arts = conn.execute(
            "SELECT source, url, title, summary, published FROM articles "
            "WHERE event_id = ? ORDER BY id", (r["id"],)
        ).fetchall()
        articles = [dict(a) for a in arts]
        feed_link = None
        if r["source_url"]:
            label = ("USGS event page" if (r["id"] or "").startswith("usgs")
                     else "GDACS event report" if (r["id"] or "").startswith("gdacs")
                     else "Source feed")
            feed_link = {"label": label, "url": r["source_url"]}
        events.append({
            "id": r["id"], "band": r["band"], "band_label": r["band_label"],
            "hazard_label": r["hazard_label"], "alert_label": r["alert_label"], "title": r["title"],
            "place": r["place"], "lat": r["lat"], "lon": r["lon"], "mag": r["last_mag"],
            "feed_cells": json.loads(r["feed_cells_json"] or "[]"),
            "ground": json.loads(r["ground_json"] or "[]"),
            "forecast": json.loads(r["forecast_json"]) if r["forecast_json"] else None,
            "no_news": r["no_news"],
            "impact": json.loads(r["impact_json"]) if r["impact_json"] else [],
            "sources": [{"name": a["source"], "url": a["url"]} for a in articles],
            "articles": articles,
            "feed_link": feed_link,
        })
    n = len(events)
    tz8 = timezone(timedelta(hours=8))
    try:
        local = datetime.strptime(latest[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).astimezone(tz8)
    except ValueError:
        local = datetime.now(tz8)
    gen_date = local.strftime("%Y-%m-%d")
    win = (local.strftime("%H:%M") + " GMT+8") if len(latest) >= 16 else None
    return {
        "title": f"{_SMALL.get(n, str(n))} event{'s' if n != 1 else ''} under watch",
        "generated_at": gen_date,
        "window_end": win,
        "feed_sources": " · ".join(feeds_seen) or "feeds",
        "events": events,
        "events_json": json.dumps(events, ensure_ascii=False),
    }


def cmd_render(conn: sqlite3.Connection, template_path: str, out_path: str) -> None:
    try:
        from jinja2 import Environment, FileSystemLoader, select_autoescape
    except ImportError:
        sys.exit("jinja2 is required: `pip install jinja2` or `uv run --with jinja2 ...`")
    import os
    ctx = build_context(conn)
    tdir, tname = os.path.split(os.path.abspath(template_path))
    world_file = os.path.join(tdir, "world_land_path.txt")
    if os.path.exists(world_file):
        with open(world_file, encoding="utf-8") as wf:
            ctx["world_path"] = wf.read().strip()
    env = Environment(loader=FileSystemLoader(tdir), autoescape=select_autoescape(["html", "j2"]))
    html = env.get_template(tname).render(**ctx)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"rendered {len(ctx['events'])} event(s) -> {out_path}")


def cmd_prune(conn: sqlite3.Connection, days: int) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur = conn.execute("DELETE FROM events WHERE last_seen < ?", (cutoff,))
    conn.commit()
    print(f"pruned {cur.rowcount} event(s) older than {days}d")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["init", "dump", "ingest", "render", "prune"])
    p.add_argument("--db", default="feeds.db")
    p.add_argument("--json", help="ingest: payload path, or '-' for stdin")
    p.add_argument("--template", default="report.html.j2")
    p.add_argument("--out", default="events.html")
    p.add_argument("--days", type=int, default=30)
    args = p.parse_args()

    conn = connect(args.db)
    if args.command == "init":
        print(f"schema ready in {args.db}")
    elif args.command == "dump":
        cmd_dump(conn)
    elif args.command == "ingest":
        raw = sys.stdin.read() if args.json in (None, "-") else open(args.json, encoding="utf-8").read()
        cmd_ingest(conn, json.loads(raw))
    elif args.command == "render":
        cmd_render(conn, args.template, args.out)
    elif args.command == "prune":
        cmd_prune(conn, args.days)
    conn.close()


if __name__ == "__main__":
    main()
