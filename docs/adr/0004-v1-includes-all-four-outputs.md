# 0004 — v1 includes all four outputs

- **Status:** Accepted (the "model layer runs in the pipeline" consequence is superseded by
  ADR 0007 — insights/report are generated client-side; the four-output scope still stands)
- **Date:** 2026-07-07

## Context

The idea named four outputs — live map, morning report, analytics, and insights. A leaner
MVP could have shipped map + report first and deferred analytics/insights. The user chose
to include all four in v1.

## Decision

**v1 delivers all four outputs:** the live map dashboard, the morning report, analytics
(quantitative trends), and insights (AI narrative). Insights covers **both** per-event
"why it matters / story angle" **and** a daily overall synthesis. Analytics covers
events/day by hazard, severity mix, region breakdown, and 7/30-day trends.

## Consequences

- v1 requires **stored event history** from the start (analytics + trends depend on it) —
  see the persistence decision (QUESTIONS §P4).
- v1 requires the **model layer** (insights) from the start, not just the deterministic
  pipeline — so the model call and its guardrails are in scope for the first build.
- Larger v1 than the starter's minimal end-state; slicing order still matters (map + report
  is the first working slice, analytics + insights layer on top of the same event store).
- Insights are strictly grounded in feed data (no fabricated numbers; every claim traceable
  to a source; explicit uncertainty).
