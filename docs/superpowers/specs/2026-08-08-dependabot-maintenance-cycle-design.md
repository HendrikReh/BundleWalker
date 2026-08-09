# Dependabot Maintenance Cycle Design

**Date:** 2026-08-08

**Status:** Approved for implementation planning

## Summary

BundleWalker `0.5.0` is published, `master` is clean, and product work has no open issue backlog.
The immediate maintenance backlog consists of ten open Dependabot pull requests spanning GitHub
Actions, development tools, runtime dependencies, and a transitive security-sensitive library.
Some pull requests pass every required supported-platform gate, while others fail supported CI or
CodeQL.

This cycle will use a hybrid, dependency-aware workflow. Independent green updates remain separate
and are merged sequentially. Failing updates receive evidence-first diagnosis and the smallest
update-specific correction. Components that must move together are replaced by one coordinated
maintainer pull request rather than being forced through incompatible isolated updates.

## Goals

1. Review every open Dependabot pull request against its exact head commit.
2. Merge independently safe updates with clear per-update provenance.
3. Diagnose supported CI and CodeQL failures from their exact Actions logs before changing code.
4. Coordinate dependencies or workflow components that cannot be updated safely in isolation.
5. Leave `master` green after every merge rather than treating the batch as one final validation.
6. Close or defer updates only with an evidence-backed explanation.
7. End with no unexplained Dependabot pull request or stale maintenance branch.

## Non-goals

- Adding product features or changing BundleWalker's public behavior.
- Broad refactoring unrelated to dependency compatibility.
- Expanding Windows from experimental to supported.
- Weakening required CI, CodeQL, security checks, or release protections to make an update pass.
- Running live model-quality evaluations or incurring provider cost without separate approval.
- Combining all dependency updates into one undifferentiated lockfile change.
- Publishing a new BundleWalker release.

## Queue Snapshot

The implementation must refresh this snapshot before acting because Dependabot and GitHub Actions
state can change independently of the design document.

### Independent lane

At design time, these pull requests are mergeable and fail only the explicitly experimental
Windows jobs:

- `#26` — `actions/checkout` `7.0.0` to `7.0.1`;
- `#27` — `astral-sh/setup-uv` `8.3.2` to `9.0.0`;
- `#33` — `uvicorn` `0.51.0` to `0.52.0`;
- `#34` — `pydantic-ai` `2.16.0` to `2.21.0`; and
- `#36` — `twine` `6.2.0` to `7.0.0`.

### Diagnostic lane

These pull requests have failures beyond experimental Windows:

- `#35` — Ruff `0.15.22` to `0.16.1`, failing supported CI and the aggregate required gate;
- `#38` — `pypa/gh-action-pypi-publish` `1.14.1` to `1.14.2`, failing supported CI and the
  aggregate required gate; and
- `#40` — `cryptography` `49.0.0` to `50.0.0`, failing the frontend/browser job and the aggregate
  required gate.

The design does not guess at their causes. Diagnosis begins from the exact failing log and proves
the root cause before any correction is proposed.

### Coupled CodeQL lane

- `#37` updates `github/codeql-action/analyze` from `4.37.1` to `4.37.4` and fails CodeQL.
- `#39` updates `github/codeql-action/init` from `4.37.1` to `4.37.4` and fails CodeQL.

The matching versions and complementary workflow roles make coupling a strong hypothesis, not a
conclusion. The implementation must verify it from workflow configuration and logs. If confirmed,
one coordinated maintainer pull request updates every required CodeQL component together. The
replacement must pass before the two Dependabot pull requests are closed.

## Maintenance Architecture

### Wave 1: establish the live baseline

1. Fetch and prune `origin`.
2. Confirm local `master` is clean and matches `origin/master`.
3. Record every open pull request's number, head SHA, changed files, mergeability, and check state.
4. Record repository branch-protection and merge requirements relevant to the cycle.
5. Reclassify any pull request whose state no longer matches this design-time snapshot.

This makes the plan operate on current evidence rather than relying on an August 8 inventory.

### Wave 2: independent updates

Process independent updates one at a time. For each pull request:

1. Inspect the exact patch and official upstream release notes.
2. Identify the affected BundleWalker contract and select focused local checks.
3. Reproduce or validate the changed dependency in an isolated branch or worktree.
4. Run the complete offline project gate after focused checks.
5. Confirm required hosted checks at the same head SHA.
6. Merge using the repository's established merge-commit convention.
7. Wait for or verify the merged `master` gate, then refresh the remaining queue.

Sequential merging is intentional. Several Python updates touch `uv.lock`; refreshing after each
merge prevents a later pull request from being judged using stale resolution evidence.

### Wave 3: supported-check failures

For each diagnostic-lane pull request:

1. Read the exact failing job logs and identify the first causal failure rather than downstream
   skipped or aggregate failures.
2. Reproduce the causal failure locally when the affected surface is locally executable.
3. Add or update a focused regression only when the failure exposes a BundleWalker compatibility
   contract not already tested.
4. Apply the smallest update-specific correction on a maintainer branch.
5. Run focused, full local, and exact-head hosted gates.
6. Merge only if the correction stays within maintenance scope.

If the dependency requires a product behavior change, unrelated refactor, reduced protection, or
unsupported compatibility promise, stop and defer it instead of expanding this cycle.

### Wave 4: coupled workflow updates

If CodeQL coupling is confirmed:

1. Create one maintainer branch from current `master`.
2. Update all mutually constrained CodeQL action references to the same approved version.
3. Preserve workflow permissions, triggers, languages, and security boundaries.
4. Run available local workflow/configuration checks.
5. Push a dedicated pull request and require its CI and CodeQL checks to pass at the exact head.
6. Merge the replacement first.
7. Close `#37` and `#39` as superseded, linking the successful replacement.

If coupling is disproved, repair or defer each original pull request according to its demonstrated
cause. The coordinated branch is not created merely because two failures look similar.

## Evidence and Data Flow

Each maintenance decision follows this evidence chain:

```text
current PR head
    -> exact patch and upstream release evidence
    -> exact failing or successful hosted checks
    -> focused local verification
    -> complete offline verification
    -> unchanged-head confirmation
    -> merge or documented deferral
    -> refreshed master and queue
```

Official upstream changelogs, release notes, and documentation are required for major-version,
security-sensitive, and CI-action updates. Third-party summaries may help discovery but are not
decision authorities.

## Merge Gate

A pull request or coordinated replacement may be merged only when all of the following are true:

1. Its reviewed head SHA is still current.
2. The patch contains only the dependency/workflow update and necessary compatibility evidence or
   correction.
3. Supported macOS and Linux jobs pass on Python 3.13 and 3.14.
4. The aggregate `Required` job passes.
5. CodeQL passes when applicable.
6. Frontend/browser, dependency-audit, distribution-build, and artifact-smoke jobs pass when the
   workflow selects them.
7. Focused local checks and the complete offline gate pass.
8. No required protection was disabled, bypassed, or reclassified.
9. The branch is mergeable against the current `master`.

Experimental Windows failures are recorded but do not block a merge because the current public
support statement explicitly treats Windows as experimental. A failure in any supported or
required gate blocks the merge regardless of GitHub's syntactic `MERGEABLE` state.

The approved cycle authorizes merges that satisfy this gate. A new user decision is required only
if the proposed correction materially changes product behavior, support policy, release policy, or
the scope of this design.

## Verification Matrix

Every updated branch runs the checks appropriate to its surface, followed by the complete offline
gate.

### Complete offline gate

```text
uv lock --check
uv run pytest -m 'not eval' -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
git diff --check
```

### Python runtime or tool updates

- Focused tests for the dependency's integration surface.
- Lockfile consistency and dependency audit.
- Wheel and source-distribution build plus packaged smoke checks when selected by CI.
- Frontend checks when the dependency or lock resolution affects the web installation gate.

### GitHub Actions updates

- Workflow syntax and repository automation tests.
- Preservation of permissions, triggers, environment protections, and immutable release rules.
- Exact-head GitHub Actions execution, because local checks cannot prove hosted action behavior.

### Model-library boundary

The `pydantic-ai` update receives the full offline suite and existing mocked/provider-independent
model integration coverage. Live evaluation remains excluded unless separately approved because it
uses provider credentials, network access, and potentially paid inference.

## Failure and Deferral Handling

- Diagnose the first causal failure; do not treat aggregate `Required` failures or skipped jobs as
  independent root causes.
- Do not edit a Dependabot branch when a maintainer replacement gives clearer ownership and review.
- Never force-push, weaken a check, or merge with a supported failure.
- If upstream is incompatible, close or defer the pull request with the exact failing evidence,
  affected support boundary, and a clear retry condition.
- If a new Dependabot pull request supersedes an older one, retain only the current candidate after
  verifying the relationship.
- If a merge makes another pull request stale or conflicted, refresh and rerun it; do not reuse old
  checks.
- If `master` fails after a merge, stop the queue immediately and repair or revert that merge before
  proceeding.

## Outputs

The cycle produces:

- merged independent dependency updates that satisfy the gate;
- minimal compatibility commits or dedicated replacement pull requests for diagnosed failures;
- one coordinated CodeQL pull request only if coupling is proven;
- evidence-backed closure comments for superseded or deferred updates;
- a final inventory of merged, closed, deferred, and newly opened maintenance work; and
- a clean, synchronized `master` with no stale local worktree or maintenance branch.

## Acceptance Criteria

1. Every Dependabot pull request open at execution start is classified using current evidence.
2. Every merged update satisfies the complete merge gate at an unchanged head SHA.
3. Independent updates retain separate provenance rather than being collapsed into a mega-update.
4. Every supported CI or CodeQL failure has a demonstrated root cause before a correction is made.
5. Coupled components are updated together only when coupling is proven.
6. No live model evaluation, support expansion, product feature, or release publication occurs.
7. Every closed or deferred pull request records why it was not merged and what would allow retry.
8. `master` remains green after each merge and at final handoff.
9. The final repository has no unexplained open Dependabot pull request or stale maintenance branch.
