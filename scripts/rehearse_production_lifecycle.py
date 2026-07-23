# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import time
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, cast

RELEASE_CANDIDATE = re.compile(r"0\.4\.0rc[1-9][0-9]*")
SHA256_LINE = re.compile(r"^SHA-256: ([0-9a-f]{64})$", re.MULTILINE)
MAX_CAPTURE_CHARACTERS = 20_000
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
