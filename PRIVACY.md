# Private build and local data

LNZ is currently a **private, local build**, not a public browser add-on.

## How it stays private

- The extension is loaded as an **unpacked extension** from `extension/dist` in your own Chrome profile.
- It is **not published** to the Chrome Web Store. Do not upload this folder to a public store or make the repository public.
- The GitHub repository is private. Do not share the folder, a packed `.crx`, or your Chrome profile with anyone you do not want to have the code.
- `host_permissions` are limited to the supported sites plus the local relay:
  `https://www.tiktok.com/*`, `https://x.com/*`, `https://twitter.com/*`, `http://localhost:*/*`, `http://127.0.0.1:*/*`.
  There is no `<all_urls>`, no external analytics endpoint, and no cloud classifier call.
- The stage pages and overlay live inside the extension. The manifest has no `web_accessible_resources`, so ordinary websites cannot load your extension pages.
- The local dashboard binds to `127.0.0.1:5174` only. Do **not** port-forward it to a public interface or expose it through a tunnel.
- The day log is written to `analytics/.data/events-YYYY-MM-DD.jsonl` and is gitignored. It contains watched titles/authors and local classifications. Delete it to reset the day.

## Honest limit

A browser extension is client-side software. Anyone with access to the unpacked folder or your Chrome profile can read the source. "Private" here means **private distribution** — a private repo and a local load — not DRM or secrecy from someone with filesystem access.

For a private Web Store listing you would need a Google Workspace publisher and trusted testers. That is not configured here. Keep the demo local, or ship a separate demo build that does not include the production profile or private data.

## What to share for a demo

Share screenshots, the `preview.html` / `preview-x.html` stage, or a separate demo build. Do not share:

- your Chrome profile directory (e.g. `.chrome-lnz-final`),
- `analytics/.data/`,
- the private repository or a packed extension if the idea must stay private.

The extension's PIN is self-control friction for configuration changes. It is not a security boundary against someone who can modify or remove the extension.
