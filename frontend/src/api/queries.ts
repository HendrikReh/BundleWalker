// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { ApiClient } from "./client";

export const apiClient = new ApiClient();

export const queryKeys = {
  workspace: ["workspace"] as const,
  concepts: ["concepts"] as const,
  concept: (conceptId: string) => ["concept", conceptId] as const,
  search: (query: string, conceptType?: string) =>
    ["concept-search", query, conceptType ?? null] as const,
};

export function useWorkspace() {
  return useQuery({
    queryKey: queryKeys.workspace,
    queryFn: () => apiClient.workspace(),
  });
}

export function useConceptPages() {
  return useInfiniteQuery({
    queryKey: queryKeys.concepts,
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => apiClient.concepts({ cursor: pageParam }),
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
  });
}

export function useConceptSearch(query: string) {
  return useQuery({
    queryKey: queryKeys.search(query),
    queryFn: () => apiClient.searchConcepts({ query }),
    enabled: query.length > 0,
  });
}

export function useConcept(conceptId: string) {
  return useQuery({
    queryKey: queryKeys.concept(conceptId),
    queryFn: () => apiClient.concept(conceptId),
    enabled: conceptId.length > 0,
  });
}
