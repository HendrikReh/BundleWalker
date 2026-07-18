# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from bundlewalker import workspace as workspace_module
from bundlewalker.cli import app
from bundlewalker.conventions import ConventionsStyle, load_conventions
from bundlewalker.interfaces.cli import confirm_changes
from bundlewalker.okf.lint import has_errors, lint_bundle

runner = CliRunner()


def test_init_creates_a_lint_clean_workspace(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"

    result = runner.invoke(app, ["init", str(root)])

    assert result.exit_code == 0, result.output
    assert str(root.resolve()) in result.output
    assert (root / "bundlewalker.toml").is_file()
    assert (root / "conventions.md").is_file()
    assert (root / "raw").is_dir()
    for category in ("sources", "topics", "entities", "syntheses"):
        assert (root / "wiki" / category).is_dir()
        assert (root / "wiki" / category / "index.md").is_file()
    assert (root / "wiki" / "index.md").is_file()
    log = (root / "wiki" / "log.md").read_text(encoding="utf-8")
    assert log.count("**Initialization**") == 1
    assert not has_errors(lint_bundle(root / "wiki", root))


@pytest.mark.parametrize("style", list(ConventionsStyle))
def test_init_selects_the_requested_conventions_style(
    tmp_path: Path,
    style: ConventionsStyle,
) -> None:
    root = tmp_path / style.value

    result = runner.invoke(
        app,
        ["init", str(root), "--conventions-style", style.value],
    )

    assert result.exit_code == 0, result.output
    assert result.output == f"Initialized BundleWalker workspace at {root.resolve()}\n"
    assert (root / "conventions.md").read_text(encoding="utf-8") == load_conventions(style)
    assert not has_errors(lint_bundle(root / "wiki", root))


def test_init_help_lists_all_conventions_styles() -> None:
    result = runner.invoke(app, ["init", "--help"])

    assert result.exit_code == 0, result.output
    assert "--conventions-style" in result.output
    for style in ConventionsStyle:
        assert style.value in result.output


def test_init_rejects_an_unknown_conventions_style_before_creating_target(
    tmp_path: Path,
) -> None:
    root = tmp_path / "knowledge"

    result = runner.invoke(
        app,
        ["init", str(root), "--conventions-style", "unknown-style"],
    )

    assert result.exit_code == 2
    assert "--conventions-style" in result.output
    assert not root.exists()


def test_init_rejects_a_non_empty_target_with_usage_exit_code(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    root.mkdir()
    marker = root / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    result = runner.invoke(app, ["init", str(root)])

    assert result.exit_code == 2
    assert "empty" in result.output.lower()
    assert marker.read_text(encoding="utf-8") == "keep"


def test_failed_init_removes_only_command_created_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "existing-empty"
    root.mkdir()
    sibling = tmp_path / "keep.txt"
    sibling.write_text("keep", encoding="utf-8")

    def fail_indexes(_root: Path) -> None:
        raise OSError("simulated index failure")

    monkeypatch.setattr(workspace_module, "regenerate_indexes", fail_indexes)

    result = runner.invoke(app, ["init", str(root)])

    assert result.exit_code == 1
    assert "initialize" in result.output.lower()
    assert root.is_dir()
    assert list(root.iterdir()) == []
    assert sibling.read_text(encoding="utf-8") == "keep"


def test_confirmation_framework_abort_is_a_clean_unchanged_exit() -> None:
    review_app = typer.Typer()

    def review() -> None:
        confirm_changes()

    review_app.command()(review)
    result = runner.invoke(review_app, [], input="")

    assert result.exit_code == 0
    assert "No changes applied." in result.output
    assert "Aborted" not in result.output
