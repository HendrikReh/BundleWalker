// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
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

const lintResult = {
  deterministic_has_errors: false,
  findings: [
    {
      origin: "deterministic",
      severity: "warning",
      code: "ORPHAN001",
      message: "Concept is not referenced.",
      path: "topics/agents.md",
      evidence_paths: [],
      remediation: null,
    },
    {
      origin: "semantic",
      severity: "info",
      code: "SEM-GAP",
      message: "Explain how tools support agents.",
      path: "topics/agents.md",
      evidence_paths: ["topics/agents"],
      remediation: "Add one evidence-backed example.",
    },
  ],
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderLint() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/lint"]}>
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

test("shows lint progress and prevents duplicate runs", async () => {
  let resolveLint!: (response: Response) => void;
  const pendingLint = new Promise<Response>((resolve) => {
    resolveLint = resolve;
  });
  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse(workspace))
    .mockReturnValueOnce(pendingLint);
  const user = userEvent.setup();
  renderLint();

  const run = await screen.findByRole("button", { name: "Run lint" });
  await user.click(run);

  expect((run as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByRole("status").textContent).toContain(
    "Checking the knowledge base",
  );
  await user.click(run);
  expect(
    vi.mocked(fetch).mock.calls.filter(([url]) => url === "/api/v1/lint"),
  ).toHaveLength(1);

  resolveLint(jsonResponse(lintResult));
  await screen.findByRole("heading", { name: "Deterministic findings" });
  expect(screen.getByRole("status").textContent).toContain("Lint complete");
});

test("preserves semantic selection and optional model after bounded failure", async () => {
  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse(workspace))
    .mockResolvedValueOnce(
      jsonResponse(
        {
          error: {
            code: "configuration_error",
            message:
              "an agent model is required; pass --model MODEL or set BUNDLEWALKER_MODEL",
            retryable: false,
            review_id: null,
            diagnostic_id: null,
          },
        },
        400,
      ),
    );
  const user = userEvent.setup();
  renderLint();

  const semantic = await screen.findByRole("checkbox", {
    name: "Include semantic lint",
  });
  const model = screen.getByRole("textbox", { name: "Model (optional)" });
  await user.click(semantic);
  await user.type(model, "test:model");
  await user.click(screen.getByRole("button", { name: "Run lint" }));

  await screen.findByRole("alert");
  expect((semantic as HTMLInputElement).checked).toBe(true);
  expect((model as HTMLInputElement).value).toBe("test:model");
  expect(model.getAttribute("maxlength")).toBe("255");
  expect(screen.getByRole("status").textContent).toContain("Lint failed");
});

test("keeps deterministic and semantic findings distinct with visible severity text", async () => {
  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse(workspace))
    .mockResolvedValueOnce(jsonResponse(lintResult));
  const user = userEvent.setup();
  renderLint();

  await user.click(
    await screen.findByRole("checkbox", { name: "Include semantic lint" }),
  );
  await user.click(screen.getByRole("button", { name: "Run lint" }));

  const deterministic = await screen.findByRole("region", {
    name: "Deterministic findings",
  });
  const semantic = screen.getByRole("region", { name: "Semantic findings" });
  expect(deterministic.textContent).toContain("Severity: warning");
  expect(deterministic.textContent).toContain("ORPHAN001");
  expect(semantic.textContent).toContain("Severity: info");
  expect(semantic.textContent).toContain("SEM-GAP");
});
