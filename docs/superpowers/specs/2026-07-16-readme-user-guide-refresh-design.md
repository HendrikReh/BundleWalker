# Documentation Suite Refresh Design

**Date:** 2026-07-16

## Purpose

Improve BundleWalker’s documentation suite so a first-time user can understand the project,
complete a safe first workflow, find detailed operating guidance, and contribute effectively
without reading the same material in several places.

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
- there is no dedicated, copy-pasteable tutorial that carries one personal knowledge workspace
  through ingestion, synthesis, newer evidence, and refresh;
- contributor guidance is scattered across the README, project configuration, tests, and design
  documents instead of presenting one architecture and development workflow;
- the evaluation-coverage summary and a few transaction/model descriptions need to be checked
  against the current implementation; and
- `docs/user-guide.md` has an equality-checked embedded copy in the historical end-user-guide
  implementation plan, so uncoordinated edits create documentation drift.

## Audience and success criteria

The README primarily serves a first-time user evaluating or trying BundleWalker. The tutorial
serves a learner completing one personal-workbook journey. The user guide serves an operator who
needs to complete, understand, or troubleshoot every supported workflow. The contributor guide
serves someone changing BundleWalker itself.

The refresh succeeds when:

1. a newcomer can explain BundleWalker’s value and safety boundary from the README;
2. the README provides one copy-paste route from checkout to a reviewed knowledge proposal;
3. the tutorial is fully copy-pasteable and demonstrates the complete personal-workbook
   lifecycle without depending on exact model-generated wording;
4. the guide presents common tasks before exhaustive reference material;
5. the contributor guide explains architecture, test layers, and the verified change workflow;
6. model setup remains provider-neutral and includes one clearly labelled OpenAI example;
7. command syntax and behavior match the live Typer interface and tests;
8. detailed semantics have one authoritative home instead of being repeated across files;
9. the guide’s embedded copy remains byte-identical to the canonical guide; and
10. the normal offline verification suite remains green.

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
   commands, with prominent navigation to the tutorial and contributor guide.

The README will not duplicate complete option tables, exit-code detail, workspace recovery
procedures, or every troubleshooting case.

### Tutorial

`docs/tutorial.md` becomes a fully copy-pasteable personal-workbook walkthrough. It will:

1. establish prerequisites and provider-neutral model configuration;
2. create two small local source files containing initial and newer evidence;
3. initialize a workspace with `personal-workbook` conventions;
4. run the initial deterministic lint;
5. ingest and review the first source;
6. inspect the accepted `raw/` and `wiki/` layers;
7. ask a cited question and save a Synthesis;
8. ingest the newer evidence;
9. explicitly refresh the saved Synthesis;
10. run final deterministic and optional semantic lint; and
11. create an optional Git checkpoint after reviewing privacy implications.

The tutorial will identify which model-produced paths, titles, prose, citations, and semantic
advisories can vary. It will describe observable outcomes rather than promise byte-identical model
output. It will not require additional checked-in sample data; shell commands create the tutorial
files in the user’s working directory.

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

### Contributor guide

`CONTRIBUTING.md` uses the conventional GitHub filename and contains:

1. project principles and the agent/deterministic-code trust boundary;
2. an architecture overview and repository map;
3. locked local environment setup;
4. the expected branch, change, and test-driven development workflow;
5. unit, agent, workflow, CLI, acceptance, documentation, and opt-in live-evaluation test layers;
6. formatting, Ruff, strict Pyright, pytest, and diff-check commands;
7. documentation authority and embedded-guide synchronization requirements;
8. transaction, security, compatibility, and provider-boundary considerations; and
9. a concise commit and pull-request checklist.

The contributor guide explains how to change BundleWalker, not how to operate a knowledge
workspace. It links to the user guide for CLI semantics and to the design/plan directory for
historical decisions rather than duplicating them.

### Navigation contract

README links prominently to the tutorial, user guide, and contributor guide. The tutorial links
to the user guide for detailed options and troubleshooting. The user guide links to the tutorial
for guided learning and to the contributor guide for development. The contributor guide links
back to the README and user guide where user-facing behavior is authoritative.

## Workflow explanations

The documentation will consistently explain three connected flows:

```text
Source -> model proposal -> deterministic validation -> reviewed diff -> raw/ + wiki/

Question -> cited answer -> optional save -> reviewed Synthesis creation

Existing Synthesis -> explicit refresh instruction -> reviewed in-place replacement
```

These are conceptual explanations, not promises of agent autonomy. Semantic lint may identify a
candidate for maintenance but never authorizes or starts a write.

The tutorial instantiates all three flows in one workspace. The guide explains each flow as a
task and reference. README summarizes the boundary, while the contributor guide explains the code
layers that enforce it.

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
- `docs/tutorial.md` is authoritative for the guided personal-workbook walkthrough.
- `docs/user-guide.md` is authoritative for detailed end-user operation.
- `CONTRIBUTING.md` is authoritative for architecture, development, and verification workflow.
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
- `CONTRIBUTING.md`;
- `docs/tutorial.md`;
- `docs/user-guide.md`; and
- `docs/superpowers/plans/2026-07-16-end-user-guide.md`, only to synchronize its embedded guide
  and keep the existing equality contract valid.

No production code or CLI behavior changes are in scope. No additional end-user guide copy or
checked-in tutorial fixture directory will be introduced.

## Verification

Verification will include:

1. compare all documented command forms with live top-level and subcommand help;
2. run the end-user-guide contract, including byte-for-byte embedded-guide equality;
3. check README navigation and every local link across all four documents;
4. verify the tutorial’s shell sequence, working-directory transitions, and model-variable reuse;
5. compare contributor setup and verification commands with `pyproject.toml` and the current test
   layout;
6. scan examples for placeholder consistency, shell correctness, and accidental secrets;
7. run `git diff --check`;
8. run the complete non-evaluation pytest suite;
9. run Ruff formatting and lint checks; and
10. run strict Pyright.

Live provider calls are not required because the change affects documentation only.

## Non-goals

This refresh will not:

- add, remove, or rename CLI commands or options;
- change conventions preset content;
- redesign the OKF workspace;
- add support for new source formats or installation channels;
- add checked-in tutorial source fixtures;
- turn the user guide into contributor or architecture documentation;
- define project governance, a code of conduct, or release automation; or
- create a separate documentation site.

## Risks and mitigations

- **README becomes too sparse:** retain one complete first workflow and the core safety model.
- **Guide remains repetitive:** place detailed semantics in one task or reference section and link
  to it from troubleshooting.
- **Tutorial becomes brittle:** state variable model output explicitly and verify commands and
  observable state transitions instead of generated filenames or prose.
- **Contributor guide duplicates internals:** link to authoritative modules and historical design
  documents, and keep the guide focused on stable boundaries and workflows.
- **Navigation fragments:** require reciprocal links among README, tutorial, user guide, and
  contributor guide.
- **Examples drift from the CLI:** verify every command against live help during implementation.
- **Embedded guide drifts:** update it mechanically and run the byte-equality contract.
- **Provider example becomes stale:** label it as an example and link to current provider docs.
