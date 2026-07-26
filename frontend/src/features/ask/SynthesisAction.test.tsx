// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { AppRoutes } from "../../app/routes";

const reviewId = "a".repeat(32);
const workspace = {
  display_name: "knowledge",
  config_version: 1,
  concept_counts: { Topic: 1 },
  pending_review: null,
  csrf_token: "csrf-token",
};
const synthesis = {
  answer: {
    title: "Agent tools synthesis",
    markdown:
      "# Synthesis\n\nAgents can use tools [1].\n\n# Citations\n\n[1] [Agents](/topics/agents.md)\n",
    citations: [{ number: 1, concept_id: "topics/agents" }],
  },
  review: {
    review_id: reviewId,
    kind: "synthesis",
    status: "pending",
    summary: "Saved synthesis: Agent tools synthesis",
    diff: "--- /dev/null\n+++ wiki/syntheses/agent-tools-synthesis.md\n",
    changed_paths: ["syntheses/agent-tools-synthesis.md"],
    created_at: "2026-07-25T12:00:00Z",
  },
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderAsk() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/ask"]}>
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

test("keeps Ask and Prepare synthesis distinct and submits through its own endpoint", async () => {
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
                  kind: "synthesis",
                  status: "pending",
                  summary: synthesis.review.summary,
                },
              },
        ),
      );
    }
    if (path === "/api/v1/syntheses") {
      return Promise.resolve(jsonResponse(synthesis));
    }
    throw new Error(`Unexpected request: ${path}`);
  });
  const user = userEvent.setup();
  renderAsk();

  const question = await screen.findByRole("textbox", { name: "Question" });
  const model = screen.getByRole("textbox", { name: "Model (optional)" });
  await user.type(question, "What do agents use?");
  await user.type(model, "test:model");
  expect(screen.getByRole("button", { name: "Ask" })).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "Prepare synthesis" }));

  expect(
    await screen.findByRole("heading", {
      name: "Agent tools synthesis",
      level: 2,
    }),
  ).toBeTruthy();
  const reviewLink = screen.getByRole("link", {
    name: "Review the synthesis proposal",
  });
  expect(reviewLink.getAttribute("href")).toBe(`/review/${reviewId}`);
  const synthesisCalls = vi
    .mocked(fetch)
    .mock.calls.filter(([url]) => url === "/api/v1/syntheses");
  expect(synthesisCalls).toHaveLength(1);
  expect(JSON.parse(String(synthesisCalls[0]?.[1]?.body))).toEqual({
    question: "What do agents use?",
    model: "test:model",
  });
  expect(
    vi.mocked(fetch).mock.calls.filter(([url]) => url === "/api/v1/ask"),
  ).toHaveLength(0);
  await waitFor(() => expect(workspaceCalls).toBe(2));
});

test("preserves the question and model after a bounded synthesis failure", async () => {
  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse(workspace))
    .mockResolvedValueOnce(
      jsonResponse(
        {
          error: {
            code: "configuration_error",
            message: "an agent model is required",
            retryable: false,
            review_id: null,
            diagnostic_id: null,
          },
        },
        400,
      ),
    );
  const user = userEvent.setup();
  renderAsk();

  const question = await screen.findByRole("textbox", { name: "Question" });
  const model = screen.getByRole("textbox", { name: "Model (optional)" });
  await user.type(question, "What do agents use?");
  await user.type(model, "missing:model");
  await user.click(screen.getByRole("button", { name: "Prepare synthesis" }));

  await screen.findByText("an agent model is required");
  expect((question as HTMLTextAreaElement).value).toBe("What do agents use?");
  expect((model as HTMLInputElement).value).toBe("missing:model");
  expect(screen.getByRole("status").textContent).toContain(
    "Synthesis preparation failed",
  );
});

test("retains a successful synthesis when workspace reconciliation fails", async () => {
  let workspaceCalls = 0;
  vi.mocked(fetch).mockImplementation((input) => {
    const path = String(input);
    if (path === "/api/v1/workspace") {
      workspaceCalls += 1;
      return workspaceCalls === 1
        ? Promise.resolve(jsonResponse(workspace))
        : Promise.reject(new Error("workspace reload failed"));
    }
    if (path === "/api/v1/syntheses") {
      return Promise.resolve(jsonResponse(synthesis));
    }
    throw new Error(`Unexpected request: ${path}`);
  });
  const user = userEvent.setup();
  renderAsk();

  await user.type(
    await screen.findByRole("textbox", { name: "Question" }),
    "What do agents use?",
  );
  await user.click(screen.getByRole("button", { name: "Prepare synthesis" }));

  expect(
    await screen.findByRole("heading", {
      name: "Agent tools synthesis",
      level: 2,
    }),
  ).toBeTruthy();
  expect(
    screen
      .getByRole("link", { name: "Review the synthesis proposal" })
      .getAttribute("href"),
  ).toBe(`/review/${reviewId}`);
  expect(
    (
      await screen.findByRole("status", {
        name: "Synthesis reconciliation warning",
      })
    ).textContent,
  ).toContain(
    "Synthesis preparation succeeded, but workspace status could not refresh",
  );
  expect(screen.queryByText("Synthesis preparation failed")).toBeNull();
  expect(
    vi.mocked(fetch).mock.calls.filter(([url]) => url === "/api/v1/syntheses"),
  ).toHaveLength(1);
  expect(
    screen.getByRole("button", { name: "Prepare synthesis" }),
  ).toHaveProperty("disabled", true);
});
