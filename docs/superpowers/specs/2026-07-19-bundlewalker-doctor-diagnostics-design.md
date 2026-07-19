# BundleWalker Doctor Diagnostics Design

**Date:** 2026-07-19
**Status:** Approved design
**Milestone:** Public-beta Milestone B2 — diagnostics and supportability

## Goal

Add an offline, read-only `bundlewalker doctor` command that can diagnose installation,
workspace, configuration, transaction, MCP, and storage problems from any directory. The command
must explain the next safe user action, return an automation-friendly exit status, and optionally
write a versioned JSON support report that is redacted by construction.

This completes the diagnostics portion of the public-beta operational-safety milestone. It does
not repair state, contact a model provider, expose diagnostics through MCP, or broaden the
supported-platform contract.

## Context

BundleWalker already has three boundaries that this feature should preserve:

- Typer in `src/bundlewalker/interfaces/cli.py` is a delivery adapter rather than the owner of
  application behavior.
- `WorkspaceApplication` and `LifecycleApplication` expose adapter-neutral use cases with strict
  Pydantic contracts and safe public errors.
- Transaction entry points deliberately recover interrupted work and may create private lock
  state. They are correct for normal operations but unsuitable for a byte-for-byte read-only
  diagnostic.

The public-beta roadmap requires diagnostics for the Python and BundleWalker versions, workspace
discovery and permissions, configuration and selected model, provider-credential presence,
pending or interrupted transactions, MCP launch prerequisites, writable storage, and available
disk space. It also requires stable categories, actionable next steps, opt-in report generation,
and strong privacy boundaries.

## Decisions

The approved design makes these decisions:

1. Add a focused `DiagnosticsApplication` instead of extending lifecycle behavior or putting
   diagnostic orchestration in Typer.
2. Run `doctor` from any directory and accept an optional workspace path.
3. Continue independent checks after a failure so one run provides a useful support picture.
4. Use three severities: `pass`, `warning`, and `failure`.
5. Return exit code `0` for pass or warning-only results and exit code `1` when any check fails.
6. Keep diagnosis strictly offline and read-only. There is no repair mode.
7. Write a report only when the user explicitly supplies `--report REPORT.json`.
8. Use a versioned JSON report and refuse to overwrite existing files or follow report symlinks.
9. Build terminal output and JSON from the same bounded, safe contracts rather than redacting an
   unrestricted object after collection.
10. Recognize the documented OpenAI credential mapping only. Unknown provider prefixes warn
    instead of guessing secret-variable names.

## Non-goals

This work does not add:

- `--fix`, automatic transaction recovery, configuration edits, or workspace creation;
- provider API calls, network reachability checks, telemetry, or remote crash reporting;
- a diagnostic MCP tool or resource;
- official Windows support;
- arbitrary PydanticAI provider credential inference;
- performance benchmarks, workspace capacity guarantees, or operation-specific space estimates;
- local web UI behavior;
- a package-version bump, TestPyPI publication, tag, or release.

## Architecture

### Application service

Add a synchronous, adapter-neutral `DiagnosticsApplication`. Its public operation is conceptually:

```python
DiagnosticsApplication(dependencies).run(start: Path | None = None) -> DiagnosticResult
```

The service coordinates focused inspectors and converts every expected environmental or
filesystem problem into one bounded check. It does not throw merely because a workspace cannot be
found: workspace discovery is itself a diagnostic. Unexpected internal programming errors remain
exceptions and are translated through the existing safe CLI boundary without relaying exception
text.

Dependencies are injectable and include:

- environment-variable access as a `Mapping[str, str]`;
- BundleWalker, Python, and platform identity;
- current UTC time;
- executable lookup;
- import/package availability lookup;
- permission inspection;
- portable disk-usage inspection; and
- the read-only workspace and transaction inspectors.

Production defaults use the current process and standard-library APIs. Tests provide deterministic
fakes, so ordinary verification remains offline, credential-free, and independent of the host
machine.

### Delivery adapter

Add `doctor` as a top-level Typer command:

```text
bundlewalker doctor [PATH] [--report REPORT.json]
```

The CLI callback must not eagerly discover a workspace before invoking `doctor`. The command
creates the application, renders its ordered checks and summary, optionally writes the report, and
selects the exit status. It does not contain diagnostic policy.

### Application contracts

Add strict, immutable Pydantic contracts at the application boundary:

- `DiagnosticSeverity`: `pass`, `warning`, or `failure`;
- `DiagnosticCategory`: `runtime`, `workspace`, `configuration`, `transactions`, `mcp`, or
  `storage`;
- `DiagnosticCheck`: stable code, category, severity, safe summary, and an ordered tuple of safe
  remediation instructions;
- `DiagnosticCounts`: nonnegative pass, warning, and failure totals;
- `DiagnosticResult`: overall severity, runtime identity, counts, and ordered checks; and
- `SupportReport`: report schema version, generation time, the safe result, and no destination
  path.

All models forbid extra fields. Check codes and severity values are compatibility-sensitive public
data. Human-readable wording may improve while retaining the meaning of each code.

## Safe-by-construction data model

Diagnostic contracts may contain only bounded diagnostic vocabulary and deliberately selected
runtime facts. They never contain:

- environment-variable values, including `BUNDLEWALKER_MODEL`;
- credential values, prefixes, suffixes, lengths, or hashes;
- raw source text, accepted knowledge, generated concepts, review diffs, or staged transaction
  content;
- transaction or review identifiers;
- absolute or relative filesystem paths, current directory, workspace name, username, hostname,
  or report destination;
- raw exception text, exception representations, provider payloads, or tracebacks.

The report serializer performs no search-and-replace redaction. A value that is not permitted
never enters `DiagnosticResult` or `SupportReport`. This makes terminal and JSON privacy behavior
identical and prevents adapter drift.

The selected model is represented only as “configured” or “not configured,” its configuration
source, and a recognized provider family such as `openai`. The raw model identifier is excluded
because environment values are caller-controlled and may accidentally contain sensitive data.

## Check catalog

Checks run in the following stable order. Every run includes one result for every code. A check
whose prerequisite failed becomes a warning explaining that it was not run; the prerequisite's
failure remains the overall blocking signal.

| Code | Category | Purpose and severity policy |
|---|---|---|
| `runtime.bundlewalker` | runtime | Pass when the installed BundleWalker version is available; fail when package identity cannot be established. |
| `runtime.python` | runtime | Pass for Python 3.13 or 3.14; fail for every other version. |
| `runtime.platform` | runtime | Pass for macOS or Linux; warn for experimental Windows or any unsupported platform. |
| `workspace.discovery` | workspace | Pass when a non-symlink `bundlewalker.toml` is found from `PATH` or the current directory; fail when discovery is absent or unsafe. |
| `workspace.configuration` | workspace | Pass when the bounded TOML configuration parses and validates; fail when invalid; warn as skipped if discovery failed. |
| `workspace.compatibility` | workspace | Pass for current format; fail for too-new, unsupported, or otherwise unusable formats; warn as skipped when configuration is unavailable. An upgradeable but currently non-writable format fails and names the explicit upgrade command. |
| `workspace.structure` | workspace | Pass when configured directories and files have the expected regular-file/directory topology without linked components; fail on missing, linked, or wrong-kind entries; warn as skipped when the workspace is unavailable. |
| `workspace.permissions` | workspace | Pass when required managed paths are readable and writable according to a non-mutating permission inspection; fail otherwise; warn as skipped when the workspace is unavailable. |
| `configuration.model` | configuration | Pass when a nonblank model is selected through `BUNDLEWALKER_MODEL`; warn when absent or blank. Never emit the value. |
| `configuration.credential` | configuration | For recognized OpenAI models, pass when `OPENAI_API_KEY` is nonblank and warn when absent. Warn when no model is selected or a provider mapping is unknown. Never emit the variable value. |
| `transactions.state` | transactions | Pass when no transaction state exists; warn for one valid pending review or a concurrently busy workspace; fail for interrupted, malformed, linked, or ambiguous state; warn as skipped when the workspace is unavailable. |
| `mcp.package` | mcp | Pass when the installed MCP dependency is importable; fail when unavailable or inconsistent. No module is executed. |
| `mcp.entrypoint` | mcp | Pass when the `bundlewalker-mcp` console entry point is installed and discoverable; fail otherwise. No server process is started. |
| `storage.disk` | storage | Pass when portable free-space inspection succeeds with at least 1 GiB free; warn below 1 GiB or when space cannot be inspected. This check never claims an operation will fit. |

The overall severity is `failure` if any check fails, otherwise `warning` if any check warns,
otherwise `pass`. `DiagnosticCounts` must exactly match the check tuple.

## Inspector behavior

### Runtime and MCP

Runtime checks use injected values rather than shelling out. Python support is exactly 3.13 and
3.14. Platform matching is based on stable system identifiers: Darwin and Linux are supported,
Windows is experimental, and all other values are unsupported warnings.

MCP checks inspect installed metadata, module availability, registered console entry points, and
executable lookup. They do not import and execute the server, open stdio, bind a transport, read a
host configuration, or contact a model provider.

### Workspace discovery and structure

The optional `PATH` follows the existing workspace-discovery semantics: a file begins discovery
from its parent, and a directory is searched together with its parents. Diagnostic discovery must
differentiate “not found” from an unsafe symlinked configuration without placing either path in
the result.

After bounded configuration parsing and compatibility inspection, the structure inspector checks
only expected topology and metadata:

- the workspace root is a real directory;
- `bundlewalker.toml` and the configured conventions path are regular, non-symlink files;
- configured wiki and raw paths are real directories with no symlinked component; and
- required paths can be inspected without following links outside the workspace.

It does not scan or parse accepted OKF documents, read conventions content, or read raw-source
content. Permission checks use metadata and access inspection only; they do not create a probe
file or directory. This is a useful indicator rather than a race-free promise about a future
write, and the wording must not claim otherwise.

### Model and credential presence

Model resolution for diagnostics is limited to `BUNDLEWALKER_MODEL`; `doctor` has no `--model`
override because it diagnoses the environment that ordinary MCP and CLI processes will inherit.
A blank value is equivalent to absence.

Provider recognition examines a bounded, normalized prefix without retaining the complete model
string. The first implementation recognizes the documented `openai:` family and checks only
whether `OPENAI_API_KEY` is present and nonblank. It does not reveal the variable's value or any
derived information about it. Unknown providers warn that local credential verification is not
available and direct the user to the provider documentation.

Credential absence is a warning rather than a failure because deterministic BundleWalker
operations remain supported without a model provider.

### Read-only transaction inspection

Add a focused read-only inspection API next to transaction internals. It returns a small internal
state classification to `DiagnosticsApplication` and never exposes filesystem paths, identifiers,
or content.

The inspector:

- does not call `recover_transactions`, `get_pending_review`, or another recovery-triggering API;
- never creates `.bundlewalker`, `transactions`, or `transaction.lock`;
- never writes, deletes, renames, fsyncs, or repairs any entry;
- does not read raw payloads, prospective wiki files, backup trees, accepted knowledge, or review
  diffs;
- reads only directory topology, bounded manifest data, transaction phase, and the minimum review
  metadata needed to distinguish a durable pending review;
- refuses symlinked or wrong-kind private state;
- treats multiple pending reviews or mixed ambiguous phases as a failure; and
- reports a known interrupted phase as a failure with a normal recovery-triggering command.

If an existing regular transaction lock is held, the inspector does not block and does not create
a replacement lock. It returns a warning that the workspace is busy and asks the user to rerun
`doctor` after the active operation. If no lock exists, inspection proceeds without creating one.
Any concurrent snapshot inconsistency becomes a bounded busy warning or malformed-state failure,
never raw exception output.

A valid pending review is an advisory warning, not corruption. Its remediation lists:

```text
bundlewalker review show
bundlewalker review apply <REVIEW_ID>
bundlewalker review discard <REVIEW_ID>
```

The real identifier remains available through `review show`; it is not copied into diagnostics or
the support report.

### Disk space

Disk usage is inspected with a portable standard-library API against the workspace filesystem when
available, otherwise against the invocation filesystem. The inspected path is not retained. Free
space below 1 GiB warns. Failure to obtain disk usage also warns. The check never fails solely on
a capacity heuristic and never predicts whether backup, ingestion, or transaction staging will
fit; those claims require the later measured-capacity workstream.

## CLI presentation

Each check renders to stdout with one stable severity token, code, and safe summary:

```text
PASS runtime.python — Python 3.13 is supported.
WARN configuration.model — No agent model is configured.
FAIL workspace.discovery — No BundleWalker workspace was found.
  Next: run `bundlewalker init PATH` or pass an existing workspace to `bundlewalker doctor PATH`.
```

Remediation lines are ordered and use fixed placeholders rather than discovered paths or
identifiers. The command ends with a deterministic summary:

```text
Doctor: 8 passed, 4 warnings, 2 failures.
```

Pass and warning-only results exit `0`. Any diagnostic failure exits `1`. Typer syntax errors and
invalid arguments retain exit code `2`.

## Support report

`--report REPORT.json` is explicit opt-in output. A report has:

- schema version `1`;
- an injected UTC generation timestamp;
- BundleWalker, Python, and normalized platform identity;
- overall severity and exact counts; and
- the same ordered checks and remediation instructions shown in the terminal.

The output is canonical UTF-8 JSON with a trailing newline. The report does not contain its own
destination. Parent directories must already exist. The writer opens a new regular file without
following symlinks and refuses an existing path rather than overwriting it. On platforms that
support POSIX modes, the new file uses owner-only permissions. If any write, `fchmod`, `fsync`, or
close operation fails after creation, the writer retains the owner-only partial target. Portable
macOS and Linux pathname APIs cannot atomically prove that a path still names the created inode;
automatic cleanup could delete an unrelated replacement. The user must inspect and remove the
newly created report target when appropriate before retrying.

An existing target, symlink, directory, or otherwise invalid report target is an invalid-input
error and exits `2`. An I/O failure while fulfilling a valid report request is an operational
failure and exits `1`. Both use bounded stderr messages without the target path or underlying
exception text. A successful diagnostic report may be mentioned in stdout as written, but the
destination itself is not echoed.

Plain `doctor` performs no writes. `doctor --report` writes only the user-authorized report and
still performs no workspace mutation.

## Error handling

Expected check problems are values, not exceptions. An inspector converts known operating-system,
configuration, compatibility, and transaction problems into the corresponding stable check.
Dependent checks continue as explicit prerequisite warnings.

Unexpected defects are translated through a new bounded diagnostic application error or the
existing safe error vocabulary. The CLI never prints exception representations or tracebacks.
Report-target validation distinguishes invalid input from an operational write failure so exit
codes remain consistent with the existing CLI contract.

## Security and privacy

The feature preserves BundleWalker's local-first disclosure boundary:

- no network call or telemetry is possible from the diagnostics service;
- no secret value is retained, logged, rendered, serialized, hashed, or measured;
- no workspace content or transaction content enters diagnostic contracts;
- no filesystem identity enters terminal or report data;
- no diagnostic automatically repairs or recovers state; and
- report creation is explicit, exclusive, and outside the workspace unless the user deliberately
  chooses a path there.

Tests must include adversarial environment values and exceptions containing recognizable secret,
path, hostname, model, provider, review, and content markers. Neither terminal output nor JSON may
contain those markers.

## Testing strategy

Implementation is test-first and remains offline.

### Contract and application tests

- Validate every contract's strict schema, severity vocabulary, ordering, count invariants, and
  JSON round trip.
- Inject each supported and unsupported Python/platform combination.
- Exercise workspace discovery absent, unsafe, current, upgradeable, too-new, malformed, and
  permission-limited states.
- Exercise model absent, blank, recognized OpenAI, missing OpenAI credential, present OpenAI
  credential, and unknown provider states without exposing values.
- Exercise MCP package and entry-point presence independently.
- Exercise disk inspection with sufficient, low, and unavailable capacity.
- Verify independent checks continue after failures and prerequisites become explicit warnings.

### Transaction inspection tests

- Cover absent private state, a valid pending review, every recoverable interrupted phase,
  malformed manifests, multiple pending reviews, mixed phases, symlinked entries, wrong-kind
  entries, busy-lock behavior, and concurrent snapshot changes.
- Snapshot names, types, modes, sizes, digests, and contents before and after diagnosis to prove
  byte-for-byte and topology-level non-mutation.
- Assert that raw payload, prospective wiki, backup tree, accepted knowledge, and review diff files
  are never opened by the diagnostic path.

### CLI and report tests

- Run from outside a workspace and with an explicit workspace path.
- Verify stable line ordering, remediation placeholders, pluralized summary counts, and exit codes.
- Verify warning-only exit `0` and any failure exit `1`.
- Validate the report against its versioned Pydantic schema.
- Refuse existing files, symlinks, directories, and missing parents without overwriting anything.
- Verify owner-only partial-target retention for simulated write, `fchmod`, `fsync`, and close
  failures, including a regression that proves an unrelated replacement is never deleted.
- Assert no workspace mutation for plain `doctor` and no mutation beyond the authorized report for
  `doctor --report`.
- Feed secret values, private paths, hostnames, raw content, review identifiers, and exception
  payloads into fakes and assert their absence from stdout, stderr, and JSON.

### Project verification

The final gate runs:

```text
uv sync --locked
uv lock --check
uv run pytest -m 'not eval' -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv build --clear --no-sources
uv run twine check dist/*
git diff --check
```

Built wheel and source-distribution smoke tests must continue to find both `bundlewalker` and
`bundlewalker-mcp` entry points. No live-model evaluation is required.

## Documentation changes

Update:

- `README.md` with command discovery and one short invocation;
- `docs/user-guide.md` with the complete command, check, exit, report, recovery, and privacy
  contract;
- `SUPPORT.md` with guidance to attach the opt-in redacted JSON report to public issues while still
  reviewing it before upload;
- `SECURITY.md` if needed to state that even redacted reports do not belong in public issues when
  they concern a suspected security vulnerability; and
- `CHANGELOG.md` under `Unreleased`.

Documentation must not claim provider reachability, successful authentication, operation-specific
capacity, Windows support, repair capability, or zero disclosure risk.

## Acceptance criteria

The feature is complete when:

1. `bundlewalker doctor [PATH]` runs from any directory and returns all stable checks in order.
2. Pass and warning-only results exit `0`; any diagnostic failure exits `1`.
3. `--report` writes schema-version-1 JSON only to a new, explicit target and never overwrites or
   follows an existing path.
4. Plain diagnosis is offline and leaves the inspected workspace byte-for-byte and
   topology-for-topology unchanged.
5. Report generation changes only the explicitly authorized output file.
6. The service checks every runtime, workspace, configuration, transaction, MCP, and storage item
   required by the public-beta roadmap.
7. Every check provides a safe, actionable next step when user action is needed.
8. No terminal or report output contains credential values, model values, content, filesystem
   identities, transaction/review identifiers, exception text, or provider payloads.
9. macOS and Linux pass the supported CI matrix; Windows remains visible and experimental.
10. All offline tests, formatting, linting, strict typing, packaging, and artifact checks pass.

## Delivery boundary

Land the design, implementation plan, production code, tests, and documentation through a
protected pull request. Do not create a new package version, tag, TestPyPI publication, GitHub
release, or production PyPI publication as part of this feature. Exercise the diagnostic command
from the next meaningful prerelease rather than creating a release solely for this change.
