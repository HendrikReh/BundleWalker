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

## TestPyPI

TestPyPI publishing uses the GitHub workflow `publish-testpypi.yml`, GitHub environment
`testpypi`, and a matching TestPyPI trusted publisher. It does not use an API-token secret.
The workflow's build and publish jobs run only from `master`.

Dispatch it with the exact version already present on `master`:

```bash
gh workflow run publish-testpypi.yml --ref master -f version=0.4.0a1
```

The build, publish, and TestPyPI installation jobs must all pass. TestPyPI versions are immutable;
increment the prerelease version instead of attempting to overwrite a failed publication.

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
