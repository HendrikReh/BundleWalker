# Synthesis Refresh Design

**Date:** 2026-07-16

## Problem

Semantic lint can correctly report that a saved Synthesis is stale relative to newer knowledge,
but BundleWalker v1 offers no supported remediation. `ask --save` creates exactly one new
Synthesis, while ingestion rejects all Synthesis drafts. Creating another answer leaves the old
conclusion active and makes its lifecycle ambiguous.

BundleWalker needs a reviewed way to revise a Synthesis at its existing concept ID without
weakening citation validation, prompt isolation, concurrency protection, recovery, or the
unchanged-workspace guarantees of the current CLI.

## Goals

1. Refresh one existing Synthesis in place from an explicit user instruction.
2. Give the query agent the existing Synthesis as untrusted revision context and current wiki
   concepts through the existing read-only tools.
3. Require fresh citations to other live concepts read during the refresh run.
4. Preserve the concept path, descriptive metadata, metadata extensions, and transaction history.
5. Show a complete diff and require confirmation before persistence.
6. Treat a substantively unchanged canonical result as a successful no-op.

## Non-goals

- Versioned successor files or supersession metadata.
- Renaming or moving a Synthesis concept ID.
- Refreshing Sources, Topics, Entities, or permissive extension types.
- Automatic refresh initiated by semantic lint.
- Multi-document backlink or dependent-concept updates.
- Weakening the advisory nature of semantic lint.

## Considered approaches

### 1. Extend `ask` with `--refresh` (selected)

This reuses the existing one-model-call query workflow, read-ledger validation, diff review,
transaction preparation, confirmation, commit, and recovery behavior. It adds only one mutually
exclusive destination mode to the established command.

### 2. Add a separate `refresh` command

A separate command would make the operation prominent, but would duplicate model selection,
question handling, answer rendering, review, and transaction behavior. The distinct command does
not provide enough semantic value to justify another public workflow.

### 3. Create a versioned successor

Separate files preserve every revision as knowledge content, but require supersession metadata,
navigation rules, stale-finding suppression, and a policy for citations to historical versions.
The selected in-place model already preserves operational history through reviewed diffs, Git,
and `wiki/log.md`.

## CLI contract

Refresh uses an explicit instruction and a canonical concept ID without `.md`:

```bash
bundlewalker ask \
  "Refresh this decision framework using newer comparative evidence." \
  --refresh syntheses/decision-framework-for-agent-guidance-and-context
```

The existing positional `QUESTION` remains required. `--save` and `--refresh` are mutually
exclusive. Plain `ask` remains read-only, and `ask --save` remains create-only.

Before resolving a model or making a provider call, BundleWalker validates that the refresh target:

- is a safe canonical concept ID;
- exists in the live repository; and
- has exact metadata type `Synthesis`.

Invalid option combinations or targets are usage errors and leave the workspace unchanged.

## Agent context and trust boundary

The query agent remains read-only. In refresh mode, its protected payload gains a distinct
`refresh_target` object containing the target concept ID, current metadata, and complete body.
The refresh target, workspace conventions, indexes, question, search results, and concept content
are all untrusted data.

Trusted refresh instructions tell the agent to:

- revise the supplied Synthesis according to the explicit question;
- preserve still-supported material, uncertainty, and contradictions;
- use current wiki concepts through the read-only tools;
- return a complete replacement title and body; and
- never cite the Synthesis being replaced.

Only concepts successfully returned by `read_concept` during this run may support structured
citations. Supplying the old Synthesis as revision context does not add it to the read ledger.

## Replacement proposal

The refreshed answer produces exactly one `DraftConcept` with:

- operation `REPLACE`;
- the existing Synthesis concept ID;
- type `Synthesis`;
- the refreshed answer title, body, and structured citations;
- the existing description and tags;
- the existing document digest as `base_digest`; and
- the transaction occurrence time as the new timestamp.

The existing renderer continues to preserve permissive metadata extensions when replacing a live
document. The target path never changes, so existing inbound links remain valid.

Synthesis validation will accept exactly one create or replace Synthesis draft. A replacement must
target an existing live Synthesis, carry the matching base digest, and must not cite its own
concept ID. Existing path, category, citation, prospective-wiki lint, and source-span rules remain
unchanged.

## Review, persistence, and concurrency

The application renders and lints the prospective wiki, then displays the complete diff through
the existing review prompt. Acceptance uses the current authenticated transaction and recovery
machinery. Declining, interrupting, validation failure, model failure, or a stale base digest
leaves live knowledge unchanged.

Commit-time digest revalidation detects edits made after proposal preparation. The accepted
replacement updates the generated indexes when its visible metadata changes and prepends one
normal transaction entry to `wiki/log.md`.

## No-op behavior

If the canonical refreshed title, body, and citations are equivalent to the current Synthesis,
BundleWalker returns a successful no-op:

```text
Synthesis is already current; no changes applied.
```

A no-op creates no transaction state, timestamp-only diff, or log entry. Description, tags, and
metadata extensions are preserved and therefore do not create false changes.

## Error behavior

- `--save` combined with `--refresh`: usage error, exit `2`, no model call.
- Missing, unsafe, or non-Synthesis target: usage error, exit `2`, no model call.
- Empty instruction: existing usage error behavior, exit `2`.
- Invalid, unread, nonexistent, or self-referential citation: agent/change validation error,
  exit `1`, no staged or live mutation.
- Concurrent target edit: stale-digest transaction error, exit `1`, no overwrite.
- Decline or Ctrl-C during review: exit `0`, unchanged workspace.
- Equivalent refresh: exit `0`, unchanged workspace.

## Testing strategy

### Deterministic validation

Test create and replace Synthesis modes, correct base-digest enforcement, wrong target types,
self-citation rejection, and preservation of the existing create-only `--save` contract.

### Agent and workflow tests

Use fake runners and PydanticAI test models to verify separate untrusted refresh context, trusted
refresh instructions, read-ledger enforcement, target prevalidation before model resolution,
metadata-extension preservation, refreshed-title persistence, and no-op detection.

### CLI and transaction tests

Cover mutual exclusion, help output, invalid targets without provider invocation, reviewed accept,
decline, interruption, stale concurrent edits, failure cleanup, exit codes, and recovery. Extend the
acceptance flow with one refresh that retains the concept ID and replaces its content after review.

### Live-model evaluation

Add one opt-in case containing an older Synthesis plus newer evidence. The selected live model must
incorporate the newer qualification, cite live supporting concepts, avoid self-citation, and
produce a valid replacement. The case remains excluded from offline CI and runs only when an
evaluation model and credentials are intentionally configured.

## Documentation

Update the README and end-user guide command summary, `ask` reference, examples, lifecycle
semantics, troubleshooting, and documentation contract. Explain create versus refresh, the stable
path, metadata preservation, one-model-call behavior, reviewed replacement, no-op outcome, and how
`--refresh` addresses an actionable `SEM-STALE` finding without making semantic lint mutating.

## Acceptance criteria

1. A valid explicit refresh prepares one reviewed replacement at the original Synthesis path.
2. The old Synthesis is revision context but cannot become a citation to itself.
3. Every persisted citation targets another live concept read during the refresh run.
4. Description, tags, unknown metadata fields, and inbound links survive the replacement.
5. Title and body may update; timestamp and log change only after acceptance.
6. Invalid targets are rejected before model resolution or provider use.
7. Equivalent output is a successful byte-unchanged no-op.
8. Decline, interruption, errors, and concurrent edits never overwrite live knowledge.
9. Existing `ask`, `ask --save`, ingestion, lint, and transaction behavior remains compatible.
10. Offline tests and the intentionally configured refresh quality evaluation pass.
