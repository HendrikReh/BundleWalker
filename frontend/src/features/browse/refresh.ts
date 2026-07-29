// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import type { WebConceptResponse } from "../../api/types";
import { encodeConceptRoute } from "../../routing/conceptRoute";

const CANONICAL_SYNTHESIS_ID = /^syntheses\/[a-z0-9]+(?:-[a-z0-9]+)*$/;

export function isRefreshEligibleConcept(
  concept: Pick<WebConceptResponse, "concept_id" | "type">,
): boolean {
  return (
    concept.type === "Synthesis" &&
    CANONICAL_SYNTHESIS_ID.test(concept.concept_id)
  );
}

export function refreshPathForConcept(conceptId: string): string {
  return `/refresh/${encodeConceptRoute(conceptId)}`;
}
