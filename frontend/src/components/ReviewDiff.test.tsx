// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";

import { ReviewDiff } from "./ReviewDiff";

const completeDiff =
  "--- wiki/topics/agents.md\n" +
  "+++ wiki/topics/agents.md\n" +
  "@@ -1,3 +1,3 @@\n" +
  " # Agents\n" +
  "-Agents can use tools.\n" +
  "+Agents use reviewed tools.\n";

function setNarrowViewport(narrow: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      matches: narrow && query === "(max-width: 48rem)",
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

test("renders the complete persisted evidence with visible added and removed labels", () => {
  setNarrowViewport(false);
  render(<ReviewDiff diff={completeDiff} />);

  expect(
    screen.getByRole("region", { name: "Complete unified diff evidence" })
      .textContent,
  ).toBe(completeDiff);
  expect(
    screen.getByText("Removed", { selector: ".diff-line-label" }),
  ).toBeTruthy();
  expect(
    screen.getByText("Added", { selector: ".diff-line-label" }),
  ).toBeTruthy();
  expect(screen.getByText("-Agents can use tools.")).toBeTruthy();
  expect(screen.getByText("+Agents use reviewed tools.")).toBeTruthy();
  expect(screen.getByTestId("review-diff").dataset.mode).toBe("split");
  expect(
    screen.getByText("-Agents can use tools.").closest(".diff-split-row"),
  ).toBe(
    screen.getByText("+Agents use reviewed tools.").closest(".diff-split-row"),
  );
  expect(
    screen.getByRole("button", { name: "Switch to unified diff" }),
  ).toBeTruthy();
});

test("defaults narrow viewports to unified and supports a manual mode toggle", async () => {
  setNarrowViewport(true);
  const user = userEvent.setup();
  render(<ReviewDiff diff={completeDiff} />);

  expect(screen.getByTestId("review-diff").dataset.mode).toBe("unified");
  await user.click(
    screen.getByRole("button", { name: "Switch to split diff" }),
  );

  expect(screen.getByTestId("review-diff").dataset.mode).toBe("split");
  expect(
    screen.getByRole("button", { name: "Switch to unified diff" }),
  ).toBeTruthy();
});

test("falls back to a labeled preformatted complete diff when parsing fails", () => {
  setNarrowViewport(false);
  const malformed = "This persisted evidence is not a unified diff.\n+Keep it.";
  render(<ReviewDiff diff={malformed} />);

  expect(screen.getByText("Unified diff (presentation fallback)")).toBeTruthy();
  expect(
    screen.getByRole("region", { name: "Complete unified diff evidence" })
      .textContent,
  ).toBe(malformed);
  expect(screen.queryByTestId("review-diff")).toBeNull();
});
