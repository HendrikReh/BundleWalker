// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { useMemo, useState } from "react";
import { Link } from "react-router";

import { useConceptPages, useConceptSearch } from "../../api/queries";
import type { WebConceptSummary } from "../../api/types";
import { RequestError } from "../../components/RequestError";

export function BrowsePage() {
  const [input, setInput] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const pages = useConceptPages();
  const search = useConceptSearch(submittedQuery);
  const concepts = useMemo(() => {
    const source =
      submittedQuery.length > 0
        ? search.data?.items
        : pages.data?.pages.flatMap((page) => page.items);
    const unique = new Map<string, WebConceptSummary>();
    for (const concept of source ?? []) unique.set(concept.concept_id, concept);
    return [...unique.values()];
  }, [pages.data, search.data, submittedQuery]);
  const error = submittedQuery.length > 0 ? search.error : pages.error;

  return (
    <section>
      <h1>Browse concepts</h1>
      <form
        role="search"
        onSubmit={(event) => {
          event.preventDefault();
          setSubmittedQuery(input.trim());
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
        <button type="submit">Search</button>
      </form>
      {error ? <RequestError error={error} /> : null}
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
      {submittedQuery.length === 0 && pages.hasNextPage ? (
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

function encodeConceptRoute(conceptId: string): string {
  return conceptId
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
}
