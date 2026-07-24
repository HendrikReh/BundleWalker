# BundleWalker 0.4.0rc3 Dependency Stabilization and Public Beta Design

**Date:** 2026-07-24

**Status:** Approved

**Targets:** Production release candidate `0.4.0rc3`, followed by public beta `0.4.0`

## Summary

BundleWalker `0.4.0rc2` is published on production PyPI and has passed the supported
production-installed lifecycle matrix. Three external users subsequently completed the project
pilot without reporting issues. The maintainer considers that informal validation sufficient for
this personal project and does not require a participant-level pilot evidence record.

Before publishing the final public beta, the maintainer has chosen to include all four pending
dependency-housekeeping updates:

- PydanticAI `2.10.0` to `2.16.0`;
- Typer `0.26.8` to `0.27.0`;
- Ruff `0.15.21` to `0.15.22`; and
- `pypa/gh-action-pypi-publish` `1.14.0` to `1.14.1`.

The runtime and publishing-path changes mean final `0.4.0` must not be cut directly from the
`0.4.0rc2` evidence state. BundleWalker will first publish and validate immutable
`0.4.0rc3`, including a fresh production-installed lifecycle rehearsal. Final `0.4.0` will then
be a release-only promotion of that validated candidate.

## Goals

1. Consolidate all four approved dependency updates on current `master`.
2. Keep TestPyPI and production PyPI on the same immutable publishing-action revision.
3. Validate the changed runtime dependency set as production release candidate `0.4.0rc3`.
4. Repeat the supported production-installed lifecycle gate for exact `0.4.0rc3`.
5. Promote the validated candidate to package version and Git tag `0.4.0`/`v0.4.0`.
6. Describe BundleWalker as a **public beta** in active project documentation.
7. Preserve all historical tags, releases, changelog entries, plans, specifications, benchmarks,
   and rc2 evidence without rewriting their recorded identities.

## Non-goals

- Do not add product behavior, commands, tools, providers, formats, platforms, or UI surfaces.
- Do not refactor application or transaction code.
- Do not broaden support beyond macOS and Linux with Python 3.13 and 3.14.
- Do not make Windows a required or supported platform.
- Do not record pilot participant identities, environments, or individual results.
- Do not rerun the three-user pilot.
- Do not merge stale Dependabot branches individually.
- Do not move, delete, recreate, or reuse any existing tag or published package version.
- Do not tag or publish `0.4.0` until rc3 publication and lifecycle evidence are complete.

## Current State

The authoritative package version and editable lock record are `0.4.0rc2`. Active README, support,
and user documentation still describe BundleWalker as a proof of concept approaching beta.
`pyproject.toml` carries `Development Status :: 3 - Alpha`.

The current lock resolves PydanticAI `2.10.0`, Typer `0.26.8`, and Ruff `0.15.21`.
Both `.github/workflows/publish-testpypi.yml` and `.github/workflows/publish-pypi.yml` pin
`pypa/gh-action-pypi-publish` `v1.14.0` by commit SHA.

Dependabot pull requests 1, 2, 3, and 8 were opened before the current release-gate work reached
`master`. Their branches are stale, share lockfile changes, and do not form a coherent release:
pull request 8 updates only TestPyPI even though production uses the same action. The consolidated
release branch supersedes them.

## Selected Approach

Use two protected release stages.

### Stage 1: 0.4.0rc3 dependency stabilization

One focused branch updates the tested dependency resolution, both publishing workflows, rc3
release identity, active candidate documentation, changelog, and metadata tests. It does not
change application behavior.

The repository lock must resolve exactly:

| Dependency | rc2 lock | rc3 lock | Role |
| --- | --- | --- | --- |
| PydanticAI | `2.10.0` | `2.16.0` | Runtime model and MCP integration |
| Typer | `0.26.8` | `0.27.0` | Runtime CLI |
| Ruff | `0.15.21` | `0.15.22` | Development formatting and linting |

The existing declared dependency floors remain unchanged:

- `pydantic-ai>=2.10.0`;
- `typer>=0.16.0`; and
- `ruff>=0.12.0`.

This preserves BundleWalker's declared compatibility contract while advancing the exact
repository-tested resolution. No unrelated dependency may change unless `uv` proves it is a
required transitive consequence of the three targeted upgrades; every such change must be
identified during review.

Both publishing workflows must pin
`pypa/gh-action-pypi-publish@ba38be9e461d3875417946c167d0b5f3d385a247`, identified by
Dependabot as `v1.14.1`. Tests must require the same immutable SHA and version comment in both
workflows.

The branch advances:

- `pyproject.toml` and the editable project lock record to `0.4.0rc3`;
- active release-candidate assertions and installation examples to `0.4.0rc3`;
- the changelog with a dated `v0.4.0rc3` entry describing dependency and publishing-action
  stabilization; and
- maintainer release instructions to the exact rc3 tag, workflow, failure, and lifecycle path.

The rc3 documentation continues to call BundleWalker a proof of concept approaching public beta.
The Alpha classifier remains until final `0.4.0`.

After the rc3 pull request passes local review and required CI, the maintainer may approve its
merge. Only then may an annotated `v0.4.0rc3` tag be created at the exact merge commit and pushed
once. The protected production workflow builds, publishes, verifies, and creates the GitHub
prerelease from that tag.

The manual production-installed lifecycle workflow then runs for exact `0.4.0rc3` across:

- macOS 15 with Python 3.13;
- macOS 15 with Python 3.14;
- Ubuntu 24.04 with Python 3.13; and
- Ubuntu 24.04 with Python 3.14.

All four artifacts must be inspected under the existing evidence contract. A concise durable rc3
evidence record updates active release and compatibility documentation. Participant-level pilot
evidence remains out of scope.

Only after the consolidated rc3 change lands may Dependabot pull requests 1, 2, 3, and 8 be closed
as superseded, with a reference to the merged replacement.

### Stage 2: 0.4.0 public beta promotion

A separate branch begins from the verified rc3 lifecycle-evidence state. It changes release
identity and active public documentation only:

- package and editable lock versions become `0.4.0`;
- the classifier becomes `Development Status :: 4 - Beta`;
- active status text becomes **public beta**;
- current installation examples use exact `bundlewalker==0.4.0`;
- the changelog gains dated final entry `v0.4.0`;
- comparison links advance through `v0.4.0rc3...v0.4.0`; and
- the release procedure records the final tag and publication boundary.

The final promotion must not update application code, dependencies, workflow action pins, or
historical evidence. If any package-affecting fix becomes necessary after rc3, final promotion
stops and a later release candidate is prepared instead.

Final `v0.4.0` is created only after the release pull request passes required review and CI and is
explicitly approved for merge. The protected production workflow treats exact `0.4.0` as a
non-prerelease, publishes the exact wheel and source archive to PyPI, and creates a non-prerelease
GitHub release from the same bytes.

## Security and Release Audit

The project is a local Python CLI and MCP `stdio` server, not a Django, Flask, FastAPI, or browser
application. The available security-review references contain no framework-neutral Python CLI
guide, so the final audit uses the repository's established threat boundaries and automation.

The rc3 and final gates include:

- the complete non-evaluation test suite;
- formatting, Ruff linting, and strict Pyright checks;
- `uv lock --check`;
- strict hash-checked `pip-audit` over exported third-party requirements;
- wheel and source-distribution builds with `twine check`;
- clean wheel and source-distribution installation smokes;
- CLI and MCP entry-point help/startup smokes;
- release metadata and historical-evidence integrity tests;
- CodeQL, dependency audit, and supported CI matrix review;
- review of open Dependabot, code-scanning, dependency, and private-advisory state;
- immutable action SHA and minimal workflow permission checks;
- scans for committed credentials, private keys, absolute local paths, and unbounded diagnostic
  evidence; and
- explicit confirmation that no known critical or high-severity data-loss, corruption,
  credential-exposure, workspace-boundary, or review-bypass issue remains open.

This personal project does not require a separate committed security-audit report. The release
pull-request description and final release completion summary record the commands and material
findings.

## Testing Strategy

Release changes follow test-first metadata development:

1. Add or revise focused tests for rc3 identity, exact dependency resolution, identical publishing
   action pins, candidate wording, changelog links, and immutable historical evidence.
2. Run the focused tests and observe failure against rc2.
3. Apply the minimal rc3 metadata, lock, workflow, and active-documentation changes.
4. Run focused tests, then the full local release gate.
5. Validate built artifacts in clean environments.
6. Require supported CI, distribution build, dependency audit, artifact smoke, and CodeQL success.
7. Publish and independently inspect rc3 and its lifecycle evidence.
8. Repeat the red/green metadata cycle for final `0.4.0` identity and public-beta wording.
9. Run the complete final release gate again before merge and again on the merged result before
   tagging.

Historical documents that intentionally name alpha, rc1, or rc2 versions are never mechanically
rewritten. Tests must distinguish active release metadata from immutable provenance.

## Failure and Recovery

Before a release tag is pushed, ordinary failures are corrected through the same reviewed branch.

After `v0.4.0rc3` is pushed, the tag and package version are consumed even if publication fails.
Never move, delete, recreate, or reuse them. Apply the existing production recovery matrix. A
package defect advances through review to a later release candidate; a workflow-only defect may
rerun the same immutable package only when published bytes are unaffected and the documented
lifecycle exception applies.

After `v0.4.0` is pushed, the final tag and package version are likewise immutable. If PyPI accepts
unsafe or partial artifacts, use the documented yank mechanism and prepare a fixed patch release.
Never republish different bytes under `0.4.0`.

Experimental Windows failures do not block rc3 or final beta when the required supported job and
all macOS/Linux jobs pass. A supported-platform failure always blocks release.

## Acceptance Criteria

The dependency-stabilization stage is complete only when:

1. the repository lock contains the three exact approved dependency versions and no unexplained
   dependency drift;
2. TestPyPI and production PyPI workflows use the same approved immutable publishing-action SHA;
3. all active candidate metadata consistently names `0.4.0rc3`;
4. local and required remote release gates pass;
5. production PyPI and GitHub expose the exact verified rc3 artifacts;
6. the four-job production-installed rc3 lifecycle gate passes and its artifacts are inspected;
7. durable rc3 lifecycle evidence is merged; and
8. the four superseded Dependabot pull requests are closed.

The public-beta stage is complete only when:

1. final metadata consistently names `0.4.0` and classifier Beta;
2. active project documentation says public beta and no longer labels the current project a proof
   of concept or release candidate;
3. dependencies and application behavior remain identical to the verified rc3 state;
4. the final security and release audit has no blocking finding;
5. local and required remote release gates pass;
6. annotated tag `v0.4.0` identifies the exact reviewed merge commit;
7. production PyPI exposes exactly the verified wheel and source archive;
8. the GitHub release is non-draft, non-prerelease, and carries those exact artifacts; and
9. local `master` and `origin/master` are clean and synchronized after independent verification.
