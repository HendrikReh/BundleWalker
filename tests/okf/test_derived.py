from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote

from bundlewalker.okf.derived import (
    prepend_log_entry,
    regenerate_indexes,
    tree_diff,
)
from bundlewalker.okf.documents import extract_links


def _write_concept(
    root: Path,
    concept_id: str,
    *,
    title: str,
    description: str,
    suffix: str = ".md",
) -> None:
    path = root / f"{concept_id}{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ntype: Topic\ntitle: {title}\ndescription: {description}\ntags: []\n---\n\n# Notes\n",
        encoding="utf-8",
    )


def test_regenerate_indexes_creates_stable_okf_navigation(tmp_path: Path) -> None:
    root = tmp_path / "wiki"
    _write_concept(
        root,
        "root-note",
        title="Root Note",
        description="A top-level concept.",
    )
    _write_concept(
        root,
        "topics/zulu",
        title="Zulu",
        description="Sorted second by ID.",
    )
    _write_concept(
        root,
        "topics/alpha",
        title="Alpha",
        description="Sorted first by ID.",
    )
    _write_concept(
        root,
        "topics/nested/deep",
        title="Deep",
        description="Nested concept.",
    )
    (root / "entities").mkdir()
    (root / "topics" / "index.md").write_text("stale", encoding="utf-8")

    regenerate_indexes(root)

    assert (root / "index.md").read_text(encoding="utf-8") == (
        "# Knowledge Index\n\n"
        "## Directories\n\n"
        "* [Entities](entities/index.md) - Browse Entities concepts.\n"
        "* [Topics](topics/index.md) - Browse Topics concepts.\n\n"
        "## Concepts\n\n"
        "* [Root Note](root-note.md) - A top-level concept.\n"
    )
    assert (root / "topics" / "index.md").read_text(encoding="utf-8") == (
        "# Topics\n\n"
        "## Directories\n\n"
        "* [Nested](nested/index.md) - Browse Nested concepts.\n\n"
        "## Concepts\n\n"
        "* [Alpha](alpha.md) - Sorted first by ID.\n"
        "* [Zulu](zulu.md) - Sorted second by ID.\n"
    )
    assert (root / "topics" / "nested" / "index.md").read_text(encoding="utf-8") == (
        "# Nested\n\n## Concepts\n\n* [Deep](deep.md) - Nested concept.\n"
    )
    assert (root / "entities" / "index.md").read_text(encoding="utf-8") == ("# Entities\n")
    assert "---" not in (root / "index.md").read_text(encoding="utf-8")


def test_regenerate_indexes_preserves_and_encodes_real_targets(tmp_path: Path) -> None:
    root = tmp_path / "wiki"
    _write_concept(
        root,
        "topics/Case File",
        title=r"Case [Name] \ Guide",
        description="A mixed-case suffix.",
        suffix=".MD",
    )
    _write_concept(
        root,
        "topics/More [Notes]/Deep File",
        title="Deep File",
        description="A nested mixed-case suffix.",
        suffix=".Md",
    )

    regenerate_indexes(root)

    topics_index_path = root / "topics" / "index.md"
    topics_index = topics_index_path.read_text(encoding="utf-8")
    topics_targets = extract_links(topics_index)
    assert topics_targets == (
        "More%20%5BNotes%5D/index.md",
        "Case%20File.MD",
    )
    assert r"[Case \[Name\] \\ Guide](Case%20File.MD)" in topics_index
    for target in topics_targets:
        assert (topics_index_path.parent / unquote(target)).exists()

    nested_index_path = root / "topics" / "More [Notes]" / "index.md"
    nested_targets = extract_links(nested_index_path.read_text(encoding="utf-8"))
    assert nested_targets == ("Deep%20File.Md",)
    assert (nested_index_path.parent / unquote(nested_targets[0])).exists()


def test_prepend_log_entry_creates_newest_date_first(tmp_path: Path) -> None:
    root = tmp_path / "wiki"

    prepend_log_entry(
        root,
        "Initialized the workspace.",
        date=datetime(2026, 7, 14, 10, tzinfo=UTC),
        kind="Initialization",
    )
    prepend_log_entry(
        root,
        "Added agent notes.",
        date=datetime(2026, 7, 15, 9, tzinfo=UTC),
    )

    assert (root / "log.md").read_text(encoding="utf-8") == (
        "# Knowledge Update Log\n\n"
        "## 2026-07-15\n\n"
        "* **Update**: Added agent notes.\n\n"
        "## 2026-07-14\n\n"
        "* **Initialization**: Initialized the workspace.\n"
    )


def test_prepend_log_entry_inserts_same_day_entry_first(tmp_path: Path) -> None:
    root = tmp_path / "wiki"
    date = datetime(2026, 7, 15, 9, tzinfo=UTC)
    prepend_log_entry(root, "First update.", date=date)

    prepend_log_entry(
        root,
        "Later synthesis.",
        date=datetime(2026, 7, 15, 17, tzinfo=UTC),
        kind="Synthesis",
    )

    assert (root / "log.md").read_text(encoding="utf-8") == (
        "# Knowledge Update Log\n\n"
        "## 2026-07-15\n\n"
        "* **Synthesis**: Later synthesis.\n"
        "* **Update**: First update.\n"
    )


def test_tree_diff_uses_wiki_paths_and_stable_file_order(tmp_path: Path) -> None:
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (old / "a-deleted.md").write_text("gone\n", encoding="utf-8")
    (old / "m-changed.md").write_text("before\n", encoding="utf-8")
    (new / "m-changed.md").write_text("after\n", encoding="utf-8")
    (new / "z-created.md").write_text("new\n", encoding="utf-8")

    diff = tree_diff(old, new)

    assert diff.index("--- wiki/a-deleted.md") < diff.index("--- wiki/m-changed.md")
    assert diff.index("--- wiki/m-changed.md") < diff.index("--- /dev/null")
    assert "+++ /dev/null" in diff
    assert "--- /dev/null\n+++ wiki/z-created.md" in diff
    assert "-before\n+after\n" in diff


def test_tree_diff_ignores_unchanged_files(tmp_path: Path) -> None:
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (old / "same.md").write_text("same\n", encoding="utf-8")
    (new / "same.md").write_text("same\n", encoding="utf-8")

    assert tree_diff(old, new) == ""


def test_tree_diff_separates_replacement_lines_without_final_newlines(
    tmp_path: Path,
) -> None:
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (old / "changed.md").write_text("before", encoding="utf-8")
    (new / "changed.md").write_text("after", encoding="utf-8")

    diff = tree_diff(old, new)

    assert ("-before\n\\ No newline at end of file\n+after\n\\ No newline at end of file\n") in diff
    assert "-before+after" not in diff


def test_tree_diff_reports_adding_only_the_final_newline(tmp_path: Path) -> None:
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (old / "changed.md").write_text("same", encoding="utf-8")
    (new / "changed.md").write_text("same\n", encoding="utf-8")

    diff = tree_diff(old, new)

    assert "-same\n\\ No newline at end of file\n+same\n" in diff


def test_tree_diff_reports_removing_only_the_final_newline(tmp_path: Path) -> None:
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (old / "changed.md").write_text("same\n", encoding="utf-8")
    (new / "changed.md").write_text("same", encoding="utf-8")

    diff = tree_diff(old, new)

    assert "-same\n+same\n\\ No newline at end of file\n" in diff
