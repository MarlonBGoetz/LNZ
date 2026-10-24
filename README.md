# LNZ

Take control of your short-form video feed. LNZ is a Chrome extension that floats a small overlay on TikTok, runs three independent AI filters on each video, and skips what you don't want. Settings are locked behind a PIN.

| Part | Path | What it is |
|---|---|---|
| Extension | `extension/` | MV3 Chrome extension: launcher, panel, PIN lock, onboarding, TikTok DOM glue |
| Dashboard | `analytics/` | Local live-analysis dashboard (localhost:5174) for the split-screen demo |
| Contracts | `shared/` | TypeScript interfaces, decision engine, demo provider, brand mark |

## Run it

Requires Node 20+.

```bash
npm install
npm run build:ext        # -> extension/dist
npm run dev:analytics    # -> http://localhost:5174 (binds 127.0.0.1 only)
npm test
```

Load the extension: Chrome → `chrome://extensions` → Developer mode → **Load unpacked** → `extension/dist`. Open <https://www.tiktok.com>. First launch asks you to create a PIN.

### Split-screen demo

- Left: Chrome on TikTok with LNZ.
- Right: a second Chrome window on `http://localhost:5174`.

The extension posts every video, score and decision to the dashboard. With no extension connected, press **Run demo** in the dashboard for a labelled fixture stream (or open `?demo=1`). Set the header user with `?user=Your%20Name&role=Researcher`.

If the dashboard runs on another machine (e.g. the GPU box), forward the port: `ssh -L 5174:localhost:5174 <host>`.

## How it behaves

- **Launcher**: mask lit cyan when LNZ is on, grey outline when off. Small padlock badge shows lock state. When on, the three filter icons sit under it.
- **Locked (PROTECTED)**: filters run; any change opens the PIN dialog. Turning LNZ *on* never needs a PIN; turning it *off* does.
- **Unlocked (EDIT MODE)**: playback pauses while you edit. Save & lock applies the new config and resumes playback. Cancel restores the last saved config.
- **Decision**: a video is kept only if every enabled filter passes. One rejection is enough to skip. Unavailable classifiers are shown as unknown, never as a pass.
- **PIN**: stored only as a PBKDF2-SHA256 verifier (310k iterations, random salt). 3 free attempts, then 30 s doubling back-off. The unlocked flag lives in `chrome.storage.session`, so a browser restart always comes back locked.

The PIN is self-control friction. It cannot stop someone removing the extension in Chrome.

## Demo data

With no models connected, the **Demo** provider returns deterministic fixtures from a hash of the video id. The overlay and dashboard label these **DEMO**. They are not predictions.

## Integrating models and navigation

See [`docs/INTEGRATION.md`](docs/INTEGRATION.md).

## Verification

See [docs/TESTING.md](docs/TESTING.md) for automated coverage and the manual Chrome/TikTok checklist. The toolbar action opens the overlay on an existing supported tab, or opens TikTok when no overlay is available.
