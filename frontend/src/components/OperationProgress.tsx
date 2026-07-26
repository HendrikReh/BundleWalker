// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

export function OperationProgress({ message }: { readonly message: string }) {
  return (
    <output className="operation-progress" role="status" aria-live="polite">
      {message}
    </output>
  );
}
