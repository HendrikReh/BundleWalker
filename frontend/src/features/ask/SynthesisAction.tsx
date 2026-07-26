// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";

import { queryKeys, usePrepareSynthesis } from "../../api/queries";
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

  function prepare() {
    if (synthesis.isPending || !question.trim()) return;
    synthesis.mutate(
      {
        question,
        model: model.trim() || null,
      },
      {
        onSuccess: async () => {
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
        },
      },
    );
  }

  const status = synthesis.isPending
    ? "Preparing synthesis proposal…"
    : synthesis.isError
      ? "Synthesis preparation failed"
      : synthesis.data
        ? "Synthesis proposal ready"
        : "";

  return (
    <>
      <button
        type="button"
        disabled={synthesis.isPending || !question.trim()}
        onClick={prepare}
      >
        Prepare synthesis
      </button>
      {status ? <OperationProgress message={status} /> : null}
      {synthesis.error ? <RequestError error={synthesis.error} /> : null}
      {synthesis.data ? (
        <article aria-labelledby="synthesis-answer-title">
          <h2 id="synthesis-answer-title">{synthesis.data.answer.title}</h2>
          <MarkdownContent markdown={synthesis.data.answer.markdown} />
          <p>
            <Link to={`/review/${synthesis.data.review.review_id}`}>
              Review the synthesis proposal
            </Link>
          </p>
        </article>
      ) : null}
    </>
  );
}
