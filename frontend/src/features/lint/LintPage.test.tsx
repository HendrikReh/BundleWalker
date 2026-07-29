// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
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

test("groups each origin by severity order and then by concept", async () => {
  const mixedFindings = [
    {
      origin: "semantic",
      severity: "info",
      code: "SEM-INFO",
      message: "Workspace-level semantic advice.",
      path: null,
      evidence_paths: [],
      remediation: null,
    },
    {
      origin: "deterministic",
      severity: "warning",
      code: "WARN-Z",
      message: "Warning for Z.",
      path: "topics/z.md",
      evidence_paths: [],
      remediation: null,
    },
    {
      origin: "deterministic",
      severity: "error",
      code: "ERR-B",
      message: "Error for B.",
      path: "topics/b.md",
      evidence_paths: [],
      remediation: "Repair B.",
    },
    {
      origin: "semantic",
      severity: "error",
      code: "SEM-ERROR",
      message: "Semantic error for Z.",
      path: "entities/z.md",
      evidence_paths: ["sources/z"],
      remediation: null,
    },
    {
      origin: "deterministic",
      severity: "info",
      code: "INFO-A",
      message: "Information for A.",
      path: "topics/a.md",
      evidence_paths: [],
      remediation: null,
    },
    {
      origin: "deterministic",
      severity: "error",
      code: "ERR-WORKSPACE",
      message: "Workspace-level error.",
      path: null,
      evidence_paths: [],
      remediation: null,
    },
    {
      origin: "semantic",
      severity: "warning",
      code: "SEM-WARN",
      message: "Semantic warning for Z.",
      path: "entities/z.md",
      evidence_paths: [],
      remediation: null,
    },
    {
      origin: "deterministic",
      severity: "error",
      code: "ERR-A",
      message: "Error for A.",
      path: "topics/a.md",
      evidence_paths: [],
      remediation: null,
    },
    {
      origin: "deterministic",
      severity: "warning",
      code: "WARN-A",
      message: "Warning for A.",
      path: "topics/a.md",
      evidence_paths: [],
      remediation: null,
    },
  ];
  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse(workspace))
    .mockResolvedValueOnce(
      jsonResponse({
        deterministic_has_errors: true,
        findings: mixedFindings,
      }),
    );
  const user = userEvent.setup();
  renderLint();

  await user.click(
    await screen.findByRole("checkbox", { name: "Include semantic lint" }),
  );
  await user.click(screen.getByRole("button", { name: "Run lint" }));

  const deterministic = await screen.findByRole("region", {
    name: "Deterministic findings",
  });
  expect(
    within(deterministic)
      .getAllByRole("heading", { level: 3 })
      .map((heading) => heading.textContent),
  ).toEqual(["Errors", "Warnings", "Information"]);

  const errors = within(deterministic).getByRole("region", {
    name: "Errors",
  });
  expect(
    within(errors)
      .getAllByRole("heading", { level: 4 })
      .map((heading) => heading.textContent),
  ).toEqual([
    "Concept: Workspace",
    "Concept: topics/a.md",
    "Concept: topics/b.md",
  ]);
  expect(
    within(errors)
      .getAllByRole("listitem")
      .map((finding) => finding.querySelector("strong")?.textContent),
  ).toEqual(["ERR-WORKSPACE", "ERR-A", "ERR-B"]);
  expect(errors.textContent).toContain("Severity: error");
  expect(errors.textContent).toContain("Suggested action: Repair B.");

  const semantic = screen.getByRole("region", {
    name: "Semantic findings",
  });
  expect(
    within(semantic)
      .getAllByRole("heading", { level: 3 })
      .map((heading) => heading.textContent),
  ).toEqual(["Errors", "Warnings", "Information"]);
  expect(
    within(semantic)
      .getAllByRole("heading", { level: 4 })
      .map((heading) => heading.textContent),
  ).toEqual([
    "Concept: entities/z.md",
    "Concept: entities/z.md",
    "Concept: Workspace",
  ]);
  expect(semantic.textContent).toContain("Severity: warning");
  expect(semantic.textContent).toContain("Severity: info");
});

test("does not render empty nested groups when an origin has no findings", async () => {
  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse(workspace))
    .mockResolvedValueOnce(
      jsonResponse({
        deterministic_has_errors: false,
        findings: lintResult.findings.filter(
          (finding) => finding.origin === "deterministic",
        ),
      }),
    );
  const user = userEvent.setup();
  renderLint();

  await user.click(await screen.findByRole("button", { name: "Run lint" }));

  const semantic = await screen.findByRole("region", {
    name: "Semantic findings",
  });
  expect(semantic.textContent).toContain("No findings.");
  expect(within(semantic).queryAllByRole("heading", { level: 3 })).toHaveLength(
    0,
  );
});

test("keeps null workspace scope distinct from a literal workspace path", async () => {
  const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
  try {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse(workspace))
      .mockResolvedValueOnce(
        jsonResponse({
          deterministic_has_errors: true,
          findings: [
            {
              origin: "deterministic",
              severity: "error",
              code: "ROOT-SCOPE",
              message: "Workspace metadata is invalid.",
              path: null,
              evidence_paths: [],
              remediation: null,
            },
            {
              origin: "deterministic",
              severity: "error",
              code: "LITERAL-PATH",
              message: "The workspace concept is invalid.",
              path: "workspace",
              evidence_paths: [],
              remediation: null,
            },
          ],
        }),
      );
    const user = userEvent.setup();
    renderLint();

    await user.click(await screen.findByRole("button", { name: "Run lint" }));

    const errors = await screen.findByRole("region", { name: "Errors" });
    const rootScope = within(errors).getByRole("region", {
      name: "Concept: Workspace",
    });
    const literalPath = within(errors).getByRole("region", {
      name: "Concept: workspace",
    });
    expect(rootScope.textContent).toContain("ROOT-SCOPE");
    expect(rootScope.textContent).not.toContain("LITERAL-PATH");
    expect(literalPath.textContent).toContain("LITERAL-PATH");
    expect(literalPath.textContent).not.toContain("ROOT-SCOPE");
    expect(consoleError.mock.calls.flat().map(String).join(" ")).not.toContain(
      "same key",
    );
  } finally {
    consoleError.mockRestore();
  }
});
