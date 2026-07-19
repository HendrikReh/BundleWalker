# BundleWalker Release Procedure

BundleWalker builds one wheel and one source distribution for each publication. The same verified
artifacts are promoted; they are never rebuilt between indexes or release attachments.

## Version policy

- `pyproject.toml` is the only authoritative build/runtime package-version source.
- `bundlewalker.__version__` reads installed distribution metadata.
- Historical `v1`, `v2`, and `v3` tags remain unchanged.
- New tags match package versions, for example `v0.4.0` and `v0.4.1`.
- Alpha or release-candidate versions may be published to TestPyPI.
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

Production publication is a later milestone. Before enabling it, add a separate `pypi` environment
with required human approval, configure its trusted publisher, require a package-aligned tag, and
attach the exact workflow-built wheel and source archive to the GitHub release.

Never delete or replace historical releases to correct a later license, documentation, or
compatibility decision. Publish a new version and document the difference.

## Failure and rollback

Do not retry by rebuilding the same version. Diagnose the failed job, fix the repository, increment
the prerelease or patch version, and run the complete verification again. If a production release
is later found unsafe, stop new installations through the package index's supported yank mechanism,
publish an advisory, and issue a fixed version; do not move or reuse its Git tag.
