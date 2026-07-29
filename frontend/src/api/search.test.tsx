// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { ApiClient } from "./client";
import { queryKeys, useConceptSearch } from "./queries";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("the API client sends the supported concept type search parameter", async () => {
  vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ items: [] }));

  await new ApiClient().searchConcepts({
    query: "agent tools",
    conceptType: "Entity",
  });

  expect(vi.mocked(fetch).mock.calls[0]?.[0]).toBe(
    "/api/v1/concepts/search?query=agent+tools&type=Entity",
  );
});

test("the concept search query key and request include the submitted type", async () => {
  vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ items: [] }));
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  function Wrapper({ children }: PropsWithChildren) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  }

  const { result } = renderHook(() => useConceptSearch("agents", "Synthesis"), {
    wrapper: Wrapper,
  });

  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(
    queryClient.getQueryData(queryKeys.search("agents", "Synthesis")),
  ).toEqual({ items: [] });
  expect(vi.mocked(fetch).mock.calls[0]?.[0]).toBe(
    "/api/v1/concepts/search?query=agents&type=Synthesis",
  );
});
