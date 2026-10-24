# Architecture

```
MAIN world (injected)     content script (bridge)          extension pages
src/injected/             src/bridge/                      src/model-host/  (hidden iframe on tiktok.com)
 fetch/XHR wrapper  ──▶    parser → FeedStore               TRIBE ONNX models (WebGPU → WASM)
 media stream tee   ──▶    MediaStore → classifier ──port──▶ decode → log-mel → encoders → head → readout
 drop (holds batch) ◀──    VerdictCache, skip, auto-scroll  src/background/ (config, HTTP proxy)
 play() guard              overlay (shadow DOM)             src/popup/
```

- One message protocol: `src/shared/messages.ts` (page ↔ bridge, `LNZ_` prefix, same-origin only). Model host uses a private `MessageChannel` (`src/shared/model-host.ts`).
- Classifiers implement `Classifier` (`src/classifier/types.ts`) and are created only in `src/classifier/registry.ts`. `needs: "metadata"` classifiers can drop; `needs: "media"` classifiers can only skip.
- Platform specifics live under `src/platforms/tiktok/` (config, parser, media URL mapping, drop filter).
- Verdicts are final once set and cached by video id.
- Media classifiers run one clip at a time, current video first (`pumpMedia` in the bridge).

Patterns: strategy (classifiers, advance adapters), dependency injection (HTTP transport, `StressModel`, `TribeRunner`). Don't add a second way to do something that already has an interface.
