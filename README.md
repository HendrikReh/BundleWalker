# BundleWalker

BundleWalker is a local, review-first CLI for building a persistent personal knowledge wiki
from Markdown and plain-text sources. It follows the LLM-wiki pattern: immutable source bytes
feed a maintained, interlinked knowledge layer instead of being rediscovered for every
question. The resulting `wiki/` directory is a standalone Open Knowledge Format (OKF) v0.1
bundle that remains readable without BundleWalker.

PydanticAI agents propose typed changes and cited answers. Deterministic application code owns
paths, rendering, validation, indexes, logs, diffs, confirmation, and crash recovery. Agents
receive read-only list, search, and concept-read tools; they cannot write files, use a shell,
access arbitrary paths, or make network calls through BundleWalker tools.

## Install

BundleWalker requires Python 3.13 or newer and
[`uv`](https://docs.astral.sh/uv/). From this repository, install the locked environment:

```bash
uv sync --locked
uv run bundlewalker --help
```

For installation, model setup, complete command examples, and conventions preset guidance, see
the [BundleWalker User Guide](docs/user-guide.md).

`init` and deterministic `lint` need no model. Agent-backed commands resolve a model in this
order:

1. `--model MODEL`
2. `BUNDLEWALKER_MODEL`

Use any model string supported by your PydanticAI installation. Provider credentials are your
responsibility and remain in the provider's environment variables; BundleWalker does not write
credentials or model identifiers into the workspace.

## Copy-paste workflow

Replace the placeholder model string with one configured for your PydanticAI environment. This
session stays provider-neutral and creates the workspace inside the repository so `uv --project`
can keep using the checked-out application:

```bash
uv sync --locked
export BUNDLEWALKER_MODEL='<pydantic-ai-model-string>'

printf '%s\n' \
  'Reviewing a proposed change before persistence keeps durable knowledge inspectable.' \
  'Rejected proposals do not change the knowledge base.' > example-notes.txt

uv run bundlewalker init ./my-knowledge --conventions-style personal-workbook
cd ./my-knowledge

uv run --project .. bundlewalker lint
uv run --project .. bundlewalker ingest ../example-notes.txt
uv run --project .. bundlewalker ask 'Why review changes before persistence?'
uv run --project .. bundlewalker ask --save 'Why review changes before persistence?'
uv run --project .. bundlewalker lint --semantic
```

`ingest`, `ask --save`, and `ask --refresh` print a summary and complete prospective wiki diff,
then prompt before any model-derived knowledge is persisted. Answer `n`, press Ctrl-C, or end the
prompt to discard the proposal with a successful unchanged outcome. Saving or refreshing uses the
already validated answer; proposal preparation does not make a second model call.

## Commands

### Initialize a workspace

```bash
uv run bundlewalker init PATH [--conventions-style STYLE]
```

`PATH` must be new or empty. Initialization creates the configuration, conventions, raw-source
directory, four wiki categories, generated indexes, and initial log. The empty wiki is checked
with deterministic lint before the command succeeds. Initialization never needs a model.

`--conventions-style` chooses the initial, editable `conventions.md` template:

- `default`: the original concise, neutral BundleWalker conventions; this remains the default.
- `personal-workbook`: reflective, evidence-backed personal understanding and open questions.
- `agent-context`: general operational context, authority, constraints, procedures, and recovery.
- `software-agent`: repository maps, commands, architecture, invariants, validation, and traps.
- `research-agent`: methods, evidence quality, competing claims, limitations, and research gaps.

The choice is not stored as workspace metadata. After initialization, `conventions.md` is the sole
authority and may be customized freely. Examples:

```bash
uv run bundlewalker init ./personal-notes --conventions-style personal-workbook
uv run bundlewalker init ./operations --conventions-style agent-context
uv run bundlewalker init ./repository-context --conventions-style software-agent
uv run bundlewalker init ./research-context --conventions-style research-agent
```

### Ingest one text source

```bash
uv run bundlewalker ingest FILE [--model MODEL]
```

V1 accepts one regular UTF-8 `.md` or `.txt` file per invocation. The default maximum is exactly
100,000 Unicode characters. BundleWalker hashes the original bytes, stages one Source page plus
any proposed Topic or Entity changes, regenerates indexes and the log, lints the prospective
wiki, and shows the diff before confirmation. On acceptance, the original bytes are copied
unchanged into `raw/`. Re-ingesting identical bytes is a successful no-op and does not call a
model.

### Ask a cited question

```bash
uv run bundlewalker ask QUESTION [--model MODEL]
uv run bundlewalker ask --save QUESTION [--model MODEL]
uv run bundlewalker ask QUESTION --refresh SYNTHESIS_ID [--model MODEL]
```

Plain `ask` reads the compiled wiki and prints a Markdown answer with citations; it does not
write the workspace. Every citation must target an existing concept that the query run actually
read. `--save` converts that same validated answer into one create-only Synthesis proposal and
uses the normal diff and confirmation path. Query answers cite concepts, not raw-source line
spans; line spans are reserved for evidence citations created during ingestion.

`--refresh` revises one existing Synthesis in place from the explicit `QUESTION`. The target must
be a canonical ID such as `syntheses/decision-framework`, must exist, and must have exact metadata
type `Synthesis`; BundleWalker checks these requirements before resolving or calling a model.
`--save` and `--refresh` are mutually exclusive.

```bash
uv run bundlewalker ask \
  'Refresh this decision framework using the newer comparative evidence.' \
  --refresh syntheses/decision-framework
```

The existing Synthesis is supplied as untrusted revision context. One query-agent run returns a
complete replacement title, body, and citations to other live concepts read during that run.
The concept path remains stable. BundleWalker preserves existing description, tags, and metadata
extensions when they are present and representable; a missing description gets the normal saved-
answer fallback, and an accepted replacement receives the operation timestamp. It then shows the
full replacement diff; only acceptance updates the wiki, generated indexes, and `wiki/log.md`.
The target digest protects against concurrent edits, so a changed Synthesis is never silently
overwritten.

If the complete canonical replacement, including all rendered metadata, is already identical,
BundleWalker prints
`Synthesis is already current; no changes applied.` without opening a review prompt, creating
transaction state, changing a timestamp, or adding a log entry. A `SEM-STALE` advisory can suggest
that a refresh is worth reviewing, but semantic lint never starts or authorizes one automatically.

### Lint the knowledge bundle

```bash
uv run bundlewalker lint
uv run bundlewalker lint --semantic [--model MODEL]
```

Deterministic lint is offline and checks OKF parsing, safe paths, internal links, indexes, logs,
raw-source identity, citation structure, and orphan concepts. Broken links and orphans are
warnings; deterministic errors exit `1`.

`--semantic` runs an additional provider-neutral, read-only agent pass for contradictions,
staleness, unsupported claims, missing concepts, and knowledge gaps. Its findings are advisory:
even a semantic finding displayed as `ERROR` does not change the process status. Only
deterministic errors control lint's exit code. Before either pass, lint completes or rolls back
any authenticated interrupted BundleWalker transaction. This crash recovery is maintenance of
an already reviewed operation; lint never auto-fixes knowledge content.

## Workspace layout

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

`wiki/` is the portable OKF bundle and canonical compiled knowledge layer. `raw/` holds immutable
source bytes under content-derived identities. `bundlewalker.toml` contains local paths and the
source-size limit, but no model or credential settings.

`conventions.md` is the human-editable instruction and schema layer supplied to every agent. Use
it to state local writing style, naming, emphasis, and wiki conventions. Agents may read this
file but cannot propose edits to it.
The initialization presets are starting points only. BundleWalker does not remember, enforce, or
upgrade the selected style after creating the workspace.

`.bundlewalker/` is created when the first reviewed write is staged. It contains only temporary
transaction journals and a coordination lock. It is not knowledge content and is safe to delete
when no BundleWalker command or interrupted transaction is active.

## Exit codes

- `0`: success, duplicate-ingest no-op, declined/interrupted review, or lint with only warnings
  and semantic advisories.
- `1`: model/provider failure, invalid model output, source or OKF validation error,
  deterministic lint error, transaction failure, or unrecoverable workspace state.
- `2`: command usage or configuration error, including a missing model for an agent-backed
  command.

Tracebacks are hidden by default. Errors report a concise primary cause without printing source
content or provider credentials.

## Version control

Git is recommended for reviewing and backing up `bundlewalker.toml`, `conventions.md`, `raw/`,
and `wiki/`. BundleWalker performs no Git operations. Initialize and commit the repository
yourself, and ignore transaction state:

```gitignore
.bundlewalker/
```

Because `raw/` intentionally preserves exact personal source bytes, decide what is appropriate
to publish before pushing a knowledge workspace to any remote.

## V1 limits

Model-produced concept paths are exactly `<category>/<lowercase-ascii-slug>`. Per proposal,
BundleWalker accepts at most 128 drafts and 1,000,000 total proposal characters. Individual
draft and answer bodies are capped at 128,000 characters, titles at 300, descriptions at 1,000,
tags at 32 entries of 80 characters, and citations at 100. Semantic lint returns at most 100
findings. These limits are deliberately large enough for the intended hundreds-page local wiki
while bounding malformed provider output. Existing OKF concepts remain permissively readable,
including custom paths, unknown types, and extra frontmatter.

BundleWalker v1 intentionally excludes:

- URL, PDF, image, audio, video, and OCR ingestion;
- batch ingestion, watched directories, and automatic chunking of book-sized sources;
- embeddings, vector databases, SQLite catalogs, and background indexes;
- a web UI, Obsidian plugin, MCP server, or hosted service;
- agent-authored deletes, renames, convention edits, or automatic contradiction resolution;
- multi-user synchronization and automatic Git operations; and
- producer taxonomies beyond Source, Topic, Entity, and Synthesis.

The OKF reader remains permissive: it accepts unknown concept types and extra frontmatter even
though the v1 producer emits only those four page types.

## Development and opt-in evaluations

The default suite is offline and requires no credentials, network access, or paid inference:

```bash
uv run pytest -m 'not eval' -q
uv run ruff format --check src tests
uv run ruff check src tests
uv run pyright
```

The opt-in suite includes small live-model quality cases for faithful summarization, cross-source
topic updates, contradiction preservation, and cited answers. They are skipped unless an
evaluation model is explicitly selected:

```bash
BUNDLEWALKER_EVAL_MODEL='<pydantic-ai-model-string>' uv run pytest -m eval -v
```

Live evaluations use the selected provider and may incur network use or cost. They complement,
but never weaken or replace, the offline acceptance suite.
