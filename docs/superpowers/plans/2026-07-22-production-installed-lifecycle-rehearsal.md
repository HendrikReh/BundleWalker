# Production-Installed Lifecycle Rehearsal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run a manual GitHub Actions beta gate that proves one exact production-PyPI
BundleWalker `0.4.0rcN` artifact can complete the supported workspace lifecycle and installed MCP
startup on macOS and Linux with Python 3.13 and 3.14.

**Architecture:** A standard-library-first Python harness invokes the installed CLI and MCP entry
points without importing BundleWalker, records sanitized JSON evidence, and verifies portable-tree
and archive identities independently. A read-only manual workflow installs exclusively from
production PyPI in runner-temporary storage, runs the harness across the four supported
environment combinations, and uploads evidence unconditionally.

**Tech Stack:** Python 3.13/3.14 standard library, BundleWalker CLI, MCP Python SDK client,
GitHub Actions, `uv` 0.11.28, pytest, PyYAML, Ruff, Pyright

## Global Constraints

- Accept only exact versions matching `0\.4\.0rc[1-9][0-9]*`.
- Run the live gate only on Ubuntu 24.04 and macOS 15 with Python 3.13 and 3.14.
- Windows remains experimental and must not appear in the certification matrix.
- Install BundleWalker and every dependency only from `https://pypi.org/simple`; do not fall back
  to TestPyPI, a local wheel, the checkout, another index, or a direct local path.
- The harness must not import `bundlewalker`; installed behavior is observed only through entry
  points and installed distribution metadata.
- Do not configure providers, credentials, remote models, semantic lint, or provider-backed MCP
  calls.
- Use disposable paths under runner-temporary storage and never touch a maintainer workspace.
- Preserve bounded, run-root-sanitized evidence even after harness failure.
- The workflow has `contents: read`, no publishing environment, and no write or OIDC permission.
- Do not bump the package version unless the live run proves a defect in the immutable published
  package.
- Do not claim the live gate passed until four workflow jobs and their evidence artifacts are
  inspected and a durable result record is merged.
- Every new Python file starts with the repository GPL-3.0-or-later copyright/SPDX header.

---

### Task 1: Build the evidence and subprocess foundation

**Files:**
- Create: `scripts/rehearse_production_lifecycle.py`
- Create: `tests/test_production_lifecycle_rehearsal.py`
- Modify: `pyproject.toml`
- Modify: `tests/test_release_metadata.py`

**Interfaces:**
- Produces: `validate_release_candidate(value: str) -> str`.
- Produces: `sanitize_value(value: object, run_root: Path) -> object`.
- Produces: `bounded_text(value: str, run_root: Path) -> str`.
- Produces: `run_command(argv: Sequence[str], *, cwd: Path, run_root: Path, timeout: float = 60.0) -> dict[str, object]`.
- Produces: `write_evidence(path: Path, evidence: Mapping[str, object], run_root: Path) -> None`.
- Produces: `RehearsalFailure(category: str, message: str)` with public `category` and safe
  `message` attributes.

- [ ] **Step 1: Write failing foundation tests**

Create `tests/test_production_lifecycle_rehearsal.py` with the repository header, a safe dynamic
loader for the non-package script, and these tests:

```python
# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts/rehearse_production_lifecycle.py"


def _load_harness() -> ModuleType:
    spec = importlib.util.spec_from_file_location("production_lifecycle_rehearsal", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


HARNESS = _load_harness()


@pytest.mark.parametrize("value", ["0.4.0rc1", "0.4.0rc2", "0.4.0rc19"])
def test_release_candidate_validation_accepts_exact_values(value: str) -> None:
    assert HARNESS.validate_release_candidate(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "0.4.0",
        "0.4.0a2",
        "0.4.0rc0",
        "0.4.0rc01",
        "v0.4.0rc2",
        " 0.4.0rc2",
        "0.4.0rc2 ",
        "0.4.1rc1",
        "0.4.0rc2; echo unsafe",
    ],
)
def test_release_candidate_validation_rejects_every_other_shape(value: str) -> None:
    with pytest.raises(ValueError, match="exact 0.4.0 release candidate"):
        HARNESS.validate_release_candidate(value)


def test_sanitization_replaces_run_root_recursively_and_bounds_output(tmp_path: Path) -> None:
    root = tmp_path / "private-root"
    nested = {
        "path": str(root / "workspace"),
        "items": [f"before {root}/archive.zip after", {"plain": "safe"}],
    }

    assert HARNESS.sanitize_value(nested, root) == {
        "path": "$RUN_ROOT/workspace",
        "items": ["before $RUN_ROOT/archive.zip after", {"plain": "safe"}],
    }
    bounded = HARNESS.bounded_text("x" * 25_000 + str(root), root)
    assert len(bounded) <= HARNESS.MAX_CAPTURE_CHARACTERS + len(HARNESS.TRUNCATION_MARKER)
    assert str(root) not in bounded
    assert HARNESS.TRUNCATION_MARKER in bounded


def test_run_command_records_safe_success_and_failure(tmp_path: Path) -> None:
    success = HARNESS.run_command(
        [sys.executable, "-c", "print('ok')"],
        cwd=tmp_path,
        run_root=tmp_path,
    )
    failure = HARNESS.run_command(
        [sys.executable, "-c", "import sys; print('bad', file=sys.stderr); sys.exit(7)"],
        cwd=tmp_path,
        run_root=tmp_path,
    )

    assert success["exit_code"] == 0
    assert success["stdout"] == "ok\n"
    assert failure["exit_code"] == 7
    assert failure["stderr"] == "bad\n"
    assert success["cwd"] == "$RUN_ROOT"
    assert isinstance(success["elapsed_seconds"], float)


def test_write_evidence_is_atomic_sanitized_and_newline_terminated(tmp_path: Path) -> None:
    root = tmp_path / "run"
    output = root / "evidence" / "evidence.json"

    HARNESS.write_evidence(
        output,
        {"result": "passed", "workspace": str(root / "original")},
        root,
    )

    assert not output.with_suffix(".json.tmp").exists()
    assert output.read_text(encoding="utf-8").endswith("\n")
    assert json.loads(output.read_text(encoding="utf-8")) == {
        "result": "passed",
        "workspace": "$RUN_ROOT/original",
    }
```

Extend the existing `test_python_sources_have_gpl_headers` source list in
`tests/test_release_metadata.py` with:

```python
python_files.extend(sorted((PROJECT_ROOT / "scripts").rglob("*.py")))
```

Add this strict-analysis contract:

```python
def test_operational_python_scripts_are_strictly_type_checked() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["tool"]["pyright"]["include"] == [
        "src",
        "tests",
        "benchmarks",
        "scripts",
    ]
```

- [ ] **Step 2: Run the tests to verify the script is absent**

Run:

```bash
uv run pytest tests/test_production_lifecycle_rehearsal.py -q
```

Expected: collection fails because `scripts/rehearse_production_lifecycle.py` does not exist, and
the strict-analysis contract fails because `scripts` is not yet in the Pyright include list.

- [ ] **Step 3: Implement the foundation**

Create `scripts/rehearse_production_lifecycle.py` with these constants and interfaces:

```python
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
from typing import Any

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
        return {str(key): sanitize_value(item, run_root) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_value(item, run_root) for item in value]
    return value


def bounded_text(value: str, run_root: Path) -> str:
    safe = str(sanitize_value(value, run_root))
    if len(safe) <= MAX_CAPTURE_CHARACTERS:
        return safe
    return safe[:MAX_CAPTURE_CHARACTERS] + TRUNCATION_MARKER


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
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
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
```

Change the Pyright configuration in `pyproject.toml` to:

```toml
[tool.pyright]
include = ["src", "tests", "benchmarks", "scripts"]
pythonVersion = "3.13"
typeCheckingMode = "strict"
```

- [ ] **Step 4: Run foundation tests and lint the new files**

Run:

```bash
uv run pytest tests/test_production_lifecycle_rehearsal.py -q
uv run pytest tests/test_release_metadata.py::test_python_sources_have_gpl_headers tests/test_release_metadata.py::test_operational_python_scripts_are_strictly_type_checked -q
uv run ruff format --check scripts/rehearse_production_lifecycle.py tests/test_production_lifecycle_rehearsal.py
uv run ruff check scripts/rehearse_production_lifecycle.py tests/test_production_lifecycle_rehearsal.py
uv run pyright
```

Expected: all focused tests, both Ruff commands, and strict Pyright exit `0`.

- [ ] **Step 5: Commit the foundation**

```bash
git add pyproject.toml scripts/rehearse_production_lifecycle.py tests/test_production_lifecycle_rehearsal.py tests/test_release_metadata.py
git commit -m "test: add lifecycle rehearsal foundation"
```

---

### Task 2: Add portable identity and lifecycle assertions

**Files:**
- Modify: `scripts/rehearse_production_lifecycle.py`
- Modify: `tests/test_production_lifecycle_rehearsal.py`

**Interfaces:**
- Consumes: `RehearsalFailure`, `run_command`, and evidence helpers from Task 1.
- Produces: `portable_tree_sha256(workspace: Path) -> str`.
- Produces: `file_sha256(path: Path) -> str`.
- Produces: `parse_reported_sha256(output: str) -> str`.
- Produces: `require_success(result: Mapping[str, object], *, category: str) -> None`.
- Produces: `require_environment_entrypoint(path: Path, environment_root: Path) -> Path`.
- Produces: `require_exact_tools(actual: Sequence[str]) -> list[str]`.

- [ ] **Step 1: Add failing assertion tests**

Append tests that create the exact portable surface, prove stable hashing, reject symlinks, parse
CLI digests, and enforce executable/tool identity:

```python
import os


EXPECTED_TOOLS = {
    "apply_review",
    "ask",
    "discard_review",
    "get_pending_review",
    "lint",
    "prepare_ingestion",
    "prepare_refresh",
    "prepare_synthesis",
    "search_concepts",
    "workspace_status",
}


def _portable_workspace(root: Path) -> Path:
    root.mkdir()
    (root / "bundlewalker.toml").write_text("version = 1\n", encoding="utf-8")
    (root / "conventions.md").write_text("# Conventions\n", encoding="utf-8")
    (root / "raw").mkdir()
    (root / "wiki" / "topics").mkdir(parents=True)
    (root / "wiki" / "index.md").write_text("# Index\n", encoding="utf-8")
    return root


def test_portable_tree_digest_is_stable_and_excludes_private_state(tmp_path: Path) -> None:
    first = _portable_workspace(tmp_path / "first")
    second = _portable_workspace(tmp_path / "second")
    (first / ".bundlewalker").mkdir()
    (first / ".bundlewalker" / "private.json").write_text("private", encoding="utf-8")

    assert HARNESS.portable_tree_sha256(first) == HARNESS.portable_tree_sha256(second)
    (second / "wiki" / "index.md").write_text("# Changed\n", encoding="utf-8")
    assert HARNESS.portable_tree_sha256(first) != HARNESS.portable_tree_sha256(second)


def test_portable_tree_digest_refuses_missing_roots_and_symlinks(tmp_path: Path) -> None:
    incomplete = tmp_path / "incomplete"
    incomplete.mkdir()
    with pytest.raises(HARNESS.RehearsalFailure, match="portable workspace surface"):
        HARNESS.portable_tree_sha256(incomplete)

    workspace = _portable_workspace(tmp_path / "linked")
    target = tmp_path / "outside.txt"
    target.write_text("outside", encoding="utf-8")
    (workspace / "raw" / "linked.txt").symlink_to(target)
    with pytest.raises(HARNESS.RehearsalFailure, match="symlink"):
        HARNESS.portable_tree_sha256(workspace)


def test_digest_parsing_and_independent_file_hashing(tmp_path: Path) -> None:
    archive = tmp_path / "workspace.zip"
    archive.write_bytes(b"archive")
    digest = HARNESS.file_sha256(archive)

    assert len(digest) == 64
    assert HARNESS.parse_reported_sha256(f"Backup: x\nSHA-256: {digest}\n") == digest
    with pytest.raises(HARNESS.RehearsalFailure, match="exactly one SHA-256"):
        HARNESS.parse_reported_sha256("no digest")
    with pytest.raises(HARNESS.RehearsalFailure, match="exactly one SHA-256"):
        HARNESS.parse_reported_sha256(f"SHA-256: {digest}\nSHA-256: {digest}\n")


def test_entrypoint_and_tool_contracts_are_exact(tmp_path: Path) -> None:
    environment = tmp_path / "venv"
    executable = environment / "bin" / "bundlewalker"
    executable.parent.mkdir(parents=True)
    executable.write_text("entrypoint", encoding="utf-8")

    assert HARNESS.require_environment_entrypoint(executable, environment) == executable.resolve()
    with pytest.raises(HARNESS.RehearsalFailure, match="isolated environment"):
        HARNESS.require_environment_entrypoint(Path(os.devnull), environment)
    assert set(HARNESS.require_exact_tools(sorted(EXPECTED_TOOLS))) == EXPECTED_TOOLS
    with pytest.raises(HARNESS.RehearsalFailure, match="MCP tool inventory"):
        HARNESS.require_exact_tools(sorted(EXPECTED_TOOLS - {"ask"}))
```

- [ ] **Step 2: Run the new tests and verify missing interfaces fail**

Run:

```bash
uv run pytest tests/test_production_lifecycle_rehearsal.py -q
```

Expected: failures name `portable_tree_sha256`, `file_sha256`,
`parse_reported_sha256`, `require_environment_entrypoint`, and `require_exact_tools`.

- [ ] **Step 3: Implement deterministic identity and strict assertions**

Add `hashlib`, `stat`, and `PurePosixPath` imports, then implement the interfaces with these exact
rules:

```python
import hashlib
import stat
from pathlib import PurePosixPath

PORTABLE_ENTRIES = ("bundlewalker.toml", "conventions.md", "raw", "wiki")
SHA256_LINE = re.compile(r"^SHA-256: ([0-9a-f]{64})$", re.MULTILINE)
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


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def portable_tree_sha256(workspace: Path) -> str:
    digest = hashlib.sha256()
    for name in PORTABLE_ENTRIES:
        if not (workspace / name).exists():
            raise RehearsalFailure("workspace_identity", "portable workspace surface is incomplete")
    paths = [workspace / name for name in PORTABLE_ENTRIES]
    paths.extend(
        child
        for name in PORTABLE_ENTRIES
        if (workspace / name).is_dir()
        for child in (workspace / name).rglob("*")
    )
    for path in sorted(paths, key=lambda item: item.relative_to(workspace).as_posix()):
        relative = PurePosixPath(path.relative_to(workspace).as_posix()).as_posix()
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise RehearsalFailure("workspace_identity", f"portable surface contains symlink: {relative}")
        if stat.S_ISDIR(mode):
            kind = b"directory\0"
            content = b""
        elif stat.S_ISREG(mode):
            kind = b"file\0"
            content = path.read_bytes()
        else:
            raise RehearsalFailure("workspace_identity", f"unsupported portable entry: {relative}")
        digest.update(kind)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
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
    if set(normalized) != EXPECTED_TOOLS or len(normalized) != len(EXPECTED_TOOLS):
        raise RehearsalFailure("mcp", "installed MCP tool inventory does not match ten-tool contract")
    return normalized
```

- [ ] **Step 4: Run focused tests and Ruff**

```bash
uv run pytest tests/test_production_lifecycle_rehearsal.py -q
uv run ruff format --check scripts/rehearse_production_lifecycle.py tests/test_production_lifecycle_rehearsal.py
uv run ruff check scripts/rehearse_production_lifecycle.py tests/test_production_lifecycle_rehearsal.py
```

Expected: all commands exit `0`.

- [ ] **Step 5: Commit lifecycle assertions**

```bash
git add scripts/rehearse_production_lifecycle.py tests/test_production_lifecycle_rehearsal.py
git commit -m "feat: verify lifecycle artifact identities"
```

---

### Task 3: Orchestrate the complete installed lifecycle and MCP probe

**Files:**
- Modify: `scripts/rehearse_production_lifecycle.py`
- Modify: `tests/test_production_lifecycle_rehearsal.py`

**Interfaces:**
- Consumes: every helper from Tasks 1 and 2.
- Produces: immutable `RehearsalConfig` with `version`, `run_root`, `evidence_dir`,
  `bundlewalker`, and `bundlewalker_mcp` fields.
- Produces: `run_rehearsal(config: RehearsalConfig) -> dict[str, object]`.
- Produces: `main(argv: Sequence[str] | None = None) -> int`.
- Produces: evidence schema version `1` with ordered phases `installed_identity`, `initialize`,
  `inspect_original`, `backup`, `restore`, `upgrade_noop`, `rollback`, `mcp`, and
  `final_invariants`.

- [ ] **Step 1: Add failing phase and end-to-end tests**

Append tests for phase failure finalization and a development-environment integration run. The
integration test is orchestration evidence only and must say so in its name:

```python
import shutil
import subprocess
from importlib.metadata import version as distribution_version


def test_failed_phase_is_recorded_and_later_phases_are_skipped(tmp_path: Path) -> None:
    evidence = HARNESS.new_evidence("0.4.0rc2")

    def fail() -> dict[str, object]:
        raise HARNESS.RehearsalFailure("backup", "synthetic failure")

    with pytest.raises(HARNESS.RehearsalFailure, match="synthetic failure"):
        HARNESS.execute_phases(
            evidence,
            [("backup", fail), ("restore", lambda: {"unreachable": True})],
        )

    assert evidence["phases"] == [
        {
            "name": "backup",
            "status": "failed",
            "failure_category": "backup",
            "message": "synthetic failure",
        },
        {
            "name": "restore",
            "status": "skipped",
            "reason": "blocked by failed phase backup",
        },
    ]


def test_harness_orchestration_passes_in_development_environment(tmp_path: Path) -> None:
    bundlewalker = shutil.which("bundlewalker")
    bundlewalker_mcp = shutil.which("bundlewalker-mcp")
    assert bundlewalker is not None
    assert bundlewalker_mcp is not None
    run_root = tmp_path / "run"
    evidence_dir = run_root / "evidence"

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--version",
            distribution_version("bundlewalker"),
            "--run-root",
            str(run_root),
            "--evidence-dir",
            str(evidence_dir),
            "--bundlewalker",
            bundlewalker,
            "--bundlewalker-mcp",
            bundlewalker_mcp,
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert completed.returncode == 0, completed.stderr
    evidence = json.loads((evidence_dir / "evidence.json").read_text(encoding="utf-8"))
    assert evidence["result"] == "passed"
    assert [phase["status"] for phase in evidence["phases"]] == ["passed"] * 9
    assert set(evidence["mcp_tools"]) == EXPECTED_TOOLS
    assert evidence["digests"]["original"] == evidence["digests"]["restored"]
    assert evidence["digests"]["original"] == evidence["digests"]["rollback"]
```

- [ ] **Step 2: Run the tests and verify orchestration interfaces are missing**

```bash
uv run pytest tests/test_production_lifecycle_rehearsal.py -q
```

Expected: the new unit test fails on `new_evidence`; the integration test cannot complete because
the harness has no CLI entry point.

- [ ] **Step 3: Implement phase recording and CLI configuration**

Add `argparse`, `asyncio`, `platform`, `sys`, `tempfile`, dataclass, datetime, and distribution
metadata imports. Implement:

```python
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version as distribution_version

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


@dataclass(frozen=True)
class RehearsalConfig:
    version: str
    run_root: Path
    evidence_dir: Path
    bundlewalker: Path
    bundlewalker_mcp: Path


def new_evidence(version: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "result": "running",
        "failure_category": None,
        "requested_version": version,
        "started_at": datetime.now(UTC).isoformat(),
        "phases": [],
    }


def execute_phases(
    evidence: dict[str, object],
    phases: Sequence[tuple[str, Callable[[], dict[str, object]]]],
) -> None:
    recorded = cast(list[dict[str, object]], evidence["phases"])
    for index, (name, phase) in enumerate(phases):
        try:
            details = phase()
        except RehearsalFailure as exc:
            recorded.append(
                {
                    "name": name,
                    "status": "failed",
                    "failure_category": exc.category,
                    "message": exc.message,
                }
            )
            recorded.extend(
                {
                    "name": later_name,
                    "status": "skipped",
                    "reason": f"blocked by failed phase {name}",
                }
                for later_name, _ in phases[index + 1 :]
            )
            raise
        recorded.append({"name": name, "status": "passed", **details})
```

Import `Callable` and `cast` consistently. Parse the five required CLI options into
`RehearsalConfig`. Require the evidence directory to resolve inside the run root, but allow the
workflow bootstrap file, copied harness, and isolated `venv/` to exist there already. Fail closed
if any harness-owned lifecycle target such as `original/`, `restored/`, `rollback/`, `archives/`,
or `upgrade-backups/` already exists.

- [ ] **Step 4: Implement the lifecycle phases**

In `run_rehearsal`, create `original`, `restored`, `rollback`, `archives`, `upgrade-backups`, and
raw-doctor paths beneath `config.run_root`. Keep phase-specific command records in each returned
details mapping. Use these exact black-box commands:

```python
[bundlewalker, "init", original]
[bundlewalker, "workspace", "status", original]
[bundlewalker, "doctor", original, "--report", original_raw_report]
[bundlewalker, "workspace", "backup", archive, "--workspace", original]
[bundlewalker, "workspace", "restore", archive, restored]
[bundlewalker, "workspace", "status", restored]
[bundlewalker, "lint"]  # cwd=restored
[bundlewalker, "doctor", restored, "--report", restored_raw_report]
[bundlewalker, "workspace", "upgrade", original, "--backup-dir", upgrade_backups]
[bundlewalker, "workspace", "restore", archive, rollback]
[bundlewalker, "workspace", "status", rollback]
[bundlewalker, "lint"]  # cwd=rollback
[bundlewalker, "doctor", rollback, "--report", rollback_raw_report]
```

Require status output to contain all of:

```text
Workspace format: 1
Compatibility: current
Readable: yes
Writable: yes
Upgrade available: no
```

Require upgrade output to equal `Workspace format 1 is already current.\n`, require
`upgrade-backups` to contain no files, and compare original portable identity before and after the
command. Independently hash `archives/original.zip` and compare it with the one digest parsed from
both backup and restore output.

For each doctor report, load the raw JSON, recursively sanitize it with `sanitize_value`, write the
sanitized object under `config.evidence_dir`, and delete the raw report. Do not copy environment
variables into evidence.

- [ ] **Step 5: Implement the installed MCP handshake**

Store a child-program string in the harness. Invoke it with `sys.executable -c`, the installed MCP
entry point, and rollback path. The child imports only `mcp` and its dependencies, initializes the
server, lists tools, and prints one JSON array:

```python
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
```

Run the probe with a 30-second timeout, require exit `0`, parse stdout as a JSON list of strings,
and pass it through `require_exact_tools`. Never call a tool.

- [ ] **Step 6: Finalize evidence on success and failure**

`main` must initialize evidence before lifecycle work and write `evidence.json` in a `finally`
block. On success, set `result="passed"`; on `RehearsalFailure`, set `result="failed"`, copy its
safe category/message, return `1`, and print only the safe message to stderr. Add environment
metadata, digests, archive bytes, MCP tools, completion time, and final invariants. Unexpected
exceptions use category `harness_internal`, a bounded exception type/message, and return `1` only
after evidence is written.

End the script with:

```python
if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 7: Run focused and integration tests**

```bash
uv run pytest tests/test_production_lifecycle_rehearsal.py -q
uv run ruff format --check scripts/rehearse_production_lifecycle.py tests/test_production_lifecycle_rehearsal.py
uv run ruff check scripts/rehearse_production_lifecycle.py tests/test_production_lifecycle_rehearsal.py
```

Expected: all tests pass; the integration test creates nine passed phases and discovers exactly
ten installed MCP tools.

- [ ] **Step 8: Commit complete harness behavior**

```bash
git add scripts/rehearse_production_lifecycle.py tests/test_production_lifecycle_rehearsal.py
git commit -m "feat: rehearse installed workspace lifecycle"
```

---

### Task 4: Add the manual supported-platform workflow

**Files:**
- Create: `.github/workflows/rehearse-production-lifecycle.yml`
- Modify: `tests/test_project_automation.py`

**Interfaces:**
- Consumes: harness CLI from Task 3.
- Produces: manual workflow input `version` and matrix job `rehearse`.
- Produces: artifact name `production-lifecycle-<version>-<os>-py<python-version>`.

- [ ] **Step 1: Write failing workflow contract tests**

Append a test using existing `_yaml`, `_steps`, `_run_commands`, and
`_assert_actions_are_sha_pinned` helpers:

```python
def test_production_lifecycle_rehearsal_is_manual_read_only_and_supported_only() -> None:
    workflow = _yaml(".github/workflows/rehearse-production-lifecycle.yml")

    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["env"]["UV_VERSION"] == "0.11.28"
    assert set(workflow["on"]) == {"workflow_dispatch"}
    version = workflow["on"]["workflow_dispatch"]["inputs"]["version"]
    assert version == {
        "description": "Exact production PyPI release candidate (0.4.0rcN)",
        "required": "true",
        "type": "string",
    }

    rehearse = workflow["jobs"]["rehearse"]
    assert "environment" not in rehearse
    assert rehearse["strategy"] == {
        "fail-fast": "false",
        "matrix": {
            "os": ["ubuntu-24.04", "macos-15"],
            "python-version": ["3.13", "3.14"],
        },
    }
    assert rehearse["runs-on"] == "${{ matrix.os }}"
    commands = _run_commands(workflow, "rehearse")
    for required in (
        r"0\.4\.0rc[1-9][0-9]*",
        "UV_NO_CONFIG=1",
        "unset PYTHONPATH UV_INDEX UV_INDEX_URL UV_EXTRA_INDEX_URL UV_FIND_LINKS UV_CONFIG_FILE",
        "--default-index https://pypi.org/simple",
        '"bundlewalker==${VERSION}"',
        "scripts/rehearse_production_lifecycle.py",
        'cd "$REHEARSAL_ROOT"',
    ):
        assert required in commands
    assert "test.pypi.org" not in commands.lower()
    assert "dist/" not in commands
    assert "uv sync" not in commands

    upload = _step(workflow, "rehearse", "Upload lifecycle evidence")
    assert upload["if"] == "always()"
    assert upload["with"]["if-no-files-found"] == "error"
    assert upload["with"]["retention-days"] == "90"
    assert "${{ inputs.version }}" in upload["with"]["name"]
    assert "${{ matrix.os }}" in upload["with"]["name"]
    assert "${{ matrix.python-version }}" in upload["with"]["name"]
    _assert_actions_are_sha_pinned(workflow)
```

- [ ] **Step 2: Run the contract test and verify the workflow is absent**

```bash
uv run pytest tests/test_project_automation.py::test_production_lifecycle_rehearsal_is_manual_read_only_and_supported_only -q
```

Expected: failure because `.github/workflows/rehearse-production-lifecycle.yml` does not exist.

- [ ] **Step 3: Create the workflow**

Create `.github/workflows/rehearse-production-lifecycle.yml` with these exact structural elements:

```yaml
name: Rehearse production-installed lifecycle

on:
  workflow_dispatch:
    inputs:
      version:
        description: Exact production PyPI release candidate (0.4.0rcN)
        required: true
        type: string

permissions:
  contents: read

env:
  UV_VERSION: "0.11.28"

jobs:
  rehearse:
    name: Lifecycle (${{ matrix.os }}, Python ${{ matrix.python-version }})
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-24.04, macos-15]
        python-version: ["3.13", "3.14"]
    steps:
      - name: Initialize failure evidence
        shell: bash
        run: |
          REHEARSAL_ROOT="$RUNNER_TEMP/bundlewalker-lifecycle-${GITHUB_RUN_ID}"
          EVIDENCE_DIR="$REHEARSAL_ROOT/evidence"
          mkdir -p "$EVIDENCE_DIR"
          printf '%s\n' '{"schema_version":1,"result":"incomplete","failure_category":"workflow_bootstrap"}' > "$EVIDENCE_DIR/evidence.json"
          printf 'REHEARSAL_ROOT=%s\n' "$REHEARSAL_ROOT" >> "$GITHUB_ENV"
          printf 'EVIDENCE_DIR=%s\n' "$EVIDENCE_DIR" >> "$GITHUB_ENV"
      - name: Check out rehearsal harness
        uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0
        with:
          persist-credentials: false
      - name: Install uv and Python
        uses: astral-sh/setup-uv@11f9893b081a58869d3b5fccaea48c9e9e46f990 # v8.3.2
        with:
          version: ${{ env.UV_VERSION }}
          python-version: ${{ matrix.python-version }}
          enable-cache: false
      - name: Validate exact release candidate
        shell: bash
        env:
          VERSION_INPUT: ${{ inputs.version }}
        run: |
          python -c 'import re, sys; value = sys.argv[1]; assert re.fullmatch(r"0\.4\.0rc[1-9][0-9]*", value)' "$VERSION_INPUT"
          printf 'VERSION=%s\n' "$VERSION_INPUT" >> "$GITHUB_ENV"
      - name: Create isolated production environment
        shell: bash
        run: |
          unset PYTHONPATH UV_INDEX UV_INDEX_URL UV_EXTRA_INDEX_URL UV_FIND_LINKS UV_CONFIG_FILE
          export PYTHONNOUSERSITE=1 UV_NO_CONFIG=1
          VENV="$REHEARSAL_ROOT/venv"
          uv venv --no-config --python "${{ matrix.python-version }}" "$VENV"
          VENV_PYTHON="$VENV/bin/python"
          uv pip install --no-config --python "$VENV_PYTHON" --strict --default-index https://pypi.org/simple "bundlewalker==${VERSION}"
          printf 'VENV=%s\n' "$VENV" >> "$GITHUB_ENV"
          printf 'VENV_PYTHON=%s\n' "$VENV_PYTHON" >> "$GITHUB_ENV"
      - name: Run production-installed rehearsal
        shell: bash
        run: |
          unset PYTHONPATH BUNDLEWALKER_MODEL UV_INDEX UV_INDEX_URL UV_EXTRA_INDEX_URL UV_FIND_LINKS UV_CONFIG_FILE
          export PYTHONNOUSERSITE=1 UV_NO_CONFIG=1
          cp "$GITHUB_WORKSPACE/scripts/rehearse_production_lifecycle.py" "$REHEARSAL_ROOT/rehearse_production_lifecycle.py"
          cd "$REHEARSAL_ROOT"
          "$VENV_PYTHON" "$REHEARSAL_ROOT/rehearse_production_lifecycle.py" \
            --version "$VERSION" \
            --run-root "$REHEARSAL_ROOT" \
            --evidence-dir "$EVIDENCE_DIR" \
            --bundlewalker "$VENV/bin/bundlewalker" \
            --bundlewalker-mcp "$VENV/bin/bundlewalker-mcp"
      - name: Upload lifecycle evidence
        if: always()
        uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1
        with:
          name: production-lifecycle-${{ inputs.version }}-${{ matrix.os }}-py${{ matrix.python-version }}
          path: ${{ runner.temp }}/bundlewalker-lifecycle-${{ github.run_id }}/evidence/
          if-no-files-found: error
          retention-days: 90
```

During implementation, keep the initial evidence JSON valid even for an adversarial unvalidated
version by excluding the version from that bootstrap file. The validated harness overwrites it
with complete evidence.

- [ ] **Step 4: Run workflow contracts and YAML parsing tests**

```bash
uv run pytest tests/test_project_automation.py::test_production_lifecycle_rehearsal_is_manual_read_only_and_supported_only -q
uv run pytest tests/test_project_automation.py -q
```

Expected: both commands pass, including SHA pin validation.

- [ ] **Step 5: Commit workflow automation**

```bash
git add .github/workflows/rehearse-production-lifecycle.yml tests/test_project_automation.py
git commit -m "ci: add production lifecycle rehearsal"
```

---

### Task 5: Publish the pre-run maintainer contract

**Files:**
- Modify: `docs/maintainers/releases.md`
- Modify: `docs/workspace-compatibility.md`
- Modify: `CHANGELOG.md`
- Modify: `tests/test_project_automation.py`
- Modify: `tests/test_release_metadata.py`

**Interfaces:**
- Consumes: workflow and artifact names from Task 4.
- Produces: maintainer dispatch command and immutable-version decision tree.
- Produces: explicit documentation that implementation is not passing live evidence.

- [ ] **Step 1: Write failing documentation contract tests**

Add a project-automation test requiring the dispatch command, four-environment scope, workflow
artifact name, source-isolation statement, and immutable-version policy:

```python
def test_production_lifecycle_rehearsal_policy_is_published_without_premature_claims() -> None:
    releases = (PROJECT_ROOT / "docs/maintainers/releases.md").read_text(encoding="utf-8")
    compatibility = (PROJECT_ROOT / "docs/workspace-compatibility.md").read_text(
        encoding="utf-8"
    )
    changelog = (PROJECT_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    for required in (
        "gh workflow run rehearse-production-lifecycle.yml --ref master -f version=0.4.0rc2",
        "production-lifecycle-0.4.0rc2-<os>-py<python-version>",
        "Ubuntu 24.04",
        "macOS 15",
        "Python 3.13",
        "Python 3.14",
        "does not import BundleWalker from the checkout",
        "workflow implementation is not live rehearsal evidence",
    ):
        assert required in releases
    assert "advance to the next release candidate" in releases
    assert "rerun the same immutable release candidate" in releases
    assert "current format `1`" in compatibility
    assert "real migration rehearsal" in compatibility
    assert "production-installed lifecycle rehearsal workflow" in changelog
    assert "0.4.0rc2 lifecycle rehearsal passed" not in changelog
```

Add a release-metadata assertion that the design, workflow, release procedure, and compatibility
guide agree on `0.4.0rcN`, the four environments, and the absence of Windows certification.

- [ ] **Step 2: Run documentation tests and verify missing policy fails**

```bash
uv run pytest tests/test_project_automation.py::test_production_lifecycle_rehearsal_policy_is_published_without_premature_claims tests/test_release_metadata.py -q
```

Expected: the new policy test fails on the missing dispatch command and workflow language.

- [ ] **Step 3: Add the maintainer rehearsal section**

In `docs/maintainers/releases.md`, insert a section immediately before `Failure and rollback` with:

- the exact dispatch command;
- the exact accepted version shape;
- the four required environments;
- the artifact naming pattern;
- instructions to inspect each `evidence.json` and doctor report;
- the statement “The harness does not import BundleWalker from the checkout”;
- the statement “Workflow implementation is not live rehearsal evidence”;
- the distinction between a harness/workflow defect, which may rerun the same immutable release
  candidate, and a published-package defect, which must advance to the next release candidate;
- a prohibition on local-wheel or TestPyPI fallback; and
- a note that Windows remains experimental and excluded.

Use this dispatch block verbatim:

```bash
gh workflow run rehearse-production-lifecycle.yml --ref master -f version=0.4.0rc2
```

Document artifact names as:

```text
production-lifecycle-0.4.0rc2-<os>-py<python-version>
```

- [ ] **Step 4: Clarify the migration boundary and changelog**

In `docs/workspace-compatibility.md`, state that the production-installed rehearsal proves current
format `1` is a byte-preserving upgrade no-op. It is not a real migration rehearsal; the first
production format transition must separately prove backup-before-mutation, migration, failure
recovery, and rollback from an installed artifact.

Add to `CHANGELOG.md` under `[Unreleased]`:

```markdown
- Added a manual, production-installed lifecycle rehearsal workflow for the supported macOS/Linux
  and Python 3.13/3.14 matrix, with black-box workspace lifecycle and installed MCP discovery plus
  sanitized evidence artifacts. This automation does not itself claim that the live release gate
  has passed.
```

- [ ] **Step 5: Run documentation and link tests**

```bash
uv run pytest tests/test_project_automation.py tests/test_release_metadata.py -q
uv run python - <<'PY'
from pathlib import Path
import re

root = Path.cwd()
for document in root.rglob("*.md"):
    text = document.read_text(encoding="utf-8")
    for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", text):
        if "://" in target or target.startswith("#"):
            continue
        path = (document.parent / target.split("#", 1)[0]).resolve()
        assert path.exists(), (document, target)
PY
```

Expected: all documentation contracts and local links pass.

- [ ] **Step 6: Commit pre-run documentation**

```bash
git add CHANGELOG.md docs/maintainers/releases.md docs/workspace-compatibility.md tests/test_project_automation.py tests/test_release_metadata.py
git commit -m "docs: define lifecycle rehearsal gate"
```

---

### Task 6: Verify the implementation branch and rehearse locally from PyPI

**Files:**
- Modify only if verification exposes a defect in Tasks 1-5.

**Interfaces:**
- Consumes: complete harness, workflow, tests, and documentation.
- Produces: verified implementation branch ready for review; local execution is diagnostic and
  does not close the live GitHub Actions gate.

- [ ] **Step 1: Run the complete offline project gate**

```bash
uv lock --check
uv run pytest -m 'not eval' -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
git diff --check
```

Expected: every command exits `0`.

- [ ] **Step 2: Build and validate distributions without changing the version**

```bash
uv build --clear --no-sources
uv run twine check dist/bundlewalker-0.4.0rc2-py3-none-any.whl dist/bundlewalker-0.4.0rc2.tar.gz
```

Expected: one wheel and one source distribution build, and both pass `twine check`. Do not publish
these local artifacts.

- [ ] **Step 3: Run a local production-PyPI isolation diagnostic**

Create a temporary directory with `mktemp -d`, create a fresh `uv` environment there, install
`bundlewalker==0.4.0rc2` using `--no-config --default-index https://pypi.org/simple`, copy only the
harness, change into the temporary directory, and run the harness with that environment's
entry points. Use `PYTHONNOUSERSITE=1`, unset all index and `PYTHONPATH` variables, and preserve the
temporary path until its `evidence.json` is inspected.

Expected: result `passed`, nine passed phases, identical original/restored/rollback digests, and
exactly ten MCP tools. Record this only as local diagnostic evidence; do not update documentation
to claim the four-job gate passed.

- [ ] **Step 4: Review branch scope**

```bash
git status --short --branch
git log --oneline master..HEAD
git diff --stat master...HEAD
git diff --check master...HEAD
```

Expected: only the approved harness, tests, workflow, plan/spec, release documentation,
compatibility documentation, and changelog are changed; the worktree is clean.

- [ ] **Step 5: Request review through the repository's protected-branch workflow**

Push `codex/production-lifecycle-rehearsal`, open a draft pull request, wait for required supported
CI, inspect the patch and checks, then mark it ready. Do not merge without explicit user approval.

---

### Task 7: Run and record the live gate after merge

**Files:**
- Create after four passing jobs: `docs/maintainers/evidence/2026-07-22-production-lifecycle-0.4.0rc2.md`
- Modify after four passing jobs: `docs/maintainers/releases.md`
- Modify after four passing jobs: `docs/mcp-compatibility.md`
- Modify after four passing jobs: `CHANGELOG.md`
- Modify after four passing jobs: `tests/test_release_metadata.py`

**Interfaces:**
- Consumes: merged workflow on `master` and its four evidence artifacts.
- Produces: durable result record that closes the production-installed lifecycle gate for
  `0.4.0rc2`.

- [ ] **Step 1: Dispatch only from synchronized `master`**

```bash
git switch master
git pull --ff-only origin master
gh workflow run rehearse-production-lifecycle.yml --ref master -f version=0.4.0rc2
```

Resolve the new run ID from the exact workflow name and require its `headBranch` to be `master` and
its `headSha` to equal current `origin/master`.

- [ ] **Step 2: Wait for all four named jobs without assuming success**

```bash
gh run watch "$RUN_ID"
gh run view "$RUN_ID" --json status,conclusion,headBranch,headSha,url,jobs
```

Inspect the four jobs named `Lifecycle (<os>, Python <version>)`. Require four completed jobs and
require each conclusion to be `success`. If any fail, download its evidence before classifying the
failure; do not write a passing result record.

- [ ] **Step 3: Download and independently inspect every artifact**

Download the four exact artifact names. For each `evidence.json`, require:

- schema version `1`;
- requested and installed version `0.4.0rc2`;
- result `passed` and no failure category;
- nine passed phases in the documented order;
- identical original, restored, and rollback portable-tree digests;
- archive digest agreement;
- upgrade no-op with no backup files;
- ten exact MCP tools; and
- no occurrence of the runner's raw temporary root or captured environment variables.

Require three sanitized doctor reports per artifact.

- [ ] **Step 4: Write failing durable-evidence contract tests**

Add a test in `tests/test_release_metadata.py` requiring the evidence record, workflow URL, source
commit, four-environment result table, artifact names, archive digests, and exact installed MCP
claim. Run it and observe failure because the record does not exist.

- [ ] **Step 5: Add the inspected evidence record and update claims**

Create the dated evidence document with only values independently read from the GitHub run and
downloaded artifacts. Update release docs to mark this gate passed for `0.4.0rc2`. Update
`docs/mcp-compatibility.md` only to state that the generic installed `bundlewalker-mcp` entry point
initialized and exposed ten tools on the supported matrix; do not broaden the VS Code-specific
host certification. Add a separate changelog bullet recording the completed live rehearsal.

- [ ] **Step 6: Verify and submit the evidence commit through review**

```bash
uv run pytest tests/test_release_metadata.py tests/test_project_automation.py -q
uv run pytest -m 'not eval' -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
git diff --check
```

Expected: every command exits `0`. Commit the durable evidence on a new `codex/` branch, push it,
and open a pull request. Do not merge without explicit user approval.

## Plan self-review checklist

- Tasks 1-3 cover version validation, source isolation, command bounds/redaction, portable identity,
  archive identity, phase failure evidence, all lifecycle phases, final invariants, and MCP tool
  discovery.
- Task 4 covers manual dispatch, supported matrix, production-PyPI-only installation, bootstrap
  evidence, read-only permissions, SHA-pinned actions, and unconditional artifact upload.
- Task 5 covers maintainer dispatch/failure policy, current-format migration boundaries, and the
  prohibition on premature success claims.
- Task 6 covers complete repository verification and an explicitly non-authoritative local
  production-PyPI diagnostic.
- Task 7 separates post-merge live evidence from gate implementation and requires a second reviewed
  record before the gate is considered complete.
