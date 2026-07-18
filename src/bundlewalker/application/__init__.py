# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

"""Stable adapter-neutral application contracts and public errors."""

from bundlewalker.application.contracts import (
    MAX_CONCEPT_PAGE_SIZE,
    MAX_INLINE_SOURCE_CHARACTERS,
    MAX_QUESTION_CHARACTERS,
    MAX_SEARCH_CHARACTERS,
    MAX_SOURCE_NAME_CHARACTERS,
    AnswerResult,
    BackupResult,
    CompatibilityResult,
    ConceptContent,
    ConceptPage,
    ConceptSearchResult,
    ConceptSummaryResult,
    IngestionResult,
    InlineSource,
    LintResult,
    MutationResult,
    PendingReviewResult,
    PendingReviewSummary,
    RefreshResult,
    RestoreResult,
    ReviewResult,
    SynthesisResult,
    UpgradeResult,
    WorkspaceStatus,
)
from bundlewalker.application.errors import (
    ApplicationError,
    ApplicationErrorCode,
    translate_error,
)
from bundlewalker.application.facade import ApplicationDependencies, WorkspaceApplication
from bundlewalker.application.lifecycle import LifecycleApplication, LifecycleDependencies

__all__ = [
    "MAX_CONCEPT_PAGE_SIZE",
    "MAX_INLINE_SOURCE_CHARACTERS",
    "MAX_QUESTION_CHARACTERS",
    "MAX_SEARCH_CHARACTERS",
    "MAX_SOURCE_NAME_CHARACTERS",
    "AnswerResult",
    "ApplicationDependencies",
    "ApplicationError",
    "ApplicationErrorCode",
    "BackupResult",
    "CompatibilityResult",
    "ConceptContent",
    "ConceptPage",
    "ConceptSearchResult",
    "ConceptSummaryResult",
    "IngestionResult",
    "InlineSource",
    "LifecycleApplication",
    "LifecycleDependencies",
    "LintResult",
    "MutationResult",
    "PendingReviewResult",
    "PendingReviewSummary",
    "RefreshResult",
    "RestoreResult",
    "ReviewResult",
    "SynthesisResult",
    "UpgradeResult",
    "WorkspaceApplication",
    "WorkspaceStatus",
    "translate_error",
]
