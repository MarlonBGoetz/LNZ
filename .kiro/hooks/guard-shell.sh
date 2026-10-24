#!/bin/bash
# preToolUse(shell): block commands that broke or could break this project/machine. Exit 2 = block.
cmd=$(node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{try{process.stdout.write(JSON.parse(s).tool_input?.command??"")}catch{}})')

deny() { echo "Blocked by .kiro/hooks/guard-shell.sh: $1" >&2; exit 2; }

[[ "$cmd" =~ vitest.*--root[[:space:]]+/([[:space:]]|$) ]] && deny "vitest must run inside the repo (it picked up unrelated tests from / before)."
[[ "$cmd" =~ rm[[:space:]]+-[a-zA-Z]*r[a-zA-Z]*f?[[:space:]]+(/|~|\$HOME)([[:space:]]|$) ]] && deny "recursive delete of a root/home path."
[[ "$cmd" =~ git[[:space:]]+push.*(--force|-f([[:space:]]|$)) ]] && deny "force push needs explicit user approval."
[[ "$cmd" =~ git[[:space:]]+reset[[:space:]]+--hard ]] && deny "git reset --hard needs explicit user approval."
[[ "$cmd" =~ (curl|wget).*tiktok\.com ]] && deny "the project is passive-only: no requests to tiktok.com."
[[ "$cmd" =~ Co-Authored-By ]] && deny "no attribution markers in commits (steering/working-style.md)."
exit 0
