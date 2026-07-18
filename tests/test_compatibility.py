# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from pathlib import Path

import pytest

import bundlewalker.compatibility as compatibility_module
from bundlewalker.compatibility import (
    CompatibilityStatus,
    MigrationStep,
    inspect_workspace,
    migration_path,
)
from bundlewalker.errors import ConfigurationError
from bundlewalker.transactions import QuiescentWorkspace
from bundlewalker.workspace import Workspace, initialize_workspace


def _write_version(root: Path, version: object) -> None:
    root.mkdir()
    (root / "bundlewalker.toml").write_text(
        f"version = {version}\n"
        'wiki_dir = "wiki"\n'
        'raw_dir = "raw"\n'
        'conventions_file = "conventions.md"\n'
        "max_source_characters = 100000\n",
        encoding="utf-8",
    )


def test_current_workspace_is_readable_writable_and_not_upgradeable(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge")

    result = inspect_workspace(workspace.root)

    assert result.root == workspace.root
    assert result.workspace_format_version == 1
    assert result.status is CompatibilityStatus.CURRENT
    assert result.readable is True
    assert result.writable is True
    assert result.upgrade_available is False


@pytest.mark.parametrize(
    ("version", "status"),
    [(0, CompatibilityStatus.UNSUPPORTED), (2, CompatibilityStatus.TOO_NEW)],
)
def test_noncurrent_well_formed_versions_are_inspection_only(
    tmp_path: Path,
    version: int,
    status: CompatibilityStatus,
) -> None:
    root = tmp_path / f"format-{version}"
    _write_version(root, version)

    result = inspect_workspace(root)

    assert result.workspace_format_version == version
    assert result.status is status
    assert result.readable is False
    assert result.writable is False
    assert result.upgrade_available is False


def test_future_format_remains_inspection_only_for_an_injected_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "format-2"
    _write_version(root, 2)

    def fail_current_parser(_root: Path) -> Workspace:
        raise AssertionError("future formats must not be interpreted as current workspaces")

    monkeypatch.setattr(compatibility_module, "discover_workspace", fail_current_parser)

    result = inspect_workspace(root, target_version=2)

    assert result.status is CompatibilityStatus.TOO_NEW
    assert result.readable is False
    assert result.writable is False
    assert result.upgrade_available is False


@pytest.mark.parametrize("content", ["version = '1'\n", "not toml", "wiki_dir = 'wiki'\n"])
def test_malformed_or_missing_version_is_a_configuration_error(
    tmp_path: Path,
    content: str,
) -> None:
    root = tmp_path / "invalid"
    root.mkdir()
    (root / "bundlewalker.toml").write_text(content, encoding="utf-8")

    with pytest.raises(ConfigurationError):
        inspect_workspace(root)


def test_migration_path_requires_a_complete_contiguous_chain() -> None:
    def apply(_quiescent: QuiescentWorkspace) -> None:
        return None

    def verify(_workspace: Workspace) -> None:
        return None

    steps = {
        1: MigrationStep(1, 2, apply, verify),
        2: MigrationStep(2, 3, apply, verify),
    }

    assert migration_path(1, target_version=3, migrations=steps) == (
        steps[1],
        steps[2],
    )
    assert migration_path(1, target_version=4, migrations=steps) is None
    assert migration_path(3, target_version=3, migrations=steps) == ()
    assert migration_path(4, target_version=3, migrations=steps) is None


def test_upgradeable_status_uses_an_injected_complete_registry(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge")

    def apply(_quiescent: QuiescentWorkspace) -> None:
        return None

    def verify(_workspace: Workspace) -> None:
        return None

    step = MigrationStep(1, 2, apply, verify)
    result = inspect_workspace(
        workspace.root,
        target_version=2,
        migrations={1: step},
    )

    assert result.status is CompatibilityStatus.UPGRADEABLE
    assert result.readable is False
    assert result.writable is False
    assert result.upgrade_available is True
