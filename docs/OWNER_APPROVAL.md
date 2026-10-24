# Owner approval for LNZ

## Status when this change was prepared

On 24 October 2026, the GitHub API reported five unprotected branches in the
private personal repository `MarlonBGoetz/LNZ`. Its default branch was
`feature/lnz-overlay-ui`; `main` pointed to an empty initial commit. The ruleset
endpoint returned HTTP 403 requiring GitHub Pro.

**These files prepare protection; they do not activate it.** Merging this pull
request alone does not block collaborators. Repository settings are the source
of truth for current enforcement.

## Intended behavior after activation

- Collaborators work in private forks and open pull requests.
- Only the repository administrator can create, update, or delete branches and
  tags in the original repository, including merging a pull request.
- Every branch and tag is covered, including future names containing slashes.
- The branch rules also require a pull request, one approval, and code-owner
  review; new reviewable commits dismiss previous approvals.
- `.github/CODEOWNERS` assigns every path to `@MarlonBGoetz`.
- The administrator retains an explicit bypass. In this personal repository,
  that is the owner. Do not add Write, Maintain, apps, or deploy keys to bypass.

The administrator's bypass is deliberate: GitHub does not let a PR author
approve their own PR. Marlon can review the diff and merge an owner-authored PR
using his administrator permission. This configuration enforces owner control,
not a mandatory second-person approval of Marlon's own work.

## Activate in GitHub

Private personal repositories require GitHub Pro for these rulesets. This setup
does not purchase a plan, change repository visibility, or transfer ownership.

After a supported plan is available:

1. Review and merge the setup files into the relevant PR base branch. CODEOWNERS
   review routing uses the file on the base branch. Apply that file to any other
   integration branch that should request Marlon's review.
2. Open [LNZ ruleset settings](https://github.com/MarlonBGoetz/LNZ/settings/rules).
3. Import `.github/rulesets/owner-approval-branches.json` and
   `.github/rulesets/owner-approval-tags.json` as repository rulesets. If using
   the manual form instead, reproduce the table below.
4. Verify both rulesets show **Active**, cover all branches/tags, and have only
   **Repository admin / Always allow** in the bypass list.
5. Keep private forking available so collaborators can submit changes from
   their own forks.

| Setting | Branch ruleset | Tag ruleset |
| --- | --- | --- |
| Name | Owner approval - all branches | Owner approval - all tags |
| Enforcement | Active | Active |
| Target | All branches | All tags |
| Exclusions | None | None |
| Restrict creations | On | On |
| Restrict updates | On | On |
| Restrict deletions | On | On |
| Require pull request | On | Not applicable |
| Required approvals | 1 | Not applicable |
| Require code-owner review | On | Not applicable |
| Dismiss stale approvals | On | Not applicable |
| Bypass | Repository admin only, Always allow | Repository admin only, Always allow |

The JSON uses `~ALL`, not `*`, because a single `*` does not cover slash-separated
branch names in GitHub ruleset patterns. Repository-role ID `5` is administrator;
it is not a GitHub user ID.

### Alternative: create through GitHub CLI

Run only from a trusted owner session after reviewing the JSON. Confirm
`gh api user --jq .login` returns `MarlonBGoetz`. The authentication must include
repository Administration write permission.

First inspect existing settings:

```bash
gh api repos/MarlonBGoetz/LNZ/rulesets --paginate
```

If that returns the plan error, stop. If either named ruleset already exists,
inspect and update that existing rule in GitHub instead of creating duplicates.
Otherwise, from a checkout containing these files:

```bash
gh api --method POST repos/MarlonBGoetz/LNZ/rulesets \
  --input .github/rulesets/owner-approval-branches.json
gh api --method POST repos/MarlonBGoetz/LNZ/rulesets \
  --input .github/rulesets/owner-approval-tags.json
```

These commands activate source-write restrictions immediately. They do not
merge any application pull requests or change the default branch.

## Verify the saved settings

Read each saved ruleset by its returned ID:

```bash
gh api repos/MarlonBGoetz/LNZ/rulesets/RULESET_ID
```

Check both full responses against the table: active enforcement, the correct
target, no exclusions, all three write restrictions, and exactly one bypass
actor (`RepositoryRole`, ID `5`, mode `always`). Also check the branch review
requirements. Do not treat the local JSON's `active` value as evidence that
GitHub has enabled anything.

Check which active rules apply without creating a branch or commit:

```bash
gh api repos/MarlonBGoetz/LNZ/rules/branches/main
gh api repos/MarlonBGoetz/LNZ/rules/branches/feature%2Flnz-overlay-ui
gh api repos/MarlonBGoetz/LNZ/rules/branches/feature%2Fexample%2Fnested
```

Each response should include the creation, update, deletion, and pull-request
rules from the branch ruleset. This endpoint also accepts nonexistent branch
names, so the final command checks future nested names without altering code.

## Permission boundaries

- These rules protect source branches and tags. Personal-repository
  collaborators still have other write-level capabilities, such as issue and
  release management. For true read-only collaborator roles, use an
  organization-owned repository with contributors assigned Read.
- A token or agent operating as Marlon uses Marlon's administrator bypass.
  Contributors must use their own accounts. Do not place owner credentials in
  workflows contributors can run.
- CODEOWNERS is review routing, not file secrecy or an ownership agreement.
- The rules do not prevent reading, cloning, or retaining copies of source.
- Branch and tag rulesets do not propagate into personal forks. Push rulesets
  are different; they are not used here.
- No status checks or deployment requirements are added by this setup.

## References

- [Creating repository rulesets and plan availability](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository)
- [Creation, update, deletion, and pull-request rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)
- [Rules REST API](https://docs.github.com/en/rest/repos/rules)
- [CODEOWNERS behavior](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners)
- [Personal repository permissions](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/repository-access-and-collaboration/permission-levels-for-a-personal-account-repository)
- [Fork inheritance of rulesets](https://docs.github.com/en/organizations/managing-organization-settings/creating-rulesets-for-repositories-in-your-organization)
- [Repository role IDs in GitHub's Terraform provider](https://github.com/integrations/terraform-provider-github/blob/main/docs/resources/organization_ruleset.md)
