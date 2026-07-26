// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { AppRoutes } from "../../app/routes";

const reviewId = "b".repeat(32);
const workspace = {
  display_name: "knowledge",
  config_version: 1,
  concept_counts: { Synthesis: 1, Topic: 1 },
  pending_review: null,
  csrf_token: "csrf-token",
};
const synthesisConcept = {
  concept_id: "syntheses/agent-framework",
  type: "Synthesis",
  title: "Agent framework",
  description: "A maintained agent framework.",
  tags: ["agents"],
  markdown: "# Agent framework\n\nAgents use tools.",
  digest: "a".repeat(64),
};
const answer = {
  title: "Updated agent framework",
  markdown:
    "# Updated framework\n\nAgents use current tools [1].\n\n# Citations\n\n[1] [Agents](/topics/agents.md)\n",
  citations: [{ number: 1, concept_id: "topics/agents" }],
};
const pendingReview = {
  review_id: reviewId,
  kind: "refresh",
  status: "pending",
  summary: "Refreshed synthesis: Updated agent framework",
  diff:
    "--- wiki/syntheses/agent-framework.md\n" +
    "+++ wiki/syntheses/agent-framework.md\n" +
    "@@ -1 +1 @@\n-old\n+new\n",
  changed_paths: ["syntheses/agent-framework.md"],
  created_at: "2026-07-25T12:00:00Z",
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function LocationProbe() {
  return <output data-testid="location">{useLocation().pathname}</output>;
}

function renderRoute(initialEntry: string) {
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
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockReturnValue({
      matches: false,
      media: "(max-width: 48rem)",
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("offers refresh only for eligible generated synthesis concepts", async () => {
  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse(workspace))
    .mockResolvedValueOnce(jsonResponse(synthesisConcept));
  renderRoute("/browse/syntheses/agent-framework");

  const refreshLink = await screen.findByRole("link", {
    name: "Prepare refresh",
  });
  expect(refreshLink.getAttribute("href")).toBe(
    "/refresh/syntheses/agent-framework",
  );
});

test("does not offer refresh for a non-synthesis concept", async () => {
  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse(workspace))
    .mockResolvedValueOnce(
      jsonResponse({
        ...synthesisConcept,
        concept_id: "topics/agent-framework",
        type: "Topic",
      }),
    );
  renderRoute("/browse/topics/agent-framework");

  await screen.findByRole("heading", { name: "Agent framework", level: 1 });
  expect(screen.queryByRole("link", { name: "Prepare refresh" })).toBeNull();
});

test("announces an already-current refresh without creating a review", async () => {
  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse(workspace))
    .mockResolvedValueOnce(jsonResponse(synthesisConcept))
    .mockResolvedValueOnce(
      jsonResponse({
        status: "current",
        concept_id: synthesisConcept.concept_id,
        answer,
        review: null,
      }),
    );
  const user = userEvent.setup();
  renderRoute("/refresh/syntheses/agent-framework");

  const instruction = await screen.findByRole("textbox", {
    name: "Refresh instruction",
  });
  await user.type(instruction, "Add current evidence");
  await user.click(screen.getByRole("button", { name: "Prepare refresh" }));

  expect(
    await screen.findByRole("heading", {
      name: "Updated agent framework",
      level: 2,
    }),
  ).toBeTruthy();
  expect(
    screen.getByText("Synthesis is already current; no review was created"),
  ).toHaveProperty("role", "status");
  expect(screen.getByTestId("location").textContent).toBe(
    "/refresh/syntheses/agent-framework",
  );
});

test("navigates a pending refresh to the exact review after invalidation", async () => {
  let workspaceCalls = 0;
  vi.mocked(fetch).mockImplementation((input) => {
    const path = String(input);
    if (path === "/api/v1/workspace") {
      workspaceCalls += 1;
      return Promise.resolve(
        jsonResponse(
          workspaceCalls === 1
            ? workspace
            : {
                ...workspace,
                pending_review: {
                  review_id: reviewId,
                  kind: "refresh",
                  status: "pending",
                  summary: pendingReview.summary,
                },
              },
        ),
      );
    }
    if (path === "/api/v1/concepts/syntheses/agent-framework") {
      return Promise.resolve(jsonResponse(synthesisConcept));
    }
    if (path === "/api/v1/refreshes") {
      return Promise.resolve(
        jsonResponse({
          status: "pending",
          concept_id: synthesisConcept.concept_id,
          answer,
          review: pendingReview,
        }),
      );
    }
    if (path === "/api/v1/review") {
      return Promise.resolve(jsonResponse(pendingReview));
    }
    throw new Error(`Unexpected request: ${path}`);
  });
  const user = userEvent.setup();
  renderRoute("/refresh/syntheses/agent-framework");

  await user.type(
    await screen.findByRole("textbox", { name: "Refresh instruction" }),
    "Add current evidence",
  );
  await user.click(screen.getByRole("button", { name: "Prepare refresh" }));

  await waitFor(() => {
    expect(screen.getByTestId("location").textContent).toBe(
      `/review/${reviewId}`,
    );
  });
  expect(
    await screen.findByRole("heading", { name: "Review proposal" }),
  ).toBeTruthy();
  expect(workspaceCalls).toBe(2);
});

test("preserves refresh input and model after a bounded failure", async () => {
  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse(workspace))
    .mockResolvedValueOnce(jsonResponse(synthesisConcept))
    .mockResolvedValueOnce(
      jsonResponse(
        {
          error: {
            code: "configuration_error",
            message: "model configuration is unavailable",
            retryable: false,
            review_id: null,
            diagnostic_id: null,
          },
        },
        400,
      ),
    );
  const user = userEvent.setup();
  renderRoute("/refresh/syntheses/agent-framework");

  const instruction = await screen.findByRole("textbox", {
    name: "Refresh instruction",
  });
  const model = screen.getByRole("textbox", { name: "Model (optional)" });
  await user.type(instruction, "Add current evidence");
  await user.type(model, "missing:model");
  await user.click(screen.getByRole("button", { name: "Prepare refresh" }));

  await screen.findByText("model configuration is unavailable");
  expect((instruction as HTMLTextAreaElement).value).toBe(
    "Add current evidence",
  );
  expect((model as HTMLInputElement).value).toBe("missing:model");
  expect(screen.getByText("Refresh preparation failed")).toHaveProperty(
    "role",
    "status",
  );
});

test("retains a pending refresh when workspace reconciliation fails", async () => {
  let workspaceCalls = 0;
  vi.mocked(fetch).mockImplementation((input) => {
    const path = String(input);
    if (path === "/api/v1/workspace") {
      workspaceCalls += 1;
      return workspaceCalls === 1
        ? Promise.resolve(jsonResponse(workspace))
        : Promise.reject(new Error("workspace reload failed"));
    }
    if (path === "/api/v1/concepts/syntheses/agent-framework") {
      return Promise.resolve(jsonResponse(synthesisConcept));
    }
    if (path === "/api/v1/refreshes") {
      return Promise.resolve(
        jsonResponse({
          status: "pending",
          concept_id: synthesisConcept.concept_id,
          answer,
          review: pendingReview,
        }),
      );
    }
    throw new Error(`Unexpected request: ${path}`);
  });
  const user = userEvent.setup();
  renderRoute("/refresh/syntheses/agent-framework");

  await user.type(
    await screen.findByRole("textbox", { name: "Refresh instruction" }),
    "Add current evidence",
  );
  await user.click(screen.getByRole("button", { name: "Prepare refresh" }));

  expect(
    await screen.findByRole("heading", {
      name: "Updated agent framework",
      level: 2,
    }),
  ).toBeTruthy();
  expect(
    screen
      .getByRole("link", { name: "Review the refresh proposal" })
      .getAttribute("href"),
  ).toBe(`/review/${reviewId}`);
  expect(
    (
      await screen.findByRole("status", {
        name: "Refresh reconciliation warning",
      })
    ).textContent,
  ).toContain(
    "Refresh preparation succeeded, but workspace status could not refresh",
  );
  expect(screen.queryByText("Refresh preparation failed")).toBeNull();
  expect(screen.getByTestId("location").textContent).toBe(
    "/refresh/syntheses/agent-framework",
  );
  expect(
    vi.mocked(fetch).mock.calls.filter(([url]) => url === "/api/v1/refreshes"),
  ).toHaveLength(1);
  expect(
    screen.getByRole("button", { name: "Prepare refresh" }),
  ).toHaveProperty("disabled", true);
});
