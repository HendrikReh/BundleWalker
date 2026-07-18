# Changelog

All notable BundleWalker releases are recorded here.

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

[v2]: https://github.com/HendrikReh/BundleWalker/compare/v1...v2
[v1]: https://github.com/HendrikReh/BundleWalker/tree/v1
