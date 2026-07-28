// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { expect, test } from "vitest";

import { encodeConceptRoute } from "./conceptRoute";

test("encodes each concept route segment without flattening the hierarchy", () => {
  expect(encodeConceptRoute("topics/agents")).toBe("topics/agents");
  expect(encodeConceptRoute("topics/agent tools")).toBe("topics/agent%20tools");
  expect(encodeConceptRoute("entities/a:b?c#d")).toBe("entities/a%3Ab%3Fc%23d");
});
