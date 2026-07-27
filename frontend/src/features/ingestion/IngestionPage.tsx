// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import type { DragEvent, FormEvent } from "react";
import { useNavigate } from "react-router";

import { queryKeys, usePrepareIngestion } from "../../api/queries";
import type { WebIngestionResponse } from "../../api/types";
import { OperationProgress } from "../../components/OperationProgress";
import { RequestError } from "../../components/RequestError";

const MAX_SOURCE_NAME_CHARACTERS = 255;
const MAX_SOURCE_CHARACTERS = 1_000_000;
const MAX_SOURCE_BYTES = 4_000_000;
const MAX_MODEL_CHARACTERS = 255;

type SourceMode = "paste" | "file";

export function IngestionPage() {
  const [mode, setMode] = useState<SourceMode>("paste");
  const [sourceName, setSourceName] = useState("pasted-notes.md");
  const [content, setContent] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [model, setModel] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const validationErrorRef = useRef<HTMLParagraphElement>(null);
  const prepare = usePrepareIngestion();
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  useEffect(() => {
    if (validationError !== null) validationErrorRef.current?.focus();
  }, [validationError]);

  function chooseMode(nextMode: SourceMode) {
    setMode(nextMode);
    setValidationError(null);
    prepare.reset();
  }

  function chooseFile(files: FileList | readonly File[]) {
    if (files.length !== 1) {
      setSelectedFile(null);
      setValidationError("Choose exactly one Markdown or text file.");
      return;
    }
    setSelectedFile(files[0] ?? null);
    setValidationError(null);
    prepare.reset();
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (prepare.isPending) return;
    setValidationError(null);

    let activeName = sourceName;
    let activeContent = content;
    if (mode === "file") {
      if (selectedFile === null) {
        setValidationError("Choose one Markdown or text file.");
        return;
      }
      activeName = selectedFile.name;
      const fileError = validateFileBeforeRead(selectedFile);
      if (fileError !== null) {
        setValidationError(fileError);
        return;
      }
      activeContent = await selectedFile.text();
    }

    const inputError = validateSource(activeName, activeContent);
    if (inputError !== null) {
      setValidationError(inputError);
      return;
    }

    let result: WebIngestionResponse;
    try {
      result = await prepare.mutateAsync({
        source_name: activeName,
        content: activeContent,
        model: model.trim() || null,
      });
    } catch {
      return;
    }
    if (result.status === "pending") {
      await queryClient.invalidateQueries({ queryKey: queryKeys.workspace });
      navigate(`/review/${result.review.review_id}`);
    }
  }

  function dropFile(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    chooseFile(event.dataTransfer.files);
  }

  const status = prepare.isPending
    ? "Preparing ingestion…"
    : prepare.isError
      ? "Ingestion preparation failed"
      : prepare.data?.status === "duplicate"
        ? "No changes prepared"
        : "";

  return (
    <section className="knowledge-workbench ingestion-workbench">
      <h1>New ingestion</h1>
      <p>
        Paste text or choose one UTF-8 <code>.md</code> or <code>.txt</code>{" "}
        file. Content is limited to 1,000,000 characters and 4,000,000 UTF-8
        bytes.
      </p>
      <form onSubmit={(event) => void submit(event)}>
        <fieldset>
          <legend>Source input</legend>
          <label>
            <input
              type="radio"
              name="source-mode"
              checked={mode === "paste"}
              onChange={() => {
                chooseMode("paste");
              }}
            />
            Paste text
          </label>
          <label>
            <input
              type="radio"
              name="source-mode"
              checked={mode === "file"}
              onChange={() => {
                chooseMode("file");
              }}
            />
            Choose a file
          </label>
        </fieldset>

        {mode === "paste" ? (
          <>
            <label htmlFor="ingestion-source-name">Source filename</label>
            <input
              id="ingestion-source-name"
              value={sourceName}
              required
              maxLength={MAX_SOURCE_NAME_CHARACTERS}
              aria-describedby="ingestion-name-help"
              onChange={(event) => {
                setSourceName(event.currentTarget.value);
              }}
            />
            <span id="ingestion-name-help">
              Use one simple filename ending in .md or .txt.
            </span>
            <label htmlFor="ingestion-content">Content</label>
            <textarea
              id="ingestion-content"
              value={content}
              required
              maxLength={MAX_SOURCE_CHARACTERS}
              onChange={(event) => {
                setContent(event.currentTarget.value);
              }}
            />
          </>
        ) : (
          <div
            className="file-drop-target"
            data-testid="file-drop-target"
            onDragOver={(event) => {
              event.preventDefault();
            }}
            onDrop={dropFile}
          >
            <label htmlFor="ingestion-file">Source file</label>
            <input
              id="ingestion-file"
              type="file"
              accept=".md,.txt"
              onChange={(event) => {
                chooseFile(event.currentTarget.files ?? []);
              }}
            />
            <p>
              {selectedFile
                ? `Selected: ${selectedFile.name}`
                : "Choose a file or drop one here."}
            </p>
          </div>
        )}

        <label htmlFor="ingestion-model">Model (optional)</label>
        <input
          id="ingestion-model"
          value={model}
          maxLength={MAX_MODEL_CHARACTERS}
          onChange={(event) => {
            setModel(event.currentTarget.value);
          }}
        />
        <button type="submit" disabled={prepare.isPending}>
          Prepare ingestion
        </button>
      </form>

      <OperationProgress message={status} />
      {validationError ? (
        <p ref={validationErrorRef} role="alert" tabIndex={-1}>
          {validationError}
        </p>
      ) : null}
      {prepare.error ? <RequestError error={prepare.error} /> : null}
      {prepare.data?.status === "duplicate" ? (
        <p>This source is already in the knowledge base.</p>
      ) : null}
    </section>
  );
}

function validateFileBeforeRead(file: File): string | null {
  const nameError = validateSourceName(file.name);
  if (nameError !== null) return nameError;
  if (file.size > MAX_SOURCE_BYTES) {
    return "The selected file exceeds the 4,000,000-byte limit.";
  }
  return null;
}

function validateSource(sourceName: string, content: string): string | null {
  const nameError = validateSourceName(sourceName);
  if (nameError !== null) return nameError;
  if (content.trim().length === 0) return "Source content must not be blank.";
  if (content.length > MAX_SOURCE_CHARACTERS) {
    return "Source content exceeds the 1,000,000-character limit.";
  }
  if (new TextEncoder().encode(content).byteLength > MAX_SOURCE_BYTES) {
    return "Source content exceeds the 4,000,000-byte limit.";
  }
  return null;
}

function validateSourceName(sourceName: string): string | null {
  if (
    sourceName.length === 0 ||
    sourceName.length > MAX_SOURCE_NAME_CHARACTERS ||
    sourceName === "." ||
    sourceName === ".." ||
    sourceName.includes("/") ||
    sourceName.includes("\\") ||
    sourceName.includes(":") ||
    /[\u0000-\u001f\u007f-\u009f]/u.test(sourceName)
  ) {
    return "Use one safe source filename.";
  }
  const suffix = sourceName.endsWith(".md")
    ? ".md"
    : sourceName.endsWith(".txt")
      ? ".txt"
      : null;
  if (suffix === null) return "Source filename must end in .md or .txt.";
  if (sourceName.slice(0, -suffix.length).trim().length === 0) {
    return "Source filename must contain a usable name before its suffix.";
  }
  return null;
}
