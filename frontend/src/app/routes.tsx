// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { Navigate, Route, Routes } from "react-router";

import { RequestError } from "../components/RequestError";
import { AskPage } from "../features/ask/AskPage";
import { BrowsePage } from "../features/browse/BrowsePage";
import { ConceptPage } from "../features/browse/ConceptPage";
import { LintPage } from "../features/lint/LintPage";
import { IngestionPage } from "../features/ingestion/IngestionPage";
import { ReviewPage } from "../features/review/ReviewPage";
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
        <Route path="ingest" element={<IngestionPage />} />
        <Route path="review/:reviewId" element={<ReviewPage />} />
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
