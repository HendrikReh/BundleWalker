// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { useInfiniteQuery, useMutation, useQuery } from "@tanstack/react-query";

import { ApiClient } from "./client";

export const apiClient = new ApiClient();

export const queryKeys = {
  workspace: ["workspace"] as const,
  concepts: ["concepts"] as const,
  concept: (conceptId: string) => ["concept", conceptId] as const,
  search: (query: string, conceptType?: string) =>
    ["concept-search", query, conceptType ?? null] as const,
  lint: ["lint"] as const,
  ingestion: ["ingestion"] as const,
  synthesis: ["synthesis"] as const,
  refresh: (conceptId: string) => ["refresh", conceptId] as const,
  review: ["review"] as const,
};

export function useWorkspace(
  options: { readonly refetchOnMount: boolean } = { refetchOnMount: true },
) {
  return useQuery({
    queryKey: queryKeys.workspace,
    queryFn: () => apiClient.workspace(),
    refetchOnMount: options.refetchOnMount,
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

export function useConceptSearch(query: string, conceptType?: string) {
  return useQuery({
    queryKey: queryKeys.search(query, conceptType),
    queryFn: () =>
      apiClient.searchConcepts({
        query,
        ...(conceptType === undefined ? {} : { conceptType }),
      }),
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

export function useAsk() {
  return useMutation({
    mutationFn: (options: {
      readonly question: string;
      readonly model?: string | null;
    }) => apiClient.ask(options),
  });
}

export function useLint() {
  return useMutation({
    mutationKey: queryKeys.lint,
    mutationFn: (options: {
      readonly semantic: boolean;
      readonly model?: string | null;
    }) => apiClient.lint(options),
  });
}

export function usePrepareIngestion() {
  return useMutation({
    mutationKey: queryKeys.ingestion,
    mutationFn: (options: {
      readonly source_name: string;
      readonly content: string;
      readonly model?: string | null;
    }) => apiClient.prepareIngestion(options),
  });
}

export function usePrepareSynthesis() {
  return useMutation({
    mutationKey: queryKeys.synthesis,
    mutationFn: (options: {
      readonly question: string;
      readonly model?: string | null;
    }) => apiClient.prepareSynthesis(options),
  });
}

export function usePrepareRefresh(conceptId: string) {
  return useMutation({
    mutationKey: queryKeys.refresh(conceptId),
    mutationFn: (options: {
      readonly instruction: string;
      readonly concept_id: string;
      readonly model?: string | null;
    }) => apiClient.prepareRefresh(options),
  });
}

export function useReview() {
  return useQuery({
    queryKey: queryKeys.review,
    queryFn: () => apiClient.review(),
  });
}

export function useApplyReview() {
  return useMutation({
    mutationFn: (reviewId: string) => apiClient.applyReview(reviewId),
  });
}

export function useDiscardReview() {
  return useMutation({
    mutationFn: (reviewId: string) => apiClient.discardReview(reviewId),
  });
}
