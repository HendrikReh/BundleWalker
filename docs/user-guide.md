# BundleWalker User Guide

BundleWalker is a local, review-first command-line tool for turning Markdown and plain-text
sources into a persistent, interlinked knowledge wiki. PydanticAI agents propose knowledge
changes and cited answers, while deterministic application code controls validation, diffs,
confirmation, persistence, indexes, logs, and recovery.

This guide covers installation, model configuration, a first workflow, every supported command,
all available conventions presets, and common operating problems.

## Contents

- [What BundleWalker does](#what-bundlewalker-does)
- [Installation](#installation)
- [Model and provider setup](#model-and-provider-setup)
- [Five-minute quick start](#five-minute-quick-start)
- [Workspace discovery and layout](#workspace-discovery-and-layout)
- [Command reference](#command-reference)
  - [`init`](#init)
  - [`ingest`](#ingest)
  - [`ask`](#ask)
  - [`lint`](#lint)
- [Conventions presets](#conventions-presets)
- [Review and confirmation](#review-and-confirmation)
- [Exit codes](#exit-codes)
- [Troubleshooting and safety](#troubleshooting-and-safety)

## What BundleWalker does

BundleWalker maintains two complementary layers:

- `raw/` stores immutable copies of accepted source bytes under content-derived names.
- `wiki/` stores the compiled Open Knowledge Format (OKF) knowledge layer: Sources, Topics,
  Entities, Syntheses, indexes, and a change log.

The four supported commands form one operating loop:

| Command | Purpose | Model needed? | Writes knowledge? | Review prompt? |
| --- | --- | --- | --- | --- |
| `init` | Create an empty workspace | No | Creates the workspace | No |
| `ingest` | Propose knowledge from one source | Yes, unless the bytes are already ingested | Only after acceptance | Yes, for a new proposal |
| `ask` | Answer a cited question | Yes | No | No |
| `ask --save` | Answer and propose a Synthesis page | Yes | Only after acceptance | Yes |
| `lint` | Run deterministic wiki checks | No | No knowledge edits | No |
| `lint --semantic` | Add read-only semantic advisories | Yes | No knowledge edits | No |

BundleWalker never lets an agent write files directly. Agents receive read-only knowledge tools
and return typed proposals; deterministic code validates and stages those proposals before you
decide whether to apply them.

## Installation

BundleWalker requires Python 3.13 or newer and
[`uv`](https://docs.astral.sh/uv/). From the BundleWalker repository:

```bash
cd "/path/to/BundleWalker"
uv sync --locked
uv run bundlewalker --help
```

The examples in this guide use the repository checkout rather than a globally installed command.
When an example changes into a knowledge workspace, it passes the repository path to
`uv --project`.

## Model and provider setup

`init` and plain `lint` are deterministic and need no model. `ingest`, `ask`, and
`lint --semantic` need a PydanticAI model. Duplicate source bytes are detected before model
resolution, so a duplicate `ingest` is also model-free.

BundleWalker resolves an agent model in this order:

1. the command's `--model MODEL` option;
2. the `BUNDLEWALKER_MODEL` environment variable.

For provider-neutral setup, replace the placeholder with a model string supported by your
PydanticAI installation and export the provider's credential separately:

```bash
export BUNDLEWALKER_MODEL='<pydantic-ai-model-string>'
# Export the provider-specific API key required by that model.
```

See the [PydanticAI model documentation](https://ai.pydantic.dev/models/) for provider prefixes
and credential variables. BundleWalker does not store model identifiers or provider credentials
inside the workspace.

### OpenAI example

This is an example, not a BundleWalker default. Replace the credential placeholder with your
own key:

```bash
export OPENAI_API_KEY='replace-with-your-openai-api-key'
export BUNDLEWALKER_MODEL='openai:gpt-5.6-luna'
```

`openai:gpt-5.6-luna` tells PydanticAI to use OpenAI's Responses API provider with the
`gpt-5.6-luna` model. Check the
[OpenAI model catalog](https://developers.openai.com/api/docs/models) for current availability
and alternatives.

You can confirm that variables exist without printing their values:

```bash
uv run python - <<'PY'
import os

for name in ("OPENAI_API_KEY", "BUNDLEWALKER_MODEL"):
    print(f"{name}: {'SET' if os.getenv(name) else 'UNSET'}")
PY
```

Prefer a shell session, operating-system keychain, or secret manager appropriate to your
environment. Do not commit credentials.

## Five-minute quick start

Start at the BundleWalker repository root. The `PROJECT_ROOT` variable lets `uv` find this
project after you change into the new knowledge workspace.

```bash
uv sync --locked
PROJECT_ROOT="$(pwd)"

printf '%s\n' \
  'Reviewing a proposed change before persistence keeps durable knowledge inspectable.' \
  'Rejected proposals do not change the knowledge base.' > example-notes.txt

uv run bundlewalker init ./my-knowledge --conventions-style personal-workbook
cd ./my-knowledge

uv run --project "$PROJECT_ROOT" bundlewalker lint
uv run --project "$PROJECT_ROOT" bundlewalker ingest ../example-notes.txt
uv run --project "$PROJECT_ROOT" bundlewalker ask 'Why review changes before persistence?'
uv run --project "$PROJECT_ROOT" bundlewalker ask --save \
  'Why review changes before persistence?'
uv run --project "$PROJECT_ROOT" bundlewalker lint --semantic
```

`ingest` and `ask --save` show a summary and complete prospective wiki diff. Answer `y`
to persist the proposal or `n` to leave the workspace unchanged. Plain `ask` only prints an
answer. Semantic lint only prints advisories.

The three agent-backed operations use `BUNDLEWALKER_MODEL` from the current environment. You
may instead add `--model '<pydantic-ai-model-string>'` to an individual command.

## Workspace discovery and layout

Except for `init`, commands discover a workspace by searching from the current directory
upward for `bundlewalker.toml`. You can run commands from the workspace root or any descendant,
including a directory under `wiki/`.

A workspace has this layout:

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
│   ├── topics/
│   ├── entities/
│   └── syntheses/
└── .bundlewalker/  # created when the first reviewed write is staged
    ├── transaction.lock
    └── transactions/
```

- `bundlewalker.toml` contains local paths and the source-size limit, but no model or
  credential setting.
- `conventions.md` is the editable instruction and schema layer supplied to every agent.
- `raw/` holds exact accepted source bytes.
- `wiki/` is the portable OKF bundle and canonical compiled knowledge layer.
- `.bundlewalker/` is created when the first reviewed write is staged. It holds temporary
  transaction state and a coordination lock, not knowledge.

## Command reference

The top-level command lists the complete public interface:

```bash
uv run bundlewalker --help
```

### `init`

```text
bundlewalker init [OPTIONS] PATH
```

Creates a workspace at `PATH`. The path must be new or empty.

| Option | Value | Default | Meaning |
| --- | --- | --- | --- |
| `--conventions-style` | `default\|personal-workbook\|agent-context\|software-agent\|research-agent` | `default` | Initial editable conventions template |
| `--help` | — | — | Show command help |

`init` creates the configuration, conventions, raw-source directory, four wiki categories,
generated indexes, and initial log. It validates the empty wiki before success and never needs
a model or review prompt. Transaction state is created later when a reviewed write is staged.

```bash
uv run bundlewalker init ./knowledge
uv run bundlewalker init ./notes --conventions-style personal-workbook
```

Success prints the resolved workspace path:

```text
Initialized BundleWalker workspace at /resolved/path/to/knowledge
```

### `ingest`

```text
bundlewalker ingest [OPTIONS] FILE
```

Reads one regular UTF-8 `.md` or `.txt` file. By default, a source may contain at most
100,000 Unicode characters.

| Option | Value | Default | Meaning |
| --- | --- | --- | --- |
| `--model` | PydanticAI model string | `BUNDLEWALKER_MODEL` | Override the model for this invocation |
| `--help` | — | — | Show command help |

For new bytes, BundleWalker:

1. hashes the original file;
2. asks the model for one Source plus any Topic or Entity changes;
3. validates the typed proposal, citations, paths, links, prospective indexes, and log;
4. shows the summary and complete diff;
5. prompts for confirmation; and
6. on acceptance, copies the original bytes unchanged into `raw/` and commits the compiled
   wiki changes.

```bash
uv run --project "$PROJECT_ROOT" bundlewalker ingest ../meeting-notes.md
uv run --project "$PROJECT_ROOT" bundlewalker ingest ../research.txt \
  --model 'openai:gpt-5.6-luna'
```

Re-ingesting identical bytes is a successful no-op:

```text
Source already ingested; no changes applied.
```

The no-op happens before model resolution, so it neither needs nor calls a model.

### `ask`

```text
bundlewalker ask [OPTIONS] QUESTION
```

Searches and reads the compiled wiki, then prints a Markdown answer whose citations target
concepts read during that query.

| Option | Value | Default | Meaning |
| --- | --- | --- | --- |
| `--model` | PydanticAI model string | `BUNDLEWALKER_MODEL` | Override the model for this invocation |
| `--save` | flag | off | Propose a new Synthesis page from the validated answer |
| `--help` | — | — | Show command help |

Plain `ask` is read-only:

```bash
uv run --project "$PROJECT_ROOT" bundlewalker ask \
  'What evidence supports review before persistence?'
```

`--save` stages one create-only Synthesis proposal and uses the normal diff and confirmation
path:

```bash
uv run --project "$PROJECT_ROOT" bundlewalker ask --save \
  'What evidence supports review before persistence?'
```

Saving reuses the already validated answer; it does not make a second model call. Query answers
cite existing concepts, while evidence line spans belong to ingestion-created knowledge.

### `lint`

```text
bundlewalker lint [OPTIONS]
```

Runs deterministic wiki checks. Plain `lint` is offline and needs no model.

| Option | Value | Default | Meaning |
| --- | --- | --- | --- |
| `--semantic` | flag | off | Add one read-only semantic advisory pass |
| `--model` | PydanticAI model string | `BUNDLEWALKER_MODEL` | Override the semantic model |
| `--help` | — | — | Show command help |

```bash
uv run --project "$PROJECT_ROOT" bundlewalker lint
uv run --project "$PROJECT_ROOT" bundlewalker lint --semantic
uv run --project "$PROJECT_ROOT" bundlewalker lint --semantic \
  --model 'openai:gpt-5.6-luna'
```

Deterministic lint checks OKF parsing, safe paths, internal links, indexes, logs, raw-source
identity, citation structure, and orphan concepts. Broken links and orphans are warnings;
deterministic errors exit `1`.

`--semantic` runs an additional agent pass for contradictions, staleness, unsupported claims,
missing concepts, and knowledge gaps. Semantic findings are advisory. Even a semantic finding
displayed as `ERROR` does not control the process exit status; only deterministic errors do.

Before linting, BundleWalker completes or rolls back an authenticated interrupted transaction.
Recovery maintains an already reviewed operation and does not let lint auto-edit knowledge.

## Conventions presets

`--conventions-style` selects the initial `conventions.md` content during `init`.

| Style | Intended use | Knowledge emphasis | Example |
| --- | --- | --- | --- |
| `default` | General-purpose, neutral wiki | Concise facts, explicit uncertainty, conflicts, links, stable naming | `uv run bundlewalker init ./knowledge --conventions-style default` |
| `personal-workbook` | Reflective personal understanding | Evidence versus personal interpretation, provisional judgments, open questions, useful connections | `uv run bundlewalker init ./personal-notes --conventions-style personal-workbook` |
| `agent-context` | Context for operational AI agents | Authority, scope, preconditions, side effects, success criteria, failure handling, recovery, escalation | `uv run bundlewalker init ./operations --conventions-style agent-context` |
| `software-agent` | Context for coding and repository agents | Repository maps, exact commands, architecture boundaries, generated files, validation, security, compatibility, traps | `uv run bundlewalker init ./repository-context --conventions-style software-agent` |
| `research-agent` | Evidence synthesis and research planning | Claim type, provenance, methods, samples, timeframes, limitations, competing explanations, falsification | `uv run bundlewalker init ./research-context --conventions-style research-agent` |

### Choosing a preset

- Choose `default` for concise, neutral knowledge without a specialized operating voice.
- Choose `personal-workbook` when the wiki should separate sourced facts from your own
  interpretation and preserve how your thinking changes.
- Choose `agent-context` when another agent needs reliable operational rules, constraints,
  procedures, and recovery guidance.
- Choose `software-agent` for repository-specific context such as working directories,
  architecture, authoritative commands, invariants, validation, and known traps.
- Choose `research-agent` when methods, evidence quality, limitations, alternative
  explanations, and unresolved research gaps matter.

The preset is only a starting point:

- selection happens only during initialization;
- the style identifier is not stored in `bundlewalker.toml`, logs, or wiki metadata;
- BundleWalker does not enforce or upgrade the selected style later; and
- the generated `conventions.md` is fully editable and becomes the sole authority.

Edit `conventions.md` to add local writing, naming, evidence, and maintenance rules. Agents may
read this file, but BundleWalker does not let them propose changes to it.

## Review and confirmation

Model-backed writes share one review path:

1. the agent returns a typed proposal;
2. deterministic code validates a complete prospective workspace;
3. BundleWalker prints a summary and full diff;
4. you choose whether to apply it; and
5. accepted changes commit through a recoverable transaction.

| Action | Result |
| --- | --- |
| Answer `y` | Apply the staged changes |
| Answer `n` | Discard the proposal and print `No changes applied.` |
| Press Ctrl-C | Discard the proposal and exit successfully unchanged |
| End input at the prompt | Discard the proposal and exit successfully unchanged |

`init` writes deterministic scaffolding without a review prompt. Plain `ask`, plain
`lint`, and semantic lint do not propose knowledge changes. Lint may only complete or roll
back an authenticated transaction that was already reviewed before an earlier interruption.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success, duplicate-ingest no-op, declined or interrupted review, or lint with only warnings and semantic advisories |
| `1` | Model/provider failure, invalid model output, source or OKF validation error, deterministic lint error, transaction failure, or unrecoverable workspace state |
| `2` | Command usage or configuration error, including a missing model for an agent-backed operation |

Tracebacks are hidden by default. Errors report a concise primary cause without printing source
content or provider credentials.

## Troubleshooting and safety

### Workspace not found

`ingest`, `ask`, and `lint` must run from a workspace root or descendant. Change into the
workspace, or confirm that an ancestor contains `bundlewalker.toml`. `init` is the only
command that does not require workspace discovery.

### A model is required

Pass `--model '<pydantic-ai-model-string>'` to the command or set
`BUNDLEWALKER_MODEL`. The explicit option wins when both are present. Plain `lint` and
`init` do not use a model.

### OpenAI returns 401 or 403

Confirm that `OPENAI_API_KEY` is set in the process running BundleWalker and that the key has
access to the selected model. Do not print the key while diagnosing it. Model availability can
vary by account; consult the
[OpenAI model catalog](https://developers.openai.com/api/docs/models).

### Initialization refuses the target

Use a path that does not exist or an existing empty directory. BundleWalker will not initialize
over a non-empty directory or an existing workspace.

### A source is rejected

Version 1 accepts one regular UTF-8 `.md` or `.txt` file per invocation. The default limit is
100,000 Unicode characters. URL, PDF, image, audio, video, OCR, batch, and watched-directory
ingestion are not supported.

### A proposal is rejected

BundleWalker validates model output before showing or applying it. A failure can mean the
proposal used an unsafe path, invalid citation, broken link, incompatible source identity, or
malformed typed data. No proposal content is persisted when validation fails. Retry after
checking the source, conventions, selected model, and concise error message.

### Semantic lint reports an error but exits 0

Semantic severities are advisory by design. Only deterministic lint errors control the exit
status. Run plain `lint` to isolate deterministic health.

### An earlier command was interrupted

The next `ingest`, `ask`, or `lint` run authenticates the transaction journal and either
completes or rolls it back. Do not manually edit `.bundlewalker/transactions/` while recovering
an operation.

### Git and privacy

Git is recommended for reviewing and backing up `bundlewalker.toml`, `conventions.md`,
`raw/`, and `wiki/`, but BundleWalker performs no Git operations. Ignore temporary state:

```gitignore
.bundlewalker/
```

`raw/` intentionally preserves exact source bytes. Review personal, confidential, licensed,
or regulated material before pushing a knowledge workspace to any remote.
