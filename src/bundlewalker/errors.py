# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from bundlewalker.backups import VerifiedBackup


class BundleWalkerError(Exception):
    exit_code: ClassVar[int] = 1


class UsageError(BundleWalkerError):
    exit_code: ClassVar[int] = 2


class ConfigurationError(UsageError):
    pass


class WorkspaceCompatibilityError(ConfigurationError):
    def __init__(self, status: str) -> None:
        self.status = status
        super().__init__(f"workspace is not current: {status}")


class WorkspaceError(BundleWalkerError):
    pass


class BackupError(BundleWalkerError):
    pass


class BackupVerificationError(BackupError):
    pass


class RestoreTargetError(UsageError):
    pass


class MigrationUnavailableError(UsageError):
    pass


class MigrationExecutionError(BundleWalkerError):
    def __init__(
        self,
        message: str,
        *,
        backup: VerifiedBackup | None,
    ) -> None:
        self.backup = backup
        super().__init__(message)


class OkfError(BundleWalkerError):
    pass


class ChangeSetError(BundleWalkerError):
    pass


class AgentRunError(BundleWalkerError):
    pass


class TransactionError(BundleWalkerError):
    pass


class ReviewPendingError(TransactionError):
    def __init__(self, review_id: str) -> None:
        self.review_id = review_id
        super().__init__(f"workspace already has a pending review: {review_id}")


class ReviewNotFoundError(TransactionError):
    pass


class ReviewMismatchError(TransactionError):
    pass


class ReviewStaleError(TransactionError):
    pass
