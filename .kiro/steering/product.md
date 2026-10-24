# Product: LNZ Feed Filter

Chrome MV3 extension for TikTok's desktop For You feed. It reads the feed data and video files TikTok already downloads, classifies each upcoming video locally (stressful or not), and skips or drops stressful ones so the user only sees calm content.

## Hard constraints (never break)

- **Passive only.** Never send requests to TikTok, never re-implement or bypass request signing (X-Bogus, msToken, X-Gnarly). Only copy responses the page already receives.
- **Local only.** No external server unless the user configures an HTTP classifier URL.
- **Desktop Chrome only.**
- **No fixed JSON paths.** Walk the JSON to find video objects; TikTok changes formats without notice.
- **Privacy.** Fixtures must go through `scripts/sanitize-fixtures.mjs` (no real handles, user ids or signed URLs). Never read cookies, localStorage or tokens.
- **Turning the extension off restores normal TikTok** with no console errors.

## Ground truth

`FINDINGS.md` holds the measured facts (endpoint, batch size, field gaps, media lookahead 1–2 videos, 5–18 s lead). Check claims against it; measure in the browser before assuming.
