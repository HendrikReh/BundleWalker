# Dependabot Maintenance Cycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Review, repair, and merge BundleWalker's live Dependabot queue while keeping every merged `master` state green and preserving per-update provenance.

**Architecture:** Use a sequential, dependency-aware maintenance pipeline. Independently green pull requests are verified and merged one at a time; supported-check failures are diagnosed from exact GitHub Actions logs and repaired on focused maintainer branches; coupled CodeQL actions move together only after the coupling hypothesis is proven. Every remote mutation is guarded by an unchanged-head check, required hosted checks, local verification, and a post-merge `master` gate.

**Tech Stack:** Git and Git worktrees, GitHub CLI and GitHub Actions, Python 3.13/3.14, uv, pytest, Ruff, Pyright, Hatch/uv builds, Twine, pip-audit, Node 22.22.3, npm, React/Vite/Vitest/Playwright, immutable SHA-pinned GitHub Actions.

## Global Constraints

- The accepted design is `docs/superpowers/specs/2026-08-08-dependabot-maintenance-cycle-design.md`.
- Refresh the live queue before acting; PR numbers and design-time SHAs are evidence to compare, not permission to use stale checks.
- Do not add product features, change BundleWalker's public behavior, or perform unrelated refactoring.
- Do not expand Windows support; its jobs remain visible, experimental, and non-blocking.
- Never weaken required CI, CodeQL, dependency audit, release protection, or SHA-pinning policy.
- Never force-push or merge a branch with a supported-platform, aggregate `Required`, or applicable CodeQL failure.
- Merge only the exact reviewed head SHA with `gh pr merge --match-head-commit`.
- Use the repository-standard merge-commit strategy, not squash or rebase merge.
- After each merge, verify both CI and CodeQL on the resulting `master` commit before processing the next PR.
- Preserve immutable release history in `CHANGELOG.md`, `docs/maintainers/evidence/`, and the historical assertions in `tests/test_release_metadata.py`.
- Live model-quality evaluation is excluded; do not run `pytest -m eval` or provider-backed commands.
- If a correction changes product behavior, support policy, release policy, or this plan's scope, stop for a new user decision.
- Resolve the main checkout with `MAIN_ROOT=$(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)` before every worktree operation; create all temporary verification worktrees below `$MAIN_ROOT/.worktrees/`, never below a linked execution worktree.
- Remove temporary worktrees and their local branches after their PR is merged, closed, or deferred.
- Record task evidence in ignored `.superpowers/sdd/dependabot-maintenance-ledger.md`; do not commit transient logs or credentials.

## File and Responsibility Map

- `.superpowers/sdd/dependabot-maintenance-ledger.md`
  - Ignored execution ledger containing the live queue, exact head SHAs, causal failures, local gates,
    merge commits, hosted-run URLs, deferrals, and cleanup state.
- `.github/workflows/benchmarks.yml`
  - SHA-pinned checkout and uv setup used by scheduled/manual benchmark evidence.
- `.github/workflows/ci.yml`
  - Supported Python matrix, experimental Windows jobs, frontend/browser checks, build, audit,
    artifact smokes, and aggregate `Required` gate.
- `.github/workflows/codeql.yml`
  - SHA-pinned checkout plus version-coupled CodeQL `init` and `analyze` actions.
- `.github/workflows/publish-pypi.yml`
  - Production release build, OIDC publisher, verification, and GitHub release boundaries.
- `.github/workflows/publish-testpypi.yml`
  - Manual TestPyPI build, OIDC publisher, and bounded verification.
- `.github/workflows/rehearse-production-lifecycle.yml`
  - Production lifecycle rehearsal action pins.
- `pyproject.toml`
  - Direct runtime/development dependency ranges; only Twine's approved `<8` range is expected from
    the design-time queue.
- `uv.lock`
  - Exact resolved Python graph changed independently by Uvicorn, PydanticAI, Ruff, Twine, and
    Cryptography PRs; refresh remaining PRs after every lock merge.
- `tests/test_project_automation.py`
  - Active workflow structure, SHA pinning, publisher action approval, CI sequencing, and release
    automation contracts.
- `tests/test_release_metadata.py`
  - Current dependency-floor policy plus immutable tagged release-history assertions; historical
    `0.4.0rc3` versions must not be rewritten.
- `tests/interfaces/web/test_server.py` and `tests/interfaces/web/`
  - Uvicorn integration and local-web compatibility coverage.
- `tests/agents/`, `tests/application/`, `tests/workflows/`, and `tests/interfaces/`
  - Provider-independent PydanticAI and adapter integration coverage.
- `frontend/` and `src/bundlewalker/interfaces/web/static/`
  - Locked browser graph, reproducible contracts, and generated packaged assets used by the hosted
    frontend/browser gate.

---

### Task 1: Capture the live queue and execution baseline

**Files:**
- Create: `.superpowers/sdd/dependabot-maintenance-ledger.md` (ignored execution evidence)
- Read: `docs/superpowers/specs/2026-08-08-dependabot-maintenance-cycle-design.md`
- Read: `.github/workflows/ci.yml`
- Read: `.github/workflows/codeql.yml`

**Interfaces:**
- Consumes: Clean planning branch containing design commit `2f1cc36` and this implementation plan.
- Produces: A ledger row for every live Dependabot PR with `number`, `title`, `head_sha`,
  `head_branch`, `changed_files`, `mergeable`, `required_checks`, `all_failures`, and
  `classification`; all later tasks consume the current row rather than the design-time SHA.

- [ ] **Step 1: Verify authentication and repository identity**

Run:

```bash
gh auth status
git remote get-url origin
git status --short --branch
```

Expected: GitHub authentication succeeds, `origin` is `HendrikReh/BundleWalker`, and the planning
branch is clean.

- [ ] **Step 2: Refresh Git and GitHub state**

Run:

```bash
git fetch --prune origin
gh pr list --state open --author 'app/dependabot' --limit 100 \
  --json number,title,headRefName,headRefOid,mergeable,files,statusCheckRollup,url
```

Expected: The returned list becomes the authoritative execution-start queue. Record new,
superseded, merged, or closed PRs instead of assuming the design-time count remains ten.

- [ ] **Step 3: Verify the base branch**

Run:

```bash
git rev-parse master
git rev-parse origin/master
git log -1 --oneline origin/master
gh api repos/HendrikReh/BundleWalker/branches/master/protection
gh api 'repos/HendrikReh/BundleWalker/rulesets?includes_parents=true'
```

Expected: local and remote `master` match. If they differ, update local `master` with an
explicit fast-forward before creating any verification worktree. Record the required checks,
allowed merge method, and any ruleset that applies to `master`; do not infer protection solely from
the workflow files.

- [ ] **Step 4: Create the ignored ledger**

Use `date -u +%Y-%m-%dT%H:%M:%SZ` and `git rev-parse origin/master` to obtain the execution-start
timestamp and base SHA. Create `.superpowers/sdd/dependabot-maintenance-ledger.md` with `apply_patch`;
paste those two command outputs directly into the metadata lines and include this exact section/table
structure:

```markdown
# Dependabot Maintenance Ledger

Execution start
Base master

| PR | Head SHA | Files | Required checks | Other failures | Classification | Outcome |
| --- | --- | --- | --- | --- | --- | --- |

## Root-cause evidence

## Merge and master-gate evidence

## Deferred or superseded updates

## Final cleanup
```

The two metadata headings must have their command output on the same line. Do not leave either
metadata value blank.

- [ ] **Step 5: Classify the queue**

Use these exact rules:

```text
independent-green: all required checks pass; failures are experimental Windows only
diagnostic: any supported, frontend/browser, build, audit, artifact, Required, or CodeQL failure
coupled-candidate: separate PRs change complementary components to one identical release/SHA
superseded: a newer PR replaces the same dependency and target range
already-resolved: merged or closed before execution began
```

Expected: Every execution-start PR has exactly one primary classification and no unexplained
failure.

- [ ] **Step 6: Review Task 1 evidence**

Run:

```bash
git check-ignore -v .superpowers/sdd/dependabot-maintenance-ledger.md
git status --short --branch
```

Expected: the ledger is ignored, no tracked file changed, and the task requires no commit.

---

### Task 2: Verify and merge `actions/checkout` PR #26 when still current

**Files:**
- Verify: `.github/workflows/benchmarks.yml`
- Verify: `.github/workflows/ci.yml`
- Verify: `.github/workflows/codeql.yml`
- Verify: `.github/workflows/publish-pypi.yml`
- Verify: `.github/workflows/publish-testpypi.yml`
- Verify: `.github/workflows/rehearse-production-lifecycle.yml`
- Test: `tests/test_project_automation.py`
- Update evidence: `.superpowers/sdd/dependabot-maintenance-ledger.md`

**Interfaces:**
- Consumes: Task 1 ledger row for PR #26. Design-time head was
  `2809109d98611c1656d4f788fbdbcff25da928bc`; design-time target pin was
  `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1`.
- Produces: merged PR #26 or an evidence-backed reclassification; refreshed `master` and queue.

- [ ] **Step 1: Confirm head and scope**

Run:

```bash
gh pr view 26 --json state,headRefOid,mergeable,files,statusCheckRollup,url
gh pr diff 26 --name-only
gh pr diff 26 --patch
```

Expected: only the six workflow files listed above change, every checkout occurrence moves to one
40-character SHA, `persist-credentials: false` remains present, and no permission or trigger changes.
If the PR is no longer open, record its current outcome and end this task without mutation.

- [ ] **Step 2: Verify official update evidence**

Review the official checkout release notes/changelog linked in PR #26. Confirm that `v7.0.1` is a
patch update and that the immutable SHA in the live patch belongs to that release. Record the URL
and conclusion in the ledger.

- [ ] **Step 3: Create an exact-head detached worktree**

Run:

```bash
MAIN_ROOT=$(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)
WT="$MAIN_ROOT/.worktrees/dependabot-pr-26"
git -C "$MAIN_ROOT" fetch origin pull/26/head
git -C "$MAIN_ROOT" worktree add --detach "$WT" FETCH_HEAD
git -C "$WT" rev-parse HEAD
```

Expected: the worktree SHA exactly equals the Task 1 ledger SHA.

- [ ] **Step 4: Run focused and complete local checks**

Run from `$WT`:

```bash
cd "$WT"
uv sync --locked
uv run pytest tests/test_project_automation.py -q
uv lock --check
uv run pytest -m 'not eval' -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
git diff --check
git status --short --branch
cd "$MAIN_ROOT"
```

Expected: all commands pass and the detached worktree remains clean.

- [ ] **Step 5: Revalidate hosted gates at the unchanged head**

Run:

```bash
gh pr checks 26 --required
gh pr view 26 --json headRefOid,mergeable --jq '[.headRefOid,.mergeable] | @tsv'
```

Expected: required checks pass, mergeability is `MERGEABLE`, and the head still equals the ledger
SHA. Experimental Windows failures may remain visible but cannot appear in the required set.

- [ ] **Step 6: Merge and verify `master`**

Compare the live head with the commit tested in `$WT`, then merge that exact commit:

```bash
TESTED_SHA=$(git -C "$WT" rev-parse HEAD)
HEAD_SHA=$(gh pr view 26 --json headRefOid --jq '.headRefOid')
test "$HEAD_SHA" = "$TESTED_SHA"
gh pr merge 26 --merge --delete-branch --match-head-commit "$TESTED_SHA"
gh pr view 26 --json state,mergedAt,mergeCommit,url
```

Fetch `master`, then resolve the merge and run IDs directly from GitHub:

```bash
git fetch origin master
MERGE_SHA=$(gh pr view 26 --json mergeCommit --jq '.mergeCommit.oid')
CI_RUN_ID=$(gh run list --commit "$MERGE_SHA" --workflow CI --event push --limit 5 \
  --json databaseId --jq '.[0].databaseId')
CODEQL_RUN_ID=$(gh run list --commit "$MERGE_SHA" --workflow CodeQL --event push --limit 5 \
  --json databaseId --jq '.[0].databaseId')
test -n "$CI_RUN_ID"
test -n "$CODEQL_RUN_ID"
gh run watch "$CI_RUN_ID" --exit-status
gh run watch "$CODEQL_RUN_ID" --exit-status
```

Replace the three runtime identifiers from `gh pr view` and `gh run list`; do not reuse an older
run. Expected: both exact-merge runs succeed.

- [ ] **Step 7: Clean up and refresh**

Run:

```bash
git -C "$MAIN_ROOT" worktree remove "$WT"
git -C "$MAIN_ROOT" worktree prune
git fetch --prune origin
gh pr list --state open --author 'app/dependabot' --limit 100
```

Record the merge SHA, run URLs, and refreshed queue in the ledger. No local code commit is created
for this task; the reviewed GitHub merge commit is the deliverable.

---

### Task 3: Verify and merge `setup-uv` PR #27 when still current

**Files:**
- Verify: `.github/workflows/benchmarks.yml`
- Verify: `.github/workflows/ci.yml`
- Verify: `.github/workflows/publish-pypi.yml`
- Verify: `.github/workflows/publish-testpypi.yml`
- Verify: `.github/workflows/rehearse-production-lifecycle.yml`
- Test: `tests/test_project_automation.py`
- Update evidence: `.superpowers/sdd/dependabot-maintenance-ledger.md`

**Interfaces:**
- Consumes: refreshed Task 1 ledger row for PR #27 and post-Task-2 `master`. Design-time head was
  `5e5ff25a3c3e60992e2dab0fb237895bba93690e`; target pin was
  `astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9 # v9.0.0`.
- Produces: merged PR #27 or evidence-backed deferral; refreshed master gate and queue.

- [ ] **Step 1: Refresh the PR before using its old checks**

Run:

```bash
gh pr view 27 --json state,headRefOid,mergeable,files,statusCheckRollup,url
gh pr diff 27 --patch
```

Expected: only setup-uv pins change; `UV_VERSION: "0.11.28"`, Python matrices, cache suffixes,
workflow permissions, and release gates remain unchanged. If lock/workflow merges made the branch
stale, request a Dependabot rebase and wait for a new head/check set before proceeding.

- [ ] **Step 2: Review the official major-version evidence**

Read the official setup-uv `v9.0.0` release notes and compare link from PR #27. Record breaking
changes and confirm that BundleWalker supplies every required input explicitly.

- [ ] **Step 3: Verify the exact head locally**

Run:

```bash
MAIN_ROOT=$(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)
WT="$MAIN_ROOT/.worktrees/dependabot-pr-27"
git -C "$MAIN_ROOT" fetch origin pull/27/head
git -C "$MAIN_ROOT" worktree add --detach "$WT" FETCH_HEAD
cd "$WT"
uv sync --locked
uv run pytest tests/test_project_automation.py -q
uv lock --check
uv run pytest -m 'not eval' -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
git diff --check
git status --short --branch
cd "$MAIN_ROOT"
```

Expected: all local checks pass and the worktree is clean.

- [ ] **Step 4: Require current hosted checks and merge**

Run:

```bash
gh pr checks 27 --required
TESTED_SHA=$(git -C "$WT" rev-parse HEAD)
HEAD_SHA=$(gh pr view 27 --json headRefOid --jq '.headRefOid')
test "$HEAD_SHA" = "$TESTED_SHA"
test "$(gh pr view 27 --json mergeable --jq '.mergeable')" = "MERGEABLE"
gh pr merge 27 --merge --delete-branch --match-head-commit "$TESTED_SHA"
```

Expected: the tested head is still current and is merged only after all required checks pass.

- [ ] **Step 5: Verify merged `master`, clean up, and refresh**

Resolve and watch the CI and CodeQL push runs for the exact merge commit. After both succeed, clean
up the worktree:

```bash
git fetch origin master
MERGE_SHA=$(gh pr view 27 --json mergeCommit --jq '.mergeCommit.oid')
CI_RUN_ID=$(gh run list --commit "$MERGE_SHA" --workflow CI --event push --limit 5 \
  --json databaseId --jq '.[0].databaseId')
CODEQL_RUN_ID=$(gh run list --commit "$MERGE_SHA" --workflow CodeQL --event push --limit 5 \
  --json databaseId --jq '.[0].databaseId')
test -n "$CI_RUN_ID"
test -n "$CODEQL_RUN_ID"
gh run watch "$CI_RUN_ID" --exit-status
gh run watch "$CODEQL_RUN_ID" --exit-status
git -C "$MAIN_ROOT" worktree remove "$WT"
git -C "$MAIN_ROOT" worktree prune
git fetch --prune origin
```

Record release-note evidence, merge SHA, hosted run URLs, and the refreshed queue. No local commit
is created.

---

### Task 4: Verify and merge Uvicorn PR #33 when still current

**Files:**
- Verify: `uv.lock`
- Test: `tests/interfaces/web/test_server.py`
- Test: `tests/interfaces/web/`
- Update evidence: `.superpowers/sdd/dependabot-maintenance-ledger.md`

**Interfaces:**
- Consumes: current ledger row for PR #33. Design-time head was
  `d39c5e98195add93194101800cc3cbe1103e44af`; the patch changed only Uvicorn `0.51.0` to `0.52.0`
  in `uv.lock` while `pyproject.toml` retained `uvicorn>=0.51,<1`.
- Produces: merged Uvicorn lock update or a documented deferral; refreshed remaining lock PRs.

- [ ] **Step 1: Confirm the refreshed lock-only patch**

Run `gh pr view 33 --json state,headRefOid,files,statusCheckRollup` and `gh pr diff 33 --patch`.
Expected: only the Uvicorn package record and artifact hashes change. If another dependency changes,
classify the extra resolution before continuing.

- [ ] **Step 2: Review official Uvicorn compatibility notes**

Read the official `0.52.0` release notes/changelog linked by PR #33. Record any server lifecycle,
logging, ASGI, or Python-version changes relevant to `bundlewalker-web`.

- [ ] **Step 3: Run focused web-server checks at the exact head**

```bash
MAIN_ROOT=$(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)
WT="$MAIN_ROOT/.worktrees/dependabot-pr-33"
git -C "$MAIN_ROOT" fetch origin pull/33/head
git -C "$MAIN_ROOT" worktree add --detach "$WT" FETCH_HEAD
cd "$WT"
uv sync --locked
uv lock --check
uv run pytest tests/interfaces/web/test_server.py tests/interfaces/web/test_security.py -q
uv run pytest tests/interfaces/web -q
uv run bundlewalker-web --help
cd "$MAIN_ROOT"
```

Expected: all web adapter and startup/lifecycle contracts pass without modifying files.

- [ ] **Step 4: Run the complete offline gate**

Run from the PR worktree:

```bash
cd "$WT"
uv run pytest -m 'not eval' -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
git diff --check
git status --short --branch
cd "$MAIN_ROOT"
```

Expected: all commands pass and the worktree stays clean.

- [ ] **Step 5: Merge at the unchanged head and verify master**

Require `gh pr checks 33 --required`, then merge only the head read immediately before the command:

```bash
TESTED_SHA=$(git -C "$WT" rev-parse HEAD)
HEAD_SHA=$(gh pr view 33 --json headRefOid --jq '.headRefOid')
test "$HEAD_SHA" = "$TESTED_SHA"
gh pr merge 33 --merge --delete-branch --match-head-commit "$TESTED_SHA"
```

Watch CI and CodeQL for the returned merge commit. Both must succeed.

- [ ] **Step 6: Remove the worktree and refresh all lock PRs**

Remove `$WT` with `git -C "$MAIN_ROOT" worktree remove "$WT"`, prune worktrees, fetch/prune origin, and refresh PRs #34, #35,
#36, and #40. If any now conflicts or has a changed head, update its ledger row and discard its old
check evidence. No local commit is created.

---

### Task 5: Verify and merge PydanticAI PR #34 without live evaluation

**Files:**
- Verify: `uv.lock`
- Test: `tests/agents/`
- Test: `tests/application/`
- Test: `tests/workflows/`
- Test: `tests/interfaces/test_mcp_resources.py`
- Test: `tests/interfaces/test_mcp_tools.py`
- Test: `tests/interfaces/web/`
- Update evidence: `.superpowers/sdd/dependabot-maintenance-ledger.md`

**Interfaces:**
- Consumes: current ledger row for PR #34. Design-time head was
  `08667ac569fb9d9b0c8017eb73aae593d3388fa3`; the patch moved the PydanticAI family from `2.16.0`
  to `2.21.0` in `uv.lock` only.
- Produces: merged provider-independent model-library update or evidence-backed deferral; no live
  model call.

- [ ] **Step 1: Confirm family coherence and patch scope**

Inspect the refreshed PR patch. Expected: `pydantic-ai`, `pydantic-ai-slim`, `pydantic-evals`, and
`pydantic-graph` resolve coherently to `2.21.0`, with only their lock records and artifacts changed.

- [ ] **Step 2: Review official PydanticAI release notes**

Review official changes from `v2.16.0...v2.21.0`, focusing on `Agent`, structured output,
exceptions, MCP integration, model strings, retries, and eval APIs used by BundleWalker. Record each
relevant change and the existing test that covers it.

- [ ] **Step 3: Run focused provider-independent tests**

```bash
MAIN_ROOT=$(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)
WT="$MAIN_ROOT/.worktrees/dependabot-pr-34"
git -C "$MAIN_ROOT" fetch origin pull/34/head
git -C "$MAIN_ROOT" worktree add --detach "$WT" FETCH_HEAD
cd "$WT"
uv sync --locked
uv lock --check
uv run pytest tests/agents tests/application tests/workflows \
  tests/interfaces/test_mcp_resources.py tests/interfaces/test_mcp_tools.py \
  tests/interfaces/web -q
cd "$MAIN_ROOT"
```

Expected: all mocked/provider-independent integrations pass. Do not export provider credentials or
run `pytest -m eval`.

- [ ] **Step 4: Run the complete offline gate**

Run from `$WT`:

```bash
cd "$WT"
uv run pytest -m 'not eval' -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
git diff --check
git status --short --branch
cd "$MAIN_ROOT"
```

Expected: all pass with no generated changes.

- [ ] **Step 5: Merge and verify exact master gates**

Require current required checks, then merge only the head read immediately before the command:

```bash
TESTED_SHA=$(git -C "$WT" rev-parse HEAD)
HEAD_SHA=$(gh pr view 34 --json headRefOid --jq '.headRefOid')
test "$HEAD_SHA" = "$TESTED_SHA"
gh pr merge 34 --merge --delete-branch --match-head-commit "$TESTED_SHA"
```

Watch exact CI and CodeQL push runs for the merge commit. Both must succeed.

- [ ] **Step 6: Clean up and invalidate stale lock evidence**

Run:

```bash
git -C "$MAIN_ROOT" worktree remove "$WT"
git -C "$MAIN_ROOT" worktree prune
git -C "$MAIN_ROOT" fetch --prune origin
gh pr view 35 --json state,headRefOid,mergeable,statusCheckRollup
gh pr view 36 --json state,headRefOid,mergeable,statusCheckRollup
gh pr view 40 --json state,headRefOid,mergeable,statusCheckRollup
```

Record the no-live-evaluation boundary and merge evidence. No local commit is created.

---

### Task 6: Verify and merge Twine PR #36 as a bounded development-tool major update

**Files:**
- Verify: `pyproject.toml`
- Verify: `uv.lock`
- Test: `tests/test_project_automation.py`
- Test: `tests/test_release_metadata.py`
- Generated locally: `dist/` (ignored build output)
- Update evidence: `.superpowers/sdd/dependabot-maintenance-ledger.md`

**Interfaces:**
- Consumes: current ledger row for PR #36. Design-time head was
  `8307b7b8e1dcc9a1557b3e667f1e6e5819bb40a7`; the intended declaration is `twine>=6,<8` and the
  intended lock resolution is `7.0.0`.
- Produces: merged Twine 7 validation lane or documented incompatibility.

- [ ] **Step 1: Review the major-version change and exact diff**

Confirm the refreshed patch changes only Twine's upper bound, editable lock metadata, and Twine
artifact record. Review official Twine 7.0 release notes for CLI, metadata validation, Python, and
upload behavior changes.

- [ ] **Step 2: Verify release-policy tests at the exact head**

```bash
MAIN_ROOT=$(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)
WT="$MAIN_ROOT/.worktrees/dependabot-pr-36"
git -C "$MAIN_ROOT" fetch origin pull/36/head
git -C "$MAIN_ROOT" worktree add --detach "$WT" FETCH_HEAD
cd "$WT"
uv sync --locked
uv lock --check
uv run pytest tests/test_project_automation.py tests/test_release_metadata.py -q
cd "$MAIN_ROOT"
```

Expected: current-policy tests accept the new range while historical `0.4.0rc3` assertions remain
unchanged and pass.

- [ ] **Step 3: Exercise Twine against fresh artifacts**

Run in the PR worktree:

```bash
cd "$WT"
uv build --clear --no-sources
uv run twine check dist/*
cd "$MAIN_ROOT"
```

Expected: wheel and sdist build successfully and every artifact passes Twine 7 validation.

- [ ] **Step 4: Run the complete offline gate**

Run:

```bash
cd "$WT"
uv run pytest -m 'not eval' -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
git diff --check
git status --short --branch
cd "$MAIN_ROOT"
```

Expected: all pass; only ignored `dist/` may exist.

- [ ] **Step 5: Merge, verify `master`, and clean up**

After `gh pr checks 36 --required`, merge only the head read immediately before the command:

```bash
TESTED_SHA=$(git -C "$WT" rev-parse HEAD)
HEAD_SHA=$(gh pr view 36 --json headRefOid --jq '.headRefOid')
test "$HEAD_SHA" = "$TESTED_SHA"
gh pr merge 36 --merge --delete-branch --match-head-commit "$TESTED_SHA"
```

Watch exact CI and CodeQL master runs. Then run:

```bash
git -C "$MAIN_ROOT" worktree remove "$WT"
git -C "$MAIN_ROOT" worktree prune
git -C "$MAIN_ROOT" fetch --prune origin
gh pr view 35 --json state,headRefOid,mergeable,statusCheckRollup
gh pr view 40 --json state,headRefOid,mergeable,statusCheckRollup
```

Refresh the ledger from these heads and checks. No local commit is created.

---

### Task 7: Diagnose and resolve Ruff PR #35

**Files:**
- Verify/modify if proven necessary: `uv.lock`
- Modify if formatter output is the causal compatibility change: Python files reported by
  `uv run ruff format --check .`
- Test: `tests/test_project_automation.py`
- Test: complete Python suite
- Update evidence: `.superpowers/sdd/dependabot-maintenance-ledger.md`

**Interfaces:**
- Consumes: current ledger row for PR #35. Design-time head was
  `0aac7a141ccffc316fa09af2aeecf04e02f4c94e`; design-time patch changed only Ruff `0.15.22` to
  `0.16.1` in `uv.lock` and failed all supported CI jobs plus `Required`.
- Produces: either a green focused replacement PR containing the Dependabot lock commit plus the
  minimal compatibility correction, or a documented deferral with a retry condition.

- [ ] **Step 1: Invoke the CI-debugging workflow and capture the first causal failure**

Use `github:gh-fix-ci`. Resolve the CI run whose `headSha` equals the current ledger SHA, then run:

```bash
gh pr checks 35
HEAD_SHA=$(gh pr view 35 --json headRefOid --jq '.headRefOid')
RUN_ID=$(gh run list --branch dependabot/uv/ruff-0.16.1 --workflow CI --event pull_request \
  --limit 20 --json databaseId,headSha,conclusion,url | \
  jq -r --arg sha "$HEAD_SHA" 'map(select(.headSha == $sha))[0].databaseId')
test "$RUN_ID" != "null"
gh run view "$RUN_ID" --log-failed
```

Record the first causal step and log excerpt. Do not classify aggregate `Required`, skipped jobs,
or experimental Windows as separate root causes.

- [ ] **Step 2: Reproduce the causal failure on the exact PR head**

```bash
MAIN_ROOT=$(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)
WT="$MAIN_ROOT/.worktrees/dependabot-pr-35"
git -C "$MAIN_ROOT" fetch origin pull/35/head
git -C "$MAIN_ROOT" worktree add --detach "$WT" FETCH_HEAD
cd "$WT"
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run pytest tests/test_project_automation.py -q
cd "$MAIN_ROOT"
```

Expected: one command reproduces the supported CI failure for the same reason. If none does, rerun
the exact failing CI job once; if the exact-head rerun passes, record it as transient and return to
the normal merge gate without a code change.

- [ ] **Step 3: Demonstrate the minimal correction**

If and only if `ruff format --check` is causal, create a maintainer branch from the exact PR head:

```bash
git -C "$WT" switch -c codex/ruff-0.16.1-compat
uv run --directory "$WT" ruff format .
git -C "$WT" diff --stat
git -C "$WT" diff --check
```

Expected: the diff contains formatter-only Python layout changes and no configuration relaxation.
If the causal failure is lint rather than format, add the narrowest code/test correction demanded
by the exact rule; do not disable the rule globally unless the design is reopened.

- [ ] **Step 4: Run focused and full verification**

In the maintainer worktree run:

```bash
cd "$WT"
uv run ruff format --check .
uv run ruff check .
uv run pytest -m 'not eval' -q
uv run pyright
uv lock --check
git diff --check
cd "$MAIN_ROOT"
```

Expected: all pass. Review every formatter/code change for semantic equivalence.

- [ ] **Step 5: Commit and publish the replacement only when a correction exists**

```bash
git -C "$WT" add uv.lock src tests benchmarks scripts
git -C "$WT" commit -m "style: adopt Ruff 0.16 formatting"
git -C "$WT" push -u origin codex/ruff-0.16.1-compat
gh pr create --base master --head codex/ruff-0.16.1-compat \
  --title "build: adopt Ruff 0.16.1" \
  --body "Supersedes #35 by retaining its lock update and adding only the verified Ruff 0.16 compatibility correction. Live model evaluations were not run."
```

Stage only paths that actually changed; omit nonexistent groups from `git add`. If no correction
exists because a rerun passed, merge #35 directly at its unchanged head instead.

- [ ] **Step 6: Merge the green candidate before closing #35**

Select the original PR when no correction was needed, otherwise resolve the replacement PR from its
branch. Compare its live head with the worktree commit before merging:

```bash
CANDIDATE_PR=35
BRANCH=$(git -C "$WT" symbolic-ref --short -q HEAD || true)
if test "$BRANCH" = "codex/ruff-0.16.1-compat"; then
  CANDIDATE_PR=$(gh pr view codex/ruff-0.16.1-compat --json number --jq '.number')
fi
TESTED_SHA=$(git -C "$WT" rev-parse HEAD)
HEAD_SHA=$(gh pr view "$CANDIDATE_PR" --json headRefOid --jq '.headRefOid')
test "$HEAD_SHA" = "$TESTED_SHA"
gh pr checks "$CANDIDATE_PR" --required
gh pr merge "$CANDIDATE_PR" --merge --delete-branch --match-head-commit "$TESTED_SHA"
```

Verify exact CI and CodeQL master runs. If `CANDIDATE_PR` is not `35`, comment on #35 with the
merged replacement link and close it as superseded. Never close #35 before the replacement merge
succeeds.

- [ ] **Step 7: Clean up and record the outcome**

After the original or replacement merge and its master gates succeed, run:

```bash
git -C "$MAIN_ROOT" worktree remove "$WT"
git -C "$MAIN_ROOT" worktree prune
git -C "$MAIN_ROOT" fetch --prune origin
if git -C "$MAIN_ROOT" show-ref --verify --quiet refs/heads/codex/ruff-0.16.1-compat; then
  git -C "$MAIN_ROOT" branch -d codex/ruff-0.16.1-compat
fi
```

Record root cause, correction diff, review URL, merge SHA, master run URLs, and closure link.

---

### Task 8: Repair the active publisher-action contract for PR #38

**Files:**
- Verify: `.github/workflows/publish-pypi.yml`
- Verify: `.github/workflows/publish-testpypi.yml`
- Modify: `tests/test_project_automation.py`
- Preserve: `tests/test_release_metadata.py`
- Preserve: `CHANGELOG.md`
- Update evidence: `.superpowers/sdd/dependabot-maintenance-ledger.md`

**Interfaces:**
- Consumes: current ledger row for PR #38. Design-time head was
  `2c9cf314ff7f0a2d1e80d10febab9266dec94364`; new approved active pin is
  `pypa/gh-action-pypi-publish@dc37677b2e1c63e2034f94d8a5b11f265b73ba33 # v1.14.2`.
- Produces: a green replacement PR that updates active automation assertions while leaving the
  immutable `0.4.0rc3` record at `v1.14.1`.

- [ ] **Step 1: Capture and reproduce the exact supported failure**

Use `github:gh-fix-ci` to inspect the exact-head CI logs. Create a detached PR worktree and run:

```bash
MAIN_ROOT=$(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)
WT="$MAIN_ROOT/.worktrees/dependabot-pr-38"
git -C "$MAIN_ROOT" fetch origin pull/38/head
git -C "$MAIN_ROOT" worktree add --detach "$WT" FETCH_HEAD
cd "$WT"
uv sync --locked
uv run pytest \
  tests/test_project_automation.py::test_testpypi_workflow_is_manual_oidc_only_and_verifies_publication \
  tests/test_project_automation.py::test_publishing_workflows_pin_approved_publisher_action -q
cd "$MAIN_ROOT"
```

Expected RED: active automation tests still require SHA
`ba38be9e461d3875417946c167d0b5f3d385a247` / `v1.14.1` while the workflows use the new immutable
`v1.14.2` SHA.

- [ ] **Step 2: Create the focused maintainer branch**

```bash
git -C "$WT" switch -c codex/pypi-publish-action-1.14.2
```

In `$WT/tests/test_project_automation.py`, change only active workflow assertions:

```python
assert publish_steps[-1]["uses"].startswith(
    "pypa/gh-action-pypi-publish@dc37677b2e1c63e2034f94d8a5b11f265b73ba33"
)
```

and:

```python
publisher = "pypa/gh-action-pypi-publish@dc37677b2e1c63e2034f94d8a5b11f265b73ba33 # v1.14.2"
```

Do not alter `tests/test_release_metadata.py` or the historical changelog entry that asserts
`v1.14.1` for `0.4.0rc3`.

- [ ] **Step 3: Verify GREEN and historical separation**

Run from `$WT`:

```bash
cd "$WT"
uv run pytest tests/test_project_automation.py tests/test_release_metadata.py -q
rg -n "gh-action-pypi-publish.*v1\.14\.[12]" \
  .github/workflows tests/test_project_automation.py tests/test_release_metadata.py CHANGELOG.md
cd "$MAIN_ROOT"
```

Expected: active workflows/tests name `v1.14.2`; historical release evidence still names
`v1.14.1`; both test modules pass.

- [ ] **Step 4: Run the full maintenance gate**

Run from `$WT`:

```bash
cd "$WT"
uv lock --check
uv run pytest -m 'not eval' -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv build --clear --no-sources
uv run twine check dist/*
git diff --check
cd "$MAIN_ROOT"
```

Expected: all pass with no release publication or tag creation.

- [ ] **Step 5: Commit, push, and open the replacement**

```bash
git -C "$WT" add .github/workflows/publish-pypi.yml .github/workflows/publish-testpypi.yml \
  tests/test_project_automation.py
git -C "$WT" commit -m "build: update PyPI publisher action to 1.14.2"
git -C "$WT" push -u origin codex/pypi-publish-action-1.14.2
gh pr create --base master --head codex/pypi-publish-action-1.14.2 \
  --title "build: update PyPI publisher action to 1.14.2" \
  --body "Supersedes #38. Updates the two active OIDC publisher pins and their active automation assertions while preserving immutable 0.4.0rc3 release history."
```

- [ ] **Step 6: Merge replacement, then close #38**

Require exact-head CI and CodeQL success, and compare the live replacement head with the worktree:

```bash
REPLACEMENT_PR=$(gh pr view codex/pypi-publish-action-1.14.2 --json number --jq '.number')
TESTED_SHA=$(git -C "$WT" rev-parse HEAD)
HEAD_SHA=$(gh pr view "$REPLACEMENT_PR" --json headRefOid --jq '.headRefOid')
test "$HEAD_SHA" = "$TESTED_SHA"
gh pr checks "$REPLACEMENT_PR" --required
gh pr merge "$REPLACEMENT_PR" --merge --delete-branch --match-head-commit "$TESTED_SHA"
```

Verify both master push workflows, then comment on and close #38 as superseded. Clean up with:

```bash
git -C "$MAIN_ROOT" worktree remove "$WT"
git -C "$MAIN_ROOT" worktree prune
git -C "$MAIN_ROOT" fetch --prune origin
git -C "$MAIN_ROOT" branch -d codex/pypi-publish-action-1.14.2
```

Record all evidence.

---

### Task 9: Diagnose and resolve Cryptography PR #40

**Files:**
- Verify/modify if proven safe: `uv.lock`
- Test: `tests/test_project_automation.py`
- Test: `tests/interfaces/web/`
- Test: `frontend/`
- Verify generated assets: `frontend/src/test/fixtures/contracts.json`
- Verify generated assets: `src/bundlewalker/interfaces/web/static/`
- Update evidence: `.superpowers/sdd/dependabot-maintenance-ledger.md`

**Interfaces:**
- Consumes: current ledger row for PR #40. Design-time head was
  `aa821b22228ea559feb7878a8b363781c20c613e`; the lock update moved indirect Cryptography from
  `49.0.0` to `50.0.0` and changed `secretstorage` marker normalization.
- Produces: a verified lock update or a deferral identifying the incompatible platform/resolution
  boundary; no direct dependency declaration is added merely to force the resolver.

- [ ] **Step 1: Inspect the exact frontend/browser failure**

Use `github:gh-fix-ci`. Resolve the CI run matching the current PR head and inspect only the failed
frontend/browser job first:

```bash
gh pr checks 40
HEAD_SHA=$(gh pr view 40 --json headRefOid --jq '.headRefOid')
RUN_ID=$(gh run list --branch dependabot/uv/cryptography-50.0.0 --workflow CI \
  --event pull_request --limit 20 --json databaseId,headSha,conclusion,url | \
  jq -r --arg sha "$HEAD_SHA" 'map(select(.headSha == $sha))[0].databaseId')
FRONTEND_JOB_ID=$(gh run view "$RUN_ID" --json jobs | \
  jq -r '.jobs[] | select(.name == "Frontend and browser") | .databaseId')
test "$RUN_ID" != "null"
test -n "$FRONTEND_JOB_ID"
gh run view "$RUN_ID" --job "$FRONTEND_JOB_ID" --log
```

Record the first causal command and exact error. `Required` is downstream and not a second cause.

- [ ] **Step 2: Reproduce on the exact PR head**

```bash
MAIN_ROOT=$(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)
WT="$MAIN_ROOT/.worktrees/dependabot-pr-40"
git -C "$MAIN_ROOT" fetch origin pull/40/head
git -C "$MAIN_ROOT" worktree add --detach "$WT" FETCH_HEAD
cd "$WT"
uv sync --locked
uv lock --check
uv run pytest tests/test_project_automation.py tests/interfaces/web -q
uv run python scripts/generate_web_contract_fixtures.py
npm --prefix frontend ci
npm --prefix frontend run format:check
npm --prefix frontend run lint
npm --prefix frontend run test
npm --prefix frontend run build
npm --prefix frontend audit --audit-level=high
git diff --exit-code -- frontend/src/test/fixtures/contracts.json
git diff --exit-code -- src/bundlewalker/interfaces/web/static
cd "$MAIN_ROOT"
```

Expected: the causal hosted failure is reproduced locally when the affected tool is locally
portable. If it is a hosted-only platform/wheel issue, record that boundary and use the exact
supported CI rerun as the proving environment.

- [ ] **Step 3: Decide merge, minimal replacement, or deferral**

Apply this exact decision table:

```text
transient exact-head failure + successful rerun -> no code change; return to normal merge gate
stale lock resolution after earlier merges -> ask Dependabot to rebase; test the new head
upstream wheel/platform incompatibility -> defer with upstream evidence and retry condition
BundleWalker compatibility regression -> add one focused regression and minimal correction on
  codex/cryptography-50-compat, without declaring Cryptography as a new direct dependency
```

- [ ] **Step 4: Verify the chosen candidate completely**

Run from the selected candidate worktree:

```bash
cd "$WT"
uv sync --locked
uv lock --check
uv run pytest -m 'not eval' -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
npm --prefix frontend ci
uv run python scripts/generate_web_contract_fixtures.py
npm --prefix frontend run format:check
npm --prefix frontend run lint
npm --prefix frontend run test
npm --prefix frontend run test:a11y
npm --prefix frontend run build
npm --prefix frontend audit --audit-level=high
git diff --exit-code -- frontend/src/test/fixtures/contracts.json
git diff --exit-code -- src/bundlewalker/interfaces/web/static
cd "$WT/frontend"
npx playwright install chromium
cd "$WT"
uv run python scripts/run_web_smoke.py -- npm --prefix frontend run test:e2e
AUDIT_REQ=$(mktemp)
trap 'rm -f "$AUDIT_REQ"' EXIT
uv export --frozen --no-emit-project --output-file "$AUDIT_REQ" >/dev/null
uv run pip-audit --strict --requirement "$AUDIT_REQ" --require-hashes --disable-pip
rm -f "$AUDIT_REQ"
trap - EXIT
uv build --clear --no-sources
uv run twine check dist/*
git diff --check
git status --short --branch
cd "$MAIN_ROOT"
```

Expected: every deterministic Python, frontend, browser, audit, generated-asset, and distribution
gate passes. No live model evaluation runs.

- [ ] **Step 5: Publish and merge only a green candidate**

If a maintainer correction is needed, commit it with `fix: support Cryptography 50 resolution`,
push `codex/cryptography-50-compat`, and open a PR that supersedes #40. Otherwise merge #40 at its
unchanged head. In either path, require exact-head CI and CodeQL, verify merged master runs, then
close #40 only if a replacement merged. Use the same tested-head invariant:

```bash
CANDIDATE_PR=40
BRANCH=$(git -C "$WT" symbolic-ref --short -q HEAD || true)
if test "$BRANCH" = "codex/cryptography-50-compat"; then
  CANDIDATE_PR=$(gh pr view codex/cryptography-50-compat --json number --jq '.number')
fi
TESTED_SHA=$(git -C "$WT" rev-parse HEAD)
HEAD_SHA=$(gh pr view "$CANDIDATE_PR" --json headRefOid --jq '.headRefOid')
test "$HEAD_SHA" = "$TESTED_SHA"
gh pr checks "$CANDIDATE_PR" --required
gh pr merge "$CANDIDATE_PR" --merge --delete-branch --match-head-commit "$TESTED_SHA"
```

After the exact master runs pass, clean up the worktree, any merged compatibility branch, and
remote-tracking refs using the Task 7 cleanup pattern. Record the outcome. If the decision was to
defer, do not run the merge block; record the upstream evidence and retry condition instead.

---

### Task 10: Prove and resolve the CodeQL `init`/`analyze` coupling

**Files:**
- Modify when coupling is proven: `.github/workflows/codeql.yml`
- Test: `tests/test_project_automation.py`
- Update evidence: `.superpowers/sdd/dependabot-maintenance-ledger.md`

**Interfaces:**
- Consumes: current rows for PRs #37 and #39. Design-time heads were
  `66ef31e7f27d2857e64aaa9616972ed9a0c1c31a` and
  `a3e47a248f3d94a20565202a1ebd9fb3f5bae8f4`; both target
  `github/codeql-action@f205ea1c3313d32999d8d6a48b4f6530d4437b38 # v4.37.4`.
- Produces: either one green coordinated CodeQL PR followed by superseding closure of #37/#39, or
  separate evidence-backed resolutions if coupling is disproved.

- [ ] **Step 1: Invoke CI debugging and compare exact failures**

Use `github:gh-fix-ci` for both PRs. Capture the CodeQL `Analyze (Python)` logs at each exact head.
Record whether each failure states or demonstrates a version mismatch between `init` and `analyze`.

- [ ] **Step 2: Verify the workflow coupling locally**

Run:

```bash
rg -n "github/codeql-action/(init|analyze)@" .github/workflows/codeql.yml
uv run pytest tests/test_project_automation.py::test_codeql_scans_python_on_changes_and_schedule -q
```

Expected baseline: both components use the same old `v4.37.1` SHA. Each Dependabot patch updates
only one component, creating a mixed-version workflow.

- [ ] **Step 3: Create the coordinated branch from current master**

```bash
MAIN_ROOT=$(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)
WT="$MAIN_ROOT/.worktrees/codeql-action-4.37.4"
git -C "$MAIN_ROOT" fetch origin master
git -C "$MAIN_ROOT" branch codex/codeql-action-4.37.4 origin/master
git -C "$MAIN_ROOT" worktree add "$WT" codex/codeql-action-4.37.4
cd "$WT"
! uv run python - <<'PY'
from pathlib import Path

workflow = Path(".github/workflows/codeql.yml").read_text()
sha = "f205ea1c3313d32999d8d6a48b4f6530d4437b38"
assert workflow.count(f"github/codeql-action/init@{sha}") == 1
assert workflow.count(f"github/codeql-action/analyze@{sha}") == 1
PY
cd "$MAIN_ROOT"
```

Expected RED: the inline assertion fails because current `master` still has both old pins. If it
passes, stop and refresh #37/#39 because `master` already contains the coordinated update.

Change both action references in `$WT/.github/workflows/codeql.yml` to:

```yaml
uses: github/codeql-action/init@f205ea1c3313d32999d8d6a48b4f6530d4437b38 # v4.37.4
```

and:

```yaml
uses: github/codeql-action/analyze@f205ea1c3313d32999d8d6a48b4f6530d4437b38 # v4.37.4
```

Preserve checkout pin, permissions, triggers, schedule, language matrix, and all other workflow
content.

- [ ] **Step 4: Run local RED/GREEN contract checks**

After the edit, run the same contract positively and then the repository checks:

```bash
cd "$WT"
uv run python - <<'PY'
from pathlib import Path

workflow = Path(".github/workflows/codeql.yml").read_text()
sha = "f205ea1c3313d32999d8d6a48b4f6530d4437b38"
assert workflow.count(f"github/codeql-action/init@{sha}") == 1
assert workflow.count(f"github/codeql-action/analyze@{sha}") == 1
PY
uv run pytest tests/test_project_automation.py::test_codeql_scans_python_on_changes_and_schedule -q
uv run pytest tests/test_project_automation.py -q
uv run pytest -m 'not eval' -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
git diff --check
cd "$MAIN_ROOT"
```

Expected: all pass; the diff changes exactly two `uses:` lines.

- [ ] **Step 5: Commit and open the coordinated PR**

```bash
git -C "$WT" add .github/workflows/codeql.yml
git -C "$WT" commit -m "build: update CodeQL actions to 4.37.4"
git -C "$WT" push -u origin codex/codeql-action-4.37.4
gh pr create --base master --head codex/codeql-action-4.37.4 \
  --title "build: update CodeQL actions to 4.37.4" \
  --body "Updates CodeQL init and analyze together at one immutable v4.37.4 SHA. Supersedes #37 and #39 after this replacement passes and merges."
```

- [ ] **Step 6: Require hosted proof, merge, then close originals**

Require exact-head CI and a successful CodeQL `Analyze (Python)` job, then run:

```bash
REPLACEMENT_PR=$(gh pr view codex/codeql-action-4.37.4 --json number --jq '.number')
TESTED_SHA=$(git -C "$WT" rev-parse HEAD)
HEAD_SHA=$(gh pr view "$REPLACEMENT_PR" --json headRefOid --jq '.headRefOid')
test "$HEAD_SHA" = "$TESTED_SHA"
gh pr checks "$REPLACEMENT_PR" --required
gh pr merge "$REPLACEMENT_PR" --merge --delete-branch --match-head-commit "$TESTED_SHA"
```

Verify CI and CodeQL on the resulting master commit, then comment on and close #37 and #39 with the
replacement link. Do not close either original before the replacement is merged.

- [ ] **Step 7: Clean up**

After the replacement merge and its master gates succeed, run:

```bash
git -C "$MAIN_ROOT" worktree remove "$WT"
git -C "$MAIN_ROOT" worktree prune
git -C "$MAIN_ROOT" fetch --prune origin
git -C "$MAIN_ROOT" branch -d codex/codeql-action-4.37.4
```

Record the paired log evidence, replacement PR, merge SHA, master runs, and closure links. Leave
the primary checkout on its current execution branch until Task 11 performs the final `master`
switch.

---

### Task 11: Final queue, repository, and evidence audit

**Files:**
- Read: `.superpowers/sdd/dependabot-maintenance-ledger.md`
- Verify: all files changed by merged maintenance PRs
- Verify: `docs/superpowers/specs/2026-08-08-dependabot-maintenance-cycle-design.md`
- Verify: `docs/superpowers/plans/2026-08-08-dependabot-maintenance-cycle.md`

**Interfaces:**
- Consumes: outcomes and merge evidence from Tasks 1-10.
- Produces: clean synchronized `master`, no stale maintenance worktree/branch, and a complete final
  classification of every execution-start and newly opened Dependabot PR.

- [ ] **Step 1: Refresh the final GitHub inventory**

```bash
git fetch --prune origin
gh pr list --state open --author 'app/dependabot' --limit 100 \
  --json number,title,headRefOid,mergeable,statusCheckRollup,url
gh pr list --state merged --author 'app/dependabot' --limit 100 \
  --json number,title,mergedAt,mergeCommit,url
```

Expected: every execution-start PR is recorded as merged, superseded, or deferred with evidence;
new PRs are classified and either included when in scope or explicitly left for the next cycle.

- [ ] **Step 2: Verify the final local and remote base**

```bash
MAIN_ROOT=$(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)
git -C "$MAIN_ROOT" switch master
git -C "$MAIN_ROOT" pull --ff-only
git -C "$MAIN_ROOT" rev-parse HEAD
git -C "$MAIN_ROOT" rev-parse origin/master
git -C "$MAIN_ROOT" status --short --branch
cd "$MAIN_ROOT"
```

Expected: local and remote SHAs match and the working tree is clean.

- [ ] **Step 3: Run the final complete offline gate**

```bash
uv sync --locked
uv lock --check
uv run pytest -m 'not eval' -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest tests/test_project_automation.py tests/test_release_metadata.py -q
git diff --check
```

Expected: all commands pass; no provider-backed command runs.

- [ ] **Step 4: Run final frontend and distribution gates**

```bash
npm --prefix frontend ci
npm --prefix frontend run format:check
npm --prefix frontend run lint
npm --prefix frontend run test
npm --prefix frontend run test:a11y
uv run python scripts/generate_web_contract_fixtures.py
npm --prefix frontend run build
npm --prefix frontend audit --audit-level=high
git diff --exit-code -- frontend/src/test/fixtures/contracts.json
git diff --exit-code -- src/bundlewalker/interfaces/web/static
cd frontend
npx playwright install chromium
cd ..
uv run python scripts/run_web_smoke.py -- npm --prefix frontend run test:e2e
AUDIT_REQ=$(mktemp)
trap 'rm -f "$AUDIT_REQ"' EXIT
uv export --frozen --no-emit-project --output-file "$AUDIT_REQ" >/dev/null
uv run pip-audit --strict --requirement "$AUDIT_REQ" --require-hashes --disable-pip
rm -f "$AUDIT_REQ"
trap - EXIT
uv build --clear --no-sources
uv run twine check dist/*
```

Expected: all checks pass and generated contracts/assets remain reproducible.

- [ ] **Step 5: Verify exact-head hosted master state**

Resolve the CI and CodeQL push runs whose `headSha` equals final `origin/master`:

```bash
FINAL_MASTER_SHA=$(git rev-parse origin/master)
CI_RUN_ID=$(gh run list --commit "$FINAL_MASTER_SHA" --workflow CI --event push --limit 5 \
  --json databaseId --jq '.[0].databaseId')
CODEQL_RUN_ID=$(gh run list --commit "$FINAL_MASTER_SHA" --workflow CodeQL --event push --limit 5 \
  --json databaseId --jq '.[0].databaseId')
test -n "$CI_RUN_ID"
test -n "$CODEQL_RUN_ID"
gh run view "$CI_RUN_ID"
gh run view "$CODEQL_RUN_ID"
```

Expected: both runs completed successfully. Do not substitute scheduled or PR runs from another
commit.

- [ ] **Step 6: Remove stale maintenance worktrees and branches**

```bash
git worktree list --porcelain
git branch --merged master
git branch -r --merged origin/master
```

Remove only worktrees created by this plan and delete only their merged local branches. Prune
worktrees and remote-tracking refs. Do not delete an unmerged or newly generated Dependabot branch.

- [ ] **Step 7: Complete the ledger and handoff**

The final ledger must contain:

```text
execution-start PR count and exact SHAs
merged original PRs
merged replacement PRs
superseded originals and closure links
deferred PRs with retry conditions
new PRs classified during execution
final master SHA
final local and hosted verification results
worktree and branch cleanup result
```

Run `git status --short --branch` and `git worktree list`. Expected: clean synchronized `master`, no
worktree or branch created by this plan, every unrelated pre-existing worktree preserved, and no
unexplained maintenance item. The ledger stays ignored; the remote PRs and merge commits are the
durable operational record.
