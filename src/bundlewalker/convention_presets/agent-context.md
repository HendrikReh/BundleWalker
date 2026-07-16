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
