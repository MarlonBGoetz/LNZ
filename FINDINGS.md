# FINDINGS (Step 0)

Captured 2026-10-24, logged-in desktop Chrome 155, `https://www.tiktok.com/` For You.
Method: `extension/injected.js` (MAIN world, `document_start`) copied responses the page already received. No extra requests.

## Fixtures

| File | Source | Items |
|---|---|---|
| `rehydration_foryou.json` | `<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">` | 3 |
| `item_list_1..5.json` | `/api/recommend/item_list/` | 6, 6, 6, 7, 7 |

Fixtures are sanitized with `scripts/sanitize-fixtures.mjs`. All keys are kept. Handles, names, user IDs and `secUid` become consistent `user_N` pseudonyms, URL values become `https://redacted.invalid/`, ad tracking blobs are scrubbed, and non-feed rehydration scopes (your account data) are emptied. Video IDs, captions, hashtags, stats and labels are unchanged.

## Endpoint

- `GET https://www.tiktok.com/api/recommend/item_list/?…`, called via **`fetch`** on the main thread (not XHR, not a worker).
- About 4 calls per 10 videos scrolled.
- Query params include `count=6`, `pullType`, `itemID`, `vv_count_fyp`, plus signing (`msToken`, `X-Bogus`, `X-Gnarly`). We don't touch these.
- Hook at `document_start` (MAIN world) so the wrapper is in place before TikTok's code runs. (An earlier note blamed TikTok caching `fetch`; the real cause was that AppleScript runs JS in an isolated world, so that test wrapper never touched the page's `fetch`.)

## Batch size

- Network: 6–7 items (`count=6`; an ad brings it to 7).
- Embedded first batch: 3 items.

## Top-level keys

- `item_list`: `extra, hasMore, itemList, log_pb, statusCode, status_code, status_msg`.
- Embedded: `__DEFAULT_SCOPE__` → `webapp.app-context, webapp.biz-context, webapp.i18n-translation, seo.abtest, webapp.updated-items, webapp.a-b`.
  The first-batch videos are in **`webapp.updated-items`**, an array of video objects, not an `itemList`.

## Video item keys (all 32 network items)

`id` (string), `desc`, `createTime` (unix seconds, number), `isAd`, `author`, `authorStats`, `authorStatsV2`, `music`, `stats`, `statsV2`, `video`, `CategoryType`, `ShowAIGC`, `contentContext`, `item_control`, `digged`, `duetDisplay`, `stitchDisplay`, `forFriend`, `itemCommentStatus`, `officalItem`, `originalItem`, `privateItem`, `secret`, `shareEnabled`.

Mapping to `FeedItem`:

| FeedItem | Source |
|---|---|
| caption | `desc` |
| hashtags | `challenges[].title`, `textExtra[].hashtagName` (type 1 = hashtag, 0 = @mention) |
| language | `textLanguage` (`en`, `zh-Hans`, `vi`, `un` = undetermined) |
| author | `author.uniqueId`, `author.nickname`, `author.verified`; followers in **`authorStats.followerCount`** (item level, not under `author`) |
| video | `video.duration`, `width`, `height`, `cover`, `playAddr`, `subtitleInfos[]` |
| music | `music.id`, `title`, `authorName` |
| stats | `stats.*` numbers are **rounded** (13700); `statsV2.*` are exact **strings** ("13700"). Prefer `statsV2`. `collectCount` = saves. |
| labels.aigc | `ShowAIGC` (bool), `AIGCDescription` (always "" so far), `moderationAigcLabelType` (2/32) |
| labels.diversification | `diversificationLabels` (**embedded items only**, absent from all network items) |

## Sometimes missing

| Field | Present |
|---|---|
| `textLanguage`, `AIGCDescription`, `collected`, `contents`, `author.verified`, `music.authorName` | 30/32 (missing on ads) |
| `textExtra` | 28/32 |
| `challenges` | 26/32 |
| `video.subtitleInfos` | 20/32 |
| `diversificationLabels` | 0/32 network, 2/3 embedded |
| `ad_info`, `adAuthorization` | ads only |

`desc` was never empty in this sample, but treat it as optional.

## Things that affect the design

1. **Items repeat across batches.** 8 of 32 network items reappeared in the next batch (b2/b3 share 4 IDs, and b4/b5 share 3, including the ad). Verdicts must be cached by `id`, and drop mode must drop a repeat every time it appears.
2. **Ads** look like normal items with `isAd: true` and `ad_info`, and lack several fields.
3. **Media URLs are signed and expire** (`expire`, `signature`, `policy` params on `playAddr`; `UrlExpire` on subtitles).
4. The embedded and network shapes differ (`updated-items` vs `itemList`, and `diversificationLabels` only in embedded), which confirms we should walk the JSON rather than use fixed paths.
5. Drop for the first batch means rewriting the `__UNIVERSAL_DATA_FOR_REHYDRATION__` text before TikTok parses it. This is unverified and will be tested during the drop step.

# Step 0b: video/audio availability (passive)

Measured over 16 videos scrolled at 3–15 s each.

- **Playback uses MediaSource.** `<video>` has `blob:https://www.tiktok.com/...` src, `crossOrigin="use-credentials"`, `preload="auto"`. Two `<video>` elements exist: current and next.
- **Media bytes arrive via main-thread `fetch`** from `v16-webapp-prime.us.tiktok.com/video/tos/...` (62 requests). URL paths match the item's `playAddr` / `bitrateInfo` URLs, so each download maps to an item `id`.
- **Media lookahead is 1–2 videos.** First media fetch for an item started when the user was 2 videos before it (3 cases) or 1 before (1 case). The next video was fully buffered (33.8/33.8 s) while paused.
- **Frames are readable.** `drawImage(video)` + `getImageData` on the current video succeeded (blob source is same-origin, canvas not tainted). Audio via `captureStream()` should work for the same reason (not tested).
- Metadata lookahead stays ~10–15 items (Step 0), far ahead of media.

Implications:
1. Video+audio verdicts are possible only for the next 1–2 items, with a time budget of roughly the current video's remaining watch time.
2. Drop mode can't use video verdicts: a batch reaches TikTok before any of its media is downloaded. Drop can only use metadata; video verdicts drive skip.
3. Two passive ways to feed the model: tee the media `fetch` responses (verified below), or capture frames/audio from the playing `<video>`.

## Media tee (verified)

Teed TikTok's own media `fetch` responses with `res.clone().body` streaming (54 responses). No extra requests.

| Video length | Delivery | What we get before play |
|---|---|---|
| Short (≈ under 60 s, most items) | One progressive MP4 (`ftyp, moov, mdat`), **video and audio muxed**, HTTP 200 | The whole file (0.8–5.4 MB), usually complete 5–18 s before play |
| Long | DASH-style fragmented MP4, **separate video and audio files**, HTTP 206 ranges (`ftyp/moov` header, then `sidx` + fragments) | A prefix of both tracks, e.g. 129 s video: 7.9/18.8 MB video, 0.58/1.6 MB audio, ~13 s before play |

- Body is readable (CORS-OK, `video/mp4`). `content-range` header is exposed.
- TikTok aborts downloads once its buffer is full, then resumes with later ranges. A tee that waits for `arrayBuffer()` loses the data; reading the stream keeps everything delivered so far.
- Video URLs map to item `id` via `playAddr` / `bitrateInfo[].PlayAddr.UrlList`. Separate audio URLs don't match those; likely `video.bitrateAudioInfo` (present 17/32), unverified. They are requested in the same instant as the paired video track.
- Already-watched videos are sometimes re-downloaded; dedupe by `id`.
