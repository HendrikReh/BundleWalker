# BundleWalker 0.4.0rc1 Production Release Design

**Date:** 2026-07-21
**Status:** Approved
**Target:** First production-PyPI release candidate for the BundleWalker public beta

## Context

BundleWalker has completed its supported-platform build foundation, TestPyPI trusted-publishing
rehearsals, workspace lifecycle safety work, diagnostics, MCP documentation, and reviewed
performance-capacity evidence. The repository currently declares package version `0.4.0a2`, and
TestPyPI contains immutable `0.4.0a1` and `0.4.0a2` alpha publications. Required macOS and Linux
CI is active, while Windows remains a visible, non-blocking experimental lane.

Production PyPI does not yet contain a `bundlewalker` project. The maintainer is signed in to
production PyPI as `hereh`, so the first production publication must use PyPI's pending trusted
publisher bootstrap flow. GitHub currently has a `testpypi` environment and a dedicated
TestPyPI workflow, but no production `pypi` environment, publisher, workflow, release-candidate
tag, or production package record.

The next release identity is `0.4.0rc1`, with Git tag `v0.4.0rc1`. This is a public prerelease and
the first production-PyPI installation candidate. It is not the final `0.4.0` beta and does not,
by itself, remove BundleWalker's proof-of-concept status.

## Goals

- Publish exactly one wheel and one source distribution for `bundlewalker==0.4.0rc1` to
  production PyPI through GitHub Actions OIDC trusted publishing.
- Build the publication artifacts once, verify them, publish those exact files, and attach the
  same files to a GitHub prerelease.
- Require a reviewed, protected pull request before the release identity reaches `master`.
- Require an immutable package-aligned Git tag before production publication can start.
- Put the production upload behind a dedicated GitHub `pypi` environment with human approval
  and tag-only deployment restrictions.
- Prove that the exact production version can be installed and that both public command entry
  points start successfully.
- Preserve an auditable, retry-safe recovery path after PyPI has accepted immutable artifacts.
- Keep the workflow reusable for later `0.4.0rcN` candidates and final `0.4.0` without weakening
  identity checks.

## Non-goals

- Do not publish final version `0.4.0` in this release.
- Do not call the public-beta milestone complete solely because `0.4.0rc1` is installable.
- Do not add a local web UI, hosted service, remote MCP transport, multi-user behavior, new
  ingestion formats, or another application feature.
- Do not replace the current GPL-3.0-or-later/CC0-1.0 license split or rewrite historical release
  artifacts.
- Never move, delete, or reuse any existing tag, release, or package version.
- Do not promote files downloaded from TestPyPI. The TestPyPI alphas already exercised the
  packaging and OIDC path; production `0.4.0rc1` is built from its own reviewed tag.
- Do not store a PyPI password or API token in GitHub secrets.
- Do not rewrite historical benchmark evidence whose recorded runtime version is `0.4.0a2`.
- Do not certify Windows; it remains experimental.

## Considered Approaches

### Dedicated tag-gated production workflow — selected

Add `publish-pypi.yml` alongside the existing TestPyPI workflow. A pushed `v*` tag starts a
release pipeline that validates the tag against the version in the tagged source tree, builds and
tests once, pauses at the protected `pypi` environment, publishes through OIDC, verifies the
production record and installation, and finally creates the GitHub release from the downloaded
workflow artifact.

This keeps production authorization, triggers, logs, and recovery semantics separate from
TestPyPI. It also allows the production environment to approve a specific immutable tag rather
than a manually supplied version string.

### Parameterize the existing TestPyPI workflow

A repository-index input could select TestPyPI or production PyPI. This would reduce YAML
duplication but would place rehearsal and production credentials behind one control surface. A
wrong input or conditional would have a larger blast radius, and environment protections would
be harder to audit. This approach is rejected.

### Manual local upload with an API token

A maintainer could build locally and upload with Twine. This would depend on workstation state,
introduce a long-lived credential, and weaken artifact provenance and repeatability. This
approach is rejected.

## Release Identity and Immutability

The release has four identity anchors:

1. the reviewed merge commit on `master`;
2. package version `0.4.0rc1` in `pyproject.toml` and derived installed metadata;
3. annotated Git tag `v0.4.0rc1` pointing to that exact merge commit; and
4. production-PyPI project version `0.4.0rc1`.

The workflow accepts GitHub's broad `v*` tag glob only as an event filter. Before any build or
OIDC operation, repository-owned validation must prove all of the following:

- the ref is a tag;
- the tag name is exactly `v${project_version}`;
- the version is valid PEP 440 metadata;
- the version belongs to the beta lane: `0.4.0rcN`, where `N` is a positive integer, or final
  `0.4.0`; and
- installed distribution metadata produced from the checked-out tag equals the declared version;
  and
- the current `origin` tag has both an annotated-tag ref and a peeled ref whose commit equals the
  workflow event commit.

`0.4.0rc1` and `v0.4.0rc1` are single-use identifiers. Once the tag is pushed, never move, delete,
or reuse it, even if failure occurs before PyPI accepts an upload. A repository or workflow
fix after tag creation advances to `0.4.0rc2` and `v0.4.0rc2`. If PyPI accepts any file, the version
is also permanently consumed.

## Reviewed Repository State

All repository changes land through branch `codex/release-0.4.0rc1` and a protected pull request.
The release-preparation change will:

- set `project.version` to `0.4.0rc1` and refresh only the derived editable-project lock record;
- update runtime/version assertions that intentionally describe the current package;
- preserve historical fixtures, evidence JSON, release plans, and dated documentation that
  intentionally record `0.4.0a2`;
- update the README, changelog, maintainer release procedure, and affected current-version docs;
- add the production workflow and focused automation tests for its release contract; and
- identify `0.4.0rc1` as a production prerelease while retaining the proof-of-concept warning.

The pull request must pass every required supported-platform and repository gate before merge.
No production tag or publication is created from the feature branch.

## Production Workflow Architecture

The new `.github/workflows/publish-pypi.yml` is triggered only by pushed tags matching `v*`.
Actions are pinned to full commit SHAs, checkout does not retain credentials, and each job receives
only the permissions it needs.

The dependency order is:

1. `build`
2. `publish`
3. `verify`
4. `github-release`

### Build job

The `build` job runs on Ubuntu 24.04 with Python 3.13 and read-only repository contents. It checks
out the exact tagged commit and performs these gates before producing release files:

1. query `origin` for both the current tag ref and its peeled ref, rejecting missing, lightweight,
   deleted, or moved tags and requiring the peeled commit to equal `GITHUB_SHA`;
2. validate the ref, declared version, beta-lane version, tag/version equality, and installed
   metadata;
3. synchronize the frozen environment and verify the lockfile;
4. run the full offline non-evaluation test suite;
5. run Ruff formatting and lint checks;
6. run Pyright;
7. export and audit locked third-party dependencies with `pip-audit`;
8. build with `uv build --clear --no-sources`;
9. require exactly one `bundlewalker-*.whl` and one `bundlewalker-*.tar.gz` for the exact version;
10. validate both files with Twine;
11. install the built wheel into a clean environment and smoke-test `bundlewalker --help` and
    `bundlewalker-mcp --help`; and
12. calculate and log SHA-256 digests for both files.

Only after all gates pass does the job upload the two-file `dist/` directory as the workflow
artifact `python-package-distributions`. Later jobs download this artifact; they never invoke a
package build.

### Publish job

The `publish` job depends on `build` and targets the GitHub environment `pypi`, whose environment
URL is the production PyPI BundleWalker project page. Entering the environment requires the
configured human approval and a permitted release tag.

This job has `id-token: write` and no repository write permission. It downloads the exact build
artifact and invokes the pinned `pypa/gh-action-pypi-publish` action using its production-PyPI
default endpoint. It supplies no password, API token, or TestPyPI repository URL.

### Verify job

The `verify` job runs after either ordinary success or ordinary failure of the upload action,
provided the build succeeded. It has read-only permissions, no OIDC or repository-write
permission, and downloads the exact build artifact. It then:

1. queries the official production-PyPI JSON API for the exact version without retrying metadata;
2. requires exactly the expected wheel and source archive filenames and SHA-256 digests;
3. creates a clean Python 3.13 virtual environment;
4. installs the workflow-built wheel with dependencies and confirms both command entry points;
5. uninstalls BundleWalker while retaining those resolved dependencies;
6. installs exact version `bundlewalker==${project_version}` from production PyPI with
   `--no-deps`;
7. retries only this exact production-index installation for a bounded propagation window;
8. confirms installed distribution metadata equals the tag-derived version; and
9. smoke-tests `bundlewalker --help` and `bundlewalker-mcp --help` from the production install.

The bounded index retry uses at most six attempts with waits of 5, 10, 20, 40, and 80 seconds,
matching the proven TestPyPI propagation policy. Only production-index resolution is retryable.
Artifact installation, metadata, checksum, and command failures remain immediate.

### GitHub release job

The `github-release` job runs only after production verification passes. It alone receives
`contents: write`. Before using that permission, it queries `origin` again for the current tag and
peeled ref, rejecting a lightweight, deleted, or moved tag and requiring the peeled commit to equal
`GITHUB_SHA`. It downloads `python-package-distributions` and creates a GitHub release titled
`BundleWalker 0.4.0rc1` for the existing tag.

For `0.4.0rcN`, the release is marked as a prerelease. When the same workflow later handles exact
version `0.4.0`, it creates a non-prerelease release. Release notes come from the corresponding
reviewed changelog section. The attached wheel and source archive are byte-for-byte the same files
whose digests were accepted and verified on production PyPI.

The release job must be idempotent enough to recover after PyPI publication: it may create a
missing GitHub release or upload missing exact assets, but it must not rebuild or republish the
Python distributions.

## External Trusted-Publishing Configuration

### GitHub environment

Before the tag is pushed, create GitHub environment `pypi` with:

- required reviewer: GitHub account `HendrikReh`;
- deployment branches and tags limited to release tags matching the repository's `v*` release
  convention;
- no PyPI token secret; and
- environment URL `https://pypi.org/project/bundlewalker/` in the workflow.

After configuration, inspect the environment through GitHub's API and confirm that approval and
tag restriction rules are actually present. The tag must not be pushed while the environment is
unprotected.

### Production PyPI pending publisher

Because the production project does not yet exist, user `hereh` registers a pending trusted
publisher from the PyPI account settings with these exact values:

| Field | Value |
| --- | --- |
| PyPI project name | `bundlewalker` |
| GitHub owner | `HendrikReh` |
| GitHub repository | `BundleWalker` |
| Workflow filename | `publish-pypi.yml` |
| Environment | `pypi` |

The first successful OIDC upload creates the production project and converts the pending publisher
into a project-scoped trusted publisher. Afterward, inspect the production project and confirm
that `hereh` owns or manages it and the expected publisher is registered. Credentials are entered
only by the maintainer directly into PyPI; they are never exposed to Codex, logs, files, or GitHub
secrets.

## Publication Sequence

The external release transaction is deliberately ordered:

1. merge the protected release-preparation pull request into `master` after required checks pass,
   binding the merge to the recorded reviewed PR head;
2. create and verify the protected GitHub `pypi` environment;
3. register and verify the production-PyPI pending trusted publisher;
4. immediately before tagging, fetch fresh `origin/master` and tags, read the actual PR merge OID
   from GitHub, and require it, local `master`, and fresh `origin/master` to agree while the tree is
   clean;
5. re-read the environment reviewer and tag-only rule, re-open the PyPI publishing settings to
   verify the exact pending-publisher tuple, and confirm the production project/version remains
   unavailable;
6. create annotated tag `v0.4.0rc1` at the exact reviewed merge commit;
7. verify the tag locally before pushing it;
8. push the tag once, starting the production workflow;
9. inspect the build evidence and explicitly approve the `pypi` environment deployment;
10. wait for publish, production verification, and GitHub prerelease creation to pass;
11. independently inspect production-PyPI JSON, the project page, the remote tag, workflow run,
    GitHub prerelease, attached assets, and checksums; and
12. perform one final clean install of exact `bundlewalker==0.4.0rc1` and run both CLI help smokes.

The production environment approval is the final human authorization before an irreversible PyPI
upload. Approval applies to the displayed tag and build evidence, not to a mutable branch head.

## Failure and Recovery Semantics

Failures before the tag is created are ordinary reviewed repository fixes; `0.4.0rc1` remains
available if no immutable release identity exists.

Once `v0.4.0rc1` is pushed, never move, delete, or reuse it. A build or pre-upload failure requires a
reviewed fix and new version/tag `0.4.0rc2`/`v0.4.0rc2` rather than mutating the first tag.

After either ordinary success or ordinary failure of the upload action, read-only verification uses
production PyPI as the authority:

- if no remote files exist, verification fails and the release advances to `0.4.0rc2`;
- if one remote file exists or any filename or digest mismatches, verification fails, the unsafe
  partial release is yanked through PyPI, and the release advances to `0.4.0rc2`;
- if both exact filenames and digests exist, verification continues even if the upload action
  reported failure, allowing the downstream GitHub release to attach the retained artifacts
  without rebuilding or republishing;
- if only production-index installation exhausts the bounded propagation window after exact
  metadata succeeds, rerun only the failed verification job and downstream release job;
- if only GitHub release creation or attachment fails, rerun only that downstream job using the
  retained exact workflow artifact; and
- if an unsafe production version is discovered later, use PyPI's supported yank mechanism,
  publish an advisory, and issue a new version. Preserve the historical GitHub release and never
  move, delete, or reuse its tag.

A fully cancelled workflow may not execute verification. Maintainers must inspect production PyPI
manually before any further action and must never restart build or publish for a version whose files
may already have been accepted.

Workflow artifact retention must be long enough to support downstream recovery. Maintainers also
record the two distribution SHA-256 digests in the successful run and GitHub release evidence.

## Security Model

- Production authentication uses short-lived OIDC credentials bound to the exact GitHub owner,
  repository, workflow filename, and `pypi` environment.
- The upload job is the only job with `id-token: write`.
- The GitHub release job is the only job with `contents: write`.
- Build and verification jobs have read-only contents permission.
- Third-party actions are pinned to immutable commit SHAs.
- Checkout does not persist credentials.
- A human-approved protected environment separates a valid build from an irreversible upload.
- No package-index token is stored in repository, environment, organization, or local files.
- The build, audit, metadata, artifact-count, version, and tag gates run before OIDC publication.

## Repository Tests and Verification

Focused automation tests will parse the production workflow and enforce its contract, including:

- tag-only trigger and exact tag/version validation;
- accepted beta-lane versions and rejection of unrelated tags;
- current remote annotated-tag and peeled-commit validation before build and GitHub release;
- frozen setup, offline tests, lint, type, lock, audit, build, Twine, artifact-count, and clean-wheel
  smoke gates;
- one artifact passed through build, publish, verify, and GitHub release jobs;
- `pypi` environment use and production trusted publishing without a token or TestPyPI endpoint;
- least-privilege job permissions;
- bounded production-index propagation retry;
- ordinary upload-action failure flowing to read-only PyPI verification;
- exact installed-version, filename, and checksum verification;
- GitHub prerelease behavior for release candidates and final-release behavior for `0.4.0`;
- no `continue-on-error` on a production release job, no JSON metadata retry; and
- no second build or publication command in downstream jobs.

Before the pull request is proposed, run the full non-evaluation suite, Ruff formatting and lint,
Pyright, lock verification, dependency audit, clean package build, Twine validation, wheel-install
smoke, and `git diff --check`. The protected pull-request CI supplies the official macOS/Linux
matrix evidence.

After merge but before tagging, perform a read-only release-state audit. After publication,
compare local/workflow SHA-256 values with production-PyPI JSON and GitHub release assets.

## Documentation and Public Claims

The README and changelog will describe `0.4.0rc1` as the current production-PyPI release candidate,
with an exact prerelease installation command. Maintainer documentation will describe environment
and pending-publisher setup, immutable tagging, approval, verification, downstream-only retry,
yanking, and the future `0.4.0` path.

Historical `v1`, `v2`, `v3`, `0.4.0a1`, and `0.4.0a2` records remain intact. Historical benchmark
evidence continues to identify the version that produced it. Current documentation may link that
reviewed evidence without pretending it was generated by `0.4.0rc1`.

The public support statement remains:

- macOS and Linux are officially supported;
- Windows is experimental;
- BundleWalker is still a proof of concept approaching public beta; and
- `0.4.0rc1` proves the production clean-install path, not final beta readiness.

The next release gate after `0.4.0rc1` is a production-installed lifecycle rehearsal covering
workspace inspection, upgrade behavior, verified backup, separate-target restore, rollback, and
post-operation checks. Final `0.4.0` remains reserved until that rehearsal and the remaining public
beta exit criteria pass.

## Acceptance Criteria

The `0.4.0rc1` production release is complete only when all of the following are fresh evidence:

- [ ] The release-preparation pull request is merged with all required supported-platform checks
  passing.
- [ ] `master`, `origin/master`, and annotated tag `v0.4.0rc1` identify the exact reviewed commit.
- [ ] The GitHub `pypi` environment requires `HendrikReh` approval and permits only release tags.
- [ ] Production PyPI recognizes the pending or converted publisher for owner/repository/workflow/
  environment tuple `HendrikReh/BundleWalker/publish-pypi.yml/pypi`.
- [ ] The workflow build, publish, production verification, and GitHub release jobs all pass.
- [ ] Production PyPI reports `bundlewalker==0.4.0rc1` with exactly the expected wheel and source
  archive.
- [ ] Production PyPI SHA-256 digests equal the workflow artifact digests.
- [ ] A clean exact production installation reports version `0.4.0rc1` and both CLI help smokes
  pass.
- [ ] GitHub has a prerelease for `v0.4.0rc1` with the exact same wheel and source archive.
- [ ] The repository's release documentation and changelog identify the candidate accurately and
  retain the proof-of-concept and platform-support boundaries.
- [ ] Local `master` is clean and synchronized after the release audit.

Passing these criteria certifies the production release candidate. It does not authorize final
`0.4.0` or close the broader public-beta milestone.
