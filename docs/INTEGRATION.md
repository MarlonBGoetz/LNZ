# Integration guide

All shared types live in `shared/src/contracts.ts`. The UI depends only on these.

## Classifiers

### Option A — local HTTP service (no extension code)

Run your model behind a local server, then in the LNZ panel: unlock → Settings → Classifiers → **Local service** → set the URL (default `http://localhost:8000`).

```
GET  /health
  -> { "calm": true, "learn": false, "shield": true }

POST /classify/{calm|learn|shield}
  body: { "video": VideoRef }   // { videoId, url, title?, author?, durationSec?, index? }

  calm  -> { "score": 0.22, "timeline"?: [0.1, 0.3, ...], "regions"?: { "frontal": 0.4, ... }, "model"?: "tribe2-distill-v1" }
  learn -> { "score": 0.81, "model"?: "qwen3-vl-..." }
  shield-> { "flagged": ["S10"], "model"?: "llama-guard-4" }
```

Rules:

- `score` must be in `[0, 1]`. Calm: higher = more predicted stress-related response. Learn: higher = more educational value.
- If you cannot produce a result, return a non-2xx status. The UI shows *Unknown / Error*. Never return a placeholder score.
- Shield returns categorical labels only (`S1`–`S13`, see `SHIELD_CATEGORIES` in `shared/src/filters.ts`). No probabilities.
- `timeline` (per time step) and `regions` (`frontal | parietal | temporal | occipital | limbic | cerebellum`) are optional and drive the dashboard's brain view.

The extension's service worker calls the service, so page CSP does not apply. `host_permissions` already cover `http://localhost:*` and `http://127.0.0.1:*`.

### Option B — in-extension provider

Implement `ClassifierProvider` and return it from `buildProviders()` in `extension/src/background/providers.ts`.

## Video detection, preloading and navigation

The overlay talks to three interfaces:

| Interface | Default (DOM) | File |
|---|---|---|
| `VideoSource` | `TikTokDomVideoSource` — most-visible `<video>` | `extension/src/content/tiktok.ts` |
| `VideoNavigator` | `TikTokDomNavigator` — next button / ArrowDown / scroll | same |
| `PlaybackController` | `TikTokPlayback` — pause & hold during edits | same |

Swap your implementations in `extension/src/content/index.tsx`. Emit a new `VideoRef` whenever the active video changes; results for older `videoId`s are discarded.

## Analytics events

Anything can post to the dashboard relay (`POST http://localhost:5174/api/events`, JSON `AnalyticsEvent` from `shared/src/events.ts`). The dashboard streams them from `/api/stream` (SSE). The relay binds to `127.0.0.1` and has no auth; keep it local.
