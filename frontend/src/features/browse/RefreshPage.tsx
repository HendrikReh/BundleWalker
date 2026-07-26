// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { FormEvent } from "react";
import { useNavigate, useParams } from "react-router";

import { queryKeys, useConcept, usePrepareRefresh } from "../../api/queries";
import { MarkdownContent } from "../../components/MarkdownContent";
import { OperationProgress } from "../../components/OperationProgress";
import { RequestError } from "../../components/RequestError";
import { isRefreshEligibleConcept } from "./refresh";

const MAX_INSTRUCTION_CHARACTERS = 20_000;
const MAX_MODEL_CHARACTERS = 255;

export function RefreshPage() {
  const conceptId = useParams()["*"] ?? "";
  const [instruction, setInstruction] = useState("");
  const [model, setModel] = useState("");
  const concept = useConcept(conceptId);
  const refresh = usePrepareRefresh(conceptId);
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (
      refresh.isPending ||
      !instruction.trim() ||
      concept.data === undefined ||
      !isRefreshEligibleConcept(concept.data)
    ) {
      return;
    }
    refresh.mutate(
      {
        instruction,
        concept_id: concept.data.concept_id,
        model: model.trim() || null,
      },
      {
        onSuccess: async (result) => {
          if (result.status === "current") return;
          await Promise.all([
            queryClient.invalidateQueries(
              { queryKey: queryKeys.workspace },
              { throwOnError: true },
            ),
            queryClient.invalidateQueries(
              { queryKey: queryKeys.review },
              { throwOnError: true },
            ),
          ]);
          navigate(`/review/${encodeURIComponent(result.review.review_id)}`);
        },
      },
    );
  }

  if (concept.error) return <RequestError error={concept.error} />;
  if (concept.data === undefined) return <p role="status">Loading concept…</p>;
  if (!isRefreshEligibleConcept(concept.data)) {
    return (
      <section>
        <h1>Prepare refresh</h1>
        <p role="alert">
          Only generated Synthesis concepts with canonical IDs can be refreshed.
        </p>
      </section>
    );
  }

  const status = refresh.isPending
    ? "Preparing refresh proposal…"
    : refresh.isError
      ? "Refresh preparation failed"
      : refresh.data?.status === "current"
        ? "Synthesis is already current; no review was created"
        : refresh.data?.status === "pending"
          ? "Refresh proposal ready"
          : "";

  return (
    <section className="knowledge-workbench">
      <h1>Prepare refresh</h1>
      <p>
        Update <strong>{concept.data.title}</strong> using current knowledge.
      </p>
      <form onSubmit={submit}>
        <label htmlFor="refresh-instruction">Refresh instruction</label>
        <textarea
          id="refresh-instruction"
          required
          maxLength={MAX_INSTRUCTION_CHARACTERS}
          value={instruction}
          onChange={(event) => {
            setInstruction(event.currentTarget.value);
          }}
        />
        <label htmlFor="refresh-model">Model (optional)</label>
        <input
          id="refresh-model"
          maxLength={MAX_MODEL_CHARACTERS}
          value={model}
          onChange={(event) => {
            setModel(event.currentTarget.value);
          }}
        />
        <button type="submit" disabled={refresh.isPending}>
          Prepare refresh
        </button>
      </form>
      {status ? <OperationProgress message={status} /> : null}
      {refresh.error ? <RequestError error={refresh.error} /> : null}
      {refresh.data?.status === "current" ? (
        <article aria-labelledby="refresh-answer-title">
          <h2 id="refresh-answer-title">{refresh.data.answer.title}</h2>
          <MarkdownContent markdown={refresh.data.answer.markdown} />
        </article>
      ) : null}
    </section>
  );
}
