# Verification and manual testing

Run `npm run typecheck`, `npm test`, and `npm run build` from the repository root. The production extension is `extension/dist`; the dashboard is `analytics/dist`.

## Automated coverage

The 54 unit/regression tests cover deterministic rules, PIN verifier and retry delays, provider payload validation, analysis request generations, provider changes, dashboard config re-announcement, collapsed-rail heat mapping, day-summary aggregation, TikTok/X id collision separation, delayed skip cancellation/deduplication, concurrent PIN/configuration messages, playback hold transitions, source cleanup/restart, the X toolbar hint, and Chrome toolbar routing.

A result belongs to both a video and its analysis request/provider. Changing providers or disconnecting clears the previous result. Demo labels follow the results actually displayed, including while a different provider is selected in an unsaved draft. A pending skip is cancelled when editing begins or state changes, and its current conditions are checked again immediately before navigation.

## Stage previews — verified 2026-10-24

`http://localhost:5174/stage/tiktok.html` mounts the real content script over a synthetic four-clip TikTok-style feed. The X-style stage is `preview-x.html?platform=x` and uses the same content script with the X post adapter. Verified in Chrome for Testing 149 on macOS with the production `extension/dist`:

- Overlay mounts with the real launcher and filter rail; the panel reports **PROTECTED**.
- Clip 1 (`100000000000039`) resolves to Calm 5% / Learn 87% / Shield no flags → **KEEP** with correct title/author from the stage DOM; the collapsed rail shows three green rings and a green launcher dot.
- Clip 3 (`100000000000024`) shows an amber Calm ring at 35% and a green Learn/Shield pair; the launcher dot is amber.
- Clip 4 (`100000000000043`) shows a red Shield ring for the S1 flag, a green Calm ring, an amber Learn ring and a red launcher dot → **SKIP**.
- A locked control opens the PIN dialog and pauses playback.
- PIN `1234` unlocks to **EDIT MODE**; the Learn slider changes to 95%, Save & lock relocks and re-evaluates the clip to **SKIP** (`Learn 91% < 95%`).
- The learning threshold was restored to 50% and the stage returned to clip 1 → **KEEP**.
- The dashboard at `http://localhost:5174` shows the same video, scores and **KEEP** decision from the stage events.
- The stage header's two-icon TikTok/X switch jumps between `preview.html` and `preview-x.html?platform=x`; the active interface is marked with `aria-current="page"`.
- X post 1 (`@nightatlas`, status `100000000000039`) shows the post text and `@handle` in the panel, with Calm 5% / Learn 87% / Shield no flags → **KEEP**.
- X post 2 (`100000000000004`) is rejected and the X navigator advances to post 3 (`100000000000024`, amber Calm → **KEEP**).
- X post 4 (`100000000000043`) flags **S1 Violent crimes**, the rail turns red for Shield and the launcher dot is red → **SKIP**.

The stage clips, posts and scores are synthetic. They are not a live TikTok/X run and not model predictions.

## Day summary — verified 2026-10-24

With the local relay running, the dashboard's **Day** tab was checked against the mixed demo log:

- 7 unique videos: **3 TikTok + 4 X**; 4 kept, 3 skipped, 7 analyzed.
- Average Calm 36%, average Learn 64%; hour chart stacked cyan (kept) and red (skipped) in the 17:00 bucket.
- Shield flags: **S1 Violent crimes × 1**; one session; first activity 05:39 PM, last 05:44 PM.
- Recently watched listed both platforms with the correct post/clip title, platform tag, Calm/Learn scores and KEEP/SKIP decision.
- The same numeric id on TikTok and X (`100000000000039`) is separated by platform in the day log and counts as two videos, not one.

The day log lives in `analytics/.data/events-2026-10-24.jsonl` (gitignored). It is local-only, unauthenticated, and bound to `127.0.0.1`; see `PRIVACY.md`.

## Half-screen session layout — verified 2026-10-24

At 756×806 (the right-hand demo half), the Session view's four cards fit with `scrollHeight === 806` and no scrolling:

- 2×2 grid: Calm, Learn, Shield, Filter Rules.
- The Calm card replaces the brain illustration with four lit lobe tiles (Frontal, Parietal, Temporal, Occipital); the 71% Occipital tile is the strongest lit. Limbic and Cerebellum remain as small chips.
- The header is compact (LNZ, relay/linked/protected/demo, avatar), and the Session / Day tabs are visible.
- The session/log sections are hidden at this width so the four main cards fit.

## Verified Chromium fixture run — 2026-10-24

The production unpacked extension was loaded into a fresh Chromium profile on the workstation. A controlled TikTok-shaped page was intercepted at a supported URL; no live TikTok account was used. The test interacted with the actual closed Shadow DOM through Chrome DevTools Protocol and trusted mouse/keyboard input.

All seven flow checks passed with zero page script errors: Manifest V3 worker/startup and overlay mount; onboarding PIN confirmation mismatch; locked controls and incorrect/correct PIN; cancel/discard with real video pause/resume; saving/relocking; background-to-content toolbar-message delivery; and persistence after page reload. Protected-overlay and onboarding screenshots were captured. Native toolbar mouse interaction and live TikTok navigation were not exercised.

## Manual Chrome/TikTok/X checklist

Chrome 137+ branded builds ignore the `--load-extension` command-line switch. Use **Load unpacked** below for daily Chrome, or a Chrome for Testing / Chromium build for scripted runs.

1. Load `extension/dist` with Chrome's Developer mode and **Load unpacked**, then open or reload `https://www.tiktok.com/` or `https://x.com/`.
2. Complete onboarding with a confirmed 4–6 digit PIN. Confirm that no raw PIN appears in stored settings and the panel says **PROTECTED**.
3. Open the panel with the floating launcher and Chrome toolbar action. A TikTok tab opened before installation may need a reload.
4. Attempt a locked setting change. Confirm the PIN dialog opens and playback pauses. An incorrect PIN must leave settings locked; repeated failures must trigger throttling.
5. Unlock, change modes/thresholds, and cancel: the saved configuration must return. Unlock again, save, and refresh: the saved configuration must remain.
6. Scroll to a new video during editing: it must stay paused; leaving editing may resume the current clip, not a previous one.
7. With demo providers selected, confirm **DEMO DATA** is visible. Demo scores are fixtures, not model predictions.
8. Change to a connected local classifier while viewing a rejected demo video. Old scores must clear and no old queued skip may fire. With the service offline, errors/unavailability must be explicit.
9. Test auto-skip with the navigation teammate's adapter on the current live TikTok UI. Verify at most one request for the same video, cancellation when the PIN dialog opens, and no navigation when auto-skip or protection is off.
10. Navigate away/back and restart the browser. Verify cleanup, restored configuration, and the locked state after restart.
11. On X, scroll to a timeline post with a video. Confirm the overlay anchors to that video and the panel shows the post text and `@handle`; confirm the `status/<id>` becomes the video id.
12. Open an X video in the modal player, then trigger a rejected post: the X navigator should leave the modal and advance to the next timeline article with a video. Verify at most one request for the same post.
13. Reload the extension on X and use the toolbar action. A tab opened before installation should show the **Reload this X tab** hint; the X and TikTok counts should appear separately in the dashboard Day view.

The live TikTok/X DOM and navigation adapters, real classifier services, and native Chrome toolbar mouse interaction require manual testing. X selectors use `data-testid="User-Name"`, `data-testid="tweetText"` and `/status/<id>` links; X can change these, so re-check after site updates. Fixture-browser results are recorded separately and must not be represented as live-site verification.
