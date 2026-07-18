# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from bundlewalker.backups import create_workspace_backup, verify_backup_archive
from bundlewalker.compatibility import CompatibilityStatus, inspect_workspace
from bundlewalker.errors import ConfigurationError
from bundlewalker.okf.repository import OkfRepository
from bundlewalker.transactions import get_pending_review, recover_transactions
from bundlewalker.workspace import discover_workspace

FIXTURES = Path(__file__).parent / "fixtures" / "historical"


@pytest.mark.parametrize("release", ["v1", "v2", "v3"])
def test_released_clean_workspace_remains_current_and_readable(
    tmp_path: Path,
    release: str,
) -> None:
    root = tmp_path / release
    shutil.copytree(FIXTURES / f"{release}-clean", root)

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
) -> None:
    root = tmp_path / release
    shutil.copytree(FIXTURES / f"{release}-clean", root)
    workspace = discover_workspace(root)

    verified = create_workspace_backup(workspace, tmp_path / f"{release}.zip")

    assert verified.manifest.workspace_format_version == 1
    assert verify_backup_archive(verified.archive_path) == verified


def test_v1_interrupted_schema1_transaction_recovers_exact_base(tmp_path: Path) -> None:
    root = tmp_path / "legacy"
    shutil.copytree(FIXTURES / "v1-schema1-swapping", root)
    expected = (root / "expected-base.sha256").read_text(encoding="utf-8").strip()
    (root / "expected-base.sha256").unlink()
    workspace = discover_workspace(root)

    recover_transactions(workspace)

    assert _tree_digest(workspace.wiki_dir) == expected
    assert not any((root / ".bundlewalker/transactions").iterdir())


def test_v3_pending_review_remains_pending(tmp_path: Path) -> None:
    root = tmp_path / "pending"
    shutil.copytree(FIXTURES / "v3-schema2-pending", root)
    workspace = discover_workspace(root)

    pending = get_pending_review(workspace)

    assert pending is not None
    assert pending.kind.value == "ingestion"
    assert pending.status.value == "pending"


def test_static_provenance_pins_release_commits() -> None:
    provenance = json.loads((FIXTURES / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["v1"]["commit"] == "be165ac283ba7511592771fd876c89b12ef4ff1a"
    assert provenance["v2"]["commit"] == "12ef119ac3b2ba84cff7ca9aee0fbf14b239d975"
    assert provenance["v3"]["commit"] == "ab079a16a98cc31c46f77db73c941328c886075b"
    assert {provenance[release]["expected_compatibility"] for release in ("v1", "v2", "v3")} == {
        "current"
    }
    assert provenance["fixtures"]["v1-schema1-swapping"] == "recovers_base"
    assert provenance["fixtures"]["v3-schema2-pending"] == "pending_review"


@pytest.mark.parametrize(
    ("name", "status"),
    [
        ("invalid-format-zero", CompatibilityStatus.UNSUPPORTED),
        ("future-format", CompatibilityStatus.TOO_NEW),
    ],
)
def test_well_formed_incompatible_fixtures_are_inspection_only(
    name: str,
    status: CompatibilityStatus,
) -> None:
    assert inspect_workspace(FIXTURES / name).status is status


def test_malformed_fixture_is_a_configuration_error() -> None:
    with pytest.raises(ConfigurationError):
        inspect_workspace(FIXTURES / "invalid-malformed")


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
