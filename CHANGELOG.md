# Changelog

All notable BundleWalker releases are recorded here.

## [Unreleased]

### Added

- Added the offline, read-only `bundlewalker doctor` health check with stable remediation,
  automation-friendly exit behavior, and explicit redacted JSON support reports.

### Changed

- Clarified that post-creation report failures retain the owner-only partial support-report target
  so automatic pathname cleanup cannot delete an unrelated replacement.
- Hardened TestPyPI post-upload verification with six bounded exponential installation attempts
  while preserving permanent failures and immutable-version safety.

## [v0.4.0a2] - 2026-07-19

### Added

- Added required macOS/Linux CI for Python 3.13 and 3.14 plus visible experimental Windows jobs.
- Added verified wheel and source-distribution builds, artifact installation smoke tests,
  dependency auditing, CodeQL, and Dependabot.
- Added public security and support policies, complete package metadata, and an OIDC-only
  TestPyPI publishing rehearsal.
- Added workspace status with explicit compatibility, readability, writability, and upgrade
  availability reporting, without creating state for unsupported future formats.
- Added verified workspace backup and restore commands with archive integrity checks and safe
  lifecycle boundaries.
- Added historical compatibility fixtures for clean, pending-review, future-format, invalid, and
  interrupted-workspace states.
- Added abrupt-termination recovery evidence for prepared, accepted, raw-persisted, swapping, and
  new-live transaction phases, including idempotent second recovery.

### Changed

- Adopted package-aligned versioning through the public-beta release-foundation rehearsal.
- Made installed distribution metadata the runtime package-version source.
- Made workspace upgrades explicitly backup-first, with rollback safety and clear handling for
  current, unsupported, and failed upgrade states.

## [v3] - 2026-07-18

### Added

- Licensed BundleWalker's application code, tests, documentation, and internal prompts under
  GPL-3.0-or-later.
- Dedicated the five convention preset resources under CC0-1.0 so their copied scaffolding does
  not restrict generated workspaces.
- Added path-specific license documentation, PEP 639 distribution metadata, official-text
  fingerprint checks, and repository-wide GPL source-header enforcement.

### Changed

- Published the first explicitly licensed BundleWalker release as Python package `0.3.0` without
  changing CLI or MCP behavior.

## [v2] - 2026-07-18

### Added

- Added a local MCP `stdio` server that exposes one workspace through bounded resources and ten
  strict tools.
- Added separate MCP prepare, inspect, apply, and discard operations for review-first writes.
- Added coarse MCP progress reporting and cancellation support for model-backed operations.

### Changed

- Routed CLI and MCP delivery through one workspace-bound application facade with serializable
  contracts and bounded public errors.
- Made prepared reviews durable across CLI and MCP process restarts while preserving one pending
  review per workspace.
- Expanded the user and contributor documentation for MCP setup, review recovery, and adapter
  boundaries.

### Security

- Hardened transaction compatibility checks, authenticated recovery, raw-source link accounting,
  and fail-closed handling of ambiguous post-commit states.
- Kept MCP workspace selection at process startup and prohibited MCP tool inputs from accepting
  local workspace or source paths.

## [v1] - 2026-07-16

- Initial local, review-first CLI release.
- Added immutable raw-source ingestion, deterministic proposal validation, complete review diffs,
  cited questions, saved and refreshed Syntheses, offline lint, and recoverable transactions.
- Added configurable conventions and presets for personal, agent, software, and research knowledge
  workspaces.

[Unreleased]: https://github.com/HendrikReh/BundleWalker/compare/v0.4.0a2...HEAD
[v3]: https://github.com/HendrikReh/BundleWalker/compare/v2...v3
[v0.4.0a2]: https://github.com/HendrikReh/BundleWalker/compare/v3...v0.4.0a2
[v2]: https://github.com/HendrikReh/BundleWalker/compare/v1...v2
[v1]: https://github.com/HendrikReh/BundleWalker/tree/v1
