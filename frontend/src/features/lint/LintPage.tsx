// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { useState } from "react";
import type { FormEvent } from "react";

import { useLint } from "../../api/queries";
import type { FindingOrigin, WebLintFinding } from "../../api/types";
import { OperationProgress } from "../../components/OperationProgress";
import { RequestError } from "../../components/RequestError";

const MAX_MODEL_CHARACTERS = 255;

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
  return (
    <section aria-labelledby={id}>
      <h2 id={id}>{title}</h2>
      {findings.length === 0 ? (
        <p>No findings.</p>
      ) : (
        <ul className="lint-findings">
          {findings.map((finding) => (
            <li key={`${finding.origin}:${finding.code}:${finding.path ?? ""}`}>
              <strong>{finding.code}</strong>
              <span>Severity: {finding.severity}</span>
              <p>{finding.message}</p>
              {finding.path ? <p>Concept: {finding.path}</p> : null}
              {finding.remediation ? (
                <p>Suggested action: {finding.remediation}</p>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
