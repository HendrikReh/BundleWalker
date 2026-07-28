// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { apiClient, queryKeys, usePrepareSynthesis } from "../../api/queries";
import type { WebSynthesisResponse } from "../../api/types";
import { MarkdownContent } from "../../components/MarkdownContent";
import { OperationProgress } from "../../components/OperationProgress";
import { RequestError } from "../../components/RequestError";

interface SynthesisActionProps {
  readonly question: string;
  readonly model: string;
}

export function SynthesisAction({ question, model }: SynthesisActionProps) {
  const queryClient = useQueryClient();
  const synthesis = usePrepareSynthesis();
  const [prepared, setPrepared] = useState<WebSynthesisResponse | null>(null);
  const [reconciliation, setReconciliation] = useState<
    "idle" | "loading" | "complete" | "failed"
  >("idle");

  async function reconcileWorkspace(result: WebSynthesisResponse) {
    try {
      await Promise.all([
        queryClient.invalidateQueries(
          { queryKey: queryKeys.workspace, refetchType: "none" },
          { throwOnError: true },
        ),
        queryClient.invalidateQueries(
          { queryKey: queryKeys.review, refetchType: "none" },
          { throwOnError: true },
        ),
      ]);
      const [freshWorkspace, freshReview] = await Promise.all([
        queryClient.fetchQuery({
          queryKey: queryKeys.workspace,
          queryFn: () => apiClient.workspace(),
          staleTime: 0,
        }),
        queryClient.fetchQuery({
          queryKey: queryKeys.review,
          queryFn: () => apiClient.review(),
          staleTime: 0,
        }),
      ]);
      if (
        freshWorkspace.pending_review?.review_id !== result.review.review_id ||
        freshReview?.review_id !== result.review.review_id
      ) {
        setReconciliation("failed");
        return;
      }
      setReconciliation("complete");
    } catch {
      setReconciliation("failed");
    }
  }

  function prepare() {
    if (synthesis.isPending || prepared !== null || !question.trim()) return;
    synthesis.mutate(
      {
        question,
        model: model.trim() || null,
      },
      {
        onSuccess: (result) => {
          setPrepared(result);
          setReconciliation("loading");
          void reconcileWorkspace(result);
        },
      },
    );
  }

  const status = synthesis.isPending
    ? "Preparing synthesis proposal…"
    : synthesis.isError
      ? "Synthesis preparation failed"
      : reconciliation === "loading"
        ? "Synthesis proposal ready; refreshing workspace status…"
        : prepared
          ? "Synthesis proposal ready"
          : "";

  const reconciliationWarning =
    reconciliation === "failed"
      ? "Synthesis preparation succeeded, but workspace and review status could not be confirmed. The successful answer is preserved, but the proposal link is unavailable until status can be confirmed."
      : "";

  return (
    <>
      <button
        type="button"
        disabled={synthesis.isPending || prepared !== null || !question.trim()}
        onClick={prepare}
      >
        Prepare synthesis
      </button>
      {reconciliationWarning ? (
        <p
          aria-label="Synthesis reconciliation warning"
          aria-live="polite"
          role="status"
        >
          {reconciliationWarning}
        </p>
      ) : status ? (
        <OperationProgress message={status} />
      ) : null}
      {synthesis.error ? <RequestError error={synthesis.error} /> : null}
      {prepared ? (
        <article aria-labelledby="synthesis-answer-title">
          <h2 id="synthesis-answer-title">{prepared.answer.title}</h2>
          <MarkdownContent markdown={prepared.answer.markdown} />
          {reconciliation === "complete" ? (
            <p>
              <Link to={`/review/${prepared.review.review_id}`}>
                Review the synthesis proposal
              </Link>
            </p>
          ) : null}
        </article>
      ) : null}
    </>
  );
}
