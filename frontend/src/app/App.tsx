// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { useEffect, useRef } from "react";
import { Link, Outlet, useLocation } from "react-router";

import { useWorkspace } from "../api/queries";
import { RequestError } from "../components/RequestError";

export function App() {
  const workspace = useWorkspace();
  const pendingReview = workspace.data?.pending_review;
  const location = useLocation();
  const mainRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const main = mainRef.current;
    if (main === null) return;

    function focusPageHeading(): boolean {
      const heading = main?.querySelector("h1");
      if (!(heading instanceof HTMLHeadingElement)) return false;
      heading.tabIndex = -1;
      heading.focus();
      document.title = `${heading.textContent ?? "BundleWalker"} · BundleWalker`;
      return true;
    }

    if (focusPageHeading()) return;
    const observer = new MutationObserver(() => {
      if (focusPageHeading()) observer.disconnect();
    });
    observer.observe(main, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [location.pathname]);

  return (
    <>
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <div className="app-shell">
        <aside aria-label="Workspace">
          <header className="workspace-header">
            <strong>BundleWalker</strong>
            {workspace.data ? <p>{workspace.data.display_name}</p> : null}
          </header>
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
        <main id="main-content" ref={mainRef}>
          {workspace.data ? (
            <Outlet />
          ) : (
            <p role="status">Loading workspace…</p>
          )}
        </main>
      </div>
    </>
  );
}
