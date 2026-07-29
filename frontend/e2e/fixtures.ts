// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { readFileSync } from "node:fs";

import { test as base } from "@playwright/test";
import type { BrowserContext, Page } from "@playwright/test";

interface SmokeState {
  readonly bootstrap_url: string;
  readonly origin: string;
  readonly workspace: string;
}

interface AuthenticatedBrowser {
  readonly context: BrowserContext;
  readonly redirectedUrl: string;
}

const statePath = process.env["BUNDLEWALKER_WEB_SMOKE_STATE"];
if (!statePath) {
  throw new Error(
    "BUNDLEWALKER_WEB_SMOKE_STATE is required; run through scripts/run_web_smoke.py",
  );
}

export const smokeState = JSON.parse(
  readFileSync(statePath, "utf8"),
) as SmokeState;

export const test = base.extend<
  { page: Page },
  { authenticatedBrowser: AuthenticatedBrowser }
>({
  authenticatedBrowser: [
    async ({ browser }, provide) => {
      const context = await browser.newContext({ baseURL: smokeState.origin });
      const bootstrapPage = await context.newPage();
      await bootstrapPage.goto(smokeState.bootstrap_url);
      const redirectedUrl = bootstrapPage.url();
      await bootstrapPage.close();
      await provide({ context, redirectedUrl });
      await context.close();
    },
    { scope: "worker" },
  ],
  page: async ({ authenticatedBrowser }, provide) => {
    const page = await authenticatedBrowser.context.newPage();
    page.on("dialog", (dialog) => void dialog.accept());
    await page.goto("/browse");
    await provide(page);
    await page.close();
  },
});

test.afterEach(async ({ page }) => {
  const workspace = await page.request.get("/api/v1/workspace");
  if (!workspace.ok()) return;
  const body = (await workspace.json()) as {
    readonly csrf_token: string;
    readonly pending_review: { readonly review_id: string } | null;
  };
  if (body.pending_review === null) return;
  await page.request.post(
    `/api/v1/reviews/${encodeURIComponent(body.pending_review.review_id)}/discard`,
    {
      data: {},
      headers: {
        Origin: smokeState.origin,
        "X-BundleWalker-CSRF": body.csrf_token,
      },
    },
  );
});

export { expect } from "@playwright/test";
