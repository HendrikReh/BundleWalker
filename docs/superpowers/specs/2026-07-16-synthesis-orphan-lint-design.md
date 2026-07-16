# Synthesis Orphan Lint Design

**Date:** 2026-07-16

## Problem

BundleWalker currently reports `ORPHAN001` for every concept with no inbound concept link,
regardless of concept type. This is useful for Sources, Topics, and Entities because those
concepts are intended to accumulate into a navigable knowledge graph.

It produces an unavoidable warning for a newly saved Synthesis. The `ask --save` contract permits
exactly one create-only Synthesis draft, so the operation cannot add a backlink from an existing
concept. The Synthesis can cite and link to its supporting concepts, but no concept can link to the
new path before it exists. As a result, a successful supported workflow immediately creates a
deterministic warning even when the Synthesis is well connected to its evidence.

## Considered approaches

### 1. Exempt Syntheses from `ORPHAN001`

Treat `Synthesis` as an intentional terminal concept and retain the inbound-link rule for every
other accepted or extension concept type. This is the smallest change and matches the existing
create-only `ask --save` contract.

### 2. Require no links in either direction before reporting an orphan

This would stop the Synthesis warning because saved answers link outward through their citations.
It would also suppress useful warnings for unreferenced Topics and Entities merely because they
cite Sources, weakening the signal that led to the comparative Synthesis during the pilot.

### 3. Add backlinks during `ask --save`

The workflow could update every cited concept with a link to the new Synthesis. This would change
the validated transaction from one create-only draft into a multi-document mutation, introduce
generated backlink content into maintained pages, and expand recovery and review behavior. That is
not justified by a warning-level graph heuristic.

## Decision

Use approach 1. `_lint_orphans` will skip documents whose exact OKF metadata type is `Synthesis`.
Sources, Topics, Entities, and permissively consumed extension types will keep the existing
inbound-link requirement. Unknown types remain covered so permissive OKF consumption does not
silently remove health checks from extension concepts.

No CLI output format, severity, exit code, semantic-lint behavior, workspace content, or
`ask --save` transaction behavior changes.

## Testing

Add a deterministic lint regression test that creates an unreferenced Synthesis and an
unreferenced Topic in the same valid bundle. Assert that `ORPHAN001` reports the Topic but not the
Synthesis. Keeping both concepts in one test proves that the exemption is type-specific rather
than a broad weakening of orphan detection.

Then run the focused OKF lint tests, the full offline suite, formatting, linting, type checking,
and deterministic lint against the pilot knowledge bundle.

## Acceptance criteria

1. A canonical `Synthesis` with no inbound concept link does not produce `ORPHAN001`.
2. An otherwise equivalent Topic, Entity, Source, or extension concept still produces
   `ORPHAN001` when it has no inbound concept link.
3. Existing deterministic and semantic lint ordering, severity, and exit behavior remain intact.
4. The pilot bundle's saved decision-framework Synthesis no longer causes a deterministic orphan
   warning.
