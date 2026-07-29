// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { AppRoutes } from "../app/routes";

const workspace = {
  display_name: "knowledge",
  config_version: 1,
  concept_counts: { Topic: 1 },
  pending_review: null,
  csrf_token: "csrf-token",
};

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function renderRoutes(initialEntry = "/browse") {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.title = "";
});

test("offers a skip link and focuses the single page heading after navigation", async () => {
  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse(workspace))
    .mockResolvedValueOnce(jsonResponse({ items: [], next_cursor: null }));
  const user = userEvent.setup();
  renderRoutes();

  const browseHeading = await screen.findByRole("heading", {
    name: "Browse concepts",
    level: 1,
  });
  expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  const skipLink = screen.getByRole("link", { name: "Skip to main content" });
  expect(skipLink.getAttribute("href")).toBe("#main-content");
  const main = screen.getByRole("main");
  expect(main.id).toBe("main-content");
  await waitFor(() => expect(document.activeElement).toBe(browseHeading));

  await user.click(skipLink);
  expect(document.activeElement).toBe(main);

  await user.click(screen.getByRole("link", { name: "Ask" }));
  const askHeading = await screen.findByRole("heading", {
    name: "Ask",
    level: 1,
  });
  expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  await waitFor(() => {
    expect(document.activeElement).toBe(askHeading);
    expect(document.title).toBe("Ask · BundleWalker");
  });
});

test("focuses and titles a route-level concept error", async () => {
  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse(workspace))
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          error: {
            code: "concept_not_found",
            message: "concept does not exist",
            retryable: false,
            review_id: null,
            diagnostic_id: null,
          },
        }),
        { status: 404, headers: { "Content-Type": "application/json" } },
      ),
    );
  renderRoutes("/browse/topics/missing");

  const heading = await screen.findByRole("heading", {
    name: "Concept unavailable",
    level: 1,
  });
  expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  await waitFor(() => {
    expect(document.activeElement).toBe(heading);
    expect(document.title).toBe("Concept unavailable · BundleWalker");
  });
  expect(screen.getByRole("alert").textContent).toContain(
    "concept does not exist",
  );
});

test("moves focus to an announced validation error", async () => {
  vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(workspace));
  const user = userEvent.setup();
  renderRoutes("/ingest");

  const sourceName = await screen.findByRole("textbox", {
    name: "Source filename",
  });
  await user.clear(sourceName);
  await user.type(sourceName, "../notes.md");
  await user.type(
    screen.getByRole("textbox", { name: "Content" }),
    "Evidence.",
  );
  await user.click(screen.getByRole("button", { name: "Prepare ingestion" }));

  const error = await screen.findByRole("alert");
  expect(error.textContent).toContain("safe source filename");
  expect(document.activeElement).toBe(error);
});

test("announces completed operations and exposes non-color lint state", async () => {
  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse(workspace))
    .mockResolvedValueOnce(
      jsonResponse({
        findings: [
          {
            origin: "deterministic",
            severity: "warning",
            code: "missing-description",
            message: "Description is missing.",
            path: "topics/agents.md",
            evidence_paths: ["topics/agents.md"],
            remediation: "Add a description.",
          },
        ],
        deterministic_has_errors: false,
      }),
    );
  const user = userEvent.setup();
  renderRoutes("/lint");

  await user.click(
    await screen.findByRole("button", {
      name: "Run lint",
    }),
  );

  expect((await screen.findByRole("status")).textContent).toContain(
    "Lint complete",
  );
  expect(screen.getByText("Severity: warning")).toBeTruthy();
  expect(screen.getByText("Suggested action: Add a description.")).toBeTruthy();
});

test("has no serious or critical automated accessibility violations", async () => {
  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse(workspace))
    .mockResolvedValueOnce(jsonResponse({ items: [], next_cursor: null }));
  const { container } = renderRoutes();
  await screen.findByRole("heading", { name: "Browse concepts" });

  const results = await axe.run(container, {
    resultTypes: ["violations"],
    rules: {
      "color-contrast": { enabled: false },
    },
  });
  const blocking = results.violations.filter(
    (violation) =>
      violation.impact === "serious" || violation.impact === "critical",
  );
  expect(blocking).toEqual([]);
});
