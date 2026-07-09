# 0001 — Primary user is a newsroom/editorial analyst

- **Status:** Accepted
- **Date:** 2026-07-07

## Context

The product could serve several kinds of "media analyst": newsroom/editorial, OSINT/
intelligence, corporate comms/PR monitoring, or humanitarian/NGO. Each optimises for a
different question, which changes what counts as a "major event" and what "analytics" and
"insights" should mean.

## Decision

The primary — and for v1, only — user is a **newsroom / editorial analyst**. Their driving
question is **newsworthiness**: *what happened, where, how bad, who is affected, and is it
worth a story now?*

## Consequences

- The "major event" threshold and severity model are tuned for newsworthiness, not just
  raw physical magnitude (see QUESTIONS B).
- Insights are framed as "why it matters / possible story angle," not response logistics.
- No multi-user, roles, or accounts in v1 (see ADR 0002).
- Event detail must be "decision-ready" for a pitch: what/where/severity/affected/sources
  at a glance.
