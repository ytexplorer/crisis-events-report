# 0006 — Stack & hosting: all-on-Vercel, Python pipeline + Next.js front end

- **Status:** Accepted
- **Date:** 2026-07-08

## Context

The dashboard needs a scheduled data pipeline, a store, and a rich interactive UI. The user
chose Python, Vercel, and Tailwind + shadcn/ui (React). shadcn/ui implies a React/Next.js
front end; Vercel is the host; the pipeline must run somewhere unattended.

## Decision

**All-on-Vercel** (QUESTIONS §P2-B):

- **Pipeline** — **Python serverless functions**: ingest GDACS + USGS + ReliefWeb(RSS) →
  deterministic dedup → embedding enrichment (hosted embedding API, server-side key) →
  severity + newsworthiness + analytics → emit a **versioned JSON contract**.
- **Scheduling** — **Vercel Cron** daily refresh + an **on-demand** serverless refresh route
  when the page loads, with short caching (QUESTIONS §R3/§R6). Skip republish if unchanged.
- **State** — Vercel-hosted storage (Postgres or KV/Blob; exact choice at spec time) for event
  history + dedup keys.
- **Front end** — **Next.js + Tailwind + shadcn/ui**, read-only, the sole consumer of the JSON
  contract; map via **react-leaflet + OSM tiles** (no API key); renders map, events, analytics,
  and the client-side AI layer (see ADR 0007).

## Consequences

- Serverless time/memory limits shape the pipeline: no local ML model (hence hosted embedder),
  and long work must be chunked or moved on-demand.
- Two distinct key types: a **server-side embedding key** (owner-paid, cheap) and **client-side
  LLM keys** (viewer BYOK, ADR 0007). No server-side LLM key exists.
- Hobby-plan cron is daily; intraday freshness comes from the on-demand refresh, not the cron.
- Deviates from the starter's GitHub-Actions + `claude -p` + `dashboard.html` shape; recorded
  as a deliberate deviation.
