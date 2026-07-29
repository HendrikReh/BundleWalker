// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { useState } from "react";
import type { FormEvent } from "react";

import { useLint } from "../../api/queries";
import type { FindingOrigin, Severity, WebLintFinding } from "../../api/types";
import { OperationProgress } from "../../components/OperationProgress";
import { RequestError } from "../../components/RequestError";

const MAX_MODEL_CHARACTERS = 255;
const SEVERITY_GROUPS: readonly {
  readonly severity: Severity;
  readonly title: string;
}[] = [
  { severity: "error", title: "Errors" },
  { severity: "warning", title: "Warnings" },
  { severity: "info", title: "Information" },
];

export function LintPage() {
  const [semantic, setSemantic] = useState(false);
  const [model, setModel] = useState("");
  const lint = useLint();

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (lint.isPending) return;
    lint.mutate({
      semantic,
      model: semantic ? model.trim() || null : null,
    });
  }

  const status = lint.isPending
    ? "Checking the knowledge base…"
    : lint.isError
      ? "Lint failed"
      : lint.data
        ? "Lint complete"
        : "";
  const deterministic = findingsByOrigin(
    lint.data?.findings ?? [],
    "deterministic",
  );
  const semanticFindings = findingsByOrigin(
    lint.data?.findings ?? [],
    "semantic",
  );

  return (
    <section className="knowledge-workbench">
      <h1>Lint</h1>
      <p>Run deterministic checks, with an optional read-only semantic pass.</p>
      <form onSubmit={submit}>
        <label>
          <input
            type="checkbox"
            checked={semantic}
            onChange={(event) => {
              setSemantic(event.currentTarget.checked);
            }}
          />
          Include semantic lint
        </label>
        <label htmlFor="lint-model">Model (optional)</label>
        <input
          id="lint-model"
          value={model}
          disabled={!semantic}
          maxLength={MAX_MODEL_CHARACTERS}
          onChange={(event) => {
            setModel(event.currentTarget.value);
          }}
        />
        <button type="submit" disabled={lint.isPending}>
          Run lint
        </button>
      </form>
      <OperationProgress message={status} />
      {lint.error ? <RequestError error={lint.error} /> : null}
      {lint.data ? (
        <>
          <FindingGroup
            id="deterministic-findings"
            title="Deterministic findings"
            findings={deterministic}
          />
          <FindingGroup
            id="semantic-findings"
            title="Semantic findings"
            findings={semanticFindings}
          />
        </>
      ) : null}
    </section>
  );
}

function findingsByOrigin(
  findings: readonly WebLintFinding[],
  origin: FindingOrigin,
) {
  return findings.filter((finding) => finding.origin === origin);
}

function FindingGroup({
  id,
  title,
  findings,
}: {
  readonly id: string;
  readonly title: string;
  readonly findings: readonly WebLintFinding[];
}) {
  const groups = SEVERITY_GROUPS.flatMap(({ severity, title }) => {
    const matching = findings.filter(
      (finding) => finding.severity === severity,
    );
    if (matching.length === 0) return [];

    const byConcept = new Map<string | null, WebLintFinding[]>();
    for (const finding of matching) {
      const conceptFindings = byConcept.get(finding.path) ?? [];
      conceptFindings.push(finding);
      byConcept.set(finding.path, conceptFindings);
    }
    const concepts = [...byConcept.entries()]
      .sort(([left], [right]) => compareConceptPaths(left, right))
      .map(([path, conceptFindings]) => ({
        path,
        findings: conceptFindings.slice().sort(compareFindings),
      }));
    return [{ severity, title, concepts }];
  });

  return (
    <section aria-labelledby={id}>
      <h2 id={id}>{title}</h2>
      {findings.length === 0 ? (
        <p>No findings.</p>
      ) : (
        groups.map((group) => {
          const severityId = `${id}-${group.severity}`;
          return (
            <section key={group.severity} aria-labelledby={severityId}>
              <h3 id={severityId}>{group.title}</h3>
              {group.concepts.map((concept, conceptIndex) => {
                const conceptId = `${severityId}-concept-${conceptIndex}`;
                return (
                  <section
                    key={
                      concept.path === null
                        ? "scope:workspace"
                        : `path:${concept.path}`
                    }
                    aria-labelledby={conceptId}
                  >
                    <h4 id={conceptId}>
                      Concept: {concept.path ?? "Workspace"}
                    </h4>
                    <ul className="lint-findings">
                      {concept.findings.map((finding, findingIndex) => (
                        <Finding
                          key={`${finding.code}:${finding.message}:${findingIndex}`}
                          finding={finding}
                        />
                      ))}
                    </ul>
                  </section>
                );
              })}
            </section>
          );
        })
      )}
    </section>
  );
}

function Finding({ finding }: { readonly finding: WebLintFinding }) {
  return (
    <li>
      <strong>{finding.code}</strong>
      <span>Severity: {finding.severity}</span>
      <p>{finding.message}</p>
      {finding.remediation ? (
        <p>Suggested action: {finding.remediation}</p>
      ) : null}
    </li>
  );
}

function compareConceptPaths(left: string | null, right: string | null) {
  if (left === right) return 0;
  if (left === null) return -1;
  if (right === null) return 1;
  return compareStrings(left, right);
}

function compareFindings(left: WebLintFinding, right: WebLintFinding) {
  return (
    compareStrings(left.code, right.code) ||
    compareStrings(left.message, right.message)
  );
}

function compareStrings(left: string, right: string): number {
  if (left < right) return -1;
  if (left > right) return 1;
  return 0;
}
