#!/bin/bash
# stop: after each agent turn that touched code, typecheck + test; report a one-line summary, warn on failure.
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)" || exit 0
stamp=node_modules/.lnz-last-verify
changed=$(find src test static scripts -newer "$stamp" -type f 2>/dev/null | head -1)
[ -f "$stamp" ] && [ -z "$changed" ] && exit 0
touch "$stamp"
if ! out=$(npm run -s typecheck 2>&1); then echo "typecheck failed:" >&2; echo "$out" | head -20 >&2; exit 1; fi
if ! out=$(npx vitest run --reporter=dot 2>&1); then echo "tests failed:" >&2; echo "$out" | tail -25 >&2; exit 1; fi
echo "$out" | grep -E "Tests" | head -1
