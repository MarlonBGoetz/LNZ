# LNZ Feed Filter

A Chrome extension (Manifest V3, desktop) that keeps stressful videos out of your TikTok For You feed.

It reads the feed data and video files TikTok **already downloads** for upcoming videos, runs a stress classifier **locally in the browser**, and then either removes a stressful video from the feed before TikTok renders it (text classifiers) or skips it automatically (the video + audio model). The skip is pre-emptive: an upcoming video is paused, muted and blurred before it reaches the screen.

**Challenge track:** _TBD (fill in)_

Built with Kiro. See [KIRO.md](KIRO.md) for how.

- Passive only: no requests to TikTok, no touching request signing (X-Bogus, msToken).
- Local only: models run in the extension (WebGPU, WASM fallback). No server unless you configure an HTTP classifier.
- Ground truth about TikTok's responses and media timing: [FINDINGS.md](FINDINGS.md).

## Quick start

Requirements: Chrome 120+ on desktop, Node 20+.

```sh
npm install
npm run build        # writes dist/ (≈83 MB with the model)
npm test             # 159 tests: parser on fixtures, pipeline, property-based, TRIBE model
npm run typecheck
```

1. Open `chrome://extensions`, enable **Developer mode**, click **Load unpacked** and select `dist/`.
2. Open https://www.tiktok.com/ (For You). Pin the LNZ icon and open its popup.
3. Choose a classifier and mode (below). Turn on **Debug overlay** to see what's happening.
4. After a rebuild, click the reload icon on the extension card, then reload TikTok.

### Model files

The TRIBE student model (distilled by our teammate from Meta TRIBE v2) lives in `model/tribe_student_export/`. The build copies the three fp16 ONNX models and `stress_readout.json` into `dist/models/`. The TikHarm demo clips and traces (`demo/`, `live_demo.html`) are **not** in the repo: they contain third-party videos, uploader handles and transcripts. Without them the extension works fully; only the in-browser self-test page and the demo-trace test (auto-skipped) need them.

## How to test

| What | Popup settings | What you should see |
|---|---|---|
| Capture | any, Debug overlay on | Overlay lists upcoming videos before they play. |
| Skip (acceptance) | Classifier **keyword**, pattern `#test` (or `fyp` to see it often), Mode **skip** | Red rows are skipped automatically, log under "Recent skips". |
| Drop (acceptance) | same + **Drop mode** | Blocked videos never appear; `dropped` counter rises. |
| Stress text model | Classifier **stress text model** | Captions with war/death/horror etc. are blocked; reason shown per row. |
| TRIBE video model | Classifier **TRIBE stress model**, Mode **skip** | `model ready (webgpu)`, a `stress 0.xx · 10s · ~2000ms` note per row, scores ≥ threshold are skipped. |
| Auto-scroll | **Auto-scroll**, N = 5 | Feed advances by itself (`Alt+Shift+A` toggles). |
| Off | untick **Enabled**, reload | Normal TikTok, no errors on the extension card. |
| No own requests | DevTools → Network on tiktok.com | No requests from the extension (only its own `chrome-extension://` files). |

TRIBE self-test (needs the demo `.mp4` files): open `chrome-extension://<id>/selftest.html` with the tab visible. It runs demo clips through the browser pipeline and compares against the exported curves (we measured mean abs error 0.023 on the final stress score).

## How it works

```
TikTok page (MAIN world)        content script (bridge)              extension frame on tiktok.com
injected.js                      bridge.js                            model-host.html
 wraps fetch/XHR ── item_list ─▶ parse → FeedItem (walks JSON)
 tees media fetch ── chunks ───▶ MediaStore → clip ── MessagePort ──▶ decode (4 fps, 32 kHz)
 drop: holds batch ◀─ blockIds ─ classifier + timeout policy          → log-mel → ONNX encoders + head
 play() guard                    VerdictCache (by video id)           → stress readout ── verdict ──▶
                                 skip / pre-blur / auto-scroll
                                 overlay + export (last 500 items)
```

- **Feed:** `/api/recommend/item_list/` responses (6–7 items) and the embedded `__UNIVERSAL_DATA_FOR_REHYDRATION__` first batch. Hooks run at `document_start`.
- **Media:** TikTok downloads the next 1–2 videos 5–18 s before they play. We copy those streams (including partial downloads) and map them to items through `playAddr` / `bitrateInfo` / `bitrateAudioInfo` URLs.
- **Verdicts** are final and cached by id. A skipped video stays skipped.
- **Media classifiers** run one clip at a time, current video first, then the next ones.

### Modes

| Setting | Effect |
|---|---|
| `skip` (default) | Upcoming blocked videos are paused, muted and blurred in advance. When one becomes current, the extension jumps past it instantly (adaptive navigator: instant scroll → ArrowDown → smooth scroll, the one that works is tried first next time). Pending verdict → "checking…" hold for up to **Hold timeout**, then **When unanswered** applies. |
| `observe` | Capture, classify and log only. |
| Drop mode | Text classifiers only. Holds each `item_list` response until the classifier answers (or times out) and removes blocked items before TikTok sees them. Trade-off: adds that latency to every batch; on timeout the batch passes unchanged and skip mode catches the rest; it always keeps one item so TikTok doesn't refetch in a loop; the embedded first batch isn't filtered. |
| failClosed / failOpen | Unanswered video becomes block (skip) or allow (play). |

### Classifiers

| Name | Input | Notes |
|---|---|---|
| `stub` | metadata | Allows everything. |
| `keyword` | metadata | Blocks when caption contains the pattern or a hashtag equals it. |
| `stressText` | metadata | Weighted stress lexicon over caption, hashtags, topic labels. Instant. Test stand-in. |
| `tribe` | video + audio | Distilled TRIBE v2 student: MobileCLIP-S1 + EfficientAT encoders, causal head → 6 stress ROIs → logistic readout. Threshold 0.67 and seconds analyzed (10) are configurable. |
| `mockStress` | media | Fake curve + latency, for UI testing. |
| `http` | metadata | POSTs `{ items }` (without `raw`) to your URL via the service worker; expects `{ "<id>": "allow" \| "block" \| "unknown" }`. Asks host permission for that origin only. |

To add one: implement `Classifier` in `src/classifier/types.ts`, register it in `src/classifier/registry.ts`, add an `<option>` in `static/popup.html`.

## Known limits

- TRIBE accuracy is modest. Our teammate's report gives AUROC 0.62 on held-out TikHarm clips; at 0.67 it catches ~57% of harmful demo clips and flags ~24% of safe ones. The labels are "harmful", not "stressful".
- Video-based verdicts can only skip, not drop: TikTok downloads media after the batch has arrived.
- Long videos come as separate audio/video files; when the partial audio can't be decoded, the clip is scored on video only (`no audio` in the overlay).
- Desktop For You layout and response formats can change.
- WASM fallback is ~8 s per 10 s clip (WebGPU ~1.5–2 s).

## Licenses and data

- Extension source: our own work.
- TRIBE v2 and models distilled from it: **CC BY-NC 4.0 (non-commercial)**. MobileCLIP and EfficientAT: see their repositories. Training data: TikHarm (Kaggle `anhoangvo/tikharm-dataset`), follow its terms.
- `fixtures/` are real TikTok responses with personal data removed by `scripts/sanitize-fixtures.mjs` (handles, user ids, signed URLs).

## Layout

```
src/injected/          MAIN-world hooks (fetch/XHR, media tee, drop, play guard)
src/bridge/            content script: stores, scheduler, player control, navigator, overlay, model-host client
src/model-host/        hidden extension frame that runs the model
src/model/tribe/       contract, decode, log-mel, features, pipeline, ONNX engine
src/classifier/        interface, built-ins, TRIBE, timeout policy, registry
src/platforms/tiktok/  parser, media URL mapping, drop filter, config
src/background/        service worker (config, HTTP classifier proxy, shortcuts)
src/popup/, static/    settings UI, manifest, model-host and self-test pages
src/selftest/          in-browser model check
fixtures/              sanitized real responses
test/                  vitest + fast-check
model/                 TRIBE student export (from our teammate)
.kiro/                 steering, project agent, hooks
```
