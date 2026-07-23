# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

RELEASE_CANDIDATE = re.compile(r"0\.4\.0rc[1-9][0-9]*")
MAX_CAPTURE_CHARACTERS = 20_000
TRUNCATION_MARKER = "\n...[truncated by lifecycle rehearsal]"


class RehearsalFailure(RuntimeError):
    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category
        self.message = message


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
