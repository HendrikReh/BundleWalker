# Conventions Style Presets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional `--conventions-style` selector to `bundlewalker init` that writes one of five packaged, editable conventions templates without changing the workspace format or existing default behavior.

**Architecture:** A focused `bundlewalker.conventions` module owns a typed style enum and trusted package-resource loader. Workspace initialization accepts the enum as a keyword-only argument and writes the selected Markdown; the Typer command only parses and forwards the choice. Preset identity is never persisted after initialization.

**Tech Stack:** Python 3.13+, `StrEnum`, `importlib.resources`, Typer, Hatchling package resources, pytest, Ruff, Pyright, Markdown.

## Global Constraints

- Python remains `>=3.13`; add no runtime or development dependency.
- Accepted CLI values are exactly `default`, `personal-workbook`, `agent-context`, `software-agent`, and `research-agent`.
- Omitting `--conventions-style` is equivalent to `--conventions-style default` and preserves the exact current default conventions bytes and success output.
- Selection is creation-time only; do not write a style identifier to `bundlewalker.toml`, logs, frontmatter, or any other workspace file.
- The generated `conventions.md` remains fully editable and is the sole authority after initialization.
- The `personal-workbook` resource must match the reviewed canonical 64-line policy byte for byte, with SHA-256 `53ca429d23a0441f3bbf56ce0dd9217200ca7071941dc1f264f8eea645629991`.
- The `default` resource must match the legacy 18-line text byte for byte, with SHA-256 `8320de0bb0d570a0aaf08425991ab75b4f1a5a94a056c62bb7ddd79f17c59680`.
- Every resource is non-empty UTF-8 ending in exactly one newline and contains no placeholder text.
- Unknown CLI styles exit `2` before target creation; missing, unreadable, malformed, or invalid UTF-8 trusted resources raise a concise `WorkspaceError` and use existing rollback.
- Initialization performs no model call, credential lookup, network access, or mutation outside the requested target.
- Existing workspaces require no migration; direct `initialize_workspace(path)` callers remain compatible.
- Keep preset prose in independent Markdown resources; do not compose it dynamically or add arbitrary user template paths.
- All tests and verification for this feature are deterministic and offline; do not run live-model evals.

---

## File map

- Create: `src/bundlewalker/conventions.py` — typed style registry and trusted resource loader.
- Create: `src/bundlewalker/convention_presets/__init__.py` — package marker for preset resources.
- Create: `src/bundlewalker/convention_presets/default.md` — byte-compatible existing default.
- Create: `src/bundlewalker/convention_presets/personal-workbook.md` — canonical reviewed personal-workbook policy.
- Create: `src/bundlewalker/convention_presets/agent-context.md` — general operational-agent context policy.
- Create: `src/bundlewalker/convention_presets/software-agent.md` — repository and coding-agent context policy.
- Create: `src/bundlewalker/convention_presets/research-agent.md` — evidence-synthesis and research-agent policy.
- Create: `tests/test_conventions.py` — enum, loader, resource-integrity, and preset-contract tests.
- Modify: `src/bundlewalker/workspace.py` — select and write a loaded template during initialization.
- Modify: `tests/test_workspace.py` — initializer selection and rollback coverage.
- Modify: `src/bundlewalker/cli.py` — expose and forward `--conventions-style`.
- Modify: `tests/cli/test_init.py` — CLI choices, help, invalid-value, and compatibility coverage.
- Modify: `README.md` — document preset purposes, template-only semantics, and examples.

### Task 1: Add the typed preset registry and packaged Markdown resources

**Files:**
- Create: `src/bundlewalker/conventions.py`
- Create: `src/bundlewalker/convention_presets/__init__.py`
- Create: `src/bundlewalker/convention_presets/default.md`
- Create: `src/bundlewalker/convention_presets/personal-workbook.md`
- Create: `src/bundlewalker/convention_presets/agent-context.md`
- Create: `src/bundlewalker/convention_presets/software-agent.md`
- Create: `src/bundlewalker/convention_presets/research-agent.md`
- Create: `tests/test_conventions.py`

**Interfaces:**
- Consumes: `bundlewalker.errors.WorkspaceError` and Python `importlib.resources`.
- Produces: `ConventionsStyle(StrEnum)` and `load_conventions(style: ConventionsStyle) -> str` for workspace and CLI integration.

- [ ] **Step 1: Write the failing preset registry and resource-contract tests**

Create `tests/test_conventions.py` with:

```python
from __future__ import annotations

import hashlib

import pytest

import bundlewalker.conventions as conventions_module
from bundlewalker.conventions import ConventionsStyle, load_conventions
from bundlewalker.errors import WorkspaceError

EXPECTED_DIGESTS = {
    ConventionsStyle.DEFAULT: "8320de0bb0d570a0aaf08425991ab75b4f1a5a94a056c62bb7ddd79f17c59680",
    ConventionsStyle.PERSONAL_WORKBOOK: (
        "53ca429d23a0441f3bbf56ce0dd9217200ca7071941dc1f264f8eea645629991"
    ),
}

PRESET_CONTRACTS = {
    ConventionsStyle.PERSONAL_WORKBOOK: (
        "reflective personal workbook",
        "state sourced facts plainly and neutrally",
        "use first person for personal interpretation",
        "evidence that could change it",
        "do not add personal interpretation or opinion to a source page",
        "never resolve the disagreement",
        "generic ai prose",
    ),
    ConventionsStyle.AGENT_CONTEXT: (
        "authoritative facts",
        "inferred conclusions",
        "proposed actions",
        "scope and applicability",
        "precedence",
        "recovery",
        "source page",
        "topic page",
        "entity page",
        "synthesis page",
    ),
    ConventionsStyle.SOFTWARE_AGENT: (
        "exact working directory",
        "architecture boundaries",
        "dependency direction",
        "generated files",
        "security",
        "definition of done",
        "current repository behavior",
        "write clean code",
    ),
    ConventionsStyle.RESEARCH_AGENT: (
        "observation",
        "reported result",
        "hypothesis",
        "speculation",
        "sample",
        "timeframe",
        "source count",
        "absence of evidence",
        "falsify",
    ),
}


def test_conventions_style_has_the_exact_public_values() -> None:
    assert tuple(style.value for style in ConventionsStyle) == (
        "default",
        "personal-workbook",
        "agent-context",
        "software-agent",
        "research-agent",
    )


@pytest.mark.parametrize("style", list(ConventionsStyle))
def test_each_conventions_resource_is_valid_text(style: ConventionsStyle) -> None:
    text = load_conventions(style)

    assert text.strip()
    assert text.endswith("\n")
    assert not text.endswith("\n\n")
    assert "placeholder" not in text.casefold()


@pytest.mark.parametrize(("style", "digest"), EXPECTED_DIGESTS.items())
def test_canonical_conventions_resources_are_byte_exact(
    style: ConventionsStyle,
    digest: str,
) -> None:
    content = load_conventions(style).encode("utf-8")

    assert hashlib.sha256(content).hexdigest() == digest
    if style is ConventionsStyle.DEFAULT:
        assert len(content.decode("utf-8").splitlines()) == 18
    else:
        assert len(content.decode("utf-8").splitlines()) == 64


@pytest.mark.parametrize(("style", "required_phrases"), PRESET_CONTRACTS.items())
def test_each_specialized_preset_has_its_required_contract(
    style: ConventionsStyle,
    required_phrases: tuple[str, ...],
) -> None:
    text = load_conventions(style).casefold()

    missing = [phrase for phrase in required_phrases if phrase not in text]
    assert not missing, f"{style.value} missing: {missing}"


@pytest.mark.parametrize(
    "failure",
    [
        ModuleNotFoundError("private package path"),
        FileNotFoundError("private resource path"),
        UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid byte"),
    ],
)
def test_conventions_loader_sanitizes_resource_failures(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    def fail_resources(_package: object) -> object:
        raise failure

    monkeypatch.setattr(conventions_module.resources, "files", fail_resources)

    with pytest.raises(WorkspaceError) as caught:
        load_conventions(ConventionsStyle.RESEARCH_AGENT)

    assert str(caught.value) == "could not load conventions style: research-agent"
    assert "private" not in str(caught.value)
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
uv run pytest tests/test_conventions.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'bundlewalker.conventions'`.

- [ ] **Step 3: Add the enum, trusted resource loader, and resource package marker**

Create `src/bundlewalker/conventions.py` with:

```python
from __future__ import annotations

from enum import StrEnum
from importlib import resources

from bundlewalker.errors import WorkspaceError


class ConventionsStyle(StrEnum):
    """Creation-time conventions templates supported by workspace initialization."""

    DEFAULT = "default"
    PERSONAL_WORKBOOK = "personal-workbook"
    AGENT_CONTEXT = "agent-context"
    SOFTWARE_AGENT = "software-agent"
    RESEARCH_AGENT = "research-agent"


_PRESET_FILES: dict[ConventionsStyle, str] = {
    ConventionsStyle.DEFAULT: "default.md",
    ConventionsStyle.PERSONAL_WORKBOOK: "personal-workbook.md",
    ConventionsStyle.AGENT_CONTEXT: "agent-context.md",
    ConventionsStyle.SOFTWARE_AGENT: "software-agent.md",
    ConventionsStyle.RESEARCH_AGENT: "research-agent.md",
}


def load_conventions(style: ConventionsStyle) -> str:
    """Load and validate one trusted packaged conventions template."""
    try:
        text = (
            resources.files("bundlewalker.convention_presets")
            .joinpath(_PRESET_FILES[style])
            .read_text(encoding="utf-8")
        )
    except (ImportError, OSError, UnicodeError) as exc:
        raise WorkspaceError(f"could not load conventions style: {style.value}") from exc
    if not text.strip() or not text.endswith("\n") or text.endswith("\n\n"):
        raise WorkspaceError(f"could not load conventions style: {style.value}")
    return text
```

Create `src/bundlewalker/convention_presets/__init__.py` with:

```python
"""Packaged creation-time conventions templates."""
```

- [ ] **Step 4: Add the byte-compatible default and personal-workbook resources**

Create `src/bundlewalker/convention_presets/default.md` with exactly:

```markdown
# BundleWalker Conventions

## Writing

- Prefer concise, factual prose and descriptive headings.
- Preserve uncertainty and record conflicting claims explicitly.
- Link related concepts using OKF Markdown links.

## Naming

- Use stable, lowercase ASCII slugs for concept filenames.
- Keep tags short, normalized, and relevant.

## Knowledge maintenance

- Source pages describe what an immutable source says.
- Topic and Entity pages accumulate knowledge across sources.
- Synthesis pages capture reviewed, question-driven conclusions.
```

Create `src/bundlewalker/convention_presets/personal-workbook.md` with exactly:

```markdown
# Personal Workbook Conventions

## Purpose

- Treat this knowledge base as a reflective personal workbook, not an encyclopedia or polished report.
- Help me develop understanding through evidence, connections, provisional judgments, and open questions.

## Voice

- Write in a reflective and exploratory voice without becoming vague or indecisive.
- State sourced facts plainly and neutrally.
- Use first person for personal interpretation, judgment, priorities, decisions, and unresolved questions.
- Prefer short, connected prose. Use bullets only when the material is genuinely list-shaped.
- Preserve uncertainty without mechanically hedging every sentence.
- When offering a provisional assessment, state the current view, why it seems stronger, and the evidence that could change it.
- Stop when the thought is complete. Do not restate a conclusion in different words.

## Evidence and interpretation

- Fidelity to evidence takes priority over voice.
- Cite the evidence behind factual claims and evidence-based interpretations.
- Distinguish explicitly between what a source establishes and what I infer from it.
- Do not present my interpretation as though it came from a source.
- Do not strengthen, generalize, or resolve a source's uncertainty without support.
- Prefer a precise unresolved question to an unsupported answer.
- Treat BundleWalker's path, citation, schema, review, and transaction validation as authoritative.

## Concept responsibilities

- **Source:** A Source page is a faithful evidence record. Explain what the immutable source says while preserving its emphasis, uncertainty, qualifications, and contradictions. Do not add personal interpretation or opinion to a Source page; place it in a Topic or Synthesis page.
- **Topic:** A Topic page is a living understanding of a reusable idea. Connect sources, compare claims, identify tensions and implications, and include a clearly marked provisional assessment when useful.
- **Entity:** An Entity page collects durable knowledge about an identifiable person, organization, project, tool, place, or other thing. Explain why it matters here instead of merely accumulating facts.
- **Synthesis:** A Synthesis page answers a specific question. It may take a position, show the reasoning, compare alternatives, record caveats, and identify what remains unresolved.
- Let headings follow the material. Do not create a section when it would contain only filler.

## Connections, disagreement, and change

- Search existing knowledge before proposing a new concept; deepen the same idea instead of creating a near-duplicate.
- When evidence agrees, combine it into a stronger shared understanding rather than repeating the claim once per source.
- Note independent corroboration when it materially changes confidence.
- When evidence conflicts, state the disagreement directly.
- Identify whether a conflict concerns facts, definitions, assumptions, values, or context.
- Give my current provisional assessment when support exists, and explain why it seems stronger.
- Record what evidence or experience could change that assessment.
- Never resolve the disagreement by silently choosing one source or counting sources as votes.
- Revise or extend an existing Topic or Entity when understanding changes.
- Preserve an earlier interpretation when the change itself is informative.
- Link concepts when the relationship helps future thinking or retrieval, not merely because both mention the same noun.

## Naming and maintenance

- Use stable, descriptive, lowercase ASCII slugs for concept paths.
- Use a small number of short, normalized tags that describe durable themes.
- Avoid synonymous, one-off, or type-duplicating tags.

## Avoid

- Polished but impersonal summaries and generic AI prose.
- Stock transitions and generic “key takeaway” language.
- Claims presented as settled when evidence remains incomplete.
- Artificial balance between claims with materially different support.
- Repeated conclusions or background that does not advance the thought.
- Forced implications, recommendations, or open-question sections with nothing substantive to add.
- Manufactured completeness that hides a real gap in knowledge.
```

- [ ] **Step 5: Add the general operational agent resource**

Create `src/bundlewalker/convention_presets/agent-context.md` with exactly:

```markdown
# Agent Context Conventions

## Purpose

- Optimize this knowledge bundle for safe, efficient use by operational AI agents.
- Make authoritative context, scope, constraints, procedures, and failure handling easy to retrieve.

## Writing and authority

- Write concise, explicit prose for unambiguous retrieval rather than personal reflection.
- Separate authoritative facts, inferred conclusions, and proposed actions.
- State scope and applicability; do not present local rules as universal.
- Identify the authority or source of a rule when that affects whether an agent may rely on it.
- Include version, effective-date, or freshness context in the body when safe use depends on it.
- Prefer exact interfaces, thresholds, states, and conditions over general advice.
- Preserve uncertainty and unsupported gaps instead of manufacturing operational certainty.

## Concept responsibilities

- **Source:** A Source page faithfully records an authoritative artifact, observation, specification, policy, or input. Do not add inferred policy or proposed action.
- **Topic:** A Topic page captures a reusable rule, capability, procedure, domain constraint, or operational model across relevant Sources.
- **Entity:** An Entity page describes an actor, system, component, organization, resource, dataset, service, or tool and its operational significance.
- **Synthesis:** A Synthesis page provides a task brief, decision record, runbook, recovery guide, or comparative assessment for a specific question.
- Use headings that reveal operational structure; omit sections that would contain only filler.

## Operational knowledge

- Record what an agent may rely on, what it may do, and what it must not do when evidence supports those boundaries.
- State required inputs, preconditions, outputs, side effects, and success conditions for procedures.
- Record failure conditions, safe stopping points, rollback or recovery paths, and escalation conditions.
- Distinguish current state from desired state and proposed changes.
- Keep examples clearly labeled; do not let examples silently redefine a rule.
- Link prerequisites, dependent concepts, responsible Entities, and relevant procedures when the relationship aids execution.

## Conflicts and maintenance

- Search existing knowledge before creating a concept; update the same operational idea instead of creating a near-duplicate.
- Record conflicting instructions explicitly and identify their differing scope, authority, version, or assumptions.
- State precedence only when supported by evidence; otherwise leave the conflict unresolved and require escalation.
- Replace obsolete operational claims when authoritative evidence changes, while preserving material transition context.
- Do not count repeated claims as independent confirmation when they share the same underlying Source.

## Naming and tags

- Use stable, descriptive, lowercase ASCII slugs for concept paths.
- Use a small number of normalized tags for durable operational domains, systems, or capabilities.
- Avoid one-off tags, synonyms, and tags that merely repeat the concept type.

## Avoid

- Generic AI prose, motivational language, and repeated summaries.
- Commands, permissions, or recovery steps not supported by evidence.
- Ambiguous terms such as “normally,” “appropriate,” or “as needed” when an exact condition is known.
- Unsupported certainty, silent conflict resolution, and stale state presented as current.
- Procedures without preconditions, success criteria, or failure handling when those details are available.
```

- [ ] **Step 6: Add the software-development agent resource**

Create `src/bundlewalker/convention_presets/software-agent.md` with exactly:

```markdown
# Software Agent Conventions

## Purpose

- Optimize this knowledge bundle for coding and repository agents.
- Make repository structure, commands, architecture, invariants, validation, and known traps explicit.

## Evidence and current state

- Separate current repository behavior, desired behavior, and proposed changes.
- Cite the repository artifact, documentation, test, or decision that supports each consequential claim.
- Do not present inferred architecture or an example as an established repository rule.
- State scope and applicability for service-specific, directory-specific, platform-specific, or version-specific guidance.
- Preserve uncertainty when code, documentation, and observed behavior disagree.

## Repository context

- Record a concise repository or component map when it improves navigation.
- Give authoritative commands with the exact working directory, relevant flags, and expected success signal.
- State architecture boundaries, dependency direction, public interfaces, and ownership of side effects.
- Identify generated files and their sources of truth; never instruct an agent to edit generated output directly.
- Record formatting, linting, testing, building, migration, and definition of done requirements.
- State security, tenancy, privacy, data-integrity, and backward-compatibility invariants explicitly.
- Capture known traps, intentionally unusual decisions, required tooling, and safe failure-recovery procedures.

## Concept responsibilities

- **Source:** A Source page faithfully records code, configuration, documentation, tests, logs, specifications, or decisions. Do not add speculative design.
- **Topic:** A Topic page captures reusable architecture, workflow, validation, security, or operational guidance across relevant Sources.
- **Entity:** An Entity page describes a repository, service, package, component, interface, datastore, environment, dependency, tool, or responsible team.
- **Synthesis:** A Synthesis page provides a task brief, implementation decision, migration plan, incident analysis, runbook, or comparative technical assessment.
- Prefer natural headings suited to the repository context; do not create empty template sections.

## Change and validation guidance

- Search existing knowledge before creating a concept; update the authoritative concept for the same rule or component.
- Distinguish required checks from optional diagnostics and state when each command applies.
- Record prerequisites, irreversible effects, rollback steps, and escalation paths for risky operations.
- Preserve conflicting implementation claims until code, tests, or authoritative decisions establish precedence.
- Keep commands and interface descriptions synchronized with the evidence that defines them.
- Link components to the architecture, constraints, commands, and runbooks that govern them when useful.

## Naming and tags

- Use stable, descriptive, lowercase ASCII slugs for concept paths.
- Use normalized tags for durable technical domains, not every library or symbol mentioned.
- Prefer repository-native names for components and interfaces.

## Avoid

- Generic instructions such as “write clean code,” “follow best practices,” or “test thoroughly.”
- Unverified commands, guessed file paths, and speculative dependencies.
- Architecture descriptions that omit boundaries or dependency direction.
- Validation lists that do not identify the relevant scope or expected success signal.
- Silent changes to security, compatibility, tenancy, persistence, or generated-file invariants.
- Repeated documentation that should instead link to one authoritative concept.
```

- [ ] **Step 7: Add the research-agent resource**

Create `src/bundlewalker/convention_presets/research-agent.md` with exactly:

```markdown
# Research Agent Conventions

## Purpose

- Optimize this knowledge bundle for evidence synthesis, research planning, and analytical agents.
- Preserve provenance, methods, limitations, competing explanations, and revision conditions.

## Evidence and claims

- Distinguish observation, reported result, interpretation, hypothesis, and speculation explicitly.
- State the source type, method, population or sample, timeframe, and limitations when they affect a claim.
- Separate primary evidence from reviews, commentary, and claims repeated from another Source.
- Evaluate evidence quality without treating source count as proof.
- Distinguish absence of evidence from evidence of absence.
- Use precise claim scope; do not generalize beyond the studied population, conditions, or timeframe.
- Preserve uncertainty and quantify it only when the Source supports a quantity.

## Concept responsibilities

- **Source:** A Source page faithfully records a paper, dataset, interview, observation, experiment, report, or other evidence artifact. Preserve its method, scope, and limitations.
- **Topic:** A Topic page accumulates reusable findings, theories, mechanisms, methods, or debates across relevant Sources.
- **Entity:** An Entity page describes a researcher, institution, population, dataset, method, instrument, intervention, location, or studied object.
- **Synthesis:** A Synthesis page answers a research question with explicit reasoning, evidence quality, alternative explanations, limitations, and confidence.
- Let headings follow the research question and evidence; omit sections that would contain only filler.

## Comparison and disagreement

- Search existing knowledge before creating a concept; extend the same finding, method, or debate instead of creating a near-duplicate.
- When Sources agree, identify whether the evidence is genuinely independent and whether methods or populations are comparable.
- When Sources conflict, state whether disagreement concerns facts, definitions, methods, assumptions, values, populations, or context.
- Do not silently choose a winner or use citation count as a vote.
- Give a provisional conclusion only when evidence quality supports it, and state the reasoning.
- Record alternative explanations and the evidence that could falsify or revise the conclusion.
- Preserve a material earlier interpretation when new evidence changes the research picture.

## Research gaps and maintenance

- Record precise unanswered questions rather than broad calls for “more research.”
- Identify missing evidence, measurement limits, confounders, and scope boundaries when supported.
- Include publication date, data period, or version context when freshness affects interpretation.
- Link findings to the Sources, methods, Entities, and competing Topics needed to evaluate them.
- Update conclusions when stronger or more applicable evidence arrives without erasing meaningful uncertainty.

## Naming and tags

- Use stable, descriptive, lowercase ASCII slugs for concept paths.
- Use normalized tags for durable fields, methods, populations, or phenomena.
- Avoid one-off tags and terminology that obscures the Source's own definitions.

## Avoid

- Broad narrative summaries that hide claim boundaries or methods.
- Causal language for correlational or otherwise insufficient evidence.
- False balance between evidence of materially different quality.
- Unsupported confidence, vague uncertainty, and unmarked speculation.
- Conclusions that omit known limitations or plausible alternative explanations.
- Recommendations that outrun the evidence or silently introduce values not present in the Sources.
```

- [ ] **Step 8: Run the preset tests and verify GREEN**

Run:

```bash
uv run pytest tests/test_conventions.py -v
```

Expected: all 15 parametrized cases pass with no warnings.

- [ ] **Step 9: Commit the typed registry and resources**

Run:

```bash
git add src/bundlewalker/conventions.py src/bundlewalker/convention_presets tests/test_conventions.py
git diff --cached --check
git diff --cached --name-only
git commit -m "feat: add conventions style presets"
```

Expected: the staged names contain exactly the loader, six resource-package files (`__init__.py` plus five Markdown templates), and `tests/test_conventions.py`; the diff check is silent; the commit succeeds.

### Task 2: Integrate preset selection with workspace initialization and rollback

**Files:**
- Modify: `tests/test_workspace.py:1-55`
- Modify: `src/bundlewalker/workspace.py:1-135`

**Interfaces:**
- Consumes: `ConventionsStyle` and `load_conventions(style) -> str` from Task 1.
- Produces: `initialize_workspace(path: Path, *, conventions_style: ConventionsStyle = ConventionsStyle.DEFAULT, occurred_at: datetime | None = None) -> Workspace`.

- [ ] **Step 1: Add failing initializer selection and loader-rollback tests**

Add this import beside the existing imports in `tests/test_workspace.py`:

```python
import bundlewalker.workspace as workspace_module
from bundlewalker.conventions import ConventionsStyle, load_conventions
```

In `test_initialize_writes_exact_default_config_and_discovery_walks_upward`, add this assertion after the existing config assertion:

```python
    assert workspace.conventions_file.read_text(encoding="utf-8") == load_conventions(
        ConventionsStyle.DEFAULT
    )
```

Add these tests immediately after that existing test:

```python
@pytest.mark.parametrize("style", list(ConventionsStyle))
def test_initialize_writes_selected_conventions_and_remains_lint_clean(
    tmp_path: Path,
    style: ConventionsStyle,
) -> None:
    workspace = initialize_workspace(
        tmp_path / style.value,
        conventions_style=style,
    )

    assert workspace.conventions_file.read_text(encoding="utf-8") == load_conventions(style)
    assert not has_errors(lint_bundle(workspace.wiki_dir, workspace.root))


@pytest.mark.parametrize("preexisting_root", [False, True])
def test_initialize_rolls_back_a_conventions_loader_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    preexisting_root: bool,
) -> None:
    root = tmp_path / "knowledge"
    if preexisting_root:
        root.mkdir()
    sibling = tmp_path / "keep.txt"
    sibling.write_text("keep", encoding="utf-8")

    def fail_loader(_style: ConventionsStyle) -> str:
        raise WorkspaceError("could not load conventions style: research-agent")

    monkeypatch.setattr(workspace_module, "load_conventions", fail_loader)

    with pytest.raises(WorkspaceError, match="could not load conventions style"):
        initialize_workspace(
            root,
            conventions_style=ConventionsStyle.RESEARCH_AGENT,
        )

    if preexisting_root:
        assert root.is_dir()
        assert list(root.iterdir()) == []
    else:
        assert not root.exists()
    assert sibling.read_text(encoding="utf-8") == "keep"
```

- [ ] **Step 2: Run the focused initializer tests and verify RED**

Run:

```bash
uv run pytest tests/test_workspace.py -k 'selected_conventions or conventions_loader or exact_default' -v
```

Expected: the existing default test passes, while seven new parametrized cases fail because `initialize_workspace` does not yet accept `conventions_style` and `workspace.py` has no `load_conventions` binding for monkeypatching.

- [ ] **Step 3: Load and write the selected preset inside the existing transaction boundary**

In `src/bundlewalker/workspace.py`, add:

```python
from bundlewalker.conventions import ConventionsStyle, load_conventions
```

Delete the complete `DEFAULT_CONVENTIONS_TEXT` multiline constant.

Change the initializer signature to:

```python
def initialize_workspace(
    path: Path,
    *,
    conventions_style: ConventionsStyle = ConventionsStyle.DEFAULT,
    occurred_at: datetime | None = None,
) -> Workspace:
```

Replace the beginning of the existing `try` body with:

```python
    try:
        root.mkdir(parents=True, exist_ok=not created_root)
        conventions_text = load_conventions(conventions_style)
        (root / CONFIG_FILENAME).write_text(DEFAULT_CONFIG_TEXT, encoding="utf-8")
        (root / "conventions.md").write_text(conventions_text, encoding="utf-8")
```

Leave the rest of initialization and the entire existing exception/rollback block unchanged.

- [ ] **Step 4: Rerun workspace tests and verify GREEN**

Run:

```bash
uv run pytest tests/test_workspace.py -v
```

Expected: all workspace tests pass, including all five styles, unchanged default behavior, and both loader-failure rollback cases.

- [ ] **Step 5: Run initialization CLI regression tests**

Run:

```bash
uv run pytest tests/cli/test_init.py -v
```

Expected: all existing init CLI tests pass unchanged, proving direct default callers and success output remain compatible.

- [ ] **Step 6: Commit the workspace integration**

Run:

```bash
git add src/bundlewalker/workspace.py tests/test_workspace.py
git diff --cached --check
git diff --cached --name-only
git commit -m "feat: initialize with a conventions preset"
```

Expected: exactly `src/bundlewalker/workspace.py` and `tests/test_workspace.py` are staged; the diff check is silent; the commit succeeds.

### Task 3: Expose the CLI selector and document preset use

**Files:**
- Modify: `tests/cli/test_init.py:1-75`
- Modify: `src/bundlewalker/cli.py:1-45`
- Modify: `README.md:34-79,139-147`

**Interfaces:**
- Consumes: `ConventionsStyle` and the Task 2 `initialize_workspace(..., conventions_style=...)` API.
- Produces: `bundlewalker init PATH [--conventions-style STYLE]` with the exact five accepted values and unchanged success output.

- [ ] **Step 1: Add failing CLI style, help, and invalid-value tests**

Add this import to `tests/cli/test_init.py`:

```python
from bundlewalker.conventions import ConventionsStyle, load_conventions
```

Add these tests after `test_init_creates_a_lint_clean_workspace`:

```python
@pytest.mark.parametrize("style", list(ConventionsStyle))
def test_init_selects_the_requested_conventions_style(
    tmp_path: Path,
    style: ConventionsStyle,
) -> None:
    root = tmp_path / style.value

    result = runner.invoke(
        app,
        ["init", str(root), "--conventions-style", style.value],
    )

    assert result.exit_code == 0, result.output
    assert result.output == f"Initialized BundleWalker workspace at {root.resolve()}\n"
    assert (root / "conventions.md").read_text(encoding="utf-8") == load_conventions(style)
    assert not has_errors(lint_bundle(root / "wiki", root))


def test_init_help_lists_all_conventions_styles() -> None:
    result = runner.invoke(app, ["init", "--help"])

    assert result.exit_code == 0, result.output
    assert "--conventions-style" in result.output
    for style in ConventionsStyle:
        assert style.value in result.output


def test_init_rejects_an_unknown_conventions_style_before_creating_target(
    tmp_path: Path,
) -> None:
    root = tmp_path / "knowledge"

    result = runner.invoke(
        app,
        ["init", str(root), "--conventions-style", "unknown-style"],
    )

    assert result.exit_code == 2
    assert "--conventions-style" in result.output
    assert not root.exists()
```

- [ ] **Step 2: Run the new CLI tests and verify RED**

Run:

```bash
uv run pytest tests/cli/test_init.py -k 'conventions_style or conventions_styles' -v
```

Expected: seven cases fail because `init` does not yet recognize `--conventions-style` or list the values in help.

- [ ] **Step 3: Add the typed Typer option and forward it to initialization**

Add this import in `src/bundlewalker/cli.py`:

```python
from bundlewalker.conventions import ConventionsStyle
```

Replace `init_command` with:

```python
@app.command("init")
def init_command(
    path: Path,
    conventions_style: ConventionsStyle = typer.Option(
        ConventionsStyle.DEFAULT,
        "--conventions-style",
        help="Initial conventions template.",
    ),
) -> None:
    """Create a BundleWalker workspace at PATH."""
    try:
        workspace = initialize_workspace(path, conventions_style=conventions_style)
    except BundleWalkerError as exc:
        _exit_for_error(exc)
    typer.echo(f"Initialized BundleWalker workspace at {workspace.root}")
```

- [ ] **Step 4: Rerun all init CLI tests and verify GREEN**

Run:

```bash
uv run pytest tests/cli/test_init.py -v
```

Expected: all init CLI cases pass, including the five styles, help choices, invalid value, unchanged default, non-empty target, and rollback behavior.

- [ ] **Step 5: Document the creation-time presets and examples**

In the README copy-paste workflow, replace:

```bash
uv run bundlewalker init ./my-knowledge
```

with:

```bash
uv run bundlewalker init ./my-knowledge --conventions-style personal-workbook
```

Under `### Initialize a workspace`, replace the command block and its following paragraph with:

````markdown
```bash
uv run bundlewalker init PATH [--conventions-style STYLE]
```

`PATH` must be new or empty. Initialization creates the configuration, conventions, raw-source
directory, four wiki categories, generated indexes, and initial log. The empty wiki is checked
with deterministic lint before the command succeeds. Initialization never needs a model.

`--conventions-style` chooses the initial, editable `conventions.md` template:

- `default`: the original concise, neutral BundleWalker conventions; this remains the default.
- `personal-workbook`: reflective, evidence-backed personal understanding and open questions.
- `agent-context`: general operational context, authority, constraints, procedures, and recovery.
- `software-agent`: repository maps, commands, architecture, invariants, validation, and traps.
- `research-agent`: methods, evidence quality, competing claims, limitations, and research gaps.

The choice is not stored as workspace metadata. After initialization, `conventions.md` is the sole
authority and may be customized freely. Examples:

```bash
uv run bundlewalker init ./personal-notes --conventions-style personal-workbook
uv run bundlewalker init ./operations --conventions-style agent-context
uv run bundlewalker init ./repository-context --conventions-style software-agent
uv run bundlewalker init ./research-context --conventions-style research-agent
```
````

In the existing `conventions.md` explanation under Workspace layout, append:

```markdown
The initialization presets are starting points only. BundleWalker does not remember, enforce, or
upgrade the selected style after creating the workspace.
```

- [ ] **Step 6: Run the complete offline verification suite**

Run:

```bash
uv run pytest -m 'not eval' -q
uv run ruff format --check src tests
uv run ruff check src tests
uv run pyright
```

Expected: all non-eval tests pass; Ruff reports every file formatted and no lint errors; Pyright reports zero errors.

- [ ] **Step 7: Verify final scope and commit the CLI and documentation**

Run:

```bash
git status --short
git diff --check
git add src/bundlewalker/cli.py tests/cli/test_init.py README.md
git diff --cached --check
git diff --cached --name-only
git commit -m "feat: choose conventions style during init"
```

Expected: exactly `src/bundlewalker/cli.py`, `tests/cli/test_init.py`, and `README.md` are staged; both diff checks are silent; the commit succeeds.
