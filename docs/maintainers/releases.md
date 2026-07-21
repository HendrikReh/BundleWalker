# BundleWalker Release Procedure

BundleWalker builds one wheel and one source distribution for each publication. The same verified
artifacts are promoted; they are never rebuilt between indexes or release attachments.

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

Before the first production upload, configure GitHub environment `pypi` with required reviewer
`HendrikReh`, self-review permitted, and a tag-only deployment rule `v0.4.0*`. Register the PyPI
pending trusted publisher while signed in as `hereh`:

| Field | Value |
| --- | --- |
| PyPI project | `bundlewalker` |
| GitHub owner | `HendrikReh` |
| GitHub repository | `BundleWalker` |
| Workflow | `publish-pypi.yml` |
| Environment | `pypi` |

For `0.4.0rc1`, merge the protected release pull request first. Confirm clean synchronized
`master`, create annotated tag `v0.4.0rc1` at that exact merge commit, verify it, and push it once.
Inspect the build evidence before approving the `pypi` deployment. The workflow then publishes,
verifies a clean exact production installation with bounded propagation retry, compares PyPI
digests, and creates GitHub prerelease `BundleWalker 0.4.0rc1`.

Never move or reuse a pushed tag or package version. If build or pre-upload validation fails after
tag push, fix through review and advance to `0.4.0rc2`. If upload succeeds but propagation
verification exhausts its bounded retry, confirm the immutable PyPI files and rerun only the
failed verification job and downstream release job. If only GitHub release creation fails, rerun
only that downstream job; it reuses the retained workflow artifact and verifies any existing
same-named asset byte-for-byte.

Production `0.4.0` is forbidden until every public-beta exit gate passes. `0.4.0rc1` certifies the
production clean-install candidate, not final beta readiness. The next gate is a
production-installed workspace lifecycle rehearsal covering inspection, backup, separate-target
restore, upgrade behavior, rollback, and post-operation verification.

## Failure and rollback

Do not retry by rebuilding the same version. Diagnose the failed job, fix the repository, increment
the prerelease or patch version, and run the complete verification again. If a production release
is later found unsafe, stop new installations through the package index's supported yank mechanism,
publish an advisory, and issue a fixed version; do not move or reuse its Git tag.
