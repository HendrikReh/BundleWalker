# VS Code/Copilot MCP Certification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Certify Visual Studio Code with GitHub Copilot as BundleWalker's second local MCP host
using repeatable workflow evidence and publish accurate user and compatibility documentation.

**Architecture:** Keep runtime behavior unchanged. Exercise the production `bundlewalker-mcp`
entry point from a temporary initialized workspace through VS Code's workspace-scoped `stdio`
configuration, then record host, SDK, protocol, workflow, and limitation evidence in dedicated
documentation. Repository-policy tests make the new navigation and certification record part of
the maintained public documentation contract.

**Tech Stack:** BundleWalker 0.4.0rc2, Python 3.13/3.14, uv, MCP Python SDK 1.28.1, MCP protocol
2025-11-25, Visual Studio Code 1.129.1, built-in GitHub Copilot 0.57.0, JSON, Markdown, pytest

## Global Constraints

- Keep BundleWalker local, single-user, workspace-bound, and review-first.
- Test the production `bundlewalker-mcp` entry point over local `stdio`; do not introduce HTTP or
  another transport.
- Use a disposable initialized workspace. Exercise `BUNDLEWALKER_MODEL=test` only to observe the
  provider boundary and bounded error handling; seed standards-valid private reviews through
  BundleWalker's deterministic transaction API for host-side apply/discard certification. Never
  recommend the test model to end users.
- Do not read, copy, print, or commit provider credentials.
- Do not claim compatibility for an operation that was not observed through VS Code/Copilot.
- Do not claim the published-artifact portion of Milestone C while production PyPI has no
  installable `bundlewalker` project.
- Record macOS as the tested platform; describe Linux configuration as supported by VS Code and
  BundleWalker but not covered by this specific certification run.
- Treat apply and discard as sequential, explicit review decisions requiring the exact review ID.
- Do not force-install or downgrade the Marketplace Copilot extension: VS Code 1.129.1 bundles
  GitHub Copilot 0.57.0.

## Execution outcome

The live run certified VS Code startup, ten-tool discovery, deterministic status/search/lint,
pending-review inspection, approval-gated exact-ID discard and apply, clean restart persistence,
post-apply search, and concept-resource browsing. PydanticAI's built-in `test` model reached the
production `prepare_ingestion` boundary but returned `model_failed`; `test:model` was confirmed to
be an invalid runtime provider identifier. Consequently the public record treats model-backed
preparation as provider-dependent and unverified, while deterministic transaction seeds isolate
and certify the host's review-resolution behavior. Abrupt transaction recovery remains backed by
the passing offline crash-recovery suite rather than a deliberate VS Code crash in every phase.

---

## File map

- Create `docs/vscode-copilot-mcp-setup.md`: public VS Code-specific setup, trust, tool selection,
  credential forwarding, verification, restart, troubleshooting, and removal instructions.
- Create `docs/mcp-compatibility.md`: tested-host matrix, exact versions, protocol range,
  capability evidence, limitations, and repeatable certification workflow.
- Modify `README.md`: link the VS Code guide and compatibility matrix beside the Hermes guide.
- Modify `docs/user-guide.md`: route VS Code users to the dedicated setup and compatibility
  evidence.
- Modify `docs/tutorial.md`: expose the VS Code setup and compatibility record in next steps.
- Modify `CHANGELOG.md`: record the second-host certification documentation.
- Modify `tests/test_project_automation.py`: enforce navigation and minimum evidence fields.

### Task 1: Establish the documentation contract

**Files:**
- Modify: `tests/test_project_automation.py`

**Interfaces:**
- Consumes: public README, user guide, tutorial, changelog, and Markdown documentation files.
- Produces: `test_mcp_host_documentation_is_published()` as an executable navigation and evidence
  contract.

- [ ] **Step 1: Add the failing documentation test**

Add a test that reads `README.md`, `docs/user-guide.md`, `docs/tutorial.md`,
`docs/vscode-copilot-mcp-setup.md`, and `docs/mcp-compatibility.md`; require links from the three
navigation documents and require the compatibility record to name VS Code 1.129.1, GitHub Copilot
0.57.0, MCP SDK 1.28.1, protocol 2025-11-25, macOS, all ten tools, resources, review decline,
review acceptance, restart persistence, and transaction recovery.

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
uv run pytest tests/test_project_automation.py::test_mcp_host_documentation_is_published -q
```

Expected: failure because the two dedicated documentation files do not exist.

### Task 2: Prepare the disposable VS Code certification workspace

**Files:**
- Create outside the repository: a temporary workspace and `.vscode/mcp.json`

**Interfaces:**
- Consumes: absolute `uv` path, repository root, `bundlewalker init`, and VS Code's documented
  workspace MCP configuration schema.
- Produces: one disposable initialized workspace whose `bundlewalker` server launches through the
  current checkout with `BUNDLEWALKER_MODEL=test`.

- [ ] **Step 1: Create and initialize the disposable workspace**

Run `mktemp -d`, create a `knowledge` child with `uv run bundlewalker init`, and record the
absolute temporary root without placing it under the repository.

- [ ] **Step 2: Add the workspace-scoped MCP configuration**

Create `.vscode/mcp.json` with this resolved shape:

```json
{
  "servers": {
    "bundlewalker": {
      "type": "stdio",
      "command": "/absolute/path/to/uv",
      "args": [
        "run",
        "--project",
        "/absolute/path/to/BundleWalker",
        "bundlewalker-mcp",
        "--workspace",
        "/absolute/path/to/temporary/knowledge"
      ],
      "env": {
        "BUNDLEWALKER_MODEL": "test"
      }
    }
  }
}
```

- [ ] **Step 3: Open the disposable workspace in VS Code**

Open the temporary root, inspect the resolved server configuration, approve only the local
BundleWalker command, and start the server from `MCP: List Servers`.

### Task 3: Execute the VS Code/Copilot compatibility workflow

**Files:**
- Observe temporary workspace state only.

**Interfaces:**
- Consumes: the configured `bundlewalker` MCP server and built-in GitHub Copilot agent mode.
- Produces: observed pass/fail evidence for discovery, resources, deterministic reads, proposal,
  decline, acceptance, restart persistence, and recovery.

- [ ] **Step 1: Record runtime identities**

Record VS Code, built-in Copilot, BundleWalker, MCP SDK, negotiated protocol, macOS, architecture,
and test date from local commands and server logs.

- [ ] **Step 2: Verify discovery and read behavior**

Through Copilot, list the ten BundleWalker tools, call `workspace_status`, call
`search_concepts`, run deterministic `lint`, browse MCP resources, and read one concept resource
after an accepted ingestion exists.

- [ ] **Step 3: Verify proposal and decline**

Call `prepare_ingestion` with inline Markdown, inspect the complete pending review and exact ID,
call `discard_review` with that ID, and verify live `raw/` and `wiki/` content did not change.

- [ ] **Step 4: Verify durable restart and acceptance**

Prepare a second ingestion, record its pending review ID, stop and restart the server through VS
Code, verify the same review remains discoverable, apply that exact ID, and verify the source and
concept resource are now readable.

- [ ] **Step 5: Verify transaction recovery**

Use the repository's existing deterministic interrupted-transaction fixture/setup to leave the
temporary workspace in a recoverable state, restart the VS Code-hosted server, invoke the relevant
status or resolution operation through Copilot, and verify BundleWalker completes recovery without
losing accepted content or leaving an invalid pending review.

- [ ] **Step 6: Capture limitations honestly**

Record any unsupported VS Code rendering, approval, progress, resource, or error behavior. If an
acceptance item fails, mark it failed or blocked rather than certifying the host.

### Task 4: Publish VS Code setup and compatibility evidence

**Files:**
- Create: `docs/vscode-copilot-mcp-setup.md`
- Create: `docs/mcp-compatibility.md`
- Modify: `README.md`
- Modify: `docs/user-guide.md`
- Modify: `docs/tutorial.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: observed Task 3 results and official VS Code MCP configuration terminology.
- Produces: one user setup guide and one auditable host-compatibility record.

- [ ] **Step 1: Write the VS Code setup guide**

Document prerequisites, `.vscode/mcp.json`, `${input:...}` or `envFile` guidance for real provider
credentials, server trust, tool selection, read-first verification, sequential reviewed writes,
restart/reload, logs, sandbox considerations, and removal. Do not expose certification-only test
model configuration as end-user guidance.

- [ ] **Step 2: Write the compatibility matrix**

Record exact tested versions, date, platform, transport, protocol, capability results, evidence
procedure, and remaining scope. Explain that compatible source-checkout operation does not prove
production-PyPI installation.

- [ ] **Step 3: Update public navigation and changelog**

Link both documents from README, user guide, and tutorial, and add one concise Unreleased
changelog entry.

- [ ] **Step 4: Run the focused policy test**

Run:

```bash
uv run pytest tests/test_project_automation.py::test_mcp_host_documentation_is_published -q
```

Expected: pass.

### Task 5: Verify the complete change

**Files:**
- Verify all modified files.

**Interfaces:**
- Consumes: completed certification documentation and repository policy tests.
- Produces: reviewable, internally consistent branch ready for user review.

- [ ] **Step 1: Run documentation and repository checks**

```bash
uv run pytest tests/test_project_automation.py tests/test_release_metadata.py -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
```

Expected: all pass.

- [ ] **Step 2: Run the complete offline test suite**

```bash
uv run pytest -m 'not eval' -q
```

Expected: all tests pass.

- [ ] **Step 3: Review the diff and certification wording**

Confirm every passing claim maps to observed evidence, no temporary absolute path or credential is
committed, links resolve, and Milestone C's published-artifact condition remains explicitly open.
