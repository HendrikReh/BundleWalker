# BundleWalker 0.5.0 GUI Release Design

**Date:** 2026-07-28

**Target:** Public-beta feature release `0.5.0`, Git tag `v0.5.0`

## Context

BundleWalker `0.4.0` is the current production-PyPI public beta. The local
`bundlewalker-web` cockpit has since been implemented, independently reviewed,
merged through pull request 30, and verified on the supported macOS/Linux and
Python 3.13/3.14 matrix. Exact-head CI and CodeQL passed. Fresh merged-state
Python, frontend, accessibility, production-browser, reproducible-asset,
dependency-audit, distribution, and Twine gates also passed.

The GUI is a substantial backward-compatible interface addition. It therefore
advances the minor version to `0.5.0`; it is not a `0.4.1` patch. A separate
`0.5.0rc1` publication is unnecessary because the merged feature already
completed the independent review and release-gate work that an additional
candidate cycle would repeat for this personal project.

## Goals

- Make `0.5.0` the single active package and documentation identity.
- Promote the verified GUI changelog material into a dated `v0.5.0` entry.
- Make active installation and status documentation describe the GUI as
  included in the published public beta.
- Advance protected publishing validation to the explicit `0.5.0` release
  family without broadening it to arbitrary tags.
- Preserve all historical release records and evidence byte-for-byte except
  where an active maintainer procedure must distinguish the new current lane
  from historical `0.4.0` recovery instructions.
- Commit and review the release preparation before creating any immutable tag.

## Non-goals

- No product-code, API, workspace-format, dependency, or platform-support
  change.
- No remote web access, accounts, hosted service, multi-workspace server, or
  background daemon.
- No rewriting, deleting, moving, or reusing existing tags or package
  versions.
- No TestPyPI, production PyPI, GitHub release, or tag mutation in the release
  preparation commit.
- No claim of supported Windows behavior; Windows remains experimental.

## Release identity

`pyproject.toml` remains the sole build/runtime version authority and becomes
`0.5.0`. The editable BundleWalker record in `uv.lock` must be regenerated to
the same value. Runtime `bundlewalker.__version__` continues to derive from
installed distribution metadata.

The private frontend package remains `0.0.0`; it is a contributor/build input,
not a public package or second version authority.

The `Unreleased` changelog section becomes empty and the verified GUI,
packaging, and post-`0.4.0` maintenance notes move together under
`## [v0.5.0] - 2026-07-28`. Comparison links advance to:

- `v0.5.0...HEAD` for `Unreleased`; and
- `v0.4.0...v0.5.0` for the new release.

Historical entries and links remain unchanged.

## Publishing boundary

The production workflow accepts only canonical `0.5.0rcN` candidates or final
`0.5.0`, still requiring an annotated remote tag exactly equal to
`v${project.version}`. GitHub prerelease classification recognizes only the
`0.5.0rc*` shape. TestPyPI validation advances to `0.5.0a*` or `0.5.0rc*` for
future rehearsals, though the final `0.5.0` release does not use TestPyPI.

Before the tag is created, the GitHub `pypi` environment's tag-only deployment
policy must permit `v0.5.0*`. The trusted-publisher tuple is version-independent
and remains:

`bundlewalker/HendrikReh/BundleWalker/publish-pypi.yml/pypi`

The tag is created only after the release pull request passes required review
and CI, is merged into `master`, and the merged commit passes the final
release-state audit. Publication remains a separate irreversible transaction.

## Documentation

The README and user guide identify `0.5.0` as the current public beta, use the
exact `uv tool install "bundlewalker==0.5.0"` command, and state that
`bundlewalker-web` ships in the standard installation. They retain the local,
single-user, loopback-only security and scope boundary.

The maintainer release procedure gains a current `0.5.0` section while
retaining the complete historical `0.4.0rcN` and final-`0.4.0` recovery
records. Active workflow descriptions name the `0.5.0` validation lane and
tag policy.

## Verification

Release-metadata tests must fail first against the `0.4.0` state and then pass
with the coordinated `0.5.0` changes. The complete local release gate includes:

- `uv lock --check`;
- all non-evaluation Python tests;
- Ruff format/check and Pyright;
- frontend format, lint, 81 unit/component tests, and 5 accessibility tests;
- reproducible contract fixtures and production assets;
- npm high-severity audit;
- 9 production-loopback Chromium journeys;
- clean wheel and source archive build for exactly `0.5.0`;
- Twine and packaged-browser-asset validation; and
- clean Git diff/worktree checks.

After the release commit is pushed, required CI and CodeQL must pass on its
exact SHA before the release pull request is merged. No tag may be created from
an unreviewed branch commit.

## Completion

Release preparation is complete when the coordinated `0.5.0` commit is clean,
locally verified, independently reviewed, pushed, and represented by a
mergeable pull request with exact-head required CI and CodeQL success. The GUI
release itself is complete only after the reviewed merge commit is annotated
as `v0.5.0`, production PyPI and GitHub expose the exact verified artifacts,
and a clean installed smoke confirms all three commands including
`bundlewalker-web`.
