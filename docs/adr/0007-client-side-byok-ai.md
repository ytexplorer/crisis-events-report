# 0007 — AI generation is client-side, BYOK, multi-provider

- **Status:** Accepted
- **Date:** 2026-07-08
- **Supersedes:** the report-generation model in ADR 0002 and ADR 0004 (the narrative was to be
  generated unattended in the pipeline; it is now generated client-side on demand).

## Context

The report and insights need an LLM. The user chose that viewers bring their own key (BYOK) for
Gemini, OpenAI, or Claude, entered on the webapp. An unattended 08:30 narrative is impossible
under BYOK (no human, no key at that hour), so the report model must change.

## Decision

- **All LLM generation is client-side, BYOK.** The viewer supplies a **Gemini / OpenAI /
  Claude** key on the webapp; the provider abstraction lives in the **front end**; the browser
  calls the chosen provider **directly**. The Python pipeline makes **no** LLM calls.
- **Keys stay in the browser** (localStorage), are never sent to our backend, are clearable, and
  carry a "used directly from your browser" caveat.
- **On-demand generation** — the report + insights (both per-event "why it matters / angle" and
  a daily synthesis) are generated when the analyst opens the dashboard with a key. There is
  **no unattended narrative report**; the scheduled job refreshes **data only**.
- **Graceful degradation** — map + events + analytics render **without** a key; only the AI
  narrative requires one.
- **Grounding** — insights may only interpret data present in the JSON contract; every claim
  traceable to a source feed; explicit uncertainty; no fabricated numbers.

## Consequences

- No server-side LLM cost or key; per-viewer, potentially varying narrative.
- Each provider needs browser-side handling of its own auth/CORS quirks (Anthropic's
  direct-browser header, OpenAI's browser flag, Gemini's browser SDK).
- The "change-detection gate" now governs whether **data** is republished/notified, not whether
  a model runs (there is no server model). Reconciles QUESTIONS §L3.
- Supporting all three providers from v1 is deliberate (QUESTIONS §Q2) and adds front-end
  surface area.
