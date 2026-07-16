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
