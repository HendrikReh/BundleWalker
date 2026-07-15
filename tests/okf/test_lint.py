from __future__ import annotations

import hashlib
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from bundlewalker.domain import FindingOrigin, LintFinding, OkfDocument, Severity
from bundlewalker.okf import lint as lint_module
from bundlewalker.okf.derived import prepend_log_entry, regenerate_indexes
from bundlewalker.okf.documents import parse_document
from bundlewalker.okf.lint import has_errors, lint_bundle

FIXTURE = Path(__file__).parents[1] / "fixtures" / "wiki-valid"


def _copy_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "wiki"
    shutil.copytree(FIXTURE, root)
    return root


def _write_concept(
    root: Path,
    concept_id: str,
    metadata: dict[str, Any],
    body: str,
) -> None:
    path = root / f"{concept_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True)
    path.write_text(f"---\n{frontmatter}---\n{body}", encoding="utf-8")


def _findings_with_code(findings: list[LintFinding], code: str) -> list[LintFinding]:
    return [finding for finding in findings if finding.code == code]


def test_valid_bundle_has_no_findings(tmp_path: Path) -> None:
    assert lint_bundle(_copy_fixture(tmp_path)) == []


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("# Missing frontmatter\n", "missing frontmatter"),
        ("---\ntype: ''\n---\n", "invalid frontmatter"),
    ],
)
def test_parse_failures_are_aggregated_as_okf_errors(
    tmp_path: Path,
    content: str,
    message: str,
) -> None:
    root = tmp_path / "wiki"
    root.mkdir()
    (root / "broken.md").write_text(content, encoding="utf-8")

    findings = _findings_with_code(lint_bundle(root), "OKF001")

    assert len(findings) == 1
    assert findings[0].severity is Severity.ERROR
    assert findings[0].path == "broken.md"
    assert message in findings[0].message


def test_case_folded_concept_collision_is_an_okf_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "wiki"
    metadata = {"type": "Topic", "title": "One", "description": "A concept."}
    _write_concept(root, "topics/first", metadata, "\n# One\n")
    _write_concept(root, "topics/second", metadata, "\n# Two\n")
    regenerate_indexes(root)
    real_parse_document = parse_document

    def parse_with_collision(path: Path, bundle_root: Path) -> OkfDocument:
        document = real_parse_document(path, bundle_root)
        concept_id = "topics/Straße" if path.stem == "first" else "topics/STRASSE"
        return document.model_copy(update={"concept_id": concept_id})

    monkeypatch.setattr(lint_module, "parse_document", parse_with_collision)

    collisions = _findings_with_code(lint_bundle(root), "OKF001")

    assert len(collisions) == 1
    assert collisions[0].severity is Severity.ERROR
    assert "collision" in collisions[0].message
    assert collisions[0].path == "topics/second.md"


@pytest.mark.parametrize(
    ("relative_path", "replacement", "message"),
    [
        ("index.md", "# Stale\n", "stale"),
        ("topics/index.md", None, "missing"),
    ],
)
def test_stale_and_missing_indexes_are_errors(
    tmp_path: Path,
    relative_path: str,
    replacement: str | None,
    message: str,
) -> None:
    root = _copy_fixture(tmp_path)
    path = root / relative_path
    if replacement is None:
        path.unlink()
    else:
        path.write_text(replacement, encoding="utf-8")

    findings = _findings_with_code(lint_bundle(root), "INDEX001")

    assert len(findings) == 1
    assert findings[0].severity is Severity.ERROR
    assert findings[0].path == relative_path
    assert message in findings[0].message


def test_invalid_log_date_is_an_error(tmp_path: Path) -> None:
    root = _copy_fixture(tmp_path)
    (root / "log.md").write_text(
        "# Knowledge Update Log\n\n## 2026-02-30\n\n* **Update**: Impossible.\n",
        encoding="utf-8",
    )

    findings = _findings_with_code(lint_bundle(root), "LOG001")

    assert len(findings) == 1
    assert findings[0].severity is Severity.ERROR
    assert findings[0].path == "log.md"
    assert "2026-02-30" in findings[0].message


def test_broken_internal_link_is_a_warning(tmp_path: Path) -> None:
    root = _copy_fixture(tmp_path)
    agents = root / "topics" / "agents.md"
    agents.write_text(
        agents.read_text(encoding="utf-8").replace(
            "[Agents](/topics/agents.md)", "[Missing](/topics/missing.md)"
        ),
        encoding="utf-8",
    )

    findings = _findings_with_code(lint_bundle(root), "LINK001")

    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING
    assert findings[0].path == "topics/agents.md"
    assert "/topics/missing.md" in findings[0].message


def test_malformed_internal_target_does_not_abort_other_lint_passes(tmp_path: Path) -> None:
    root = _copy_fixture(tmp_path)
    agents = root / "topics" / "agents.md"
    agents.write_text(
        agents.read_text(encoding="utf-8").replace("[Agents](/topics/agents.md)", "[bad](%00)"),
        encoding="utf-8",
    )
    (root / "log.md").write_text(
        "# Knowledge Update Log\n\n## 2026-02-30\n\n* **Update**: Impossible.\n",
        encoding="utf-8",
    )

    findings = lint_bundle(root)

    assert any(
        finding.code == "LINK001"
        and finding.path == "topics/agents.md"
        and "%00" in finding.message
        for finding in findings
    )
    assert any(finding.code == "LOG001" and finding.path == "log.md" for finding in findings)


def test_concept_without_inbound_concept_links_is_an_orphan_warning(tmp_path: Path) -> None:
    root = _copy_fixture(tmp_path)
    _write_concept(
        root,
        "topics/orphan",
        {"type": "Source", "title": "Orphan", "description": "No inbound links."},
        "\n# Orphan\n",
    )
    regenerate_indexes(root)

    findings = _findings_with_code(lint_bundle(root), "ORPHAN001")

    assert [(finding.path, finding.severity) for finding in findings] == [
        ("topics/orphan.md", Severity.WARNING)
    ]


def test_unknown_types_and_extra_metadata_are_accepted(tmp_path: Path) -> None:
    root = _copy_fixture(tmp_path)
    agents = root / "topics" / "agents.md"
    agents.write_text(
        agents.read_text(encoding="utf-8")
        .replace("type: Topic", "type: Experimental")
        .replace("title: Agents", "title: Agents\nowner: Hendrik"),
        encoding="utf-8",
    )
    regenerate_indexes(root)

    assert lint_bundle(root) == []


def test_findings_are_sorted_by_severity_code_path_and_message(tmp_path: Path) -> None:
    root = _copy_fixture(tmp_path)
    (root / "index.md").write_text("stale\n", encoding="utf-8")
    agents = root / "topics" / "agents.md"
    agents.write_text(
        agents.read_text(encoding="utf-8").replace(
            "[Agents](/topics/agents.md)", "[Missing](/z-missing.md)"
        ),
        encoding="utf-8",
    )

    findings = lint_bundle(root)
    severity_order = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
    keys = [
        (
            severity_order[finding.severity],
            finding.code,
            finding.path or "",
            finding.message,
        )
        for finding in findings
    ]

    assert keys == sorted(keys)


def test_has_errors_only_matches_error_severity() -> None:
    warning = LintFinding(
        origin=FindingOrigin.DETERMINISTIC,
        severity=Severity.WARNING,
        code="TEST001",
        message="Warning only.",
    )
    error = warning.model_copy(update={"severity": Severity.ERROR})

    assert not has_errors([warning])
    assert has_errors([warning, error])


def _make_workspace_bundle(tmp_path: Path) -> tuple[Path, Path, dict[str, Any]]:
    workspace = tmp_path / "workspace"
    wiki = workspace / "wiki"
    raw_path = workspace / "raw" / "source.txt"
    raw_path.parent.mkdir(parents=True)
    raw_bytes = b"line one\nline two\n"
    raw_path.write_bytes(raw_bytes)
    digest = hashlib.sha256(raw_bytes).hexdigest()
    source_metadata: dict[str, Any] = {
        "type": "Source",
        "title": "Source",
        "description": "Raw evidence.",
        "resource": f"urn:bundlewalker:source:sha256:{digest}",
        "source_sha256": digest,
        "raw_path": "raw/source.txt",
    }
    _write_concept(
        wiki,
        "sources/source",
        source_metadata,
        "\n# Source\n\nSee [Agents](/topics/agents.md).\n",
    )
    _write_concept(
        wiki,
        "topics/agents",
        {"type": "Topic", "title": "Agents", "description": "Agent notes."},
        (
            "\n# Agents\n\nA claim [1].\n\n# Citations\n\n"
            "[1] [Source](/sources/source.md) — raw lines 1\N{EN DASH}2\n"
        ),
    )
    regenerate_indexes(wiki)
    prepend_log_entry(
        wiki,
        "Created the fixture.",
        date=datetime(2026, 7, 15, tzinfo=UTC),
        kind="Initialization",
    )
    return workspace, wiki, source_metadata


def test_valid_workspace_extensions_and_citations_have_no_findings(tmp_path: Path) -> None:
    workspace, wiki, _ = _make_workspace_bundle(tmp_path)

    assert lint_bundle(wiki, workspace) == []


@pytest.mark.parametrize("field", ["resource", "source_sha256", "raw_path"])
def test_source_extension_fields_are_required(
    tmp_path: Path,
    field: str,
) -> None:
    workspace, wiki, metadata = _make_workspace_bundle(tmp_path)
    metadata.pop(field)
    _write_concept(
        wiki,
        "sources/source",
        metadata,
        "\n# Source\n\nSee [Agents](/topics/agents.md).\n",
    )
    regenerate_indexes(wiki)

    findings = _findings_with_code(lint_bundle(wiki, workspace), "SOURCE001")

    assert len(findings) == 1
    assert field in findings[0].message
    assert all(finding.severity is Severity.ERROR for finding in findings)


def test_source_raw_path_cannot_escape_workspace(tmp_path: Path) -> None:
    workspace, wiki, metadata = _make_workspace_bundle(tmp_path)
    metadata["raw_path"] = "../outside.txt"
    _write_concept(
        wiki,
        "sources/source",
        metadata,
        "\n# Source\n\nSee [Agents](/topics/agents.md).\n",
    )
    regenerate_indexes(wiki)

    findings = _findings_with_code(lint_bundle(wiki, workspace), "SOURCE001")

    assert any(
        "raw_path" in finding.message and "workspace" in finding.message for finding in findings
    )


def test_source_raw_path_must_be_below_raw_directory(tmp_path: Path) -> None:
    workspace, wiki, metadata = _make_workspace_bundle(tmp_path)
    other_path = workspace / "elsewhere" / "source.txt"
    other_path.parent.mkdir()
    shutil.copyfile(workspace / "raw" / "source.txt", other_path)
    metadata["raw_path"] = "elsewhere/source.txt"
    _write_concept(
        wiki,
        "sources/source",
        metadata,
        "\n# Source\n\nSee [Agents](/topics/agents.md).\n",
    )
    regenerate_indexes(wiki)

    findings = _findings_with_code(lint_bundle(wiki, workspace), "SOURCE001")

    assert len(findings) == 1
    assert "raw_path must be below raw/" in findings[0].message


def test_source_digest_must_match_raw_bytes(tmp_path: Path) -> None:
    workspace, wiki, metadata = _make_workspace_bundle(tmp_path)
    wrong_digest = "0" * 64
    metadata["source_sha256"] = wrong_digest
    metadata["resource"] = f"urn:bundlewalker:source:sha256:{wrong_digest}"
    _write_concept(
        wiki,
        "sources/source",
        metadata,
        "\n# Source\n\nSee [Agents](/topics/agents.md).\n",
    )
    regenerate_indexes(wiki)

    findings = _findings_with_code(lint_bundle(wiki, workspace), "SOURCE001")

    assert any("does not match raw bytes" in finding.message for finding in findings)


def test_citation_markers_must_match_references(tmp_path: Path) -> None:
    workspace, wiki, _ = _make_workspace_bundle(tmp_path)
    topic = wiki / "topics" / "agents.md"
    topic.write_text(
        topic.read_text(encoding="utf-8").replace("A claim [1].", "A claim [2]."),
        encoding="utf-8",
    )

    findings = _findings_with_code(lint_bundle(wiki, workspace), "CITATION001")

    assert len(findings) == 1
    assert findings[0].severity is Severity.ERROR
    assert findings[0].path == "topics/agents.md"
    assert "markers" in findings[0].message and "references" in findings[0].message


def test_malformed_citation_target_is_a_link_warning_and_citation_error(
    tmp_path: Path,
) -> None:
    workspace, wiki, _ = _make_workspace_bundle(tmp_path)
    topic = wiki / "topics" / "agents.md"
    topic.write_text(
        topic.read_text(encoding="utf-8").replace("/sources/source.md", "%00"),
        encoding="utf-8",
    )

    findings = lint_bundle(wiki, workspace)

    assert any(
        finding.code == "LINK001" and finding.path == "topics/agents.md" for finding in findings
    )
    assert any(
        finding.code == "CITATION001"
        and finding.path == "topics/agents.md"
        and "does not reference an existing concept" in finding.message
        for finding in findings
    )


@pytest.mark.parametrize("span", ["1\N{EN DASH}3", "2\N{EN DASH}1"])
def test_citation_line_ranges_must_fit_raw_source(
    tmp_path: Path,
    span: str,
) -> None:
    workspace, wiki, _ = _make_workspace_bundle(tmp_path)
    topic = wiki / "topics" / "agents.md"
    topic.write_text(
        topic.read_text(encoding="utf-8").replace("raw lines 1\N{EN DASH}2", f"raw lines {span}"),
        encoding="utf-8",
    )

    findings = _findings_with_code(lint_bundle(wiki, workspace), "CITATION001")

    assert len(findings) == 1
    assert findings[0].severity is Severity.ERROR
    assert findings[0].path == "topics/agents.md"
    assert "line range" in findings[0].message
