from typing import ClassVar


class BundleWalkerError(Exception):
    exit_code: ClassVar[int] = 1


class UsageError(BundleWalkerError):
    exit_code: ClassVar[int] = 2


class ConfigurationError(UsageError):
    pass


class WorkspaceError(BundleWalkerError):
    pass


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
