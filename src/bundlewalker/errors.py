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
