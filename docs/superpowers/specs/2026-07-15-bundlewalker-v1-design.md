# BundleWalker v1: Local Personal Knowledge CLI

**Date:** 2026-07-15
**Status:** Design approved; implementation awaits written-spec review

## Summary

BundleWalker v1 is a local, provider-neutral CLI for building an accumulating personal knowledge base from Markdown and plain-text sources. It follows the persistent LLM-wiki pattern: immutable raw sources feed a maintained, interlinked wiki rather than being rediscovered through raw-document retrieval for every question.

The wiki is a standalone Open Knowledge Format (OKF) v0.1 bundle. PydanticAI agents propose typed semantic changes, but deterministic application code owns all paths, rendering, citations, validation, indexes, logs, diffs, confirmation, and persistence.

The four user-facing operations are:

```text
bundlewalker init PATH
bundlewalker ingest FILE [--model MODEL]
bundlewalker ask QUESTION [--model MODEL] [--save]
bundlewalker lint [--semantic] [--model MODEL]
```

## Source ideas

The design combines:

- [Karpathy's LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f): immutable sources, an agent-maintained persistent wiki, a co-evolving convention layer, index-first navigation, an append-only activity log, and periodic health checks.
- [Open Knowledge Format v0.1](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md): portable Markdown concepts with YAML frontmatter, path identity, standard links, optional `index.md` files, and optional `log.md` files.
- [PydanticAI](https://pydantic.dev/docs/ai/overview/): provider-neutral agents, dependency injection, typed tools and outputs, structured-output retries, fake/function models for tests, and optional evaluations.

## Goals

1. Create a useful local knowledge workspace with one command.
2. Ingest one UTF-8 Markdown or text source at a time.
3. Preserve the exact source bytes under a stable content identity.
4. Integrate new knowledge into existing Source, Topic, and Entity pages.
5. Show a complete proposed diff and require confirmation before every durable `raw/` or `wiki/` mutation derived from model output.
6. Answer questions from the compiled wiki with verifiable concept citations.
7. Optionally save an answer as a reviewed Synthesis page without another model call.
8. Validate OKF structure and wiki health without requiring an LLM.
9. Offer an opt-in, read-only semantic health pass for contradictions, staleness, unsupported claims, and knowledge gaps.
10. Keep the OKF bundle readable and useful without BundleWalker.

## Non-goals

The following are explicitly excluded from v1:

- URL, PDF, image, audio, video, or OCR ingestion.
- Batch ingestion and watched directories.
- Automatic chunking of book-sized sources.
- Embeddings, vector databases, SQLite catalogs, or background indexes.
- A web UI, Obsidian plugin, MCP server, or hosted service.
- Agent-authored deletions, renames, or automatic contradiction resolution.
- Multi-user synchronization and automatic Git operations.
- Custom producer taxonomies beyond the four v1 page types.

The OKF reader remains permissive and accepts unknown types even though BundleWalker's v1 producer does not generate them.

## Design principles

### The wiki is the durable knowledge artifact

`wiki/` is the canonical compiled knowledge layer. It is directly browsable, versionable, and portable. No database or hidden index is required to understand it.

### Raw sources are immutable

Every accepted ingestion stores an exact byte copy under `raw/`. Its SHA-256 digest supplies stable identity and duplicate detection. BundleWalker never edits a raw source after storing it.

### Models propose; deterministic code disposes

Agents have no write, rename, delete, shell, or arbitrary filesystem tools. They can list, search, and read concepts. Their only mutation-shaped output is a validated Pydantic model returned to the application.

### Review precedes mutation

The application renders a complete prospective wiki, validates it, and shows a unified diff before asking for confirmation. Rejection and Ctrl-C are normal unchanged outcomes.

### Consumption is permissive; production is strict

The OKF parser preserves unknown frontmatter and tolerates unknown concept types and broken links as required by the OKF consumer model. BundleWalker's agent-output models allow only the narrower v1 vocabulary and stricter citation rules.

## Workspace layout

```text
my-knowledge/
├── bundlewalker.toml
├── conventions.md
├── raw/
│   └── <sha-prefix>-<slug>.(md|txt)
├── wiki/                         # Standalone OKF bundle root
│   ├── index.md                  # Generated
│   ├── log.md                    # Generated
│   ├── sources/
│   │   ├── index.md              # Generated
│   │   └── <sha-prefix>-<slug>.md
│   ├── topics/
│   │   ├── index.md              # Generated
│   │   └── <topic-slug>.md
│   ├── entities/
│   │   ├── index.md              # Generated
│   │   └── <entity-slug>.md
│   └── syntheses/
│       ├── index.md              # Generated
│       └── <synthesis-slug>.md
└── .bundlewalker/                # Temporary transaction state only
    └── transactions/
```

`.bundlewalker/` is not knowledge and must be safe to delete when no transaction is active. It should be excluded from version control.

### `bundlewalker.toml`

The generated machine-readable configuration contains only local workflow settings:

```toml
version = 1
wiki_dir = "wiki"
raw_dir = "raw"
conventions_file = "conventions.md"
max_source_characters = 100000
```

Model identifiers and credentials are not written to workspace configuration.

### `conventions.md`

This generated, human-editable file is Karpathy's schema/instruction layer. It describes writing style, naming preferences, emphasis, and local wiki conventions. Every agent receives it as protected context. Agents may read it but cannot propose changes to it.

## OKF authoring profile

### Concept types

BundleWalker produces four types:

- `Source`: what one immutable source says, including summary, key claims, and provenance.
- `Topic`: accumulated knowledge about a general subject across sources.
- `Entity`: accumulated knowledge about a specific person, organization, place, product, work, or other named thing.
- `Synthesis`: a question-driven conclusion or comparison produced by `ask --save`.

Ingestion must propose exactly one Source page and may propose any number of Topic or Entity pages. It cannot create Synthesis pages. Only `ask --save` creates Synthesis proposals.

### Frontmatter

Every generated concept includes the OKF fields:

```yaml
---
type: Source | Topic | Entity | Synthesis
title: Human-readable title
description: One-sentence summary
tags: [short, normalized, tags]
timestamp: 2026-07-15T12:00:00Z
---
```

Source concepts additionally include BundleWalker extension fields:

```yaml
resource: urn:bundlewalker:source:sha256:<full-sha256>
source_sha256: <full-sha256>
raw_path: raw/<sha-prefix>-<slug>.<extension>
```

`raw_path` is a normalized, workspace-root-relative path rather than a path relative to the concept document. The full digest, not the filename prefix, is authoritative. If a prefix collision occurs, BundleWalker lengthens the prefix until the path is unique.

When parsing existing concepts, unknown fields are preserved during round-tripping.

### Paths

Concept IDs are their paths below `wiki/` without `.md`. BundleWalker generates normalized ASCII slugs, confines each produced type to its corresponding directory, resolves paths before use, and rejects absolute paths, `..`, symlink escapes, reserved filenames, and non-Markdown concept paths.

Agents return logical concept paths, but application code validates or derives final paths. Agents never choose raw-source destinations or generated-file paths.

### Citations

Source input is presented to the ingestion agent with stable one-based line numbers. Source-derived evidence uses a typed reference:

```text
EvidenceRef(source_id, start_line, end_line)
```

The application validates that spans are ordered and within the source. Topic and Entity bodies use numbered citation markers, and the renderer writes an OKF-compatible final section:

```markdown
# Citations

[1] [Source title](/sources/<source>.md) — raw lines 12–18
```

Every numbered marker in a generated body must have one structured citation, and every structured citation must be referenced by the body. Synthesis citations point to existing concepts read by the QueryAgent. BundleWalker verifies citation identity and access history; semantic faithfulness is measured by evaluations rather than claimed as a deterministic guarantee.

### Generated indexes and logs

Agents cannot create or edit `index.md` or `log.md`.

- Indexes are regenerated from directory contents and concept frontmatter. Entries use stable concept-ID ordering and include title plus description.
- A successful logical transaction prepends exactly one dated log entry summarizing its accepted creates and replacements.
- Index and log generation use an injectable clock so tests remain deterministic.

## Architecture

### Component boundaries

The Python package uses a `src/` layout and separates responsibilities:

- `cli`: command definitions, terminal rendering, confirmation, and exit-code mapping.
- `config`: workspace discovery, TOML loading, and model selection.
- `domain`: Pydantic boundary models and application errors.
- `okf`: frontmatter parsing/rendering, links, repository access, indexes, logs, and deterministic lint.
- `retrieval`: deterministic lexical ranking and bounded read-only tools.
- `agents`: agent factories, role instructions, typed outputs, and protected context assembly.
- `workflows`: orchestration for init, ingest, ask, and lint.
- `transactions`: staging, prospective validation, journaling, directory replacement, rollback, and recovery.

These modules communicate through typed domain values rather than terminal strings or raw model responses.

### Primary boundary models

#### `OkfDocument`

A permissive consumer model containing concept ID, metadata, body, and extracted links. Metadata requires a non-empty string `type` and preserves extra fields.

#### `DraftConcept`

A strict producer model containing operation, proposed path, v1 concept type, title, description, tags, complete Markdown body, structured citations, and an optional base digest for replacement.

Only `create` and `replace` operations exist in v1. Replacements carry the SHA-256 digest of the document version the agent read.

#### `ChangeSet`

A single reviewable proposal containing a purpose summary, source identity when applicable, and one or more DraftConcept values. It cannot contain duplicate paths, reserved paths, deletion operations, or changes outside `wiki/` concept directories.

#### `CitedAnswer`

Query output containing a suggested title, answer Markdown, and structured concept citations. Each citation must name an existing concept returned by a successful read tool call during the same agent run.

#### `LintFinding`

A shared finding shape containing origin (`deterministic` or `semantic`), severity, stable code, path when applicable, message, evidence paths, and optional remediation.

## Agent design

### Shared protected context

Deterministic code assembles four context layers:

1. Package-owned, versioned role and safety instructions.
2. Workspace-owned `conventions.md`.
3. The current root `index.md` for progressive disclosure.
4. Task material: numbered source text, the user's question, or deterministic lint signals.

Prompts never contain credentials. Workspace content is treated as untrusted data, not as higher-priority instructions.

### Shared tools

All agents receive only:

- `list_concepts(path)`: returns child concept metadata and directory entries.
- `search_concepts(query, type, limit)`: returns ranked metadata snippets.
- `read_concept(concept_id)`: returns one parsed concept and records that it was read.

Search returns at most ten results by default. Results and reads have explicit character budgets, and tool arguments are path-validated. No tool can access `raw/`, `.bundlewalker/`, arbitrary paths, the network, a shell, or write operations.

### IngestionAgent

The IngestionAgent receives one numbered source and read-only wiki tools. It returns a ChangeSet containing exactly one Source draft plus relevant Topic and Entity creates or replacements. It must preserve uncertainty, surface contradictions instead of silently choosing a winner, and attach source spans to source-derived claims.

### QueryAgent

The QueryAgent answers from compiled wiki concepts. It uses index-first lexical retrieval, reads the concepts it relies on, and returns a CitedAnswer. The application rejects missing citations, unread citations, and nonexistent paths.

With `--save`, deterministic code converts the already validated answer into a new Synthesis ChangeSet, derives a collision-safe slug, and sends it through the normal preview/confirmation transaction. There is no second model call.

### SemanticLintAgent

The SemanticLintAgent runs only for `lint --semantic`. It uses the same read-only tools and returns LintFinding values for contradictions, stale synthesis, unsupported claims, missing concepts, and promising knowledge gaps. Findings are advisory and never mutate the workspace.

### Model selection

For agent-backed commands, model selection precedence is:

1. `--model MODEL`
2. `BUNDLEWALKER_MODEL`

If neither exists, the command fails before calling an agent and explains how to configure one. Provider credentials remain the responsibility of PydanticAI providers and their environment variables.

Structured-output validation receives a fixed retry budget of two retries after the initial model response. Exhaustion produces an operational error and no knowledge changes.

## Retrieval

V1 uses no embeddings. Each command scans parsed concepts and computes a deterministic lexical score weighted in this order:

1. title
2. description
3. tags and concept path
4. body

Exact phrase matches outrank individual-term matches. Stable ties are ordered by concept ID. The root index is supplied initially; agents can then list, search, and selectively read. This supports the expected v1 scale of roughly hundreds of pages without introducing a second knowledge store.

The retrieval interface is intentionally replaceable so a future hybrid search implementation does not change workflows or agent contracts.

## Command workflows

### `bundlewalker init PATH`

1. Require a new or empty target directory; never overwrite an existing workspace.
2. Create configuration and default conventions.
3. Create `raw/` and the four wiki concept directories.
4. Generate all indexes and the initial log.
5. Run deterministic lint and roll back only the files and directories created by the command if initialization cannot produce a valid result.

The command needs no model configuration.

### `bundlewalker ingest FILE`

1. Recover any interrupted transaction before new work.
2. Resolve the input, require a regular `.md` or `.txt` file, read exact bytes, decode strict UTF-8, normalize only the in-memory numbered view, and enforce `max_source_characters`.
3. Compute SHA-256 and return a successful no-op if that full digest already exists in a Source concept.
4. Assemble protected context and run the IngestionAgent.
5. Validate the ChangeSet, paths, operation rules, replacement base digests, citation markers, and source line spans.
6. Render a prospective wiki, regenerate affected indexes, prepend one log entry, and run deterministic lint.
7. Show a change summary and unified diff.
8. Ask for confirmation. A negative answer or Ctrl-C removes staging and reports no changes applied.
9. Persist the raw source and prospective wiki using the transaction protocol.
10. Re-open and lint the committed wiki before reporting success.

### `bundlewalker ask QUESTION`

1. Recover interrupted transactions.
2. Require a non-empty question and configured model.
3. Supply the root index and read-only retrieval tools to the QueryAgent.
4. Validate that every cited concept exists and was read in the run.
5. Print the Markdown answer and citations.
6. Without `--save`, stop without writing.
7. With `--save`, render a Synthesis ChangeSet from the CitedAnswer and use the same prospective validation, diff, confirmation, and transaction workflow as ingestion.

### `bundlewalker lint`

Deterministic lint checks:

- UTF-8 and parseable frontmatter for all non-reserved Markdown files.
- Non-empty concept types while accepting unknown type values and fields.
- Reserved-file structure.
- Safe paths and case-folded path collisions.
- Markdown link syntax and bundle-relative target resolution.
- Broken internal links as warnings, consistent with permissive OKF consumption.
- Index completeness, descriptions, stable ordering, and stale entries.
- Log date-heading format and newest-first ordering.
- Source digest format, raw-file existence, and raw-byte digest agreement.
- Citation marker/reference agreement and valid source line ranges.
- Orphan concepts as warnings.

With `--semantic`, the SemanticLintAgent adds advisory findings after deterministic lint. Semantic findings do not alter the process exit code; only deterministic errors do. Lint never writes or auto-fixes in v1.

## Persistence and recovery

Filesystem APIs do not provide a portable atomic transaction across the top-level `raw/` and `wiki/` directories. BundleWalker therefore implements a crash-recoverable staged transaction and does not overstate it as globally atomic.

1. Copy the current wiki into `.bundlewalker/transactions/<id>/prospective-wiki/`.
2. Apply rendered concept changes there.
3. Regenerate derived files and validate the complete prospective bundle.
4. Recheck replacement base digests immediately before persistence.
5. Write and sync a transaction manifest with phase `prepared`.
6. Create the content-addressed raw copy with exclusive-create semantics. If it already exists, verify its full digest. Update and sync the manifest to `raw-persisted`.
7. Update and sync the manifest to `swapping` before any directory rename.
8. Rename the live wiki to a transaction backup, then rename the prospective wiki into the live path.
9. Update and sync the manifest to `new-live`.
10. Verify the live wiki, then remove the backup and transaction directory.

If any command finds an incomplete manifest, it recovers before other work:

- At `prepared` or `raw-persisted`, discard staging; an unreferenced raw copy is harmless and reusable.
- At `swapping`, inspect the live, backup, and prospective paths rather than trusting that a rename completed. If only the backup is present, restore it. If both live and backup are present, verify the live wiki and either complete the swap or restore the backup. If the original live wiki is still present and no backup exists, discard staging.
- At `new-live`, verify the new wiki; complete cleanup when valid or restore the backup when invalid.

Recovery operations are idempotent and covered by fault-injection tests at every phase boundary.

## Error behavior and exit codes

- Exit `0`: successful operation, duplicate-ingest no-op, user-declined proposal, Ctrl-C during review, or lint with warnings/advisory semantic findings only.
- Exit `1`: model/provider failure, exhausted structured-output retries, source/OKF validation error, deterministic lint error, transaction failure, or unrecoverable workspace state.
- Exit `2`: CLI usage or configuration error, following Typer conventions.

Errors use typed application exceptions. The CLI reports a concise primary message, the affected path or provider when useful, and a remediation hint. Tracebacks are hidden by default. No source content or provider credential is included in normal error output.

## Dependencies

Runtime dependencies are intentionally small:

- `pydantic-ai`
- `typer`
- `PyYAML`
- `markdown-it-py`

Development dependencies include pytest, appropriate async support, type checking, and lint/format tooling selected in the implementation plan.

## Testing strategy

### Deterministic unit tests

Cover permissive OKF parsing, unknown-field round-tripping, rendering, path safety, Markdown link extraction, index/log generation, lexical ranking, citation validation, duplicate detection, and every transaction recovery phase.

### Agent contract tests

Use PydanticAI fake or function models with no network. Cover:

- tool availability and path confinement;
- exact Source-page cardinality during ingestion;
- valid create and replace proposals;
- structured-output retry success and exhaustion;
- invented, nonexistent, unread, or out-of-range citations;
- the invariant that agent and validation failure cannot enter persistence.

### CLI integration tests

Use temporary workspaces to cover:

- successful initialization and immediate lint;
- ingest preview rejection and acceptance;
- Ctrl-C during review;
- duplicate ingestion;
- multi-page integration with generated index/log changes;
- cited questions and rejected citations;
- `ask --save` rejection and acceptance without a second inference;
- deterministic and semantic lint behavior;
- missing model configuration and exit codes;
- interrupted transaction recovery.

### Opt-in model evaluations

A small, versioned fixture corpus evaluates summary faithfulness, cross-source integration, contradiction recognition, and answer citation quality. Evals require an explicitly configured model, report model/provider identity, and do not run in default offline CI.

## Acceptance criteria

V1 is complete when all of the following are demonstrated by automated tests or an explicit opt-in evaluation:

1. `init` creates a workspace whose empty wiki passes deterministic lint.
2. Ingestion always shows a complete diff before changing live `raw/` or `wiki/` content.
3. Rejecting or interrupting review leaves the knowledge base unchanged.
4. Approved ingestion stores exact source bytes, creates one Source concept, updates relevant concepts, regenerates indexes, and adds one log entry.
5. Re-ingesting identical source bytes is a successful no-op.
6. `ask` returns citations only to existing concepts read during that query run.
7. `ask --save` creates a reviewable Synthesis proposal without another model call.
8. Deterministic lint requires no model; semantic lint is opt-in, advisory, read-only, and provider-neutral.
9. Interrupted persistence is completed or rolled back before another command performs work.
10. No default test requires credentials, network access, or paid inference.

## Future extension points

The following interfaces should remain replaceable without changing the v1 domain contracts:

- source readers, enabling later URL/PDF/media ingestion;
- retrieval, enabling hybrid lexical/vector search;
- renderer templates for domain-specific page conventions;
- transaction storage for more advanced multi-user systems;
- CLI presentation, enabling MCP, desktop, or web consumers;
- producer taxonomy, while retaining permissive OKF consumption.
