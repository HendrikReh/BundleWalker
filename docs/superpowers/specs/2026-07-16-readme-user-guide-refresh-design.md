# README and User Guide Refresh Design

**Date:** 2026-07-16

## Purpose

Improve `README.md` and `docs/user-guide.md` so a first-time user can understand BundleWalker,
complete a safe first workflow, and find detailed operating guidance without reading the same
manual twice.

This is an editorial and information-architecture change. It does not change BundleWalker’s CLI,
runtime behavior, file formats, or safety model.

## Current problems

The current documents are accurate and comprehensive, but their responsibilities overlap:

- the README is long enough to function as a second command reference;
- the guide is organized primarily as reference material rather than around user tasks;
- important safety guarantees recur in several sections instead of appearing at the decision
  points where users need them;
- setup and workflow examples are correct but can lead more directly from installation to a
  reviewed write;
- the evaluation-coverage summary and a few transaction/model descriptions need to be checked
  against the current implementation; and
- `docs/user-guide.md` has an equality-checked embedded copy in the historical end-user-guide
  implementation plan, so uncoordinated edits create documentation drift.

## Audience and success criteria

The README primarily serves a first-time user evaluating or trying BundleWalker. The user guide
serves an operator who needs to complete, understand, or troubleshoot every supported workflow.

The refresh succeeds when:

1. a newcomer can explain BundleWalker’s value and safety boundary from the README;
2. the README provides one copy-paste route from checkout to a reviewed knowledge proposal;
3. the guide presents common tasks before exhaustive reference material;
4. model setup remains provider-neutral and includes one clearly labelled OpenAI example;
5. command syntax and behavior match the live Typer interface and tests;
6. detailed semantics have one authoritative home instead of being repeated across both files;
7. the guide’s embedded copy remains byte-identical to the canonical guide; and
8. the normal offline verification suite remains green.

## Information architecture

### README

The README becomes a concise project landing page with this progression:

1. **What BundleWalker is** — one outcome-led introduction.
2. **Why use it** — the distinctive local, review-first, cited, portable knowledge model.
3. **Install and configure a model** — repository installation, provider-neutral model selection,
   and a short OpenAI example.
4. **First workflow** — initialize, ingest, review, ask, save, and lint.
5. **Choose a conventions preset** — a compact decision aid with links to the full guide.
6. **How the safety boundary works** — agents propose; deterministic code validates, shows a
   complete diff, and commits only after confirmation.
7. **Common next steps** — concise examples for read-only ask, saved Synthesis, refresh, and
   semantic lint.
8. **Scope and limits** — a short summary of current v1 boundaries.
9. **Documentation and development** — links to the user guide plus offline and opt-in evaluation
   commands.

The README will not duplicate complete option tables, exit-code detail, workspace recovery
procedures, or every troubleshooting case.

### User guide

The guide becomes task-first while retaining a complete reference section:

1. understand BundleWalker’s workspace and review model;
2. install BundleWalker and configure a provider;
3. create a workspace and choose a conventions preset;
4. ingest and review a source;
5. ask cited questions;
6. save and refresh Syntheses;
7. maintain the bundle with deterministic lint, semantic lint, and recovery;
8. consult the complete CLI option reference;
9. inspect workspace layout and exit codes; and
10. troubleshoot provider, validation, transaction, Git, and privacy issues.

Each task chapter uses the same local structure:

1. when to use the task;
2. exact command;
3. what BundleWalker does;
4. what requires review;
5. expected success or no-op behavior; and
6. the most relevant failure or recovery guidance.

## Workflow explanations

The documentation will consistently explain three connected flows:

```text
Source -> model proposal -> deterministic validation -> reviewed diff -> raw/ + wiki/

Question -> cited answer -> optional save -> reviewed Synthesis creation

Existing Synthesis -> explicit refresh instruction -> reviewed in-place replacement
```

These are conceptual explanations, not promises of agent autonomy. Semantic lint may identify a
candidate for maintenance but never authorizes or starts a write.

## Voice and terminology

The revised prose will be direct, calm, and practical:

- lead with the user outcome, then explain implementation details that affect behavior;
- prefer short sentences, concrete commands, and explicit expected results;
- use “model-backed” consistently and use “offline” only when no provider call occurs;
- state the safety boundary at ingestion, review, refresh, provider, and publication decisions;
- distinguish immutable raw sources from the maintained compiled wiki;
- distinguish deterministic lint errors from semantic advisories;
- avoid marketing claims, anthropomorphic agent language, and repeated cautions; and
- preserve uncertainty and current v1 limitations without burying the first workflow.

The OpenAI configuration remains an example rather than a default. Model availability is treated
as provider-controlled and time-sensitive; the guide links to current PydanticAI and OpenAI model
documentation rather than promising availability.

## Accuracy and duplication rules

- Live `bundlewalker --help` and subcommand help are authoritative for command names, arguments,
  and options.
- Tests and production code are authoritative for review, no-op, recovery, model-resolution, and
  exit behavior.
- `docs/user-guide.md` is authoritative for detailed end-user operation.
- README repeats only the installation, first workflow, core safety model, and a small set of
  common next steps.
- Preset names and purposes must match the packaged templates.
- Evaluation documentation must include the current refresh-quality case without implying that
  live evaluations replace offline acceptance coverage.
- `.bundlewalker/` is described as coordination and temporary transaction state created when a
  reviewed write is staged; an idle workspace may retain only its lock.

## Files and maintenance contract

The implementation changes:

- `README.md`;
- `docs/user-guide.md`; and
- `docs/superpowers/plans/2026-07-16-end-user-guide.md`, only to synchronize its embedded guide
  and keep the existing equality contract valid.

No production code or CLI behavior changes are in scope. No additional end-user guide copy will
be introduced.

## Verification

Verification will include:

1. compare all documented command forms with live top-level and subcommand help;
2. run the end-user-guide contract, including byte-for-byte embedded-guide equality;
3. check the README link and every local documentation link;
4. scan examples for placeholder consistency, shell correctness, and accidental secrets;
5. run `git diff --check`;
6. run the complete non-evaluation pytest suite;
7. run Ruff formatting and lint checks; and
8. run strict Pyright.

Live provider calls are not required because the change affects documentation only.

## Non-goals

This refresh will not:

- add, remove, or rename CLI commands or options;
- change conventions preset content;
- redesign the OKF workspace;
- add support for new source formats or installation channels;
- turn the user guide into contributor or architecture documentation; or
- create a separate documentation site.

## Risks and mitigations

- **README becomes too sparse:** retain one complete first workflow and the core safety model.
- **Guide remains repetitive:** place detailed semantics in one task or reference section and link
  to it from troubleshooting.
- **Examples drift from the CLI:** verify every command against live help during implementation.
- **Embedded guide drifts:** update it mechanically and run the byte-equality contract.
- **Provider example becomes stale:** label it as an example and link to current provider docs.
