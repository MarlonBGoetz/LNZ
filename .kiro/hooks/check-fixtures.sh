#!/bin/bash
# postToolUse(write): if a fixture was written, fail loudly when it still has signed URLs (must be sanitized).
event=$(cat)
case "$event" in *fixtures/*) ;; *) exit 0 ;; esac
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)" || exit 0
bad=""
for f in fixtures/*.json; do
  n=$(grep -oE '"https?://[^"]*"' "$f" | grep -vc 'redacted\.invalid')
  [ "$n" -gt 0 ] && bad="$bad $f($n)"
done
if [ -n "$bad" ]; then
  echo "Fixture privacy check failed, unredacted URLs in:$bad. Run: npm run sanitize -- <file>" >&2
  exit 1
fi
exit 0
