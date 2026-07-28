// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

export function encodeConceptRoute(conceptId: string): string {
  return conceptId
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
}
