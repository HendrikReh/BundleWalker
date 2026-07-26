// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { AppRoutes } from "../../app/routes";

const workspace = {
  display_name: "knowledge",
  config_version: 1,
  concept_counts: { Topic: 1 },
  pending_review: null,
  csrf_token: "csrf-token",
};

const answer = {
  title: "Agent tools",
  markdown:
    "# Answer\n\nAgents can use tools [1].\n\n# Citations\n\n[1] [Agents](/topics/agents.md)\n",
  citations: [{ number: 1, concept_id: "topics/agents" }],
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

test("shows Ask progress and prevents a duplicate submission", async () => {
  let resolveAsk!: (response: Response) => void;
  const pendingAsk = new Promise<Response>((resolve) => {
    resolveAsk = resolve;
  });
  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse(workspace))
    .mockReturnValueOnce(pendingAsk);
  const user = userEvent.setup();
  renderAsk();

  await user.type(
    await screen.findByRole("textbox", { name: "Question" }),
    "What do agents use?",
  );
  const submit = screen.getByRole("button", { name: "Ask" });
  await user.click(submit);

  expect((submit as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByRole("status").textContent).toContain(
    "Asking the knowledge base",
  );
  await user.click(submit);
  expect(
    vi.mocked(fetch).mock.calls.filter(([url]) => url === "/api/v1/ask"),
  ).toHaveLength(1);

  resolveAsk(jsonResponse(answer));
  await screen.findByRole("heading", { name: "Agent tools", level: 2 });
  expect(screen.getByRole("status").textContent).toContain("Answer ready");
});

test("preserves question and optional model after a bounded failure", async () => {
  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse(workspace))
    .mockResolvedValueOnce(
      jsonResponse(
        {
          error: {
            code: "model_failed",
            message: "model request failed",
            retryable: false,
            review_id: null,
            diagnostic_id: null,
          },
        },
        502,
      ),
    );
  const user = userEvent.setup();
  renderAsk();

  const question = await screen.findByRole("textbox", { name: "Question" });
  const model = screen.getByRole("textbox", { name: "Model (optional)" });
  await user.type(question, "What do agents use?");
  await user.type(model, "test:model");
  await user.click(screen.getByRole("button", { name: "Ask" }));

  await screen.findByRole("alert");
  expect((question as HTMLTextAreaElement).value).toBe("What do agents use?");
  expect((model as HTMLInputElement).value).toBe("test:model");
  expect(model.getAttribute("maxlength")).toBe("255");
  expect(screen.getByRole("status").textContent).toContain("Ask failed");
});

test("renders cited Markdown through the safe concept-link renderer", async () => {
  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse(workspace))
    .mockResolvedValueOnce(jsonResponse(answer));
  const user = userEvent.setup();
  renderAsk();

  await user.type(
    await screen.findByRole("textbox", { name: "Question" }),
    "What do agents use?",
  );
  await user.click(screen.getByRole("button", { name: "Ask" }));

  const citation = await screen.findByRole("link", { name: "Agents" });
  expect(citation.getAttribute("href")).toBe("/browse/topics/agents");
  expect(document.querySelector("script")).toBeNull();
  await waitFor(() => {
    expect(screen.getByRole("status").textContent).toContain("Answer ready");
  });
});
