# BundleWalker Documentation Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework BundleWalker's active documentation into an accurate newcomer-first path while preserving detailed reference material and immutable historical records.

**Architecture:** Keep the existing Markdown files, but give each one a single canonical role: README as landing page, tutorial as first journey, user guide as operational reference, specialist pages for integration and operating boundaries, and top-level policy files for governance. Replace the current byte-for-byte coupling between the live user guide and a historical plan with validation of active-document links, anchors, release claims, and product contracts.

**Tech Stack:** CommonMark/GitHub Markdown, Python 3.13/3.14, `markdown-it-py`, Pytest, `uv`, Ruff, Pyright, Typer CLI help.

## Global Constraints

- Optimize first for new users evaluating and installing BundleWalker, with clear routes to comprehensive operational and maintainer reference material.
- BundleWalker remains a proof of concept approaching beta; do not claim final beta or production stability.
- macOS and Linux are officially supported; Windows is experimental.
- Distinguish latest stable release `v3` / package `0.3.0` from production release candidate `0.4.0rc2`.
- Use the canonical description: “BundleWalker is a local-first tool that turns a source bundle into a navigable knowledge workspace for people and AI agents.”
- Preserve the terms source bundle, workspace, indexing, exploration, reviewed writes, MCP server, and local web UI consistently.
- The local MCP `stdio` server exists; the local web UI remains planned and unimplemented.
- Keep Hermes-specific configuration in `docs/hermes-mcp-setup.md`; keep `docs/user-guide.md` host-neutral.
- Never include personal usernames, absolute machine paths, real credentials, private workspace names, or provider/model availability claims.
- Do not alter tagged changelog entries, historical specifications or plans, benchmark evidence, prompts, presets, or test fixtures.
- Do not introduce a documentation generator, hosted documentation site, or publishing workflow.
- Preserve every exact phrase and measured claim enforced by `tests/test_release_metadata.py` unless the corresponding product contract has changed.
- Each task ends with focused verification and one intentional commit; never push during task execution unless separately requested.

---

## File Responsibility Map

| File | Responsibility after this plan |
| --- | --- |
| `README.md` | Product landing page, maturity, supported platforms, installation, shortest useful workflow, interface choice, safety summary, and documentation map. |
| `docs/tutorial.md` | Reproducible personal-workbook journey from sources through reviewed knowledge, refresh, health check, and backup. |
| `docs/user-guide.md` | Canonical task, CLI, MCP, lifecycle, recovery, limits, and troubleshooting reference. |
| `docs/hermes-mcp-setup.md` | Portable Hermes-specific MCP registration, tool filtering, environment forwarding, verification, and removal. |
| `docs/workspace-compatibility.md` | Workspace format, backup/restore/upgrade/rollback contract and portability boundary. |
| `docs/performance-and-capacity.md` | Reviewed evidence, the single supported-capacity sentence, exclusions, profiles, and reproduction. |
| `docs/maintainers/releases.md` | Current TestPyPI and production-PyPI trusted-publishing procedure and immutable release recovery. |
| `CONTRIBUTING.md` | Architecture, contributor workflow, verification, documentation ownership, and historical-record policy. |
| `SECURITY.md` | Supported security-reporting scope and private vulnerability route. |
| `SUPPORT.md` | Supported platforms, issue-reporting evidence, and best-effort maintenance boundary. |
| `LICENSE-SCOPE.md` | GPL/CC0 path mapping and treatment of user content and generated workspaces. |
| `CHANGELOG.md` | Immutable tagged history plus a concise Unreleased documentation entry. |
| `tests/test_project_automation.py` | Repository policy assertions, including historical-record independence. |
| `tests/test_release_metadata.py` | Active-document link/anchor, release, platform, package, and capacity contracts. |

### Task 1: Decouple active documentation from historical plans

**Files:**
- Modify: `tests/test_project_automation.py:368-380`
- Modify: `tests/test_release_metadata.py`
- Modify: `CONTRIBUTING.md:130-149`
- Preserve unchanged: `docs/superpowers/plans/2026-07-16-end-user-guide.md`

**Interfaces:**
- Consumes: the active-document set and `MarkdownIt("commonmark")` already used by `tests/test_release_metadata.py`.
- Produces: an automated local-link and local-anchor contract for active docs; an explicit contributor rule that historical plans are immutable records rather than mirrors of live docs.

- [ ] **Step 1: Replace the historical byte-equality test with the provenance rule**

Delete `test_historical_plan_embeds_current_user_guide_byte_for_byte` from
`tests/test_project_automation.py` and add this focused policy test:

```python
def test_contributor_documentation_keeps_historical_records_immutable() -> None:
    contributing = (PROJECT_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")

    assert "Historical plans and specifications are immutable project records." in contributing
    assert "Do not synchronize them with later edits to active documentation." in contributing
    assert "After every user-guide edit, update the embedded block" not in contributing
```

- [ ] **Step 2: Run the provenance test and observe the intended failure**

Run:

```bash
uv run pytest tests/test_project_automation.py::test_contributor_documentation_keeps_historical_records_immutable -q
```

Expected: FAIL because `CONTRIBUTING.md` still instructs contributors to rewrite the historical
embedded guide.

- [ ] **Step 3: Update the contributor documentation contract**

Replace the historical synchronization paragraphs under `## Documentation changes` with:

```markdown
Historical plans and specifications are immutable project records. Do not synchronize them with
later edits to active documentation. Validate the current README, tutorial, user guide, specialist
guides, and policy files against the live product instead.

For every active-document change, check relative links and local heading anchors, compare affected
commands with live help, and preserve versioned statements that intentionally describe a tagged
release or reviewed evidence set.
```

Change the final pull-request checklist item from the embedded-copy requirement to:

```markdown
- [ ] Active documentation matches live help, local links and anchors resolve, and historical
  records remain unchanged.
```

- [ ] **Step 4: Add active-document link and anchor validation**

Add `unquote` and `urlsplit` from `urllib.parse` to `tests/test_release_metadata.py`, then add the
following constants and helpers after `PYTHON_HEADER`:

```python
ACTIVE_DOCUMENTATION = (
    Path("README.md"),
    Path("CHANGELOG.md"),
    Path("CONTRIBUTING.md"),
    Path("LICENSE-SCOPE.md"),
    Path("SECURITY.md"),
    Path("SUPPORT.md"),
    Path("docs/hermes-mcp-setup.md"),
    Path("docs/maintainers/releases.md"),
    Path("docs/performance-and-capacity.md"),
    Path("docs/tutorial.md"),
    Path("docs/user-guide.md"),
    Path("docs/workspace-compatibility.md"),
)


def _github_anchor(text: str) -> str:
    without_punctuation = re.sub(r"[^\w\- ]", "", text.strip().casefold())
    return re.sub(r"\s+", "-", without_punctuation)


def _heading_anchors(markdown: str) -> frozenset[str]:
    anchors: set[str] = set()
    occurrences: dict[str, int] = {}
    tokens = MarkdownIt("commonmark").parse(markdown)
    for index, token in enumerate(tokens[:-1]):
        if token.type != "heading_open":
            continue
        inline = tokens[index + 1]
        text = "".join(
            child.content
            for child in inline.children or ()
            if child.type in {"text", "code_inline"}
        )
        base = _github_anchor(text)
        occurrence = occurrences.get(base, 0)
        occurrences[base] = occurrence + 1
        anchors.add(base if occurrence == 0 else f"{base}-{occurrence}")
    return frozenset(anchors)
```

Add this test near the other public-document tests:

```python
def test_active_documentation_local_links_and_anchors_resolve() -> None:
    parser = MarkdownIt("commonmark")
    for relative in ACTIVE_DOCUMENTATION:
        source = PROJECT_ROOT / relative
        markdown = source.read_text(encoding="utf-8")
        for token in parser.parse(markdown):
            for child in token.children or ():
                if child.type != "link_open":
                    continue
                href = child.attrGet("href")
                assert isinstance(href, str)
                parsed = urlsplit(href)
                if parsed.scheme or parsed.netloc:
                    continue
                target = source if not parsed.path else source.parent / unquote(parsed.path)
                target = target.resolve()
                assert target.is_file(), f"{relative}: missing link target {href}"
                if parsed.fragment and target.suffix.casefold() == ".md":
                    anchors = _heading_anchors(target.read_text(encoding="utf-8"))
                    fragment = unquote(parsed.fragment).casefold()
                    assert fragment in anchors, f"{relative}: missing anchor {href}"
```

- [ ] **Step 5: Run focused governance and link tests**

Run:

```bash
uv run pytest \
  tests/test_project_automation.py::test_contributor_documentation_keeps_historical_records_immutable \
  tests/test_release_metadata.py::test_active_documentation_local_links_and_anchors_resolve -q
```

Expected: PASS. If the link test exposes an existing active-document defect, record the exact
source and target and fix it in the task that owns that document; do not edit a historical target.

- [ ] **Step 6: Verify the historical plan is untouched and commit**

Run:

```bash
git diff --exit-code -- docs/superpowers/plans/2026-07-16-end-user-guide.md
git diff --check
git add CONTRIBUTING.md tests/test_project_automation.py tests/test_release_metadata.py
git commit -m "test: validate active documentation contracts"
```

Expected: both checks are silent and the commit succeeds.

### Task 2: Rewrite the README as the newcomer landing page

**Files:**
- Modify: `README.md`
- Test: `tests/test_project_automation.py`
- Test: `tests/test_release_metadata.py`

**Interfaces:**
- Consumes: current package identity `0.4.0rc2`, stable release `0.3.0` / `v3`, supported Python
  `3.13` and `3.14`, platform policy, CLI entry points, and links to every canonical document.
- Produces: the public product narrative and navigation contract consumed by PyPI and new users.

- [ ] **Step 1: Capture the current product and CLI contracts**

Run:

```bash
uv run python -c 'import tomllib; from pathlib import Path; project=tomllib.loads(Path("pyproject.toml").read_text())["project"]; print(project["version"], project["requires-python"], sorted(project["scripts"]))'
uv run bundlewalker --help
uv run bundlewalker-mcp --help
```

Expected: `0.4.0rc2`, `>=3.13,<3.15`, both public scripts, and help output that confirms the
commands retained in the README.

- [ ] **Step 2: Rewrite the README using the approved order**

Use this top-level section order and no additional competing quick-start section:

```markdown
# BundleWalker
## Why BundleWalker
## Project status
## Install BundleWalker
## Create your first workspace
## Choose how to use BundleWalker
### Command-line interface
### MCP server
### Local web UI
## Understand reviewed writes
## Operate and protect a workspace
## Documentation
## Development
## License
```

Apply these exact content requirements:

- Open with the canonical local-first description from Global Constraints, followed by one
  sentence explaining review-first OKF Markdown and immutable accepted sources.
- Keep the link bar for Tutorial, User Guide, Changelog, Contributing, Security, Support, and
  License.
- In `Project status`, retain the exact tested phrase “current production release candidate is
  `0.4.0rc2`”, state latest stable `v3` / package `0.3.0`, include “proof of concept”, and state
  “macOS and Linux are supported; Windows is experimental.”
- In `Install BundleWalker`, retain “BundleWalker requires Python 3.13 or 3.14” and
  `uv tool install "bundlewalker==0.4.0rc2"`; label it as prerelease installation and link to the
  source-checkout development path rather than mixing it into the first-use flow.
- In `Create your first workspace`, keep one portable source-file example, `bundlewalker init`,
  `bundlewalker doctor`, `bundlewalker ingest`, and one read-only `bundlewalker ask`. Explain model
  credentials before the first model-backed command and link to the user guide for provider setup.
- In `Choose how to use BundleWalker`, present the existing CLI first, the existing local MCP
  `stdio` server second, and a short “planned, not implemented” local web UI subsection third.
- In `Understand reviewed writes`, preserve prepare/validate/diff/decision/commit semantics and
  distinguish deterministic, read-only, prepare-only, and applying operations.
- In `Operate and protect a workspace`, summarize `workspace status`, `backup`, `restore`, and
  `upgrade`; retain the links to compatibility and performance/capacity evidence.
- In `Documentation`, give every active document one sentence matching the File Responsibility
  Map, including the performance page and License Scope.
- Preserve the doctor support-report wording required by
  `test_doctor_diagnostics_and_redacted_support_reports_are_published`: users must “inspect and
  remove” an owner-only partial target “before retrying”.
- Remove the long preset table, full source-checkout walkthrough, and command catalog from the
  README; link to their canonical guide sections instead.

- [ ] **Step 3: Run README contract tests**

Run:

```bash
uv run pytest \
  tests/test_release_metadata.py::test_declared_documented_and_diagnostic_python_support_agree \
  tests/test_release_metadata.py::test_public_policy_documents_exist_and_are_linked \
  tests/test_release_metadata.py::test_second_release_candidate_documents_rc1_recovery_without_final_beta_claim \
  tests/test_release_metadata.py::test_performance_document_publishes_reviewed_capacity_derived_from_evidence_and_is_linked \
  tests/test_project_automation.py::test_workspace_lifecycle_policy_and_commands_are_published \
  tests/test_project_automation.py::test_doctor_diagnostics_and_redacted_support_reports_are_published \
  tests/test_release_metadata.py::test_active_documentation_local_links_and_anchors_resolve -q
```

Expected: PASS.

- [ ] **Step 4: Inspect README rendering structure and commit**

Run:

```bash
rg -n '^#{1,3} ' README.md
git diff --check
git add README.md
git commit -m "docs: improve newcomer README"
```

Expected: headings appear once in the approved order, whitespace check is silent, and the commit
succeeds.

### Task 3: Tighten the tutorial into one reproducible first journey

**Files:**
- Modify: `docs/tutorial.md`
- Test: `tests/test_project_automation.py`
- Test: `tests/test_release_metadata.py`

**Interfaces:**
- Consumes: the personal-workbook preset, live CLI commands, Python support statement, reviewed
  write behavior, workspace lifecycle commands, and model/provider boundary.
- Produces: one copy-pasteable end-to-end learning path; deeper explanations link to the user guide.

- [ ] **Step 1: Verify every tutorial command against live help**

Run:

```bash
uv run bundlewalker init --help
uv run bundlewalker ingest --help
uv run bundlewalker ask --help
uv run bundlewalker lint --help
uv run bundlewalker doctor --help
uv run bundlewalker workspace backup --help
uv run bundlewalker workspace restore --help
```

Expected: every option used in the tutorial is present in the corresponding help output.

- [ ] **Step 2: Rework the tutorial around explicit learning outcomes**

Retain the existing personal-workbook scenario and use this section progression:

```markdown
# Build a Personal Knowledge Workbook
## What you will build
## Prerequisites
## 1. Prepare BundleWalker and your model
## 2. Create the source notes
## 3. Initialize the workspace
## 4. Ingest and review the first source
## 5. Explore accepted knowledge
## 6. Ask and save a Synthesis
## 7. Add newer evidence
## 8. Refresh the Synthesis
## 9. Check workspace health
## 10. Back up and restore the workspace
## What you learned
## Next steps
## Clean up
```

Apply these exact rules:

- Retain the exact support sentence “You need Python 3.13 or 3.14”.
- Declare `PROJECT_ROOT`, `TUTORIAL_ROOT`, and workspace paths once; quote every use.
- Keep placeholders for the model string and provider credential and state that commands using a
  model can use the network and incur cost.
- Before each reviewed write, tell the reader what proposal and diff they should expect; after it,
  tell them which files or concepts should now exist without promising model-specific prose.
- Explain that rejection or interruption leaves accepted knowledge unchanged.
- Keep `workspace backup` and a restore to a new or empty target, with the raw-source and
  unencrypted-archive warning linked to `workspace-compatibility.md`.
- Move the optional Git checkpoint out of the numbered core journey or remove it; BundleWalker does
  not perform Git operations.
- Finish with links to the user guide, MCP section, Hermes guide, compatibility policy, and
  performance/capacity evidence.

- [ ] **Step 3: Run tutorial-focused tests and a shell-syntax review**

Run:

```bash
uv run pytest \
  tests/test_release_metadata.py::test_declared_documented_and_diagnostic_python_support_agree \
  tests/test_project_automation.py::test_workspace_lifecycle_policy_and_commands_are_published \
  tests/test_release_metadata.py::test_active_documentation_local_links_and_anchors_resolve -q
rg -n '^#{1,3} |PROJECT_ROOT|TUTORIAL_ROOT|workspace backup|workspace restore' docs/tutorial.md
git diff --check
```

Expected: tests pass, variables are declared before use, backup and restore remain documented, and
the whitespace check is silent.

- [ ] **Step 4: Commit the tutorial**

Run:

```bash
git add docs/tutorial.md
git commit -m "docs: streamline first-workspace tutorial"
```

Expected: commit succeeds.

### Task 4: Reorganize the user guide as the canonical operational reference

**Files:**
- Modify: `docs/user-guide.md`
- Preserve unchanged: `docs/superpowers/plans/2026-07-16-end-user-guide.md`
- Test: `tests/test_project_automation.py`
- Test: `tests/test_release_metadata.py`

**Interfaces:**
- Consumes: all live CLI subcommands, MCP `TOOL_SPECS`, reviewed-write transaction behavior,
  compatibility policy, performance evidence, and the tutorial's newcomer handoff.
- Produces: the authoritative host-neutral CLI/MCP/lifecycle/recovery/troubleshooting reference.

- [ ] **Step 1: Capture authoritative CLI and MCP surfaces**

Run:

```bash
uv run bundlewalker --help
uv run bundlewalker init --help
uv run bundlewalker ingest --help
uv run bundlewalker ask --help
uv run bundlewalker lint --help
uv run bundlewalker doctor --help
uv run bundlewalker review --help
uv run bundlewalker workspace --help
uv run bundlewalker-mcp --help
uv run python - <<'PY'
from bundlewalker.interfaces.mcp import TOOL_SPECS
for name in sorted(TOOL_SPECS):
    print(name)
PY
```

Expected: the captured names and options match every documented command and all ten MCP tools.

- [ ] **Step 2: Reorganize without duplicating the tutorial**

Use this top-level progression, retaining deeper third-level sections where they remain useful:

```markdown
# BundleWalker User Guide
## Choose your path
## Core concepts and safety model
## Install and configure BundleWalker
## Create and understand a workspace
## Ingest and review sources
## Explore, ask, save, and refresh
## Maintain, diagnose, and recover
## Back up, restore, upgrade, and roll back
## CLI reference
## Use BundleWalker through a local MCP host
## Workspace and process reference
## Limits and compatibility
## Troubleshooting and safety
## Related documentation
```

Apply these exact rules:

- Keep “BundleWalker requires Python 3.13 or 3.14” and the model/provider setup anchor used by the
  README.
- Start with links for first-time users, CLI users, MCP-host users, Hermes users, and maintainers.
- Define source bundle, workspace, indexing, exploration, reviewed writes, MCP server, and planned
  local web UI once in the concepts section.
- Keep all exact doctor, review recovery, transaction, producer-limit, and process-boundary phrases
  currently asserted in repository tests.
- Keep command signatures in one CLI reference section; task sections should explain intent and
  link to the signature rather than repeat every option.
- Preserve all ten MCP tool names, their read/prepare/resolve grouping, strict schemas, resource
  behavior, single-workspace startup boundary, inline-ingestion limit, model boundary, and
  sequential review constraint.
- Link to the Hermes guide without putting Hermes CLI or YAML in the host-neutral guide.
- Link to the tutorial for the full learning journey, compatibility for lifecycle policy, and
  performance/capacity for measured boundaries.
- Do not update the embedded copy in the historical 2026-07-16 plan.

- [ ] **Step 3: Run operational-reference tests**

Run:

```bash
uv run pytest \
  tests/test_project_automation.py::test_workspace_lifecycle_policy_and_commands_are_published \
  tests/test_project_automation.py::test_doctor_diagnostics_and_redacted_support_reports_are_published \
  tests/test_release_metadata.py::test_declared_documented_and_diagnostic_python_support_agree \
  tests/test_release_metadata.py::test_performance_document_publishes_reviewed_capacity_derived_from_evidence_and_is_linked \
  tests/test_release_metadata.py::test_active_documentation_local_links_and_anchors_resolve -q
git diff --exit-code -- docs/superpowers/plans/2026-07-16-end-user-guide.md
```

Expected: all tests pass and the historical-plan diff is empty.

- [ ] **Step 4: Inspect headings, stale terminology, and commit**

Run:

```bash
rg -n '^#{1,3} ' docs/user-guide.md
rg -n 'web UI|Windows|proof of concept|beta|0\.4\.0|v3' docs/user-guide.md
git diff --check
git add docs/user-guide.md
git commit -m "docs: reorganize user guide"
```

Expected: the guide is host-neutral, status terms are accurate, whitespace check is silent, and
the commit succeeds.

### Task 5: Clarify specialist integration and operating-boundary guides

**Files:**
- Modify: `docs/hermes-mcp-setup.md`
- Modify: `docs/workspace-compatibility.md`
- Modify: `docs/performance-and-capacity.md`
- Test: `tests/test_project_automation.py`
- Test: `tests/test_release_metadata.py`

**Interfaces:**
- Consumes: user-guide canonical concepts, Hermes-only setup boundary, lifecycle CLI contract, and
  reviewed benchmark evidence.
- Produces: focused specialist guides that do not duplicate onboarding or overstate support.

- [ ] **Step 1: Audit the specialist guides for protected facts**

Run:

```bash
uv run pytest \
  tests/test_release_metadata.py::test_performance_document_publishes_reviewed_capacity_derived_from_evidence_and_is_linked \
  tests/test_release_metadata.py::test_performance_document_marks_reported_large_and_probe_boundaries_unsupported \
  tests/test_project_automation.py::test_workspace_lifecycle_policy_and_commands_are_published -q
rg -n '/Users/|/Volumes/|hereh|OPENAI_API_KEY=[^<]' \
  docs/hermes-mcp-setup.md docs/workspace-compatibility.md docs/performance-and-capacity.md
```

Expected: tests pass; the portability search returns no personal path, username, or real secret.

- [ ] **Step 2: Improve the Hermes guide without generalizing it**

Keep its current operational sequence but add a two-sentence orientation and a final “Related
BundleWalker documentation” subsection. Preserve these requirements:

- local `stdio`, one fixed workspace, and no remote/HTTP claim;
- portable `PROJECT_ROOT`, `WORKSPACE`, `UV_COMMAND`, and `HERMES_HOME` values;
- `--args` last in the Hermes registration command;
- five-tool initial read-oriented surface and optional prepare/resolve tools;
- separate Hermes and BundleWalker model configuration;
- explicit minimal environment forwarding without printing secrets;
- `/reload-mcp`, discovery naming, sequential calls, troubleshooting, and removal; and
- links to the host-neutral MCP reference, safety/recovery guidance, compatibility, and support.

- [ ] **Step 3: Improve compatibility guidance around decisions**

Keep every complete lifecycle command and warning enforced by
`test_workspace_lifecycle_policy_and_commands_are_published`. Add an opening “Use this guide when”
paragraph and a short decision table with these rows:

```markdown
| Need | Action |
| --- | --- |
| Inspect without changing anything | Run `bundlewalker workspace status`. |
| Move or archive a workspace | Create and verify a backup; protect it as sensitive data. |
| Recover elsewhere | Restore into a new or empty target. |
| Adopt a newer format | Create a pre-upgrade backup, then request an explicit upgrade. |
| Return to an earlier state | Restore a known backup into a separate target. |
```

Do not imply automatic migration, cross-version write compatibility, encryption, or safe in-place
restore.

- [ ] **Step 4: Improve performance guidance without changing evidence**

Preserve byte-for-byte the single generated supported-capacity sentence, evidence links,
environment strings, profile table values, scenario inventory, timing boundary language,
unsupported Large/Probe statement, 1-GiB advisory, privacy boundary, and reproduction commands.
Add only navigation and interpretive guidance:

- an opening statement that this is reviewed evidence, not a universal machine guarantee;
- a “How to use these numbers” paragraph directing users to stay within the supported profile,
  monitor free space, and benchmark their own environment; and
- links back to the user guide, compatibility policy, and support policy.

- [ ] **Step 5: Run specialist-document tests and commit**

Run:

```bash
uv run pytest \
  tests/test_release_metadata.py::test_performance_document_publishes_reviewed_capacity_derived_from_evidence_and_is_linked \
  tests/test_release_metadata.py::test_performance_document_marks_reported_large_and_probe_boundaries_unsupported \
  tests/test_release_metadata.py::test_active_documentation_local_links_and_anchors_resolve \
  tests/test_project_automation.py::test_workspace_lifecycle_policy_and_commands_are_published -q
git diff --check
git add docs/hermes-mcp-setup.md docs/workspace-compatibility.md docs/performance-and-capacity.md
git commit -m "docs: clarify specialist operating guides"
```

Expected: all tests pass and the commit succeeds.

### Task 6: Align maintainer, governance, and release documentation

**Files:**
- Modify: `docs/maintainers/releases.md`
- Modify: `CONTRIBUTING.md`
- Modify: `SECURITY.md`
- Modify: `SUPPORT.md`
- Modify: `LICENSE-SCOPE.md`
- Modify: `CHANGELOG.md`
- Confirm absent, do not create: `CODE_OF_CONDUCT.md`
- Test: `tests/test_project_automation.py`
- Test: `tests/test_release_metadata.py`

**Interfaces:**
- Consumes: current `publish-testpypi.yml`, `publish-pypi.yml`, PyPI trusted-publishing recovery,
  GPL/CC0 path map, support matrix, and private security-reporting route.
- Produces: consistent project policy navigation and an accurate current maintainer procedure.

- [ ] **Step 1: Compare release documentation with current workflows**

Run:

```bash
rg -n '^(name:|on:|  [a-z-]+:|    environment:|      - name:)' \
  .github/workflows/publish-testpypi.yml .github/workflows/publish-pypi.yml
rg -n 'TestPyPI|production PyPI|trusted publisher|environment|rerun|Never' \
  docs/maintainers/releases.md
```

Expected: the guide names the current workflows, `testpypi` and `pypi` environments, OIDC trusted
publishing, immutable versions/tags, and recovery rules.

- [ ] **Step 2: Improve maintainer release navigation without rewriting release history**

Add a short prerequisite checklist and a numbered release overview before the detailed existing
procedure. Preserve every exact phrase asserted by
`test_second_release_candidate_documents_rc1_recovery_without_final_beta_claim`, including both
release-candidate tags, run ID `29847165596`, immutable-tag rule, fresh-artifact rule, verification
rerun command, and prohibition on rerunning a failed publish job. Do not change workflows or claim
that the final beta exists.

- [ ] **Step 3: Make governance documents mutually navigable and consistent**

Apply focused changes only:

- `CONTRIBUTING.md`: retain Task 1's immutable-history rule; clarify supported Python as 3.13 and
  3.14, supported macOS/Linux CI, experimental Windows, and the standard verification commands.
- `SECURITY.md`: keep the private GitHub advisory URL, “Do not report vulnerabilities in a public
  issue.”, supported-version scope, workspace/provider boundaries, and doctor partial-target
  guidance; add links to Support and License Scope.
- `SUPPORT.md`: retain “macOS and Linux”, “Windows is experimental”, “no guaranteed response time”,
  issue evidence, performance link, and doctor report sanitization; add links to Security,
  compatibility, and the user guide.
- `LICENSE-SCOPE.md`: do not alter the GPL-3.0-or-later or CC0-1.0 legal mapping; improve the opening
  summary and link to the exact license texts, README, and contributing terms.
- Confirm `CODE_OF_CONDUCT.md` does not exist; because the approved scope says “if present”, do not
  create a new policy in this documentation refresh.

- [ ] **Step 4: Add one Unreleased changelog entry**

Under `## [Unreleased]`, add exactly one bullet summarizing the user-visible documentation change:

```markdown
- Reorganized active documentation around a newcomer-first README, guided tutorial, canonical
  user reference, focused specialist guides, and consistent project-policy navigation.
```

Do not modify any tagged changelog section or comparison link.

- [ ] **Step 5: Run policy and release tests and commit**

Run:

```bash
uv run pytest \
  tests/test_release_metadata.py::test_public_policy_documents_exist_and_are_linked \
  tests/test_release_metadata.py::test_declared_documented_and_diagnostic_python_support_agree \
  tests/test_release_metadata.py::test_license_metadata_and_files_are_declared \
  tests/test_release_metadata.py::test_official_license_texts_are_unmodified \
  tests/test_release_metadata.py::test_second_release_candidate_documents_rc1_recovery_without_final_beta_claim \
  tests/test_project_automation.py::test_doctor_diagnostics_and_redacted_support_reports_are_published \
  tests/test_release_metadata.py::test_active_documentation_local_links_and_anchors_resolve -q
git diff --check
git add CHANGELOG.md CONTRIBUTING.md LICENSE-SCOPE.md SECURITY.md SUPPORT.md docs/maintainers/releases.md
git commit -m "docs: align project and maintainer guidance"
```

Expected: all tests pass, official license files remain unmodified, and the commit succeeds.

### Task 7: Perform the complete documentation and repository verification

**Files:**
- Modify only if verification exposes a defect: active documentation and documentation-contract
  tests listed in the File Responsibility Map
- Preserve unchanged: historical plans/specifications except this approved design and plan,
  benchmark evidence, prompts, presets, test fixtures, `LICENSE`, and `LICENSES/CC0-1.0.txt`

**Interfaces:**
- Consumes: every deliverable from Tasks 1-6.
- Produces: evidence that active documentation is navigable, internally consistent, matches live
  interfaces, and passes the repository's supported-platform-equivalent local gates.

- [ ] **Step 1: Run the active-document structural contract**

Run:

```bash
uv run pytest tests/test_release_metadata.py::test_active_documentation_local_links_and_anchors_resolve -q
git diff --check origin/master...HEAD
```

Expected: PASS and silent whitespace output.

- [ ] **Step 2: Search for stale, private, and conflicting active-doc claims**

Run:

```bash
rg -n '/Users/|/Volumes/|hereh|replace-with-your-openai-api-key' \
  README.md CHANGELOG.md CONTRIBUTING.md LICENSE-SCOPE.md SECURITY.md SUPPORT.md docs/*.md docs/maintainers/*.md
rg -n 'Python 3\.13 or newer|Windows (is )?supported|final 0\.4\.0|beta (is )?complete|hosted MCP|remote MCP' \
  README.md CONTRIBUTING.md SECURITY.md SUPPORT.md docs/*.md docs/maintainers/*.md
rg -n '0\.4\.0(?:a1|a2|rc1)|v0\.4\.0(?:a1|a2|rc1)' \
  README.md CONTRIBUTING.md SECURITY.md SUPPORT.md LICENSE-SCOPE.md docs/*.md docs/maintainers/*.md
```

Expected: no private path or real secret. Placeholder secret text may occur only in an explicitly
labelled safe example. Historical release identifiers may occur only where required by the current
release procedure or changelog; every other match is reviewed and either corrected or justified.

- [ ] **Step 3: Recheck all documented public entry points**

Run:

```bash
uv run bundlewalker --help >/dev/null
uv run bundlewalker init --help >/dev/null
uv run bundlewalker ingest --help >/dev/null
uv run bundlewalker ask --help >/dev/null
uv run bundlewalker lint --help >/dev/null
uv run bundlewalker doctor --help >/dev/null
uv run bundlewalker review --help >/dev/null
uv run bundlewalker workspace --help >/dev/null
uv run bundlewalker-mcp --help >/dev/null
```

Expected: every command exits `0`.

- [ ] **Step 4: Run the full offline quality gates**

Run:

```bash
uv sync --locked
uv lock --check
uv run pytest -m 'not eval' -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
```

Expected: all commands pass. Do not run live provider evaluations; this work does not require
credentials, network model calls, or cost.

- [ ] **Step 5: Verify protected records and license texts remain unchanged**

Run:

```bash
git diff --exit-code origin/master...HEAD -- \
  docs/superpowers/plans/2026-07-16-end-user-guide.md \
  benchmarks/evidence \
  src/bundlewalker/agents/prompts \
  src/bundlewalker/convention_presets \
  tests/fixtures \
  LICENSE \
  LICENSES/CC0-1.0.txt
```

Expected: no output and exit `0`.

- [ ] **Step 6: Review the complete diff and commit any verification-only corrections**

Run:

```bash
git status --short
git diff --stat origin/master...HEAD
git diff --check origin/master...HEAD
```

Expected: only approved active docs, the documentation contract tests, this approved design, and
this implementation plan changed. If verification required corrections, stage only those files
and commit them:

```bash
git add README.md CHANGELOG.md CONTRIBUTING.md LICENSE-SCOPE.md SECURITY.md SUPPORT.md \
  docs/hermes-mcp-setup.md docs/maintainers/releases.md docs/performance-and-capacity.md \
  docs/tutorial.md docs/user-guide.md docs/workspace-compatibility.md \
  tests/test_project_automation.py tests/test_release_metadata.py
git commit -m "docs: finalize documentation consistency"
```

Expected: create this final commit only when Task 7 produced actual corrections; otherwise leave
the already verified task commits unchanged.
