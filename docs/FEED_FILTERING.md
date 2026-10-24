# Feed filtering (TikTok + X)

Blocked items are removed from the feed **before the site renders them**. The user keeps scrolling and never lands on a blocked item.

## Layers

| Layer | File | What it does |
|---|---|---|
| Interceptor (MAIN world, `document_start`) | `extension/src/feed/interceptor.ts` | Wraps `fetch` and XHR. For claimed feed responses it extracts items, waits up to `waitBudgetMs` (fetch only, max 400 ms) for verdicts, then returns a copy without blocked items. Unclaimed responses and any error pass through untouched. Also reads TikTok's server-rendered first page. |
| Rules tier | `extension/src/sites/rules.ts` | Keywords, hashtags, creators and ads, matched synchronously at response time, so they work on both fetch and XHR with zero latency. |
| Site adapters | `extension/src/sites/tiktok.ts`, `x.ts` | Pure `claims / extract / filter` per site. TikTok keeps paging fields and never returns an empty page. X never removes cursor entries and filters inside conversation modules. |
| Bridge (isolated, `document_start`) | `extension/src/feed/bridge.ts` | `postMessage` ⇄ interceptor, port `lnz-feed` ⇄ background. |
| Judge ahead (service worker) | `extension/src/background/feedJudge.ts` | Classifies each item as soon as it appears in feed data, 3 at a time, cache by `site:id`. Uses the same providers and `decide()` as the overlay. Fail-open: unverified means keep. |
| DOM safety net | `extension/src/feed/dom.ts` | For items that slipped through (first page, late verdicts). TikTok: a blocked item keeps its box, renders nothing and never plays; landing on one jumps straight to the next allowed item in the direction of travel, and Arrow keys skip over it in one step. X: a blocked cell below the viewport is removed from layout; one already on screen is only silenced, so the page never jumps. |

## Config

Stored at `chrome.storage.local['lnz:removal']` (`normalizeRemoval()` in `sites/types.ts`):

```ts
{ enabled, mode: 'drop-and-jump' | 'jump-only' | 'off', waitBudgetMs, sites: { tiktok, x },
  rules: { keywords, hashtags, creators, blockAds, videoOnly } }
```

The master switch and auto-skip come from the PIN-protected main config. The panel UI for these fields is not built yet. Until it is, it must go through the background's PIN-checked save path, not a direct storage write.

## Limits

- XHR responses are filtered with what is known at that moment (rules plus cached verdicts). Fresh classifier verdicts for XHR items are applied by the DOM layer.
- The site API field names are read defensively. If a site changes shape, `extract` returns `[]` and only the DOM layer acts.
- Classifier latency decides how often the DOM layer is needed. A fast first-pass classifier keeps most removals at the feed-data stage.
