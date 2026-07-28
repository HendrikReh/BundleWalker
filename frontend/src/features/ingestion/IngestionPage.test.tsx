// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { AppRoutes } from "../../app/routes";

const workspace = {
  display_name: "knowledge",
  config_version: 1,
  concept_counts: { Topic: 1 },
  pending_review: null,
  csrf_token: "csrf-token",
};

const pendingResult = {
  status: "pending",
  review: {
    review_id: "a".repeat(32),
    kind: "ingestion",
    status: "pending",
    summary: "Integrated browser notes",
    diff: "--- /dev/null\n+++ wiki/sources/notes.md\n",
    changed_paths: ["sources/notes.md"],
    created_at: "2026-07-25T12:00:00Z",
  },
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function LocationProbe() {
  return <div data-testid="location">{useLocation().pathname}</div>;
}

function renderIngestion() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/ingest"]}>
        <AppRoutes />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function textFile(name: string, content: string): File {
  return byteFile(name, new TextEncoder().encode(content));
}

function byteFile(name: string, bytes: Uint8Array): File {
  const ownedBytes = new Uint8Array(bytes.byteLength);
  ownedBytes.set(bytes);
  const file = new File([ownedBytes.buffer], name, {
    type: "text/markdown",
  });
  Object.defineProperty(file, "arrayBuffer", {
    configurable: true,
    value: vi.fn().mockResolvedValue(ownedBytes.slice().buffer),
  });
  Object.defineProperty(file, "text", {
    configurable: true,
    value: vi.fn().mockResolvedValue(new TextDecoder().decode(ownedBytes)),
  });
  return file;
}

function ingestionRequest(): [RequestInfo | URL, RequestInit | undefined] {
  const call = vi
    .mocked(fetch)
    .mock.calls.find(([url]) => url === "/api/v1/ingestions");
  if (call === undefined) throw new Error("ingestion request was not sent");
  return [call[0], call[1]];
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("uploads one accepted file by reading its bytes and sending its basename as JSON", async () => {
  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse(workspace))
    .mockResolvedValueOnce(jsonResponse({ status: "duplicate", review: null }));
  const user = userEvent.setup();
  renderIngestion();

  await user.click(await screen.findByRole("radio", { name: "Choose a file" }));
  const input = screen.getByLabelText("Source file") as HTMLInputElement;
  expect(input.accept).toBe(".md,.txt");
  expect(input.multiple).toBe(false);
  const first = textFile("meeting notes.md", "# Meeting\n\nEvidence.");
  const second = textFile("ignored.txt", "Ignored.");
  await user.upload(input, [first, second]);

  expect(input.files).toHaveLength(1);
  await user.click(screen.getByRole("button", { name: "Prepare ingestion" }));

  await screen.findByText("This source is already in the knowledge base.");
  expect(first.arrayBuffer).toHaveBeenCalledTimes(1);
  const [, init] = ingestionRequest();
  expect(init?.headers).toBeInstanceOf(Headers);
  expect(JSON.parse(String(init?.body))).toEqual({
    source_name: "meeting notes.md",
    content: "# Meeting\n\nEvidence.",
    model: null,
  });
});

test("rejects malformed UTF-8 file bytes without sending replacement text", async () => {
  vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(workspace));
  const user = userEvent.setup();
  renderIngestion();

  await user.click(await screen.findByRole("radio", { name: "Choose a file" }));
  const file = byteFile(
    "malformed.md",
    new Uint8Array([0x23, 0x20, 0xc3, 0x28]),
  );
  const input = screen.getByLabelText("Source file");
  await user.upload(input, file);
  await user.click(screen.getByRole("button", { name: "Prepare ingestion" }));

  expect((await screen.findByRole("alert")).textContent).toContain(
    "valid UTF-8",
  );
  expect(screen.getByText("Selected: malformed.md")).toBeTruthy();
  expect(screen.getByRole("radio", { name: "Choose a file" })).toHaveProperty(
    "checked",
    true,
  );
  expect(document.activeElement).toBe(screen.getByRole("alert"));
  expect(file.arrayBuffer).toHaveBeenCalledTimes(1);
  expect(file.text).not.toHaveBeenCalled();
  expect(
    vi.mocked(fetch).mock.calls.filter(([url]) => url === "/api/v1/ingestions"),
  ).toHaveLength(0);
});

test("preserves valid multibyte UTF-8 file content exactly", async () => {
  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse(workspace))
    .mockResolvedValueOnce(jsonResponse({ status: "duplicate", review: null }));
  const user = userEvent.setup();
  renderIngestion();

  await user.click(await screen.findByRole("radio", { name: "Choose a file" }));
  const utf8 = new Uint8Array([
    0x23, 0x20, 0x47, 0x72, 0xc3, 0xbc, 0xc3, 0x9f, 0x65, 0x20, 0xf0, 0x9f,
    0x8c, 0x8d,
  ]);
  await user.upload(
    screen.getByLabelText("Source file"),
    byteFile("grüße.md", utf8),
  );
  await user.click(screen.getByRole("button", { name: "Prepare ingestion" }));

  await screen.findByText("This source is already in the knowledge base.");
  const [, init] = ingestionRequest();
  expect(JSON.parse(String(init?.body))).toMatchObject({
    source_name: "grüße.md",
    content: "# Grüße 🌍",
  });
});

test("submits only the active mode and supports dropping a single file", async () => {
  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse(workspace))
    .mockResolvedValueOnce(jsonResponse({ status: "duplicate", review: null }));
  const user = userEvent.setup();
  renderIngestion();

  const pasted = await screen.findByRole("textbox", { name: "Content" });
  await user.type(pasted, "Pasted content that must stay inactive.");
  await user.click(screen.getByRole("radio", { name: "Choose a file" }));
  const file = textFile("dropped.txt", "Dropped evidence.");
  fireEvent.drop(screen.getByTestId("file-drop-target"), {
    dataTransfer: { files: [file] },
  });
  await user.click(screen.getByRole("button", { name: "Prepare ingestion" }));

  await screen.findByText("This source is already in the knowledge base.");
  const [, init] = ingestionRequest();
  expect(JSON.parse(String(init?.body))).toMatchObject({
    source_name: "dropped.txt",
    content: "Dropped evidence.",
  });
  expect(JSON.parse(String(init?.body)).content).not.toContain(
    "Pasted content",
  );
});

test.each([
  ["unsupported suffix", textFile("notes.pdf", "Evidence.")],
  ["unsafe separator", textFile("folder/notes.md", "Evidence.")],
  ["dot-only name", textFile(".md", "Evidence.")],
  ["control character", textFile("notes\nprivate.md", "Evidence.")],
  ["blank content", textFile("notes.md", " \n\t")],
  ["oversized bytes", textFile("notes.md", "a".repeat(4_000_001))],
])(
  "repeats %s validation before submitting a selected file",
  async (_case, file) => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(workspace));
    const user = userEvent.setup();
    renderIngestion();

    await user.click(
      await screen.findByRole("radio", { name: "Choose a file" }),
    );
    fireEvent.drop(screen.getByTestId("file-drop-target"), {
      dataTransfer: { files: [file] },
    });
    await user.click(screen.getByRole("button", { name: "Prepare ingestion" }));

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(
      vi
        .mocked(fetch)
        .mock.calls.filter(([url]) => url === "/api/v1/ingestions"),
    ).toHaveLength(0);
  },
);

test("preserves pasted content and source name after a bounded error", async () => {
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
  renderIngestion();

  const sourceName = await screen.findByRole("textbox", {
    name: "Source filename",
  });
  const content = screen.getByRole("textbox", { name: "Content" });
  await user.clear(sourceName);
  await user.type(sourceName, "field-notes.md");
  await user.type(content, "# Field notes\n\nEvidence.");
  await user.click(screen.getByRole("button", { name: "Prepare ingestion" }));

  await screen.findByText("model request failed");
  expect((sourceName as HTMLInputElement).value).toBe("field-notes.md");
  expect((content as HTMLTextAreaElement).value).toBe(
    "# Field notes\n\nEvidence.",
  );
  expect(screen.getByRole("status").textContent).toContain(
    "Ingestion preparation failed",
  );
});

test("shows a no-change result for duplicate pasted content", async () => {
  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse(workspace))
    .mockResolvedValueOnce(jsonResponse({ status: "duplicate", review: null }));
  const user = userEvent.setup();
  renderIngestion();

  await user.type(
    await screen.findByRole("textbox", { name: "Content" }),
    "Existing evidence.",
  );
  await user.click(screen.getByRole("button", { name: "Prepare ingestion" }));

  expect(
    await screen.findByText("This source is already in the knowledge base."),
  ).toBeTruthy();
  expect(screen.getByRole("status").textContent).toContain(
    "No changes prepared",
  );
});

test("navigates a pending result to its opaque review route", async () => {
  vi.mocked(fetch).mockImplementation((input) => {
    const path = String(input);
    if (path === "/api/v1/workspace") {
      return Promise.resolve(
        jsonResponse({
          ...workspace,
          pending_review: {
            review_id: pendingResult.review.review_id,
            kind: pendingResult.review.kind,
            status: pendingResult.review.status,
            summary: pendingResult.review.summary,
          },
        }),
      );
    }
    if (path === "/api/v1/ingestions") {
      return Promise.resolve(jsonResponse(pendingResult));
    }
    if (path === "/api/v1/review") {
      return Promise.resolve(jsonResponse(pendingResult.review));
    }
    throw new Error(`Unexpected request: ${path}`);
  });
  const user = userEvent.setup();
  renderIngestion();

  await user.type(
    await screen.findByRole("textbox", { name: "Content" }),
    "New evidence.",
  );
  await user.click(screen.getByRole("button", { name: "Prepare ingestion" }));

  await waitFor(() => {
    expect(screen.queryByRole("heading", { name: "New ingestion" })).toBeNull();
  });
  expect(
    await screen.findByRole("heading", { name: "Review proposal" }),
  ).toBeTruthy();
  expect(screen.getByText("Integrated browser notes")).toBeTruthy();
});

test("waits for both authoritative refetches before navigating", async () => {
  let workspaceCalls = 0;
  let resolveReview: ((response: Response) => void) | undefined;
  const reviewResponse = new Promise<Response>((resolve) => {
    resolveReview = resolve;
  });
  vi.mocked(fetch).mockImplementation((input) => {
    const path = String(input);
    if (path === "/api/v1/workspace") {
      workspaceCalls += 1;
      return Promise.resolve(
        workspaceCalls === 1
          ? jsonResponse(workspace)
          : jsonResponse({
              ...workspace,
              pending_review: {
                review_id: pendingResult.review.review_id,
                kind: pendingResult.review.kind,
                status: pendingResult.review.status,
                summary: pendingResult.review.summary,
              },
            }),
      );
    }
    if (path === "/api/v1/ingestions") {
      return Promise.resolve(jsonResponse(pendingResult));
    }
    if (path === "/api/v1/review") return reviewResponse;
    throw new Error(`Unexpected request: ${path}`);
  });
  const user = userEvent.setup();
  renderIngestion();

  await user.type(
    await screen.findByRole("textbox", { name: "Content" }),
    "New evidence.",
  );
  await user.click(screen.getByRole("button", { name: "Prepare ingestion" }));

  await waitFor(() => {
    expect(
      vi.mocked(fetch).mock.calls.filter(([url]) => url === "/api/v1/review"),
    ).toHaveLength(1);
  });
  expect(screen.getByTestId("location").textContent).toBe("/ingest");
  expect(screen.getByRole("heading", { name: "New ingestion" })).toBeTruthy();
  expect(
    screen.queryByRole("link", { name: "Review the ingestion proposal" }),
  ).toBeNull();

  if (resolveReview === undefined) {
    throw new Error("review response resolver was not initialized");
  }
  resolveReview(jsonResponse(pendingResult.review));

  await waitFor(() => {
    expect(screen.getByTestId("location").textContent).toBe(
      `/review/${pendingResult.review.review_id}`,
    );
  });
  expect(
    await screen.findByRole("heading", { name: "Review proposal" }),
  ).toBeTruthy();
});

test("retains a pending ingestion when workspace reconciliation fails", async () => {
  let workspaceCalls = 0;
  vi.mocked(fetch).mockImplementation((input) => {
    const path = String(input);
    if (path === "/api/v1/workspace") {
      workspaceCalls += 1;
      return workspaceCalls === 1
        ? Promise.resolve(jsonResponse(workspace))
        : Promise.reject(new Error("workspace reload failed"));
    }
    if (path === "/api/v1/ingestions") {
      return Promise.resolve(jsonResponse(pendingResult));
    }
    if (path === "/api/v1/review") {
      return Promise.resolve(jsonResponse(pendingResult.review));
    }
    throw new Error(`Unexpected request: ${path}`);
  });
  const user = userEvent.setup();
  renderIngestion();

  await user.type(
    await screen.findByRole("textbox", { name: "Content" }),
    "New evidence.",
  );
  await user.click(screen.getByRole("button", { name: "Prepare ingestion" }));

  expect(
    (
      await screen.findByRole("status", {
        name: "Ingestion reconciliation warning",
      })
    ).textContent,
  ).toContain(
    "Ingestion preparation succeeded, but workspace and review status could not refresh",
  );
  expect(screen.getByRole("heading", { name: "New ingestion" })).toBeTruthy();
  expect(screen.getByTestId("location").textContent).toBe("/ingest");
  expect(
    screen
      .getByRole("link", { name: "Review the ingestion proposal" })
      .getAttribute("href"),
  ).toBe(`/review/${pendingResult.review.review_id}`);
  expect(screen.getByText("Integrated browser notes")).toBeTruthy();
  expect(screen.queryByText("Ingestion preparation failed")).toBeNull();
  expect(
    vi.mocked(fetch).mock.calls.filter(([url]) => url === "/api/v1/ingestions"),
  ).toHaveLength(1);
  expect(
    screen.getByRole("button", { name: "Prepare ingestion" }),
  ).toHaveProperty("disabled", true);
  await user.click(screen.getByRole("button", { name: "Prepare ingestion" }));
  expect(
    vi.mocked(fetch).mock.calls.filter(([url]) => url === "/api/v1/ingestions"),
  ).toHaveLength(1);
});

test("retains a pending ingestion when review reconciliation fails", async () => {
  let workspaceCalls = 0;
  vi.mocked(fetch).mockImplementation((input) => {
    const path = String(input);
    if (path === "/api/v1/workspace") {
      workspaceCalls += 1;
      return Promise.resolve(
        workspaceCalls === 1
          ? jsonResponse(workspace)
          : jsonResponse({
              ...workspace,
              pending_review: {
                review_id: pendingResult.review.review_id,
                kind: pendingResult.review.kind,
                status: pendingResult.review.status,
                summary: pendingResult.review.summary,
              },
            }),
      );
    }
    if (path === "/api/v1/ingestions") {
      return Promise.resolve(jsonResponse(pendingResult));
    }
    if (path === "/api/v1/review") {
      return Promise.reject(new Error("review reload failed"));
    }
    throw new Error(`Unexpected request: ${path}`);
  });
  const user = userEvent.setup();
  renderIngestion();

  await user.type(
    await screen.findByRole("textbox", { name: "Content" }),
    "New evidence.",
  );
  await user.click(screen.getByRole("button", { name: "Prepare ingestion" }));

  expect(
    await screen.findByRole("status", {
      name: "Ingestion reconciliation warning",
    }),
  ).toBeTruthy();
  expect(screen.getByRole("heading", { name: "New ingestion" })).toBeTruthy();
  expect(screen.getByTestId("location").textContent).toBe("/ingest");
  expect(
    screen
      .getByRole("link", { name: "Review the ingestion proposal" })
      .getAttribute("href"),
  ).toBe(`/review/${pendingResult.review.review_id}`);
  expect(screen.getByText("Integrated browser notes")).toBeTruthy();
  expect(
    screen.queryByRole("heading", { name: "Review unavailable" }),
  ).toBeNull();
  expect(
    vi.mocked(fetch).mock.calls.filter(([url]) => url === "/api/v1/ingestions"),
  ).toHaveLength(1);
  expect(
    screen.getByRole("button", { name: "Prepare ingestion" }),
  ).toHaveProperty("disabled", true);
});

test.each(["workspace", "review"] as const)(
  "does not navigate when the authoritative %s review identity differs",
  async (mismatch) => {
    const otherReview = {
      ...pendingResult.review,
      review_id: "b".repeat(32),
      summary: "A different pending proposal",
    };
    let workspaceCalls = 0;
    vi.mocked(fetch).mockImplementation((input) => {
      const path = String(input);
      if (path === "/api/v1/workspace") {
        workspaceCalls += 1;
        return Promise.resolve(
          workspaceCalls === 1
            ? jsonResponse(workspace)
            : jsonResponse({
                ...workspace,
                pending_review: {
                  review_id:
                    mismatch === "workspace"
                      ? otherReview.review_id
                      : pendingResult.review.review_id,
                  kind: pendingResult.review.kind,
                  status: pendingResult.review.status,
                  summary: pendingResult.review.summary,
                },
              }),
        );
      }
      if (path === "/api/v1/ingestions") {
        return Promise.resolve(jsonResponse(pendingResult));
      }
      if (path === "/api/v1/review") {
        return Promise.resolve(
          jsonResponse(
            mismatch === "review" ? otherReview : pendingResult.review,
          ),
        );
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    const user = userEvent.setup();
    renderIngestion();

    await user.type(
      await screen.findByRole("textbox", { name: "Content" }),
      "New evidence.",
    );
    await user.click(screen.getByRole("button", { name: "Prepare ingestion" }));

    expect(
      await screen.findByRole("status", {
        name: "Ingestion reconciliation warning",
      }),
    ).toBeTruthy();
    expect(screen.getByTestId("location").textContent).toBe("/ingest");
    expect(screen.getByText("Integrated browser notes")).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: "Review the ingestion proposal" })
        .getAttribute("href"),
    ).toBe(`/review/${pendingResult.review.review_id}`);
    expect(
      vi
        .mocked(fetch)
        .mock.calls.filter(([url]) => url === "/api/v1/ingestions"),
    ).toHaveLength(1);
  },
);
