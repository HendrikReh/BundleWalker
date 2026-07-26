// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function textFile(name: string, content: string): File {
  const file = new File([content], name, { type: "text/markdown" });
  Object.defineProperty(file, "text", {
    configurable: true,
    value: vi.fn().mockResolvedValue(content),
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

test("uploads one accepted file by reading its text and sending its basename as JSON", async () => {
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
  expect(first.text).toHaveBeenCalledTimes(1);
  const [, init] = ingestionRequest();
  expect(init?.headers).toBeInstanceOf(Headers);
  expect(JSON.parse(String(init?.body))).toEqual({
    source_name: "meeting notes.md",
    content: "# Meeting\n\nEvidence.",
    model: null,
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
  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse(workspace))
    .mockResolvedValueOnce(jsonResponse(pendingResult));
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
    screen.getByRole("heading", { name: "No pending review" }),
  ).toBeTruthy();
});
