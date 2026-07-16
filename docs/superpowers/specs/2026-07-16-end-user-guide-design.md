# BundleWalker End-User Guide Design

## Goal

Create a dedicated end-user guide that helps a new user install BundleWalker, configure an
agent model, complete a first knowledge workflow, understand every supported CLI command, and
choose among all currently available conventions presets.

The guide must work both as a beginner-friendly path and as a complete operating reference.

## Audience

The primary reader is a BundleWalker user who may understand command-line basics but should not
need prior knowledge of BundleWalker's architecture, OKF internals, PydanticAI, or the source
code.

The guide assumes:

- Python 3.13 or newer;
- `uv`;
- a local checkout of this repository; and
- provider credentials only when using agent-backed commands.

## Deliverables

Create:

- `docs/user-guide.md` as the dedicated end-user source of truth.

Modify:

- `README.md` with a short, prominent link to the user guide near installation and first use.

Do not split the guide across multiple files. Do not move development, testing, or live-evaluation
instructions out of the README.

## Guide Structure

Organize `docs/user-guide.md` in this task-oriented order:

1. What BundleWalker does
2. Installation
3. Model and provider setup
4. Five-minute quick start
5. Workspace discovery and layout
6. Complete command reference
   - `init`
   - `ingest`
   - `ask`
   - `lint`
7. Conventions preset guide
8. Review and confirmation behavior
9. Exit codes
10. Troubleshooting and safety notes

Use a linked table of contents so the document also works as a reference.

## Command Documentation Contract

Document exactly the four commands exposed by `bundlewalker --help`:

- `init`
- `ingest`
- `ask`
- `lint`

For each command, include:

- exact syntax, arguments, options, and defaults;
- whether a model is required;
- what the command reads and writes;
- whether it presents a review and confirmation step;
- at least one copy-paste example; and
- important success, no-op, decline, or failure behavior where applicable.

The guide must cover these options:

- `init --conventions-style STYLE`;
- `ingest --model MODEL`;
- `ask --model MODEL`;
- `ask --save`;
- `lint --semantic`; and
- `lint --model MODEL`.

Do not document internal functions, planned commands, development commands, or unsupported
input types as end-user CLI features.

## Model and Provider Guidance

Explain that agent-backed commands resolve a model in this order:

1. `--model MODEL`
2. `BUNDLEWALKER_MODEL`

State which operations are model-free:

- `init`;
- deterministic `lint`; and
- duplicate-ingest detection before model resolution.

Keep the main explanation provider-neutral using a
`<pydantic-ai-model-string>` placeholder. Add one clearly labeled OpenAI example showing:

- `OPENAI_API_KEY`;
- `BUNDLEWALKER_MODEL`; and
- a non-secret example model string that is verified against current official guidance and the
  installed PydanticAI stack during implementation.

Never include a real credential, copied environment value, or user-specific secret. Explain that
credentials and model identifiers are process environment settings and are not persisted in the
workspace.

## Conventions Preset Reference

Document exactly these five accepted styles:

- `default`;
- `personal-workbook`;
- `agent-context`;
- `software-agent`; and
- `research-agent`.

Use a comparison table with:

- style name;
- intended use;
- knowledge emphasis; and
- a sample `init` command.

Describe each preset from its packaged Markdown resource, not only from short README summaries.
Make these lifecycle semantics explicit:

- the style is selected only during initialization;
- the selection is not stored as workspace metadata;
- BundleWalker does not later enforce or upgrade the selected style; and
- the generated, editable `conventions.md` is the sole authority after initialization.

## Workflow and Safety Guidance

Explain the complete operating flow:

1. initialize a workspace;
2. enter the workspace or run a command from a descendant directory;
3. ingest one supported source at a time;
4. review and accept or decline the proposed diff;
5. ask cited questions;
6. optionally save an answer through the same review path; and
7. run deterministic or semantic lint.

Cover:

- immutable raw source bytes;
- review-before-write behavior;
- decline, interruption, and end-of-input as successful unchanged outcomes;
- duplicate ingestion as a successful no-op;
- `ask` as read-only unless `--save` is supplied;
- `ask --save` reusing the validated answer without another model call;
- deterministic lint versus advisory semantic lint;
- upward workspace discovery;
- transaction recovery;
- concise error output and exit codes `0`, `1`, and `2`;
- Git as a recommended but external workflow; and
- privacy risks when publishing `raw/` source material.

## Examples

Examples must be copy-pasteable after replacing explicit placeholders. Use shell quoting around
questions and model strings. Show:

- installation and help;
- provider-neutral model configuration;
- one OpenAI configuration;
- quick-start initialization, ingestion, querying, saving, and linting;
- one initialization example for every conventions preset;
- explicit `--model` override;
- plain and semantic lint; and
- accepted and declined review outcomes in explanatory prose.

Examples run from either:

- the repository root with paths to a workspace; or
- inside the workspace with `uv run --project /path/to/BundleWalker bundlewalker ...`.

The guide must explain the chosen context before presenting commands so users do not encounter
an unexplained missing-project error after changing directories.

## Accuracy Sources

Use these sources in descending order:

1. live output from `uv run bundlewalker --help` and each command's `--help`;
2. `src/bundlewalker/cli.py` and command workflow implementations;
3. CLI and acceptance tests for observable behavior;
4. packaged files in `src/bundlewalker/convention_presets/`; and
5. the README for established terminology.

Use current official OpenAI guidance and the installed PydanticAI package for the OpenAI example.
If the two disagree, prefer a model string proven by the installed runtime and label it as an
example rather than a universal default.

## Verification

Before completion:

- compare the documented command inventory, arguments, options, and defaults with all live
  `--help` outputs;
- verify the preset table contains every and only `ConventionsStyle` value;
- run every documented operation that is deterministic and safe in a temporary workspace;
- verify internal Markdown links and the README link;
- scan for placeholders that are not explicitly explained;
- scan for real-looking secrets or user-specific values;
- run `git diff --check`; and
- run the existing offline test and static-analysis suite.

No live model call, credential access, network-backed inference, or paid evaluation is required
to validate the guide.

## Non-Goals

This work does not:

- add, rename, or change CLI commands or options;
- add or modify conventions presets;
- change workspace or OKF behavior;
- provide a developer API reference;
- duplicate the full development and evaluation documentation;
- document unsupported ingestion formats or future features; or
- publish, push, or otherwise distribute the documentation.
