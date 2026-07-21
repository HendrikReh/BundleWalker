# BundleWalker Release Procedure

TestPyPI and production builds are separate.
Production builds fresh artifacts from its reviewed tag: one wheel and one source distribution.
The publish, verification, and GitHub release jobs then reuse those exact production bytes without
rebuilding them.

## Version policy

- `pyproject.toml` is the only authoritative build/runtime package-version source.
- `bundlewalker.__version__` reads installed distribution metadata.
- Historical `v1`, `v2`, and `v3` tags remain unchanged.
- New tags match package versions, for example `v0.4.0` and `v0.4.1`.
- Alpha versions are rehearsed on TestPyPI; release candidates are published to production PyPI
  only through the protected production workflow.
- Production `0.4.0` is forbidden until every public-beta exit gate passes.

## Local release verification

Run from a clean checkout:

```bash
uv sync --locked
uv lock --check
uv run pytest -m 'not eval' -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
AUDIT_REQ="$(mktemp)"
uv export --frozen --no-emit-project --output-file "$AUDIT_REQ" >/dev/null
uv run pip-audit --strict --requirement "$AUDIT_REQ" --require-hashes --disable-pip
uv build --clear --no-sources
uv run twine check dist/*
git diff --check
```

The commands must all exit zero. The `dist/` directory must contain exactly one
`bundlewalker-*.whl` and one `bundlewalker-*.tar.gz` for the declared version.

## Workspace lifecycle evidence

Before publishing any prerelease or release that can read BundleWalker workspaces, attach or link
fresh evidence for the authoritative [workspace compatibility policy](../workspace-compatibility.md):

- [ ] Static historical `v1`, `v2`, and `v3` workspace fixtures pass their documented
  compatibility, backup, restore, and supported-read behavior without regeneration by current
  initialization code.
- [ ] A current verified backup and its separate-target restore both print `SHA-256`; the recorded
  archive digests match.
- [ ] A rollback rehearsal restores a verified pre-upgrade backup to a separate new or empty
  target. It does not overwrite, rename, or remove the original workspace.
- [ ] The restored rollback target reports `current` through `bundlewalker workspace status`, and
  offline deterministic `bundlewalker lint` completes without errors from inside that target.
- [ ] Abrupt-termination recovery evidence passes for prepared, accepted, raw-persisted, swapping,
  and new-live transaction phases, including idempotent second recovery.
- [ ] Required CI is green on Ubuntu 24.04 and macOS 15 with both Python 3.13 and 3.14. Windows
  2025 jobs for Python 3.13 and 3.14 remain experimental and `continue-on-error`; they provide
  visibility and are not evidence of supported Windows behavior.

Production currently registers no migration and format `1` upgrade is a no-op. Synthetic migration
tests prove backup-before-mutation and rollback orchestration without claiming a real format
migration.

## TestPyPI

TestPyPI publishing uses the GitHub workflow `publish-testpypi.yml`, GitHub environment
`testpypi`, and a matching TestPyPI trusted publisher. It does not use an API-token secret.
The workflow's build and publish jobs run only from `master`.

Dispatch it with the exact version already present on `master`:

```bash
gh workflow run publish-testpypi.yml --ref master -f version=0.4.0a2
```

The build, publish, and TestPyPI installation jobs must all pass. TestPyPI versions are immutable;
increment the prerelease version instead of attempting to overwrite a failed publication.

The verification job retries only the exact TestPyPI installation up to six times, waiting 5,
10, 20, 40, and 80 seconds after successive propagation failures. Build, upload, artifact,
metadata, and CLI failures remain immediate. If upload succeeded but post-upload verification
exhausted the propagation window, confirm the immutable version is present on TestPyPI and rerun
only the failed verification job; do not dispatch a new build or publication for that version.

## Production PyPI and GitHub releases

Production publishing uses `publish-pypi.yml`, GitHub environment `pypi`, and a matching PyPI
trusted publisher. The workflow starts only from a pushed `v*` tag, validates that the tag is
exactly `v${project.version}`, and accepts only `0.4.0rcN` or final `0.4.0`. It builds one wheel and
one source archive, publishes those exact files, verifies production filenames and SHA-256
digests, and attaches the same files to the GitHub release.

Before the first production upload, configure GitHub environment `pypi` with exactly one
required-reviewers rule naming only GitHub user `HendrikReh`, self-review permitted, no wait timer
or custom protection rule, custom deployment policies enabled, and protected-branch policy
disabled. The only other protection-rule type must be the branch-policy rule, and the separate
policy endpoint must contain exactly one tag rule `v0.4.0*` and no branch rule. Register the PyPI
pending trusted publisher while signed in as `hereh`:

| Field | Value |
| --- | --- |
| PyPI project | `bundlewalker` |
| GitHub owner | `HendrikReh` |
| GitHub repository | `BundleWalker` |
| Workflow | `publish-pypi.yml` |
| Environment | `pypi` |

`v0.4.0rc1` is consumed and immutable at commit
`d3a18370e2fdc7cfe2f79728731c82ba63aa0cf1`. Production workflow run `29847165596` failed once in
the reversible build stage because `uv build --clear` created `dist/.gitignore` and the validation
step counted every regular file. It produced no retained workflow artifact, deployment approval,
OIDC upload, PyPI version, or GitHub release. Never rerun that workflow or move, delete, or reuse
the rc1 tag.

For `0.4.0rc2`, merge the protected recovery pull request first, binding the merge to its recorded
head commit. Immediately before tagging, fetch fresh `origin/master` and tags; require local
`master`, fresh `origin/master`, and the pull request's actual merge OID to agree. Re-read the
`pypi` environment reviewer and tag-only rule, and verify the still-pending trusted-publisher tuple
`bundlewalker/HendrikReh/BundleWalker/publish-pypi.yml/pypi`; this tuple is keyed by workflow and
environment, not package version. Confirm production `0.4.0rc2` is unavailable. Only then create
annotated tag `v0.4.0rc2` at that exact merge commit, verify it, and push it once. Inspect the
build evidence before approving only the exact `pypi` deployment for that tag and commit.

Never move, delete, or reuse a pushed tag or package version. If build or pre-upload validation
fails after tag push, fix through review and advance to `0.4.0rc3`. The read-only verification job
runs after either ordinary success or ordinary failure of the upload action and treats production
PyPI as authoritative:

- If PyPI exposes neither file, verification fails; advance through review to `0.4.0rc3`.
- If PyPI exposes one file or any filename or digest differs, treat the release as unsafe, yank
  the partial version through PyPI, and advance through review to `0.4.0rc3`.
- If PyPI exposes both exact filenames and digests, verification continues even when the upload
  action reported failure. A successful exact-version install then permits the downstream GitHub
  release job to attach the retained workflow artifacts without rebuilding or republishing.

Only the exact production-index installation receives the bounded 5/10/20/40/80-second
propagation retry. Metadata, checksum, artifact, and CLI failures remain immediate. If that
installation alone exhausts its retry, download the original run artifact and prove production
JSON has the complete exact filename/digest set. Obtain the original verification job database ID,
then run `gh run rerun "$RUN_ID" --job "$VERIFY_JOB_ID"`; this reruns verification and its
dependent release job without rerunning upload. Never rerun a failed publish job. If only GitHub
release creation fails, target only that original job; it reuses the retained workflow artifact and
verifies any existing same-named asset byte-for-byte. A fully cancelled workflow may not reach
verification; inspect production PyPI manually before any further action and never restart build
or publish for a version whose files may have been accepted.

Completion requires successful build, authoritative verification, and GitHub release jobs.
Publish normally succeeds; a failed publish is safe only when the same run's exact-set verification
and GitHub release both succeed. Keep that failed job visible and record a recovered publication
warning in the completion report.

Production `0.4.0` is forbidden until every public-beta exit gate passes. `0.4.0rc2` certifies the
production clean-install candidate, not final beta readiness. The next gate is a
production-installed workspace lifecycle rehearsal covering inspection, backup, separate-target
restore, upgrade behavior, rollback, and post-operation verification.

## Failure and rollback

Do not retry by rebuilding the same version. Diagnose the failed job, fix the repository, increment
the prerelease or patch version, and run the complete verification again. If a production release
is later found unsafe, stop new installations through the package index's supported yank mechanism,
publish an advisory, and issue a fixed version; never move, delete, or reuse its Git tag.
