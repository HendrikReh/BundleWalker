from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass, replace
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
_PROSPECTIVE_NAME = "prospective-wiki"
_BACKUP_NAME = "backup-wiki"
_VALIDATION_WORKSPACE_NAME = "validation-workspace"
_BASE_CHECK_NAME = "base-wiki-check"
_RAW_PAYLOAD_NAME = "raw-source"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_Phase = Literal["prepared", "raw-persisted", "swapping", "new-live"]


@dataclass(frozen=True, slots=True)
class PreparedTransaction:
    transaction_id: str
    workspace: Workspace
    transaction_dir: Path
    prospective_wiki: Path
    backup_wiki: Path
    raw_source: RawSource | None
    summary: str
    diff: str


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


class _IncompleteManifestError(Exception):
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
    transactions_root = _ensure_transactions_root(workspace)
    transaction_id = uuid.uuid4().hex
    transaction_dir = transactions_root / transaction_id
    prospective_wiki = transaction_dir / _PROSPECTIVE_NAME
    backup_wiki = transaction_dir / _BACKUP_NAME
    validation_root = transaction_dir / _VALIDATION_WORKSPACE_NAME

    try:
        transaction_dir.mkdir()
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
            prospective_digest=_tree_digest(prospective_wiki),
            base_wiki_digest=_tree_digest(validation_workspace.wiki_dir),
        )
        _write_raw_payload(transaction_dir, raw_source)
        _remove_tree(validation_root)
        _write_manifest(transaction_dir, manifest)
    except OSError as exc:
        _remove_tree_if_safe(transaction_dir)
        raise TransactionError("could not prepare transaction staging") from exc
    except BaseException:
        _remove_tree_if_safe(transaction_dir)
        raise

    return PreparedTransaction(
        transaction_id=transaction_id,
        workspace=workspace,
        transaction_dir=transaction_dir,
        prospective_wiki=prospective_wiki,
        backup_wiki=backup_wiki,
        raw_source=raw_source,
        summary=change_set.summary,
        diff=diff,
    )


def commit_transaction(prepared: PreparedTransaction) -> None:
    """Persist a prepared transaction and recover immediately from interrupted swaps."""
    workspace = prepared.workspace
    manifest = _load_manifest(workspace, prepared.transaction_dir)
    prospective, backup = _manifest_paths(workspace, prepared.transaction_dir, manifest)
    _validate_prepared_handle(prepared, manifest, prospective, backup)
    if manifest.phase != "prepared":
        raise TransactionError(f"transaction is not prepared: {manifest.phase}")

    _verify_prospective(prospective, workspace, manifest, lint=False)
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
    _verify_prospective(prospective, workspace, manifest, lint=True)

    manifest = replace(manifest, phase="swapping")
    _write_manifest(prepared.transaction_dir, manifest)
    try:
        workspace.wiki_dir.rename(backup)
        _sync_directory(workspace.root)
        _sync_directory(prepared.transaction_dir)
        prospective.rename(workspace.wiki_dir)
        _sync_directory(workspace.root)
        _sync_directory(prepared.transaction_dir)
        manifest = replace(manifest, phase="new-live")
        _write_manifest(prepared.transaction_dir, manifest)
        _verify_prospective(workspace.wiki_dir, workspace, manifest, lint=True)
        _remove_tree(prepared.transaction_dir)
    except OSError as exc:
        _recover_after_commit_error(workspace, prepared.transaction_dir, exc)


def discard_transaction(prepared: PreparedTransaction) -> None:
    """Discard an unaccepted prepared transaction without touching live knowledge."""
    manifest = _load_manifest(prepared.workspace, prepared.transaction_dir)
    prospective, backup = _manifest_paths(
        prepared.workspace,
        prepared.transaction_dir,
        manifest,
    )
    _validate_prepared_handle(prepared, manifest, prospective, backup)
    if manifest.phase != "prepared":
        raise TransactionError(f"only a prepared transaction can be discarded: {manifest.phase}")
    _remove_tree(prepared.transaction_dir)


def recover_transactions(workspace: Workspace) -> None:
    """Recover every interrupted transaction in stable order; safe to call repeatedly."""
    transactions_root = workspace.root.joinpath(*_TRANSACTIONS_PATH.parts)
    if not transactions_root.exists():
        return
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


def _recover_transaction(workspace: Workspace, transaction_dir: Path) -> None:
    try:
        manifest = _load_manifest(workspace, transaction_dir)
    except _IncompleteManifestError:
        _recover_incomplete_transaction(workspace, transaction_dir)
        return

    prospective, backup = _manifest_paths(workspace, transaction_dir, manifest)
    if manifest.phase in {"prepared", "raw-persisted"}:
        _remove_tree(transaction_dir)
        return
    if manifest.phase == "swapping":
        _recover_swapping(workspace, transaction_dir, manifest, prospective, backup)
        return
    _recover_new_live(workspace, transaction_dir, manifest, prospective, backup)


def _recover_swapping(
    workspace: Workspace,
    transaction_dir: Path,
    manifest: _Manifest,
    prospective: Path,
    backup: Path,
) -> None:
    live_exists = _directory_exists(workspace.wiki_dir, "live wiki")
    backup_exists = _directory_exists(backup, "transaction backup")
    prospective_exists = _directory_exists(prospective, "prospective wiki")

    if live_exists and not backup_exists:
        _remove_tree(transaction_dir)
        return
    if not live_exists and backup_exists:
        backup.rename(workspace.wiki_dir)
        _sync_directory(workspace.root)
        _remove_tree(transaction_dir)
        return
    if live_exists and backup_exists:
        if _is_valid_prospective(workspace.wiki_dir, workspace, manifest):
            _remove_tree(transaction_dir)
        else:
            _restore_backup(workspace, transaction_dir, manifest, backup)
        return
    if prospective_exists and _is_valid_prospective(prospective, workspace, manifest):
        prospective.rename(workspace.wiki_dir)
        _sync_directory(workspace.root)
        _remove_tree(transaction_dir)
        return
    raise TransactionError(f"transaction {manifest.transaction_id} has no recoverable wiki tree")


def _recover_new_live(
    workspace: Workspace,
    transaction_dir: Path,
    manifest: _Manifest,
    prospective: Path,
    backup: Path,
) -> None:
    live_exists = _directory_exists(workspace.wiki_dir, "live wiki")
    backup_exists = _directory_exists(backup, "transaction backup")
    prospective_exists = _directory_exists(prospective, "prospective wiki")

    if live_exists and _is_valid_prospective(workspace.wiki_dir, workspace, manifest):
        _remove_tree(transaction_dir)
        return
    if backup_exists:
        _restore_backup(workspace, transaction_dir, manifest, backup)
        return
    if (
        not live_exists
        and prospective_exists
        and _is_valid_prospective(
            prospective,
            workspace,
            manifest,
        )
    ):
        prospective.rename(workspace.wiki_dir)
        _sync_directory(workspace.root)
        _remove_tree(transaction_dir)
        return
    raise TransactionError(
        f"transaction {manifest.transaction_id} has no valid live or backup wiki"
    )


def _recover_incomplete_transaction(workspace: Workspace, transaction_dir: Path) -> None:
    backup = transaction_dir / _BACKUP_NAME
    live_exists = _directory_exists(workspace.wiki_dir, "live wiki")
    backup_exists = _directory_exists(backup, "transaction backup")
    if backup_exists:
        if live_exists:
            _remove_tree(workspace.wiki_dir)
        backup.rename(workspace.wiki_dir)
        _sync_directory(workspace.root)
    elif not live_exists:
        raise TransactionError(
            f"incomplete transaction {transaction_dir.name} has no recoverable wiki"
        )
    _remove_tree(transaction_dir)


def _restore_backup(
    workspace: Workspace,
    transaction_dir: Path,
    manifest: _Manifest,
    backup: Path,
) -> None:
    if has_errors(lint_bundle(backup, workspace.root)):
        raise TransactionError(
            f"transaction {manifest.transaction_id} backup wiki failed deterministic lint"
        )
    _write_manifest(transaction_dir, replace(manifest, phase="swapping"))
    if workspace.wiki_dir.exists():
        _remove_tree(workspace.wiki_dir)
    backup.rename(workspace.wiki_dir)
    _sync_directory(workspace.root)
    _remove_tree(transaction_dir)


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
    destination = _resolve_workspace_relative(workspace, manifest.raw_path)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise TransactionError(f"could not create raw directory: {manifest.raw_path}") from exc
    try:
        os.link(payload, destination, follow_symlinks=False)
    except FileExistsError:
        if destination.is_symlink() or not destination.is_file():
            raise TransactionError(f"raw destination is occupied: {manifest.raw_path}") from None
        if _file_digest(destination) != raw_source.sha256:
            raise TransactionError(
                f"raw destination has a different digest: {manifest.raw_path}"
            ) from None
        return
    except OSError as exc:
        raise TransactionError(f"could not create raw source: {manifest.raw_path}") from exc

    _sync_directory(destination.parent)
    if _file_digest(destination) != raw_source.sha256:
        raise TransactionError(
            f"persisted raw source failed digest verification: {manifest.raw_path}"
        )


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
    staged_base = transaction_dir / _BASE_CHECK_NAME
    try:
        _copy_tree_materialized(workspace.wiki_dir, staged_base)
        current_digest = _tree_digest(staged_base)
    finally:
        _remove_tree_if_safe(staged_base)
    if current_digest != manifest.base_wiki_digest:
        raise TransactionError("live wiki changed since preparation")


def _verify_prospective(
    path: Path,
    workspace: Workspace,
    manifest: _Manifest,
    *,
    lint: bool,
) -> None:
    if path.is_symlink() or not path.is_dir():
        raise TransactionError(f"prospective wiki is missing: {path}")
    if manifest.prospective_digest is not None:
        actual = _tree_digest(path)
        if actual != manifest.prospective_digest:
            raise TransactionError("prospective wiki no longer matches the reviewed tree")
    if lint and has_errors(lint_bundle(path, workspace.root)):
        raise TransactionError("prospective wiki failed deterministic lint")


def _is_valid_prospective(
    path: Path,
    workspace: Workspace,
    manifest: _Manifest,
) -> bool:
    try:
        _verify_prospective(path, workspace, manifest, lint=True)
    except TransactionError:
        return False
    return True


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
    transactions_root = workspace.root.joinpath(*_TRANSACTIONS_PATH.parts)
    for existing in (workspace.root / ".bundlewalker", transactions_root):
        if existing.is_symlink():
            raise TransactionError(f"transaction path is a symlink: {existing}")
    try:
        transactions_root.mkdir(parents=True, exist_ok=True)
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
    temporary = transaction_dir / f"{_MANIFEST_NAME}.tmp"
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
    try:
        with temporary.open("wb") as manifest_file:
            manifest_file.write(content)
            manifest_file.flush()
            os.fsync(manifest_file.fileno())
        os.replace(temporary, path)
        _sync_directory(transaction_dir)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise TransactionError("could not persist transaction manifest") from exc


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
    resolved = workspace.root.joinpath(*relative.parts).resolve(strict=False)
    if not resolved.is_relative_to(workspace.root.resolve(strict=False)):
        raise TransactionError("raw path is not a safe workspace-relative path")
    return relative.as_posix()


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
    transaction_dir: Path,
    cause: OSError,
) -> None:
    try:
        _recover_transaction(workspace, transaction_dir)
    except TransactionError as recovery_error:
        raise TransactionError("transaction commit failed and recovery was unsuccessful") from (
            recovery_error
        )
    raise TransactionError("transaction commit failed; filesystem state was recovered") from cause
