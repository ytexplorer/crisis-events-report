# 0003 — "Major event" definition & severity model

- **Status:** Accepted
- **Date:** 2026-07-07

## Context

The dashboard must decide which events appear by default. Options ranged from raw feed
alert levels, to per-hazard physical thresholds, to a newsworthiness-weighted measure. For
a newsroom the interesting event is not always the physically largest one.

## Decision

Compute a single internal **Severity** from the feeds' own signals (GDACS colour;
USGS `mag` / `sig` / `alert`), tuned per hazard type, then apply a **newsworthiness boost**
for events near population centres / capital cities — from v1, not later.

- Earthquakes: M≥5.5 globally, OR `sig`≥600, OR any non-null USGS `alert`.
- A fixed default threshold gates the default map view; dashboard filters can widen/narrow.
- Minor/Green events are hidden by default, available behind a "show all" filter.
- USGS `automatic` (unreviewed) events are shown, badged "provisional".

## Consequences

- Needs a per-hazard severity mapping and a population-proximity lookup (adds a small
  geospatial reference dataset).
- The default view is opinionated; the filter set must let an analyst override it.
- Thresholds will need tuning against real feed volume during the first slice.
