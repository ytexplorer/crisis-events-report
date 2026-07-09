# Architecture Decision Records

Each ADR captures one decision: its context, the choice made, and the consequences.
They are numbered, append-only, and never rewritten — to change a decision, add a new
ADR that supersedes the old one.

**Format** (keep it short):

```
# NNNN — Title

- **Status:** Proposed | Accepted | Superseded by NNNN
- **Date:** YYYY-MM-DD

## Context
Why this decision was needed.

## Decision
What we chose.

## Consequences
What follows — good and bad.
```

## Index

- [0001 — Primary user is a newsroom/editorial analyst](0001-primary-user-newsroom-analyst.md) — Accepted
- [0002 — Delivery: hosted, read-only, auto-refreshing dashboard](0002-delivery-hosted-readonly-dashboard.md) — Accepted
- [0003 — "Major event" definition & severity model](0003-major-event-and-severity.md) — Accepted
- [0004 — v1 includes all four outputs](0004-v1-includes-all-four-outputs.md) — Accepted (report model superseded by 0007)
- [0005 — Two-layer de-duplication](0005-two-layer-deduplication.md) — Accepted
- [0006 — Stack & hosting: all-on-Vercel, Python pipeline + Next.js front end](0006-stack-and-hosting.md) — Accepted
- [0007 — AI generation is client-side, BYOK, multi-provider](0007-client-side-byok-ai.md) — Accepted (supersedes report model in 0002/0004)

_Core architecture is settled. Remaining open items are detail-level leans in `QUESTIONS.md`
(users/usage, event lifecycle, feed handling, map UX, report/analytics detail)._
