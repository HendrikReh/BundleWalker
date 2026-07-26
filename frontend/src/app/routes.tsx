// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { Navigate, Route, Routes, useParams } from "react-router";

import { RequestError } from "../components/RequestError";
import { AskPage } from "../features/ask/AskPage";
import { BrowsePage } from "../features/browse/BrowsePage";
import { ConceptPage } from "../features/browse/ConceptPage";
import { LintPage } from "../features/lint/LintPage";
import { useWorkspace } from "../api/queries";
import { App } from "./App";

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<App />}>
        <Route index element={<DefaultRoute />} />
        <Route path="browse" element={<BrowsePage />} />
        <Route path="browse/*" element={<ConceptPage />} />
        <Route path="ask" element={<AskPage />} />
        <Route path="lint" element={<LintPage />} />
        <Route path="ingest" element={<Placeholder title="New ingestion" />} />
        <Route path="review/:reviewId" element={<ReviewPlaceholder />} />
      </Route>
    </Routes>
  );
}

function DefaultRoute() {
  const workspace = useWorkspace();
  if (workspace.error) return <RequestError error={workspace.error} />;
  if (workspace.data === undefined)
    return <p role="status">Loading workspace…</p>;
  return (
    <Navigate
      replace
      to={
        workspace.data.pending_review
          ? `/review/${workspace.data.pending_review.review_id}`
          : "/browse"
      }
    />
  );
}

function ReviewPlaceholder() {
  const workspace = useWorkspace();
  const reviewId = useParams().reviewId;
  const pending = workspace.data?.pending_review;
  const title =
    pending !== null && pending !== undefined && pending.review_id === reviewId
      ? pending.summary
      : "No pending review";
  return <Placeholder title={title} />;
}

function Placeholder({ title }: { readonly title: string }) {
  return (
    <section>
      <h1>{title}</h1>
      <p>This workbench will be available in the next capability slice.</p>
    </section>
  );
}
