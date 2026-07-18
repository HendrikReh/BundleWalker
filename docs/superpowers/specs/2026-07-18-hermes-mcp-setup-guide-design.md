# Hermes Agent MCP Setup Guide Design

**Date:** 2026-07-18
**Status:** Approved for implementation

## Context

The supplied `BundleWalker-Hermes-MCP-Setup.md` records a successful local connection between
Hermes Agent and a BundleWalker OKF workspace. It contains useful operational details, but it is
not suitable for repository documentation because it embeds one user's absolute paths, provider
choice, workspace counts, and machine-specific executable location.

BundleWalker already has authoritative host-neutral MCP documentation in `docs/user-guide.md`.
The repository therefore needs a separate Hermes-specific setup guide that explains how Hermes
launches and controls BundleWalker's local MCP server without duplicating the complete BundleWalker
tool and transaction reference.

## Goal

Create a discoverable, portable guide at `docs/hermes-mcp-setup.md` that enables any Hermes Agent
user to connect one local BundleWalker workspace, choose an appropriate tool surface, configure
provider access safely, exercise read-only and review-first workflows, diagnose common failures,
and remove the integration.

## Non-goals

- General documentation for every MCP host.
- A Hermes catalog manifest or built-in Hermes preset.
- A hosted, HTTP, remote, or multi-workspace BundleWalker MCP deployment.
- Changes to BundleWalker application behavior, MCP schemas, dependencies, or console scripts.
- Copying personal workspace counts, paths, credentials, or provider assumptions into the
  repository.
- Reproducing every field from BundleWalker's canonical MCP tool reference.

## Documentation boundaries

The new guide owns Hermes-specific concerns:

- Hermes prerequisites and configuration locations;
- `hermes mcp add`, `list`, `test`, `configure`, and `remove` commands;
- the requirement that `--args` be the final `hermes mcp add` option;
- Hermes `config.yaml` structure for a local `stdio` MCP server;
- per-server tool filtering and the recommended initial allowlist;
- filtered subprocess environments and explicit provider-variable forwarding;
- `/reload-mcp`, fresh-session discovery, and Hermes-prefixed MCP tool names; and
- Hermes-oriented troubleshooting and example requests.

The existing `docs/user-guide.md` remains authoritative for:

- BundleWalker's ten tools and strict schemas;
- concept and pending-review resources;
- durable review preparation, inspection, apply, discard, staleness, and recovery;
- model-backed versus deterministic operations;
- inline-ingestion limits; and
- workspace, process, privacy, and transaction boundaries.

The Hermes guide summarizes these only as needed to make setup and safe first use coherent, then
links to the canonical sections.

## Portability model

Replace personal values with four named setup values:

| Value | Meaning | How users obtain it |
| --- | --- | --- |
| `PROJECT_ROOT` | Absolute path to the cloned BundleWalker repository containing `pyproject.toml`. | Run `pwd` from the BundleWalker checkout. |
| `WORKSPACE` | Absolute path to the initialized OKF workspace containing `bundlewalker.toml`. | Run `pwd` from the workspace root. |
| `UV_COMMAND` | Command or absolute path Hermes uses to launch `uv`. | Run `command -v uv`; use `uv` when Hermes receives an adequate `PATH`. |
| `HERMES_HOME` | Active Hermes configuration directory. | Usually `~/.hermes`; profile-specific installations may differ. |

Examples use shell variables for terminal commands and unmistakable uppercase placeholders inside
configuration snippets. No example contains a real username, mounted-volume name, API key, model
availability claim, or source workspace count.

Paths with spaces remain quoted in shell examples and separate scalar items in YAML argument
lists. The guide requires absolute `PROJECT_ROOT` and `WORKSPACE` values so Hermes does not depend
on its launch directory.

## Guide structure

The new guide uses this sequence:

1. **Purpose and trust boundary** — local `stdio`, one workspace fixed at startup, no arbitrary
   workspace or source paths in tool calls.
2. **Prerequisites** — BundleWalker v2 checkout synced with `uv`, initialized workspace, Hermes
   with MCP support, and terminal access.
3. **Record portable setup values** — obtain and validate `PROJECT_ROOT`, `WORKSPACE`,
   `UV_COMMAND`, and `HERMES_HOME` without printing secrets.
4. **Register the server** — recommended `hermes mcp add bundlewalker --command ... --args ...`
   command, with `--args` last; equivalent `mcp_servers.bundlewalker` YAML for manual review or
   editing.
5. **Test and select tools** — run `hermes mcp list`, `hermes mcp test bundlewalker`, and
   `hermes mcp configure bundlewalker`.
6. **Choose a safe tool surface** — recommend the five read-oriented tools first; explain the
   optional three prepare tools and two review-resolution tools.
7. **Configure model-backed operations** — distinguish Hermes's model from BundleWalker's
   PydanticAI model, identify deterministic tools, store secrets in the active Hermes `.env`, and
   explicitly forward only `BUNDLEWALKER_MODEL` plus the selected provider credential in the MCP
   server's `env` mapping. Include a clearly labelled OpenAI-shaped example without naming a
   current model as a default.
8. **Reload and verify discovery** — use `/reload-mcp`; start a fresh conversation when needed;
   explain the `mcp_bundlewalker_<tool>` naming pattern.
9. **Try read-only and review-first requests** — examples for status, search, cited questions,
   deterministic lint, prepare-only synthesis, pending-review inspection, and explicit
   apply/discard authorization.
10. **Troubleshoot** — executable/path failures, filtered credentials, missing tools, stale or
    occupied review slots, clean-environment launch tests, and safe CLI recovery.
11. **Security and removal** — minimal tool exposure, explicit environment forwarding, exact
    review-ID handling, privacy of accepted raw sources, `hermes mcp remove bundlewalker`, and
    reload/session reset.
12. **References** — canonical BundleWalker MCP guide and current official Hermes MCP, CLI, and
    security documentation.

## Tool-selection guidance

The initial recommended allowlist is:

- `workspace_status`
- `search_concepts`
- `ask`
- `lint`
- `get_pending_review`

This is described as read-oriented rather than fully offline: `ask` requires a configured model,
and semantic `lint` requires a model even though deterministic `lint` does not.

Users may additionally enable:

- `prepare_ingestion`
- `prepare_synthesis`
- `prepare_refresh`
- `apply_review`
- `discard_review`

The guide must not call the full ten-tool set “safe” merely because BundleWalker validates it.
Hermes tool exposure is a separate authorization choice. Preparation changes only private pending
state; apply or discard requires the exact review ID. Example prompts distinguish permission to
prepare from permission to apply.

Do not enable parallel MCP tool calls for this integration. BundleWalker has shared workspace
state and enforces one pending review, so sequential Hermes MCP calls are the conservative
documented configuration.

## Provider and environment guidance

Hermes and BundleWalker use separate model configurations. BundleWalker model-backed tools read
`BUNDLEWALKER_MODEL` unless a tool supplies its optional `model` field. The corresponding provider
credential must also reach the BundleWalker subprocess.

Hermes filters the environment of local MCP subprocesses. The guide therefore stores actual
secret values in the active Hermes `.env` and references them from `config.yaml` using
`${VARIABLE}` substitution. The MCP server entry explicitly declares only the variables needed by
BundleWalker. It never suggests printing an environment file or echoing a credential during
diagnosis.

The provider example uses:

```dotenv
BUNDLEWALKER_MODEL=openai:<current-model-id>
OPENAI_API_KEY=<your-api-key>
```

It is labelled as an example, not a default or model-availability claim. Other providers replace
the credential variable and model string according to PydanticAI and provider documentation.

## Repository integration

Create or modify only these user-documentation files during implementation:

- Create `docs/hermes-mcp-setup.md`.
- Modify `README.md` to add the Hermes guide under the local MCP or documentation navigation.
- Modify `docs/user-guide.md` to add a short Hermes-specific link from the host-neutral MCP
  section.
- Modify `docs/superpowers/plans/2026-07-16-end-user-guide.md` only to synchronize its required
  exact embedded copy of `docs/user-guide.md`.

Historical design and implementation records otherwise remain unchanged.

## Source verification

Hermes-specific behavior must be checked against current primary documentation:

- [Hermes MCP documentation](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp)
- [Hermes CLI reference](https://hermes-agent.nousresearch.com/docs/reference/cli-commands)
- [Hermes security documentation](https://hermes-agent.nousresearch.com/docs/user-guide/security)
- [Hermes configuration documentation](https://hermes-agent.nousresearch.com/docs/user-guide/configuration)

BundleWalker behavior must be checked against live `bundlewalker-mcp --help`, live
`bundlewalker review --help`, `TOOL_SPECS`, and the canonical user guide. The supplied setup notes
are evidence of a successful configuration, not an authority when they conflict with current
product documentation.

## Validation

Implementation is complete only after:

- all personal paths, usernames, workspace counts, and provider-specific assumptions are absent;
- every documented BundleWalker command matches live help;
- all ten tool names and their read/prepare/resolve grouping match `TOOL_SPECS`;
- the Hermes CLI command shape matches the current official CLI reference;
- shell and YAML examples preserve paths containing spaces;
- the embedded user guide is byte-identical to `docs/user-guide.md`;
- rendered links and heading anchors resolve in README, the new guide, user guide, and affected
  documentation;
- `git diff --check` is silent;
- the complete offline test, format, lint, type, and lockfile gates pass; and
- the pre-existing untracked backup archive remains untouched and unstaged.

## Acceptance criteria

The documentation is successful when a reader without access to the original machine can:

1. identify the four local setup values they must supply;
2. register and test BundleWalker as a Hermes MCP server;
3. choose a minimal read-oriented or explicitly write-capable tool surface;
4. understand which calls require a BundleWalker model and how to forward only needed variables;
5. reload Hermes and recognize BundleWalker's registered tool names;
6. use read-only and prepare/review/apply workflows without confusing preparation with live
   mutation;
7. diagnose path, environment, tool-discovery, and pending-review failures without exposing
   secrets; and
8. remove the integration cleanly.
