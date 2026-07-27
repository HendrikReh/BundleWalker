// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { execFileSync } from "node:child_process";

import { expect, smokeState, test } from "./fixtures";

async function preparePaste(
  page: import("@playwright/test").Page,
  name: string,
) {
  await page.getByRole("link", { name: "New ingestion" }).click();
  await page.getByRole("textbox", { name: "Source filename" }).fill(name);
  await page
    .getByRole("textbox", { name: "Content" })
    .fill(`# Browser notes\n\nEvidence from ${name}.`);
  await page
    .getByRole("textbox", { name: "Model (optional)" })
    .fill("test:model");
  await page.getByRole("button", { name: "Prepare ingestion" }).click();
  await expect(
    page.getByRole("heading", { name: "Review proposal" }),
  ).toBeVisible();
}

test("prepares pasted and uploaded text, then applies and discards exact diffs", async ({
  page,
}) => {
  await preparePaste(page, "pasted-smoke.md");
  await expect(
    page.getByRole("region", { name: "Complete unified diff evidence" }),
  ).toContainText("The source contains browser evidence [1].");
  await expect(
    page.getByText(/sources\/.*-pasted-smoke\.md/).first(),
  ).toBeVisible();
  await page.getByRole("button", { name: "Apply proposal" }).click();
  await expect(
    page.getByRole("heading", { name: "Browse concepts" }),
  ).toBeVisible();

  await page.getByRole("link", { name: "New ingestion" }).click();
  await page.getByRole("radio", { name: "Choose a file" }).check();
  await page.getByLabel("Source file").setInputFiles({
    name: "uploaded-smoke.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Uploaded browser evidence."),
  });
  await page
    .getByRole("textbox", { name: "Model (optional)" })
    .fill("test:model");
  await page.getByRole("button", { name: "Prepare ingestion" }).click();
  await expect(
    page.getByRole("heading", { name: "Review proposal" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Discard proposal" }).click();
  await expect(
    page.getByRole("heading", { name: "Browse concepts" }),
  ).toBeVisible();
});

test("keeps synthesis and refresh result variants distinct", async ({
  page,
}) => {
  await page.getByRole("link", { name: "Ask" }).click();
  await page
    .getByRole("textbox", { name: "Question" })
    .fill("What do agents use?");
  await page
    .getByRole("textbox", { name: "Model (optional)" })
    .fill("test:model");
  await page.getByRole("button", { name: "Prepare synthesis" }).click();
  await expect(page.getByText("Synthesis proposal ready")).toBeVisible();
  await page
    .getByRole("link", { name: "Review the synthesis proposal" })
    .click();
  await page.getByRole("button", { name: "Discard proposal" }).click();

  await page.goto("/browse/syntheses/current-agent-framework");
  await page.getByRole("link", { name: "Prepare refresh" }).click();
  await page
    .getByRole("textbox", { name: "Refresh instruction" })
    .fill("Check current evidence");
  await page
    .getByRole("textbox", { name: "Model (optional)" })
    .fill("test:model");
  await page.getByRole("button", { name: "Prepare refresh" }).click();
  await expect(page.getByRole("status")).toContainText(
    "already current; no review was created",
  );

  await page.goto("/browse/syntheses/agent-framework");
  await page.getByRole("link", { name: "Prepare refresh" }).click();
  await page
    .getByRole("textbox", { name: "Refresh instruction" })
    .fill("Add current evidence");
  await page
    .getByRole("textbox", { name: "Model (optional)" })
    .fill("test:model");
  await page.getByRole("button", { name: "Prepare refresh" }).click();
  await expect(
    page.getByRole("heading", { name: "Review proposal" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Discard proposal" }).click();
});

test("opens a review prepared through MCP as the root default", async ({
  page,
}) => {
  const reviewId = execFileSync(
    process.env["BUNDLEWALKER_PYTHON"] ?? "python",
    [
      "../scripts/run_web_smoke.py",
      "--prepare-mcp-review",
      smokeState.workspace,
    ],
    { cwd: process.cwd(), stdio: "pipe" },
  )
    .toString()
    .trim();

  const rootResponse = await page.goto("/");

  expect(rootResponse?.status()).toBe(200);
  await expect(page).toHaveURL(`/review/${reviewId}`);
  await expect(
    page.getByRole("heading", { name: "Review proposal", level: 1 }),
  ).toBeFocused();
  await expect(
    page.getByText("Saved synthesis: MCP handoff", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText(reviewId, { exact: true })).toBeVisible();
  await expect(
    page.getByText("syntheses/mcp-handoff", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Discard proposal" }).click();
});

test("defaults exact diffs to unified mode in a narrow viewport", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await preparePaste(page, "narrow-smoke.md");

  await expect(page.getByTestId("review-diff")).toHaveAttribute(
    "data-mode",
    "unified",
  );
  await expect(page.getByText("Added", { exact: true }).first()).toBeVisible();
  await expect(
    page.getByRole("navigation", { name: "Explorer" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("button", { name: "Discard proposal" }).click();
});
