// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { AppRoutes } from "../../app/routes";
import { MarkdownContent } from "../../components/MarkdownContent";

const workspaceWithoutReview = {
  display_name: "knowledge",
  config_version: 1,
  concept_counts: { Topic: 1 },
  pending_review: null,
  csrf_token: "csrf-token",
};

const workspaceWithReview = {
  ...workspaceWithoutReview,
  pending_review: {
    review_id: "0123456789abcdef0123456789abcdef",
    kind: "ingestion",
    status: "pending",
    summary: "Prepared notes",
  },
};

const agents = {
  concept_id: "topics/agents",
  type: "Topic",
  title: "Agents",
  description: "Knowledge about agents.",
  tags: ["agents"],
};

const tools = {
  concept_id: "entities/tools",
  type: "Entity",
  title: "Tools",
  description: "Tools support agent workflows.",
  tags: ["tools"],
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderRoutes(initialEntry = "/browse") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
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
});

test("opens Review first when workspace status contains a pending review", async () => {
  vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(workspaceWithReview));

  renderRoutes("/");

  await screen.findByRole("heading", { name: "Prepared notes" });
});

test("opens Browse first when workspace has no pending review", async () => {
  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse(workspaceWithoutReview))
    .mockResolvedValueOnce(
      jsonResponse({ items: [agents], next_cursor: null }),
    );

  renderRoutes("/");

  await screen.findByRole("heading", { name: "Browse concepts" });
});

test("Explorer exposes the first-release capabilities", async () => {
  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse(workspaceWithoutReview))
    .mockResolvedValueOnce(jsonResponse({ items: [], next_cursor: null }));

  renderRoutes();

  const explorer = await screen.findByRole("complementary", {
    name: "Workspace",
  });
  for (const label of ["Browse", "Ask", "Lint", "Review", "New ingestion"]) {
    expect(explorer.textContent).toContain(label);
  }
});

test("submits a lexical search exactly once", async () => {
  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse(workspaceWithoutReview))
    .mockResolvedValueOnce(jsonResponse({ items: [], next_cursor: null }))
    .mockResolvedValueOnce(jsonResponse({ items: [agents] }));
  const user = userEvent.setup();
  renderRoutes();

  await user.type(
    await screen.findByRole("searchbox", { name: "Search concepts" }),
    "agents",
  );
  await user.click(screen.getByRole("button", { name: "Search" }));

  await screen.findByRole("link", { name: "Agents" });
  const searchCalls = vi
    .mocked(fetch)
    .mock.calls.filter(([url]) => String(url).includes("/concepts/search"));
  expect(searchCalls).toHaveLength(1);
  expect(String(searchCalls[0]?.[0])).toContain("query=agents");
});

test("appends later concept pages without duplicate entries", async () => {
  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse(workspaceWithoutReview))
    .mockResolvedValueOnce(
      jsonResponse({ items: [agents], next_cursor: "opaque-cursor" }),
    )
    .mockResolvedValueOnce(
      jsonResponse({ items: [agents, tools], next_cursor: null }),
    );
  const user = userEvent.setup();
  renderRoutes();

  await screen.findByRole("link", { name: "Agents" });
  await user.click(screen.getByRole("button", { name: "Load more" }));

  await screen.findByRole("link", { name: "Tools" });
  expect(screen.getAllByRole("link", { name: "Agents" })).toHaveLength(1);
});

test("opens a hierarchical concept through the browse splat route", async () => {
  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse(workspaceWithoutReview))
    .mockResolvedValueOnce(
      jsonResponse({
        ...agents,
        markdown: "# Agents\n\nAgents can use tools.",
        digest: "a".repeat(64),
      }),
    );

  renderRoutes("/browse/topics/agents");

  await screen.findByRole("heading", { name: "Agents", level: 1 });
  expect(vi.mocked(fetch).mock.calls[1]?.[0]).toBe(
    "/api/v1/concepts/topics/agents",
  );
});

describe("MarkdownContent", () => {
  test("does not execute raw HTML or executable links", () => {
    render(
      <MarkdownContent
        markdown={
          "Before <script>alert('bad')</script> after\n\n[unsafe](javascript:alert('bad'))"
        }
      />,
    );

    expect(document.querySelector("script")).toBeNull();
    expect(document.body.textContent).toContain(
      "<script>alert('bad')</script>",
    );
    expect(screen.queryByRole("link", { name: "unsafe" })).toBeNull();
  });

  test("marks external links with safe browser relationship attributes", () => {
    render(
      <MarkdownContent markdown="[BundleWalker](https://example.com/docs)" />,
    );

    const link = screen.getByRole("link", { name: "BundleWalker (external)" });
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
  });
});

test("renders a bounded request error instead of raw response text", async () => {
  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse(workspaceWithoutReview))
    .mockResolvedValueOnce(
      new Response("<html>private traceback /private/workspace</html>", {
        status: 500,
      }),
    );

  renderRoutes();

  await waitFor(() => {
    expect(screen.getByRole("alert").textContent).toContain("Request failed");
  });
  expect(document.body.textContent).not.toContain("private traceback");
  expect(document.body.textContent).not.toContain("/private/workspace");
});
