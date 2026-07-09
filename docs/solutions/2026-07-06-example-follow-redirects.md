---
date: 2026-07-06
tags: [example, http, tooling]
problem: Feed fetch returned an empty body even though the URL works in a browser
---

# Follow redirects when fetching feeds

**Symptom:** `curl` on a feed URL returns nothing; the same URL renders fine in
a browser.

**Cause:** The endpoint redirects to its canonical host, and `curl` does not
follow redirects by default.

**Fix:** `curl -L`, or the equivalent option in your HTTP client. Log the final
URL you actually fetched, not the one you asked for.
