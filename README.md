# LNZ

Take control of your short-form video feed. LNZ is a Chrome extension that floats a small overlay on TikTok and X, runs three independent AI filters on each video or post with video, and skips what you don't want. Settings are locked behind a PIN.

| Part | Path | What it is |
|---|---|---|
| Extension | `extension/` | MV3 Chrome extension: launcher, panel, PIN lock, onboarding, TikTok and X DOM adapters |
| Dashboard | `analytics/` | Local session monitor + persisted day summary (localhost:5174) |
| Contracts | `shared/` | TypeScript interfaces, decision engine, demo provider, brand mark |

## Run it

Requires Node 20+.

```bash
npm install
npm run build:ext        # -> extension/dist
npm run dev:analytics    # -> http://localhost:5174 (binds 127.0.0.1 only)
npm test
```

Load the extension: Chrome → `chrome://extensions` → Developer mode → **Load unpacked** → `extension/dist`. Open <https://www.tiktok.com> or <https://x.com>. First launch asks you to create a PIN.

Chrome 137+ no longer honours `--load-extension` for branded Chrome. Load unpacked manually, or use Chrome for Testing / Chromium when you need a scripted launch. The automated fixture run in `docs/TESTING.md` used Chrome for Testing 149.

### Stage previews (no platform account needed)

`chrome://extensions` → LNZ → **Extension options**, or open `chrome-extension://<extension-id>/preview.html`. This is a synthetic four-clip TikTok-style stage that mounts the **real content script**, PIN lock, decision engine and demo classifiers. Every value is labelled **DEMO DATA**; the clips are generated for the review and are not TikTok content. Use it to open the panel, test a locked change, unlock/edit/save, and watch auto-skip advance through clips that keep or reject.

The X-style stage is at `chrome-extension://<extension-id>/preview-x.html?platform=x` (linked from the TikTok stage header). It uses the same content script with the X DOM adapter, so the post text, `@handle` and `/status/<id>` become the video identity. It is a controlled timeline, not X content.

Relaunch it with `./scripts/demo-stage.sh`. The script builds the extension, derives the unpacked-extension ID, and opens the stage in Chrome for Testing / Chromium. Set `CHROME_FOR_TESTING` if the browser is elsewhere. Use `LNZ_STAGE=x ./scripts/demo-stage.sh` for the X stage. The dashboard still runs separately with `npm run dev:analytics`.

### Split-screen demo

- Left: Chrome on TikTok or X with LNZ.
- Right: a second Chrome window on `http://localhost:5174` with the **Session** or **Day** tab.

The extension posts every video, score and decision to the dashboard. With no extension connected, press **Run demo** in the dashboard for a labelled fixture stream (or open `?demo=1`). Set the header user with `?user=Your%20Name&role=Researcher`.

If the dashboard runs on another machine (e.g. the GPU box), forward the port: `ssh -L 5174:localhost:5174 <host>`. Keep the relay local; see [PRIVACY.md](PRIVACY.md).

### Day summary

The dashboard's **Day** tab compresses the local day log into unique videos watched, kept/skipped/pending, average Calm and Learn scores, an hourly watch chart, a TikTok/X platform split, Shield flags, session count, and the latest watched videos.

The relay appends every event to `analytics/.data/events-YYYY-MM-DD.jsonl` (gitignored). Keep `npm run dev:analytics` running to record the day; nothing is uploaded. A new session starts after a 30-minute gap.

## How it behaves

- **Launcher**: mask lit cyan when LNZ is on, grey outline when off. Small padlock badge shows lock state. When on, the three filter icons sit under it.
- **Heat rail**: with the panel collapsed, Calm, Learn and Shield carry live health rings — green clear, amber pending/moderate/uncertain, red would skip. A dot on the launcher summarises the current video.
- **X posts**: the adapter selects the most visible video in a timeline post or X's modal player. The post text, `@handle` and `/status/<id>` become the video identity; the same Calm / Learn / Shield rules apply. A rejected post advances to the next timeline article with a video.
- **Locked (PROTECTED)**: filters run; any change opens the PIN dialog. Turning LNZ *on* never needs a PIN; turning it *off* does.
- **Unlocked (EDIT MODE)**: playback pauses while you edit. Save & lock applies the new config and resumes playback. Cancel restores the last saved config.
- **Decision**: a video is kept only if every enabled filter passes. One rejection is enough to skip. Unavailable classifiers are shown as unknown, never as a pass.
- **PIN**: stored only as a PBKDF2-SHA256 verifier (310k iterations, random salt). 3 free attempts, then 30 s doubling back-off. The unlocked flag lives in `chrome.storage.session`, so a browser restart always comes back locked.

The PIN is self-control friction. It cannot stop someone removing the extension in Chrome.

## Privacy

LNZ is a private local build: an unpacked extension, a private repo, a loopback-only dashboard and a gitignored day log. It is not a public Chrome Web Store add-on. Do not port-forward the dashboard or share the extension folder if the idea must stay private. See [PRIVACY.md](PRIVACY.md) for the exact boundary and the honest limit of client-side privacy.

## Demo data

With no models connected, the **Demo** provider returns deterministic fixtures from a hash of the video id. The overlay and dashboard label these **DEMO**. They are not predictions.

## Integrating models and navigation

See [`docs/INTEGRATION.md`](docs/INTEGRATION.md).

## Verification

See [docs/TESTING.md](docs/TESTING.md) for automated coverage and the manual Chrome/TikTok/X checklist. The toolbar action opens the overlay on an existing supported tab, or opens TikTok when no overlay is available.
