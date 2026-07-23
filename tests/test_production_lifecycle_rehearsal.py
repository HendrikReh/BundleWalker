# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import importlib.util
import json
import os
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
    with pytest.raises(ValueError, match=r"exact 0.4.0 release candidate"):
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


def test_portable_tree_digest_is_stable_and_excludes_private_state(tmp_path: Path) -> None:
    first = _portable_workspace(tmp_path / "first")
    second = _portable_workspace(tmp_path / "second")
    (first / ".bundlewalker").mkdir()
    (first / ".bundlewalker" / "private.json").write_text("private", encoding="utf-8")

    assert HARNESS.portable_tree_sha256(first) == HARNESS.portable_tree_sha256(second)
    (second / "wiki" / "index.md").write_text("# Changed\n", encoding="utf-8")
    assert HARNESS.portable_tree_sha256(first) != HARNESS.portable_tree_sha256(second)


def test_portable_tree_digest_unambiguously_frames_entries(tmp_path: Path) -> None:
    single_entry = _portable_workspace(tmp_path / "single-entry")
    split_entries = _portable_workspace(tmp_path / "split-entries")
    (single_entry / "raw" / "a").write_bytes(b"alpha\0file\0raw/b\0omega")
    (split_entries / "raw" / "a").write_bytes(b"alpha")
    (split_entries / "raw" / "b").write_bytes(b"omega")

    assert HARNESS.portable_tree_sha256(single_entry) != HARNESS.portable_tree_sha256(split_entries)


@pytest.mark.parametrize("name", ["bundlewalker.toml", "conventions.md"])
def test_portable_tree_digest_requires_regular_file_roots(tmp_path: Path, name: str) -> None:
    workspace = _portable_workspace(tmp_path / name)
    root = workspace / name
    root.unlink()
    root.mkdir()

    with pytest.raises(HARNESS.RehearsalFailure, match="regular file"):
        HARNESS.portable_tree_sha256(workspace)


@pytest.mark.parametrize("name", ["raw", "wiki"])
def test_portable_tree_digest_requires_directory_roots(tmp_path: Path, name: str) -> None:
    workspace = _portable_workspace(tmp_path / name)
    root = workspace / name
    if name == "wiki":
        (root / "index.md").unlink()
        (root / "topics").rmdir()
    root.rmdir()
    root.write_text("not a directory\n", encoding="utf-8")

    with pytest.raises(HARNESS.RehearsalFailure, match="directory"):
        HARNESS.portable_tree_sha256(workspace)


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


def test_require_success_rejects_nonzero_exit_codes() -> None:
    HARNESS.require_success({"exit_code": 0}, category="archive")

    with pytest.raises(HARNESS.RehearsalFailure, match="command failed with exit 7"):
        HARNESS.require_success({"exit_code": 7}, category="archive")
