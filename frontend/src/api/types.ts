// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

export type ReviewKind = "ingestion" | "synthesis" | "refresh";
export type ReviewStatus = "pending" | "stale";
export type FindingOrigin = "deterministic" | "semantic";
export type Severity = "error" | "warning" | "info";

export interface WebPendingReviewSummary {
  readonly review_id: string;
  readonly kind: ReviewKind;
  readonly status: ReviewStatus;
  readonly summary: string;
}

export interface WebWorkspaceResponse {
  readonly display_name: string;
  readonly config_version: number;
  readonly concept_counts: Readonly<Record<string, number>>;
  readonly pending_review: WebPendingReviewSummary | null;
  readonly csrf_token: string;
}

export interface WebConceptSummary {
  readonly concept_id: string;
  readonly type: string;
  readonly title: string;
  readonly description: string;
  readonly tags: readonly string[];
}

export interface WebConceptPageResponse {
  readonly items: readonly WebConceptSummary[];
  readonly next_cursor: string | null;
}

export interface WebConceptResponse extends WebConceptSummary {
  readonly markdown: string;
  readonly digest: string;
}

export interface WebSearchResponse {
  readonly items: readonly WebConceptSummary[];
}

export interface WebAskRequest {
  readonly question: string;
  readonly model?: string | null;
}

export interface WebCitation {
  readonly number: number;
  readonly concept_id: string;
}

export interface WebAnswerResponse {
  readonly title: string;
  readonly markdown: string;
  readonly citations: readonly WebCitation[];
}

export interface WebLintRequest {
  readonly semantic?: boolean;
  readonly model?: string | null;
}

export interface WebLintFinding {
  readonly origin: FindingOrigin;
  readonly severity: Severity;
  readonly code: string;
  readonly message: string;
  readonly path: string | null;
  readonly evidence_paths: readonly string[];
  readonly remediation: string | null;
}

export interface WebLintResponse {
  readonly findings: readonly WebLintFinding[];
  readonly deterministic_has_errors: boolean;
}

export interface WebIngestionRequest {
  readonly source_name: string;
  readonly content: string;
  readonly model?: string | null;
}

export interface WebReviewResponse {
  readonly review_id: string;
  readonly kind: ReviewKind;
  readonly status: ReviewStatus;
  readonly summary: string;
  readonly diff: string;
  readonly changed_paths: readonly string[];
  readonly created_at: string;
}

export interface WebDuplicateIngestionResponse {
  readonly status: "duplicate";
  readonly review: null;
}

export interface WebPendingIngestionResponse {
  readonly status: "pending";
  readonly review: WebReviewResponse;
}

export type WebIngestionResponse =
  WebDuplicateIngestionResponse | WebPendingIngestionResponse;

export type WebSynthesisRequest = WebAskRequest;

export interface WebSynthesisResponse {
  readonly answer: WebAnswerResponse;
  readonly review: WebReviewResponse;
}

export interface WebRefreshRequest {
  readonly instruction: string;
  readonly concept_id: string;
  readonly model?: string | null;
}

interface WebRefreshResponseBase {
  readonly concept_id: string;
  readonly answer: WebAnswerResponse;
}

export interface WebCurrentRefreshResponse extends WebRefreshResponseBase {
  readonly status: "current";
  readonly review: null;
}

export interface WebPendingRefreshResponse extends WebRefreshResponseBase {
  readonly status: "pending";
  readonly review: WebReviewResponse;
}

export type WebRefreshResponse =
  WebCurrentRefreshResponse | WebPendingRefreshResponse;

export interface WebMutationResponse {
  readonly review_id: string;
  readonly status: "applied" | "discarded";
}

export interface WebErrorDetail {
  readonly code: string;
  readonly message: string;
  readonly retryable: boolean;
  readonly review_id: string | null;
  readonly diagnostic_id: string | null;
}

export interface WebErrorResponse {
  readonly error: WebErrorDetail;
}
