# Conventions Style Presets Design

**Date:** 2026-07-16

## Goal

Let users choose the intended reader and working style of a new BundleWalker workspace during
`init`, while preserving the existing default behavior and leaving the generated
`conventions.md` fully editable and self-contained.

## User-facing command

Initialization accepts one new optional CLI option:

```bash
uv run bundlewalker init PATH --conventions-style STYLE
```

Accepted style values are:

- `default`
- `personal-workbook`
- `agent-context`
- `software-agent`
- `research-agent`

Omitting the option is equivalent to `--conventions-style default`. Existing invocations and
scripts therefore retain their current behavior. Typer rejects unknown values as usage errors
with exit code `2` before workspace creation begins.

The successful initialization message remains unchanged.

## Template-only semantics

The selected style is a creation-time template, not a persistent workspace mode.

- `init` copies the selected packaged Markdown template to `conventions.md`.
- No style identifier is written to `bundlewalker.toml`, `wiki/log.md`, concept frontmatter, or
  any other workspace file.
- The generated `conventions.md` is the sole authority after initialization and may be edited
  freely.
- Existing workspaces require no migration and behave exactly as before.
- BundleWalker does not compare customized conventions with the originating preset or attempt to
  upgrade them later.

This preserves the portability of an OKF bundle and avoids stale metadata after users customize
their instructions.

## Architecture

Introduce a typed `ConventionsStyle` string enum and a focused preset loader. The loader maps each
enum value to one packaged UTF-8 Markdown resource and returns its exact text.

Preset prose lives in separate Markdown resource files rather than multiline Python constants or
runtime-composed fragments. This keeps editorial content independently reviewable and prevents
composition from producing awkward or contradictory instructions.

`initialize_workspace` gains a keyword-only conventions-style parameter whose default is
`ConventionsStyle.DEFAULT`. It loads the template and writes that text to `conventions.md`; its
remaining creation, index-generation, logging, linting, and rollback behavior stays unchanged.

The CLI parses `--conventions-style` into the enum and passes it to `initialize_workspace`.
Direct callers that continue to use `initialize_workspace(path)` remain compatible.

## Preset definitions

### `default`

The default template is byte-for-byte identical to the `DEFAULT_CONVENTIONS_TEXT` generated before
this feature. Its headings, wording, blank lines, and final newline do not change.

This preset remains intentionally small and neutral:

- concise factual prose and descriptive headings;
- explicit uncertainty and conflicting claims;
- OKF links between related concepts;
- stable lowercase ASCII slugs;
- short normalized tags; and
- the current Source, Topic, Entity, and Synthesis responsibilities.

### `personal-workbook`

The personal-workbook template is byte-for-byte identical to the reviewed 64-line policy developed
for the personal OKF knowledge workspace. It treats the bundle as a reflective working notebook.

Its critical boundaries are:

- sourced facts are stated neutrally;
- first person is reserved for interpretation, judgment, priorities, decisions, and open
  questions;
- provisional assessments include rationale and evidence that could revise them;
- Source pages contain no personal interpretation or opinion;
- Topic and Synthesis pages carry evolving personal understanding;
- disagreement, corroboration, and changes of mind are explicit; and
- generic AI prose, overconfidence, artificial balance, repetition, filler, and manufactured
  completeness are rejected.

### `agent-context`

The general agent-context template optimizes knowledge for safe operational use by AI agents across
domains. It prioritizes fast, unambiguous retrieval over personal reflection.

It requires agents producing knowledge to:

- distinguish authoritative facts, inferred conclusions, and proposed actions;
- state scope, applicability, authority, current state, and precedence when known;
- include freshness or version context in the body when safe use depends on it;
- record capabilities, allowed actions, constraints, prohibited actions, procedures, expected
  outcomes, failure conditions, and recovery paths when supported;
- prefer exact interfaces, thresholds, and conditions over general advice;
- preserve unresolved conflicts when precedence is unknown; and
- avoid generic prose, duplicated guidance, and unsupported certainty.

Its concept roles are operational: Sources record authoritative artifacts or observations; Topics
capture reusable rules, capabilities, procedures, or domain constraints; Entities describe actors,
systems, resources, datasets, or tools; Syntheses provide task briefs, decisions, runbooks, or
comparative assessments.

### `software-agent`

The software-agent template specializes operational context for repository and coding agents.

It requires knowledge to capture, when supported:

- a concise repository or component map;
- authoritative commands with exact working directories and relevant expected outcomes;
- architecture boundaries, dependency direction, and public interfaces;
- generated files and sources of truth;
- security, tenancy, data-integrity, and compatibility invariants;
- required formatting, linting, testing, building, and definition-of-done checks;
- known traps, intentionally unusual decisions, and failure-recovery procedures; and
- the distinction between current repository behavior, desired behavior, and proposed changes.

It rejects generic coding advice such as “write clean code,” commands not evidenced by repository
sources, and speculative architecture presented as current fact.

### `research-agent`

The research-agent template optimizes context for evidence synthesis and analysis.

It requires knowledge to:

- distinguish observations, reported results, interpretations, hypotheses, and speculation;
- record source type, method, population or sample, timeframe, and limitations when relevant;
- evaluate evidence quality without treating citation count as proof;
- preserve competing claims and identify whether disagreement concerns facts, definitions,
  methods, assumptions, values, or context;
- separate absence of evidence from evidence of absence;
- record research gaps, uncertainty, alternative explanations, and evidence that could falsify or
  revise a conclusion; and
- prefer precise claims over broad narrative summaries.

Sources remain faithful evidence records; Topics accumulate reusable findings and models; Entities
describe researchers, institutions, datasets, methods, instruments, or studied objects; Syntheses
answer research questions with explicit reasoning, limitations, and confidence.

## Shared agent-preset principles

The three agent-oriented presets share these rules:

- Write for unambiguous retrieval rather than personal reflection.
- Separate authoritative facts, inferred conclusions, and proposed actions.
- State scope and applicability instead of presenting local rules as universal.
- Record conflicts explicitly and state precedence only when supported.
- Include freshness or version context when it materially affects safe use.
- Prefer exact commands, interfaces, thresholds, and failure conditions over general advice.
- Avoid generic AI prose, duplicated guidance, unsupported certainty, and filler sections.

They do not require metadata fields outside BundleWalker's existing producer schema. Ownership,
authority, version, and freshness information belongs in concept bodies when it is relevant and
supported by evidence.

## Error handling and rollback

- Typer rejects an unknown style before `initialize_workspace` runs; the target remains absent.
- A missing, unreadable, or invalid UTF-8 packaged template raises a concise `WorkspaceError` that
  identifies the requested style without exposing filesystem internals.
- Template-loading or writing failures participate in the existing initialization rollback path.
- Rollback removes only paths created by the command and preserves a pre-existing empty target
  directory, matching current behavior.
- Template selection performs no model call, credential lookup, network access, or mutation outside
  the requested workspace target.

## Documentation

The README will document:

- the new option and all accepted values;
- that omission preserves the current default;
- the purpose and intended reader of each preset;
- that the selection is not persisted and `conventions.md` remains editable; and
- copy-paste examples for the personal-workbook and three agent-oriented styles.

## Testing and acceptance criteria

All feature tests are deterministic and offline.

### Loader and template contracts

- Every enum value resolves to one readable UTF-8 resource ending in exactly one newline.
- The `default` resource matches the previous `DEFAULT_CONVENTIONS_TEXT` byte for byte.
- The `personal-workbook` resource matches the reviewed canonical 64-line policy byte for byte.
- Each agent-oriented template has focused assertions for its purpose, evidence boundary, concept
  responsibilities, and distinctive requirements.
- Every template is non-empty and contains no placeholder text.

### Workspace and CLI behavior

- `initialize_workspace(path)` writes the unchanged default template.
- Explicit `default` writes the same bytes.
- Each opt-in style writes its exact packaged template.
- All five initialized workspaces pass deterministic lint.
- `init --help` lists the option and accepted values.
- An invalid style exits `2` and does not create the target.
- A simulated loader failure exercises existing rollback for both new and pre-existing empty
  targets.
- Successful output remains unchanged.

### Complete verification

Before completion, run:

```bash
uv run pytest -m 'not eval' -q
uv run ruff format --check src tests
uv run ruff check src tests
uv run pyright
```

No live-model evaluation is required for the deterministic selector. The existing qualitative
evidence for `personal-workbook` is sufficient for that preset. The new agent-oriented templates
may receive separate opt-in model-quality evaluation later if real usage shows a need for prompt
calibration; that is outside this feature.

## Non-goals

- Persisting or detecting a workspace's originating style.
- Migrating existing workspaces or customized conventions.
- Switching or resetting conventions after initialization.
- Loading arbitrary user-supplied template paths.
- Composing templates from reusable fragments.
- Adding provider, model, or network behavior to `init`.
- Adding domain-specific presets beyond the five approved values.
