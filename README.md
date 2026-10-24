# LNZ

Take control of your short-form video feed. LNZ is a Chrome extension that floats a small overlay on TikTok and X, runs three independent AI filters on each video or post with video, and skips what you don't want. Settings are locked behind a PIN.

| Part | Path | What it is |
|---|---|---|
| Extension | `extension/` | MV3 Chrome extension: launcher, panel, PIN lock, onboarding, TikTok and X DOM adapters |
| Dashboard | `analytics/` | Local session monitor + persisted day summary (localhost:5174) |
| Contracts | `shared/` | TypeScript interfaces, decision engine, demo provider, brand mark |
| Calm model | `models/` | Browser-ready ONNX student distilled from Meta's TRIBE v2, stress readout, PyTorch weights |
| Distillation pipeline | `pipeline/` | GPU pipeline that produced the Calm model: data prep, transcription, TRIBE teacher, student features, training and export |
| Brain demo | `brain-demo/` | Second-by-second replay of the model on 60 held-out clips (`live_demo.html`) |

## Calm model: TRIBE v2 distilled for the browser

The Calm filter is built on **TRIBE v2**, Meta's brain-encoding model, which predicts fMRI responses across the cortex from video, audio and speech. TRIBE is far too large for a browser. It needs V-JEPA 2, Llama 3.2 3B, Wav2Vec-BERT and a WhisperX transcript, and takes about 80 s per 10 s clip on an H100. We distilled it into a **student** small enough to run next to the video, live, once per second.

### Strengths

- **Small and fast:**
  - frozen MobileCLIP-S1 vision encoder (21.5M params) and EfficientAT mn10_as audio encoder (4.9M);
  - a head under 5M params;
  - about 10 ms per one-second window on an H100.
  - The fp16 ONNX files total about 54 MB.
- **Live by design:** a causal 3-second window, so the score updates every second as the clip plays. It needs no transcript and no lookahead.
- **Brain-shaped output:** each second, the student predicts all 148 Destrieux cortical parcels and 6 regions of interest (left/right anterior insula, dACC, mPFC, early auditory, early visual). It doesn't just output a single opaque score, so the dashboard can show *where* a clip is predicted to drive the brain.
- **Tracks the teacher:** on held-out test clips, the parcel-level correlation with TRIBE is 0.50 mean and 0.54 median. By region: visual 0.63, auditory 0.50, mPFC 0.40, insula 0.33, dACC 0.22.
- **Fits LNZ's Calm contract:**
  - the running stress readout gives a `score` in `[0, 1]`;
  - the per-second curve gives the `timeline`;
  - ROI values can feed `regions`.

  See [`docs/INTEGRATION.md`](docs/INTEGRATION.md).
- **Reproducible and cost-capped:** the pipeline ran on two RunPod H100s, with a dead-man switch that shuts each pod down on its own. Clip work is shared through atomic claim files, so pods never duplicate work. The run cost about $10.

### Limits

- **Stress AUROC on TikHarm:** student 0.62, TRIBE regions 0.68. A raw-feature baseline reaches 0.93, because TikHarm's labels are moderation tags that correlate with language and region, not stress ratings.
- **Cortex only:** TRIBE predicts no subcortical regions such as the amygdala.
- **English only:** TRIBE's text pathway assumes English.

Full numbers are in [`docs/CALM_MODEL_REPORT.md`](docs/CALM_MODEL_REPORT.md). The demo clips are broken down in [`brain-demo/DEMO_CLIPS.md`](brain-demo/DEMO_CLIPS.md).

### Code geography

```
models/                      what the browser loads
  vision_encoder.fp16.onnx   MobileCLIP-S1, 4 fps frames -> 512-d
  audio_encoder.*.onnx       EfficientAT mn10_as, 1 s / 32 kHz log-mel -> 960-d
  student_head.*.onnx        last 3 windows x 2496-d features -> 148 parcels + 6 ROIs
  stress_readout.json        logistic readout on running mean/max of the 6 ROIs
  README.md                  the web contract: inputs, preprocessing, shapes, parity checks
  pytorch/student_head.pt    head weights for further training
pipeline/                    how the model was made (runs on RunPod, volume at /workspace)
  bootstrap.sh               pod entrypoint: timeout + self-stop trap
  run.sh                     installs, then runs each stage by ROLE (A = prep, B = train)
  common.py                  paths, claim files, progress JSON, Destrieux atlas and ROIs
  prep_data.py               TikHarm -> 10 s clips + manifest
  xd_prep.py                 XD-Violence onset / calm / normal windows (written, not run yet)
  dl_models.py               model downloads with Llama sha256 check
  transcribe.py              WhisperX worker -> TRIBE-format word TSVs
  teacher.py                 TRIBE v2 inference, 3 workers per GPU -> parcels / ROIs per second
  encoders.py                student encoders and exact preprocessing
  student_features.py        per-clip vision and audio embeddings
  train_export.py            train head, fit stress readout, eval, ablations, ONNX export, demo traces
  data/manifest.csv          every clip: split, label, source
  ops/                       laptop-side S3 polling scripts (need your own secrets file)
  run-logs/                  progress snapshots from the final run
brain-demo/
  live_demo.html             open in a browser: video on the left, live per-second numbers on the right
  demo/                      60 held-out clips (mp4 plus per-second student and teacher JSON)
docs/
  CALM_MODEL_REPORT.md       metrics, ablations, label caveats
  TRIBE_DISTILL_HANDOFF.md   the original task brief and spending rules
```

TRIBE v2 weights are CC BY-NC 4.0, so the distilled Calm model is non-commercial too.

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

The X-style stage is at `chrome-extension://<extension-id>/preview-x.html?platform=x` (linked from the TikTok stage header). It uses the same content script with the X DOM adapter, so the post text, `@handle` and `/status/<id>` become the video identity. It is a controlled timeline, not X content. Use the two-icon **TikTok / X switch** in the stage header to jump between the interfaces.

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
- **Half-screen session**: the Session view is a 2×2 grid of Calm / Learn / Shield / Rules. The Calm card replaces the brain sketch with four lit lobe tiles (Frontal, Parietal, Temporal, Occipital) plus Limbic / Cerebellum chips. At 756×806 the four cards fit without scrolling.
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
