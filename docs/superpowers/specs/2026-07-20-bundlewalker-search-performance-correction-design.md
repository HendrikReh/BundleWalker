# BundleWalker Search Performance Correction Design

**Date:** 2026-07-20

**Status:** Approved for implementation planning

**Milestone:** Public-beta Milestone B3 — performance and capacity evidence

## Summary

BundleWalker's first authoritative performance matrix demonstrated that Medium workspaces satisfy
the reference targets for every measured operation except lexical search. Profiling traced the
search miss to two complete repository scans in one application request: `LexicalRetriever.search`
scans and ranks the workspace, then `WorkspaceApplication.search_concepts` scans the same workspace
again to reconstruct public result objects.

The correction removes only that second scan. The application will convert the ranked
`ConceptSummary` values returned by `LexicalRetriever` directly into `ConceptSummaryResult` values.
It will preserve existing validation, ranking, serialization, error translation, and public API
behavior. No index, cache, parser shortcut, capacity claim, or release-version change belongs to
this correction.

## Context and Evidence

The first full matrix ran against merge commit
`55608145bc51cce979fccecd0466e3cc550f41fb` in GitHub Actions run `29723884192` on the four
supported combinations:

- Ubuntu 24.04 with Python 3.13 and 3.14;
- macOS 15 with Python 3.13 and 3.14.

The complete run reported Medium search medians of approximately 1.97–2.95 seconds. Both Linux
environments and macOS with Python 3.14 missed the 2-second reference target; macOS with Python
3.13 passed narrowly. Every other Medium scenario passed in all four environments. Local profiling
showed that search scoring itself accounted for less than two percent of elapsed time. Nearly all
search time was spent in two successive `OkfRepository.scan()` calls. Each scan reads and validates
every Markdown document, loads YAML metadata, parses Markdown links, and computes document digests.

The run is diagnostic evidence, not a supported-capacity baseline. Milestone B3 requires at least
the Medium profile to meet every reference target across the complete supported matrix before
BundleWalker publishes a supported capacity.

## Goals

1. Reduce an application-level lexical search request from two complete repository scans to one.
2. Preserve the exact existing search result contract and ordering.
3. Preserve full repository validation during the remaining scan.
4. Establish the correction structurally in tests and verify it with the authoritative matrix.
5. Keep the change small enough to evaluate independently before the `0.4.0rc1` production-PyPI
   release candidate.

## Non-goals

This correction does not:

- introduce a persistent or in-memory search index;
- cache repository contents between requests;
- change document parsing, YAML loading, Markdown link extraction, or digest calculation;
- weaken case-folded collision detection or whole-repository validation;
- optimize status, list, read, lint, transaction, or MCP startup operations;
- promise that the Large profile will meet the initial target;
- alter lexical scoring weights, normalization, filtering, limits, or tie-breaking;
- change CLI, MCP, schema, resource-URI, workspace-format, or package-version contracts;
- publish performance evidence or a supported-capacity claim by itself.

Large remains a desired first capacity envelope, but Medium is the explicit public-beta gate. A
broader operation-specific parser or index would require a separate design because either can
change validation and consistency guarantees.

## Current Data Flow

For an application search request:

1. `WorkspaceApplication.search_concepts` validates the public query and recovers transactions.
2. It creates one `OkfRepository`.
3. `LexicalRetriever.search` calls `repository.scan()`, scores every eligible document, and returns
   ranked `ConceptSummary` values.
4. `WorkspaceApplication.search_concepts` calls `repository.scan()` again.
5. The application looks up each matched concept in the second result and converts the full
   `OkfDocument` to `ConceptSummaryResult`.

Step 4 repeats the dominant work but contributes no information absent from `ConceptSummary`.

## Proposed Data Flow

The first three steps remain unchanged. After retrieval, the application converts each returned
`ConceptSummary` directly to `ConceptSummaryResult` and returns the ordered tuple.

The conversion belongs in the application facade because `ConceptSummaryResult` is an application
contract containing the delivery-neutral `bundlewalker://` resource URI. The repository summary
must remain free of application serialization concerns.

The existing full-document `_concept_summary` conversion remains in place for list and read use
cases. Search uses a parallel summary conversion accepting the repository's `ConceptSummary`.
Keeping the input types explicit prevents search from needing an `OkfDocument` and makes a future
accidental rescan visible in code review.

### Field Mapping

The direct conversion preserves these exact rules:

| Public field | Source and fallback |
| --- | --- |
| `concept_id` | `ConceptSummary.concept_id` |
| `type` | `ConceptSummary.type` |
| `title` | metadata title, or the final POSIX path component of `concept_id` |
| `description` | metadata description, or `""` |
| `tags` | immutable tuple from `ConceptSummary.tags` |
| `resource_uri` | `bundlewalker://concept/` plus the concept ID quoted with `/` preserved |

The conversion does not read the document path or body. Search ordering continues to come entirely
from `LexicalRetriever`: descending phrase score, descending token score, then ascending concept ID,
followed by the existing limit.

## Validation and Error Semantics

The retained `LexicalRetriever` scan continues to parse every eligible Markdown document before
returning results. Therefore malformed documents, unsafe workspace state, symlink behavior,
case-folded collisions, and repository I/O errors retain their existing behavior.

`WorkspaceApplication.search_concepts` continues to:

- reject blank or oversized queries as `INVALID_INPUT` before repository access;
- recover interrupted transactions before searching;
- delegate the 1–10 result-limit validation to `LexicalRetriever`;
- translate `BundleWalkerError` instances through the existing application error boundary.

Removing the second scan also removes the theoretical window in which the workspace could change
between retrieval and result reconstruction. Each result now represents the same validated scan
used for ranking.

## Test Design

Implementation follows test-driven development.

### Structural regression

Add an application-facade test that observes `OkfRepository.scan` and proves a successful search
invokes it exactly once. This is the primary regression test. It asserts the architectural property
that produced the performance improvement and avoids a flaky elapsed-time threshold in unit tests.

### Contract regression

Extend facade coverage so direct conversion proves:

- ranking and output order are unchanged;
- title falls back to the concept filename when omitted;
- description falls back to an empty string when omitted;
- tags and concept type are preserved;
- resource URIs retain the existing URL-quoting rules;
- no-match searches return an empty tuple;
- repository and limit failures retain their existing translated error behavior.

Existing retrieval tests continue to own scoring weights, normalization, concept-type filtering,
limit enforcement, and deterministic tie-breaking. The implementation should not duplicate those
tests in the facade suite.

### Verification sequence

After the focused red/green cycle:

1. run the relevant facade and retrieval tests;
2. run the complete test suite;
3. run repository lint and static type checks;
4. build the distribution and run the existing artifact smoke checks if required by the branch
   verification workflow;
5. merge the reviewed correction before generating authoritative evidence;
6. rerun the complete performance matrix against the exact merged commit.

## Performance Acceptance

The correction is functionally acceptable only when ordinary verification passes. It qualifies
Milestone B3 only when the authoritative rerun also shows:

- Medium completes without a hard-timeout or correctness failure;
- both present-query and absent-query Medium search scenarios meet the 2-second reference target;
- every other reference scenario continues to meet its target;
- all four supported environment combinations pass: Ubuntu 24.04 and macOS 15, each with Python
  3.13 and 3.14;
- evidence identifies the exact merged source commit and passes privacy and integrity validation.

No single local measurement, selected environment, best-of run, or smaller profile is sufficient.
If Medium still misses the target in any supported environment, B3 remains incomplete and the team
must review fresh profiles before considering the broader parser approach.

Large or Probe timeout remains a measured capacity boundary under the existing benchmark design.
It does not invalidate Medium evidence, but no Large support claim may be published unless Large
meets the full matrix criteria.

## Evidence and Documentation Policy

The diagnostic run is retained in GitHub Actions but is not committed as the supported baseline.
Only evidence from the qualifying post-merge run may update the reviewed evidence set and render
the public `docs/performance-and-capacity.md` report.

The Phase 2 evidence change must include the complete supported matrix, exact artifact checksums,
the rendered capacity report, and any affected roadmap/release documentation. Until that change is
reviewed and merged, public documentation continues to state that supported capacity is not yet
published.

## Release Relationship

The production release candidate will use package version `0.4.0rc1`. The final public beta remains
reserved for `0.4.0` after every beta gate passes. This performance correction does not itself bump
the version or publish an artifact; it is one prerequisite for the release-candidate certification
sequence.

After B3 qualifies, the remaining release path is:

1. configure and verify the production-PyPI trusted-publishing workflow;
2. publish and validate `0.4.0rc1`;
3. rehearse install, upgrade, backup, restore, and rollback procedures;
4. certify Hermes and a second independent MCP host;
5. complete the external pilot with at least three users without private setup assistance;
6. complete the final security/release audit and publish `0.4.0`.

## Rollback

The implementation changes only application result construction. If verification exposes a
contract regression, revert the correction commit to restore the previous two-scan behavior. No
workspace migration, cache invalidation, evidence rewrite, or user-data recovery is required.

## Approved Decision

The approved approach is the one-scan correction. Broader lightweight parsing and a persistent
index are explicitly deferred unless new authoritative evidence shows that the narrow correction
cannot satisfy the Medium public-beta gate.
