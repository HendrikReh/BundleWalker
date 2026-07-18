# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from bundlewalker.backups import (
    create_workspace_backup,
    restore_workspace_backup,
    verify_backup_archive,
)
from bundlewalker.compatibility import CompatibilityStatus, inspect_workspace
from bundlewalker.errors import ConfigurationError
from bundlewalker.okf.repository import OkfRepository
from bundlewalker.transactions import get_pending_review, recover_transactions
from bundlewalker.workspace import Workspace, discover_workspace
from tests.historical_fixtures import HistoricalFixtures, copy_file_representation

SOURCE_FIXTURES = Path(__file__).parent / "fixtures" / "historical"


@pytest.fixture
def historical_fixtures(tmp_path: Path) -> HistoricalFixtures:
    represented = tmp_path / "represented-historical-fixtures"
    copy_file_representation(SOURCE_FIXTURES, represented)
    return HistoricalFixtures(represented)


def test_file_only_representation_restores_release_owned_empty_directories(
    historical_fixtures: HistoricalFixtures,
    tmp_path: Path,
) -> None:
    for name in ("v1-clean", "v2-clean", "v3-clean", "v3-schema2-pending"):
        root = historical_fixtures.materialize(name, tmp_path / f"materialized-{name}")

        assert (root / "raw").is_dir()
        assert list((root / "raw").iterdir()) == []
        assert not (root / "empty-directories.json").exists()


@pytest.mark.parametrize("release", ["v1", "v2", "v3"])
def test_released_clean_workspace_remains_current_and_readable(
    tmp_path: Path,
    release: str,
    historical_fixtures: HistoricalFixtures,
) -> None:
    root = historical_fixtures.materialize(f"{release}-clean", tmp_path / release)

    compatibility = inspect_workspace(root)
    workspace = discover_workspace(root)
    documents = OkfRepository(workspace.wiki_dir).scan()

    assert compatibility.status is CompatibilityStatus.CURRENT
    assert compatibility.workspace_format_version == 1
    assert "sources/index" not in documents
    assert (workspace.wiki_dir / "index.md").is_file()


@pytest.mark.parametrize("release", ["v1", "v2", "v3"])
def test_released_clean_workspace_creates_a_current_verified_backup(
    tmp_path: Path,
    release: str,
    historical_fixtures: HistoricalFixtures,
) -> None:
    root = historical_fixtures.materialize(f"{release}-clean", tmp_path / release)
    workspace = discover_workspace(root)

    verified = create_workspace_backup(workspace, tmp_path / f"{release}.zip")

    assert verified.manifest.workspace_format_version == 1
    assert verify_backup_archive(verified.archive_path) == verified


@pytest.mark.parametrize("release", ["v1", "v2", "v3"])
def test_released_workspace_round_trips_through_backup_and_restore(
    tmp_path: Path,
    release: str,
    historical_fixtures: HistoricalFixtures,
) -> None:
    source = historical_fixtures.materialize(
        f"{release}-clean",
        tmp_path / f"{release}-source",
    )
    archive = tmp_path / f"{release}.zip"
    original = discover_workspace(source)
    create_workspace_backup(original, archive)

    restored = restore_workspace_backup(archive, tmp_path / f"{release}-restored")

    assert _workspace_bytes(restored.workspace) == _workspace_bytes(original)
    assert set(OkfRepository(restored.workspace.wiki_dir).scan()) == set(
        OkfRepository(original.wiki_dir).scan()
    )
    assert (restored.workspace.wiki_dir / "index.md").is_file()


def test_v1_interrupted_schema1_transaction_recovers_exact_base(
    tmp_path: Path,
    historical_fixtures: HistoricalFixtures,
) -> None:
    root = historical_fixtures.materialize("v1-schema1-swapping", tmp_path / "legacy")
    expected = (root / "expected-base.sha256").read_text(encoding="utf-8").strip()
    (root / "expected-base.sha256").unlink()
    workspace = discover_workspace(root)

    recover_transactions(workspace)

    assert _tree_digest(workspace.wiki_dir) == expected
    assert not any((root / ".bundlewalker/transactions").iterdir())


def test_v3_pending_review_remains_pending(
    tmp_path: Path,
    historical_fixtures: HistoricalFixtures,
) -> None:
    root = historical_fixtures.materialize("v3-schema2-pending", tmp_path / "pending")
    workspace = discover_workspace(root)

    pending = get_pending_review(workspace)

    assert pending is not None
    assert pending.kind.value == "ingestion"
    assert pending.status.value == "pending"


def test_static_provenance_pins_release_commits(
    historical_fixtures: HistoricalFixtures,
) -> None:
    provenance = historical_fixtures.read_metadata("provenance.json")
    releases = {name: cast(dict[str, object], provenance[name]) for name in ("v1", "v2", "v3")}
    assert releases["v1"]["commit"] == "be165ac283ba7511592771fd876c89b12ef4ff1a"
    assert releases["v2"]["commit"] == "12ef119ac3b2ba84cff7ca9aee0fbf14b239d975"
    assert releases["v3"]["commit"] == "ab079a16a98cc31c46f77db73c941328c886075b"
    assert {releases[release]["expected_compatibility"] for release in releases} == {"current"}
    fixtures = cast(dict[str, object], provenance["fixtures"])
    representation = cast(dict[str, object], provenance["representation"])
    assert fixtures["v1-schema1-swapping"] == "recovers_base"
    assert fixtures["v3-schema2-pending"] == "pending_review"
    assert representation == {
        "schema_version": 1,
        "empty_directories": "empty-directories.json",
        "ownership": "bundlewalker_fixture_representation",
    }
    assert not list(SOURCE_FIXTURES.rglob(".gitkeep"))


@pytest.mark.parametrize(
    ("name", "status"),
    [
        ("invalid-format-zero", CompatibilityStatus.UNSUPPORTED),
        ("future-format", CompatibilityStatus.TOO_NEW),
    ],
)
def test_well_formed_incompatible_fixtures_are_inspection_only(
    tmp_path: Path,
    name: str,
    status: CompatibilityStatus,
    historical_fixtures: HistoricalFixtures,
) -> None:
    root = historical_fixtures.materialize(name, tmp_path / name)

    assert inspect_workspace(root).status is status


def test_malformed_fixture_is_a_configuration_error(
    tmp_path: Path,
    historical_fixtures: HistoricalFixtures,
) -> None:
    root = historical_fixtures.materialize("invalid-malformed", tmp_path / "invalid-malformed")

    with pytest.raises(ConfigurationError):
        inspect_workspace(root)


def _tree_digest(root: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda value: value.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode()
        if path.is_dir():
            digest.update(b"D" + len(relative).to_bytes(8, "big") + relative)
        elif path.is_file() and not path.is_symlink():
            content = path.read_bytes()
            digest.update(b"F" + len(relative).to_bytes(8, "big") + relative)
            digest.update(len(content).to_bytes(8, "big") + content)
    return digest.hexdigest()


def _workspace_bytes(workspace: Workspace) -> dict[str, bytes]:
    roots = (
        workspace.root / "bundlewalker.toml",
        workspace.conventions_file,
        workspace.raw_dir,
        workspace.wiki_dir,
    )
    files: dict[str, bytes] = {}
    for root in roots:
        candidates = (root,) if root.is_file() else tuple(sorted(root.rglob("*")))
        for candidate in candidates:
            if candidate.is_file() and not candidate.is_symlink():
                files[candidate.relative_to(workspace.root).as_posix()] = candidate.read_bytes()
    return files
