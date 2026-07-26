// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { useParams } from "react-router";

import { useConcept } from "../../api/queries";
import { MarkdownContent } from "../../components/MarkdownContent";
import { RequestError } from "../../components/RequestError";

export function ConceptPage() {
  const conceptId = useParams()["*"] ?? "";
  const concept = useConcept(conceptId);

  if (concept.error) return <RequestError error={concept.error} />;
  if (concept.data === undefined) return <p role="status">Loading concept…</p>;

  return (
    <article>
      <h1>{concept.data.title}</h1>
      <p className="concept-type">{concept.data.type}</p>
      <MarkdownContent markdown={concept.data.markdown} />
    </article>
  );
}
