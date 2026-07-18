# BundleWalker Public Beta Roadmap Design

**Date:** 2026-07-18
**Status:** Approved
**Target:** Public beta for technical solo users

## Context

BundleWalker describes itself as a proof of concept, but its integrity-critical core is already
more mature than that label suggests. The project has extensive offline tests, durable reviewed
transactions, crash recovery, cross-process coordination, immutable accepted sources,
deterministic validation around model proposals, and a shared application facade used by the CLI
and local MCP server.

The remaining proof-of-concept gaps are primarily productization gaps. Users cannot yet install a
published package without cloning the repository. Supported platforms are not continuously
verified. Releases are not built and published by an automated, reproducible pipeline. Workspace
compatibility, backup, restore, upgrade, rollback, diagnostics, security reporting, performance
limits, and support expectations are not yet expressed as public and tested contracts.

The next milestone is therefore a reliability-first public beta rather than a capability or
architecture expansion.

## Goal

Make BundleWalker a credible public beta for technical solo users while preserving its local,
single-user, review-first design.

The beta must demonstrate that users can independently install, configure, operate, diagnose,
upgrade, recover, and integrate BundleWalker using only public documentation. The beta label is
earned by satisfying measurable exit criteria rather than by changing release terminology.

## Product promise

The public beta supports:

- local, single-user operation;
- the CLI and a workspace-bound local MCP `stdio` server;
- macOS and Linux as officially supported platforms;
- Windows as an explicitly experimental platform;
- Python 3.13 and 3.14, subject to a passing supported-platform CI matrix;
- one regular UTF-8 Markdown or text source per ingestion;
- the existing configured source-size limit;
- human review before every knowledge-base mutation;
- immutable accepted source evidence; and
- durable recovery from interrupted operations.

The existing application-level guarantees remain central product guarantees:

- Models propose changes; deterministic application code validates them.
- Review precedes mutation.
- A declined or invalid proposal leaves the knowledge base unchanged.
- Accepted raw sources remain immutable.
- CLI and MCP behavior share the same application boundary and transaction model.

## Non-goals

The following are outside the first public beta:

- a local web UI;
- a hosted service or remote MCP transport;
- multi-user synchronization;
- PDF, image, audio, URL, or OCR ingestion;
- embeddings or a vector database;
- a plugin SDK;
- automatic Git operations; and
- autonomous writes that bypass human review.

These boundaries limit operational and compatibility risk while beta feedback establishes which
capabilities users actually need. The local web UI remains the first planned product-surface
expansion after the beta foundation. Hosted and multi-user operation would require a separate
architecture decision.

## Considered delivery strategies

### 1. Reliability-first foundation (selected)

Build continuous integration, packaging, lifecycle safety, diagnostics, MCP compatibility
evidence, benchmarks, and user validation before expanding the product surface.

This sequence addresses the current maturity gap directly and minimizes risk to the transaction
core. It produces a narrower beta with stronger promises.

### 2. MCP-first expansion

Prioritize compatibility with additional MCP hosts before packaging and operational hardening.

This would improve integration visibility quickly, but host testing would still depend on a
repository checkout and weak installation, upgrade, and support contracts.

### 3. UX-first expansion

Build the local web UI immediately and use it to attract pilot users.

This would make the project easier to demonstrate, but it would enlarge the failure surface before
installation, lifecycle, release, and diagnostics foundations are dependable.

## Delivery order

The primary dependency order is:

1. continuous integration and project health;
2. packaging and reproducible releases;
3. workspace lifecycle and data safety;
4. diagnostics and supportability;
5. MCP compatibility validation;
6. performance and capacity evidence; and
7. external beta validation.

Documentation, governance, and security-policy work may proceed alongside the earlier stages when
they do not depend on unfinished product behavior.

## Workstream 1: Continuous integration and project health

Add required macOS and Linux jobs for Python 3.13 and 3.14. Keep a visible Windows job, but make
its experimental status explicit and do not let an expected Windows-only failure misrepresent the
official support contract.

Every supported job must run the complete offline test suite and the existing formatting, linting,
type-checking, and lockfile gates. Release-oriented jobs must also build the wheel and source
distribution, install from the built artifact in a clean environment, and smoke-test the CLI and
MCP entry points.

Add automated dependency and security scanning. Protect the release branch with the required
supported-platform checks so a local success cannot substitute for the public support matrix.

## Workstream 2: Packaging and releases

Complete the Python package metadata, including maintainers, project URLs, classifiers, supported
Python versions, and useful discovery keywords.

Publish to TestPyPI before the first production publication. Use a trusted publishing identity
instead of storing a long-lived PyPI API token. Build the distribution once for a release, verify
it, and promote those exact artifacts. Attach the wheel and source distribution to the GitHub
release and publish the same artifacts to PyPI.

Document the regular release, urgent patch, failed publication, and rollback procedures. Keep one
authoritative package version and verify that the tag, package metadata, runtime version, and
release notes agree before publication.

Historical `v1`, `v2`, and `v3` releases remain intact. Their documentation and licenses describe
the artifacts that were released at those points in time; they must not be deleted or rewritten to
look like later releases.

## Workstream 3: Workspace lifecycle and data safety

Define the compatibility policy for workspace configuration, durable reviews, and transaction
formats. Document which versions are readable, writable, migratable, or unsupported.

When a format changes, provide an explicit forward migration or reject the workspace with an
actionable message. Preserve representative fixtures from released versions and run them in CI.
Compatibility tests must cover inspection, normal operation where supported, migration, and clear
rejection of formats that cannot be handled safely.

Document and test backup, restore, upgrade, rollback, and post-upgrade verification. Exercise
recovery after abrupt termination at integrity-critical transaction stages on every officially
supported operating system.

## Workstream 4: Diagnostics and supportability

Add a `bundlewalker doctor` command backed by a focused diagnostics service. It must inspect:

- Python and BundleWalker versions;
- workspace discovery, structure, and permissions;
- configuration and selected model;
- presence, but never values, of required provider credentials;
- pending or interrupted transactions;
- MCP launch prerequisites;
- writable storage; and
- available disk space where it can be checked portably.

Results use stable categories and explain the next user action. A separate, explicit support-report
operation may serialize redacted diagnostics. It must not include credentials, accepted raw source
content, generated knowledge content, or unnecessary absolute paths by default.

## Workstream 5: MCP compatibility

Keep Hermes as a documented reference host and add at least one independent MCP host. For each
host, test tool discovery, read operations, proposal creation, review acceptance, review decline,
restart with a durable pending review, and transaction recovery.

Publish the tested host, MCP SDK, and protocol-version ranges. Distinguish MCP protocol failures
from configuration, model-provider, validation, review-conflict, and transaction failures so hosts
can provide actionable feedback.

Track MCP evolution, but do not couple stable BundleWalker releases to proposals that have not yet
become supported protocol requirements. Compatibility claims must be based on repeatable tests.

## Workstream 6: Performance and maintainability

Create synthetic benchmark workspaces at several documented sizes. Measure initialization, search,
lint, ingestion preparation, commit, MCP startup, and any recovery paths whose cost grows with the
workspace.

Publish the measured environment and a practical capacity envelope. The beta does not claim
unlimited scale. Once a baseline exists, CI should identify material regressions while allowing for
normal runner variation.

`src/bundlewalker/transactions.py` is a maintainability hotspot, but the beta must not begin with a
broad transaction rewrite. Extract locking, manifests, durable review persistence, commit, or
recovery responsibilities only when a beta workstream needs a clearer seam. Add characterization
tests before moving behavior and preserve the existing end-to-end transaction tests.

## Workstream 7: External beta validation

Recruit three to five technical solo users. Give them the public installation and user
documentation rather than private setup assistance.

The pilot workflow covers:

1. package installation;
2. model-provider configuration;
3. workspace initialization;
4. ingestion and review;
5. query and lint operations;
6. MCP setup;
7. backup and restore; and
8. diagnosis of at least one documented failure scenario.

Convert observed failures and user reports into a public, prioritized issue backlog. Do not use the
pilot as a reason to add unrelated major features before recurring setup, safety, and usability
friction is understood.

## Architecture

The beta preserves the modular monolith. BundleWalker remains one Python distribution with CLI and
MCP adapters, a shared `WorkspaceApplication` use-case boundary, deterministic validation around
model proposals, and transaction services controlling mutation. Ordinary OKF workspace files
remain the durable data format.

New beta capabilities should be focused services rather than adapter-specific implementations:

- a diagnostics service returning structured, redacted results;
- a compatibility service inspecting versions and coordinating migrations;
- a backup service creating and verifying recoverable snapshots;
- a capability report describing the installed version, supported formats, limits, and interfaces;
  and
- a benchmark harness operating on synthetic fixtures outside normal user workflows.

CLI and MCP may format service results differently, but they must not duplicate the underlying
rules. The future local web UI will call the same application facade directly rather than routing
through MCP.

No beta workstream introduces a database, background daemon, hosted control plane, or alternate
mutation path.

## Privacy and observability

The beta retains a strict local-first posture:

- no automatic telemetry;
- no remote crash reporting;
- no credential values in logs, diagnostics, or reports;
- no raw source or generated knowledge content in reports by default;
- no diagnostic upload without a separate explicit user action; and
- manual or explicitly user-submitted pilot feedback.

External model providers receive only the workflow context described in the product documentation.
The beta-hardening work must not silently broaden that disclosure boundary.

Use stable error categories for configuration, workspace compatibility, model/provider,
validation, review conflict, transaction/recovery, MCP protocol, and internal defects. User-facing
messages explain the next action. Detailed diagnostics go to stderr or an explicitly requested
local report; MCP responses retain machine-readable categories.

## Milestones

### Milestone A: Build and release foundation

Exit evidence:

- required macOS and Linux CI is green on Python 3.13 and 3.14;
- experimental Windows results are visible and correctly labeled;
- the wheel and source distribution build successfully;
- built artifacts pass clean-install smoke tests;
- package metadata and governance documents are complete; and
- TestPyPI publication succeeds through trusted publishing.

### Milestone B: Operational safety

Exit evidence:

- the compatibility and migration policy is published;
- historical workspace fixtures pass;
- backup, restore, upgrade, and interrupted-operation tests pass;
- `bundlewalker doctor` covers the defined failure scenarios;
- diagnostic reports are redacted and opt-in; and
- the performance baseline and capacity envelope are published.

### Milestone C: Integration candidate

Exit evidence:

- Hermes and a second MCP host pass the compatibility workflow;
- CLI and MCP expose consistent application behavior and error categories;
- installation and MCP setup work from published artifacts;
- no known critical or high-severity data-safety defects remain; and
- public beta documentation is complete.

### Milestone D: Public beta

Exit evidence:

- three to five external users complete the core pilot workflow using public documentation;
- reported blockers are fixed or explicitly documented;
- the public issue backlog is prioritized;
- release and rollback rehearsals succeed; and
- every public beta exit criterion is satisfied.

## Risk controls

| Risk | Control |
|---|---|
| Filesystem and process differences | Supported-platform CI and recovery tests |
| Workspace corruption | Transactions, historical fixtures, verified backups, and migrations |
| Model nondeterminism | Deterministic validation and focused live-model evaluations |
| MCP specification changes | Explicit compatibility matrix and supported version ranges |
| Credential or content leakage | Local-only diagnostics, redaction, and no automatic telemetry |
| Refactoring regressions | Characterization tests and incremental extraction |
| Expanding support burden | Narrow beta scope and explicit experimental Windows status |

## Versioning

Keep the historical `v1`, `v2`, and `v3` tags unchanged. Adopt package-aligned tags for subsequent
releases, such as `v0.4.0`, `v0.4.1`, and `v0.5.0`. This allows patch and prerelease tags to map
unambiguously to Python package versions.

Use `0.4.0` as the likely public-beta version only if all beta gates pass. Use versions such as
`0.4.0a1` or `0.4.0rc1` to exercise the publishing and upgrade paths before the final beta release.
Do not create the final `v0.4.0` tag merely because implementation has started.

Keep the package below `1.0.0` until the project can make and maintain long-term CLI, MCP, and
workspace compatibility commitments.

## Public beta exit criteria

BundleWalker may replace the proof-of-concept label with public beta when all of the following are
true:

1. Every supported operating-system and Python combination passes tests, formatting, linting,
   type checking, packaging, and artifact smoke installation in CI.
2. Users can install BundleWalker from PyPI without cloning the repository.
3. Clean installation, upgrade, backup, restore, and rollback procedures are tested and documented.
4. Workspace, configuration, durable-review, and transaction compatibility rules are documented.
5. `bundlewalker doctor` diagnoses the agreed configuration, provider, workspace, permission, MCP,
   and recovery scenarios without exposing credentials or content.
6. Hermes and at least one additional MCP host pass the documented compatibility workflow.
7. Realistic performance benchmarks and supported workspace limits are published.
8. At least three external technical users complete the core pilot workflow without private
   developer intervention.
9. There are no known critical or high-severity defects involving data loss, workspace corruption,
   credential exposure, or review bypass.
10. Security reporting, support boundaries, and release-maintenance policies are public.

## References

- [GitHub Actions: Building and testing Python](https://docs.github.com/en/actions/tutorials/build-and-test-code/python)
- [Python Packaging User Guide: Build and publish](https://packaging.python.org/en/latest/guides/section-build-and-publish/)
- [Python Packaging User Guide: Tool recommendations](https://packaging.python.org/en/latest/guides/tool-recommendations/)
- [OpenSSF Best Practices Badge](https://www.bestpractices.dev/)
- [Model Context Protocol specifications and proposals](https://modelcontextprotocol.io/specification/)
