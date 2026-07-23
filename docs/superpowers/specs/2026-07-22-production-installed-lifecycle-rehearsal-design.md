# Production-Installed Lifecycle Rehearsal Design

**Date:** 2026-07-22

**Milestone:** Public-beta release gate

**Target artifact:** BundleWalker `0.4.0rc2` from production PyPI, with later `0.4.0rcN`
release candidates supported by the same gate

## Context

BundleWalker `0.4.0rc2` is published on production PyPI and has passed the package publication,
checksum, and clean-install checks in the protected release workflow. The repository also has
source-based and artifact-smoke coverage for workspace status, diagnostics, backup, restore,
current-format upgrade behavior, rollback primitives, and abrupt transaction recovery.

Those checks do not yet prove that an independently installed production artifact can complete the
full workspace lifecycle expected of a public-beta user. The Visual Studio Code and GitHub Copilot
MCP certification similarly used the current source checkout, so the installed MCP entry point
remains outside the recorded compatibility evidence.

The release procedure therefore names a production-installed workspace lifecycle rehearsal as the
next gate before external beta validation. It must cover inspection, backup, separate-target
restore, current-format upgrade behavior, rollback, post-operation verification, and installed MCP
startup on every supported platform and Python combination.

## Goal

Add a reproducible, manually dispatched GitHub Actions gate that installs one exact BundleWalker
`0.4.0rcN` version exclusively from production PyPI and proves the supported lifecycle through
black-box CLI and MCP behavior on:

- Ubuntu 24.04 with Python 3.13;
- Ubuntu 24.04 with Python 3.14;
- macOS 15 with Python 3.13; and
- macOS 15 with Python 3.14.

The gate must preserve sanitized machine-readable evidence for every matrix job, including failed
jobs, and support a later checked-in result summary without treating workflow implementation as
proof that the rehearsal passed.

## Non-goals

This work does not:

- publish, rebuild, replace, yank, tag, or release a package;
- bump the BundleWalker package version unless the rehearsal exposes a published-package defect;
- certify Windows, which remains experimental;
- exercise remote models, providers, credentials, semantic quality, or network-dependent MCP
  tools;
- perform a real workspace-format migration, because production currently registers no migration
  and format `1` is current;
- modify or inspect a maintainer's real workspace;
- make the local web UI part of the public-beta gate; or
- claim final `0.4.0` beta readiness before external validation and the remaining exit criteria.

## Considered approaches

### 1. Black-box Python harness with a supported-platform workflow

A small rehearsal harness invokes the installed executables through subprocesses, independently
checks filesystem and archive digests, and writes structured evidence. A manual workflow creates
an isolated environment and runs the harness across the supported matrix.

This is the selected approach. It keeps lifecycle assertions readable, provides consistent
behavior across macOS and Linux, and prevents the source checkout from being mistaken for the
installed artifact.

### 2. Shell-only workflow

Embedding the complete rehearsal in workflow shell blocks would reduce the number of repository
files. It would also duplicate cross-platform path, subprocess, hashing, JSON, redaction, and
failure-handling logic in a format that is difficult to test locally. This approach is rejected.

### 3. Pytest against the installed distribution

Pytest provides strong assertions but makes it easier for the repository checkout or editable
environment to shadow the production wheel. It would also require installing test-only project
dependencies in the evidence environment. This approach is rejected for the production gate;
ordinary repository tests remain appropriate for unit and contract coverage of the harness.

## Architecture

The gate has three focused parts:

1. `.github/workflows/rehearse-production-lifecycle.yml` owns dispatch validation, the four-job
   matrix, isolated production-PyPI installation, harness invocation, and unconditional artifact
   upload.
2. `scripts/rehearse_production_lifecycle.py` owns black-box lifecycle orchestration, independent
   verification, sanitization, evidence creation, and its final exit status.
3. Maintainer documentation owns dispatch instructions, result interpretation, immutable-release
   failure policy, and the durable record added after a successful live run.

The harness is standard-library-first and must never import `bundlewalker`. For the MCP handshake
it may run a short child program with the isolated environment's installed `mcp` dependency. That
child imports the MCP client library, not BundleWalker, and launches the installed
`bundlewalker-mcp` executable over local `stdio`.

## Workflow contract

The workflow is manually dispatched and accepts one required `version` input. The input must match
the full regular expression `0\.4\.0rc[1-9][0-9]*`; whitespace, shell syntax, final versions,
alphas, other package lines, and normalized alternatives are rejected before installation.

The workflow has read-only repository permissions and no environment, publishing permission,
secret, provider credential, or model configuration. It checks out the repository only to obtain
the reviewed harness. The package environment is created in runner-temporary storage outside the
checkout.

Each matrix job must:

1. select the declared Python version;
2. create an isolated virtual environment under runner-temporary storage;
3. disable user-site imports and remove `PYTHONPATH` from the harness environment;
4. install exactly `bundlewalker==<version>` and its dependencies using production PyPI as the
   sole package index;
5. record the resolved distribution version and installed CLI/MCP executable paths;
6. change the working directory to runner-temporary storage before invoking the harness;
7. copy the harness into that storage rather than running it with the checkout as the current
   directory;
8. write evidence to a platform- and Python-specific directory; and
9. upload that evidence with an unconditional `if: always()` step.

The job succeeds only when installation, metadata validation, every lifecycle phase, the MCP
handshake, and evidence finalization succeed. Ordinary PR CI validates the workflow and harness
contracts but does not contact production PyPI or claim a live rehearsal result.

## Rehearsal lifecycle

All paths are created under one disposable run root. The harness uses the installed `bundlewalker`
and `bundlewalker-mcp` entry points and performs the following phases in order.

### 1. Installed-artifact identity

The harness records the requested version, `importlib.metadata.version("bundlewalker")`, Python
version, operating system, machine architecture, executable paths, and a UTC timestamp. The
installed distribution version must exactly equal the requested input. The CLI and MCP entry
points must resolve inside the isolated environment rather than the repository checkout or a user
installation.

### 2. Workspace initialization and inspection

The installed CLI initializes `original/` with the default convention style. The harness then
runs:

```text
bundlewalker workspace status original
bundlewalker doctor original --report evidence/original-doctor.json
```

Both commands must exit successfully. Status must identify workspace format `1` as current,
readable, and writable. The opt-in doctor report must be created and remain safe to preserve as
evidence.

The harness computes a deterministic SHA-256 identity for the portable backup surface:
`bundlewalker.toml`, `conventions.md`, `raw/`, and `wiki/`, including their explicit empty
directories. The identity includes normalized relative paths, file kinds, and file bytes in sorted
order. It refuses symlinks and excludes transient private state under `.bundlewalker/`, matching
the documented portable-backup boundary.

### 3. Backup verification

The installed CLI creates `archives/original.zip`. The command must print a 64-character lowercase
SHA-256 digest. The harness independently hashes the completed archive and requires equality with
the printed value. It records the archive size and digest.

### 4. Separate-target restore

The installed CLI restores the verified archive into new path `restored/`. The restore command's
printed archive digest must match the backup digest. The restored portable-tree identity must
match the original identity exactly.

The harness runs status and doctor with explicit `restored/` paths, then runs deterministic
`bundlewalker lint` with `restored/` as its working directory. Each command must succeed.

### 5. Current-format upgrade behavior

The installed CLI runs:

```text
bundlewalker workspace upgrade original --backup-dir upgrade-backups
```

Because production format `1` is current and has no registered migration, the command must report
that the workspace is already current, create no backup archive, and leave the original portable
tree byte-identical. This phase proves present release behavior without claiming a real migration
rehearsal.

Synthetic migration and failed-upgrade tests remain the evidence for backup-before-mutation and
rollback orchestration until a real production migration exists.

### 6. Rollback rehearsal

Rollback is represented by restoring the already verified pre-operation archive into a second new
path, `rollback/`. The harness never restores over `original/` or `restored/`. It requires the
rollback target's portable-tree identity to match the original, runs status and doctor with the
rollback path, and runs deterministic `bundlewalker lint` from the rollback working directory.

The original workspace remains present and unchanged until all rollback verification finishes.

### 7. Installed MCP startup

The isolated environment starts its installed `bundlewalker-mcp` entry point bound to
`rollback/`. A local MCP client performs initialization and tool discovery over `stdio`. The server
must expose exactly the documented ten tools:

- `workspace_status`;
- `search_concepts`;
- `ask`;
- `lint`;
- `get_pending_review`;
- `prepare_ingestion`;
- `prepare_synthesis`;
- `prepare_refresh`;
- `apply_review`; and
- `discard_review`.

The rehearsal does not call provider-backed tools. It closes the installed-entry-point and schema
discovery gap without making model-quality or provider-availability claims. The client terminates
the server cleanly within a bounded timeout.

### 8. Final invariants

At the end of the run:

- `original/`, `restored/`, and `rollback/` have the same portable-tree identity;
- the verified backup still exists with the same bytes and digest;
- no upgrade backup exists for the current-format no-op;
- every status, deterministic lint, and doctor command succeeded;
- every doctor report exists;
- MCP initialization and exact ten-tool discovery succeeded; and
- no path outside the disposable run root was modified by the harness.

## Evidence model

Each matrix job writes one top-level `evidence.json` plus sanitized copies of the explicit doctor
reports. The evidence document uses a versioned schema and contains:

- schema version;
- overall result and failure category;
- requested and installed BundleWalker versions;
- Python, operating-system, architecture, and UTC timing metadata;
- sanitized CLI and MCP executable paths;
- ordered phase results;
- sanitized command arguments, exit codes, bounded stdout/stderr, and elapsed durations;
- original, restored, and rollback portable-tree digests;
- backup archive digest and byte size;
- upgrade no-op assertions;
- discovered MCP tool names; and
- final invariant results.

Sanitization replaces the disposable absolute run root with `$RUN_ROOT` before evidence is written.
The same recursive string replacement is applied to the JSON doctor reports before their artifact
copies are preserved; the raw temporary reports are not uploaded. The harness uses only generated
workspace content and never captures environment variables. Command output is bounded before
serialization so unexpected diagnostics cannot create unbounded artifacts.

The evidence writer runs from a `finally` boundary. If a prerequisite fails, later dependent phases
are recorded as skipped with a reason, completed phase evidence is retained, and the harness exits
nonzero only after finalizing `evidence.json`.

GitHub artifact names include the requested version, runner operating system, and Python version.
Artifact retention follows repository policy. After all four jobs pass, a separate reviewed commit
adds a durable Markdown summary with the workflow URL, source commit, exact package version,
environments, artifact names, archive digests, and result table. The live result summary, not the
workflow implementation commit, closes this gate.

## Failure policy

The rehearsal cannot mutate an immutable published version. Failures are handled by origin:

- A harness or workflow defect is fixed through an ordinary reviewed pull request. The same
  published release candidate may then be rehearsed again because its bytes did not change.
- A BundleWalker package defect is fixed through review, the version advances to the next
  `0.4.0rcN`, and the complete protected publication and lifecycle rehearsal run again. The old
  version and tag remain unchanged.
- A macOS or Linux failure blocks the public-beta gate until resolved or the support policy changes
  through an explicit reviewed decision.
- An unavailable or altered production-PyPI artifact is treated as a release incident and handled
  under the existing production release procedure rather than bypassed with a local wheel.

The workflow must never rebuild from the checkout, fall back to TestPyPI, add another index, or
install a local path after a production installation failure.

## Testing strategy

Implementation follows test-driven development.

Focused harness tests cover:

- exact release-candidate input validation;
- deterministic portable-tree hashing and symlink refusal;
- subprocess result capture, output bounds, and run-root sanitization;
- archive-digest parsing and independent verification;
- phase pass, failure, and dependent-skip recording;
- evidence finalization after a command failure;
- installed executable containment checks;
- exact MCP tool-set comparison; and
- final invariant evaluation.

Static automation tests cover:

- manual dispatch with the required version input;
- the exact four supported matrix entries;
- read-only permissions and absence of a publishing environment;
- production-PyPI-only installation;
- source-isolation environment settings;
- invocation from runner-temporary storage;
- unconditional evidence upload; and
- absence of Windows from the certification matrix.

A local integration test may exercise the harness against the development environment for
orchestration confidence, but it cannot satisfy the production-installed gate. Only the manually
dispatched workflow against production PyPI creates release evidence.

Before merge, the ordinary non-evaluation suite, formatting, linting, type checking, workflow
contract tests, and local Markdown link validation must pass. After merge, dispatch the workflow
from `master` with `version=0.4.0rc2` and inspect all evidence artifacts before recording success.

## Documentation changes

The implementation updates:

- `docs/maintainers/releases.md` with dispatch, interpretation, evidence, and failure procedures;
- `docs/workspace-compatibility.md` with the boundary between current-format no-op evidence and a
  future real migration rehearsal;
- `docs/mcp-compatibility.md` after the live run to record installed-entry-point startup and tool
  discovery without broadening the prior VS Code host claim;
- `CHANGELOG.md` with the new release-gate automation and, separately, the successful evidence
  record; and
- project automation tests so these contracts cannot silently disappear.

The documentation continues to describe BundleWalker as a proof of concept approaching beta until
every public-beta exit criterion, including external validation, is complete.

## Delivery sequence

1. Land this approved design specification.
2. Write and approve a task-level implementation plan.
3. Implement the harness, workflow, tests, and pre-run documentation through review.
4. Merge the gate to `master` without claiming successful lifecycle evidence.
5. Manually dispatch the workflow for production `0.4.0rc2`.
6. Inspect every matrix result and downloaded evidence artifact.
7. If all four jobs pass, add the durable result summary and update compatibility/release
   documentation through a second reviewed commit or pull request.
8. Advance to external beta validation only after that evidence record is merged.

## Acceptance criteria

The gate implementation is complete when:

1. the workflow accepts only an exact `0.4.0rcN` input and runs only the four supported
   platform/Python combinations;
2. every job installs exclusively from production PyPI in an isolated environment;
3. the harness never imports BundleWalker from the checkout;
4. inspection, backup, independent digest verification, separate-target restore, current-format
   upgrade no-op, rollback restore, and post-operation checks are proven through installed CLI
   behavior;
5. installed MCP initialization exposes exactly the documented ten tools without provider calls;
6. sanitized, bounded evidence is uploaded even for failed jobs;
7. tests enforce workflow, isolation, evidence, and lifecycle contracts;
8. maintainer documentation explains dispatch and immutable-version failure handling; and
9. no documentation claims the live gate passed before all four production-PyPI jobs and their
   artifacts have been independently inspected.

The live rehearsal gate is complete only after a checked-in evidence summary records four passing
jobs for the exact production release candidate.
