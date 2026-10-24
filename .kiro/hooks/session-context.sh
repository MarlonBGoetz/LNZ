#!/bin/bash
# agentSpawn: give the agent the repo state and the test status up front (stdout is added to context).
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)" || exit 0
echo "## Repo state"
git status --short 2>/dev/null | head -20
echo "branch: $(git branch --show-current 2>/dev/null)"
[ -d model/tribe_student_export ] && echo "TRIBE model export: present" || echo "TRIBE model export: MISSING (see README > Model files)"
[ -d node_modules ] || echo "node_modules missing: run npm install"
