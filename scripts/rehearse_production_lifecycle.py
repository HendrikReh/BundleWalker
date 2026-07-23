# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version as distribution_version
from pathlib import Path, PurePosixPath
from typing import Any, cast

RELEASE_CANDIDATE = re.compile(r"0\.4\.0rc[1-9][0-9]*")
SHA256_LINE = re.compile(r"^SHA-256: ([0-9a-f]{64})$", re.MULTILINE)
MAX_CAPTURE_CHARACTERS = 20_000
MAX_DOCTOR_REPORT_BYTES = 1024 * 1024
TRUNCATION_MARKER = "\n...[truncated by lifecycle rehearsal]"
PORTABLE_ENTRIES = ("bundlewalker.toml", "conventions.md", "raw", "wiki")
PORTABLE_FILE_ENTRIES = ("bundlewalker.toml", "conventions.md")
PORTABLE_DIRECTORY_ENTRIES = ("raw", "wiki")
EXPECTED_TOOLS = frozenset(
    {
        "workspace_status",
        "search_concepts",
        "ask",
        "lint",
        "get_pending_review",
        "prepare_ingestion",
        "prepare_synthesis",
        "prepare_refresh",
        "apply_review",
        "discard_review",
    }
)
PHASE_NAMES = (
    "installed_identity",
    "initialize",
    "inspect_original",
    "backup",
    "restore",
    "upgrade_noop",
    "rollback",
    "mcp",
    "final_invariants",
)
STATUS_REQUIREMENTS = (
    "Workspace format: 1",
    "Compatibility: current",
    "Readable: yes",
    "Writable: yes",
    "Upgrade available: no",
)
LIFECYCLE_TARGET_NAMES = (
    "original",
    "restored",
    "rollback",
    "archives",
    "upgrade-backups",
)
MCP_PROBE = r"""
import asyncio
import json
import os
import sys

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


async def probe() -> None:
    parameters = StdioServerParameters(
        command=sys.argv[1],
        args=["--workspace", sys.argv[2]],
        env=os.environ.copy(),
        cwd=sys.argv[2],
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
    print(json.dumps(sorted(tool.name for tool in result.tools)))


asyncio.run(probe())
"""


@dataclass(frozen=True)
class RehearsalConfig:
    version: str
    run_root: Path
    evidence_dir: Path
    bundlewalker: Path
    bundlewalker_mcp: Path


class RehearsalFailure(RuntimeError):
    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category
        self.message = message


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def portable_tree_sha256(workspace: Path) -> str:
    digest = hashlib.sha256()

    def update_field(value: bytes) -> None:
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)

    for name in PORTABLE_ENTRIES:
        path = workspace / name
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            raise RehearsalFailure(
                "workspace_identity", "portable workspace surface is incomplete"
            ) from None
        if stat.S_ISLNK(mode):
            raise RehearsalFailure(
                "workspace_identity", f"portable surface contains symlink: {name}"
            )
        if name in PORTABLE_FILE_ENTRIES and not stat.S_ISREG(mode):
            raise RehearsalFailure(
                "workspace_identity", f"portable root must be a regular file: {name}"
            )
        if name in PORTABLE_DIRECTORY_ENTRIES and not stat.S_ISDIR(mode):
            raise RehearsalFailure(
                "workspace_identity", f"portable root must be a directory: {name}"
            )
    paths = [workspace / name for name in PORTABLE_ENTRIES]
    paths.extend(
        child for name in PORTABLE_DIRECTORY_ENTRIES for child in (workspace / name).rglob("*")
    )
    for path in sorted(paths, key=lambda item: item.relative_to(workspace).as_posix()):
        relative = PurePosixPath(path.relative_to(workspace).as_posix()).as_posix()
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise RehearsalFailure(
                "workspace_identity", f"portable surface contains symlink: {relative}"
            )
        if stat.S_ISDIR(mode):
            kind = b"directory"
            content = b""
        elif stat.S_ISREG(mode):
            kind = b"file"
            content = path.read_bytes()
        else:
            raise RehearsalFailure("workspace_identity", f"unsupported portable entry: {relative}")
        update_field(kind)
        update_field(relative.encode("utf-8"))
        update_field(content)
    return digest.hexdigest()


def parse_reported_sha256(output: str) -> str:
    matches = SHA256_LINE.findall(output)
    if len(matches) != 1:
        raise RehearsalFailure("archive_identity", "command must report exactly one SHA-256")
    return matches[0]


def require_success(result: Mapping[str, object], *, category: str) -> None:
    if result["exit_code"] != 0:
        raise RehearsalFailure(category, f"command failed with exit {result['exit_code']}")


def require_environment_entrypoint(path: Path, environment_root: Path) -> Path:
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(environment_root.resolve(strict=True)):
        raise RehearsalFailure("installed_identity", "entrypoint is outside isolated environment")
    return resolved


def require_exact_tools(actual: Sequence[str]) -> list[str]:
    normalized = sorted(actual)
    if frozenset(normalized) != EXPECTED_TOOLS or len(normalized) != len(EXPECTED_TOOLS):
        raise RehearsalFailure(
            "mcp", "installed MCP tool inventory does not match ten-tool contract"
        )
    return normalized


def validate_release_candidate(value: str) -> str:
    if RELEASE_CANDIDATE.fullmatch(value) is None:
        raise ValueError("version must be an exact 0.4.0 release candidate")
    return value


def sanitize_value(value: object, run_root: Path) -> object:
    root = os.fspath(run_root.resolve())
    if isinstance(value, str):
        return value.replace(root, "$RUN_ROOT")
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {str(key): sanitize_value(item, run_root) for key, item in mapping.items()}
    if isinstance(value, (list, tuple)):
        items = cast(list[object] | tuple[object, ...], value)
        return [sanitize_value(item, run_root) for item in items]
    return value


def bounded_text(value: str, run_root: Path) -> str:
    safe = str(sanitize_value(value, run_root))
    if len(safe) <= MAX_CAPTURE_CHARACTERS:
        return safe
    return safe[:MAX_CAPTURE_CHARACTERS] + TRUNCATION_MARKER


def _timeout_text(value: object) -> str:
    return value if type(value) is str else ""


def run_command(
    argv: Sequence[str],
    *,
    cwd: Path,
    run_root: Path,
    timeout: float = 60.0,
) -> dict[str, object]:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            list(argv),
            cwd=cwd,
            env=os.environ.copy(),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        exit_code = -1
        stdout = _timeout_text(cast(object, exc.stdout))
        stderr = _timeout_text(cast(object, exc.stderr))
        stderr += f"\ncommand exceeded {timeout:g} seconds"
    return {
        "argv": sanitize_value(list(argv), run_root),
        "cwd": sanitize_value(os.fspath(cwd.resolve()), run_root),
        "exit_code": exit_code,
        "stdout": bounded_text(stdout, run_root),
        "stderr": bounded_text(stderr, run_root),
        "elapsed_seconds": round(time.monotonic() - started, 6),
    }


def write_evidence(path: Path, evidence: Mapping[str, object], run_root: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload: Any = sanitize_value(dict(evidence), run_root)
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def new_evidence(version: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "result": "running",
        "failure_category": None,
        "requested_version": version,
        "started_at": datetime.now(UTC).isoformat(),
        "phases": [],
    }


def _safe_label(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]", "?", value)[:100]
    return normalized or "unknown"


def execute_phases(
    evidence: dict[str, object],
    phases: Sequence[tuple[str, Callable[[], dict[str, object]]]],
) -> None:
    recorded = cast(list[dict[str, object]], evidence["phases"])
    for index, (name, phase) in enumerate(phases):
        record: dict[str, object] = {"name": name, "status": "running"}
        recorded.append(record)
        try:
            details = phase()
        except RehearsalFailure as exc:
            commands = record.get("commands")
            record.clear()
            record.update(
                {
                    "name": name,
                    "status": "failed",
                    "failure_category": exc.category,
                    "message": exc.message,
                }
            )
            if commands is not None:
                record["commands"] = commands
            recorded.extend(
                {
                    "name": later_name,
                    "status": "skipped",
                    "reason": f"blocked by failed phase {name}",
                }
                for later_name, _ in phases[index + 1 :]
            )
            raise
        except Exception as exc:
            commands = record.get("commands")
            record.clear()
            record.update(
                {
                    "name": name,
                    "status": "failed",
                    "failure_category": "harness_internal",
                    "message": (
                        "unexpected internal failure in phase "
                        f"{_safe_label(name)} ({_safe_label(type(exc).__name__)})"
                    ),
                }
            )
            if commands is not None:
                record["commands"] = commands
            recorded.extend(
                {
                    "name": later_name,
                    "status": "skipped",
                    "reason": f"blocked by failed phase {name}",
                }
                for later_name, _ in phases[index + 1 :]
            )
            raise
        record.update({"status": "passed", **details})


def _normalized_config(config: RehearsalConfig) -> RehearsalConfig:
    try:
        version = validate_release_candidate(config.version)
    except ValueError as exc:
        raise RehearsalFailure("configuration", str(exc)) from None
    run_root = config.run_root.resolve()
    evidence_dir = config.evidence_dir.resolve()
    if evidence_dir == run_root or not evidence_dir.is_relative_to(run_root):
        raise RehearsalFailure("configuration", "evidence directory must be inside the run root")
    return RehearsalConfig(
        version=version,
        run_root=run_root,
        evidence_dir=evidence_dir,
        bundlewalker=config.bundlewalker,
        bundlewalker_mcp=config.bundlewalker_mcp,
    )


def _prepare_run_root(config: RehearsalConfig) -> None:
    try:
        config.run_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise RehearsalFailure("configuration", "run root could not be created") from None


def _require_new_lifecycle_targets(config: RehearsalConfig) -> None:
    collisions = [
        name
        for name in LIFECYCLE_TARGET_NAMES
        if (config.run_root / name).exists() or (config.run_root / name).is_symlink()
    ]
    if collisions:
        raise RehearsalFailure(
            "configuration", "run root contains a harness-owned lifecycle target"
        )


def _record_command(
    evidence: dict[str, object],
    argv: Sequence[str],
    *,
    cwd: Path,
    run_root: Path,
    timeout: float = 60.0,
) -> dict[str, object]:
    result = run_command(
        argv,
        cwd=cwd,
        run_root=run_root,
        timeout=timeout,
    )
    phases = cast(list[dict[str, object]], evidence["phases"])
    current = phases[-1]
    commands = cast(list[dict[str, object]], current.setdefault("commands", []))
    commands.append(result)
    return result


def _stdout(result: Mapping[str, object], *, category: str) -> str:
    stdout = result["stdout"]
    if not isinstance(stdout, str):
        raise RehearsalFailure(category, "command stdout was not text")
    return stdout


def _require_status(result: Mapping[str, object], *, category: str) -> None:
    require_success(result, category=category)
    output = _stdout(result, category=category)
    if any(requirement not in output for requirement in STATUS_REQUIREMENTS):
        raise RehearsalFailure(
            category, "workspace status does not satisfy current-format contract"
        )


def _has_files(directory: Path) -> bool:
    return any(path.is_file() for path in directory.rglob("*"))


def _load_raw_doctor_report(
    raw_report: Path,
    *,
    run_root: Path,
    category: str,
) -> object:
    directory_descriptor: int | None = None
    cleanup_name: str | None = None
    cleanup_entry = False
    try:
        root = run_root.resolve(strict=True)
        parent = raw_report.parent.resolve(strict=True)
        if not parent.is_relative_to(root):
            raise RehearsalFailure(
                category, "doctor report must be a regular file inside the run root"
            )
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_flags |= getattr(os, "O_NOFOLLOW", 0)
        directory_descriptor = os.open(parent, directory_flags)
        cleanup_name = raw_report.name
        report_stat = os.stat(
            cleanup_name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        cleanup_entry = not stat.S_ISDIR(report_stat.st_mode)
        if not stat.S_ISREG(report_stat.st_mode):
            raise RehearsalFailure(
                category, "doctor report must be a regular file inside the run root"
            )
        if report_stat.st_size > MAX_DOCTOR_REPORT_BYTES:
            raise RehearsalFailure(category, "raw doctor report exceeds the one-megabyte limit")
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        if no_follow == 0:
            raise RehearsalFailure(category, "doctor report no-follow reads are unavailable")
        report_descriptor = os.open(
            cleanup_name,
            os.O_RDONLY | no_follow,
            dir_fd=directory_descriptor,
        )
        with os.fdopen(report_descriptor, "rb") as stream:
            opened_stat = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(opened_stat.st_mode)
                or opened_stat.st_dev != report_stat.st_dev
                or opened_stat.st_ino != report_stat.st_ino
            ):
                raise RehearsalFailure(category, "doctor report changed before it could be read")
            if opened_stat.st_size > MAX_DOCTOR_REPORT_BYTES:
                raise RehearsalFailure(category, "raw doctor report exceeds the one-megabyte limit")
            raw_bytes = stream.read(MAX_DOCTOR_REPORT_BYTES + 1)
            if len(raw_bytes) > MAX_DOCTOR_REPORT_BYTES:
                raise RehearsalFailure(category, "raw doctor report exceeds the one-megabyte limit")
            return json.loads(raw_bytes.decode("utf-8"))
    except RehearsalFailure:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise RehearsalFailure(category, "doctor report could not be preserved") from None
    finally:
        cleanup_failed = False
        if directory_descriptor is not None:
            if cleanup_name is not None and cleanup_entry:
                try:
                    os.unlink(cleanup_name, dir_fd=directory_descriptor)
                except FileNotFoundError:
                    pass
                except OSError:
                    cleanup_failed = True
            os.close(directory_descriptor)
        if cleanup_failed:
            raise RehearsalFailure(category, "raw doctor report could not be deleted")


def _preserve_doctor_report(
    raw_report: Path,
    evidence_report: Path,
    *,
    run_root: Path,
    category: str,
) -> None:
    payload = _load_raw_doctor_report(
        raw_report,
        run_root=run_root,
        category=category,
    )
    if not isinstance(payload, Mapping):
        raise RehearsalFailure(category, "doctor report must contain a JSON object")
    sanitized = sanitize_value(cast(Mapping[object, object], payload), run_root)
    serialized = json.dumps(sanitized, indent=2, sort_keys=True) + "\n"
    if len(serialized.encode("utf-8")) > MAX_DOCTOR_REPORT_BYTES:
        raise RehearsalFailure(category, "sanitized doctor report exceeds the one-megabyte limit")
    write_evidence(
        evidence_report,
        cast(Mapping[str, object], sanitized),
        run_root,
    )


def _execute_rehearsal(config: RehearsalConfig, evidence: dict[str, object]) -> None:
    _prepare_run_root(config)
    original = config.run_root / "original"
    restored = config.run_root / "restored"
    rollback = config.run_root / "rollback"
    archives = config.run_root / "archives"
    archive = archives / "original.zip"
    upgrade_backups = config.run_root / "upgrade-backups"
    doctor_reports = {
        "original": config.evidence_dir / "original-doctor.json",
        "restored": config.evidence_dir / "restored-doctor.json",
        "rollback": config.evidence_dir / "rollback-doctor.json",
    }
    digests: dict[str, str] = {}
    archive_identity: dict[str, object] = {}
    entrypoints: dict[str, Path] = {}

    with tempfile.TemporaryDirectory(prefix="raw-doctor-", dir=config.run_root) as temporary:
        raw_doctor = Path(temporary)

        def installed_identity() -> dict[str, object]:
            _require_new_lifecycle_targets(config)
            installed_version = distribution_version("bundlewalker")
            if installed_version != config.version:
                raise RehearsalFailure(
                    "installed_identity",
                    "installed distribution version does not match requested version",
                )
            environment_root = Path(sys.prefix)
            bundlewalker = require_environment_entrypoint(config.bundlewalker, environment_root)
            bundlewalker_mcp = require_environment_entrypoint(
                config.bundlewalker_mcp, environment_root
            )
            entrypoints["bundlewalker"] = bundlewalker
            entrypoints["bundlewalker_mcp"] = bundlewalker_mcp
            metadata: dict[str, object] = {
                "python_version": platform.python_version(),
                "operating_system": platform.system(),
                "architecture": platform.machine(),
                "python_executable": sys.executable,
                "environment_root": os.fspath(environment_root.resolve()),
                "bundlewalker": os.fspath(bundlewalker),
                "bundlewalker_mcp": os.fspath(bundlewalker_mcp),
            }
            evidence["installed_version"] = installed_version
            evidence["environment"] = metadata
            return {
                "requested_version": config.version,
                "installed_version": installed_version,
                "environment": metadata,
            }

        def initialize() -> dict[str, object]:
            command = _record_command(
                evidence,
                [os.fspath(entrypoints["bundlewalker"]), "init", os.fspath(original)],
                cwd=config.run_root,
                run_root=config.run_root,
            )
            require_success(command, category="initialize")
            return {"commands": [command]}

        def inspect_original() -> dict[str, object]:
            status_command = _record_command(
                evidence,
                [
                    os.fspath(entrypoints["bundlewalker"]),
                    "workspace",
                    "status",
                    os.fspath(original),
                ],
                cwd=config.run_root,
                run_root=config.run_root,
            )
            _require_status(status_command, category="inspect_original")
            raw_report = raw_doctor / "original.json"
            doctor_command = _record_command(
                evidence,
                [
                    os.fspath(entrypoints["bundlewalker"]),
                    "doctor",
                    os.fspath(original),
                    "--report",
                    os.fspath(raw_report),
                ],
                cwd=config.run_root,
                run_root=config.run_root,
            )
            require_success(doctor_command, category="inspect_original")
            _preserve_doctor_report(
                raw_report,
                doctor_reports["original"],
                run_root=config.run_root,
                category="inspect_original",
            )
            digests["original"] = portable_tree_sha256(original)
            evidence["digests"] = digests
            return {
                "commands": [status_command, doctor_command],
                "portable_sha256": digests["original"],
                "doctor_report": os.fspath(doctor_reports["original"]),
            }

        def backup() -> dict[str, object]:
            archives.mkdir()
            command = _record_command(
                evidence,
                [
                    os.fspath(entrypoints["bundlewalker"]),
                    "workspace",
                    "backup",
                    os.fspath(archive),
                    "--workspace",
                    os.fspath(original),
                ],
                cwd=config.run_root,
                run_root=config.run_root,
            )
            require_success(command, category="backup")
            reported_digest = parse_reported_sha256(_stdout(command, category="backup"))
            actual_digest = file_sha256(archive)
            if reported_digest != actual_digest:
                raise RehearsalFailure(
                    "archive_identity", "backup archive digest does not match command output"
                )
            archive_identity["sha256"] = actual_digest
            archive_identity["bytes"] = archive.stat().st_size
            evidence["archive_sha256"] = actual_digest
            evidence["archive_bytes"] = archive_identity["bytes"]
            return {
                "commands": [command],
                "archive_sha256": actual_digest,
                "archive_bytes": archive_identity["bytes"],
            }

        def restore() -> dict[str, object]:
            restore_command = _record_command(
                evidence,
                [
                    os.fspath(entrypoints["bundlewalker"]),
                    "workspace",
                    "restore",
                    os.fspath(archive),
                    os.fspath(restored),
                ],
                cwd=config.run_root,
                run_root=config.run_root,
            )
            require_success(restore_command, category="restore")
            if (
                parse_reported_sha256(_stdout(restore_command, category="restore"))
                != archive_identity["sha256"]
            ):
                raise RehearsalFailure(
                    "archive_identity", "restore archive digest does not match backup"
                )
            digests["restored"] = portable_tree_sha256(restored)
            if digests["restored"] != digests["original"]:
                raise RehearsalFailure(
                    "workspace_identity", "restored portable identity does not match original"
                )
            status_command = _record_command(
                evidence,
                [
                    os.fspath(entrypoints["bundlewalker"]),
                    "workspace",
                    "status",
                    os.fspath(restored),
                ],
                cwd=config.run_root,
                run_root=config.run_root,
            )
            _require_status(status_command, category="restore")
            lint_command = _record_command(
                evidence,
                [os.fspath(entrypoints["bundlewalker"]), "lint"],
                cwd=restored,
                run_root=config.run_root,
            )
            require_success(lint_command, category="restore")
            raw_report = raw_doctor / "restored.json"
            doctor_command = _record_command(
                evidence,
                [
                    os.fspath(entrypoints["bundlewalker"]),
                    "doctor",
                    os.fspath(restored),
                    "--report",
                    os.fspath(raw_report),
                ],
                cwd=config.run_root,
                run_root=config.run_root,
            )
            require_success(doctor_command, category="restore")
            _preserve_doctor_report(
                raw_report,
                doctor_reports["restored"],
                run_root=config.run_root,
                category="restore",
            )
            return {
                "commands": [
                    restore_command,
                    status_command,
                    lint_command,
                    doctor_command,
                ],
                "portable_sha256": digests["restored"],
                "doctor_report": os.fspath(doctor_reports["restored"]),
            }

        def upgrade_noop() -> dict[str, object]:
            upgrade_backups.mkdir()
            before = portable_tree_sha256(original)
            command = _record_command(
                evidence,
                [
                    os.fspath(entrypoints["bundlewalker"]),
                    "workspace",
                    "upgrade",
                    os.fspath(original),
                    "--backup-dir",
                    os.fspath(upgrade_backups),
                ],
                cwd=config.run_root,
                run_root=config.run_root,
            )
            require_success(command, category="upgrade_noop")
            if _stdout(command, category="upgrade_noop") != (
                "Workspace format 1 is already current.\n"
            ):
                raise RehearsalFailure(
                    "upgrade_noop", "current-format upgrade output did not match contract"
                )
            if _has_files(upgrade_backups):
                raise RehearsalFailure(
                    "upgrade_noop", "current-format upgrade created a backup file"
                )
            after = portable_tree_sha256(original)
            if after != before:
                raise RehearsalFailure(
                    "workspace_identity", "current-format upgrade changed portable identity"
                )
            return {
                "commands": [command],
                "portable_identity_unchanged": True,
                "upgrade_backup_files_absent": True,
            }

        def rollback_phase() -> dict[str, object]:
            restore_command = _record_command(
                evidence,
                [
                    os.fspath(entrypoints["bundlewalker"]),
                    "workspace",
                    "restore",
                    os.fspath(archive),
                    os.fspath(rollback),
                ],
                cwd=config.run_root,
                run_root=config.run_root,
            )
            require_success(restore_command, category="rollback")
            if (
                parse_reported_sha256(_stdout(restore_command, category="rollback"))
                != archive_identity["sha256"]
            ):
                raise RehearsalFailure(
                    "archive_identity", "rollback archive digest does not match backup"
                )
            digests["rollback"] = portable_tree_sha256(rollback)
            if digests["rollback"] != digests["original"]:
                raise RehearsalFailure(
                    "workspace_identity", "rollback portable identity does not match original"
                )
            status_command = _record_command(
                evidence,
                [
                    os.fspath(entrypoints["bundlewalker"]),
                    "workspace",
                    "status",
                    os.fspath(rollback),
                ],
                cwd=config.run_root,
                run_root=config.run_root,
            )
            _require_status(status_command, category="rollback")
            lint_command = _record_command(
                evidence,
                [os.fspath(entrypoints["bundlewalker"]), "lint"],
                cwd=rollback,
                run_root=config.run_root,
            )
            require_success(lint_command, category="rollback")
            raw_report = raw_doctor / "rollback.json"
            doctor_command = _record_command(
                evidence,
                [
                    os.fspath(entrypoints["bundlewalker"]),
                    "doctor",
                    os.fspath(rollback),
                    "--report",
                    os.fspath(raw_report),
                ],
                cwd=config.run_root,
                run_root=config.run_root,
            )
            require_success(doctor_command, category="rollback")
            _preserve_doctor_report(
                raw_report,
                doctor_reports["rollback"],
                run_root=config.run_root,
                category="rollback",
            )
            return {
                "commands": [
                    restore_command,
                    status_command,
                    lint_command,
                    doctor_command,
                ],
                "portable_sha256": digests["rollback"],
                "doctor_report": os.fspath(doctor_reports["rollback"]),
            }

        def mcp() -> dict[str, object]:
            command = _record_command(
                evidence,
                [
                    sys.executable,
                    "-c",
                    MCP_PROBE,
                    os.fspath(entrypoints["bundlewalker_mcp"]),
                    os.fspath(rollback),
                ],
                cwd=rollback,
                run_root=config.run_root,
                timeout=30.0,
            )
            require_success(command, category="mcp")
            try:
                tools: object = json.loads(_stdout(command, category="mcp"))
            except json.JSONDecodeError:
                raise RehearsalFailure("mcp", "MCP probe did not return valid JSON") from None
            if not isinstance(tools, list):
                raise RehearsalFailure("mcp", "MCP probe did not return a list of tool names")
            tool_values = cast(list[object], tools)
            if not all(type(tool) is str for tool in tool_values):
                raise RehearsalFailure("mcp", "MCP probe did not return a list of tool names")
            exact_tools = require_exact_tools(cast(list[str], tool_values))
            evidence["mcp_tools"] = exact_tools
            return {"commands": [command], "tools": exact_tools}

        def final_invariants() -> dict[str, object]:
            final_digests = {
                "original": portable_tree_sha256(original),
                "restored": portable_tree_sha256(restored),
                "rollback": portable_tree_sha256(rollback),
            }
            invariants = {
                "portable_identities_equal": len(set(final_digests.values())) == 1,
                "archive_digest_unchanged": file_sha256(archive) == archive_identity["sha256"],
                "archive_bytes_unchanged": archive.stat().st_size == archive_identity["bytes"],
                "upgrade_backup_files_absent": not _has_files(upgrade_backups),
                "doctor_reports_present": all(
                    report.is_file() for report in doctor_reports.values()
                ),
                "mcp_tools_exact": evidence.get("mcp_tools") == sorted(EXPECTED_TOOLS),
                "lifecycle_targets_within_run_root": all(
                    target.resolve().is_relative_to(config.run_root)
                    for target in (
                        original,
                        restored,
                        rollback,
                        archives,
                        upgrade_backups,
                        *doctor_reports.values(),
                    )
                ),
            }
            if not all(invariants.values()):
                raise RehearsalFailure(
                    "final_invariants", "one or more final lifecycle invariants failed"
                )
            digests.update(final_digests)
            evidence["digests"] = digests
            evidence["final_invariants"] = invariants
            return {"invariants": invariants}

        phases = [
            ("installed_identity", installed_identity),
            ("initialize", initialize),
            ("inspect_original", inspect_original),
            ("backup", backup),
            ("restore", restore),
            ("upgrade_noop", upgrade_noop),
            ("rollback", rollback_phase),
            ("mcp", mcp),
            ("final_invariants", final_invariants),
        ]
        if tuple(name for name, _ in phases) != PHASE_NAMES:
            raise RehearsalFailure(
                "harness_internal", "lifecycle phase order does not match schema"
            )
        execute_phases(evidence, phases)


def run_rehearsal(config: RehearsalConfig) -> dict[str, object]:
    normalized = _normalized_config(config)
    evidence = new_evidence(normalized.version)
    _execute_rehearsal(normalized, evidence)
    evidence["result"] = "passed"
    evidence["completed_at"] = datetime.now(UTC).isoformat()
    return evidence


def _parse_config(argv: Sequence[str] | None) -> RehearsalConfig:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True, type=validate_release_candidate)
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--bundlewalker", required=True, type=Path)
    parser.add_argument("--bundlewalker-mcp", required=True, type=Path)
    arguments = parser.parse_args(argv)
    return RehearsalConfig(
        version=cast(str, arguments.version),
        run_root=cast(Path, arguments.run_root),
        evidence_dir=cast(Path, arguments.evidence_dir),
        bundlewalker=cast(Path, arguments.bundlewalker),
        bundlewalker_mcp=cast(Path, arguments.bundlewalker_mcp),
    )


def _internal_failure_message(exc: Exception) -> str:
    return f"unexpected harness failure ({_safe_label(type(exc).__name__)})"


def main(argv: Sequence[str] | None = None) -> int:
    config = _parse_config(argv)
    evidence = new_evidence(config.version)
    exit_code = 1
    run_root = config.run_root
    evidence_path = run_root / "evidence" / "evidence.json"
    try:
        normalized = _normalized_config(config)
        run_root = normalized.run_root
        evidence_path = normalized.evidence_dir / "evidence.json"
        _execute_rehearsal(normalized, evidence)
        evidence["result"] = "passed"
        exit_code = 0
    except RehearsalFailure as exc:
        evidence["result"] = "failed"
        evidence["failure_category"] = exc.category
        evidence["message"] = exc.message
        print(exc.message, file=sys.stderr)
    except Exception as exc:
        message = _internal_failure_message(exc)
        evidence["result"] = "failed"
        evidence["failure_category"] = "harness_internal"
        evidence["message"] = message
        print(message, file=sys.stderr)
    finally:
        evidence["completed_at"] = datetime.now(UTC).isoformat()
        try:
            write_evidence(evidence_path, evidence, run_root)
        except Exception as exc:
            print(_internal_failure_message(exc), file=sys.stderr)
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
