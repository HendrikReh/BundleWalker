// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { queryKeys, useConcept, usePrepareRefresh } from "../../api/queries";
import type { WebRefreshResponse } from "../../api/types";
import { MarkdownContent } from "../../components/MarkdownContent";
import { OperationProgress } from "../../components/OperationProgress";
import { PageRequestError, RequestError } from "../../components/RequestError";
import { isRefreshEligibleConcept } from "./refresh";

const MAX_INSTRUCTION_CHARACTERS = 20_000;
const MAX_MODEL_CHARACTERS = 255;

export function RefreshPage() {
  const conceptId = useParams()["*"] ?? "";
  const [instruction, setInstruction] = useState("");
  const [model, setModel] = useState("");
  const [prepared, setPrepared] = useState<WebRefreshResponse | null>(null);
  const [reconciliation, setReconciliation] = useState<
    "idle" | "loading" | "failed"
  >("idle");
  const concept = useConcept(conceptId);
  const refresh = usePrepareRefresh(conceptId);
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  async function reconcilePendingReview(reviewId: string) {
    try {
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
      navigate(`/review/${encodeURIComponent(reviewId)}`);
    } catch {
      setReconciliation("failed");
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (
      refresh.isPending ||
      prepared !== null ||
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
        onSuccess: (result) => {
          setPrepared(result);
          if (result.status === "current") return;
          setReconciliation("loading");
          void reconcilePendingReview(result.review.review_id);
        },
      },
    );
  }

  if (concept.error)
    return (
      <PageRequestError title="Refresh unavailable" error={concept.error} />
    );
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
      : prepared?.status === "current"
        ? "Synthesis is already current; no review was created"
        : prepared?.status === "pending"
          ? reconciliation === "loading"
            ? "Refresh proposal ready; refreshing workspace status…"
            : "Refresh proposal ready"
          : "";

  const reconciliationWarning =
    reconciliation === "failed"
      ? "Refresh preparation succeeded, but workspace status could not refresh. The proposal remains ready for review."
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
        <button type="submit" disabled={refresh.isPending || prepared !== null}>
          Prepare refresh
        </button>
      </form>
      {reconciliationWarning ? (
        <p
          aria-label="Refresh reconciliation warning"
          aria-live="polite"
          role="status"
        >
          {reconciliationWarning}
        </p>
      ) : status ? (
        <OperationProgress message={status} />
      ) : null}
      {refresh.error ? <RequestError error={refresh.error} /> : null}
      {prepared ? (
        <article aria-labelledby="refresh-answer-title">
          <h2 id="refresh-answer-title">{prepared.answer.title}</h2>
          <MarkdownContent markdown={prepared.answer.markdown} />
          {prepared.status === "pending" ? (
            <p>
              <Link to={`/review/${prepared.review.review_id}`}>
                Review the refresh proposal
              </Link>
            </p>
          ) : null}
        </article>
      ) : null}
    </section>
  );
}
