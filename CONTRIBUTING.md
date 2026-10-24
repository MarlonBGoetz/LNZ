# Proposing changes to LNZ

Marlon (@MarlonBGoetz) decides which changes enter this repository. Contributors
submit proposals; Marlon reviews the final diff and applies accepted changes.

## Contributor workflow

1. Use your own GitHub account and create a private fork of this repository.
2. Make changes on a branch in your fork. Push to your fork, not to
   `MarlonBGoetz/LNZ`.
3. Open a pull request into the intended integration branch in
   `MarlonBGoetz/LNZ`. Check the target: the repository's current default may
   differ from `main`.
4. Explain the problem, the resulting behavior, and what you actually tested.
   For application changes, run the relevant tests; the existing commands are
   `npm run typecheck`, `npm test`, and `npm run build`.
5. Wait for Marlon to review and merge. If you change the proposal after review,
   ask for another review of the new diff.

Do not merge pull requests, enable auto-merge, or create, update, delete, or
force-push branches or tags in the original repository.

## Coding agents

Prepare changes and present a pull request for Marlon's decision. Do not treat
permission to implement a feature as permission to merge it or push it directly
to an integration branch. An explicit instruction from Marlon to perform that
specific action takes precedence.

Use your own contributor identity where possible. An agent authenticated as
`MarlonBGoetz` has the owner's authority; GitHub cannot distinguish its actions
from Marlon's. Such an agent must stop at the proposed change unless Marlon
explicitly authorizes applying it.

## Enforcement status

This workflow is a policy until the GitHub rulesets are activated. Committing
`.github/CODEOWNERS` or the JSON definitions does not activate repository rules.
See [Owner approval setup](docs/OWNER_APPROVAL.md) for the exact activation,
verification, plan requirement, and remaining permission limits.
