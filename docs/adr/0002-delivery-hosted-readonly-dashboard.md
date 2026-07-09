# 0002 — Delivery: hosted, read-only, auto-refreshing dashboard

- **Status:** Accepted (the *unattended narrative report* aspect is superseded by ADR 0007;
  hosted / read-only / auto-refresh / scheduled-data / quiet-when-unchanged all still stand)
- **Date:** 2026-07-07

## Context

The idea asked for a "crisis online space." Options ranged from the repo's baseline
(a static `dashboard.html` generated on a schedule) up to a real-time situation room or a
multi-user collaborative workspace with accounts and shared state.

## Decision

For v1 the "online space" is a **hosted, always-on, auto-refreshing, read-only web page**
that anyone with the link can open. No accounts, no real-time push, no collaboration.
It runs unattended on a schedule and stays quiet when nothing has changed.

## Consequences

- Deploys online (not just a local file) — hosting/publishing to be decided (QUESTIONS K).
- No auth/user system to build; state is single, shared, read-only.
- "Live" is bounded by the scheduled publish cadence + page auto-refresh, not streaming.
- Real-time push, annotations/collaboration, and accounts are explicitly deferred; if
  wanted later they become new ADRs superseding this one.
