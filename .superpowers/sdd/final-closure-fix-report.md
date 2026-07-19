# Final closure fix report

## Outcome

- Deeply nested sub-1-MiB TOML now becomes a bounded
  `workspace.configuration` failure without truncating the fourteen-check catalog. The
  `RecursionError` catch exists only at the selected TOML snapshot parse boundary.
- Distribution-version lookup failures caused by missing metadata, `OSError`, or
  `PermissionError` leave package identity unavailable while import and doctor continue.
  Unexpected metadata defects still propagate.
- An explicit `bundlewalker.toml` beneath a linked parent now resolves the parent only and keeps
  the final config node lexical for `lstat` and no-follow opening. Linked-directory and explicit
  linked-parent starts select the same real workspace; missing, symlink, directory, and FIFO final
  nodes retain their authoritative classifications.
- `Path.cwd()` and user-home expansion `OSError`/`RuntimeError` failures are bounded discovery
  failures. The remaining checks still run, and unavailable storage lookup becomes a warning.
- Package metadata, lock metadata, public setup documentation, support/release policy, doctor
  behavior, and the historical embedded user-guide mirror agree on Python 3.13 or 3.14 through
  `requires-python = ">=3.13,<3.15"`. The package version remains `0.4.0a2`.

## TDD evidence

| Slice | RED | GREEN |
| --- | --- | --- |
| Deep TOML | A real 800-level, 1.6-KiB TOML array escaped as `RecursionError`. | All fourteen checks return; configuration fails and dependent transaction inspection is gated. |
| Linked parent | Explicit `linked-parent/bundlewalker.toml` failed configuration opening while the linked directory start passed. | Both CLI/application start forms pass against the real root; the final-node kind matrix passes. |
| Discovery lookup | A nonexistent `~user` escaped as `RuntimeError`; injected cwd failure also reached a second storage cwd lookup. | Both lookup boundaries retain all checks and safe gating. |
| Package identity | Isolated imports raised on metadata `OSError` and `PermissionError`. | Import yields an empty version, doctor reports unavailable identity, and unexpected `RuntimeError` still propagates. |
| Python support | Release metadata still declared `>=3.13`, and setup docs said 3.13 or newer. | Metadata, docs, lock, and doctor decision-table assertions agree on 3.13/3.14 only. |

## Verification

| Command | Result |
| --- | --- |
| Focused diagnostics, CLI, release, project-automation, and acceptance suites | Passed. |
| `uv sync --locked` | Passed. |
| `uv lock --check` | Passed. |
| `uv run pytest -m 'not eval' -q` | Passed. |
| `uv run ruff format --check .` | Passed; 95 files formatted. |
| `uv run ruff check .` | Passed. |
| `uv run pyright` | Passed with 0 errors, 0 warnings, and 0 informations. |
| `uv build --clear --no-sources` | Built the `0.4.0a2` wheel and source distribution. |
| `uv run twine check dist/*` | Both artifacts passed. |
| `git diff --check` | Passed. |

The closure is committed with `fix: align diagnostic runtime boundaries`. No version bump,
publication, push, pull request, merge, tag, release, or workflow change was performed.
