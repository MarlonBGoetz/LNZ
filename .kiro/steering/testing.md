# Testing and verification

- Commands (run from the repo root only): `npm run typecheck`, `npm test`, `npm run build`.
- Never run vitest with `--root /` or outside the project. It once picked up unrelated test files on this machine.
- Parser changes: tests must pass on every file in `fixtures/` and on missing/wrong-typed fields.
- Pure logic gets property-based tests (`test/properties.test.ts`, fast-check): parser never throws, drop filter invariants, media reassembly, causal stress readout.
- TRIBE model changes: `test/tribe.test.ts` must still match all 60 demo traces; then run `dist/selftest.html` in Chrome (tab visible) and keep mean abs error ≤ 0.05.
- Browser behavior is verified live on tiktok.com with the debug overlay before calling a feature done. Unit tests alone are not proof for DOM/video behavior.
