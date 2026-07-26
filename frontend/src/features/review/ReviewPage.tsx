// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router";

import { ApiError } from "../../api/client";
import {
  queryKeys,
  useApplyReview,
  useDiscardReview,
  useReview,
} from "../../api/queries";
import type { WebReviewResponse } from "../../api/types";
import { RequestError } from "../../components/RequestError";
import { ReviewDiff } from "../../components/ReviewDiff";

type Resolution = "apply" | "discard";

const REVIEW_CONFLICTS = new Set([
  "review_id_mismatch",
  "review_not_found",
  "review_stale",
]);

export function ReviewPage() {
  const routeReviewId = useParams().reviewId;
  const reviewQuery = useReview();
  const apply = useApplyReview();
  const discard = useDiscardReview();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [reconciling, setReconciling] = useState(false);
  const [announcement, setAnnouncement] = useState<string | null>(null);
  const review = reviewQuery.data;

  useEffect(() => {
    if (
      review !== undefined &&
      review !== null &&
      routeReviewId !== review.review_id &&
      !reconciling
    ) {
      navigate(`/review/${review.review_id}`, { replace: true });
    }
  }, [navigate, reconciling, review, routeReviewId]);

  async function resolve(resolution: Resolution) {
    if (review === undefined || review === null || reconciling) return;
    const confirmed = window.confirm(
      `${resolution === "apply" ? "Apply" : "Discard"} the entire proposal?`,
    );
    if (!confirmed) return;

    const mutation = resolution === "apply" ? apply : discard;
    try {
      await mutation.mutateAsync(review.review_id);
      setReconciling(true);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.workspace }),
        queryClient.invalidateQueries({ queryKey: queryKeys.review }),
        queryClient.invalidateQueries({ queryKey: queryKeys.concepts }),
        queryClient.invalidateQueries({ queryKey: queryKeys.lint }),
      ]);
      navigate("/browse");
    } catch (error) {
      if (!(error instanceof ApiError) || !REVIEW_CONFLICTS.has(error.code)) {
        return;
      }
      setReconciling(true);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.workspace }),
        queryClient.invalidateQueries({ queryKey: queryKeys.review }),
      ]);
      const current = queryClient.getQueryData<WebReviewResponse | null>(
        queryKeys.review,
      );
      mutation.reset();
      if (current === undefined || current === null) {
        setAnnouncement("The proposal is no longer pending.");
      } else {
        setAnnouncement(`Current proposal: ${current.summary}`);
        navigate(`/review/${current.review_id}`, { replace: true });
      }
    } finally {
      setReconciling(false);
    }
  }

  if (reviewQuery.error) return <RequestError error={reviewQuery.error} />;
  if (review === undefined) return <p role="status">Loading review…</p>;
  if (review === null) {
    return (
      <section>
        <h1>No pending review</h1>
        <p>The workspace does not currently have a proposal to resolve.</p>
      </section>
    );
  }

  const busy = apply.isPending || discard.isPending || reconciling;
  const mutationError = apply.error ?? discard.error;

  return (
    <section className="review-workbench">
      <h1>Review proposal</h1>
      {announcement ? (
        <p role="status" aria-label="Review state changed">
          {announcement}
        </p>
      ) : null}
      <p>{review.summary}</p>
      <dl className="review-metadata">
        <div>
          <dt>Kind</dt>
          <dd>{review.kind}</dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>{review.status}</dd>
        </div>
        <div>
          <dt>Review ID</dt>
          <dd>
            <code>{review.review_id}</code>
          </dd>
        </div>
        <div>
          <dt>Created</dt>
          <dd>{review.created_at}</dd>
        </div>
      </dl>
      <section aria-labelledby="changed-paths-heading">
        <h2 id="changed-paths-heading">Changed paths</h2>
        <ul>
          {review.changed_paths.map((path) => (
            <li key={path}>
              <code>{path}</code>
            </li>
          ))}
        </ul>
      </section>
      <ReviewDiff diff={review.diff} />
      <div className="review-actions" aria-label="Resolve whole proposal">
        <button
          type="button"
          disabled={busy}
          onClick={() => void resolve("apply")}
        >
          Apply proposal
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => void resolve("discard")}
        >
          Discard proposal
        </button>
      </div>
      {busy ? (
        <p role="status">Reconciling authoritative workspace state…</p>
      ) : null}
      {mutationError ? <RequestError error={mutationError} /> : null}
    </section>
  );
}
