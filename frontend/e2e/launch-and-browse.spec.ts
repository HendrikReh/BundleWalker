// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import AxeBuilder from "@axe-core/playwright";

import { expect, test } from "./fixtures";

test("exchanges the bootstrap secret and opens a clean Browse workbench", async ({
  authenticatedBrowser,
  page,
}) => {
  const redirected = new URL(authenticatedBrowser.redirectedUrl);
  expect(redirected.pathname).toBe("/browse");
  expect(redirected.search).toBe("");
  await expect(
    page.getByRole("heading", { name: "Browse concepts", level: 1 }),
  ).toBeFocused();
  await expect(page.getByRole("link", { name: "Agents" })).toBeVisible();

  const skipLink = page.getByRole("link", { name: "Skip to main content" });
  await skipLink.focus();
  await expect
    .poll(() =>
      skipLink.evaluate(
        (element) => getComputedStyle(element).outlineStyle !== "none",
      ),
    )
    .toBe(true);

  await page.emulateMedia({ reducedMotion: "reduce" });
  const reducedDuration = await skipLink.evaluate((element) =>
    Number.parseFloat(getComputedStyle(element).transitionDuration),
  );
  expect(reducedDuration).toBeLessThanOrEqual(0.00001);

  const scan = await new AxeBuilder({ page }).analyze();
  expect(
    scan.violations.filter(
      ({ impact }) => impact === "serious" || impact === "critical",
    ),
  ).toEqual([]);
});

test("searches and reads one hierarchical concept", async ({ page }) => {
  await page.getByRole("searchbox", { name: "Search concepts" }).fill("agents");
  await page.getByRole("button", { name: "Search" }).click();
  await page.getByRole("link", { name: "Agents" }).click();

  await expect(
    page.getByRole("heading", { name: "Agents", level: 1 }),
  ).toBeFocused();
  await expect(page.getByText("Agents can use tools.")).toBeVisible();
});

test("runs deterministic Ask and lint without provider credentials", async ({
  page,
}) => {
  await page.getByRole("link", { name: "Ask" }).click();
  await page
    .getByRole("textbox", { name: "Question" })
    .fill("What do agents use?");
  await page
    .getByRole("textbox", { name: "Model (optional)" })
    .fill("test:model");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Answer ready");
  await expect(page.getByText("Agents can use tools")).toBeVisible();

  await page.getByRole("link", { name: "Lint" }).click();
  await page.getByRole("button", { name: "Run lint" }).click();
  await expect(page.getByRole("status")).toContainText("Lint complete");
  await expect(page.getByText(/Severity:/)).toBeVisible();
});
