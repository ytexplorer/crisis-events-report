# 0005 — Two-layer de-duplication (deterministic gate + embedding enrichment)

- **Status:** Accepted
- **Date:** 2026-07-08

## Context

The same real-world event arrives from GDACS, USGS, and ReliefWeb under different IDs and
on different days. Semantic embeddings were requested to match them. But the starter's rule
is that the change-detection gate is deterministic and never calls a model.

## Decision

De-duplication is two layers:

1. **Deterministic dedup** — GLIDE code / shared source IDs / same-hazard + spatial (~100km)
   + time-window matching. This is the *only* thing that drives the change-detection gate and
   the "is this a new event?" decision. Model-free, repeatable.
2. **Semantic embedding enrichment** — embedding-similarity matching of fuzzy *text* records
   (chiefly ReliefWeb prose) onto an existing canonical event. Runs only *after* the gate has
   fired, within a same-hazard + space/time candidate bucket, above a tuned cosine threshold.
   It **never** gates a wake-up and never overrides a deterministic match.

## Consequences

- The gate stays deterministic and cheap; embeddings add recall for text-only records without
  compromising determinism.
- Embeddings use a hosted embedding API (see the embedding-key decision, QUESTIONS §R1) — not a
  local model, because the pipeline runs in a short-lived serverless function.
- A cosine threshold + candidate-bucketing must be tuned against real data.
