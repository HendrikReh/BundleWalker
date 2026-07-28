// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
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

const pendingReview = {
  ...workspaceWithReview.pending_review,
  diff:
    "--- /dev/null\n" +
    "+++ wiki/sources/prepared-notes.md\n" +
    "@@ -0,0 +1 @@\n" +
    "+Prepared notes.\n",
  changed_paths: ["sources/prepared-notes.md"],
  created_at: "2026-07-25T12:00:00Z",
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
  vi.mocked(fetch).mockImplementation((input) => {
    const path = String(input);
    if (path === "/api/v1/workspace") {
      return Promise.resolve(jsonResponse(workspaceWithReview));
    }
    if (path === "/api/v1/review") {
      return Promise.resolve(jsonResponse(pendingReview));
    }
    throw new Error(`Unexpected request: ${path}`);
  });

  renderRoutes("/");

  await screen.findByRole("heading", { name: "Review proposal" });
  expect(screen.getByText("Prepared notes")).toBeTruthy();
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

test("submits the selected concept type only with an explicit lexical search", async () => {
  vi.mocked(fetch)
    .mockResolvedValueOnce(
      jsonResponse({
        ...workspaceWithoutReview,
        concept_counts: { Topic: 1, Entity: 2, Synthesis: 1 },
      }),
    )
    .mockResolvedValueOnce(jsonResponse({ items: [], next_cursor: null }))
    .mockResolvedValueOnce(jsonResponse({ items: [tools] }))
    .mockResolvedValueOnce(jsonResponse({ items: [agents] }));
  const user = userEvent.setup();
  renderRoutes();

  const type = await screen.findByRole("combobox", {
    name: "Concept type (search only)",
  });
  expect(
    [...type.querySelectorAll("option")].map((option) => option.textContent),
  ).toEqual(["All types", "Entity (2)", "Synthesis (1)", "Topic (1)"]);

  await user.selectOptions(type, "Entity");
  await user.type(
    screen.getByRole("searchbox", { name: "Search concepts" }),
    "tools",
  );
  expect(
    vi
      .mocked(fetch)
      .mock.calls.filter(([url]) => String(url).includes("/concepts/search")),
  ).toHaveLength(0);

  await user.click(screen.getByRole("button", { name: "Search" }));
  await screen.findByRole("link", { name: "Tools" });
  await user.selectOptions(type, "Topic");
  expect(
    vi
      .mocked(fetch)
      .mock.calls.filter(([url]) => String(url).includes("/concepts/search")),
  ).toHaveLength(1);

  await user.click(screen.getByRole("button", { name: "Search" }));
  await screen.findByRole("link", { name: "Agents" });
  const searchCalls = vi
    .mocked(fetch)
    .mock.calls.filter(([url]) => String(url).includes("/concepts/search"));
  expect(searchCalls.map(([url]) => String(url))).toEqual([
    "/api/v1/concepts/search?query=tools&type=Entity",
    "/api/v1/concepts/search?query=tools&type=Topic",
  ]);
});

test("announces the initial concept page while it is loading", async () => {
  let resolveConcepts!: (response: Response) => void;
  const pendingConcepts = new Promise<Response>((resolve) => {
    resolveConcepts = resolve;
  });
  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse(workspaceWithoutReview))
    .mockReturnValueOnce(pendingConcepts);

  renderRoutes();

  await screen.findByRole("heading", { name: "Browse concepts" });
  expect(screen.getByRole("status").textContent).toContain("Loading concepts");

  resolveConcepts(jsonResponse({ items: [agents], next_cursor: null }));
  await screen.findByRole("link", { name: "Agents" });
});

test("announces a submitted concept search while it is loading", async () => {
  let resolveSearch!: (response: Response) => void;
  const pendingSearch = new Promise<Response>((resolve) => {
    resolveSearch = resolve;
  });
  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse(workspaceWithoutReview))
    .mockResolvedValueOnce(jsonResponse({ items: [agents], next_cursor: null }))
    .mockReturnValueOnce(pendingSearch);
  const user = userEvent.setup();
  renderRoutes();

  await user.type(
    await screen.findByRole("searchbox", { name: "Search concepts" }),
    "missing",
  );
  await user.click(screen.getByRole("button", { name: "Search" }));

  expect(screen.getByRole("status").textContent).toContain(
    "Searching concepts",
  );
  expect(screen.queryByRole("link", { name: "Agents" })).toBeNull();

  resolveSearch(jsonResponse({ items: [] }));
  await screen.findByText("No concepts match your search.");
});

test("distinguishes an empty workspace page from a search with no matches", async () => {
  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse(workspaceWithoutReview))
    .mockResolvedValueOnce(jsonResponse({ items: [], next_cursor: null }))
    .mockResolvedValueOnce(jsonResponse({ items: [] }));
  const user = userEvent.setup();
  renderRoutes();

  await screen.findByText("This workspace has no concepts yet.");
  expect(screen.queryByText("No concepts match your search.")).toBeNull();

  await user.type(
    screen.getByRole("searchbox", { name: "Search concepts" }),
    "agents",
  );
  await user.click(screen.getByRole("button", { name: "Search" }));

  await screen.findByText("No concepts match your search.");
  expect(screen.queryByText("This workspace has no concepts yet.")).toBeNull();
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

  test("marks protocol-relative links as external instead of local", () => {
    render(<MarkdownContent markdown="[Outside](//evil.example/docs)" />);

    const link = screen.getByRole("link", { name: "Outside (external)" });
    expect(link.getAttribute("href")).toBe("//evil.example/docs");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
  });

  test.each([
    ["/topics/agent%20systems.md", "/browse/topics/agent%20systems"],
    ["entities/index.md#tools", "/browse/entities/index#tools"],
  ])(
    "opens OKF concept reference %s through the client concept route",
    async (reference, expectedRoute) => {
      const user = userEvent.setup();
      render(
        <MemoryRouter initialEntries={["/browse"]}>
          <MarkdownContent markdown={`[Concept](${reference})`} />
          <Routes>
            <Route path="*" element={<LocationProbe />} />
          </Routes>
        </MemoryRouter>,
      );

      const link = screen.getByRole("link", { name: "Concept" });
      expect(link.getAttribute("href")).toBe(expectedRoute);
      await user.click(link);
      expect(screen.getByTestId("current-location").textContent).toBe(
        expectedRoute,
      );
    },
  );

  test("rejects traversal-shaped concept references", () => {
    render(
      <MarkdownContent
        markdown={
          "[parent](../topics/agents.md) [encoded](/topics/%2e%2e/agents.md)"
        }
      />,
    );

    expect(screen.queryByRole("link", { name: "parent" })).toBeNull();
    expect(screen.queryByRole("link", { name: "encoded" })).toBeNull();
  });

  test("preserves safe non-concept local links and their text", () => {
    render(
      <MarkdownContent markdown="[Guide](guide.pdf) [Docs](/documentation)" />,
    );

    expect(
      screen.getByRole("link", { name: "Guide" }).getAttribute("href"),
    ).toBe("guide.pdf");
    expect(
      screen.getByRole("link", { name: "Docs" }).getAttribute("href"),
    ).toBe("/documentation");
  });
});

function LocationProbe() {
  const location = useLocation();
  return (
    <output data-testid="current-location">
      {location.pathname}
      {location.search}
      {location.hash}
    </output>
  );
}

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
