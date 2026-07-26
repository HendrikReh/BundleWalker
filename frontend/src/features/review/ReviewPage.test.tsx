// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { queryKeys } from "../../api/queries";
import { AppRoutes } from "../../app/routes";

const reviewId = "a".repeat(32);
const replacementId = "b".repeat(32);
const review = {
  review_id: reviewId,
  kind: "ingestion",
  status: "pending",
  summary: "Integrate browser notes",
  diff:
    "--- /dev/null\n" +
    "+++ wiki/sources/browser-notes.md\n" +
    "@@ -0,0 +1,2 @@\n" +
    "+# Browser notes\n" +
    "+Complete evidence.\n",
  changed_paths: ["sources/browser-notes.md"],
  created_at: "2026-07-25T12:00:00Z",
};
const workspace = {
  display_name: "knowledge",
  config_version: 1,
  concept_counts: { Source: 1 },
  pending_review: {
    review_id: reviewId,
    kind: "ingestion",
    status: "pending",
    summary: "Integrate browser notes",
  },
  csrf_token: "csrf-token",
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

function renderReview() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/review/${reviewId}`]}>
        <AppRoutes />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { queryClient, invalidate };
}

function errorResponse(
  code: string,
  message: string,
  currentReviewId: string | null = null,
) {
  return jsonResponse(
    {
      error: {
        code,
        message,
        retryable: false,
        review_id: currentReviewId,
        diagnostic_id: null,
      },
    },
    code === "review_not_found" ? 404 : 409,
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
  vi.stubGlobal("confirm", vi.fn().mockReturnValue(true));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("shows complete proposal metadata and only whole-proposal resolution controls", async () => {
  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse(workspace))
    .mockResolvedValueOnce(jsonResponse(review));
  renderReview();

  expect(
    await screen.findByRole("heading", { name: "Review proposal" }),
  ).toBeTruthy();
  expect(screen.getByText("ingestion")).toBeTruthy();
  expect(screen.getByText("pending")).toBeTruthy();
  expect(screen.getByText("Integrate browser notes")).toBeTruthy();
  expect(screen.getByText("sources/browser-notes.md")).toBeTruthy();
  expect(screen.getByText(reviewId)).toBeTruthy();
  expect(screen.getByText("2026-07-25T12:00:00Z")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Apply proposal" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Discard proposal" })).toBeTruthy();
  expect(screen.queryByRole("checkbox")).toBeNull();
  expect(screen.queryByText(/partial/i)).toBeNull();
});

test.each([
  ["Apply proposal", "apply", "applied"],
  ["Discard proposal", "discard", "discarded"],
])(
  "confirms and resolves the complete proposal through %s",
  async (buttonName, action, status) => {
    vi.mocked(fetch).mockImplementation((input) => {
      const path = String(input);
      if (path === "/api/v1/workspace")
        return Promise.resolve(jsonResponse(workspace));
      if (path === "/api/v1/review")
        return Promise.resolve(jsonResponse(review));
      if (path === `/api/v1/reviews/${reviewId}/${action}`) {
        return Promise.resolve(jsonResponse({ review_id: reviewId, status }));
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    const user = userEvent.setup();
    renderReview();
    await screen.findByRole("heading", { name: "Review proposal" });

    await user.click(screen.getByRole("button", { name: buttonName }));

    expect(confirm).toHaveBeenCalledWith(
      expect.stringContaining("entire proposal"),
    );
    await waitFor(() => {
      expect(screen.getByTestId("location").textContent).toBe("/browse");
    });
    const mutationCalls = vi
      .mocked(fetch)
      .mock.calls.filter(([path]) =>
        String(path).includes(`/reviews/${reviewId}/${action}`),
      );
    expect(mutationCalls).toHaveLength(1);
  },
);

test("keeps both controls disabled through mutation and query reconciliation", async () => {
  let resolveMutation!: (response: Response) => void;
  let resolveReload!: (response: Response) => void;
  const mutation = new Promise<Response>((resolve) => {
    resolveMutation = resolve;
  });
  const reload = new Promise<Response>((resolve) => {
    resolveReload = resolve;
  });
  let workspaceCalls = 0;
  vi.mocked(fetch).mockImplementation((input) => {
    const path = String(input);
    if (path === "/api/v1/workspace") {
      workspaceCalls += 1;
      return workspaceCalls === 1
        ? Promise.resolve(jsonResponse(workspace))
        : reload;
    }
    if (path === "/api/v1/review") return Promise.resolve(jsonResponse(review));
    if (path === `/api/v1/reviews/${reviewId}/apply`) return mutation;
    throw new Error(`Unexpected request: ${path}`);
  });
  const user = userEvent.setup();
  renderReview();
  const apply = await screen.findByRole("button", { name: "Apply proposal" });
  const discard = screen.getByRole("button", { name: "Discard proposal" });

  await user.click(apply);
  expect((apply as HTMLButtonElement).disabled).toBe(true);
  expect((discard as HTMLButtonElement).disabled).toBe(true);
  resolveMutation(jsonResponse({ review_id: reviewId, status: "applied" }));
  await waitFor(() => expect(workspaceCalls).toBe(2));
  expect((apply as HTMLButtonElement).disabled).toBe(true);
  expect((discard as HTMLButtonElement).disabled).toBe(true);

  resolveReload(jsonResponse({ ...workspace, pending_review: null }));
  await waitFor(() => {
    expect(screen.getByTestId("location").textContent).toBe("/browse");
  });
});

test("invalidates exact authoritative queries before navigating after success", async () => {
  vi.mocked(fetch).mockImplementation((input) => {
    const path = String(input);
    if (path === "/api/v1/workspace")
      return Promise.resolve(jsonResponse(workspace));
    if (path === "/api/v1/review") return Promise.resolve(jsonResponse(review));
    if (path === `/api/v1/reviews/${reviewId}/apply`) {
      return Promise.resolve(
        jsonResponse({ review_id: reviewId, status: "applied" }),
      );
    }
    throw new Error(`Unexpected request: ${path}`);
  });
  const user = userEvent.setup();
  const { invalidate } = renderReview();
  let finishInvalidation!: () => void;
  const finalInvalidation = new Promise<void>((resolve) => {
    finishInvalidation = resolve;
  });
  invalidate.mockImplementation((options) =>
    options?.queryKey === queryKeys.lint
      ? finalInvalidation
      : Promise.resolve(undefined),
  );
  await user.click(
    await screen.findByRole("button", { name: "Apply proposal" }),
  );

  await waitFor(() => expect(invalidate).toHaveBeenCalledTimes(4));
  expect(screen.getByTestId("location").textContent).toBe(
    `/review/${reviewId}`,
  );
  expect(invalidate.mock.calls.map(([options]) => options?.queryKey)).toEqual([
    queryKeys.workspace,
    queryKeys.review,
    queryKeys.concepts,
    queryKeys.lint,
  ]);
  finishInvalidation();
  await waitFor(() => {
    expect(screen.getByTestId("location").textContent).toBe("/browse");
  });
});

test("reloads and announces the current proposal after a resolution conflict without retrying", async () => {
  const replacement = {
    ...review,
    review_id: replacementId,
    summary: "A newer authoritative proposal",
  };
  const replacementWorkspace = {
    ...workspace,
    pending_review: {
      ...workspace.pending_review,
      review_id: replacementId,
      summary: replacement.summary,
    },
  };
  let workspaceCalls = 0;
  let reviewCalls = 0;
  vi.mocked(fetch).mockImplementation((input) => {
    const path = String(input);
    if (path === "/api/v1/workspace") {
      workspaceCalls += 1;
      return Promise.resolve(
        jsonResponse(workspaceCalls === 1 ? workspace : replacementWorkspace),
      );
    }
    if (path === "/api/v1/review") {
      reviewCalls += 1;
      return Promise.resolve(
        jsonResponse(reviewCalls === 1 ? review : replacement),
      );
    }
    if (path === `/api/v1/reviews/${reviewId}/apply`) {
      return Promise.resolve(
        errorResponse(
          "review_id_mismatch",
          "review ID does not match the pending review",
          replacementId,
        ),
      );
    }
    throw new Error(`Unexpected request: ${path}`);
  });
  const user = userEvent.setup();
  renderReview();
  await user.click(
    await screen.findByRole("button", { name: "Apply proposal" }),
  );

  expect(
    (
      await screen.findByRole("status", {
        name: "Review state changed",
      })
    ).textContent,
  ).toContain("A newer authoritative proposal");
  expect(screen.getByText(replacementId)).toBeTruthy();
  expect(screen.getByTestId("location").textContent).toBe(
    `/review/${replacementId}`,
  );
  expect(
    vi
      .mocked(fetch)
      .mock.calls.filter(
        ([path]) => String(path) === `/api/v1/reviews/${reviewId}/apply`,
      ),
  ).toHaveLength(1);
});

test("keeps resolution blocked and does not navigate when success reconciliation fails", async () => {
  let workspaceCalls = 0;
  vi.mocked(fetch).mockImplementation((input) => {
    const path = String(input);
    if (path === "/api/v1/workspace") {
      workspaceCalls += 1;
      return workspaceCalls === 1
        ? Promise.resolve(jsonResponse(workspace))
        : Promise.reject(new Error("workspace reload failed"));
    }
    if (path === "/api/v1/review") return Promise.resolve(jsonResponse(review));
    if (path === `/api/v1/reviews/${reviewId}/apply`) {
      return Promise.resolve(
        jsonResponse({ review_id: reviewId, status: "applied" }),
      );
    }
    throw new Error(`Unexpected request: ${path}`);
  });
  const user = userEvent.setup();
  renderReview();
  await user.click(
    await screen.findByRole("button", { name: "Apply proposal" }),
  );

  expect(
    await screen.findByRole("status", {
      name: "Review reconciliation failed",
    }),
  ).toBeTruthy();
  expect(screen.getByTestId("location").textContent).toBe(
    `/review/${reviewId}`,
  );
  expect(
    (
      screen.getByRole("button", {
        name: "Apply proposal",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(
    (
      screen.getByRole("button", {
        name: "Discard proposal",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
});

test("does not reuse stale cached review or retry when conflict reconciliation fails", async () => {
  let reviewCalls = 0;
  vi.mocked(fetch).mockImplementation((input) => {
    const path = String(input);
    if (path === "/api/v1/workspace") {
      return Promise.resolve(jsonResponse(workspace));
    }
    if (path === "/api/v1/review") {
      reviewCalls += 1;
      return reviewCalls === 1
        ? Promise.resolve(jsonResponse(review))
        : Promise.reject(new Error("review reload failed"));
    }
    if (path === `/api/v1/reviews/${reviewId}/apply`) {
      return Promise.resolve(
        errorResponse(
          "review_id_mismatch",
          "review ID does not match the pending review",
          replacementId,
        ),
      );
    }
    throw new Error(`Unexpected request: ${path}`);
  });
  const user = userEvent.setup();
  renderReview();
  await user.click(
    await screen.findByRole("button", { name: "Apply proposal" }),
  );

  expect(
    await screen.findByRole("status", {
      name: "Review reconciliation failed",
    }),
  ).toBeTruthy();
  expect(screen.queryByText(/Current proposal:/)).toBeNull();
  expect(screen.getByTestId("location").textContent).toBe(
    `/review/${reviewId}`,
  );
  expect(
    (
      screen.getByRole("button", {
        name: "Apply proposal",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(
    vi
      .mocked(fetch)
      .mock.calls.filter(
        ([path]) => String(path) === `/api/v1/reviews/${reviewId}/apply`,
      ),
  ).toHaveLength(1);
});

test("keeps the no-longer-pending conflict announcement in the live region", async () => {
  let workspaceCalls = 0;
  let reviewCalls = 0;
  vi.mocked(fetch).mockImplementation((input) => {
    const path = String(input);
    if (path === "/api/v1/workspace") {
      workspaceCalls += 1;
      return Promise.resolve(
        jsonResponse(
          workspaceCalls === 1
            ? workspace
            : { ...workspace, pending_review: null },
        ),
      );
    }
    if (path === "/api/v1/review") {
      reviewCalls += 1;
      return Promise.resolve(jsonResponse(reviewCalls === 1 ? review : null));
    }
    if (path === `/api/v1/reviews/${reviewId}/discard`) {
      return Promise.resolve(
        errorResponse("review_not_found", "review was not found"),
      );
    }
    throw new Error(`Unexpected request: ${path}`);
  });
  const user = userEvent.setup();
  renderReview();
  await user.click(
    await screen.findByRole("button", { name: "Discard proposal" }),
  );

  expect(
    (
      await screen.findByRole("status", {
        name: "Review state changed",
      })
    ).textContent,
  ).toContain("The proposal is no longer pending.");
  expect(
    screen.getByRole("heading", { name: "No pending review" }),
  ).toBeTruthy();
});

test("does not mutate when confirmation is declined", async () => {
  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse(workspace))
    .mockResolvedValueOnce(jsonResponse(review));
  vi.mocked(confirm).mockReturnValue(false);
  const user = userEvent.setup();
  renderReview();

  await user.click(
    await screen.findByRole("button", { name: "Discard proposal" }),
  );

  expect(
    vi
      .mocked(fetch)
      .mock.calls.filter(([path]) => String(path).includes("/reviews/")),
  ).toHaveLength(0);
});
