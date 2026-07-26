// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import type {
  WebAnswerResponse,
  WebConceptPageResponse,
  WebConceptResponse,
  WebConceptSummary,
  WebErrorDetail,
  WebIngestionRequest,
  WebIngestionResponse,
  WebLintRequest,
  WebLintResponse,
  WebReviewResponse,
  WebSearchResponse,
  WebWorkspaceResponse,
} from "./types";

const MAX_ERROR_BYTES = 65_536;

export class ApiError extends Error {
  readonly code: string;
  readonly retryable: boolean;
  readonly reviewId: string | null;
  readonly diagnosticId: string | null;

  constructor(detail: WebErrorDetail) {
    super(detail.message);
    this.name = "ApiError";
    this.code = detail.code;
    this.retryable = detail.retryable;
    this.reviewId = detail.review_id;
    this.diagnosticId = detail.diagnostic_id;
  }
}

export class ApiClient {
  #csrfToken: string | null = null;

  async workspace(): Promise<WebWorkspaceResponse> {
    const workspace = await this.#get("/api/v1/workspace", parseWorkspace);
    this.#csrfToken = workspace.csrf_token;
    return workspace;
  }

  async concepts(options: {
    readonly cursor?: string | null;
    readonly limit?: number;
  }): Promise<WebConceptPageResponse> {
    const query = new URLSearchParams();
    if (options.cursor) query.set("cursor", options.cursor);
    if (options.limit !== undefined) query.set("limit", String(options.limit));
    const suffix = query.size > 0 ? `?${query.toString()}` : "";
    return this.#get(`/api/v1/concepts${suffix}`, parseConceptPage);
  }

  async searchConcepts(options: {
    readonly query: string;
    readonly conceptType?: string;
    readonly limit?: number;
  }): Promise<WebSearchResponse> {
    const query = new URLSearchParams({ query: options.query });
    if (options.conceptType) query.set("type", options.conceptType);
    if (options.limit !== undefined) query.set("limit", String(options.limit));
    return this.#get(
      `/api/v1/concepts/search?${query.toString()}`,
      parseSearch,
    );
  }

  async concept(conceptId: string): Promise<WebConceptResponse> {
    const encodedId = conceptId
      .split("/")
      .map((segment) => encodeURIComponent(segment))
      .join("/");
    return this.#get(`/api/v1/concepts/${encodedId}`, parseConcept);
  }

  async ask(options: {
    readonly question: string;
    readonly model?: string | null;
  }): Promise<WebAnswerResponse> {
    return this.#post("/api/v1/ask", options, parseAnswer);
  }

  async lint(options: WebLintRequest): Promise<WebLintResponse> {
    return this.#post("/api/v1/lint", options, parseLint);
  }

  async prepareIngestion(
    options: WebIngestionRequest,
  ): Promise<WebIngestionResponse> {
    return this.#post("/api/v1/ingestions", options, parseIngestion);
  }

  async #get<T>(path: string, parse: (value: unknown) => T): Promise<T> {
    return this.#request(path, parse, false);
  }

  async #post<T>(
    path: string,
    body: unknown,
    parse: (value: unknown) => T,
  ): Promise<T> {
    return this.#request(path, parse, true, body);
  }

  async #request<T>(
    path: string,
    parse: (value: unknown) => T,
    stateChanging: boolean,
    body?: unknown,
  ): Promise<T> {
    if (!path.startsWith("/") || path.startsWith("//")) {
      throw new Error("API paths must be same-origin relative paths");
    }
    const headers = new Headers({ Accept: "application/json" });
    const init: RequestInit = { credentials: "same-origin", headers };
    if (stateChanging) {
      if (this.#csrfToken === null) {
        throw new Error("Workspace bootstrap is required before mutations");
      }
      headers.set("Content-Type", "application/json");
      headers.set("X-BundleWalker-CSRF", this.#csrfToken);
      init.method = "POST";
      init.body = JSON.stringify(body);
    }

    const response = await fetch(path, init);
    if (!response.ok) {
      const detail = await readBoundedError(response);
      throw new ApiError(
        detail ?? {
          code: "request_failed",
          message: "Request failed",
          retryable: false,
          review_id: null,
          diagnostic_id: null,
        },
      );
    }
    return parse(await response.json());
  }
}

async function readBoundedError(
  response: Response,
): Promise<WebErrorDetail | null> {
  const reader = response.body?.getReader();
  if (reader === undefined) return null;
  const chunks: Uint8Array[] = [];
  let size = 0;
  while (true) {
    const result = await reader.read();
    if (result.done) break;
    size += result.value.byteLength;
    if (size > MAX_ERROR_BYTES) {
      await reader.cancel();
      return null;
    }
    chunks.push(result.value);
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  try {
    const value: unknown = JSON.parse(new TextDecoder().decode(bytes));
    if (!isRecord(value) || !isRecord(value.error)) return null;
    return parseErrorDetail(value.error);
  } catch {
    return null;
  }
}

function parseWorkspace(value: unknown): WebWorkspaceResponse {
  const record = requireRecord(value);
  const counts = requireRecord(record.concept_counts);
  for (const count of Object.values(counts)) requireNumber(count);
  const pending = record.pending_review;
  if (pending !== null) {
    const review = requireRecord(pending);
    requireString(review.review_id);
    requireString(review.kind);
    requireString(review.status);
    requireString(review.summary);
  }
  return {
    display_name: requireString(record.display_name),
    config_version: requireNumber(record.config_version),
    concept_counts: counts as Readonly<Record<string, number>>,
    pending_review: pending as WebWorkspaceResponse["pending_review"],
    csrf_token: requireString(record.csrf_token),
  };
}

function parseConceptPage(value: unknown): WebConceptPageResponse {
  const record = requireRecord(value);
  const cursor = record.next_cursor;
  const parsedCursor = cursor === null ? null : requireString(cursor);
  return {
    items: requireArray(record.items).map(parseConceptSummary),
    next_cursor: parsedCursor,
  };
}

function parseSearch(value: unknown): WebSearchResponse {
  const record = requireRecord(value);
  return { items: requireArray(record.items).map(parseConceptSummary) };
}

function parseConcept(value: unknown): WebConceptResponse {
  const record = requireRecord(value);
  return {
    ...parseConceptSummary(record),
    markdown: requireString(record.markdown),
    digest: requireString(record.digest),
  };
}

function parseConceptSummary(value: unknown): WebConceptSummary {
  const record = requireRecord(value);
  return {
    concept_id: requireString(record.concept_id),
    type: requireString(record.type),
    title: requireString(record.title),
    description: requireString(record.description),
    tags: requireArray(record.tags).map(requireString),
  };
}

function parseAnswer(value: unknown): WebAnswerResponse {
  const record = requireRecord(value);
  return {
    title: requireString(record.title),
    markdown: requireString(record.markdown),
    citations: requireArray(record.citations).map((citation) => {
      const parsed = requireRecord(citation);
      return {
        number: requireNumber(parsed.number),
        concept_id: requireString(parsed.concept_id),
      };
    }),
  };
}

function parseLint(value: unknown): WebLintResponse {
  const record = requireRecord(value);
  return {
    findings: requireArray(record.findings).map((finding) => {
      const parsed = requireRecord(finding);
      const path = parsed.path;
      const remediation = parsed.remediation;
      const origin = requireString(parsed.origin);
      const severity = requireString(parsed.severity);
      if (origin !== "deterministic" && origin !== "semantic") {
        throw new Error("Invalid API response");
      }
      if (!["error", "warning", "info"].includes(severity)) {
        throw new Error("Invalid API response");
      }
      return {
        origin,
        severity: severity as "error" | "warning" | "info",
        code: requireString(parsed.code),
        message: requireString(parsed.message),
        path: path === null ? null : requireString(path),
        evidence_paths: requireArray(parsed.evidence_paths).map(requireString),
        remediation: remediation === null ? null : requireString(remediation),
      };
    }),
    deterministic_has_errors: requireBoolean(record.deterministic_has_errors),
  };
}

function parseIngestion(value: unknown): WebIngestionResponse {
  const record = requireRecord(value);
  if (record.status === "duplicate") {
    if (record.review !== null) throw new Error("Invalid API response");
    return { status: "duplicate", review: null };
  }
  if (record.status === "pending") {
    return { status: "pending", review: parseReview(record.review) };
  }
  throw new Error("Invalid API response");
}

function parseReview(value: unknown): WebReviewResponse {
  const record = requireRecord(value);
  const kind = requireString(record.kind);
  const status = requireString(record.status);
  if (kind !== "ingestion" && kind !== "synthesis" && kind !== "refresh") {
    throw new Error("Invalid API response");
  }
  if (status !== "pending" && status !== "stale") {
    throw new Error("Invalid API response");
  }
  return {
    review_id: requireString(record.review_id),
    kind,
    status,
    summary: requireString(record.summary),
    diff: requireString(record.diff),
    changed_paths: requireArray(record.changed_paths).map(requireString),
    created_at: requireString(record.created_at),
  };
}

function parseErrorDetail(
  value: Record<string, unknown>,
): WebErrorDetail | null {
  const reviewId = value.review_id;
  const diagnosticId = value.diagnostic_id;
  if (reviewId !== null && typeof reviewId !== "string") return null;
  if (diagnosticId !== null && typeof diagnosticId !== "string") return null;
  if (
    typeof value.code !== "string" ||
    typeof value.message !== "string" ||
    value.message.length > 2_000 ||
    typeof value.retryable !== "boolean"
  ) {
    return null;
  }
  return {
    code: value.code,
    message: value.message,
    retryable: value.retryable,
    review_id: reviewId,
    diagnostic_id: diagnosticId,
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requireRecord(value: unknown): Record<string, unknown> {
  if (!isRecord(value)) throw new Error("Invalid API response");
  return value;
}

function requireArray(value: unknown): readonly unknown[] {
  if (!Array.isArray(value)) throw new Error("Invalid API response");
  return value;
}

function requireString(value: unknown): string {
  if (typeof value !== "string") throw new Error("Invalid API response");
  return value;
}

function requireNumber(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error("Invalid API response");
  }
  return value;
}

function requireBoolean(value: unknown): boolean {
  if (typeof value !== "boolean") throw new Error("Invalid API response");
  return value;
}
