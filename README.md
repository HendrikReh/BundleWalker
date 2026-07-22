# BundleWalker

[![CI](https://github.com/HendrikReh/BundleWalker/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/HendrikReh/BundleWalker/actions/workflows/ci.yml)
[![PyPI prerelease](https://img.shields.io/pypi/v/bundlewalker?include_prereleases&label=PyPI)](https://pypi.org/project/bundlewalker/)
[![License](https://img.shields.io/badge/license-GPL--3.0--or--later%20%2B%20CC0--1.0-blue)](LICENSE-SCOPE.md)

BundleWalker is a local-first tool that turns a source bundle into a navigable knowledge workspace for people and AI agents.
It proposes review-first writes to cited, interlinked OKF Markdown while preserving the exact bytes
of every accepted source as immutable evidence.

[Tutorial](docs/tutorial.md) · [User Guide](docs/user-guide.md) ·
[Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md) ·
[Security](SECURITY.md) · [Support](SUPPORT.md) · [License](LICENSE-SCOPE.md)

## Why BundleWalker

- **Keep knowledge local.** Sources, indexing, exploration, and compiled knowledge remain ordinary
  files inside a workspace you control.
- **Review every proposed write.** Model output is validated and shown as a complete diff before
  you decide whether it becomes durable knowledge.
- **Trace answers to evidence.** Cited answers link back to the OKF Markdown concepts they read,
  while accepted source bytes stay unchanged.
- **Use the same workspace from different interfaces.** Work directly through the command-line
  interface or connect an AI agent through the local MCP server.
- **Recover safely.** Authenticated transaction state lets an accepted write finish or roll back
  after interruption without silently accepting a partial result.

## Project status

BundleWalker remains a proof of concept approaching beta; it is not a claim of production
stability or a completed beta. The latest stable release is **v3** (Python package `0.3.0`), and the
current production release candidate is `0.4.0rc2`. See the [Changelog](CHANGELOG.md) for the
immutable release history.

macOS and Linux are supported; Windows is experimental.

## Install BundleWalker

BundleWalker requires Python 3.13 or 3.14 and [`uv`](https://docs.astral.sh/uv/).

Install the exact prerelease as an isolated command-line tool:

```bash
uv tool install "bundlewalker==0.4.0rc2"
bundlewalker --help
bundlewalker-mcp --help
```

Final `0.4.0` is not published, so keep the exact prerelease version in the install command. If you
want to contribute or run from a source checkout, use the separate
[development setup](CONTRIBUTING.md#development-setup).

## Create your first workspace

Create one portable Markdown source, initialize a personal workbook, and run the offline health
check:

```bash
printf '%s\n' \
  '# Review-first knowledge' \
  '' \
  'A review gate separates a model proposal from durable knowledge.' \
  'Accepted source bytes remain immutable evidence.' \
  > example-notes.md

bundlewalker init ./my-knowledge --conventions-style personal-workbook
bundlewalker doctor ./my-knowledge
cd ./my-knowledge
```

`doctor` is deterministic, offline, and read-only. Before the first model-backed command, export
`BUNDLEWALKER_MODEL` and the provider credential required by that model. The
[provider setup guide](docs/user-guide.md#model-and-provider-setup) explains model strings,
provider-specific variables, and safe credential handling without making a provider or model
availability claim.

```bash
export BUNDLEWALKER_MODEL='<pydantic-ai-model-string>'
bundlewalker ingest ../example-notes.md
bundlewalker ask 'Why does this workspace use a review gate?'
```

`ingest` validates and displays a complete prospective diff: answer `y` to accept it or `n` to
leave live knowledge unchanged. Plain `ask` is read-only and returns a cited answer without saving
a Synthesis. Continue with the [Tutorial](docs/tutorial.md) for the complete first journey, or see
the [User Guide](docs/user-guide.md#ingest-and-review-a-source) for source rules and review outcomes.

## Choose how to use BundleWalker

### Command-line interface

The installed `bundlewalker` command is the primary interface for creating, checking, ingesting,
querying, reviewing, and protecting a workspace. Start with `bundlewalker --help`; use the
[complete CLI reference](docs/user-guide.md#complete-cli-reference) when you need options, exit
codes, limits, or recovery procedures.

### MCP server

The existing local MCP `stdio` server fixes one workspace at startup and exposes strict resources
and tools for read-only exploration, model-backed preparation, and explicit review decisions:

```text
bundlewalker-mcp --workspace /absolute/path/to/workspace
```

It is local `stdio`, not a hosted, remote, HTTP, or web-server transport. See the
[host-neutral MCP guide](docs/user-guide.md#use-bundlewalker-through-a-local-mcp-host) for its
resource and tool contract. Hermes Agent users can follow the dedicated
[Hermes MCP setup guide](docs/hermes-mcp-setup.md). Visual Studio Code users can follow the
[VS Code/Copilot MCP setup guide](docs/vscode-copilot-mcp-setup.md); the
[MCP compatibility record](docs/mcp-compatibility.md) distinguishes observed host evidence from
documented but untested combinations.

### Local web UI

A local web UI is planned, not implemented. Use the command-line interface or local MCP server
today; there is no web application or hosted service to start.

## Understand reviewed writes

Every reviewed write follows the same boundary:

```text
prepare -> deterministic validation -> complete diff -> explicit decision -> atomic commit
```

- Deterministic operations such as `init` can create known scaffolding without a model or review;
  `doctor`, `workspace status`, and plain `lint` inspect state without changing knowledge.
- Read-only operations such as plain `ask` and semantic lint may use a model, but do not prepare or
  persist knowledge writes.
- Prepare-only MCP operations validate a proposal and store at most one private pending review;
  they do not change live `raw/` or `wiki/` content.
- Applying operations revalidate the exact accepted proposal before committing it. The CLI applies
  only after your affirmative decision; MCP applies only the matching review ID. Declining or
  discarding a review leaves live knowledge unchanged.

Accepted source bytes are copied unchanged into `raw/` under content-derived names and never
rewritten. The compiled OKF Markdown in `wiki/` can evolve through later reviewed writes. Interrupted
accepted writes can complete or roll back safely, while a prepared review remains pending until it
is explicitly applied or discarded. The [review and recovery guide](docs/user-guide.md#maintain-and-recover-the-bundle)
documents duplicate no-ops, stale reviews, crash recovery, and the full decision contract.

## Operate and protect a workspace

Inspect compatibility before copying or changing a workspace, back it up outside itself, restore
only into a separate target, and request format upgrades explicitly:

```text
bundlewalker workspace status [PATH]
bundlewalker workspace backup OUTPUT [--workspace PATH]
bundlewalker workspace restore ARCHIVE TARGET
bundlewalker workspace upgrade [PATH] [--backup-dir DIRECTORY]
```

Backups can contain exact raw source bytes. Read the authoritative
[workspace compatibility and portable-backup policy](docs/workspace-compatibility.md) before a
backup, restore, upgrade, or rollback. The [reviewed performance and capacity evidence](docs/performance-and-capacity.md)
defines the measured support envelope and its exclusions.

Use `bundlewalker doctor [PATH] [--report REPORT.json]` for an offline, read-only diagnostic and an
optional redacted support report. If report creation fails after its target is created, inspect and remove
the owner-only partial target when appropriate before retrying; BundleWalker retains it to avoid deleting
an unrelated replacement installed at the same path.

## Documentation

Each active document has one canonical job:

- This README is the product landing page for maturity, platforms, installation, the shortest
  useful workflow, interface choice, reviewed-write safety, and navigation.
- The [Tutorial](docs/tutorial.md) is the reproducible personal-workbook journey from source notes
  through reviewed knowledge, refresh, health checks, backup, and restore.
- The [User Guide](docs/user-guide.md) is the canonical task, CLI, MCP, lifecycle, recovery, limits,
  and troubleshooting reference.
- The [Hermes MCP Setup Guide](docs/hermes-mcp-setup.md) covers portable Hermes-specific MCP
  registration, tool filtering, environment forwarding, verification, and removal.
- The [VS Code/Copilot MCP Setup Guide](docs/vscode-copilot-mcp-setup.md) covers workspace-scoped
  registration, secret inputs, tool selection, approvals, resources, logs, and removal.
- The [MCP Host Compatibility Record](docs/mcp-compatibility.md) publishes the tested host matrix,
  exact environment, capability evidence, and limits of each certification claim.
- The [Workspace Compatibility Policy](docs/workspace-compatibility.md) defines workspace formats,
  backup, restore, upgrade, rollback, and portability boundaries.
- [Performance and Capacity](docs/performance-and-capacity.md) publishes reviewed evidence, the
  supported-capacity statement, exclusions, profiles, and reproduction procedure.
- The [Release Procedure](docs/maintainers/releases.md) is the maintainer reference for current
  TestPyPI and production-PyPI trusted publishing and immutable release recovery.
- [Contributing](CONTRIBUTING.md) covers architecture, contributor workflow, verification,
  documentation ownership, and the historical-record policy.
- The [Security Policy](SECURITY.md) defines the supported reporting scope and private vulnerability
  route.
- The [Support Policy](SUPPORT.md) defines supported platforms, issue-reporting evidence, and the
  best-effort maintenance boundary.
- [License Scope](LICENSE-SCOPE.md) maps GPL and CC0 paths and explains how user content and generated
  workspaces are treated.
- The [Changelog](CHANGELOG.md) preserves immutable tagged history and the concise Unreleased record.

## Development

The default suite is offline and requires no model credentials:

```bash
uv run pytest -m 'not eval' -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
```

Live model-quality evaluation is explicit, opt-in, may use the network, and may incur provider
cost. See [Contributing](CONTRIBUTING.md) for architecture, setup, test layers, and change workflow.

## License

BundleWalker's application code, tests, documentation, and internal agent prompts are available
under the [GNU General Public License version 3 or later](LICENSE). The five packaged convention
presets are dedicated under [CC0 1.0 Universal](LICENSES/CC0-1.0.txt). User-provided sources and
generated knowledge remain subject to the rights in that content; processing does not make them
BundleWalker-owned. See [License Scope](LICENSE-SCOPE.md) for the exact path mapping.

Copyright (C) 2026 Hendrik Reh
