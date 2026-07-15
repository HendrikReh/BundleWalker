from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from bundlewalker.okf.derived import (
    prepend_log_entry,
    regenerate_indexes,
    tree_diff,
)


def _write_concept(
    root: Path,
    concept_id: str,
    *,
    title: str,
    description: str,
) -> None:
    path = root / f"{concept_id}.md"
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
