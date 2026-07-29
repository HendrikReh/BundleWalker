// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, expect, it } from "vitest";

import contracts from "../test/fixtures/contracts.json";
import type { WebRefreshResponse } from "./types";

function assertRefreshResponse(
  value: unknown,
): asserts value is WebRefreshResponse {
  if (
    typeof value !== "object" ||
    value === null ||
    !("status" in value) ||
    !("review" in value) ||
    (value.status !== "current" && value.status !== "pending") ||
    (value.status === "current" && value.review !== null) ||
    (value.status === "pending" &&
      (typeof value.review !== "object" || value.review === null))
  ) {
    throw new Error("invalid refresh contract fixture");
  }
}

describe("Python web contract fixtures", () => {
  it("narrows current and pending refresh results by their discriminator", () => {
    assertRefreshResponse(contracts.refresh_current);
    assertRefreshResponse(contracts.refresh_pending);

    if (contracts.refresh_current.status === "current") {
      expect(contracts.refresh_current.review).toBeNull();
      expect(contracts.refresh_current.answer.markdown).toContain(
        "Agent tools",
      );
    }
    if (contracts.refresh_pending.status === "pending") {
      expect(contracts.refresh_pending.review.review_id).toHaveLength(32);
      expect(contracts.refresh_pending.concept_id).toBe("syntheses/agents");
    }
  });
});
