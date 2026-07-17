from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import bundlewalker.workspace as workspace_module
from bundlewalker.conventions import ConventionsStyle, load_conventions
from bundlewalker.errors import WorkspaceError
from bundlewalker.okf.derived import regenerate_indexes
from bundlewalker.okf.lint import has_errors, lint_bundle
from bundlewalker.workspace import (
    DEFAULT_CONFIG_TEXT,
    discover_workspace,
    initialize_workspace,
    load_inline_source,
    load_raw_source,
    stable_source_paths,
)


def _write_source_concept(
    workspace_root: Path,
    *,
    concept_id: str,
    digest: str,
    raw_path: str,
) -> None:
    path = workspace_root / "wiki" / f"{concept_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        "type: Source\n"
        "title: Existing source\n"
        "description: An existing immutable source.\n"
        f"resource: urn:bundlewalker:source:sha256:{digest}\n"
        f"source_sha256: {digest}\n"
        f"raw_path: {raw_path}\n"
        "tags: []\n"
        "---\n\n"
        "# Existing source\n",
        encoding="utf-8",
    )
    regenerate_indexes(workspace_root / "wiki")


def test_initialize_writes_exact_default_config_and_discovery_walks_upward(
    tmp_path: Path,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge")
    nested = workspace.wiki_dir / "topics" / "nested"
    nested.mkdir()

    discovered = discover_workspace(nested)

    assert (workspace.root / "bundlewalker.toml").read_text(encoding="utf-8") == (
        DEFAULT_CONFIG_TEXT
    )
    assert workspace.conventions_file.read_text(encoding="utf-8") == load_conventions(
        ConventionsStyle.DEFAULT
    )
    assert discovered == workspace
    assert discovered.config.version == 1
    assert discovered.config.max_source_characters == 100_000


@pytest.mark.parametrize("style", list(ConventionsStyle))
def test_initialize_writes_selected_conventions_and_remains_lint_clean(
    tmp_path: Path,
    style: ConventionsStyle,
) -> None:
    workspace = initialize_workspace(
        tmp_path / style.value,
        conventions_style=style,
    )

    assert workspace.conventions_file.read_text(encoding="utf-8") == load_conventions(style)
    assert not has_errors(lint_bundle(workspace.wiki_dir, workspace.root))


@pytest.mark.parametrize("preexisting_root", [False, True])
def test_initialize_rolls_back_a_conventions_loader_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    preexisting_root: bool,
) -> None:
    root = tmp_path / "knowledge"
    if preexisting_root:
        root.mkdir()
    sibling = tmp_path / "keep.txt"
    sibling.write_text("keep", encoding="utf-8")

    def fail_loader(_style: ConventionsStyle) -> str:
        raise WorkspaceError("could not load conventions style: research-agent")

    monkeypatch.setattr(workspace_module, "load_conventions", fail_loader)

    with pytest.raises(WorkspaceError, match="could not load conventions style"):
        initialize_workspace(
            root,
            conventions_style=ConventionsStyle.RESEARCH_AGENT,
        )

    if preexisting_root:
        assert root.is_dir()
        assert list(root.iterdir()) == []
    else:
        assert not root.exists()
    assert sibling.read_text(encoding="utf-8") == "keep"


def test_discovery_rejects_paths_outside_a_workspace(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceError, match=r"bundlewalker\.toml"):
        discover_workspace(tmp_path)


@pytest.mark.parametrize("name", ["source.MD", "source.rst", "source"])
def test_load_raw_source_rejects_unsupported_extensions(
    tmp_path: Path,
    name: str,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge")
    source = tmp_path / name
    source.write_text("content", encoding="utf-8")

    with pytest.raises(WorkspaceError, match=r"\.md.*\.txt"):
        load_raw_source(source, workspace)


def test_load_raw_source_rejects_unsupported_extensions_before_reading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge")
    source = tmp_path / "source.pdf"
    source.write_text("content", encoding="utf-8")

    def fail_read_bytes(_path: Path) -> bytes:
        raise AssertionError("unsupported source files must not be read")

    monkeypatch.setattr(Path, "read_bytes", fail_read_bytes)

    with pytest.raises(WorkspaceError, match=r"\.md.*\.txt"):
        load_raw_source(source, workspace)


def test_load_raw_source_rejects_directories_and_symlinks(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge")
    directory = tmp_path / "directory.md"
    directory.mkdir()
    regular = tmp_path / "regular.md"
    regular.write_text("content", encoding="utf-8")
    symlink = tmp_path / "symlink.md"
    symlink.symlink_to(regular)

    with pytest.raises(WorkspaceError, match="regular file"):
        load_raw_source(directory, workspace)
    with pytest.raises(WorkspaceError, match="regular file"):
        load_raw_source(symlink, workspace)


def test_load_raw_source_requires_strict_utf8(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge")
    source = tmp_path / "invalid.txt"
    source.write_bytes(b"valid\xffinvalid")

    with pytest.raises(WorkspaceError, match="UTF-8"):
        load_raw_source(source, workspace)


def test_load_raw_source_enforces_character_limit_not_byte_limit(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge")
    accepted = tmp_path / "accepted.txt"
    accepted.write_text("é" * 100_000, encoding="utf-8")
    rejected = tmp_path / "rejected.txt"
    rejected.write_text("é" * 100_001, encoding="utf-8")

    assert len(load_raw_source(accepted, workspace).text) == 100_000
    with pytest.raises(WorkspaceError, match="100000"):
        load_raw_source(rejected, workspace)


def test_load_raw_source_hashes_exact_bytes_and_derives_stable_identity(
    tmp_path: Path,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge")
    source = tmp_path / "Über  Agents!.md"
    content = b"first\r\nsecond\n"
    source.write_bytes(content)

    loaded = load_raw_source(source, workspace)
    digest = hashlib.sha256(content).hexdigest()

    assert loaded.input_path == source.resolve()
    assert loaded.content == content
    assert loaded.text == "first\r\nsecond\n"
    assert loaded.sha256 == digest
    assert loaded.line_count == 2
    assert loaded.extension == ".md"
    assert loaded.slug == "uber-agents"
    assert loaded.stored_relative_path == Path(f"raw/{digest[:12]}-uber-agents.md")
    assert loaded.concept_id == f"sources/{digest[:12]}-uber-agents"


def test_load_inline_source_builds_the_same_identity_from_supplied_utf8(
    tmp_path: Path,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge")

    source = load_inline_source("Überblick.md", "Grüße\n", workspace)

    assert source.content == "Grüße\n".encode("utf-8")
    assert source.text == "Grüße\n"
    assert source.extension == ".md"
    assert source.slug == "uberblick"
    assert source.line_count == 1
    assert source.sha256 == hashlib.sha256(source.content).hexdigest()
    assert source.input_path == Path("Überblick.md")
    assert source.stored_relative_path.parent == Path("raw")


@pytest.mark.parametrize(
    "name",
    [
        "../notes.md",
        "folder/notes.md",
        r"folder\\notes.md",
        "bad\x7fname.md",
        ".",
        "..",
        "notes.pdf",
    ],
)
def test_load_inline_source_rejects_paths_and_unsupported_names(
    tmp_path: Path,
    name: str,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge")

    with pytest.raises(WorkspaceError):
        load_inline_source(name, "content\n", workspace)


def test_load_inline_source_enforces_configured_character_limit(
    tmp_path: Path,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge")
    config_path = workspace.root / "bundlewalker.toml"
    config_path.write_text(
        DEFAULT_CONFIG_TEXT.replace("max_source_characters = 100000", "max_source_characters = 2"),
        encoding="utf-8",
    )
    workspace = discover_workspace(workspace.root)

    assert load_inline_source("accepted.txt", "éé", workspace).text == "éé"
    with pytest.raises(WorkspaceError, match="2"):
        load_inline_source("rejected.txt", "ééé", workspace)


def test_load_inline_source_does_not_read_a_filesystem_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge")

    def fail_read_bytes(_path: Path) -> bytes:
        raise AssertionError("inline sources must not read from the filesystem")

    monkeypatch.setattr(Path, "read_bytes", fail_read_bytes)

    assert load_inline_source("notes.md", "content\n", workspace).text == "content\n"


def test_stable_source_paths_resolves_duplicate_by_full_digest(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge")
    digest = hashlib.sha256(b"same bytes").hexdigest()
    raw_path = f"raw/{digest[:16]}-original.txt"
    _write_source_concept(
        workspace.root,
        concept_id=f"sources/{digest[:16]}-original",
        digest=digest,
        raw_path=raw_path,
    )

    stored_path, concept_id = stable_source_paths(
        workspace,
        digest,
        "different-name",
        ".txt",
    )

    assert stored_path == Path(raw_path)
    assert concept_id == f"sources/{digest[:16]}-original"


def test_stable_source_paths_lengthens_colliding_digest_prefix(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge")
    incoming_digest = "0123456789ab0" + "a" * 51
    existing_digest = "0123456789ab1" + "b" * 51
    _write_source_concept(
        workspace.root,
        concept_id="sources/0123456789ab1-existing",
        digest=existing_digest,
        raw_path="raw/0123456789ab1-existing.md",
    )

    stored_path, concept_id = stable_source_paths(
        workspace,
        incoming_digest,
        "incoming",
        ".md",
    )

    assert stored_path == Path("raw/0123456789ab0-incoming.md")
    assert concept_id == "sources/0123456789ab0-incoming"


def test_stable_source_paths_avoids_an_occupied_custom_concept_id(
    tmp_path: Path,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge")
    digest = "abcdef1234560" + "a" * 51
    occupied = workspace.wiki_dir / f"sources/{digest[:12]}-incoming.md"
    occupied.write_text(
        "---\n"
        "type: Experimental\n"
        "title: Existing custom concept\n"
        "description: A permissive OKF type already owns this concept ID.\n"
        "---\n\n"
        "# Existing custom concept\n",
        encoding="utf-8",
    )
    regenerate_indexes(workspace.wiki_dir)

    stored_path, concept_id = stable_source_paths(
        workspace,
        digest,
        "incoming",
        ".md",
    )

    assert stored_path == Path(f"raw/{digest[:13]}-incoming.md")
    assert concept_id == f"sources/{digest[:13]}-incoming"


@pytest.mark.parametrize("configured_raw_dir", ["archive", "archive/"])
def test_lint_uses_the_workspace_configured_raw_directory(
    tmp_path: Path,
    configured_raw_dir: str,
) -> None:
    initialized = initialize_workspace(tmp_path / "knowledge")
    config_path = initialized.root / "bundlewalker.toml"
    config_path.write_text(
        DEFAULT_CONFIG_TEXT.replace('raw_dir = "raw"', f'raw_dir = "{configured_raw_dir}"'),
        encoding="utf-8",
    )
    initialized.raw_dir.rename(initialized.root / "archive")
    workspace = discover_workspace(initialized.root)
    assert workspace.config.raw_dir == "archive"
    content = b"configured source\n"
    digest = hashlib.sha256(content).hexdigest()
    raw_path = workspace.raw_dir / f"{digest[:12]}-configured.txt"
    raw_path.write_bytes(content)
    _write_source_concept(
        workspace.root,
        concept_id=f"sources/{digest[:12]}-configured",
        digest=digest,
        raw_path=raw_path.relative_to(workspace.root).as_posix(),
    )

    findings = lint_bundle(workspace.wiki_dir, workspace.root)

    assert not has_errors(findings)
    assert not any(finding.code == "SOURCE001" for finding in findings)
