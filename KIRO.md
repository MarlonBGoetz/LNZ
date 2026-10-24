# How we used Kiro

This project was built in one long session with **Kiro CLI** (terminal agent, `kiro_default` agent, Claude Opus model), working against a live Chrome tab. This page is an honest account: what we used, what made a difference, and what we did not use.

## Tools

| Kiro surface | Used? | How |
|---|---|---|
| **Kiro CLI** | Yes, for everything | Chat-driven development in the repo, shell + file tools, AppleScript bridge into Chrome for live measurements. |
| Kiro IDE / Web / Crew | No | We stayed in the terminal. |

CLI features that carried the work:

- **Task lists** (`todo_list`): every multi-step change started as a task list (e.g. "parser + tests", "pre-emptive skip", "TRIBE integration"), checked off as it was verified, with context notes that survived conversation compaction.
- **Subagents** (`subagent`): an independent read-only reviewer audited the skip-mode rewrite. It found a real HIGH bug (an id-less video under failOpen stayed paused forever because the hold timer was set to `Infinity`), which we fixed before the live test.
- **Introspect**: used to check Kiro's own docs (hooks, agent config, steering) before building `.kiro/`, instead of guessing formats.
- **Code intelligence / web**: not needed; the codebase stayed small.

## Our process (and how it compared to vibe coding)

We did not use Kiro's formal spec files. We did use a spec-like discipline that Kiro enforced through steering and checkpoints:

1. **Requirements first.** The original brief became an agreed scope in chat ("what I understand in 5–10 sentences"), then was revised as the user's goal sharpened: from "auto-skip" to "invisible filtering" to "drop mode", and from metadata to video + audio once the teammate's model arrived.
2. **Ground truth before code (Step 0).** Kiro measured the real site before writing the parser: endpoint, batch size, field gaps, then media lookahead (1–2 videos), lead time (5–18 s) and whether frames are readable. All of it is recorded in `FINDINGS.md`. Several assumptions turned out wrong (e.g. the first batch is embedded HTML, not a request; audio for long videos is a separate partial file), and catching them early avoided rework.
3. **Small verified milestones.** Each step ended with typecheck + tests + a live check on tiktok.com, and a short summary.

Compared to vibe coding, the difference showed up in the bugs we caught before they shipped:

- The first live run of the TRIBE model skipped almost everything (37 skips, 36 timeouts). Measuring instead of guessing showed three separate causes: WebGPU sessions can't be created in parallel, Chrome doesn't load video in hidden tabs, and clips were queued in download order instead of feed order. Each got a targeted fix (sequential sessions, visibility wait, current-first scheduler, watchdog).
- An "invisible skip" rewrite was reverted in seconds when the user changed direction, because a baseline copy was taken first.

## Steering

`.kiro/steering/`:

| File | Purpose |
|---|---|
| `working-style.md` | The user's rules (from their global `~/.kiro/steering/preferences.md`): don't assume, state the senior-engineer trade-off before key decisions, short comments, no duplication (strategy + DI), milestone summaries, no attribution in commits. |
| `product.md` | Hard constraints: passive only, no TikTok requests or signing, local only, no fixed JSON paths, sanitize fixtures. |
| `architecture.md` | Where things live and which interfaces to extend. |
| `testing.md` | Commands, what must pass for each kind of change, "verify live before done". |
| `tribe-model.md` | Model contract summary (`inclusion: manual`, loaded only when working on the model). |

What made the biggest difference: the **"don't assume, surface trade-offs"** rule. It made Kiro stop and ask at the right moments (drop vs skip, failOpen vs failClosed, JS vs TypeScript, whether to commit fixtures) and explain why each choice matters. That kept a fast-moving, changing brief from turning into rework. The "no attribution" rule is also enforced by a hook (below).

## Agent hooks

`.kiro/agents/lnz-dev.json` is a project agent (start it with `kiro-cli chat --agent lnz-dev`). It loads the steering docs, `FINDINGS.md` and `README.md`, and wires four hooks in `.kiro/hooks/`:

| Trigger | Script | Why |
|---|---|---|
| `agentSpawn` | `session-context.sh` | Puts git status, branch and whether the model export / node_modules exist into context at the start. |
| `preToolUse` (shell) | `guard-shell.sh` | Blocks (exit 2) commands that hurt us or would break project rules: `vitest --root /` (a real mistake in this session that ran unrelated test files on the machine), recursive deletes of `/` or `~`, force push, `reset --hard`, any `curl`/`wget` to tiktok.com (passive-only rule), `Co-Authored-By` in commits. |
| `postToolUse` (write) | `check-fixtures.sh` | After any write under `fixtures/`, fails loudly if a signed URL survived sanitizing (privacy). |
| `stop` | `verify.sh` | After each turn that changed `src/`, `test/`, `static/` or `scripts/`, runs typecheck + the full test suite and reports `Tests N passed`, or shows the failure. |

Honest timing: the hooks and project agent were added at the end of the session, based on the failures and rules that came up during it. Each script was exercised with sample events (blocked/allowed commands, a deliberately leaked fixture) before committing.

## Property-based testing

`test/properties.test.ts` (fast-check) covers requirements where unit tests only check a few hand-picked cases:

- **Parser never throws on untrusted JSON** (any `jsonValue`, 500 runs), and every video object is found at any nesting depth (requirement: "walk the JSON, don't hard-code paths").
- **Arbitrary field types** never break normalization, and stats are always finite or null.
- **Drop filter:** removes exactly the blocked ids, keeps order, never returns an empty batch.
- **Media reassembly:** any chunking of a file, in any arrival order, reassembles to the same bytes.
- **Stress readout:** one probability per second, and it is causal (future seconds never change past scores). `isStressful(max)` is monotonic.

Result: all properties passed on first run, so PBT did not find a new bug here. The unit and live tests had already caught the issues in these modules. Its value is as a guard: these invariants now hold for thousands of generated inputs, not just the fixtures.

## Not used

- **MCP servers:** none. Browser access went through AppleScript + `osascript` from the shell, which covered what we needed (run JS in the TikTok tab, read DOM state) without an MCP server.
- **Kiro powers:** none.
- **Formal spec files:** none (see "Our process").
