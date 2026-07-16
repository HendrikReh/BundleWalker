# Documentation Suite Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a first-time-user README, a copy-pasteable personal-workbook tutorial, a task-first authoritative user guide, and a contributor guide grounded in BundleWalker’s real architecture and verification workflow.

**Architecture:** The four documents use progressive disclosure and have separate authorities: README for discovery, tutorial for guided learning, user guide for operation and reference, and `CONTRIBUTING.md` for development. `docs/user-guide.md` remains byte-identical to the embedded guide in the historical end-user-guide plan; live CLI help, production code, tests, and project configuration remain the factual sources.

**Tech Stack:** Markdown, Typer CLI help, `uv`, Python 3.13, pytest, Ruff, Pyright, Git, POSIX shell examples.

## Global Constraints

- Do not change production code, CLI behavior, conventions preset content, dependencies, or OKF formats.
- Use the exact filenames `README.md`, `docs/tutorial.md`, `docs/user-guide.md`, and `CONTRIBUTING.md`.
- Keep README optimized for first-time users and keep detailed option/error semantics in the user guide.
- Make the tutorial fully copy-pasteable without checked-in sample fixtures or assumptions about model-generated slugs, titles, prose, citations, or semantic findings.
- Keep model setup provider-neutral, followed by one clearly labelled OpenAI example; never imply that the example model is a BundleWalker default or universally available.
- Use “model-backed” for provider operations and “offline” only when no provider call occurs.
- Preserve the exact safety boundary: agents propose typed results; deterministic code validates, renders, stages, recovers, and commits only reviewed writes.
- Keep semantic lint advisory; it never authorizes or applies knowledge changes.
- Keep `docs/user-guide.md` byte-identical to its embedded copy in `docs/superpowers/plans/2026-07-16-end-user-guide.md`.
- Do not run live provider evaluations for this documentation-only change.
- Every task must end with a clean worktree after its documented commit.

---

## File map

- Create `CONTRIBUTING.md`: architecture, development setup, test layers, documentation rules, security boundaries, and contribution checklist.
- Create `docs/tutorial.md`: one complete personal-workbook workflow using temporary local files.
- Rewrite `docs/user-guide.md`: authoritative task-first operations, complete CLI reference, layout, exit codes, and troubleshooting.
- Mechanically synchronize `docs/superpowers/plans/2026-07-16-end-user-guide.md`: embedded canonical guide only; do not editorialize the historical plan.
- Rewrite `README.md`: concise first-time-user landing page, quick start, safety model, preset chooser, next steps, scope, and navigation.

---

### Task 1: Add the contributor guide

**Files:**
- Create: `CONTRIBUTING.md`
- Reference: `pyproject.toml`
- Reference: `src/bundlewalker/cli.py`
- Reference: `src/bundlewalker/workflows/`
- Reference: `src/bundlewalker/agents/`
- Reference: `src/bundlewalker/okf/`
- Reference: `src/bundlewalker/changes.py`
- Reference: `src/bundlewalker/transactions.py`
- Reference: `tests/`

**Interfaces:**
- Consumes: module boundaries, test markers, tool configuration, and commands already defined by the repository.
- Produces: `CONTRIBUTING.md`, the authoritative contributor entry point linked by later tasks.

- [ ] **Step 1: Run the contributor-document contract and verify RED**

Run:

```bash
uv run python - <<'PY'
from pathlib import Path

path = Path("CONTRIBUTING.md")
assert path.is_file(), "CONTRIBUTING.md does not exist"
text = path.read_text(encoding="utf-8")
for heading in (
    "# Contributing to BundleWalker",
    "## Architecture",
    "## Development setup",
    "## Change workflow",
    "## Test layers",
    "## Documentation changes",
    "## Security and compatibility",
    "## Before opening a pull request",
):
    assert heading in text, heading
PY
```

Expected: FAIL with `AssertionError: CONTRIBUTING.md does not exist`.

- [ ] **Step 2: Write `CONTRIBUTING.md`**

Create the document with this exact section order and content contract:

```markdown
# Contributing to BundleWalker

BundleWalker is a local, review-first OKF knowledge tool. Link to `README.md` for the project
overview and `docs/user-guide.md` for user-facing behavior. State that contributors must preserve
the agent/deterministic-code trust boundary and keep the default suite offline.

## Project boundaries

Explain the v1 scope: one UTF-8 Markdown/text source per ingestion, four producer concept types,
no direct agent writes, no automatic Git, and no background service. Direct contributors to the
design documents before proposing scope expansion.

## Architecture

Use a table containing these real layers:

| Layer | Main paths | Responsibility |
| CLI | `src/bundlewalker/cli.py` | Typer parsing, display, confirmation, and bounded exit behavior |
| Workflows | `src/bundlewalker/workflows/` | Recovery, orchestration, pre-model checks, dependency construction, and transaction preparation |
| Agents | `src/bundlewalker/agents/` | PydanticAI prompts, read-only tools, typed model output, and output validation |
| Domain | `src/bundlewalker/domain.py` | Pydantic models and bounded proposal/answer/finding types |
| Changes | `src/bundlewalker/changes.py` | Operation validation, citation validation, rendering, and prospective wiki construction |
| OKF | `src/bundlewalker/okf/` | Document parsing/rendering, repository reads, indexes/logs/diffs, and deterministic lint |
| Retrieval | `src/bundlewalker/retrieval.py` | Local lexical concept ranking used by read-only agent tools |
| Transactions | `src/bundlewalker/transactions.py` | Locked staging, digest revalidation, commit/discard, and authenticated recovery |
| Workspace | `src/bundlewalker/workspace.py` | Initialization, discovery, configuration, source identities, and safe paths |

After the table, explain the write flow:
`CLI -> workflow -> agent proposal -> deterministic validation -> prospective tree -> review -> transaction commit`.
Explain that plain ask and lint remain read-only, except lint may recover an already reviewed
interrupted transaction.

## Repository map

Describe `src/bundlewalker`, `tests`, `evals`, `docs/superpowers/specs`, and
`docs/superpowers/plans`. Mention packaged prompt and convention Markdown resources.

## Development setup

Show only these commands:

```bash
git clone https://github.com/HendrikReh/BundleWalker.git
cd BundleWalker
uv sync --locked
uv run bundlewalker --help
```

State Python `>=3.13`, locked dependencies, and that credentials are unnecessary for the default
suite.

## Change workflow

Require a focused `codex/` or normal project branch, a failing focused test before a behavioral
fix, minimal implementation, focused verification, full offline verification, and an intentional
commit. State that documentation-only changes still require command/help and link validation.

## Test layers

Map:

- `tests/okf/`: parser, renderer, repository, derived-file, and deterministic lint behavior;
- `tests/agents/`: tool boundaries, prompt framing, model-output validation, and sanitized errors;
- `tests/workflows/`: orchestration, preconditions, no-ops, and transaction preparation;
- `tests/cli/`: Typer arguments, output, prompts, exit codes, and routing;
- `tests/test_acceptance.py`: complete offline user workflows and recovery;
- remaining `tests/test_*.py`: domain, workspace, retrieval, changes, conventions, and transactions;
- `tests/evals/`: opt-in provider quality cases and deterministic refresh-quality contracts.

Include exact commands:

```bash
uv run pytest -m 'not eval' -q
uv run pytest tests/workflows/test_ask.py -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
git diff --check
```

Explain that `BUNDLEWALKER_EVAL_MODEL='<pydantic-ai-model-string>' uv run pytest -m eval -v`
uses a provider, may cost money, and complements rather than replaces offline tests.

## Documentation changes

Define README, tutorial, user guide, and contributor-guide authorities. Require live CLI help
checks. Explain the embedded guide marker contract in
`docs/superpowers/plans/2026-07-16-end-user-guide.md` and require byte equality after every guide
edit.

## Security and compatibility

Require bounded public errors without source/credential leakage, untrusted framing for external
and existing-knowledge payloads, read-ledger citation validation, safe paths, digest preconditions,
permissive OKF reading, strict producer types, and preservation of transaction recovery. Forbid
weakening these boundaries merely to accept a model response.

## Before opening a pull request

Provide a checklist for scope, focused tests, full offline suite, Ruff format/check, Pyright,
`git diff --check`, documentation synchronization, no credentials, and explicit disclosure of
any live provider run.
```

Write polished prose rather than retaining the explanatory instructions above.

- [ ] **Step 3: Run the contributor-document contract and architecture checks**

Run the Step 1 contract again. Then run:

```bash
uv run python - <<'PY'
from pathlib import Path

text = Path("CONTRIBUTING.md").read_text(encoding="utf-8")
for target in (
    "README.md",
    "docs/user-guide.md",
    "src/bundlewalker/cli.py",
    "src/bundlewalker/workflows/",
    "src/bundlewalker/agents/",
    "src/bundlewalker/okf/",
    "src/bundlewalker/transactions.py",
    "tests/evals/",
):
    assert target in text, target
for command in (
    "uv sync --locked",
    "uv run pytest -m 'not eval' -q",
    "uv run ruff format --check .",
    "uv run ruff check .",
    "uv run pyright",
    "git diff --check",
):
    assert command in text, command
PY
```

Expected: both commands exit `0` without output.

- [ ] **Step 4: Verify the contributor commands**

Run:

```bash
uv run pytest -m 'not eval' --collect-only -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
git diff --check
```

Expected: offline tests collect; 57 Python files are formatted; Ruff passes; Pyright reports zero
errors and warnings; diff check is silent.

- [ ] **Step 5: Commit the contributor guide**

```bash
git add CONTRIBUTING.md
git diff --cached --check
git commit -m "docs: add contributor guide"
```

Expected: one new document is committed and the worktree is clean.

---

### Task 2: Add the personal-workbook tutorial

**Files:**
- Create: `docs/tutorial.md`
- Reference: `docs/user-guide.md`
- Reference: `src/bundlewalker/cli.py`

**Interfaces:**
- Consumes: the current CLI and the future authoritative user-guide link.
- Produces: a self-contained tutorial linked by README and the user guide in later tasks.

- [ ] **Step 1: Run the tutorial contract and verify RED**

Run:

```bash
uv run python - <<'PY'
from pathlib import Path

path = Path("docs/tutorial.md")
assert path.is_file(), "docs/tutorial.md does not exist"
text = path.read_text(encoding="utf-8")
for heading in (
    "# BundleWalker Personal Workbook Tutorial",
    "## What you will build",
    "## Before you start",
    "## 1. Prepare BundleWalker and your model",
    "## 2. Create two source notes",
    "## 3. Initialize the personal workbook",
    "## 4. Ingest and review the first source",
    "## 5. Inspect accepted knowledge",
    "## 6. Ask and save a Synthesis",
    "## 7. Add newer evidence",
    "## 8. Refresh the Synthesis",
    "## 9. Check final health",
    "## 10. Optional Git checkpoint",
    "## What to try next",
):
    assert heading in text, heading
PY
```

Expected: FAIL with `AssertionError: docs/tutorial.md does not exist`.

- [ ] **Step 2: Write the tutorial introduction and setup**

Create `docs/tutorial.md` with the exact headings from Step 1. Open with links to `../README.md`,
`user-guide.md`, and `../CONTRIBUTING.md`. State that the tutorial starts from the BundleWalker
checkout, creates all data under a temporary directory, and makes paid provider calls only for
model-backed commands. Tell the reader to run the command blocks in one shell session so
`PROJECT_ROOT`, `TUTORIAL_ROOT`, `BUNDLEWALKER_MODEL`, and `SYNTHESIS_ID` remain available.

Under “Before you start,” require Python 3.13+, `uv`, a PydanticAI model string, and its provider
credential. Use a provider-neutral export and link detailed setup to the user guide:

```bash
export BUNDLEWALKER_MODEL='<pydantic-ai-model-string>'
# Export the provider-specific credential required by that model.
```

Under step 1, use:

```bash
uv sync --locked
PROJECT_ROOT="$(pwd)"
TUTORIAL_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/bundlewalker-tutorial.XXXXXX")"
printf 'Tutorial files: %s\n' "$TUTORIAL_ROOT"
```

Explain that the tutorial retains the temporary path so users can inspect or delete it later.

- [ ] **Step 3: Add exact sample notes and initialization**

Use shell heredocs to create these two sources:

```bash
cat > "$TUTORIAL_ROOT/initial-notes.md" <<'EOF'
# Review-first knowledge workflow

A review gate separates a model proposal from durable knowledge. A declined proposal leaves the
knowledge base unchanged. Accepted source bytes remain immutable, while the compiled wiki may be
refined as new evidence arrives.

This note is a working observation, not a controlled comparison. It does not establish that a
review-first workflow improves every knowledge task.
EOF

cat > "$TUTORIAL_ROOT/newer-evidence.md" <<'EOF'
# Small comparison of review workflows

In a four-week internal comparison across three personal research projects, reviewed proposals
produced fewer unsupported wiki claims than automatically persisted proposals. The comparison
used one model and one reviewer, did not randomize task order, and did not measure long-term
maintenance cost.

The result supports testing a review gate in similar personal workflows. It does not establish
generalization to other models, teams, domains, or longer time horizons.
EOF
```

Initialize and enter the workspace:

```bash
uv run bundlewalker init "$TUTORIAL_ROOT/workbook" \
  --conventions-style personal-workbook
cd "$TUTORIAL_ROOT/workbook"
uv run --project "$PROJECT_ROOT" bundlewalker lint
```

State the expected deterministic result: initialization succeeds and lint reports no errors in
the empty bundle.

- [ ] **Step 4: Add ingestion, inspection, question, and save steps**

Use these commands:

```bash
uv run --project "$PROJECT_ROOT" bundlewalker ingest ../initial-notes.md
```

Tell the reader to inspect the full diff and answer `y` only when the Source and proposed concepts
faithfully reflect the note. Explain `n`, Ctrl-C, and EOF leave live knowledge unchanged.

Inspect accepted layers without relying on generated slugs:

```bash
find raw wiki -maxdepth 2 -type f -print | sort
uv run --project "$PROJECT_ROOT" bundlewalker lint
```

Ask and save:

```bash
uv run --project "$PROJECT_ROOT" bundlewalker ask \
  'What does this workspace currently establish about review before persistence?'

uv run --project "$PROJECT_ROOT" bundlewalker ask --save \
  'What does this workspace currently establish about review before persistence?'
```

State that plain ask is read-only; save reuses the one validated answer and proposes a Synthesis
through review.

- [ ] **Step 5: Add newer evidence and slug-independent refresh**

Ingest the second source:

```bash
uv run --project "$PROJECT_ROOT" bundlewalker ingest ../newer-evidence.md
```

After acceptance, derive the single saved Synthesis ID without assuming its model-generated slug:

```bash
SYNTHESIS_FILE="$(find wiki/syntheses -maxdepth 1 -type f -name '*.md' \
  ! -name 'index.md' -print -quit)"
test -n "$SYNTHESIS_FILE"
SYNTHESIS_ID="${SYNTHESIS_FILE#wiki/}"
SYNTHESIS_ID="${SYNTHESIS_ID%.md}"
printf 'Refreshing: %s\n' "$SYNTHESIS_ID"
```

Refresh explicitly:

```bash
uv run --project "$PROJECT_ROOT" bundlewalker ask \
  'Refresh this Synthesis with the newer comparison while preserving its methodological limits.' \
  --refresh "$SYNTHESIS_ID"
```

Explain stable path, changed title/body/citations, metadata preservation, target digest protection,
full replacement diff, no second model call, and the exact already-current no-op message. Tell the
reader to accept only if the new Synthesis preserves the sample size, duration, and generalization
limits.

- [ ] **Step 6: Add final health, optional semantic lint, Git, and cleanup guidance**

Use:

```bash
uv run --project "$PROJECT_ROOT" bundlewalker lint
uv run --project "$PROJECT_ROOT" bundlewalker lint --semantic
```

Label semantic lint optional and provider-backed. State its findings vary and remain advisory.

For optional Git:

```bash
printf '.bundlewalker/\n' > .gitignore
git init
git add .gitignore bundlewalker.toml conventions.md raw wiki
git commit -m 'Create BundleWalker personal workbook'
```

Warn that `raw/` contains exact source bytes and must be reviewed before remote publication.
Mention that Git identity configuration may be required. End with cleanup from outside the
workspace:

```bash
cd "$PROJECT_ROOT"
printf 'Tutorial workspace retained at: %s\n' "$TUTORIAL_ROOT"
# Remove it later only when you no longer need it:
# rm -rf "$TUTORIAL_ROOT"
```

“What to try next” links preset choice, full command reference, troubleshooting, and contributor
guidance without duplicating them.

- [ ] **Step 7: Verify tutorial structure, shell syntax, and links**

Run the Step 1 contract again, then:

```bash
uv run python - <<'PY'
from pathlib import Path
import re
import subprocess

text = Path("docs/tutorial.md").read_text(encoding="utf-8")
for link in ("../README.md", "user-guide.md", "../CONTRIBUTING.md"):
    assert link in text, link
for command in (
    "--conventions-style personal-workbook",
    "bundlewalker ingest ../initial-notes.md",
    "bundlewalker ask --save",
    '--refresh "$SYNTHESIS_ID"',
    "bundlewalker lint --semantic",
):
    assert command in text, command
assert "syntheses/decision-framework" not in text
bash = "\n".join(re.findall(r"```bash\n(.*?)\n```", text, flags=re.DOTALL))
subprocess.run(["bash", "-n"], input=bash, text=True, check=True)
PY
```

Expected: both commands exit `0`; no provider is called.

- [ ] **Step 8: Commit the tutorial**

```bash
git add docs/tutorial.md
git diff --cached --check
git commit -m "docs: add personal workbook tutorial"
```

Expected: the tutorial is committed and the worktree is clean.

---

### Task 3: Rewrite the authoritative user guide and synchronize its embedded copy

**Files:**
- Modify: `docs/user-guide.md`
- Modify: `docs/superpowers/plans/2026-07-16-end-user-guide.md`
- Reference: `README.md`
- Reference: `docs/tutorial.md`
- Reference: `CONTRIBUTING.md`
- Reference: `src/bundlewalker/cli.py`
- Reference: `tests/cli/`
- Reference: `tests/workflows/`

**Interfaces:**
- Consumes: tutorial and contributor navigation targets plus the live CLI contract.
- Produces: the authoritative task-first operating guide and its byte-identical embedded copy.

- [ ] **Step 1: Run the task-first guide contract and verify RED**

Run:

```bash
uv run python - <<'PY'
from pathlib import Path

text = Path("docs/user-guide.md").read_text(encoding="utf-8")
for heading in (
    "## Start here: the BundleWalker model",
    "## Install and configure a provider",
    "## Create a workspace",
    "## Ingest and review a source",
    "## Ask, save, and refresh",
    "## Maintain and recover the bundle",
    "## Complete CLI reference",
    "## Workspace and process reference",
    "## Troubleshooting and safety",
):
    assert heading in text, heading
PY
```

Expected: FAIL on the first new task-first heading.

- [ ] **Step 2: Rewrite the guide introduction, contents, mental model, and setup**

Use this top-level order:

```markdown
# BundleWalker User Guide
## Choose your path
## Contents
## Start here: the BundleWalker model
## Install and configure a provider
## Create a workspace
## Ingest and review a source
## Ask, save, and refresh
## Maintain and recover the bundle
## Complete CLI reference
## Workspace and process reference
## Troubleshooting and safety
```

“Choose your path” links to `tutorial.md`, `../README.md`, and `../CONTRIBUTING.md`. The mental
model explains `raw/`, `wiki/`, `conventions.md`, `.bundlewalker/`, the three flows from the spec,
and the agent/deterministic boundary in one place.

Setup remains provider-neutral and contains one labelled OpenAI example. Preserve safe variable
presence checking without printing secret values. Do not claim model availability; link current
PydanticAI and OpenAI catalogs. Correctly state model resolution order: `--model`, then
`BUNDLEWALKER_MODEL`.

- [ ] **Step 3: Write task chapters before reference material**

“Create a workspace” covers discovery, layout, all five presets, selection guidance, template-only
semantics, and editable `conventions.md`.

“Ingest and review a source” covers accepted formats/limit, duplicate pre-model no-op, immutable
raw bytes, typed proposal, prospective lint, complete diff, `y`/`n`/Ctrl-C/EOF behavior, and safe
retry guidance.

“Ask, save, and refresh” contains three subheadings:

- `### Ask a cited question`: read-only, read-ledger citations, concept citations rather than raw
  line spans;
- `### Save a Synthesis`: create-only proposal, one model call, reviewed diff;
- `### Refresh a Synthesis`: canonical exact-type target, pre-model validation, mutually exclusive
  `--save`, separately framed untrusted target, no self-citation, stable path, metadata behavior,
  digest protection, one model call, exact no-op text, and `SEM-STALE` as motivation only.

“Maintain and recover” distinguishes deterministic and semantic lint, process status, advisory
severities, authenticated recovery, and the idle lock-only `.bundlewalker/` state.

For every task, place the command before deep semantics and keep the most relevant error/recovery
guidance adjacent.

- [ ] **Step 4: Preserve complete reference and troubleshooting coverage**

“Complete CLI reference” retains exact syntax and option tables for `init`, `ingest`, `ask`, and
`lint`, verified against live help. Do not repeat the complete prose from the task chapters; link
back to them.

“Workspace and process reference” contains the tree, path/config meanings, review outcome table,
exit-code table, v1 producer limits, permissive-reader statement, and privacy/Git boundary.

“Troubleshooting and safety” retains focused cases for workspace discovery, missing model,
OpenAI 401/403, initialization refusal, source rejection, proposal rejection, semantic exit `0`,
refresh rejection, interrupted transaction, and Git/privacy. Link each case back to its task
chapter instead of restating the full behavior.

- [ ] **Step 5: Synchronize the embedded guide mechanically**

After `docs/user-guide.md` is complete, run:

```bash
uv run python - <<'PY'
from pathlib import Path

guide_path = Path("docs/user-guide.md")
plan_path = Path("docs/superpowers/plans/2026-07-16-end-user-guide.md")
guide = guide_path.read_text(encoding="utf-8")
plan = plan_path.read_text(encoding="utf-8")
start_marker = "Create `docs/user-guide.md` with exactly:\n\n````markdown\n"
end_marker = "\n````\n\n- [ ] **Step 3: Link the guide from the README**"
assert plan.count(start_marker) == 1
assert plan.count(end_marker) == 1
start = plan.index(start_marker) + len(start_marker)
end = plan.index(end_marker, start)
updated = plan[:start] + guide.rstrip("\n") + plan[end:]
plan_path.write_text(updated, encoding="utf-8")
PY
```

This is the only permitted mechanical edit to the historical plan.

- [ ] **Step 6: Run guide, embedded-copy, link, and live-help contracts**

Run the Step 1 contract again. Then run:

```bash
uv run python - <<'PY'
from pathlib import Path

guide = Path("docs/user-guide.md").read_text(encoding="utf-8")
plan = Path("docs/superpowers/plans/2026-07-16-end-user-guide.md").read_text(encoding="utf-8")
start_marker = "Create `docs/user-guide.md` with exactly:\n\n````markdown\n"
end_marker = "\n````\n\n- [ ] **Step 3: Link the guide from the README**"
start = plan.index(start_marker) + len(start_marker)
end = plan.index(end_marker, start)
assert plan[start:end] + "\n" == guide
for link in ("../README.md", "tutorial.md", "../CONTRIBUTING.md"):
    assert link in guide, link
for token in (
    "--conventions-style",
    "--model",
    "--save",
    "--refresh",
    "--semantic",
    "Synthesis is already current; no changes applied.",
    "Source already ingested; no changes applied.",
):
    assert token in guide, token
PY

uv run bundlewalker --help
uv run bundlewalker init --help
uv run bundlewalker ingest --help
uv run bundlewalker ask --help
uv run bundlewalker lint --help
```

Expected: contract exits `0`; live help exposes only `init`, `ingest`, `ask`, and `lint` with the
documented options.

- [ ] **Step 7: Run focused regression checks and commit**

Run:

```bash
uv run pytest tests/cli tests/workflows -q
git diff --check
```

Expected: all focused tests pass and diff check is silent.

Commit:

```bash
git add docs/user-guide.md docs/superpowers/plans/2026-07-16-end-user-guide.md
git diff --cached --check
git commit -m "docs: make the user guide task first"
```

Expected: canonical and embedded guides are committed together; worktree is clean.

---

### Task 4: Rewrite README as the documentation landing page

**Files:**
- Modify: `README.md`
- Reference: `docs/tutorial.md`
- Reference: `docs/user-guide.md`
- Reference: `CONTRIBUTING.md`
- Reference: `pyproject.toml`
- Reference: `evals/cases.yaml`

**Interfaces:**
- Consumes: the completed tutorial, user guide, contributor guide, CLI, and evaluation case list.
- Produces: the first-time-user landing page and navigation hub.

- [ ] **Step 1: Run the README navigation contract and verify RED**

Run:

```bash
uv run python - <<'PY'
from pathlib import Path

text = Path("README.md").read_text(encoding="utf-8")
for link in (
    "[Tutorial](docs/tutorial.md)",
    "[User Guide](docs/user-guide.md)",
    "[Contributing](CONTRIBUTING.md)",
):
    assert link in text, link
for heading in (
    "## Why BundleWalker",
    "## Quick start",
    "## Choose what you are building",
    "## How reviewed writes work",
    "## Common next steps",
    "## Current scope",
    "## Documentation",
    "## Development",
):
    assert heading in text, heading
PY
```

Expected: FAIL because tutorial and contributor navigation do not exist.

- [ ] **Step 2: Rewrite the opening, navigation, installation, and quick start**

Use the exact top-level order from Step 1 after `# BundleWalker`. Open with a short outcome-led
description: local review-first CLI, immutable accepted source bytes, maintained cited OKF wiki,
and readable Markdown output.

Immediately provide a three-link navigation line or list for Tutorial, User Guide, and
Contributing.

“Why BundleWalker” uses a compact table or bullets for local files, complete reviewed diffs,
cited answers, portable OKF, and recoverable writes. Keep implementation module names out of this
section.

“Quick start” includes repository install, provider-neutral model export, sample note creation,
`personal-workbook` initialization, `PROJECT_ROOT`, deterministic lint, ingestion, plain ask,
save, and semantic lint. Explain review outcomes once. Link the tutorial for the complete refresh
journey and the guide for provider setup. Include a short labelled OpenAI example but no real key.

- [ ] **Step 3: Add preset chooser, safety model, next steps, and scope**

“Choose what you are building” uses a compact five-row table:

- `default`: neutral general knowledge;
- `personal-workbook`: evidence, reflection, and open questions;
- `agent-context`: operational authority, constraints, procedures, and recovery;
- `software-agent`: repository architecture, commands, invariants, and traps;
- `research-agent`: methods, competing claims, limitations, and research gaps.

State selection is template-only and `conventions.md` becomes editable authority.

“How reviewed writes work” shows:

```text
Model-backed proposal -> deterministic validation -> complete diff -> your decision -> commit
```

Explain which commands write only after acceptance, which are read-only, duplicate/no-op behavior,
and transaction recovery. Do not repeat exit-code tables or every refresh metadata rule.

“Common next steps” gives concise commands for `ask`, `ask --save`, `ask ... --refresh`, plain
`lint`, and `lint --semantic`, each linking to the relevant user-guide section.

“Current scope” summarizes supported source formats, four producer types, main limits, and major
v1 exclusions. Link detailed limits to the guide instead of copying the full list.

- [ ] **Step 4: Add documentation and development sections**

“Documentation” explains the four-document authority map and links all three other documents.

“Development” contains only:

```bash
uv run pytest -m 'not eval' -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
```

Then document the opt-in command:

```bash
BUNDLEWALKER_EVAL_MODEL='<pydantic-ai-model-string>' uv run pytest -m eval -v
```

List all current quality areas from `evals/cases.yaml`: faithful source summary, cross-source
topic update, contradiction preservation, cited answer, and stale-Synthesis refresh. State live
evaluation may use network/cost and never replaces offline acceptance coverage. Link
`CONTRIBUTING.md` for architecture and workflow detail.

- [ ] **Step 5: Run the cross-document navigation and authority contract**

Run the Step 1 contract again. Then run:

```bash
uv run python - <<'PY'
from pathlib import Path
import re

files = {
    "README.md": Path("README.md").read_text(encoding="utf-8"),
    "CONTRIBUTING.md": Path("CONTRIBUTING.md").read_text(encoding="utf-8"),
    "docs/tutorial.md": Path("docs/tutorial.md").read_text(encoding="utf-8"),
    "docs/user-guide.md": Path("docs/user-guide.md").read_text(encoding="utf-8"),
}
expected_links = {
    "README.md": ("docs/tutorial.md", "docs/user-guide.md", "CONTRIBUTING.md"),
    "CONTRIBUTING.md": ("README.md", "docs/user-guide.md"),
    "docs/tutorial.md": ("../README.md", "user-guide.md", "../CONTRIBUTING.md"),
    "docs/user-guide.md": ("../README.md", "tutorial.md", "../CONTRIBUTING.md"),
}
for source, links in expected_links.items():
    for link in links:
        assert link in files[source], (source, link)
for source, text in files.items():
    base = Path(source).parent
    for target in re.findall(r"\[[^]]+\]\(([^)#]+)(?:#[^)]+)?\)", text):
        if "://" in target or target.startswith("mailto:"):
            continue
        path = (base / target).resolve()
        assert path.exists(), (source, target)
PY
```

Expected: exits `0` and every local documentation link resolves.

- [ ] **Step 6: Run complete documentation and offline verification**

Run:

```bash
uv run bundlewalker --help
uv run bundlewalker init --help
uv run bundlewalker ingest --help
uv run bundlewalker ask --help
uv run bundlewalker lint --help
uv run pytest -m 'not eval' -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
git diff --check
```

Expected: live help matches the documented interface; 401 non-evaluation tests pass; 57 Python
files are formatted; Ruff passes; Pyright reports zero errors and warnings; diff check is silent.

- [ ] **Step 7: Commit the README integration**

```bash
git add README.md
git diff --cached --check
git commit -m "docs: make README the documentation landing page"
```

Expected: README is committed and the worktree is clean.

---

### Task 5: Final editorial and contract audit

**Files:**
- Review: `README.md`
- Review: `CONTRIBUTING.md`
- Review: `docs/tutorial.md`
- Review: `docs/user-guide.md`
- Review: `docs/superpowers/plans/2026-07-16-end-user-guide.md`

**Interfaces:**
- Consumes: all completed documentation deliverables.
- Produces: evidence that the suite is accurate, navigable, synchronized, and ready for integration.

- [ ] **Step 1: Audit authority and duplication**

Read all four user-facing documents in order. Confirm README does not contain full option/exit
tables; tutorial does not duplicate exhaustive reference; guide remains operational authority;
contributor guide does not teach end-user workflows beyond links. Remove any repeated paragraph
that does not serve a distinct local decision.

- [ ] **Step 2: Audit commands, paths, and provider boundaries**

Compare every documented CLI command with live help. Confirm all working-directory transitions,
relative paths, environment variables, no-op messages, and review prompts. Confirm provider calls
are labelled, no credential value is present, and semantic lint is never described as offline or
authoritative.

- [ ] **Step 3: Re-run canonical/embedded equality and links**

Run the equality contract from Task 3 Step 6 and the local-link contract from Task 4 Step 5.

Expected: both exit `0`.

- [ ] **Step 4: Run the final project gate**

Run:

```bash
uv run pytest -m 'not eval' -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
git diff --check master...HEAD
git status --short --branch
```

Expected: all 401 non-evaluation tests pass; formatting, Ruff, Pyright, and diff checks pass; the
feature branch is clean. Do not run provider evaluations.

- [ ] **Step 5: Commit only if the final audit required corrections**

If Steps 1–4 required edits, stage only the affected documentation files, run
`git diff --cached --check`, and commit:

```bash
git commit -m "docs: polish documentation suite"
```

If no edits were required, do not create an empty commit.
