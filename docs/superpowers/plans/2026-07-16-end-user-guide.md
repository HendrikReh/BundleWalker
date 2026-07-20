# BundleWalker End-User Guide Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish one beginner-friendly and reference-complete end-user guide covering setup, every supported CLI command, all five conventions presets, operating behavior, and safety guidance.

**Architecture:** `docs/user-guide.md` is the dedicated operating guide, ordered from first use to detailed reference. The README remains the project overview and links prominently to the guide. All command facts come from the live Typer interface and tests; all preset descriptions come from the packaged Markdown resources.

**Tech Stack:** Markdown, Typer CLI help, Python 3.13+, PydanticAI model strings, shell examples, pytest, Ruff, Pyright.

## Global Constraints

- Create one guide at `docs/user-guide.md`; do not split it across files.
- Modify only `docs/user-guide.md` and `README.md`.
- Document exactly the supported commands `init`, `ingest`, `ask`, and `lint`.
- Document exactly the conventions styles `default`, `personal-workbook`, `agent-context`, `software-agent`, and `research-agent`.
- Do not add, rename, or change CLI behavior, workspace behavior, dependencies, presets, or tests.
- Keep development, offline-test, and live-evaluation instructions in the README rather than duplicating them in the guide.
- Explain model precedence as `--model MODEL` first and `BUNDLEWALKER_MODEL` second.
- Keep provider guidance neutral except for one labeled OpenAI example using `OPENAI_API_KEY` and `openai:gpt-5.6-luna`.
- Treat `openai:gpt-5.6-luna` as an example, not a BundleWalker default; link to the current OpenAI model catalog and PydanticAI model documentation.
- Never include a real credential, copied environment value, user-specific path, or user-specific secret.
- State that preset selection is creation-time only, is not persisted as metadata, and leaves editable `conventions.md` as the sole authority.
- All verification is deterministic and offline: do not access credentials, call a model, run live evals, or perform network-backed inference.
- Do not push, publish, or modify any knowledge workspace.

---

## File map

- Create: `docs/user-guide.md` — complete end-user walkthrough and CLI/preset reference.
- Modify: `README.md:15-23` — prominent link from installation to the dedicated guide.

### Task 1: Write, link, and verify the end-user guide

**Files:**
- Create: `docs/user-guide.md`
- Modify: `README.md:15-23`

**Interfaces:**
- Consumes: the public Typer interface in `src/bundlewalker/cli.py`, `ConventionsStyle`, packaged preset Markdown, workspace discovery, and existing observable CLI behavior.
- Produces: a stable end-user guide reachable from the README; no runtime interface changes.

- [ ] **Step 1: Run the documentation contract and verify RED**

Run:

```bash
uv run python - <<'PY'
from pathlib import Path

guide = Path("docs/user-guide.md")
readme = Path("README.md").read_text(encoding="utf-8")

assert guide.is_file(), "docs/user-guide.md does not exist"
assert "[BundleWalker User Guide](docs/user-guide.md)" in readme
PY
```

Expected: FAIL with `AssertionError: docs/user-guide.md does not exist`.

- [ ] **Step 2: Create the complete end-user guide**

Create `docs/user-guide.md` with exactly:

````markdown
# BundleWalker User Guide

BundleWalker turns Markdown and plain-text sources into a local, persistent knowledge wiki. This
guide is the authority for operating every supported workflow, understanding review and recovery,
and resolving common failures.

## Choose your path

- Follow the [personal-workbook tutorial](tutorial.md) for a guided, copy-pasteable first journey.
- Read the [project overview](../README.md) for the shortest route from checkout to a reviewed
  proposal.
- Use this guide when you need complete operating semantics, command options, or recovery help.
- See the [contributor guide](../CONTRIBUTING.md) when changing BundleWalker itself.

## Contents

- [Start here: the BundleWalker model](#start-here-the-bundlewalker-model)
- [Install and configure a provider](#install-and-configure-a-provider)
- [Create a workspace](#create-a-workspace)
- [Ingest and review a source](#ingest-and-review-a-source)
- [Ask, save, and refresh](#ask-save-and-refresh)
- [Maintain and recover the bundle](#maintain-and-recover-the-bundle)
- [Back up, restore, upgrade, and roll back](#back-up-restore-upgrade-and-roll-back)
- [Complete CLI reference](#complete-cli-reference)
- [Use BundleWalker through a local MCP host](#use-bundlewalker-through-a-local-mcp-host)
- [Workspace and process reference](#workspace-and-process-reference)
- [Troubleshooting and safety](#troubleshooting-and-safety)

## Start here: the BundleWalker model

A BundleWalker workspace separates original evidence from maintained knowledge:

- `raw/` holds exact, immutable copies of accepted source bytes under content-derived names.
- `wiki/` is the compiled Open Knowledge Format (OKF) knowledge layer. It contains Source,
  Topic, Entity, and Synthesis pages, generated indexes, and a change log.
- `conventions.md` is the editable instruction and schema layer supplied to model-backed work.
  After initialization, it is the workspace's authority for local writing and knowledge rules.
- `.bundlewalker/` holds the coordination lock and temporary authenticated transaction state used
  for reviewed writes and crash recovery. It is not part of the knowledge bundle.

Three connected flows operate on those layers:

```text
Source -> model proposal -> deterministic validation -> reviewed diff -> raw/ + wiki/

Question -> cited answer -> optional save -> reviewed Synthesis creation

Existing Synthesis -> explicit refresh instruction -> reviewed in-place replacement
```

The model proposes typed knowledge changes or cited answers. It receives read-only list, search,
and concept-read tools; it cannot write workspace files, use a shell, or access arbitrary paths
through BundleWalker. Deterministic application code owns path handling, proposal validation,
rendering, prospective lint, the complete diff, confirmation, persistence, and recovery. Semantic
lint may suggest maintenance, but it never authorizes or starts a write.

## Install and configure a provider

BundleWalker requires Python 3.13 or 3.14 and [`uv`](https://docs.astral.sh/uv/). From a
BundleWalker checkout, install the locked environment and inspect the CLI:

```bash
cd "/path/to/BundleWalker"
uv sync --locked
uv run bundlewalker --help
```

Examples in this guide start from the checkout. After changing into a knowledge workspace, they
pass the checkout through `uv --project "$PROJECT_ROOT"` so `uv` can still find BundleWalker.

### Model and provider setup

`init` and deterministic `lint` make no provider call. `ingest`, `ask`, `ask --save`,
`ask --refresh`, and `lint --semantic` are model-backed. Duplicate source bytes are detected
before model resolution, so duplicate ingestion is also model-free.

BundleWalker resolves the model in this order:

1. the command's `--model MODEL` option;
2. the `BUNDLEWALKER_MODEL` environment variable.

For provider-neutral setup, replace the placeholder with a model string supported by your
installed PydanticAI version, then export that provider's credential separately:

```bash
export BUNDLEWALKER_MODEL='<pydantic-ai-model-string>'
# Export the provider-specific credential required by that model.
```

See the current [PydanticAI model documentation](https://ai.pydantic.dev/models/) for provider
prefixes and credential variables. BundleWalker does not store model identifiers or credentials
in the workspace.

### OpenAI example

This is a labelled example, not a default or an availability claim. Choose a current model ID
from the [OpenAI model catalog](https://developers.openai.com/api/docs/models), replace both
placeholders, and keep the key out of version control:

```bash
export OPENAI_API_KEY='replace-with-your-openai-api-key'
export BUNDLEWALKER_MODEL='openai:<current-openai-model-id>'
```

Confirm that required variables are present without printing their secret values:

```bash
uv run python - <<'PY'
import os

for name in ("OPENAI_API_KEY", "BUNDLEWALKER_MODEL"):
    print(f"{name}: {'SET' if os.getenv(name) else 'UNSET'}")
PY
```

Prefer a shell session, operating-system keychain, or secret manager appropriate to your
environment. If a model-backed command reports that no model is configured, pass `--model` or
set `BUNDLEWALKER_MODEL` before retrying.

## Create a workspace

Initialize a new or empty directory, record the checkout path, and enter the workspace:

```bash
PROJECT_ROOT="$(pwd)"
uv run bundlewalker init ./my-knowledge --conventions-style default
cd ./my-knowledge
uv run --project "$PROJECT_ROOT" bundlewalker lint
```

`init` creates `bundlewalker.toml`, editable `conventions.md`, `raw/`, four wiki categories,
generated indexes, and the initial log. It validates the empty wiki before succeeding and never
needs a model or review prompt. Success prints the resolved workspace path:

```text
Initialized BundleWalker workspace at /resolved/path/to/my-knowledge
```

Every other command discovers the workspace by searching from the current directory upward for
`bundlewalker.toml`. You can run it from the workspace root or any descendant, including under
`wiki/`.

### Choosing a preset

`--conventions-style` selects only the initial `conventions.md` template:

| Style | Choose it for | Knowledge emphasis | Example |
| --- | --- | --- | --- |
| `default` | A concise, general-purpose wiki | Facts, explicit uncertainty, conflicts, links, and stable naming | `uv run bundlewalker init ./knowledge --conventions-style default` |
| `personal-workbook` | Reflective personal understanding | Evidence versus interpretation, provisional judgments, changing views, and open questions | `uv run bundlewalker init ./personal-notes --conventions-style personal-workbook` |
| `agent-context` | Context for operational AI agents | Authority, scope, constraints, preconditions, side effects, success, recovery, and escalation | `uv run bundlewalker init ./operations --conventions-style agent-context` |
| `software-agent` | Context for coding and repository agents | Repository maps, exact commands, architecture, invariants, validation, compatibility, and traps | `uv run bundlewalker init ./repository-context --conventions-style software-agent` |
| `research-agent` | Evidence synthesis and research planning | Claim type, provenance, methods, samples, timeframes, limitations, alternatives, and falsification | `uv run bundlewalker init ./research-context --conventions-style research-agent` |

The preset is template-only:

- selection happens only during initialization;
- the style identifier is not stored in `bundlewalker.toml`, logs, or wiki metadata;
- BundleWalker does not enforce or upgrade that style later; and
- the generated `conventions.md` is fully editable and becomes the sole conventions authority.

Edit `conventions.md` to add local writing, naming, evidence, and maintenance rules. Model-backed
work may read it, but cannot propose changes to it.

If initialization refuses the target, use a path that does not exist or an existing empty
directory. BundleWalker does not initialize over a non-empty directory or existing workspace; if
scaffold creation fails, it rolls back only paths that command created.

## Ingest and review a source

From the workspace, ingest one source and optionally override the configured model:

```bash
uv run --project "$PROJECT_ROOT" bundlewalker ingest ../meeting-notes.md
uv run --project "$PROJECT_ROOT" bundlewalker ingest ../research.txt \
  --model '<pydantic-ai-model-string>'
```

Version 3 accepts one regular UTF-8 `.md` or `.txt` file per invocation. The default limit is
100,000 Unicode characters, configured by `max_source_characters` in `bundlewalker.toml`.

BundleWalker recovers any interrupted transaction, reads and hashes the exact input bytes, and
checks that digest before resolving a model. If a Source already records the full digest, the
command is a successful pre-model no-op:

```text
Source already ingested; no changes applied.
```

For new bytes, one model-backed run returns a typed proposal containing exactly one Source and
any proposed Topic or Entity changes. Deterministic code validates the source identity, types,
paths, operations, citations, links, prospective indexes, and log. It builds and lints a complete
prospective wiki before showing a summary and complete unified diff.

Review the full diff at `Apply these changes?`:

- answer `y` to commit the prospective wiki and copy the original bytes unchanged into `raw/`;
- answer `n` to discard staging and print `No changes applied.`;
- press Ctrl-C to discard staging and exit successfully unchanged; or
- end input at the prompt to discard staging and exit successfully unchanged.

Accepted raw bytes are immutable evidence. Later ingestion may refine Topic or Entity knowledge,
but does not rewrite an accepted raw copy.

If source loading fails, confirm that the path is a regular `.md` or `.txt` file, is valid UTF-8,
and fits the configured character limit. If proposal validation fails, no proposal content is
persisted. Check the source, editable conventions, selected model, and concise error, then run a
fresh ingestion; never repair transaction staging by hand.

## Ask, save, and refresh

### Ask a cited question

Ask the compiled wiki without proposing a new knowledge change:

```bash
uv run --project "$PROJECT_ROOT" bundlewalker ask \
  'What evidence supports review before persistence?'
```

Plain `ask` is model-backed. It does not propose or persist new model output and opens no review
prompt. Before querying, however, it may complete or roll back an already-reviewed interrupted
transaction. The query can search and read live concepts, and a read ledger records which concepts
it actually opened. The returned Markdown answer is accepted only when every citation targets an
existing concept in that ledger. Query answers cite concepts, not raw-source line spans; raw line
spans belong to ingestion-created evidence citations.

After any recovery, the command prints the validated answer and citations without persisting the
answer as knowledge. A missing model is a configuration error; an invalid or unread citation is a
model or validation failure, with no new model output persisted.

### Save a Synthesis

Save the answer to a question as a new reviewed Synthesis:

```bash
uv run --project "$PROJECT_ROOT" bundlewalker ask --save \
  'What evidence supports review before persistence?'
```

The same single query run produces the displayed answer. BundleWalker then turns that already
validated answer into one create-only Synthesis proposal; proposal preparation does not make a
second model call. It selects an available slug, renders the page and citations, validates and
lints the prospective wiki, and shows the complete diff.

Answer `y` to create the Synthesis and add a `Saved synthesis:` log entry. Answer `n`, press
Ctrl-C, or end input to discard it successfully without changing the live wiki. If the generated
answer cannot form a valid Synthesis, correct the question, conventions, or model choice and start
a fresh command.

### Refresh a Synthesis

Give an explicit revision instruction and the canonical ID of an existing Synthesis, without a
`.md` suffix:

```bash
uv run --project "$PROJECT_ROOT" bundlewalker ask \
  'Refresh this decision framework using the newer comparative evidence.' \
  --refresh syntheses/decision-framework
```

`--save` and `--refresh` are mutually exclusive. Before model resolution or provider use,
BundleWalker requires an ID of the form `syntheses/<lowercase-ascii-slug>`, an existing target,
and exact metadata type `Synthesis`. It also rejects preserved metadata outside current producer
limits before model use. These failures are usage errors and create no transaction state.

The target is passed separately from the instruction and framed as untrusted revision context.
Its prose cannot supply instructions or automatically valid citations. One model-backed query run
returns a complete replacement title and body with fresh citations to other live concepts that run
actually read. The target cannot cite itself, and preparing the replacement makes no second model
call.

Refresh keeps the same concept path so inbound links remain valid. The visible title, body, and
citations may change. BundleWalker preserves an existing description, tags, and representable
metadata extensions. A missing description uses the fallback
`A saved answer to a knowledge query.` An
accepted replacement receives the operation timestamp even when the old page had none.

The target's digest is recorded and checked again during preparation and commit. If another
process or editor changes the page, BundleWalker refuses to overwrite it. Start a new refresh so
the next proposal uses current content.

For a changed result, the command prints the rendered answer and complete replacement diff.
Answer `y` to apply it through the recoverable transaction path. Answer `n`, press Ctrl-C, or end
input to discard it successfully. Acceptance updates the page, generated indexes when needed, and
`wiki/log.md` with a `Refreshed synthesis:` entry.

Only when the complete canonical replacement—content, citations, and all rendered metadata—matches
the existing Synthesis does the command skip review and print exactly:

```text
Synthesis is already current; no changes applied.
```

That no-op creates no transaction state, timestamp-only change, mutation, or log entry. A semantic
`SEM-STALE` finding can motivate an explicit refresh, but remains advisory; lint does not start,
approve, or apply a refresh.

## Maintain and recover the bundle

Run offline deterministic checks after accepted edits or manual wiki maintenance. Add a
model-backed semantic pass when you want advisory content review:

```bash
uv run --project "$PROJECT_ROOT" bundlewalker lint
uv run --project "$PROJECT_ROOT" bundlewalker lint --semantic
uv run --project "$PROJECT_ROOT" bundlewalker lint --semantic \
  --model '<pydantic-ai-model-string>'
```

Deterministic lint checks UTF-8 and OKF parsing, safe paths, internal links, generated indexes,
log structure, raw-source identity, citation structure, source line ranges, and orphan concepts.
Broken internal links and orphans are warnings. Deterministic errors set process status `1`; a
clean run or warnings-only run exits `0`.

The provisional [performance and capacity methodology](performance-and-capacity.md) describes the
local workspace scenarios that are measured. Model-provider latency is not controlled by
BundleWalker and is excluded from that methodology.

`--semantic` runs one additional read-only model-backed pass for contradictions, staleness,
unsupported claims, missing concepts, and knowledge gaps. Semantic findings may use `ERROR`,
`WARNING`, or `INFO` display severities, but all are advisory. They do not control process status;
only deterministic errors do. Semantic lint proposes and writes no knowledge.

Before normal work, BundleWalker authenticates and completes or rolls back an accepted operation
interrupted during its commit. This recovery never authorizes new model output. A prepared pending
review is different: it remains inspectable and blocks another write preparation until an explicit
apply or discard. Read-only work remains available while it is pending.

`.bundlewalker/` appears when the first reviewed write is staged. Completed and discarded work
removes its per-operation transaction directory. In an idle workspace, `transaction.lock` may be
the only retained file; `transactions/` may remain as an empty directory. The lock is normal
coordination state, not a pending write. If recovery fails, stop and preserve `.bundlewalker/`
for diagnosis rather than editing its manifests or staged trees.

## Back up, restore, upgrade, and roll back

The [workspace compatibility and portable-backup policy](workspace-compatibility.md) is the one
authority for supported formats, compatibility statuses, exact archive scope, exit behavior, and
the portability boundary. Use these procedures for the four lifecycle commands.

### Inspect compatibility

From the BundleWalker checkout, inspect a workspace without changing it:

```bash
uv run bundlewalker workspace status ./knowledge
```

The report includes the installed BundleWalker version, workspace format, compatibility status,
readable and writable decisions, and whether an upgrade path is registered. Check it before backup
or upgrade and after every restore.

### Create a verified workspace backup

First resolve any pending review. Inspect it, then apply or discard its exact ID:

```bash
cd ./knowledge
uv run --project "$PROJECT_ROOT" bundlewalker review show
uv run --project "$PROJECT_ROOT" bundlewalker review apply REVIEW_ID
# Or discard instead of applying:
uv run --project "$PROJECT_ROOT" bundlewalker review discard REVIEW_ID
cd "$PROJECT_ROOT"
```

Stop editors, synchronizers, and other external writers, choose an absent output path outside the
workspace, then run:

```bash
mkdir -p ./backups
uv run bundlewalker workspace backup ./backups/knowledge.zip --workspace ./knowledge
```

Record the printed `SHA-256` with the archive. The ZIP is unencrypted and may contain exact raw
source bytes, including private, licensed, regulated, or secret material. Store it at an encrypted
destination or protect it with an external encryption tool. BundleWalker never overwrites an
existing archive.

### Restore into a separate target

Restore accepts only a new or empty target and does not need a current workspace:

```bash
uv run bundlewalker workspace restore ./backups/knowledge.zip ./knowledge-restored
uv run bundlewalker workspace status ./knowledge-restored
(
  cd ./knowledge-restored
  uv run --project "$PROJECT_ROOT" bundlewalker lint
)
```

Compare the restore output's `SHA-256` with the digest recorded during backup. Restore verifies
the complete archive before publishing the target and never replaces a non-empty workspace.
Deterministic lint then checks knowledge health separately from byte preservation.

### Request an upgrade and rehearse rollback

Upgrade is always explicit:

```bash
uv run bundlewalker workspace status ./knowledge
uv run bundlewalker workspace upgrade ./knowledge --backup-dir ./backups
```

The current format reports an exact no-op. Production has no registered migration, so do not
expect a pre-upgrade archive from the current command. A future registered migration must create
and verify that archive before mutation.

If a future migration requires rollback, use the reported pre-upgrade backup and restore it to a
different new or empty path. Never restore over the original:

```bash
uv run bundlewalker workspace restore ./backups/knowledge-pre-upgrade.zip ./knowledge-restored
uv run bundlewalker workspace status ./knowledge-restored
(
  cd ./knowledge-restored
  uv run --project "$PROJECT_ROOT" bundlewalker lint
)
```

Inspect compatibility and deterministic lint, then switch consumers to the restored path only
after accepting the result. Retain the original workspace until that decision.

<a id="command-reference"></a>

## Complete CLI reference

Live `--help` output is authoritative for command names, arguments, and options. The public CLI
contains `doctor`, `init`, `ingest`, `ask`, `lint`, `review`, and `workspace`:

```bash
uv run bundlewalker --help
```

### `doctor`

```text
bundlewalker doctor [PATH] [--report REPORT.json]
```

`doctor` discovers a workspace from the current directory or an optional `PATH`, and reports
local health with fixed `PASS`, `WARN`, and `FAIL` lines followed by a summary. It is strictly
offline and read-only: it neither repairs workspace state nor contacts a model provider. Its one
explicit write is an opt-in support report requested with `--report`.

The fourteen stable check codes are `runtime.bundlewalker`, `runtime.python`,
`runtime.platform`, `workspace.discovery`, `workspace.configuration`,
`workspace.compatibility`, `workspace.structure`, `workspace.permissions`,
`configuration.model`, `configuration.credential`, `transactions.state`, `mcp.package`,
`mcp.entrypoint`, and `storage.disk`. Warnings exit `0`; failures exit `1`; an invalid report
target exits `2`.

```bash
bundlewalker doctor /path/to/workspace
bundlewalker doctor /path/to/workspace --report bundlewalker-support.json
```

The JSON report has schema version `1`. Its target must be a new regular file: existing files,
unsafe targets, and missing parents are rejected, and the command does not echo the destination.
On POSIX systems BundleWalker creates the file with mode `0600`; filesystem behavior on Windows is
experimental. If a write fails after creation, BundleWalker conservatively retains any partial
file. Portable macOS and Linux pathname APIs cannot atomically prove that the destination still
names the created inode, so automatic cleanup could delete an unrelated replacement.
Inspect and remove the newly created report target when appropriate before retrying.

The report excludes credentials, model values, workspace content, filesystem paths, host identity,
review and transaction identifiers, and exception or provider payloads. This is a bounded privacy
boundary, not a guarantee of zero disclosure risk: review even a redacted report before sharing
it. The OpenAI check maps only the presence of `OPENAI_API_KEY` for an `openai:` model; it does
not authenticate, verify a model, or test network reachability. Other providers receive an
unknown-provider warning. macOS and Linux are supported; Windows is experimental. The storage
check warns below the advisory 1-GiB free-space threshold and does not guarantee capacity for any
operation.

For a pending review, use `bundlewalker review show`, then `bundlewalker review apply
<REVIEW_ID>` or `bundlewalker review discard <REVIEW_ID>` after reviewing the result.

### `workspace`

```text
bundlewalker workspace status [PATH]
bundlewalker workspace backup OUTPUT [--workspace PATH]
bundlewalker workspace restore ARCHIVE TARGET
bundlewalker workspace upgrade [PATH] [--backup-dir DIRECTORY]
```

| Command | Arguments and options | Meaning |
| --- | --- | --- |
| `status` | optional `PATH` | Inspect format compatibility without mutation; defaults to discovery. |
| `backup` | required `OUTPUT`; optional `--workspace PATH` | Create and verify one absent archive outside a current workspace. |
| `restore` | required `ARCHIVE TARGET` | Verify and restore to a new or empty target without current-workspace discovery. |
| `upgrade` | optional `PATH`; optional `--backup-dir DIRECTORY` | Request an explicit registered migration; current format `1` is a no-op. |

Run `uv run bundlewalker workspace COMMAND --help` for the live signature. See
[Back up, restore, upgrade, and roll back](#back-up-restore-upgrade-and-roll-back) for procedures
and the [workspace compatibility policy](workspace-compatibility.md) for normative semantics.

### `init`

```text
bundlewalker init [OPTIONS] PATH
```

| Item | Value | Default | Meaning |
| --- | --- | --- | --- |
| `PATH` | path | required | New or empty workspace directory |
| `--conventions-style` | `default\|personal-workbook\|agent-context\|software-agent\|research-agent` | `default` | Initial editable conventions template |
| `--help` | — | — | Show command help |

See [Create a workspace](#create-a-workspace) for discovery, preset selection, lifecycle, and
initialization refusal behavior.

### `ingest`

```text
bundlewalker ingest [OPTIONS] FILE
```

| Item | Value | Default | Meaning |
| --- | --- | --- | --- |
| `FILE` | path | required | One regular UTF-8 `.md` or `.txt` source |
| `--model` | PydanticAI model string | `BUNDLEWALKER_MODEL` | Override the model for this invocation |
| `--help` | — | — | Show command help |

See [Ingest and review a source](#ingest-and-review-a-source) for limits, validation, review,
raw-byte persistence, and duplicate behavior.

### `ask`

```text
bundlewalker ask [OPTIONS] QUESTION
```

| Item | Value | Default | Meaning |
| --- | --- | --- | --- |
| `QUESTION` | text | required | Question or explicit refresh instruction |
| `--model` | PydanticAI model string | `BUNDLEWALKER_MODEL` | Override the model for this invocation |
| `--save` | flag | off | Propose one new Synthesis from the answer |
| `--refresh` | `SYNTHESIS_ID` | off | Propose an in-place replacement of one existing Synthesis |
| `--help` | — | — | Show command help |

`--save` and `--refresh` cannot be combined. See [Ask a cited question](#ask-a-cited-question),
[Save a Synthesis](#save-a-synthesis), and [Refresh a Synthesis](#refresh-a-synthesis) for their
read, create, and replace semantics.

### `lint`

```text
bundlewalker lint [OPTIONS]
```

| Option | Value | Default | Meaning |
| --- | --- | --- | --- |
| `--semantic` | flag | off | Add one read-only semantic advisory pass |
| `--model` | PydanticAI model string | `BUNDLEWALKER_MODEL` | Override the semantic model |
| `--help` | — | — | Show command help |

See [Maintain and recover the bundle](#maintain-and-recover-the-bundle) for deterministic status,
semantic advisories, and authenticated recovery.

### `review`

```text
bundlewalker review [OPTIONS] COMMAND [ARGS]...
```

| Command | Arguments | Meaning |
| --- | --- | --- |
| `show` | none | Print the single pending review ID, summary, and complete persisted diff. |
| `apply` | `REVIEW_ID` | Apply that exact current review after durable state revalidation. |
| `discard` | `REVIEW_ID` | Remove that exact pending review without changing live knowledge. |

Use these commands when an MCP host or an earlier process prepared a review, or when a process
ended before it resolved one. A wrong review ID never resolves the current review. If live content
changed after preparation, the review becomes stale: it remains inspectable but cannot apply;
discard it explicitly and prepare a new review.

## Use BundleWalker through a local MCP host

The MCP adapter is a local `stdio` server, not a hosted or remote service. It fixes one workspace
when the host starts it; no tool can select another workspace or accept a workspace path. Configure
the host with this exact command, replacing the placeholders with local absolute paths:

If your MCP host is Hermes Agent, follow the dedicated
[Hermes MCP setup guide](hermes-mcp-setup.md) for registration, tool filtering, provider-variable
forwarding, reload, and Hermes-specific troubleshooting.

```text
uv run --project PROJECT_ROOT bundlewalker-mcp --workspace WORKSPACE
```

For a command-and-arguments MCP configuration, the same launch is:

```json
{
  "command": "uv",
  "args": [
    "run",
    "--project",
    "PROJECT_ROOT",
    "bundlewalker-mcp",
    "--workspace",
    "WORKSPACE"
  ]
}
```

The optional `--workspace` is resolved once at startup; omitting it uses normal workspace discovery
from the server process's current directory. After startup, only MCP protocol messages use stdout.
Diagnostics use stderr or MCP logging. A local web UI is not implemented; it is a separate next
plan.

### Resources and review lifecycle

The server exposes Markdown concept resources through the template
`bundlewalker://concept/{+concept_id}`. Resource listing is ordered and paginated in pages of at
most 100 concepts: follow `nextCursor` to continue, and do not expect the stable pending-review
resource on later pages. When one exists, `bundlewalker://review/pending` is listed on the first
page and returns its exact persisted complete diff, review ID, kind, status, and summary. Raw
sources, arbitrary workspace files, transaction paths, and credentials are not resources.

The required write sequence is:

```text
prepare_ingestion | prepare_synthesis | prepare_refresh
    -> inspect get_pending_review or bundlewalker://review/pending
    -> apply_review REVIEW_ID | discard_review REVIEW_ID
```

Preparation creates at most one durable, private pending transaction under `.bundlewalker/`; it
does not change live `raw/` or `wiki/` content. The review and exact diff survive an MCP server
restart and can also be recovered with `bundlewalker review show`, `bundlewalker review apply
REVIEW_ID`, or `bundlewalker review discard REVIEW_ID`. A preparation that could create a new
review is rejected while one is pending, before provider work starts. Duplicate ingestion is the
pre-model exception: it may still return `duplicate` while an unrelated review is pending, but it
creates no review and calls no provider. A stale review remains inspectable but cannot apply; an
incorrect ID leaves the pending review untouched. Explicit discard is the way to free the slot.

MCP progress is deliberately coarse: model-backed question and preparation calls, and semantic
lint, may send one start and one completion notification when the client provides a progress token.
Cancellation before persistence leaves no review or accepted source. If
cancellation reaches the client after persistence, the durable review remains discoverable through
the pending-review tool, resource, or CLI recovery commands; inspect it before choosing apply or
discard.

### Tool reference

Every MCP input and output schema is a strict JSON object: unknown fields and invalid scalar types
are rejected, and successful calls return both structured content and a bounded text rendering.
`model`, where accepted, is an optional PydanticAI model string. The table lists the exact accepted
fields, structured result type, provider boundary, and state effect.

String limits are part of those schemas: `query` is 1–2,000 characters; `question` and
`instruction` are 1–20,000; `model` is 1–255; `source_name` is 1–255; inline `content` is at most
1,000,000; and `concept_id` is 1–4,096. Every complete `ReviewResult` includes its ID, kind,
pending-or-stale status, summary, complete diff, changed paths, creation time, and resource URI.

| Tool | Strict input fields | Structured result | Provider use | State effect |
| --- | --- | --- | --- | --- |
| `workspace_status` | none | `WorkspaceStatus` (name, config version, concept counts, optional review summary) | Never | Read-only. |
| `search_concepts` | `query`; optional `concept_type`; optional `limit` 1–10 (default 10) | `ConceptSearchResult` (concept summaries and resource URIs) | Never | Read-only lexical search. |
| `ask` | `question`; optional `model` | `AnswerResult` (validated cited answer and rendered Markdown) | Yes | Read-only. |
| `lint` | optional `semantic` and `model` | `LintResult` (findings and deterministic-error flag) | Only when `semantic` is true | Read-only. |
| `prepare_ingestion` | `source_name`, `content`; optional `model` | `IngestionResult` (`duplicate` or `pending` with optional `ReviewResult`) | For a new source; duplicates are pre-model | Creates only private pending state. |
| `prepare_synthesis` | `question`; optional `model` | `SynthesisResult` (answer plus required `ReviewResult`) | Yes | Creates only private pending state. |
| `prepare_refresh` | `instruction`, `concept_id`; optional `model` | `RefreshResult` (`current` or `pending`, answer, optional review) | Yes | Creates private pending state when changed; a current result creates none. |
| `get_pending_review` | none | `PendingReviewResult` (optional complete `ReviewResult`) | Never | Read-only. |
| `apply_review` | lowercase 32-hex-character `review_id` | `MutationResult` (`applied`) | Never | Mutates live content after revalidation. |
| `discard_review` | lowercase 32-hex-character `review_id` | `MutationResult` (`discarded`) | Never | Removes private pending state; never applies content. |

The annotations distinguish these boundaries too: `workspace_status`, `search_concepts`, and
`get_pending_review` are read-only, idempotent, closed-world tools; `ask` and `lint` are read-only
but non-idempotent, open-world tools; the three `prepare_*` tools are non-destructive,
non-idempotent, open-world private-state operations; and `apply_review` and `discard_review` are
non-idempotent, closed-world destructive operations. Annotations are hints, not authority: the
bound workspace, review ID, persisted review state, and digest revalidation enforce the boundary.

MCP ingestion is intentionally inline only. `source_name` must be one simple `.md` or `.txt`
filename, with no path separators or control characters; `content` is Unicode text whose UTF-8
encoding becomes the immutable accepted source. There is no `path`, local-file, batch, or
workspace-selection field in an MCP tool call.

The default test suite remains offline and needs no model credentials or network access:
`uv run pytest -m 'not eval' -q`. Provider access belongs only to the runtime model-backed tools
listed above (and to explicit opt-in evaluations), not to deterministic tests or MCP transport.

## Workspace and process reference

### Workspace layout and configuration

```text
my-knowledge/
├── bundlewalker.toml
├── conventions.md
├── raw/
│   └── <digest-prefix>-<source-slug>.(md|txt)
├── wiki/
│   ├── index.md
│   ├── log.md
│   ├── sources/
│   │   └── index.md
│   ├── topics/
│   │   └── index.md
│   ├── entities/
│   │   └── index.md
│   └── syntheses/
│       └── index.md
└── .bundlewalker/                  # appears when a reviewed write is staged
    ├── transaction.lock            # may remain while idle
    └── transactions/
        └── <id>/                   # exists only while staged or recovering
```

| Path or setting | Meaning |
| --- | --- |
| `bundlewalker.toml` | Versioned local configuration. It contains `wiki_dir`, `raw_dir`, `conventions_file`, and `max_source_characters`; it contains no model or credentials. |
| `conventions.md` | Editable local instructions supplied to model-backed operations. |
| `raw/` | Exact accepted source bytes. |
| `wiki/` | Portable OKF bundle and canonical compiled knowledge layer. |
| `wiki/index.md` and category `index.md` files | Deterministically generated navigation. |
| `wiki/log.md` | Newest-first record of accepted knowledge operations. |
| `.bundlewalker/` | Coordination and temporary authenticated transaction state; exclude it from the portable bundle. |

### Review outcomes

| Action | Process result | Knowledge result |
| --- | --- | --- |
| Answer `y` | Exit `0` after a successful commit | Apply the complete staged change |
| Answer `n` | Exit `0`; print `No changes applied.` | Discard staging; live knowledge stays unchanged |
| Press Ctrl-C | Exit `0`; print `No changes applied.` | Discard staging; live knowledge stays unchanged |
| End input at the prompt | Exit `0`; print `No changes applied.` | Discard staging; live knowledge stays unchanged |

`init` writes deterministic scaffolding without review. Plain `ask` and both lint modes do not
propose or persist new knowledge changes and open no review prompt. Before their normal work, each
may complete or roll back an already-reviewed interrupted transaction.

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success; duplicate-ingest or already-current refresh no-op; declined or interrupted review; or lint with only warnings and semantic advisories |
| `1` | Model/provider failure, invalid model output, source or OKF validation error, deterministic lint error, archive/backup/restore failure, migration-execution or verification failure, transaction failure, or unrecoverable workspace state |
| `2` | Command usage or configuration error, including a missing model, incompatible workspace/target, invalid restore target, or unavailable migration path |

Tracebacks are hidden by default. Errors report a concise primary cause without printing source
content or provider credentials.

### V3 producer limits and permissive reading

BundleWalker's v3 producer is deliberately stricter than its OKF reader. It generates only
Source, Topic, Entity, and Synthesis concepts; supports create and digest-protected replace
operations, not deletion; and confines generated concept paths to their matching `wiki/`
categories.

| Produced value | Limit |
| --- | --- |
| Drafts in one change set | 128 |
| Complete proposal text | 1,000,000 characters |
| Concept path | 240 characters |
| Title / description | 300 / 1,000 characters |
| Tags | 32 tags, 80 characters each |
| Draft or answer body | 128,000 characters |
| Citations | 100 per draft or answer |
| Change summary | 2,000 characters |

Existing OKF content is read permissively: a non-empty unknown concept type and unknown metadata
fields are accepted, and representable metadata extensions survive round-tripping. This allows
compatible external OKF extensions without letting v3 model proposals invent new producer types.
Broken internal links are warnings rather than parser failures. Refresh remains narrower: its
target must have exact type `Synthesis`, and metadata that must be re-produced has to fit the
producer bounds above.

### Git and privacy boundary

Git is recommended for reviewing and backing up `bundlewalker.toml`, `conventions.md`, `raw/`,
and `wiki/`, but BundleWalker performs no Git operations. Ignore temporary state:

```gitignore
.bundlewalker/
```

`raw/` intentionally preserves exact source bytes. Before publishing or pushing a workspace,
review it for personal, confidential, licensed, secret, or regulated material. A clean knowledge
diff does not make the underlying source safe to disclose.

## Troubleshooting and safety

### Workspace discovery fails

Change into the workspace root or a descendant and confirm that an ancestor contains a regular
`bundlewalker.toml`. `init` is the only command that skips discovery. See
[Create a workspace](#create-a-workspace).

### A model is required

Pass `--model '<pydantic-ai-model-string>'` or set `BUNDLEWALKER_MODEL`; the explicit option wins.
Check provider credentials without printing them. See
[Model and provider setup](#model-and-provider-setup).

### OpenAI returns 401 or 403

Confirm that `OPENAI_API_KEY` is set in the BundleWalker process and that the account can use the
selected current model. Do not print the key. Recheck the current catalog linked in the
[OpenAI example](#openai-example).

### Initialization refuses the target

Choose a path that does not exist or an existing empty directory. Do not remove an existing
workspace merely to bypass the check. See [Create a workspace](#create-a-workspace).

### A source is rejected

Check that it is one regular UTF-8 `.md` or `.txt` file and fits `max_source_characters`. URL,
PDF, image, audio, video, OCR, batch, and watched-directory ingestion are outside v3. See
[Ingest and review a source](#ingest-and-review-a-source).

### A proposal is rejected

No proposal content is persisted after validation failure. Use the concise error to check the
source, conventions, model, paths, citations, links, and producer bounds, then start a fresh
command. See [Ingest and review a source](#ingest-and-review-a-source) and
[Review outcomes](#review-outcomes).

### Semantic lint displays `ERROR` but exits `0`

Semantic severities are advisory; only deterministic errors control the lint process status. Run
plain `lint` to isolate deterministic health. See
[Maintain and recover the bundle](#maintain-and-recover-the-bundle).

### A Synthesis refresh is rejected

Use a canonical ID such as `syntheses/decision-framework`, without `.md`, and confirm the live
target has exact metadata type `Synthesis`. Do not combine `--refresh` with `--save`. If the page
changed during the operation, start again from current content. See
[Refresh a Synthesis](#refresh-a-synthesis).

### An earlier command was interrupted

Run `ingest`, `ask`, or `lint` again to invoke authenticated recovery. Preserve
`.bundlewalker/` and do not edit transaction manifests or staged trees by hand. See
[Maintain and recover the bundle](#maintain-and-recover-the-bundle).

### Git or publication may expose private material

BundleWalker never commits or pushes for you. Review durable files—especially exact bytes under
`raw/`—before sharing them, and ignore `.bundlewalker/`. See
[Git and privacy boundary](#git-and-privacy-boundary).
````

- [ ] **Step 3: Link the guide from the README**

In `README.md`, immediately after:

```markdown
```bash
uv sync --locked
uv run bundlewalker --help
```
```

insert:

```markdown
For installation, model setup, complete command examples, and conventions preset guidance, see
the [BundleWalker User Guide](docs/user-guide.md).
```

- [ ] **Step 4: Run the documentation contract and verify GREEN**

Run:

```bash
uv run python - <<'PY'
from __future__ import annotations

import re
from pathlib import Path

from typer.testing import CliRunner

from bundlewalker.cli import app
from bundlewalker.conventions import ConventionsStyle

guide_path = Path("docs/user-guide.md")
plan_path = Path("docs/superpowers/plans/2026-07-16-end-user-guide.md")
guide = guide_path.read_text(encoding="utf-8")
plan = plan_path.read_text(encoding="utf-8")
readme = Path("README.md").read_text(encoding="utf-8")

assert "[BundleWalker User Guide](docs/user-guide.md)" in readme
assert guide.startswith("# BundleWalker User Guide\n")

embedded_guide_start_marker = (
    "Create `docs/user-guide.md` with exactly:\n\n````markdown\n"
)
embedded_guide_end_marker = (
    "\n````\n\n- [ ] **Step 3: Link the guide from the README**"
)
assert plan.count(embedded_guide_start_marker) == 1
assert plan.count(embedded_guide_end_marker) == 1
embedded_start = plan.index(embedded_guide_start_marker) + len(
    embedded_guide_start_marker
)
embedded_end = plan.index(embedded_guide_end_marker, embedded_start)
embedded_guide = plan[embedded_start:embedded_end] + "\n"
assert embedded_guide == guide, "embedded end-user guide has drifted from docs/user-guide.md"

commands = ("init", "ingest", "ask", "lint")
runner = CliRunner()
root_help = runner.invoke(app, ["--help"])
assert root_help.exit_code == 0, root_help.output
for command in commands:
    assert command in root_help.output
    assert f"### `{command}`" in guide
    help_result = runner.invoke(app, [command, "--help"])
    assert help_result.exit_code == 0, help_result.output
    if command == "ask":
        assert "--refresh" in help_result.output

for option in (
    "--conventions-style",
    "--model",
    "--save",
    "--refresh",
    "--semantic",
    "--help",
):
    assert option in guide

documented_styles = {
    match.group(1)
    for match in re.finditer(
        r"^\| `(default|personal-workbook|agent-context|software-agent|research-agent)` \|",
        guide,
        re.MULTILINE,
    )
}
assert documented_styles == {style.value for style in ConventionsStyle}

headings = {
    re.sub(r"[^a-z0-9 -]", "", heading.lower()).replace(" ", "-")
    for heading in re.findall(r"^## (.+)$", guide, re.MULTILINE)
    if heading != "Contents"
}
contents_links = re.findall(r"^- \[[^]]+\]\(#([^)]+)\)$", guide, re.MULTILINE)
assert set(contents_links) == headings

assert "openai:gpt-5.6-luna" in guide
assert "replace-with-your-openai-api-key" in guide
assert "created when the first reviewed write is staged" in guide
assert "--refresh SYNTHESIS_ID" in guide
assert "Synthesis is already current; no changes applied." in guide
assert "sk-" not in guide
assert "\t" not in guide
assert guide.endswith("\n")
print("End-user guide contract passed.")
PY
```

Expected: `End-user guide contract passed.`

- [ ] **Step 5: Verify the OpenAI example against the locked runtime without credentials**

Run:

```bash
uv run python - <<'PY'
from pydantic_ai.models import infer_model
from pydantic_ai.providers.openai import OpenAIProvider

model = infer_model(
    "openai:gpt-5.6-luna",
    provider_factory=lambda provider: OpenAIProvider(
        api_key="documentation-example-not-a-real-key"
    ),
)

assert type(model).__name__ == "OpenAIResponsesModel"
assert model.model_name == "gpt-5.6-luna"
print("OpenAI example model string resolved without a network request.")
PY
```

Expected: `OpenAI example model string resolved without a network request.`

- [ ] **Step 6: Smoke-test the deterministic documented workflow**

Run:

```bash
project_root="$(pwd)"
temporary_root="$(mktemp -d)"

uv run bundlewalker init "$temporary_root/knowledge" --conventions-style research-agent
(
  cd "$temporary_root/knowledge/wiki/topics"
  uv run --project "$project_root" bundlewalker lint
)

test -f "$temporary_root/knowledge/bundlewalker.toml"
test -f "$temporary_root/knowledge/conventions.md"
rg -q '^# Research Agent Conventions$' "$temporary_root/knowledge/conventions.md"
```

Expected:

```text
Initialized BundleWalker workspace at <temporary path>/knowledge
No lint findings.
```

The three `test`/`rg` checks are silent and the command exits `0`.

- [ ] **Step 7: Run the complete offline verification suite**

Run:

```bash
git diff --check
uv run pytest -m 'not eval' -q
uv run ruff format --check src tests
uv run ruff check src tests
uv run pyright
```

Expected: the diff check is silent; all non-eval tests pass; Ruff reports every file formatted
and no lint errors; Pyright reports zero errors.

- [ ] **Step 8: Review scope and commit**

Run:

```bash
git status --short
git add docs/user-guide.md README.md
git diff --cached --check
git diff --cached --name-only
git commit -m "docs: add BundleWalker end-user guide"
```

Expected: exactly `README.md` and `docs/user-guide.md` are staged, the cached diff check is
silent, and the commit succeeds.
