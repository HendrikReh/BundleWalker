from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import uuid
from collections.abc import Generator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal, cast

from bundlewalker.changes import ChangeValidationContext, build_prospective_wiki
from bundlewalker.domain import ChangeOperation, ChangeSet
from bundlewalker.errors import OkfError, TransactionError
from bundlewalker.okf.derived import tree_diff
from bundlewalker.okf.lint import has_errors, lint_bundle
from bundlewalker.okf.repository import OkfRepository
from bundlewalker.workspace import RawSource, Workspace

_SCHEMA_VERSION = 1
_TRANSACTIONS_PATH = PurePosixPath(".bundlewalker/transactions")
_MANIFEST_NAME = "manifest.json"
_IDENTITY_NAME = "identity.json"
_PROSPECTIVE_NAME = "prospective-wiki"
_BACKUP_NAME = "backup-wiki"
_VALIDATION_WORKSPACE_NAME = "validation-workspace"
_RAW_PAYLOAD_NAME = "raw-source"
_LOCK_NAME = "transaction.lock"
_QUARANTINE_PREFIX = ".retired-backup-"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_Phase = Literal["prepared", "raw-persisted", "swapping", "new-live"]


@dataclass(frozen=True, slots=True)
class PreparedTransaction:
    transaction_id: str
    workspace: Workspace
    transaction_dir: Path
    prospective_wiki: Path
    backup_wiki: Path
    change_set: ChangeSet
    raw_source: RawSource | None
    summary: str
    diff: str
    _identity: _Identity = field(init=False, repr=False, compare=False)

    @property
    def prospective_digest(self) -> str:
        return self._identity.prospective_digest

    @property
    def base_wiki_digest(self) -> str:
        return self._identity.base_wiki_digest


@dataclass(frozen=True, slots=True)
class _DraftRecord:
    path: str
    operation: ChangeOperation
    base_digest: str | None


@dataclass(frozen=True, slots=True)
class _Manifest:
    schema_version: int
    transaction_id: str
    phase: _Phase
    prospective_path: str
    backup_path: str
    raw_path: str | None
    raw_sha256: str | None
    summary: str
    drafts: tuple[_DraftRecord, ...]
    prospective_digest: str | None = None
    base_wiki_digest: str | None = None


@dataclass(frozen=True, slots=True)
class _Identity:
    base_wiki_digest: str
    prospective_digest: str


class _IncompleteManifestError(Exception):
    pass


class _ConcurrentLiveEditError(Exception):
    pass


def prepare_transaction(
    workspace: Workspace,
    change_set: ChangeSet,
    context: ChangeValidationContext,
    raw_source: RawSource | None,
    occurred_at: datetime,
) -> PreparedTransaction:
    """Build a reviewed wiki tree and durable journal without changing live knowledge."""
    _validate_source_pair(context, raw_source)
    _validate_configured_wiki(workspace)
    transactions_root = _ensure_transactions_root(workspace)
    transaction_id = uuid.uuid4().hex
    transaction_dir = transactions_root / transaction_id
    prospective_wiki = transaction_dir / _PROSPECTIVE_NAME
    backup_wiki = transaction_dir / _BACKUP_NAME
    validation_root = transaction_dir / _VALIDATION_WORKSPACE_NAME
    owns_transaction_dir = False

    try:
        transaction_dir.mkdir()
        owns_transaction_dir = True
        _sync_directory(transactions_root)
        validation_workspace = Workspace(root=validation_root, config=workspace.config)
        _stage_validation_workspace(workspace, validation_workspace, raw_source)
        build_prospective_wiki(
            validation_workspace,
            change_set,
            context,
            prospective_wiki,
            occurred_at,
        )
        diff = tree_diff(workspace.wiki_dir, prospective_wiki)
        prospective_digest = _tree_digest(prospective_wiki)
        base_wiki_digest = _tree_digest(validation_workspace.wiki_dir)
        manifest = _Manifest(
            schema_version=_SCHEMA_VERSION,
            transaction_id=transaction_id,
            phase="prepared",
            prospective_path=_workspace_relative(workspace, prospective_wiki),
            backup_path=_workspace_relative(workspace, backup_wiki),
            raw_path=(
                _validated_raw_relative(workspace, raw_source.stored_relative_path)
                if raw_source is not None
                else None
            ),
            raw_sha256=raw_source.sha256 if raw_source is not None else None,
            summary=change_set.summary,
            drafts=tuple(
                _DraftRecord(
                    path=_canonical_concept_id(draft.path),
                    operation=draft.operation,
                    base_digest=draft.base_digest,
                )
                for draft in change_set.drafts
            ),
            prospective_digest=prospective_digest,
            base_wiki_digest=base_wiki_digest,
        )
        _write_raw_payload(transaction_dir, raw_source)
        _remove_tree(validation_root)
        _write_identity(
            transaction_dir,
            _Identity(
                base_wiki_digest=base_wiki_digest,
                prospective_digest=prospective_digest,
            ),
        )
        _write_manifest(transaction_dir, manifest)
    except OSError as exc:
        if owns_transaction_dir:
            _remove_tree_if_safe(transaction_dir)
        raise TransactionError("could not prepare transaction staging") from exc
    except BaseException:
        if owns_transaction_dir:
            _remove_tree_if_safe(transaction_dir)
        raise

    prepared = PreparedTransaction(
        transaction_id=transaction_id,
        workspace=workspace,
        transaction_dir=transaction_dir,
        prospective_wiki=prospective_wiki,
        backup_wiki=backup_wiki,
        change_set=change_set,
        raw_source=raw_source,
        summary=change_set.summary,
        diff=diff,
    )
    object.__setattr__(
        prepared,
        "_identity",
        _Identity(
            base_wiki_digest=base_wiki_digest,
            prospective_digest=prospective_digest,
        ),
    )
    return prepared


def commit_transaction(prepared: PreparedTransaction) -> None:
    """Persist a prepared transaction and recover immediately from interrupted swaps."""
    with _workspace_transaction_lock(prepared.workspace):
        _commit_transaction_locked(prepared)


def _commit_transaction_locked(prepared: PreparedTransaction) -> None:
    workspace = prepared.workspace
    manifest = _load_manifest(workspace, prepared.transaction_dir)
    prospective, backup = _manifest_paths(workspace, prepared.transaction_dir, manifest)
    _validate_prepared_handle(prepared, manifest, prospective, backup)
    if manifest.phase != "prepared":
        raise TransactionError(f"transaction is not prepared: {manifest.phase}")

    _validate_configured_wiki(workspace)
    _verify_prospective(
        prospective,
        workspace,
        prepared.prospective_digest,
        lint=False,
    )
    _revalidate_operations(workspace, manifest.drafts)
    _verify_live_base(workspace, prepared.transaction_dir, manifest)
    if backup.exists() or backup.is_symlink():
        raise TransactionError(f"transaction backup already exists: {backup}")
    if workspace.wiki_dir.is_symlink() or not workspace.wiki_dir.is_dir():
        raise TransactionError("live wiki is not a regular directory")
    _persist_raw_source(
        workspace,
        prepared.transaction_dir,
        prepared.raw_source,
        manifest,
    )
    manifest = replace(manifest, phase="raw-persisted")
    _write_manifest(prepared.transaction_dir, manifest)
    _verify_prospective(
        prospective,
        workspace,
        prepared.prospective_digest,
        lint=True,
    )
    _sync_tree(prospective)

    manifest = replace(manifest, phase="swapping")
    _write_manifest(prepared.transaction_dir, manifest)
    try:
        _rename_workspace_entry(workspace, workspace.wiki_dir, backup)
        _sync_tree(backup)
        actual_base = _materialized_tree_digest(backup, prepared.transaction_dir)
        if actual_base != prepared.base_wiki_digest:
            _restore_concurrent_backup(workspace, prepared.transaction_dir, backup)
            raise _ConcurrentLiveEditError("live wiki changed during swap")
        _rename_workspace_entry(workspace, prospective, workspace.wiki_dir)
        _sync_tree(workspace.wiki_dir)
        manifest = replace(manifest, phase="new-live")
        _write_manifest(prepared.transaction_dir, manifest)
        _verify_prospective(
            workspace.wiki_dir,
            workspace,
            prepared.prospective_digest,
            lint=True,
        )
        _sync_tree(backup)
        final_base = _materialized_tree_digest(backup, prepared.transaction_dir)
        if final_base != prepared.base_wiki_digest:
            _restore_concurrent_backup(workspace, prepared.transaction_dir, backup)
            raise _ConcurrentLiveEditError("live wiki changed during swap")
        _quarantine_backup_and_cleanup(
            workspace,
            prepared.transaction_dir,
            backup,
            prepared.base_wiki_digest,
        )
    except _ConcurrentLiveEditError as exc:
        raise TransactionError(str(exc)) from exc
    except (OSError, TransactionError) as exc:
        _recover_after_commit_error(workspace, prepared, exc)


def discard_transaction(prepared: PreparedTransaction) -> None:
    """Discard an unaccepted prepared transaction without touching live knowledge."""
    with _workspace_transaction_lock(prepared.workspace):
        _discard_transaction_locked(prepared)


def _discard_transaction_locked(prepared: PreparedTransaction) -> None:
    manifest = _load_manifest(prepared.workspace, prepared.transaction_dir)
    prospective, backup = _manifest_paths(
        prepared.workspace,
        prepared.transaction_dir,
        manifest,
    )
    _validate_prepared_handle(prepared, manifest, prospective, backup)
    if manifest.phase != "prepared":
        raise TransactionError(f"only a prepared transaction can be discarded: {manifest.phase}")
    _cleanup_transaction(prepared.workspace, prepared.transaction_dir)


def recover_transactions(workspace: Workspace) -> None:
    """Recover every interrupted transaction in stable order; safe to call repeatedly."""
    transactions_root = workspace.root.joinpath(*_TRANSACTIONS_PATH.parts)
    if not transactions_root.exists():
        return
    with _workspace_transaction_lock(workspace):
        _recover_transactions_locked(workspace, transactions_root)


def _recover_transactions_locked(workspace: Workspace, transactions_root: Path) -> None:
    if transactions_root.is_symlink() or not transactions_root.is_dir():
        raise TransactionError("transaction storage is not a regular directory")
    if not transactions_root.resolve(strict=False).is_relative_to(
        workspace.root.resolve(strict=False)
    ):
        raise TransactionError("transaction storage escapes workspace")

    try:
        transaction_dirs = sorted(transactions_root.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        raise TransactionError("could not inspect transaction storage") from exc
    for transaction_dir in transaction_dirs:
        if transaction_dir.is_symlink() or not transaction_dir.is_dir():
            raise TransactionError(f"invalid transaction entry: {transaction_dir.name}")
        try:
            _recover_transaction(workspace, transaction_dir)
        except OSError as exc:
            raise TransactionError(
                f"could not recover transaction: {transaction_dir.name}"
            ) from exc


def _recover_transaction(
    workspace: Workspace,
    transaction_dir: Path,
    expected_identity: _Identity | None = None,
) -> None:
    try:
        identity = _load_identity(transaction_dir)
    except _IncompleteManifestError:
        if expected_identity is None:
            _recover_without_identity(workspace, transaction_dir)
            return
        identity = expected_identity
    if expected_identity is not None and identity != expected_identity:
        raise TransactionError("transaction identity does not match the prepared review")

    try:
        manifest = _load_manifest(workspace, transaction_dir)
    except _IncompleteManifestError:
        _recover_known_topology(
            workspace,
            transaction_dir,
            None,
            transaction_dir / _PROSPECTIVE_NAME,
            transaction_dir / _BACKUP_NAME,
            identity,
        )
        return

    prospective, backup = _manifest_paths(workspace, transaction_dir, manifest)
    if (
        manifest.base_wiki_digest != identity.base_wiki_digest
        or manifest.prospective_digest != identity.prospective_digest
    ):
        raise TransactionError("manifest identities do not match transaction identity")
    _recover_known_topology(
        workspace,
        transaction_dir,
        manifest.phase,
        prospective,
        backup,
        identity,
    )


def _recover_known_topology(
    workspace: Workspace,
    transaction_dir: Path,
    phase: _Phase | None,
    prospective: Path,
    backup: Path,
    identity: _Identity,
) -> None:
    _validate_configured_wiki(workspace, allow_missing=True)
    backup = _recovery_backup_path(transaction_dir, backup)
    live_exists = _directory_exists(workspace.wiki_dir, "live wiki")
    backup_exists = _directory_exists(backup, "transaction backup")
    prospective_exists = _directory_exists(prospective, "prospective wiki")
    live_identity = (
        _classify_tree(workspace.wiki_dir, transaction_dir, identity) if live_exists else None
    )
    backup_identity = _classify_tree(backup, transaction_dir, identity) if backup_exists else None
    prospective_identity = (
        _classify_tree(prospective, transaction_dir, identity) if prospective_exists else None
    )

    if backup_exists:
        if backup_identity != "base":
            raise TransactionError("transaction backup wiki identity does not match reviewed base")
        if not live_exists:
            _restore_exact_backup(workspace, transaction_dir, backup, identity)
            return
        if live_identity == "new" and _new_tree_lints(workspace.wiki_dir, workspace):
            _cleanup_transaction(workspace, transaction_dir)
            return
        if live_identity == "base":
            _cleanup_transaction(workspace, transaction_dir)
            return
        _restore_exact_backup(workspace, transaction_dir, backup, identity)
        return

    if live_exists:
        if live_identity == "base":
            _cleanup_transaction(workspace, transaction_dir)
            return
        if live_identity == "new" and _new_tree_lints(workspace.wiki_dir, workspace):
            _cleanup_transaction(workspace, transaction_dir)
            return
        raise TransactionError("live wiki identity matches neither reviewed base nor new tree")

    if (
        phase in {"swapping", "new-live"}
        and prospective_identity == "new"
        and _new_tree_lints(prospective, workspace)
    ):
        _sync_tree(prospective)
        _rename_workspace_entry(workspace, prospective, workspace.wiki_dir)
        _sync_tree(workspace.wiki_dir)
        _cleanup_transaction(workspace, transaction_dir)
        return
    raise TransactionError("transaction has no authenticated recoverable wiki tree")


def _recovery_backup_path(transaction_dir: Path, backup: Path) -> Path:
    if not transaction_dir.exists():
        return backup
    try:
        quarantines = sorted(
            path for path in transaction_dir.iterdir() if path.name.startswith(_QUARANTINE_PREFIX)
        )
    except OSError as exc:
        raise TransactionError("could not inspect quarantined transaction backup") from exc
    if len(quarantines) > 1 or (quarantines and (backup.exists() or backup.is_symlink())):
        raise TransactionError("transaction has ambiguous backup topology")
    return quarantines[0] if quarantines else backup


def _recover_without_identity(workspace: Workspace, transaction_dir: Path) -> None:
    backup = transaction_dir / _BACKUP_NAME
    live_exists = _directory_exists(workspace.wiki_dir, "live wiki")
    backup_exists = _directory_exists(backup, "transaction backup")
    if backup_exists:
        raise TransactionError("incomplete transaction backup identity is unavailable")
    if not live_exists:
        raise TransactionError("incomplete transaction has no live wiki or authenticated backup")
    _cleanup_transaction(workspace, transaction_dir)


def _classify_tree(
    path: Path,
    transaction_dir: Path,
    identity: _Identity,
) -> Literal["base", "new", "unknown"]:
    try:
        digest = _materialized_tree_digest(path, transaction_dir)
    except TransactionError:
        return "unknown"
    if digest == identity.base_wiki_digest:
        return "base"
    if digest == identity.prospective_digest:
        return "new"
    return "unknown"


def _new_tree_lints(path: Path, workspace: Workspace) -> bool:
    return not has_errors(lint_bundle(path, workspace.root))


def _restore_exact_backup(
    workspace: Workspace,
    transaction_dir: Path,
    backup: Path,
    identity: _Identity,
) -> None:
    if not _tree_matches_identity(backup, identity.base_wiki_digest, transaction_dir):
        raise TransactionError("transaction backup wiki identity does not match reviewed base")
    _sync_tree(backup)
    if _validate_configured_wiki(workspace, allow_missing=True):
        _remove_live_wiki(workspace)
    _rename_workspace_entry(workspace, backup, workspace.wiki_dir)
    _sync_tree(workspace.wiki_dir)
    _cleanup_transaction(workspace, transaction_dir)


def _restore_concurrent_backup(
    workspace: Workspace,
    transaction_dir: Path,
    backup: Path,
) -> None:
    _sync_tree(backup)
    if _validate_configured_wiki(workspace, allow_missing=True):
        _remove_live_wiki(workspace)
    _rename_workspace_entry(workspace, backup, workspace.wiki_dir)
    _sync_tree(workspace.wiki_dir)
    _cleanup_transaction(workspace, transaction_dir)


def _quarantine_backup_and_cleanup(
    workspace: Workspace,
    transaction_dir: Path,
    backup: Path,
    expected_digest: str,
) -> None:
    quarantine = transaction_dir / f"{_QUARANTINE_PREFIX}{uuid.uuid4().hex}"
    _rename_workspace_entry(workspace, backup, quarantine)
    _sync_tree(quarantine)
    if _materialized_tree_digest(quarantine, transaction_dir) != expected_digest:
        _restore_concurrent_backup(workspace, transaction_dir, quarantine)
        raise _ConcurrentLiveEditError("live wiki changed during swap")
    _cleanup_transaction(workspace, transaction_dir)


def _cleanup_transaction(workspace: Workspace, transaction_dir: Path) -> None:
    if workspace.wiki_dir.is_dir() and not workspace.wiki_dir.is_symlink():
        _sync_tree(workspace.wiki_dir)
    if transaction_dir.is_dir() and not transaction_dir.is_symlink():
        backup_candidates = [transaction_dir / _BACKUP_NAME]
        backup_candidates.extend(
            path for path in transaction_dir.iterdir() if path.name.startswith(_QUARANTINE_PREFIX)
        )
        for backup in backup_candidates:
            if backup.is_dir() and not backup.is_symlink():
                _sync_tree(backup)
    if transaction_dir.is_dir() and not transaction_dir.is_symlink():
        _sync_directory(transaction_dir)
        _remove_tree(transaction_dir)
    _sync_directory(transaction_dir.parent)


@contextmanager
def _workspace_transaction_lock(workspace: Workspace) -> Generator[None]:
    flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    with _open_workspace_directory(
        workspace,
        (".bundlewalker",),
        label="transaction lock parent",
    ) as parent_descriptor:
        try:
            try:
                descriptor = os.open(
                    _LOCK_NAME,
                    flags | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=parent_descriptor,
                )
                os.fsync(parent_descriptor)
            except FileExistsError:
                descriptor = os.open(
                    _LOCK_NAME,
                    flags,
                    dir_fd=parent_descriptor,
                )
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise TransactionError("workspace transaction lock is not a regular file")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        except OSError as exc:
            raise TransactionError("could not acquire workspace transaction lock") from exc
        try:
            yield
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)


def _stage_validation_workspace(
    workspace: Workspace,
    validation_workspace: Workspace,
    raw_source: RawSource | None,
) -> None:
    validation_workspace.root.mkdir(parents=True)
    _copy_tree_materialized(workspace.wiki_dir, validation_workspace.wiki_dir)
    if workspace.raw_dir.is_dir() and not workspace.raw_dir.is_symlink():
        _copy_tree_materialized(workspace.raw_dir, validation_workspace.raw_dir)
    else:
        validation_workspace.raw_dir.mkdir(parents=True)

    config_source = workspace.root / "bundlewalker.toml"
    config_destination = validation_workspace.root / "bundlewalker.toml"
    try:
        config_destination.write_bytes(config_source.read_bytes())
    except OSError as exc:
        raise TransactionError("could not stage workspace configuration") from exc

    if raw_source is None:
        return
    relative = _validated_raw_relative(workspace, raw_source.stored_relative_path)
    destination = validation_workspace.root.joinpath(*PurePosixPath(relative).parts)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.is_symlink() or not destination.is_file():
            raise TransactionError(f"staged raw destination is occupied: {relative}")
        if _file_digest(destination) != raw_source.sha256:
            raise TransactionError(f"staged raw destination has a different digest: {relative}")
    else:
        destination.write_bytes(raw_source.content)


def _copy_tree_materialized(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_dir():
        raise TransactionError(f"workspace tree is not a regular directory: {source}")
    resolved_source = source.resolve(strict=False)
    try:
        for path in source.rglob("*"):
            if path.is_symlink():
                target = path.resolve(strict=True)
                if not target.is_relative_to(resolved_source):
                    raise TransactionError(f"workspace symlink escapes its tree: {path}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination, symlinks=False)
    except (OSError, RuntimeError) as exc:
        raise TransactionError(f"could not stage workspace tree: {source}") from exc


def _validate_source_pair(
    context: ChangeValidationContext,
    raw_source: RawSource | None,
) -> None:
    if context.source != raw_source:
        raise TransactionError("transaction raw source does not match validation context")
    if raw_source is None:
        return
    digest = hashlib.sha256(raw_source.content).hexdigest()
    if digest != raw_source.sha256:
        raise TransactionError("raw source content does not match its SHA-256 digest")


def _persist_raw_source(
    workspace: Workspace,
    transaction_dir: Path,
    raw_source: RawSource | None,
    manifest: _Manifest,
) -> None:
    if raw_source is None:
        if manifest.raw_path is not None or manifest.raw_sha256 is not None:
            raise TransactionError("transaction manifest unexpectedly contains a raw source")
        return
    if manifest.raw_path is None or manifest.raw_sha256 != raw_source.sha256:
        raise TransactionError("transaction raw source does not match its manifest")
    if hashlib.sha256(raw_source.content).hexdigest() != raw_source.sha256:
        raise TransactionError("raw source content does not match its SHA-256 digest")

    payload = transaction_dir / _RAW_PAYLOAD_NAME
    if payload.is_symlink() or not payload.is_file():
        raise TransactionError("transaction raw payload is missing")
    if _file_digest(payload) != raw_source.sha256:
        raise TransactionError("transaction raw payload has a different digest")
    relative_value = _validated_raw_relative(workspace, Path(manifest.raw_path))
    relative = PurePosixPath(relative_value)
    configured = PurePosixPath(workspace.config.raw_dir)
    parent_parts = relative.parts[:-1]
    with _open_workspace_directory(
        workspace,
        parent_parts,
        create_from=len(configured.parts),
        label="raw destination parent",
    ) as parent_descriptor:
        try:
            try:
                os.link(
                    payload,
                    relative.name,
                    dst_dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            except FileExistsError:
                metadata = os.stat(
                    relative.name,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
                if not stat.S_ISREG(metadata.st_mode):
                    raise TransactionError(
                        f"raw destination is occupied: {manifest.raw_path}"
                    ) from None
                if _file_digest_at(parent_descriptor, relative.name) != raw_source.sha256:
                    raise TransactionError(
                        f"raw destination has a different digest: {manifest.raw_path}"
                    ) from None
            if _file_digest_at(parent_descriptor, relative.name) != raw_source.sha256:
                raise TransactionError(
                    f"persisted raw source failed digest verification: {manifest.raw_path}"
                )
            os.fsync(parent_descriptor)
        except OSError as exc:
            raise TransactionError(f"could not create raw source: {manifest.raw_path}") from exc
    with _open_workspace_directory(
        workspace,
        configured.parts,
        label="configured raw path",
    ):
        pass


def _file_digest_at(directory_descriptor: int, name: str) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=directory_descriptor)
        with os.fdopen(descriptor, "rb") as source_file:
            return hashlib.sha256(source_file.read()).hexdigest()
    except OSError as exc:
        raise TransactionError(f"could not verify raw file descriptor: {name}") from exc


def _write_raw_payload(
    transaction_dir: Path,
    raw_source: RawSource | None,
) -> None:
    if raw_source is None:
        return
    payload = transaction_dir / _RAW_PAYLOAD_NAME
    try:
        with payload.open("xb") as raw_file:
            raw_file.write(raw_source.content)
            raw_file.flush()
            os.fsync(raw_file.fileno())
        _sync_directory(transaction_dir)
    except OSError as exc:
        raise TransactionError("could not stage transaction raw payload") from exc
    if _file_digest(payload) != raw_source.sha256:
        raise TransactionError("staged raw payload failed digest verification")


def _revalidate_operations(
    workspace: Workspace,
    drafts: tuple[_DraftRecord, ...],
) -> None:
    try:
        live_documents = OkfRepository(workspace.wiki_dir).scan()
    except OkfError as exc:
        raise TransactionError("could not revalidate live concepts") from exc
    folded_live = {concept_id.casefold(): concept_id for concept_id in live_documents}
    for draft in drafts:
        if draft.operation is ChangeOperation.REPLACE:
            existing = live_documents.get(draft.path)
            if existing is None or existing.digest != draft.base_digest:
                raise TransactionError(f"replacement has a stale base digest: {draft.path}")
        elif collision := folded_live.get(draft.path.casefold()):
            raise TransactionError(f"create target now exists: {collision}")


def _verify_live_base(
    workspace: Workspace,
    transaction_dir: Path,
    manifest: _Manifest,
) -> None:
    if manifest.base_wiki_digest is None:
        raise TransactionError("transaction manifest is missing its base wiki digest")
    current_digest = _materialized_tree_digest(workspace.wiki_dir, transaction_dir)
    if current_digest != manifest.base_wiki_digest:
        raise TransactionError("live wiki changed since preparation")


def _verify_prospective(
    path: Path,
    workspace: Workspace,
    expected_digest: str,
    *,
    lint: bool,
) -> None:
    if path.is_symlink() or not path.is_dir():
        raise TransactionError(f"prospective wiki is missing: {path}")
    actual = _tree_digest(path)
    if actual != expected_digest:
        raise TransactionError("prospective wiki no longer matches the reviewed tree")
    if lint and has_errors(lint_bundle(path, workspace.root)):
        raise TransactionError("prospective wiki failed deterministic lint")


def _validate_prepared_handle(
    prepared: PreparedTransaction,
    manifest: _Manifest,
    prospective: Path,
    backup: Path,
) -> None:
    if prepared.transaction_id != manifest.transaction_id:
        raise TransactionError("prepared transaction ID does not match its manifest")
    if prepared.transaction_dir.resolve(strict=False) != (
        prepared.workspace.root / ".bundlewalker" / "transactions" / manifest.transaction_id
    ).resolve(strict=False):
        raise TransactionError("prepared transaction directory is outside transaction storage")
    if prepared.prospective_wiki.resolve(strict=False) != prospective.resolve(strict=False):
        raise TransactionError("prepared prospective path does not match its manifest")
    if prepared.backup_wiki.resolve(strict=False) != backup.resolve(strict=False):
        raise TransactionError("prepared backup path does not match its manifest")
    if prepared.summary != manifest.summary:
        raise TransactionError("prepared summary does not match its manifest")
    if prepared.change_set.summary != prepared.summary:
        raise TransactionError("prepared change set summary does not match")
    expected_drafts = tuple(
        _DraftRecord(
            path=_canonical_concept_id(draft.path),
            operation=draft.operation,
            base_digest=draft.base_digest,
        )
        for draft in prepared.change_set.drafts
    )
    if manifest.drafts != expected_drafts:
        raise TransactionError("prepared change set does not match its manifest")
    if manifest.prospective_digest != prepared.prospective_digest:
        raise TransactionError("manifest does not match the reviewed prospective identity")
    if manifest.base_wiki_digest != prepared.base_wiki_digest:
        raise TransactionError("manifest does not match the reviewed base identity")
    if prepared.raw_source is None:
        if manifest.raw_path is not None or manifest.raw_sha256 is not None:
            raise TransactionError("prepared transaction unexpectedly contains a raw path")
    else:
        expected_raw_path = _validated_raw_relative(
            prepared.workspace,
            prepared.raw_source.stored_relative_path,
        )
        if (
            manifest.raw_path != expected_raw_path
            or manifest.raw_sha256 != prepared.raw_source.sha256
        ):
            raise TransactionError("prepared raw path does not match its source")


def _ensure_transactions_root(workspace: Workspace) -> Path:
    root = workspace.root.resolve(strict=False)
    bundlewalker_root = workspace.root / ".bundlewalker"
    transactions_root = workspace.root.joinpath(*_TRANSACTIONS_PATH.parts)
    for existing in (bundlewalker_root, transactions_root):
        if existing.is_symlink():
            raise TransactionError(f"transaction path is a symlink: {existing}")
    try:
        if not bundlewalker_root.exists():
            bundlewalker_root.mkdir()
            _sync_directory(workspace.root)
        elif not bundlewalker_root.is_dir():
            raise TransactionError("transaction parent is not a regular directory")
        if not transactions_root.exists():
            transactions_root.mkdir()
            _sync_directory(bundlewalker_root)
        elif not transactions_root.is_dir():
            raise TransactionError("transaction storage is not a regular directory")
    except OSError as exc:
        raise TransactionError("could not create transaction storage") from exc
    if not transactions_root.resolve(strict=False).is_relative_to(root):
        raise TransactionError("transaction storage escapes workspace")
    return transactions_root


def _manifest_paths(
    workspace: Workspace,
    transaction_dir: Path,
    manifest: _Manifest,
) -> tuple[Path, Path]:
    prospective = _resolve_workspace_relative(workspace, manifest.prospective_path)
    backup = _resolve_workspace_relative(workspace, manifest.backup_path)
    expected_dir = workspace.root / ".bundlewalker" / "transactions" / manifest.transaction_id
    if transaction_dir.resolve(strict=False) != expected_dir.resolve(strict=False):
        raise TransactionError("transaction directory does not match manifest ID")
    if prospective.resolve(strict=False) != (expected_dir / _PROSPECTIVE_NAME).resolve(
        strict=False
    ):
        raise TransactionError("prospective path is not a safe workspace-relative path")
    if backup.resolve(strict=False) != (expected_dir / _BACKUP_NAME).resolve(strict=False):
        raise TransactionError("backup path is not a safe workspace-relative path")
    if prospective.is_symlink() or backup.is_symlink():
        raise TransactionError("transaction wiki paths must not be symlinks")
    if manifest.raw_path is not None:
        _validated_raw_relative(workspace, Path(manifest.raw_path))
    return prospective, backup


def _load_manifest(workspace: Workspace, transaction_dir: Path) -> _Manifest:
    path = transaction_dir / _MANIFEST_NAME
    try:
        parsed: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _IncompleteManifestError from exc
    if not isinstance(parsed, dict):
        raise _IncompleteManifestError
    untyped_values = cast(dict[object, object], parsed)
    if not all(isinstance(key, str) for key in untyped_values):
        raise _IncompleteManifestError
    raw_values = cast(dict[str, object], untyped_values)

    try:
        schema_version = _required_int(raw_values, "schema_version")
        transaction_id = _required_string(raw_values, "transaction_id")
        phase_value = _required_string(raw_values, "phase")
        prospective_path = _required_string(raw_values, "prospective_path")
        backup_path = _required_string(raw_values, "backup_path")
        summary = _required_string(raw_values, "summary")
        raw_path = _optional_string(raw_values, "raw_path")
        raw_sha256 = _optional_string(raw_values, "raw_sha256")
        prospective_digest = _optional_string(raw_values, "prospective_digest")
        base_wiki_digest = _optional_string(raw_values, "base_wiki_digest")
        drafts_value = raw_values["drafts"]
    except (KeyError, TypeError, ValueError) as exc:
        raise _IncompleteManifestError from exc
    if schema_version != _SCHEMA_VERSION:
        raise TransactionError(f"unsupported transaction schema version: {schema_version}")
    if phase_value not in {"prepared", "raw-persisted", "swapping", "new-live"}:
        raise TransactionError(f"invalid transaction phase: {phase_value}")
    if not isinstance(drafts_value, list):
        raise _IncompleteManifestError
    drafts: list[_DraftRecord] = []
    try:
        for untyped_value in cast(list[object], drafts_value):
            if not isinstance(untyped_value, dict):
                raise TypeError
            untyped_mapping = cast(dict[object, object], untyped_value)
            if not all(isinstance(key, str) for key in untyped_mapping):
                raise TypeError
            value = cast(dict[str, object], untyped_mapping)
            operation_value = _required_string(value, "operation")
            drafts.append(
                _DraftRecord(
                    path=_canonical_concept_id(_required_string(value, "path")),
                    operation=ChangeOperation(operation_value),
                    base_digest=_optional_string(value, "base_digest"),
                )
            )
    except (TypeError, ValueError) as exc:
        raise _IncompleteManifestError from exc

    if not transaction_id or PurePosixPath(transaction_id).name != transaction_id:
        raise TransactionError("transaction ID is not safe")
    if (raw_path is None) != (raw_sha256 is None):
        raise TransactionError("transaction raw identity is incomplete")
    if raw_sha256 is not None and _SHA256.fullmatch(raw_sha256) is None:
        raise TransactionError("transaction raw digest is invalid")
    if prospective_digest is not None and _SHA256.fullmatch(prospective_digest) is None:
        raise TransactionError("transaction prospective digest is invalid")
    if base_wiki_digest is not None and _SHA256.fullmatch(base_wiki_digest) is None:
        raise TransactionError("transaction base wiki digest is invalid")

    manifest = _Manifest(
        schema_version=schema_version,
        transaction_id=transaction_id,
        phase=cast(_Phase, phase_value),
        prospective_path=prospective_path,
        backup_path=backup_path,
        raw_path=raw_path,
        raw_sha256=raw_sha256,
        summary=summary,
        drafts=tuple(drafts),
        prospective_digest=prospective_digest,
        base_wiki_digest=base_wiki_digest,
    )
    _manifest_paths(workspace, transaction_dir, manifest)
    return manifest


def _write_manifest(transaction_dir: Path, manifest: _Manifest) -> None:
    path = transaction_dir / _MANIFEST_NAME
    values: dict[str, object] = {
        "schema_version": manifest.schema_version,
        "transaction_id": manifest.transaction_id,
        "phase": manifest.phase,
        "prospective_path": manifest.prospective_path,
        "backup_path": manifest.backup_path,
        "raw_path": manifest.raw_path,
        "raw_sha256": manifest.raw_sha256,
        "summary": manifest.summary,
        "drafts": [
            {
                "path": draft.path,
                "operation": draft.operation.value,
                "base_digest": draft.base_digest,
            }
            for draft in manifest.drafts
        ],
        "prospective_digest": manifest.prospective_digest,
        "base_wiki_digest": manifest.base_wiki_digest,
    }
    content = (json.dumps(values, indent=2, sort_keys=True) + "\n").encode()
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".manifest-",
            dir=transaction_dir,
        )
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as manifest_file:
            manifest_file.write(content)
            manifest_file.flush()
            os.fsync(manifest_file.fileno())
        os.replace(temporary, path)
        temporary = None
        _sync_directory(transaction_dir)
    except OSError as exc:
        raise TransactionError("could not persist transaction manifest") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _write_identity(transaction_dir: Path, identity: _Identity) -> None:
    path = transaction_dir / _IDENTITY_NAME
    content = (
        json.dumps(
            {
                "base_wiki_digest": identity.base_wiki_digest,
                "prospective_digest": identity.prospective_digest,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as identity_file:
            identity_file.write(content)
            identity_file.flush()
            os.fsync(identity_file.fileno())
        _sync_directory(transaction_dir)
    except OSError as exc:
        raise TransactionError("could not persist transaction identity") from exc


def _load_identity(transaction_dir: Path) -> _Identity:
    path = transaction_dir / _IDENTITY_NAME
    try:
        parsed: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _IncompleteManifestError from exc
    if not isinstance(parsed, dict):
        raise _IncompleteManifestError
    values = cast(dict[object, object], parsed)
    base = values.get("base_wiki_digest")
    prospective = values.get("prospective_digest")
    if (
        not isinstance(base, str)
        or _SHA256.fullmatch(base) is None
        or not isinstance(prospective, str)
        or _SHA256.fullmatch(prospective) is None
    ):
        raise _IncompleteManifestError
    return _Identity(base_wiki_digest=base, prospective_digest=prospective)


def _required_string(values: dict[str, object], key: str) -> str:
    value = values[key]
    if not isinstance(value, str):
        raise TypeError(key)
    return value


def _optional_string(values: dict[str, object], key: str) -> str | None:
    value = values.get(key)
    if value is not None and not isinstance(value, str):
        raise TypeError(key)
    return value


def _required_int(values: dict[str, object], key: str) -> int:
    value = values[key]
    if type(value) is not int:
        raise TypeError(key)
    return value


def _canonical_concept_id(value: str) -> str:
    without_suffix = value[:-3] if value.endswith(".md") else value
    relative = PurePosixPath(without_suffix)
    if (
        not without_suffix
        or relative.is_absolute()
        or any(part in {".", ".."} for part in without_suffix.split("/"))
    ):
        raise TransactionError(f"unsafe draft path in transaction manifest: {value}")
    return relative.as_posix()


def _validated_raw_relative(workspace: Workspace, value: Path) -> str:
    relative = PurePosixPath(value.as_posix())
    configured_raw = PurePosixPath(workspace.config.raw_dir)
    if (
        relative.is_absolute()
        or relative.as_posix() != value.as_posix()
        or ".." in relative.parts
        or not relative.is_relative_to(configured_raw)
        or relative == configured_raw
    ):
        raise TransactionError("raw path is not a safe workspace-relative path")
    _configured_raw_root(workspace)
    return relative.as_posix()


def _configured_raw_root(workspace: Workspace) -> Path:
    configured = PurePosixPath(workspace.config.raw_dir)
    current = workspace.root
    for part in configured.parts:
        current /= part
        if current.is_symlink():
            raise TransactionError(f"configured raw path contains a symlink: {current}")
        if not current.is_dir():
            raise TransactionError(f"configured raw path is not a directory: {current}")
    resolved_workspace = workspace.root.resolve(strict=False)
    resolved_raw = current.resolve(strict=False)
    if not resolved_raw.is_relative_to(resolved_workspace):
        raise TransactionError("configured raw path escapes workspace")
    return current


@contextmanager
def _open_workspace_directory(
    workspace: Workspace,
    parts: tuple[str, ...],
    *,
    label: str,
    create_from: int | None = None,
) -> Generator[int]:
    if any(not part or part in {".", ".."} or "/" in part for part in parts):
        raise TransactionError(f"{label} is not a safe workspace-relative directory")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptors: list[int] = []
    traversed: list[str] = []
    try:
        current = os.open(workspace.root, flags)
        descriptors.append(current)
        for index, part in enumerate(parts):
            traversed.append(part)
            try:
                child = os.open(part, flags, dir_fd=current)
            except FileNotFoundError:
                if create_from is None or index < create_from:
                    raise
                with suppress(FileExistsError):
                    os.mkdir(part, 0o700, dir_fd=current)
                os.fsync(current)
                child = os.open(part, flags, dir_fd=current)
            descriptors.append(child)
            current = child
    except OSError as exc:
        location = "/".join(traversed) or "."
        for descriptor in reversed(descriptors):
            with suppress(OSError):
                os.close(descriptor)
        raise TransactionError(f"{label} contains a symlink or non-directory: {location}") from exc
    try:
        yield current
    finally:
        for descriptor in reversed(descriptors):
            with suppress(OSError):
                os.close(descriptor)


def _configured_wiki_parts(workspace: Workspace) -> tuple[str, ...]:
    relative = PurePosixPath(workspace.config.wiki_dir)
    if (
        relative.is_absolute()
        or relative == PurePosixPath(".")
        or ".." in relative.parts
        or relative.as_posix() != workspace.config.wiki_dir
    ):
        raise TransactionError("configured wiki path is not workspace-relative")
    return relative.parts


def _validate_configured_wiki(
    workspace: Workspace,
    *,
    allow_missing: bool = False,
) -> bool:
    parts = _configured_wiki_parts(workspace)
    with _open_workspace_directory(
        workspace,
        parts[:-1],
        label="configured wiki path",
    ) as parent_descriptor:
        try:
            metadata = os.stat(
                parts[-1],
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            if allow_missing:
                return False
            raise TransactionError("configured wiki path does not exist") from None
        if not stat.S_ISDIR(metadata.st_mode):
            raise TransactionError("configured wiki path is a symlink or non-directory")
    try:
        resolved_root = workspace.root.resolve(strict=True)
        resolved_wiki = workspace.wiki_dir.resolve(strict=True)
    except OSError as exc:
        raise TransactionError("could not resolve configured wiki path") from exc
    if not resolved_wiki.is_relative_to(resolved_root):
        raise TransactionError("configured wiki path escapes workspace")
    return True


def _workspace_entry_parts(workspace: Workspace, path: Path) -> tuple[str, ...]:
    try:
        relative = path.relative_to(workspace.root)
    except ValueError as exc:
        raise TransactionError(f"workspace entry is outside workspace: {path}") from exc
    if not relative.parts or ".." in relative.parts:
        raise TransactionError(f"workspace entry is not safe: {path}")
    return relative.parts


def _rename_workspace_entry(workspace: Workspace, source: Path, target: Path) -> None:
    source_parts = _workspace_entry_parts(workspace, source)
    target_parts = _workspace_entry_parts(workspace, target)
    try:
        with (
            _open_workspace_directory(
                workspace,
                source_parts[:-1],
                label="rename source parent",
            ) as source_parent,
            _open_workspace_directory(
                workspace,
                target_parts[:-1],
                label="rename target parent",
            ) as target_parent,
        ):
            os.rename(
                source_parts[-1],
                target_parts[-1],
                src_dir_fd=source_parent,
                dst_dir_fd=target_parent,
            )
            os.fsync(source_parent)
            os.fsync(target_parent)
    except OSError as exc:
        raise TransactionError(f"could not rename workspace entry: {source}") from exc
    _sync_directory(source.parent)
    if target.parent != source.parent:
        _sync_directory(target.parent)


def _remove_live_wiki(workspace: Workspace) -> None:
    if not _validate_configured_wiki(workspace, allow_missing=True):
        return
    parts = _configured_wiki_parts(workspace)
    try:
        with _open_workspace_directory(
            workspace,
            parts[:-1],
            label="configured wiki parent",
        ) as parent_descriptor:
            shutil.rmtree(parts[-1], dir_fd=parent_descriptor)
            os.fsync(parent_descriptor)
    except OSError as exc:
        raise TransactionError("could not remove live wiki safely") from exc
    _sync_directory(workspace.wiki_dir.parent)


def _workspace_relative(workspace: Workspace, path: Path) -> str:
    try:
        return path.relative_to(workspace.root).as_posix()
    except ValueError as exc:
        raise TransactionError("transaction path is outside workspace") from exc


def _resolve_workspace_relative(workspace: Workspace, value: str) -> Path:
    relative = PurePosixPath(value)
    if (
        not value
        or relative.is_absolute()
        or relative.as_posix() != value
        or ".." in relative.parts
    ):
        raise TransactionError(f"path is not a safe workspace-relative path: {value}")
    resolved_root = workspace.root.resolve(strict=False)
    candidate = workspace.root.joinpath(*relative.parts)
    if not candidate.resolve(strict=False).is_relative_to(resolved_root):
        raise TransactionError(f"path is not a safe workspace-relative path: {value}")
    return candidate


def _tree_digest(root: Path) -> str:
    if root.is_symlink() or not root.is_dir():
        raise TransactionError(f"wiki tree is not a regular directory: {root}")
    digest = hashlib.sha256()
    try:
        entries = sorted(root.rglob("*"), key=lambda path: path.relative_to(root).as_posix())
        for path in entries:
            relative = path.relative_to(root).as_posix().encode()
            if path.is_symlink():
                raise TransactionError(f"wiki tree contains a symlink: {path}")
            if path.is_dir():
                digest.update(b"D")
                digest.update(len(relative).to_bytes(8, "big"))
                digest.update(relative)
            elif path.is_file():
                content = path.read_bytes()
                digest.update(b"F")
                digest.update(len(relative).to_bytes(8, "big"))
                digest.update(relative)
                digest.update(len(content).to_bytes(8, "big"))
                digest.update(content)
            else:
                raise TransactionError(f"wiki tree contains a special file: {path}")
    except OSError as exc:
        raise TransactionError(f"could not hash wiki tree: {root}") from exc
    return digest.hexdigest()


def _materialized_tree_digest(source: Path, transaction_dir: Path) -> str:
    scratch_parent = transaction_dir if transaction_dir.is_dir() else transaction_dir.parent
    try:
        scratch = Path(
            tempfile.mkdtemp(
                prefix=".tree-check-",
                dir=scratch_parent,
            )
        )
    except OSError as exc:
        raise TransactionError("could not create tree identity staging") from exc
    try:
        materialized = scratch / "tree"
        _copy_tree_materialized(source, materialized)
        return _tree_digest(materialized)
    finally:
        _remove_tree_if_safe(scratch)


def _tree_matches_identity(
    path: Path,
    expected: str,
    transaction_dir: Path,
) -> bool:
    if path.is_symlink() or not path.is_dir():
        return False
    try:
        return _materialized_tree_digest(path, transaction_dir) == expected
    except TransactionError:
        return False


def _sync_tree(root: Path) -> None:
    if root.is_symlink() or not root.is_dir():
        raise TransactionError(f"cannot sync non-directory tree: {root}")
    resolved_root = root.resolve(strict=False)
    directories = [root]
    try:
        entries = sorted(root.rglob("*"), key=lambda path: path.relative_to(root).as_posix())
        for path in entries:
            if path.is_symlink():
                target = path.resolve(strict=True)
                if not target.is_relative_to(resolved_root):
                    raise TransactionError(f"tree symlink escapes during sync: {path}")
                continue
            if path.is_dir():
                directories.append(path)
                continue
            if not path.is_file():
                raise TransactionError(f"tree contains a special file during sync: {path}")
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        for directory in sorted(
            directories,
            key=lambda path: len(path.relative_to(root).parts),
            reverse=True,
        ):
            _sync_directory(directory)
    except OSError as exc:
        raise TransactionError(f"could not recursively sync tree: {root}") from exc


def _file_digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise TransactionError(f"could not verify file digest: {path}") from exc


def _directory_exists(path: Path, label: str) -> bool:
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise TransactionError(f"{label} is not a regular directory")
    return path.is_dir()


def _remove_tree(path: Path) -> None:
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise TransactionError(f"refusing to remove non-directory transaction path: {path}")
    if not path.exists():
        return
    try:
        shutil.rmtree(path)
    except OSError as exc:
        raise TransactionError(f"could not remove transaction path: {path}") from exc


def _remove_tree_if_safe(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)


def _sync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise TransactionError(f"could not sync directory: {path}") from exc


def _recover_after_commit_error(
    workspace: Workspace,
    prepared: PreparedTransaction,
    cause: OSError | TransactionError,
) -> None:
    identity = _Identity(
        base_wiki_digest=prepared.base_wiki_digest,
        prospective_digest=prepared.prospective_digest,
    )
    try:
        _recover_transaction(
            workspace,
            prepared.transaction_dir,
            expected_identity=identity,
        )
    except TransactionError as recovery_error:
        raise TransactionError(
            f"transaction commit failed ({cause}) and recovery was unsuccessful: {recovery_error}"
        ) from cause
    raise TransactionError(
        f"transaction commit failed and filesystem state was recovered: {cause}"
    ) from cause
