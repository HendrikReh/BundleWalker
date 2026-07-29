// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { useState } from "react";

type DiffMode = "split" | "unified";
type DiffLineKind = "added" | "removed" | "context" | "metadata";

interface DiffLine {
  readonly kind: DiffLineKind;
  readonly text: string;
}

interface DiffSplitRow {
  readonly left: DiffLine | null;
  readonly right: DiffLine | null;
}

export function ReviewDiff({ diff }: { readonly diff: string }) {
  const [mode, setMode] = useState<DiffMode>(() =>
    typeof window.matchMedia === "function" &&
    window.matchMedia("(max-width: 48rem)").matches
      ? "unified"
      : "split",
  );
  const lines = parseUnifiedDiff(diff);

  if (lines === null) {
    return (
      <section className="diff-fallback">
        <h2>Unified diff (presentation fallback)</h2>
        <pre
          aria-label="Complete unified diff evidence"
          role="region"
          tabIndex={0}
        >
          {diff}
        </pre>
      </section>
    );
  }

  return (
    <section aria-label="Proposal diff">
      <div className="diff-toolbar">
        <h2>Exact proposal diff</h2>
        <button
          type="button"
          onClick={() => {
            setMode(mode === "split" ? "unified" : "split");
          }}
        >
          Switch to {mode === "split" ? "unified" : "split"} diff
        </button>
      </div>
      <pre
        className="visually-hidden"
        aria-label="Complete unified diff evidence"
        role="region"
      >
        {diff}
      </pre>
      <div
        className={`review-diff review-diff--${mode}`}
        data-testid="review-diff"
        data-mode={mode}
      >
        {mode === "unified"
          ? lines.map((line, index) => (
              <UnifiedLine key={`${index}-${line.text}`} line={line} />
            ))
          : buildSplitRows(lines).map((row, index) => (
              <SplitRow
                key={`${index}-${row.left?.text ?? ""}-${row.right?.text ?? ""}`}
                row={row}
              />
            ))}
      </div>
    </section>
  );
}

function UnifiedLine({ line }: { readonly line: DiffLine }) {
  return (
    <div className={`diff-line diff-line--${line.kind}`}>
      <LineLabel kind={line.kind} />
      <code>{line.text}</code>
    </div>
  );
}

function SplitRow({ row }: { readonly row: DiffSplitRow }) {
  return (
    <div className="diff-split-row">
      {row.left === null ? (
        <div aria-hidden="true" />
      ) : (
        <SplitCell line={row.left} />
      )}
      {row.right === null ? (
        <div aria-hidden="true" />
      ) : (
        <SplitCell
          line={row.right}
          duplicate={row.left?.text === row.right.text}
        />
      )}
    </div>
  );
}

function SplitCell({
  line,
  duplicate = false,
}: {
  readonly line: DiffLine;
  readonly duplicate?: boolean;
}) {
  return (
    <div
      className={`diff-line diff-line--${line.kind}`}
      aria-hidden={duplicate || undefined}
    >
      {duplicate ? <span aria-hidden="true" /> : <LineLabel kind={line.kind} />}
      <code>{line.text}</code>
    </div>
  );
}

function LineLabel({ kind }: { readonly kind: DiffLineKind }) {
  if (kind === "added") {
    return <span className="diff-line-label">Added</span>;
  }
  if (kind === "removed") {
    return <span className="diff-line-label">Removed</span>;
  }
  return <span className="visually-hidden">{kind}</span>;
}

function parseUnifiedDiff(diff: string): readonly DiffLine[] | null {
  const rawLines = diff.endsWith("\n")
    ? diff.slice(0, -1).split("\n")
    : diff.split("\n");
  if (rawLines.length < 3) return null;

  let sawFileHeader = false;
  let sawHunk = false;
  const lines: DiffLine[] = [];
  for (let index = 0; index < rawLines.length; index += 1) {
    const text = rawLines[index] ?? "";
    if (text.startsWith("--- ")) {
      if (!(rawLines[index + 1] ?? "").startsWith("+++ ")) return null;
      sawFileHeader = true;
      lines.push({ kind: "metadata", text });
      index += 1;
      lines.push({ kind: "metadata", text: rawLines[index] ?? "" });
      continue;
    }
    if (text.startsWith("@@ ")) {
      if (!sawFileHeader) return null;
      sawHunk = true;
      lines.push({ kind: "metadata", text });
      continue;
    }
    if (!sawHunk) return null;
    if (text.startsWith("+")) {
      lines.push({ kind: "added", text });
    } else if (text.startsWith("-")) {
      lines.push({ kind: "removed", text });
    } else if (text.startsWith(" ") || text === "") {
      lines.push({ kind: "context", text });
    } else if (text === "\\ No newline at end of file") {
      lines.push({ kind: "metadata", text });
    } else {
      return null;
    }
  }
  return sawFileHeader && sawHunk ? lines : null;
}

function buildSplitRows(lines: readonly DiffLine[]): readonly DiffSplitRow[] {
  const rows: DiffSplitRow[] = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (line === undefined) break;
    if (line.kind !== "removed" && line.kind !== "added") {
      rows.push({ left: line, right: line });
      index += 1;
      continue;
    }

    const removed: DiffLine[] = [];
    while (true) {
      const candidate = lines[index];
      if (candidate?.kind !== "removed") break;
      removed.push(candidate);
      index += 1;
    }
    const added: DiffLine[] = [];
    while (true) {
      const candidate = lines[index];
      if (candidate?.kind !== "added") break;
      added.push(candidate);
      index += 1;
    }
    const rowCount = Math.max(removed.length, added.length);
    for (let offset = 0; offset < rowCount; offset += 1) {
      rows.push({
        left: removed[offset] ?? null,
        right: added[offset] ?? null,
      });
    }
  }
  return rows;
}
