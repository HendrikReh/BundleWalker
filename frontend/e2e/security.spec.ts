// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { request } from "@playwright/test";

import { expect, smokeState, test } from "./fixtures";

test("rejects unauthenticated and wrong-origin API requests", async ({
  page,
}) => {
  const unauthenticated = await request.newContext({
    baseURL: smokeState.origin,
  });
  const rejected = await unauthenticated.get("/api/v1/workspace");
  expect(rejected.status()).toBe(403);
  await unauthenticated.dispose();

  const workspace = await page.request.get("/api/v1/workspace");
  expect(workspace.ok()).toBe(true);
  const body = (await workspace.json()) as { readonly csrf_token: string };
  const wrongOrigin = await page.request.post("/api/v1/ask", {
    data: { question: "What do agents use?", model: "test:model" },
    headers: {
      Origin: "http://127.0.0.1:9",
      "X-BundleWalker-CSRF": body.csrf_token,
    },
  });
  expect(wrongOrigin.status()).toBe(403);
});
