// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { Link, useParams } from "react-router";

import { useConcept } from "../../api/queries";
import { MarkdownContent } from "../../components/MarkdownContent";
import { RequestError } from "../../components/RequestError";
import { isRefreshEligibleConcept, refreshPathForConcept } from "./refresh";

export function ConceptPage() {
  const conceptId = useParams()["*"] ?? "";
  const concept = useConcept(conceptId);

  if (concept.error) return <RequestError error={concept.error} />;
  if (concept.data === undefined) return <p role="status">Loading concept…</p>;

  return (
    <article>
      <h1>{concept.data.title}</h1>
      <p className="concept-type">{concept.data.type}</p>
      {isRefreshEligibleConcept(concept.data) ? (
        <p>
          <Link to={refreshPathForConcept(concept.data.concept_id)}>
            Prepare refresh
          </Link>
        </p>
      ) : null}
      <MarkdownContent markdown={concept.data.markdown} />
    </article>
  );
}
