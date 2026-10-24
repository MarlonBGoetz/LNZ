# Verification and manual testing

Run `npm run typecheck`, `npm test`, and `npm run build` from the repository root. The production extension is `extension/dist`; the dashboard is `analytics/dist`.

## Automated coverage

The 37 unit/regression tests cover deterministic rules, PIN verifier and retry delays, provider payload validation, analysis request generations, provider changes, delayed skip cancellation/deduplication, concurrent PIN/configuration messages, playback hold transitions, source cleanup/restart, and Chrome toolbar routing.

A result belongs to both a video and its analysis request/provider. Changing providers or disconnecting clears the previous result. Demo labels follow the results actually displayed, including while a different provider is selected in an unsaved draft. A pending skip is cancelled when editing begins or state changes, and its current conditions are checked again immediately before navigation.

## Stage preview — verified 2026-10-24

`chrome-extension://<id>/preview.html` (also reachable from `chrome://extensions` → LNZ → Extension options) mounts the real content script over a synthetic four-clip feed. Verified in Chrome for Testing 133 on macOS with the production `extension/dist`:

- Overlay mounts with the real launcher and filter rail; the panel reports **PROTECTED**.
- Clip 1 (`100000000000039`) resolves to Calm 5% / Learn 87% / Shield no flags → **KEEP** with correct title/author from the stage DOM.
- A locked control opens the PIN dialog and pauses playback.
- PIN `1234` unlocks to **EDIT MODE**; the Learn slider changes to 95%, Save & lock relocks and re-evaluates the clip to **SKIP** (`Learn 91% < 95%`).
- The learning threshold was restored to 50% and the stage returned to clip 1 → **KEEP**.
- The dashboard at `http://localhost:5174` shows the same video, scores and **KEEP** decision from the stage events.

The stage clips and scores are synthetic. They are not a live TikTok run and not model predictions.

## Verified Chromium fixture run — 2026-10-24

The production unpacked extension was loaded into a fresh Chromium profile on the workstation. A controlled TikTok-shaped page was intercepted at a supported URL; no live TikTok account was used. The test interacted with the actual closed Shadow DOM through Chrome DevTools Protocol and trusted mouse/keyboard input.

All seven flow checks passed with zero page script errors: Manifest V3 worker/startup and overlay mount; onboarding PIN confirmation mismatch; locked controls and incorrect/correct PIN; cancel/discard with real video pause/resume; saving/relocking; background-to-content toolbar-message delivery; and persistence after page reload. Protected-overlay and onboarding screenshots were captured. Native toolbar mouse interaction and live TikTok navigation were not exercised.

## Manual Chrome/TikTok checklist

Chrome 137+ branded builds ignore the `--load-extension` command-line switch. Use **Load unpacked** below for daily Chrome, or a Chrome for Testing / Chromium build for scripted runs.

1. Load `extension/dist` with Chrome's Developer mode and **Load unpacked**, then open or reload `https://www.tiktok.com/`.
2. Complete onboarding with a confirmed 4–6 digit PIN. Confirm that no raw PIN appears in stored settings and the panel says **PROTECTED**.
3. Open the panel with the floating launcher and Chrome toolbar action. A TikTok tab opened before installation may need a reload.
4. Attempt a locked setting change. Confirm the PIN dialog opens and playback pauses. An incorrect PIN must leave settings locked; repeated failures must trigger throttling.
5. Unlock, change modes/thresholds, and cancel: the saved configuration must return. Unlock again, save, and refresh: the saved configuration must remain.
6. Scroll to a new video during editing: it must stay paused; leaving editing may resume the current clip, not a previous one.
7. With demo providers selected, confirm **DEMO DATA** is visible. Demo scores are fixtures, not model predictions.
8. Change to a connected local classifier while viewing a rejected demo video. Old scores must clear and no old queued skip may fire. With the service offline, errors/unavailability must be explicit.
9. Test auto-skip with the navigation teammate's adapter on the current live TikTok UI. Verify at most one request for the same video, cancellation when the PIN dialog opens, and no navigation when auto-skip or protection is off.
10. Navigate away/back and restart the browser. Verify cleanup, restored configuration, and the locked state after restart.

The live TikTok DOM/navigation adapter, real classifier services, and native Chrome toolbar mouse interaction require manual testing. Fixture-browser results are recorded separately and must not be represented as live-site verification.
