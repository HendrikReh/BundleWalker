# Whole-Branch Final-Fix Report

Accepted review head: `885713d9a09b3bb7260f4fa2b239c0aea2d320b7`

This pass addresses all four Important and all four Minor findings from
`.superpowers/sdd/whole-branch-review.md`. It does not assess merge readiness; the final reviewer
must re-review the resulting branch.

## Finding map

| Finding | Implementation | Regression coverage |
| --- | --- | --- |
| Important 1 — authenticate the raw destination before acceptance | `src/bundlewalker/transactions.py` adds a no-mutation pending raw-destination verifier. Pending status and apply accept only absence or a regular non-symlink file with the expected digest. Apply revalidates immediately before the accepted marker. A destination conflict does not advance the phase, and discard skips only this live-destination compatibility check while retaining all journal/topology authentication. | `tests/test_transactions.py`: `test_pending_status_rejects_conflicting_raw_destination_and_allows_discard`, `test_pending_status_rejects_raw_destination_symlink_and_allows_discard`, `test_apply_revalidates_raw_destination_changed_after_status_before_acceptance`, and `test_exact_preexisting_raw_destination_is_compatible_with_pending_apply`. |
| Important 2 — schema-v2 prepared recovery fails closed | `src/bundlewalker/transactions.py` routes every schema-v2 `prepared` manifest through `_validate_pending_topology`; it can no longer fall through to legacy cleanup. A missing/substituted prospective tree, fixed or quarantined backup, symlink, or other invalid directory shape raises while retaining the journal. Schema-v1 prepared cleanup remains unchanged. | `tests/test_transactions.py`: `test_schema_v2_pending_recovery_rejects_missing_prospective_and_retains_journal`, `test_schema_v2_pending_recovery_rejects_unexpected_backup_and_retains_journal`, and the existing schema-v1 cleanup test. The old schema-v2 prepared-plus-backup cleanup expectation was narrowed to `raw-persisted`, where recovery remains valid. |
| Important 3 — public errors safe by construction | `src/bundlewalker/application/errors.py` removes denylist-based pass-through. Each error category now uses a fixed fallback; review IDs are included only from the validated typed field; usability is retained only through exact/prefix-safe messages that never relay interpolated fields. Arbitrary provider/model, filesystem, credential, JSON, and plaintext exception prose cannot cross the application boundary. | `tests/application/test_contracts.py` adds relative raw/wiki/transaction paths, separator-free `token private-token`, plaintext/non-JSON provider bodies, and retains all absolute path/credential/payload cases. `tests/interfaces/test_mcp_tools.py::test_bundlewalker_error_details_do_not_cross_the_mcp_adapter` proves the same values do not cross MCP text or structured results. |
| Important 4 — refresh validation ordering | `src/bundlewalker/application/facade.py` validates empty and oversized instructions first, removes the redundant facade pending preflight, and delegates target validation followed by the pending gate to `answer_synthesis_refresh`. Provider/model resolution remains after both input/target validation and the pending gate. | `tests/application/test_facade.py::test_refresh_validation_precedes_pending_review_through_facade`, `tests/cli/test_ask.py::test_ask_refresh_validation_precedes_pending_review_through_cli`, and `tests/interfaces/test_mcp_tools.py::test_refresh_validation_precedes_pending_review_through_mcp` cover empty, oversized, missing target, and wrong target type with a pending review and zero runner/model-resolution calls. Existing workflow ordering tests remain green. |
| Minor 1 — real concurrent preparation | No production change was needed; the existing `fcntl` workspace lock and under-lock pending recheck satisfy the invariant. | `tests/test_transactions.py::test_simultaneous_public_preparations_create_exactly_one_review` uses a spawn-based two-process barrier and public `prepare_transaction`. It observes one durable review, one `ReviewPendingError` referencing that review, and one transaction directory. |
| Minor 2 — registered console stdio session | No production change was needed; the registered script already targets `bundlewalker.interfaces.mcp:main`. | `tests/interfaces/test_mcp_stdio.py::test_registered_console_entrypoint_binds_workspace_without_protocol_noise` launches a real MCP client through `uv run --project PROJECT_ROOT bundlewalker-mcp`, not module invocation. |
| Minor 3 — bounded subprocess sessions and clean stderr | No production change was needed. | Every async stdio protocol session in `tests/interfaces/test_mcp_stdio.py` is inside `anyio.fail_after(15)`. Explicit-workspace, CWD-discovery, deterministic lint/resource, and restart sessions all assert captured stderr is empty. |
| Minor 4 — direct `jsonschema` dependency | `pyproject.toml` declares `jsonschema>=4.26,<5`; `uv.lock` records it as a direct requirement. MCP remains `>=1.28.1,<2`, resolved to `1.28.1`; jsonschema resolves to `4.26.0`. | `tests/interfaces/test_mcp_stdio.py::test_mcp_runtime_dependencies_are_direct_and_bounded` checks both direct bounds and resolved versions/majors. |

## RED and GREEN evidence

### Transaction and recovery behavior

- RED: `uv run pytest tests/test_transactions.py -q`
  - Four expected failures:
    - missing schema-v2 prospective tree did not raise;
    - conflicting live raw destination was not rejected by status;
    - raw-destination symlink was not rejected by status; and
    - a status-to-apply destination race advanced the manifest from `prepared` to `accepted`.
- Coverage-only additions that already passed at the accepted head:
  - the barrier-controlled multiprocess test proved the existing public lock invariant; and
  - exact preexisting raw bytes were already compatible.
- GREEN: `uv run pytest tests/test_transactions.py tests/test_acceptance.py -q` exited 0.
- Focused Ruff and strict Pyright checks for transaction source/tests exited 0.

### Public errors and refresh ordering

- RED: `uv run pytest tests/application/test_contracts.py tests/application/test_facade.py tests/cli/test_ask.py tests/interfaces/test_mcp_tools.py -q -k 'never_relays or validation_precedes or error_details_do_not_cross'`
  - Twenty expected failures across relative path/provider/credential leakage, facade ordering,
    CLI ordering, MCP target ordering, and MCP adapter redaction.
  - MCP empty/oversized cases were already rejected by the strict tool schema and therefore passed
    immediately; facade and CLI still failed until their ordering was fixed.
- GREEN: the same focused selection passed all 22 selected cases.
- GREEN: `uv run pytest tests/application tests/cli/test_ask.py tests/interfaces/test_mcp_tools.py tests/workflows/test_ask.py -q` exited 0 after updating superseded pass-through expectations.
- The first broad interface/application/transaction/CLI/workflow run exposed two compatibility
  regressions: fixed `source_sha256` validation guidance and fixed model-selection guidance were
  hidden by category fallbacks. Both are now exact code-owned allowlist entries with no
  interpolated data; the repeated broad run exited 0.

### Stdio and dependency behavior

- RED: `uv run pytest tests/interfaces/test_mcp_stdio.py::test_mcp_runtime_dependencies_are_direct_and_bounded -q`
  - Failed because `jsonschema>=4.26,<5` was absent from direct project dependencies.
- GREEN: `uv run pytest tests/interfaces/test_mcp_stdio.py -q` reported `8 passed`.
- `uv lock --check`, focused Ruff, and focused strict Pyright exited 0.
- The console-session, timeout, and additional stderr checks are coverage hardening for behavior
  that already worked; they did not require production transport changes.

## Final verification

All commands were run from the isolated worktree after the final implementation commit:

- `uv run pytest tests/interfaces tests/application tests/test_transactions.py tests/test_acceptance.py tests/cli tests/workflows -q` — exit 0.
- `uv run pytest -m 'not eval' -q` — exit 0, 100% progress.
- `uv run pytest --collect-only -m 'not eval' -o addopts='' -q` — `652/657 tests collected (5 deselected)`.
- `uv run ruff format --check .` — `74 files already formatted`.
- `uv run ruff check .` — `All checks passed!`.
- `uv run pyright` — `0 errors, 0 warnings, 0 informations`.
- `uv lock --check` — resolved/validated 114 packages.
- `git diff --check` — exit 0.
- `git diff 885713d9a09b3bb7260f4fa2b239c0aea2d320b7..HEAD --check` — exit 0.
- `uv run bundlewalker --help` — exit 0.
- `uv run bundlewalker review --help` — exit 0.
- `uv run bundlewalker-mcp --help` — exit 0.

Documentation files were not changed, so embedded-guide equality and relative-link checks were not
applicable to this pass.

## Commits

- `db711bb` — `fix: fail closed before accepting reviews`
- `c086152` — `fix: close public errors and validate refresh inputs`
- `54210ea` — `test: harden MCP stdio sessions`
- `2b7fcbb` — `fix: retain safe CLI error guidance`

## Complete-diff and private-data review

The full range from the accepted review head through the implementation commits contains 11 changed
files, with no remote transport, local web UI, unrelated behavior, or documentation changes. A
secret/credential pattern scan found only deliberately synthetic adversarial test strings such as
`private-token`, `/tmp/secret`, and `private plaintext body`; no real credentials, private source
content, or environment values are present. Production output includes only fixed code-owned
messages and a regex-validated 32-character lowercase review ID.

## Residual concerns

- No known implementation blocker remains from the eight findings.
- The new multiprocess test uses the platform's `spawn` context and a bounded barrier/join so it
  exercises real cross-process locking without relying on fork-only state.
- Raw-destination compatibility is intentionally identity-based (regular file plus the authenticated
  SHA-256 digest), matching the transaction manifest and staged payload identity. External actors
  that do not honor BundleWalker's workspace lock can always mutate filesystem state after a check;
  the implementation revalidates at pending status and again immediately before the durable
  acceptance marker, and the existing accepted-state recovery remains fail closed.
- Final merge readiness is intentionally left to the requested final re-review.
