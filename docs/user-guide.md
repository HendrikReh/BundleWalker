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
- [Complete CLI reference](#complete-cli-reference)
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

BundleWalker requires Python 3.13 or newer and [`uv`](https://docs.astral.sh/uv/). From a
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

Version 1 accepts one regular UTF-8 `.md` or `.txt` file per invocation. The default limit is
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

Ask the compiled wiki without changing it:

```bash
uv run --project "$PROJECT_ROOT" bundlewalker ask \
  'What evidence supports review before persistence?'
```

Plain `ask` is model-backed but read-only. The query can search and read live concepts, and a
read ledger records which concepts it actually opened. The returned Markdown answer is accepted
only when every citation targets an existing concept in that ledger. Query answers cite concepts,
not raw-source line spans; raw line spans belong to ingestion-created evidence citations.

The command prints the validated answer and citations, opens no review prompt, and writes no
knowledge. A missing model is a configuration error; an invalid or unread citation is a model or
validation failure, also without a write.

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

`--semantic` runs one additional read-only model-backed pass for contradictions, staleness,
unsupported claims, missing concepts, and knowledge gaps. Semantic findings may use `ERROR`,
`WARNING`, or `INFO` display severities, but all are advisory. They do not control process status;
only deterministic errors do. Semantic lint proposes and writes no knowledge.

Before `ingest`, `ask`, or either lint mode continues, BundleWalker inspects interrupted
transactions. It authenticates the reviewed base and prospective trees, then safely completes or
rolls back the interrupted operation. Recovery preserves an operation that was already reviewed;
it never authorizes new model output.

`.bundlewalker/` appears when the first reviewed write is staged. Completed and discarded work
removes its per-operation transaction directory. In an idle workspace, `transaction.lock` may be
the only retained file; `transactions/` may remain as an empty directory. The lock is normal
coordination state, not a pending write. If recovery fails, stop and preserve `.bundlewalker/`
for diagnosis rather than editing its manifests or staged trees.

<a id="command-reference"></a>

## Complete CLI reference

Live `--help` output is authoritative for command names, arguments, and options. The public CLI
contains only `init`, `ingest`, `ask`, and `lint`:

```bash
uv run bundlewalker --help
```

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
propose knowledge changes. Lint may only recover a write reviewed before an interruption.

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success; duplicate-ingest or already-current refresh no-op; declined or interrupted review; or lint with only warnings and semantic advisories |
| `1` | Model/provider failure, invalid model output, source or OKF validation error, deterministic lint error, transaction failure, or unrecoverable workspace state |
| `2` | Command usage or configuration error, including a missing model for a model-backed operation |

Tracebacks are hidden by default. Errors report a concise primary cause without printing source
content or provider credentials.

### V1 producer limits and permissive reading

BundleWalker's v1 producer is deliberately stricter than its OKF reader. It generates only
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
compatible external OKF extensions without letting v1 model proposals invent new producer types.
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
PDF, image, audio, video, OCR, batch, and watched-directory ingestion are outside v1. See
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
