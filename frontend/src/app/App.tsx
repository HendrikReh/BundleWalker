import { Link, Outlet } from "react-router";

import { useWorkspace } from "../api/queries";
import { RequestError } from "../components/RequestError";

export function App() {
  const workspace = useWorkspace();
  const pendingReview = workspace.data?.pending_review;

  return (
    <div className="app-shell">
      <aside aria-label="Workspace">
        <strong>BundleWalker</strong>
        {workspace.data ? <p>{workspace.data.display_name}</p> : null}
        {workspace.error ? <RequestError error={workspace.error} /> : null}
        <nav aria-label="Explorer">
          <Link to="/browse">Browse</Link>
          <Link to="/ask">Ask</Link>
          <Link to="/lint">Lint</Link>
          <Link
            to={
              pendingReview
                ? `/review/${pendingReview.review_id}`
                : "/review/unavailable"
            }
          >
            Review{pendingReview ? " (1)" : ""}
          </Link>
          <Link to="/ingest">New ingestion</Link>
        </nav>
      </aside>
      <main>
        {workspace.data ? <Outlet /> : <p role="status">Loading workspace…</p>}
      </main>
    </div>
  );
}
