# Ingestion Output Repair Design

## Goal

Allow the ingestion agent to repair schema-valid but domain-invalid `ChangeSet` output within
PydanticAI's existing output retry budget, while preserving BundleWalker's deterministic final
validation and exception-sanitization boundaries.

## Problem

The GPT-5.6 Luna live evaluation reaches the provider successfully, but three ingestion cases
fail after the agent returns:

- two proposals contain structured citations whose numbers do not match the citation markers in
  their Markdown bodies;
- one proposal uses a Source path ending in `.md`, which is not a canonical concept ID.

`ChangeSet` and `DraftConcept` accept these values at the Pydantic schema boundary. The stronger
repository-aware rules live in `validate_change_set`, which `prepare_ingestion` currently calls
only after `run_ingestion_agent` has returned. As a result, PydanticAI sees a successful typed
output, performs no repair retry, and the workflow rejects the proposal afterward.

A deterministic reproduction confirms that an invalid extension-bearing path is returned after
one model call even though the agent is configured with two output retries. The retry budget is
therefore present but placed outside the authoritative domain-validation boundary.

## Selected approach

Attach a per-run PydanticAI output validator inside `run_ingestion_agent`. The validator reuses
`validate_change_set` and converts `ChangeSetError` into PydanticAI `ModelRetry` feedback. This
keeps a single validation authority and lets PydanticAI continue the same agent run with the
validation error included as repair feedback.

The existing `prepare_ingestion` validation remains unchanged. A repaired proposal must pass the
same validation again before BundleWalker prepares a transaction.

## Architecture

### Agent construction

`create_ingestion_agent` continues to construct the provider-neutral agent with:

- `AgentDependencies`;
- `ChangeSet` output;
- the read-only knowledge tools;
- two configured retries;
- the ingestion instructions.

`run_ingestion_agent` creates one agent instance for the current source and registers an output
validator on that instance before calling `agent.run`.

### Per-run validation context

The output validator constructs `ChangeValidationContext` from:

- the current `AgentDependencies.repository`;
- a snapshot of `AgentDependencies.read_ids` at validation time;
- the current `RawSource` captured by the run;
- ingestion mode.

This gives `validate_change_set` the same repository, source identity, and read ledger that the
workflow uses. The read ledger is evaluated at validator execution time so tool calls made during
the run are included.

### Retry behavior

The validator calls `validate_change_set` with the proposed `ChangeSet`.

- Valid output is returned unchanged.
- `ChangeSetError` is converted to `ModelRetry` with the deterministic validation message and no
  exception chain.
- PydanticAI may request at most two repaired outputs after the initial output, matching the
  existing retry configuration.
- If retries are exhausted, `run_ingestion_agent` retains its generic sanitized
  `AgentRunError` behavior.
- Provider and unexpected exceptions remain hidden behind the existing sanitized error boundary.

BundleWalker does not strip `.md`, renumber citations, insert citation markers, or otherwise
normalize invalid model output. Repair remains the model's responsibility, and deterministic
validation remains the acceptance authority.

## Prompt contract

The ingestion instructions will add explicit requirements that mirror the observed failures:

- every draft path is an extensionless canonical concept ID matching
  `sources|topics|entities/<lowercase-ascii-slug>`;
- paths never include `.md`;
- the Source draft path equals `numbered_source.concept_id` exactly;
- each citation marker `[n]` in a draft body has exactly one structured citation numbered `n`;
- every structured citation has a matching body marker;
- citation numbers are contiguous starting at `1`;
- draft bodies do not contain a `# Citations` section because application code renders that
  section deterministically.

These instructions improve first-attempt compliance and reduce paid retries. They do not replace
the output validator.

## Error handling and security

`validate_change_set` messages are bounded by the producer models and describe rejected paths,
citation IDs, operation state, or deterministic repository conditions. The output validator sends
only the `ChangeSetError` message back to the model and suppresses the Python exception chain.

Raw provider exception bodies, source contents, and questions are never propagated through the
public `AgentRunError`. Existing tests that require provider exception chains and echoed secrets
to be discarded remain authoritative.

The workflow-level validation is retained as defense in depth for custom runners, future changes
to the agent boundary, and any discrepancy between retry validation and transaction preparation.

## Testing

### Deterministic repair tests

Use PydanticAI `FunctionModel` responses to exercise the real output-validator retry mechanism:

1. Return a Source path ending in `.md`, then return the corrected extensionless path. Assert two
   model calls and a valid returned proposal.
2. Return a body/citation mismatch, then return matching markers and structured citations. Assert
   two model calls and a valid returned proposal.
3. Return invalid domain output until retries are exhausted. Assert the caller receives the
   existing generic `AgentRunError` without a sensitive exception cause or context.

The strict-agent-contract test will also assert that the prompt contains the canonical-path and
citation-matching requirements.

### Regression verification

Run:

- the ingestion-agent and ingestion-workflow tests;
- the complete non-eval pytest suite;
- Ruff formatting and lint checks;
- Pyright;
- the four-case live evaluation with `openai:gpt-5.6-luna`.

## Success criteria

- Schema-valid but domain-invalid ingestion output enters PydanticAI's repair loop.
- The existing retry budget permits the initial output plus at most two repair outputs.
- Valid output is returned unchanged and is validated again by `prepare_ingestion`.
- Invalid output is never silently normalized.
- Provider errors and potentially sensitive exception chains remain sanitized.
- All deterministic tests and static checks pass.
- A fresh GPT-5.6 Luna evaluation completes all four quality cases successfully.

## Non-goals

- Changing the global `ChangeSet`, `DraftConcept`, or `Citation` Pydantic schemas.
- Adding a manual workflow-level model retry loop.
- Changing query, semantic-lint, or synthesis behavior.
- Increasing the configured retry count.
- Weakening canonical path, citation, read-ledger, or transaction validation.
