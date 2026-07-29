// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { useMemo, useState } from "react";
import { Link } from "react-router";

import {
  useConceptPages,
  useConceptSearch,
  useWorkspace,
} from "../../api/queries";
import type { WebConceptSummary } from "../../api/types";
import { RequestError } from "../../components/RequestError";
import { encodeConceptRoute } from "../../routing/conceptRoute";

const MAX_CONCEPT_TYPE_OPTIONS = 100;

export function BrowsePage() {
  const [input, setInput] = useState("");
  const [conceptType, setConceptType] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [submittedType, setSubmittedType] = useState("");
  const workspace = useWorkspace({ refetchOnMount: false });
  const pages = useConceptPages();
  const search = useConceptSearch(submittedQuery, submittedType || undefined);
  const isSearch = submittedQuery.length > 0;
  const conceptTypes = useMemo(
    () =>
      Object.entries(workspace.data?.concept_counts ?? {})
        .sort(([left], [right]) => compareStrings(left, right))
        .slice(0, MAX_CONCEPT_TYPE_OPTIONS),
    [workspace.data?.concept_counts],
  );
  const availableConceptType = conceptTypes.some(
    ([type]) => type === conceptType,
  )
    ? conceptType
    : "";
  const concepts = useMemo(() => {
    const source = isSearch
      ? search.data?.items
      : pages.data?.pages.flatMap((page) => page.items);
    const unique = new Map<string, WebConceptSummary>();
    for (const concept of source ?? []) unique.set(concept.concept_id, concept);
    return [...unique.values()];
  }, [isSearch, pages.data, search.data]);
  const error = isSearch ? search.error : pages.error;
  const isLoading = isSearch ? search.isPending : pages.isPending;
  const emptyMessage = isSearch
    ? "No concepts match your search."
    : "This workspace has no concepts yet.";

  return (
    <section>
      <h1>Browse concepts</h1>
      <form
        role="search"
        onSubmit={(event) => {
          event.preventDefault();
          const query = input.trim();
          setSubmittedQuery(query);
          setSubmittedType(query.length > 0 ? availableConceptType : "");
        }}
      >
        <label>
          Search concepts
          <input
            type="search"
            value={input}
            onChange={(event) => setInput(event.target.value)}
          />
        </label>
        <label>
          Concept type (search only)
          <select
            value={availableConceptType}
            onChange={(event) => setConceptType(event.target.value)}
          >
            <option value="">All types</option>
            {conceptTypes.map(([type, count]) => (
              <option key={type} value={type}>
                {type} ({count})
              </option>
            ))}
          </select>
        </label>
        <button type="submit">Search</button>
      </form>
      {error ? <RequestError error={error} /> : null}
      {isLoading ? (
        <p role="status">
          {isSearch ? "Searching concepts…" : "Loading concepts…"}
        </p>
      ) : null}
      {!isLoading && !error && concepts.length === 0 ? (
        <p role="status">{emptyMessage}</p>
      ) : null}
      {concepts.length > 0 ? (
        <ul className="concept-list">
          {concepts.map((concept) => (
            <li key={concept.concept_id}>
              <Link to={`/browse/${encodeConceptRoute(concept.concept_id)}`}>
                {concept.title}
              </Link>
              <span>{concept.type}</span>
              {concept.description ? <p>{concept.description}</p> : null}
            </li>
          ))}
        </ul>
      ) : null}
      {!isSearch && pages.hasNextPage ? (
        <button
          type="button"
          disabled={pages.isFetchingNextPage}
          onClick={() => void pages.fetchNextPage()}
        >
          {pages.isFetchingNextPage ? "Loading…" : "Load more"}
        </button>
      ) : null}
    </section>
  );
}

function compareStrings(left: string, right: string): number {
  if (left < right) return -1;
  if (left > right) return 1;
  return 0;
}
