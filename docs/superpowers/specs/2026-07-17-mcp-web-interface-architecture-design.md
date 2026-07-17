# MCP and Local Web Interface Architecture

**Date:** 2026-07-17
**Status:** Design approved; implementation awaits written-spec review

## Summary

BundleWalker will evolve from a CLI-oriented modular monolith into a local application with three
first-party delivery adapters: the existing CLI, a local MCP server delivered first, and a local
web UI delivered second. The adapters will share one workspace-bound application facade and the
existing deterministic knowledge, validation, OKF, and transaction engines.

The central new application concept is a durable pending review. Model-backed preparation and
acceptance become separate operations. Preparation may create private transaction state but never
changes live `raw/` or `wiki/` content. A later explicit apply operation commits the exact reviewed
proposal. One workspace may have at most one pending review, and that review can be prepared,
inspected, applied, or discarded through any first-party adapter.

The first MCP release uses local `stdio`, is bound to one workspace at process startup, accepts
inline UTF-8 source content rather than arbitrary filesystem paths, and exposes the full existing
workspace capability set except initialization. The later web UI runs as a separate, explicitly
launched, loopback-only process and calls the same application facade directly rather than routing
through MCP or recreating orchestration.

## Context

BundleWalker currently has useful module-level separation:

- `cli.py` owns Typer parsing, terminal rendering, review prompts, and exit mapping;
- `workflows/` orchestrates agents, repository reads, validation, and transaction preparation;
- `agents/`, `domain.py`, `changes.py`, `okf/`, and `retrieval.py` implement the knowledge engine;
- `transactions.py` stages, validates, commits, discards, and recovers filesystem transactions;
- `workspace.py` owns workspace discovery, configuration, source loading, and safe paths.

The write flow is already structurally sound:

```text
CLI -> workflow -> model proposal -> deterministic validation
    -> prospective tree -> complete diff -> confirmation -> transaction commit
```

The interface limitation is that review lifecycle is still partly a CLI concern. Workflows return
in-memory `PreparedTransaction` handles, the CLI immediately prints and resolves them, and normal
recovery removes a merely prepared transaction. That works for a single synchronous command but
cannot support separate MCP prepare/apply calls or an MCP-to-web review handoff.

The accepted v1 design already names source readers, retrieval, transaction storage, and CLI
presentation as future extension points. This design realizes the presentation extension without
turning BundleWalker into a hosted service or general plugin platform.

## Goals

1. Add an interface-neutral application boundary without rewriting the existing knowledge core.
2. Preserve the rule that models propose and deterministic code validates and persists.
3. Preserve complete review before every model-derived live knowledge mutation.
4. Support a two-step prepare/apply contract across process restarts.
5. Allow MCP and the later web UI to share one workspace-level pending review.
6. Expose full workspace capability through a local, workspace-bound MCP server.
7. Keep MCP source ingestion confined to explicitly supplied inline UTF-8 content.
8. Reuse the same application use cases for CLI, MCP, and web.
9. Preserve existing CLI command behavior, offline tests, and bounded public errors.
10. Deliver the MCP adapter before the local web UI.

## Non-goals

- A hosted or remotely accessible BundleWalker service.
- A background daemon shared by independent clients.
- MCP Streamable HTTP transport in the first MCP release.
- Remote web access, multi-user authorization, or workspace synchronization.
- A third-party plugin SDK, command bus, event bus, or dynamic handler discovery.
- New source formats, path-based MCP ingestion, batch ingestion, or watched directories.
- Replacing the filesystem-backed OKF bundle with a database.
- Replacing lexical retrieval or changing the v1 producer taxonomy.
- Depending on experimental MCP durable tasks for BundleWalker review state.
- Exposing raw sources, arbitrary workspace files, transaction paths, or credentials as MCP
  resources.

## Approaches considered

### Thin interface wrappers

MCP and web could call current workflows and transaction functions directly. This is the smallest
MCP prototype, but each adapter would need to coordinate review, rendering, error translation,
recovery, and transaction handles. The web UI would become a second orchestration layer, and
internal filesystem-oriented values would leak into interface contracts.

### Application facade with delivery adapters

CLI, MCP, and web call a workspace-bound application facade that owns complete use cases and
returns serializable contracts. Existing knowledge modules remain concrete internal components.
The facade owns the pending-review lifecycle and exposes opaque review IDs instead of transaction
paths or handles.

This is the selected approach. It creates the boundary needed by two new interfaces while
preserving the modular monolith and allowing incremental migration.

### Command bus and plugin kernel

A command/query bus, handler discovery, and event stream would maximize replaceability and make a
future plugin system natural. It would also introduce public versioning, discovery, and tracing
problems before BundleWalker needs third-party extensions. It is rejected for this scope.

## Target architecture

```text
┌────────────────┐  ┌────────────────┐  ┌────────────────┐
│ CLI adapter    │  │ MCP adapter    │  │ Web adapter    │
│ Typer/terminal │  │ local stdio    │  │ local HTTP/UI  │
└───────┬────────┘  └───────┬────────┘  └───────┬────────┘
        └──────────────┬─────┴──────────────┬────┘
                       │ typed requests/results
              ┌────────▼────────────────────▼───────┐
              │ WorkspaceApplication facade        │
              │ use cases + errors + review state  │
              └────────┬────────────────────┬───────┘
                       │                    │
       ┌───────────────▼──────────┐  ┌──────▼──────────────┐
       │ Existing knowledge core │  │ Review/transaction  │
       │ agents, OKF, retrieval,  │  │ persistence, locks, │
       │ validation, rendering    │  │ commit and recovery │
       └───────────────┬──────────┘  └──────┬──────────────┘
                       └────────────┬────────┘
                                    ▼
              workspace files: conventions.md, raw/, wiki/,
              and private .bundlewalker/ transaction state
```

### Package direction

The target shape is:

```text
src/bundlewalker/
├── application/
│   ├── facade.py       # WorkspaceApplication and use-case coordination
│   ├── contracts.py    # strict serializable request/result models
│   └── reviews.py      # pending-review lifecycle and error mapping
├── interfaces/
│   ├── cli.py          # existing CLI migrated behind the facade
│   ├── mcp.py          # first new adapter
│   └── web/            # second new adapter
├── agents/             # retained knowledge component
├── okf/                # retained OKF component
├── workflows/          # retained while orchestration migrates behind application
├── changes.py          # retained deterministic proposal validation/rendering
├── retrieval.py        # retained retrieval implementation
├── transactions.py     # retained engine with persistent review-ID operations
└── workspace.py        # retained workspace and safe-path implementation
```

Interfaces import `application`; application code never imports an interface. Application code may
call the existing workflows during migration, but no adapter may bypass the facade for a complete
user use case. Agents, repositories, filesystem paths, transaction directories, and
`PreparedTransaction` objects are private implementation details.

The architecture does not add an abstract interface around every existing module. Repository,
retrieval, agent, OKF, and transaction implementations stay concrete unless a separate accepted
feature requires replacement. The new boundary is selective: delivery inputs, serializable
results, errors, and durable review identity.

## Application facade

`WorkspaceApplication` is constructed for one discovered and validated `Workspace`. All facade
methods are async so CLI, MCP, and web consume one calling convention; deterministic internals may
remain synchronous behind that boundary. Its public use cases are:

- workspace status;
- paginated concept listing, concept reading, and lexical search;
- cited question answering;
- deterministic lint and optional semantic lint;
- preparing ingestion from an application source value;
- answering and preparing a saved Synthesis in one operation;
- answering and preparing a Synthesis refresh in one operation;
- reading the current pending review;
- applying a pending review by opaque ID; and
- discarding a pending review by opaque ID.

Initialization remains outside a workspace-bound application instance. The existing `init` CLI
command continues to call deterministic workspace initialization.

### Boundary contracts

Strict Pydantic application models provide bounded, serializable values suitable for Python, MCP
structured output, and later JSON responses. The contracts include:

- `InlineSource`: a simple source filename and UTF-8 text content;
- `WorkspaceStatus`: safe workspace display name, configuration version, concept counts, and
  pending-review presence;
- `ConceptSummary` and `ConceptContent`: bounded concept metadata and rendered Markdown;
- `AnswerResult`: title, body, and validated structured citations;
- `LintResult`: deterministic and optional semantic findings plus deterministic error status;
- `ReviewResult`: opaque ID, kind, status, summary, exact complete diff, changed concept paths,
  creation time, and review-resource URI; and
- `MutationResult`: the resolved review ID and applied or discarded outcome.

Contracts do not contain absolute paths, repository objects, model objects, agent dependencies,
transaction directories, or unbounded provider errors.

### Source normalization

The CLI path reader and MCP inline reader normalize different delivery inputs into one internal
source value before the ingestion use case continues.

For MCP, `source_name` must be one simple filename with no path separators, control characters,
or reserved dot name, and must use a currently supported `.md` or `.txt` suffix. `content` is a
bounded Unicode string encoded as UTF-8 by the application. Those resulting bytes are the exact
bytes hashed, staged, and stored if the review is accepted. The existing stable raw-path,
duplicate-digest, character-limit, line-numbering, and citation rules remain authoritative.

MCP tools never accept a local path. CLI path ingestion retains its existing safe regular-file
behavior.

## Durable pending reviews

### Invariants

1. A workspace has zero or one pending review.
2. A pending review has one opaque, unguessable transaction ID.
3. Preparation does not mutate live `raw/` or `wiki/` content.
4. The exact displayed summary and complete diff are persisted with the prospective tree and
   covered by transaction integrity metadata.
5. Apply and discard require the exact current review ID.
6. Apply revalidates the live base, prospective tree, raw payload, and operation digests.
7. A stale proposal is never rebased or regenerated silently.
8. Read-only operations remain available while a review is pending.
9. A second write preparation is rejected until the pending review is resolved.
10. A pending review can be inspected or resolved through any first-party adapter.

### Persistent state

The existing private transaction directory remains the persistence location. The next transaction
schema persists the review summary, complete diff, creation time, proposal kind, changed paths,
base and prospective digests, raw payload identity when applicable, and an integrity digest for
the review metadata. Application results reconstruct from persisted state rather than relying on
an in-memory `PreparedTransaction` created by the same process.

The exact on-disk filenames remain an implementation detail, but all persisted paths stay confined
below `.bundlewalker/transactions/<transaction-id>/` and use the existing safe-path and no-symlink
rules.

### State machine

```text
None --prepare--> Pending --apply--> Accepted/committing --recover--> Applied or rolled back --> None
                         \
                          --discard-----------------------------------------------> None

Pending --live base changes--> Stale pending --discard--> None
```

`stale` is a reported pending-review condition derived from base and operation revalidation. A
stale proposal stays inspectable but cannot be applied. It continues to occupy the one pending
slot until explicitly discarded.

Apply first persists the acceptance transition before beginning the live mutation sequence. Once
accepted, interruption recovery retains the existing authenticated completion-or-rollback
guarantee. A normal application startup or read-only use case preserves a valid `Pending` review;
it recovers only accepted or later commit phases.

The transaction schema version increases. A legacy schema-v1 `prepared` transaction was created
for an immediate CLI prompt and does not become a newly durable review after upgrade. It follows
the existing v1 safe cleanup/recovery semantics. Only the new schema can represent a durable
pending review or persisted acceptance decision.

### Concurrency

Preparation checks for an existing review before any model call so the common busy case does not
incur provider work. Model execution does not hold the cross-process workspace lock. Immediately
before persisting a completed proposal, transaction preparation acquires that lock and rechecks
the zero-or-one invariant. If another process won the race, the later preparation returns
`review_pending` and does not create a second review. This rare race may perform redundant model
work but cannot create conflicting durable state or mutate live knowledge.

Apply and discard operate under the same workspace transaction lock. Applying one review cannot
silently affect another because no second pending review is allowed.

## Adapter behavior

### CLI

Existing commands, prompt wording, complete diff display, confirmation semantics, exit codes,
duplicate/no-op behavior, and Ctrl-C behavior remain compatible. Model-derived writes route
through the application facade:

1. prepare the review;
2. render its persisted summary and exact diff;
3. prompt immediately;
4. apply on acceptance or discard on rejection and Ctrl-C.

Additive `bundlewalker review show`, `bundlewalker review apply REVIEW_ID`, and
`bundlewalker review discard REVIEW_ID` operations let CLI-only users recover a review left
pending by abrupt process termination or prepared through another adapter. A write command that
finds an existing review reports its safe ID and directs the user to the review operations.

### MCP transport and process model

The first MCP release uses the official Python SDK and local `stdio`. The MCP host launches the
separate `bundlewalker-mcp` entry point for one workspace. Its optional `--workspace PATH` startup
argument defaults to normal discovery from the process working directory. The selected workspace
is resolved and validated once before the server starts. No MCP request may switch workspaces or
supply a workspace path.

Only protocol messages are written to stdout. Diagnostics and logs use stderr or MCP logging.
Credentials and the default model remain environment configuration. Model-backed tools may accept
the same bounded optional model selector as the CLI, but never credentials.

The implementation does not require experimental MCP durable tasks. Model-backed tool calls send
standard progress notifications when the client supplies a progress token and honor request
cancellation. Cancellation before durable review persistence removes temporary preparation state
and leaves no review. If cancellation or transport loss occurs after persistence, the pending
review remains discoverable and must be applied or discarded normally. BundleWalker pending
reviews remain the authoritative durable human-review state.

### MCP resources

The server exposes OKF concepts as paginated, read-only resources using the URI template
`bundlewalker://concept/{+concept_id}`, where `concept_id` is the existing extensionless OKF path.
Each page contains at most 100 concepts and uses an opaque cursor. Resource reads go through the
application facade. Search results may return links to these resources.

When present, the pending review is readable through a stable
`bundlewalker://review/pending` resource containing the exact persisted summary and complete diff.
The resource disappears after apply or discard. Resource subscriptions and list-change
notifications are excluded from the first MCP milestone.

Raw sources, conventions, workspace configuration, generated transaction files, and arbitrary
filesystem paths are not MCP resources.

### MCP tools

The first MCP release exposes:

| Tool | Application effect | Annotation intent |
| --- | --- | --- |
| `workspace_status` | Inspect workspace and pending-review presence | read-only, closed-world |
| `search_concepts` | Lexically rank bounded concept summaries | read-only, closed-world |
| `ask` | Run a cited model-backed query without persistence | read-only, open-world |
| `lint` | Run deterministic and optionally semantic lint | read-only, open-world |
| `prepare_ingestion` | Create one private pending ingestion review | non-read-only, non-destructive, open-world |
| `prepare_synthesis` | Answer and create one private pending Synthesis review | non-read-only, non-destructive, open-world |
| `prepare_refresh` | Revise and create one private pending refresh review | non-read-only, non-destructive, open-world |
| `get_pending_review` | Inspect the current review | read-only, closed-world |
| `apply_review` | Commit reviewed creates or replacements | destructive, closed-world |
| `discard_review` | Delete private staged review state | destructive, closed-world |

Tool annotations are descriptive hints for clients, not authorization or safety enforcement.
Every tool has strict JSON input and output schemas. Successful results contain bounded
human-readable content and typed `structuredContent`. Review preparation results include the exact
complete diff and a link to the pending-review resource.

Domain and input failures return MCP tool execution errors so a model can correct its request.
Malformed protocol messages remain protocol errors.

### Local web UI

The web milestone adds an explicitly launched command that starts one process for one workspace.
It binds an ephemeral port on `127.0.0.1`, opens the browser, and serves the UI and a small local
JSON API from the same process. It is not a persistent daemon and has no remote-bind option in this
scope.

The web adapter calls `WorkspaceApplication` directly. It does not call the MCP adapter and does
not duplicate workflows. It renders concept navigation, answers, lint findings, progress, errors,
and the exact pending-review diff. A review prepared through MCP is immediately available when the
web process opens the same workspace.

The local server creates a 256-bit random secret and opens a loopback bootstrap URL containing that
secret. The bootstrap exchanges it for an `HttpOnly`, `SameSite=Strict` session cookie and redirects
to remove the secret from the address bar and browser history entry. Every request validates the
exact launch Host; browser API requests validate the exact launch Origin; and state-changing
requests also require a session-bound CSRF token. The UI serves no third-party scripts or assets.
It never trusts loopback location alone as authorization. Framework and asset-tooling choices are
made in the implementation plan without changing the application contracts in this design.

## Errors

The application boundary translates existing internal exceptions into a stable bounded shape:

```text
code + safe message + retryable flag + optional review ID
```

The initial closed set of error codes is `invalid_input`, `configuration_error`, `workspace_error`,
`concept_not_found`, `okf_error`, `change_invalid`, `model_failed`, `review_pending`,
`review_not_found`, `review_id_mismatch`, `review_stale`, and `transaction_failed`. Duplicate source
and unchanged refresh remain successful typed outcomes rather than errors. Safe messages never
include source bodies, protected prompt context, credentials, provider payloads, or uncontrolled
paths. Adding another code later is an application-contract change that requires tests and adapter
mapping.

Adapters map the stable application error without parsing prose:

- CLI retains current bounded messages and exit-code classes;
- MCP returns a tool execution error with structured error content; and
- web maps the same code to an appropriate local HTTP response and explicit UI state.

Unexpected defects remain distinct from correctable domain errors and are logged only through the
adapter's safe diagnostic channel.

## Security and trust boundaries

- Models retain read-only knowledge tools and typed outputs; they never receive filesystem,
  transaction, apply, discard, shell, or interface tools.
- The server is bound to one validated workspace at startup.
- MCP tool inputs cannot name workspace paths or local source paths.
- Inline source name, extension, content, byte/character count, and line count are bounded and
  validated before model use.
- Workspace and source content remain explicitly framed as untrusted model data.
- Review IDs are opaque capabilities but are not the only control: state, workspace confinement,
  base identity, prospective identity, raw identity, and operation digests are revalidated.
- Host tool approval and MCP annotations are additive UX signals and cannot bypass BundleWalker
  review rules.
- Stale reviews are not automatically rebased, refreshed, or committed.
- MCP `stdio` introduces no listener. The later web listener is loopback-only and still uses
  session, Host, Origin, and CSRF defenses.
- Public output and errors retain existing producer limits and sanitization. The complete review
  diff is preserved because full review is a product invariant.
- Default tests remain offline and credential-free.

## Delivery sequence

### 1. Durable review foundation

Version the transaction schema, persist exact review metadata and diff integrity, add review-ID
loading, enforce one pending review, record acceptance durably, and split pending preservation from
interrupted-commit recovery. Keep compatibility wrappers while existing transaction and workflow
tests migrate.

### 2. Application facade and CLI migration

Add strict request/result models, stable application errors, and the workspace-bound facade. Route
the existing CLI through it and add the recovery-oriented `review` operations. Existing CLI
behavior is the compatibility oracle.

### 3. MCP server

Add the official Python SDK, the `bundlewalker-mcp` workspace-bound `stdio` entry point, concept and
review resources, the full tool set, structured results, annotations, error mapping, standard
progress/cancellation behavior, and protocol integration tests. Inline UTF-8 is the only MCP
ingestion input.

### 4. Local web UI

Add the loopback-only web adapter, browser UI, local session defenses, rich review rendering, and
cross-adapter handoff tests. The web milestone consumes the already proven application facade and
does not change review semantics.

## Testing strategy

### Transaction and recovery tests

- Pending review survives process restart and remains byte-identical.
- The exact summary and diff fail integrity validation if partially corrupted.
- Accepted interruption at every persisted commit phase completes or rolls back safely.
- Pending state is not mistaken for an interrupted accepted commit.
- A stale live base or replacement digest rejects apply without changing live content.
- Two competing preparations produce exactly one pending review.
- Legacy schema-v1 transactions retain safe historical recovery behavior.

### Application contract tests

- Every facade use case returns the documented strict result type.
- Inline source validation rejects paths, unsupported suffixes, invalid names, and oversized
  content before model execution.
- Fake runners exercise model-backed use cases without credentials or network access.
- Stable errors remain bounded, sanitized, and adapter-independent.
- Read-only use cases work while a review is pending.
- Write preparation reports `review_pending` before normal provider work when possible.

### CLI compatibility tests

- Existing help, command arguments, output, prompts, exit codes, rejection, Ctrl-C, duplicates,
  no-ops, and acceptance behavior remain compatible.
- Review show/apply/discard supports an abruptly orphaned new-schema pending review.
- Existing acceptance and recovery suites continue to pass through the facade.

### MCP contract tests

- An MCP client can initialize, list and read paginated resources, and invoke every tool.
- Tool inputs and structured outputs conform to their schemas.
- Tool annotations match actual application effects.
- Domain failures are tool execution errors; protocol failures remain protocol errors.
- No non-protocol output reaches stdout.
- A subprocess restart preserves the pending review.
- Cancellation before review persistence leaves no review; transport loss after persistence leaves
  one discoverable pending review.
- Prepare, inspect, apply, discard, duplicate, no-op, stale, and deterministic-lint journeys are
  fully offline with fake model runners.

### Web tests

- Local API routes map to the same application contracts and errors.
- Host, Origin, session, and CSRF defenses reject invalid requests.
- The UI renders complete diffs and explicit pending, stale, applied, and discarded states.
- One browser-level smoke journey covers preparing or loading a pending review and resolving it.

### Cross-adapter acceptance

The defining acceptance journey is:

1. prepare a review through MCP;
2. terminate the MCP process;
3. open the same workspace through MCP or the local web UI;
4. inspect the same ID, summary, and complete diff; and
5. apply or discard it exactly once.

Additional acceptance covers MCP prepare followed by web resolution, stale review rejection after
an external live edit, concurrency with two preparations, and recovery after interruption of an
accepted apply.

Normal release gates remain:

```bash
uv run pytest -m 'not eval' -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
git diff --check
```

Live provider evaluations remain explicit, optional, and supplementary.

## Acceptance criteria

1. CLI, MCP, and web use the same application use cases for shared behavior.
2. Current CLI behavior remains compatible, with additive review recovery commands.
3. MCP runs locally over `stdio` and is fixed to one workspace at startup.
4. MCP exposes the full agreed workspace surface except initialization and local-path ingestion.
5. Preparation never mutates live `raw/` or `wiki/` content.
6. One durable pending review survives restart with the exact summary and complete diff.
7. Apply and discard require the matching review ID and resolve a review at most once.
8. Pending review is preserved by normal startup; accepted interruption remains recoverable.
9. A stale review cannot apply and is never silently rebased.
10. A review prepared through MCP can be resolved through the later web UI.
11. No adapter exposes arbitrary filesystem access, raw sources, transaction paths, or secrets.
12. Default tests remain offline, deterministic, and credential-free.

## References

- [BundleWalker v1 design](2026-07-15-bundlewalker-v1-design.md)
- [MCP architecture](https://modelcontextprotocol.io/docs/learn/architecture)
- [MCP transports, version 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
- [MCP resources, version 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/server/resources)
- [MCP schema, version 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/schema)
- [MCP tasks, version 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/tasks)
- [MCP security best practices](https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices)
