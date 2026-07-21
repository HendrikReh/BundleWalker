# BundleWalker Documentation Refresh Design

**Date:** 2026-07-21
**Status:** Approved

## Context

BundleWalker has substantial documentation for installation, workspace creation, local MCP use,
reviewed writes, compatibility, performance, releases, project governance, and the Hermes Agent
integration. The active documentation is useful but has grown incrementally, so responsibilities
overlap across the README, tutorial, user guide, and specialist pages. Release-candidate details,
project maturity, platform support, terminology, and next-step navigation also need a consistent
presentation.

The repository contains 97 Markdown files, but not all of them are current project documentation.
Historical designs and implementation plans, benchmark evidence, agent prompts, convention
presets, and test fixtures are records or product inputs. Rewriting those files would damage
provenance or test intent rather than improve the user experience.

The refresh therefore targets active public and maintainer documentation. It optimizes first for
new users evaluating and installing BundleWalker, while preserving clear routes to comprehensive
operational and maintainer reference material.

## Goals

- Give a newcomer a predictable path from product evaluation to a successful first workflow.
- Assign each active document one primary responsibility and one canonical home for detailed
  information.
- Explain BundleWalker's proof-of-concept maturity, release status, and platform support clearly
  and consistently.
- Make installation and workflow examples portable, accurate, and safe.
- Preserve detailed reference material while reducing duplicated onboarding content.
- Improve navigation among user, integration, operational, governance, and maintainer material.
- Verify documentation claims against the current package metadata, CLI, MCP surface, release
  process, and repository checks.

## Non-goals

- Do not introduce a documentation generator, hosted documentation portal, or publishing
  workflow.
- Do not change application behavior, package metadata, CLI or MCP schemas, workspace formats,
  or release automation solely to match documentation.
- Do not rewrite historical specifications, implementation plans, release records, benchmark
  evidence, prompts, presets, or test fixtures.
- Do not make the host-neutral user guide Hermes-specific or generalize the dedicated Hermes
  guide to other MCP hosts.
- Do not claim that BundleWalker has reached final beta or production stability.
- Do not certify Windows; it remains experimental.

## Considered Approaches

### Consistency pass

Correct stale versions, terminology, links, duplicated instructions, and formatting without
changing the existing document roles. This is low risk, but it preserves the navigation and
content overlap that make the current documentation harder for newcomers to follow. This
approach is rejected as insufficient.

### Layered documentation redesign — selected

Retain the existing files and substantial content, but give each active document an explicit
role. Make the README the concise entry point, the tutorial the guided first journey, the user
guide the canonical operational reference, and specialist pages the home of integration or
operational detail. Add consistent terminology, cross-links, status language, prerequisites,
troubleshooting, and next steps.

This provides the largest usability improvement without adding documentation infrastructure or
discarding the project's existing reference material.

### Full documentation portal

Reorganize the content around a generated documentation website with site navigation and a new
page taxonomy. This could be valuable later, but it would add tooling, deployment, and
maintenance costs before the current content architecture is mature. This approach is deferred.

## Information Architecture

The active documentation follows this progression:

```text
README
├── Tutorial — first successful BundleWalker workflow
├── User guide — complete usage and command reference
│   ├── Workspace compatibility
│   └── Performance and capacity
├── Hermes MCP setup — integration-specific instructions
└── Project documentation
    ├── Contributing
    ├── Releases
    ├── Security and support
    ├── License scope
    └── Changelog
```

### README

`README.md` is the primary landing page. It explains what BundleWalker is, who it is for, why it
is useful, its maturity, supported platforms, installation choices, and the shortest meaningful
workflow. It introduces the MCP server and local web UI as next-step surfaces without duplicating
their complete reference material. A documentation map directs readers to the appropriate depth.

### Tutorial

`docs/tutorial.md` teaches through one reproducible end-to-end scenario. It contains the context,
commands, expected outcomes, safety checkpoints, and next steps required for a first success. It
does not become a second exhaustive command reference.

### User guide

`docs/user-guide.md` is the canonical operational reference for CLI usage, workspaces, MCP tools,
reviewed writes, recovery, and troubleshooting. Short onboarding summaries may remain where they
help orientation, but detailed duplicated tutorials are reduced or linked to their canonical
home.

### Specialist documentation

- `docs/hermes-mcp-setup.md` owns Hermes-specific setup and operating guidance while linking to
  the host-neutral MCP reference.
- `docs/workspace-compatibility.md` owns platform and workspace compatibility expectations.
- `docs/performance-and-capacity.md` owns measured capacity boundaries and practical scaling
  guidance.
- `docs/maintainers/releases.md` owns the current TestPyPI and production-PyPI release process.

### Governance and project records

`CONTRIBUTING.md`, `SECURITY.md`, `SUPPORT.md`, `LICENSE-SCOPE.md`, the code of conduct if present,
and `CHANGELOG.md` remain top-level governance or release documents. They receive focused
accuracy, consistency, and navigation improvements without being folded into the user guide.

Historical plans and specifications remain unchanged and are not presented as current operating
instructions.

## Content and Terminology Rules

### Product description

Use one concise description throughout active documentation: BundleWalker is a local-first tool
that turns a source bundle into a navigable knowledge workspace for people and AI agents. Pages
may adapt the surrounding explanation to their audience, but must not introduce conflicting
product categories or guarantees.

### Maturity and releases

- State clearly that BundleWalker remains a proof of concept approaching beta.
- Distinguish the latest stable release from the current release candidate.
- Label version-pinned commands so readers know whether they install stable or prerelease code.
- Avoid treating publication of a release candidate as completion of the beta milestone.
- Keep release-sensitive facts in as few canonical locations as practical and link to them from
  summaries.

### Platform support

Present macOS and Linux as officially supported. Label Windows experimental wherever platform
support affects installation, compatibility, testing, or troubleshooting. Do not imply that an
experimental CI lane is equivalent to support certification.

### Domain terminology

Use these terms consistently: source bundle, workspace, indexing, exploration, reviewed writes,
MCP server, and local web UI. Define each term on first use when the audience may be new to the
project. Prefer task-oriented headings such as “Create a workspace” and “Connect Hermes” over
headings based only on component names.

### Safety and portability

- Explain relevant safety boundaries before commands that can modify a workspace.
- Preserve the distinction between preparing a reviewed write and explicitly applying it.
- Replace personal usernames, absolute paths, workspace names, credentials, and machine-specific
  assumptions with portable placeholders or discovery commands.
- Quote paths where spaces are possible and state when an absolute path is required.
- Keep Hermes-specific terminology and configuration in the Hermes guide.
- Never place secrets in examples, command output, or troubleshooting instructions.

### Duplication and navigation

Each subject has one canonical detailed explanation. Other pages may contain a short contextual
summary followed by a direct link. Major active documents receive relevant prerequisites,
troubleshooting, related-documentation, or next-step links so readers do not reach dead ends.

## Planned File Changes

### Primary user documentation

- Rewrite `README.md` as the concise product and documentation entry point.
- Tighten `docs/tutorial.md` into a reproducible newcomer journey with explicit expected outcomes
  and next steps.
- Reorganize `docs/user-guide.md` as the canonical usage and command reference, reducing duplicated
  onboarding material.
- Retain `docs/hermes-mcp-setup.md` as Hermes-specific guidance while removing any remaining
  assumptions tied to one machine, provider, or knowledge base.
- Clarify `docs/workspace-compatibility.md` and `docs/performance-and-capacity.md` around support,
  limits, upgrade expectations, evidence, and practical operating guidance.

### Maintainer and governance documentation

- Align `docs/maintainers/releases.md` with the current TestPyPI and production-PyPI trusted
  publishing process and immutable version rules.
- Review `CONTRIBUTING.md`, `SECURITY.md`, `SUPPORT.md`, `LICENSE-SCOPE.md`, the code of conduct if
  present, and `CHANGELOG.md` for current status, terminology, navigation, and non-historical
  release information.
- Apply targeted fixes to another active Markdown file only when it is demonstrably part of the
  public or maintainer documentation set.

### Preserved files

Do not modify:

- `docs/superpowers/specs/` or `docs/superpowers/plans/`, except for the new design and later
  implementation-plan records required by this process;
- benchmark evidence and generated reports;
- agent prompt and convention-preset Markdown;
- test fixtures; or
- dated or versioned records that accurately describe their historical state.

## Verification Strategy

### Structural verification

- Check every relative Markdown link and local heading anchor in the affected active documents.
- Check heading hierarchy, fenced code blocks, tables, and navigation in rendered Markdown.
- Confirm every major active document has a clear purpose and appropriate next-step links.
- Confirm historical and fixture Markdown remains untouched.

### Accuracy verification

- Compare documented commands and options with live `bundlewalker --help`, relevant subcommand
  help, and `bundlewalker-mcp --help`.
- Compare package names, Python requirements, entry points, and current version claims with
  `pyproject.toml` and installed metadata.
- Compare MCP tool names and reviewed-write behavior with the current implementation and canonical
  schemas.
- Compare platform statements with the supported CI policy and compatibility documentation.
- Compare release instructions with the current workflows and trusted-publishing configuration
  encoded in the repository.

### Consistency verification

Search the active documentation for:

- stale package versions and superseded release-candidate references;
- conflicting proof-of-concept, beta, stable, or production claims;
- unsupported Windows claims;
- personal or machine-specific paths and usernames;
- obsolete command names or options;
- inconsistent domain terms; and
- links to historical plans presented as current instructions.

### Repository verification

Run `git diff --check`, documentation-specific checks if present, and the normal offline test,
format, lint, type, and lockfile gates where practical. A documentation-only failure must be
resolved; an unrelated pre-existing failure must be reported with evidence and not hidden by
changing the requested scope.

## Acceptance Criteria

The refresh is successful when:

1. a newcomer can determine what BundleWalker does, its maturity, supported platforms, and the
   appropriate installation path from the README;
2. the newcomer can complete the tutorial without relying on unstated machine-specific context;
3. users can locate authoritative CLI, MCP, reviewed-write, compatibility, performance, and
   troubleshooting guidance without guessing which page is canonical;
4. Hermes users can configure the integration without personal paths, credentials, or
   knowledge-base assumptions;
5. stable and prerelease instructions are clearly distinguished and consistent with current
   package metadata;
6. macOS and Linux support and experimental Windows status are stated consistently;
7. active documents use consistent product and domain terminology with working navigation;
8. all documented commands and public interfaces match the current implementation;
9. historical plans, specifications, evidence, prompts, presets, and fixtures retain their
   original content; and
10. the defined structural, accuracy, consistency, and repository checks pass or any unrelated
    pre-existing limitation is explicitly documented.
