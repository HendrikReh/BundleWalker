# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

import hashlib
import importlib.metadata
import importlib.util
import json
import re
import shlex
import shutil
import subprocess
import tarfile
import tomllib
from dataclasses import dataclass, replace
from importlib.metadata import version as distribution_version
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

import pytest
import yaml
from markdown_it import MarkdownIt

import bundlewalker
from benchmarks.contracts import EvidenceRecord
from benchmarks.evidence import load_evidence
from benchmarks.report import render_report
from bundlewalker.application import (
    DiagnosticsApplication,
    DiagnosticsDependencies,
    DiagnosticSeverity,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = PROJECT_ROOT / "benchmarks/evidence"

REVIEWED_EVIDENCE_SHA256 = {
    "suite-1-dfaa31dfca3a431e7b2e2cb1ceda1e2cc0df286c-Linux-py3.13-29789436063.json": (
        "cb22e213cbd7af4ac7203d055cab95b1207d5d232a2daf8fe2bf60f677d2d645"
    ),
    "suite-1-dfaa31dfca3a431e7b2e2cb1ceda1e2cc0df286c-Linux-py3.14-29789436063.json": (
        "6abfd90b0fba6b2f7fcbcffd6aa6e7ef91a485262bceac5cab6e49f815c8311e"
    ),
    "suite-1-dfaa31dfca3a431e7b2e2cb1ceda1e2cc0df286c-macOS-py3.13-29789436063.json": (
        "624a81b85f69b41bec7680c3b69b1ec45e6f8b91c9f0303ec0ed36d953ff4b84"
    ),
    "suite-1-dfaa31dfca3a431e7b2e2cb1ceda1e2cc0df286c-macOS-py3.14-29789436063.json": (
        "5edc699e5fd4fd2becf6d52d24bd471d93e9b287f585a194742664df1fbe6689"
    ),
}

LICENSE_EXPRESSION = "GPL-3.0-or-later AND CC0-1.0"
LICENSE_FILES = [
    "LICENSE",
    "LICENSES/CC0-1.0.txt",
    "LICENSE-SCOPE.md",
    "THIRD_PARTY_NOTICES.md",
]
OFFICIAL_LICENSE_SHA256 = {
    "LICENSE": "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986",
    "LICENSES/CC0-1.0.txt": "a2010f343487d3f7618affe54f789f5487602331c0a8d03f49e9a7c547cf0499",
}
CC0_PRESET_PATHS = {
    "src/bundlewalker/convention_presets/agent-context.md",
    "src/bundlewalker/convention_presets/default.md",
    "src/bundlewalker/convention_presets/personal-workbook.md",
    "src/bundlewalker/convention_presets/research-agent.md",
    "src/bundlewalker/convention_presets/software-agent.md",
}
PYTHON_HEADER = "# Copyright (C) 2026 Hendrik Reh\n# SPDX-License-Identifier: GPL-3.0-or-later\n"
ACTIVE_DOCUMENTATION = (
    Path("README.md"),
    Path("CHANGELOG.md"),
    Path("CONTRIBUTING.md"),
    Path("LICENSE-SCOPE.md"),
    Path("SECURITY.md"),
    Path("SUPPORT.md"),
    Path("docs/hermes-mcp-setup.md"),
    Path("docs/maintainers/releases.md"),
    Path("docs/performance-and-capacity.md"),
    Path("docs/tutorial.md"),
    Path("docs/user-guide.md"),
    Path("docs/workspace-compatibility.md"),
)


def _github_anchor(text: str) -> str:
    without_punctuation = re.sub(r"[^\w\- ]", "", text.strip().casefold())
    return re.sub(r"\s+", "-", without_punctuation)


def _heading_anchors(markdown: str) -> frozenset[str]:
    anchors: set[str] = set()
    occurrences: dict[str, int] = {}
    tokens = MarkdownIt("commonmark").parse(markdown)
    for index, token in enumerate(tokens[:-1]):
        if token.type != "heading_open":
            continue
        inline = tokens[index + 1]
        text = "".join(
            child.content
            for child in inline.children or ()
            if child.type in {"text", "code_inline"}
        )
        base = _github_anchor(text)
        occurrence = occurrences.get(base, 0)
        occurrences[base] = occurrence + 1
        anchors.add(base if occurrence == 0 else f"{base}-{occurrence}")
    return frozenset(anchors)


@dataclass(frozen=True)
class PublishedCapacity:
    profile_name: str
    document_count: int
    wiki_bytes: int
    source_characters: int


def _reviewed_evidence() -> tuple[tuple[Path, EvidenceRecord], ...]:
    return tuple((path, load_evidence(path)) for path in sorted(EVIDENCE_ROOT.glob("*.json")))


def _published_capacity(records: tuple[EvidenceRecord, ...]) -> PublishedCapacity:
    report = render_report(records, provisional=False, require_matrix=True)
    match = re.search(
        r"^Supported capacity: (?P<profile>[A-Z][A-Za-z]+) "
        r"\((?P<documents>\d+) documents, (?P<wiki_bytes>\d+) profile wiki bytes, "
        r"(?P<source_characters>\d+) ingestion source characters\)$",
        report,
        re.MULTILINE,
    )
    assert match is not None
    capacity = PublishedCapacity(
        profile_name=match.group("profile").casefold(),
        document_count=int(match.group("documents")),
        wiki_bytes=int(match.group("wiki_bytes")),
        source_characters=int(match.group("source_characters")),
    )
    profiles = [profile for profile in records[0].profiles if profile.name == capacity.profile_name]
    assert len(profiles) == 1
    assert (
        profiles[0].document_count,
        profiles[0].target_wiki_bytes,
        profiles[0].source_characters,
    ) == (
        capacity.document_count,
        capacity.wiki_bytes,
        capacity.source_characters,
    )
    return capacity


def _published_capacity_sentence(capacity: PublishedCapacity) -> str:
    return (
        f"Supported capacity is {capacity.document_count:,} knowledge documents, approximately "
        f"{capacity.wiki_bytes / (1024**2):g} MiB of wiki content, and a "
        f"{capacity.source_characters:,}-character ingestion source."
    )


def _published_evidence_links(
    evidence: tuple[tuple[Path, EvidenceRecord], ...],
) -> frozenset[str]:
    records = tuple(record for _, record in evidence)
    commits = {record.git_commit for record in records}
    run_ids = {record.run_id for record in records}
    assert len(commits) == len(run_ids) == 1
    commit = commits.pop()
    run_id = run_ids.pop()
    github_run_id = run_id.removeprefix("github-")
    return frozenset(
        {
            f"https://github.com/HendrikReh/BundleWalker/commit/{commit}",
            f"https://github.com/HendrikReh/BundleWalker/actions/runs/{github_run_id}",
            *(f"../benchmarks/evidence/{path.name}" for path, _ in evidence),
            "../benchmarks/evidence/report.md",
        }
    )


def _reference_environment(record: EvidenceRecord) -> str:
    environment = record.environment
    assert environment.filesystem_type is not None
    assert environment.runner_image is not None
    return (
        f"{environment.os_name} {environment.os_release}, "
        f"{environment.python_implementation} {environment.python_version}, "
        f"{environment.architecture}, {environment.filesystem_type} "
        f"(runner {environment.runner_image})"
    )


def _checkpoint_maximum(records: tuple[EvidenceRecord, ...], capacity: PublishedCapacity) -> int:
    return max(
        byte_count
        for record in records
        for scenario in record.scenarios
        if scenario.profile == capacity.profile_name
        for byte_count in scenario.checkpoint_bytes.values()
    )


def _supported_capacity_sentences(markdown: str) -> frozenset[str]:
    text_parts: list[str] = []
    for token in MarkdownIt("commonmark").parse(markdown):
        if token.type != "inline":
            continue
        inline_parts: list[str] = []
        for child in token.children or ():
            if child.type in {"text", "code_inline"}:
                inline_parts.append(child.content)
            elif child.type in {"softbreak", "hardbreak"}:
                inline_parts.append(" ")
        text_parts.append("".join(inline_parts))

    normalized_text = re.sub(r"\s+", " ", " ".join(text_parts)).strip()
    sentences = {
        match.group(0).strip() for match in re.finditer(r"[^.!?]+[.!?](?=\s|$)", normalized_text)
    }
    return frozenset(
        sentence
        for sentence in sentences
        if re.search(r"\bsupported\b", sentence, re.IGNORECASE)
        and re.search(r"\bcapacity\b", sentence, re.IGNORECASE)
    )


def _assert_published_capacity_claim(markdown: str, capacity: PublishedCapacity) -> None:
    assert _supported_capacity_sentences(markdown) == {_published_capacity_sentence(capacity)}


def test_release_versions_are_consistent() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((PROJECT_ROOT / "uv.lock").read_text(encoding="utf-8"))
    editable_package = next(
        package
        for package in lock["package"]
        if package["name"] == "bundlewalker" and package.get("source") == {"editable": "."}
    )

    expected = project["project"]["version"]
    assert bundlewalker.__version__ == expected
    assert distribution_version("bundlewalker") == expected
    assert editable_package["version"] == expected


def test_current_dependency_policy_declares_supported_floors() -> None:
    locked = tomllib.loads((PROJECT_ROOT / "uv.lock").read_text(encoding="utf-8"))
    locked_names = {package["name"] for package in locked["package"]}
    assert {"pydantic-ai", "typer", "ruff"} <= locked_names

    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "pydantic-ai>=2.10.0" in project["project"]["dependencies"]
    assert "typer>=0.16.0" in project["project"]["dependencies"]
    assert "ruff>=0.12.0" in project["dependency-groups"]["dev"]


def test_active_documentation_local_links_and_anchors_resolve() -> None:
    parser = MarkdownIt("commonmark")
    for relative in ACTIVE_DOCUMENTATION:
        source = PROJECT_ROOT / relative
        markdown = source.read_text(encoding="utf-8")
        for token in parser.parse(markdown):
            for child in token.children or ():
                if child.type != "link_open":
                    continue
                href = child.attrGet("href")
                assert isinstance(href, str)
                parsed = urlsplit(href)
                if parsed.scheme or parsed.netloc:
                    continue
                target = source if not parsed.path else source.parent / unquote(parsed.path)
                target = target.resolve()
                assert target.is_file(), f"{relative}: missing link target {href}"
                if parsed.fragment and target.suffix.casefold() == ".md":
                    anchors = _heading_anchors(target.read_text(encoding="utf-8"))
                    fragment = unquote(parsed.fragment).casefold()
                    assert fragment in anchors, f"{relative}: missing anchor {href}"


def test_performance_document_publishes_reviewed_capacity_derived_from_evidence_and_is_linked() -> (
    None
):
    performance_path = PROJECT_ROOT / "docs/performance-and-capacity.md"
    performance = performance_path.read_text(encoding="utf-8")
    markdown = MarkdownIt("commonmark")
    evidence = _reviewed_evidence()
    records = tuple(record for _, record in evidence)
    capacity = _published_capacity(records)

    assert performance.count(_published_capacity_sentence(capacity)) == 1
    assert "Status: reviewed evidence" in performance
    assert f"{_checkpoint_maximum(records, capacity):,} bytes" in performance
    assert "1-GiB free-space advisory" in performance
    assert "remote model-provider latency is excluded" in performance
    assert "Windows remains experimental" in performance
    assert "public beta" in performance
    assert "proof of concept" not in performance.casefold()
    assert "release candidate" not in performance.casefold()

    _assert_published_capacity_claim(performance, capacity)
    assert "Supported capacity is not yet published." not in performance
    assert "candidate only" not in performance
    assert re.search(r"\bbeta\s+(?:is\s+)?complete\b", performance, re.IGNORECASE) is None
    assert re.search(r"\b(?:release|version)\s+(?:is|:|\d)", performance, re.IGNORECASE) is None

    linked_hrefs = {
        child.attrGet("href")
        for token in markdown.parse(performance)
        for child in token.children or ()
        if child.type == "link_open" and isinstance(child.attrGet("href"), str)
    }
    assert linked_hrefs >= _published_evidence_links(evidence)

    for environment in (_reference_environment(record) for record in records):
        assert environment in performance

    profile_section = performance.partition("## Profiles\n")[2].partition("\n## ")[0]
    profile_names = {"Smoke", "Small", "Medium", "Large", "Probe"}
    profile_rows = tuple(
        cells
        for line in profile_section.splitlines()
        if line.startswith("|")
        and (cells := tuple(cell.strip() for cell in line.strip("|").split("|")))[0]
        in profile_names
    )
    assert profile_rows == tuple(
        (
            profile.name.capitalize(),
            f"{profile.document_count:,}",
            f"{profile.target_wiki_bytes / (1024**2):g} MiB",
            f"{profile.source_characters:,} Unicode characters",
        )
        for profile in records[0].profiles
    )

    scenario_section = performance.partition("### Scenario inventory\n")[2].partition(
        "\n### Timing boundary"
    )[0]
    scenario_lines = tuple(
        line for line in scenario_section.splitlines() if re.fullmatch(r"\d+\. .+", line)
    )
    assert scenario_lines == (
        "1. Workspace initialization (`initialize`).",
        "2. Workspace status (`status`).",
        "3. First-page concept listing (`list_concepts`).",
        "4. End-of-order concept reading (`read_concept`).",
        "5. Lexical present-result search (`search_present`).",
        "6. Lexical absent-result search (`search_absent`).",
        "7. Deterministic lint (`lint`).",
        "8. MCP startup and discovery (`mcp_startup`).",
        "9. Ingestion preparation (`prepare_ingestion`).",
        "10. Review commit (`commit`).",
        "11. Prepared-review recovery (`recover_prepared`).",
        "12. Swapping-boundary recovery (`recover_swapping`).",
    )

    normalized_whitespace = " ".join(performance.split())
    for timing_contract in (
        "fixture generation and preparation are excluded from timing",
        "controller workspace copying is excluded from timing",
        "ordinary Python worker startup is excluded from timing",
        "ordinary scenario timers bracket only the specified production call",
        "process launch and protocol initialization through sorted tool discovery",
        "clean shutdown happens after the timer stops",
    ):
        assert timing_contract in normalized_whitespace

    benchmark_commands = {
        tuple(shlex.split(token.content.replace("\\\n", " ")))
        for token in markdown.parse(performance)
        if token.type == "fence"
        and token.info.strip() == "text"
        and token.content.startswith("uv run python -m benchmarks run")
    }
    assert benchmark_commands == {
        (
            "uv",
            "run",
            "python",
            "-m",
            "benchmarks",
            "run",
            "--profiles",
            "smoke",
            "--correctness-only",
            "--output",
            "benchmark-results/smoke.json",
        ),
        (
            "uv",
            "run",
            "python",
            "-m",
            "benchmarks",
            "run",
            "--profiles",
            "smoke,small,medium,large,probe",
            "--output",
            "benchmark-results/local.json",
        ),
    }
    assert "available from a repository checkout" in performance
    assert "intentionally absent from installed wheels and source distributions" in performance

    for relative in ("README.md", "SUPPORT.md", "docs/user-guide.md"):
        source = PROJECT_ROOT / relative
        targets: set[Path] = set()
        for token in markdown.parse(source.read_text(encoding="utf-8")):
            for child in token.children or ():
                if child.type != "link_open":
                    continue
                href = child.attrGet("href")
                if not isinstance(href, str):
                    continue
                target = href.partition("#")[0]
                if target:
                    targets.add((source.parent / target).resolve())
        assert performance_path.resolve() in targets


def test_performance_document_marks_reported_large_and_probe_boundaries_unsupported() -> None:
    records = tuple(record for _, record in _reviewed_evidence())
    report = render_report(records, provisional=False, require_matrix=True)
    boundary_labels = tuple(
        match.group("profile")
        for line in report.splitlines()
        if (
            match := re.fullmatch(
                r"Unsupported boundary evidence: (?P<profile>[A-Z][A-Za-z]+) \(.+\)\.", line
            )
        )
    )
    performance = (PROJECT_ROOT / "docs/performance-and-capacity.md").read_text(encoding="utf-8")

    assert f"{' and '.join(boundary_labels)} are unsupported boundary evidence." in performance


@pytest.mark.parametrize(
    "affirmative_claim",
    [
        "BundleWalker has a supported workspace capacity of 50 MiB.",
        "A capacity of 50 MiB is supported.",
        "A CAPACITY of 50 MiB is SUPPORTED.",
    ],
)
def test_performance_contract_rejects_another_supported_capacity_claim(
    affirmative_claim: str,
) -> None:
    performance = (PROJECT_ROOT / "docs/performance-and-capacity.md").read_text(encoding="utf-8")
    capacity = _published_capacity(tuple(record for _, record in _reviewed_evidence()))

    with pytest.raises(AssertionError):
        _assert_published_capacity_claim(f"{performance}\n\n{affirmative_claim}\n", capacity)


@pytest.mark.parametrize(
    "error_type",
    [importlib.metadata.PackageNotFoundError, OSError, PermissionError],
)
def test_package_import_and_diagnostics_survive_unavailable_distribution_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[Exception],
) -> None:
    def unavailable_version(_distribution_name: str) -> str:
        raise error_type("bundlewalker")

    monkeypatch.setattr(importlib.metadata, "version", unavailable_version)
    package_init = PROJECT_ROOT / "src/bundlewalker/__init__.py"
    spec = importlib.util.spec_from_file_location("isolated_bundlewalker", package_init)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)

    spec.loader.exec_module(module)

    assert module.__version__ == ""
    result = DiagnosticsApplication(
        replace(DiagnosticsDependencies(), bundlewalker_version=module.__version__)
    ).run(tmp_path)
    checks = {check.code: check for check in result.checks}
    assert len(result.checks) == 14
    assert result.bundlewalker_version == "unknown"
    assert checks["runtime.bundlewalker"].severity is DiagnosticSeverity.FAILURE


def test_package_import_preserves_unexpected_distribution_metadata_defects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def defective_version(_distribution_name: str) -> str:
        raise RuntimeError("unexpected metadata defect")

    monkeypatch.setattr(importlib.metadata, "version", defective_version)
    package_init = PROJECT_ROOT / "src/bundlewalker/__init__.py"
    spec = importlib.util.spec_from_file_location("isolated_bundlewalker_defect", package_init)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)

    with pytest.raises(RuntimeError, match="unexpected metadata defect"):
        spec.loader.exec_module(module)


def test_public_package_metadata_is_complete() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]

    assert project["authors"] == [{"name": "Hendrik Reh"}]
    assert project["maintainers"] == [{"name": "Hendrik Reh"}]
    assert project["keywords"] == [
        "knowledge-base",
        "markdown",
        "mcp",
        "okf",
        "pydantic-ai",
    ]
    assert project["classifiers"] == [
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "Operating System :: MacOS",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.13",
        "Programming Language :: Python :: 3.14",
        "Topic :: Documentation",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
    ]
    assert project["urls"] == {
        "Homepage": "https://github.com/HendrikReh/BundleWalker",
        "Documentation": "https://github.com/HendrikReh/BundleWalker#documentation",
        "Repository": "https://github.com/HendrikReh/BundleWalker",
        "Issues": "https://github.com/HendrikReh/BundleWalker/issues",
        "Changelog": "https://github.com/HendrikReh/BundleWalker/blob/master/CHANGELOG.md",
    }


def test_declared_documented_and_diagnostic_python_support_agree(tmp_path: Path) -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    public_setup_documents = {
        "README.md": "BundleWalker requires Python 3.13 or 3.14",
        "docs/user-guide.md": "BundleWalker requires Python 3.13 or 3.14",
        "docs/tutorial.md": "You need Python 3.13 or 3.14",
    }

    assert project["requires-python"] == ">=3.13,<3.15"
    for relative, support_statement in public_setup_documents.items():
        content = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
        assert support_statement in content
        assert "Python 3.13 or newer" not in content
    support = (PROJECT_ROOT / "SUPPORT.md").read_text(encoding="utf-8")
    releases = (PROJECT_ROOT / "docs/maintainers/releases.md").read_text(encoding="utf-8")
    assert "Python 3.13 and 3.14 are supported" in support
    assert "both Python 3.13 and 3.14" in releases

    expected_support = {
        (3, 12, 9): DiagnosticSeverity.FAILURE,
        (3, 13, 0): DiagnosticSeverity.PASS,
        (3, 14, 9): DiagnosticSeverity.PASS,
        (3, 15, 0): DiagnosticSeverity.FAILURE,
    }
    for python_version, expected_severity in expected_support.items():
        result = DiagnosticsApplication(
            replace(DiagnosticsDependencies(), python_version=python_version)
        ).run(tmp_path)
        checks = {check.code: check for check in result.checks}
        assert checks["runtime.python"].severity is expected_severity


def test_license_metadata_and_files_are_declared() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["license"] == LICENSE_EXPRESSION
    assert project["project"]["license-files"] == LICENSE_FILES
    assert all((PROJECT_ROOT / relative).is_file() for relative in LICENSE_FILES)


def test_browser_dependency_notices_cover_locked_production_packages() -> None:
    lock = json.loads((PROJECT_ROOT / "frontend/package-lock.json").read_text(encoding="utf-8"))
    notices = (PROJECT_ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    packages = lock["packages"]

    direct_dependencies = {
        "@tanstack/react-query",
        "react",
        "react-dom",
        "react-markdown",
        "react-router",
        "remark-gfm",
    }
    assert set(packages[""]["dependencies"]) == direct_dependencies
    assert "| `react-router-dom` |" not in notices

    production_inventory: set[tuple[str, str, str]] = set()
    for package_path, metadata in packages.items():
        if not package_path.startswith("node_modules/") or metadata.get("dev") is True:
            continue
        package_name = package_path.rsplit("node_modules/", maxsplit=1)[1]
        production_inventory.add((package_name, metadata["version"], metadata["license"]))

    assert production_inventory
    for package_name, version, license_name in production_inventory:
        assert f"| `{package_name}` | `{version}` | {license_name} |" in notices
    assert "## MIT License" in notices
    assert "## ISC License" in notices


def test_official_license_texts_are_unmodified() -> None:
    for relative, expected_digest in OFFICIAL_LICENSE_SHA256.items():
        content = (PROJECT_ROOT / relative).read_bytes()
        assert hashlib.sha256(content).hexdigest() == expected_digest


def test_reviewed_benchmark_evidence_has_complete_immutable_provenance() -> None:
    paths = tuple(sorted(EVIDENCE_ROOT.glob("*.json")))
    assert tuple(path.name for path in paths) == tuple(REVIEWED_EVIDENCE_SHA256)

    expected_manifest = "".join(
        f"{digest}  {name}\n" for name, digest in REVIEWED_EVIDENCE_SHA256.items()
    )
    assert (EVIDENCE_ROOT / "SHA256SUMS").read_text(encoding="ascii") == expected_manifest
    assert {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
    } == REVIEWED_EVIDENCE_SHA256

    records = tuple(load_evidence(path) for path in paths)
    for record in records:
        assert record.schema_version == record.suite_version == 1
        assert record.correctness_only is False
        assert (record.warmup_count, record.read_only_repetitions, record.mutation_repetitions) == (
            1,
            7,
            5,
        )
        assert record.git_commit == "dfaa31dfca3a431e7b2e2cb1ceda1e2cc0df286c"
        assert record.run_id == "github-29789436063"
        assert record.bundlewalker_version == "0.4.0a2"

    assert {
        (record.environment.os_name, ".".join(record.environment.python_version.split(".")[:2]))
        for record in records
    } == {("Darwin", "3.13"), ("Darwin", "3.14"), ("Linux", "3.13"), ("Linux", "3.14")}


def test_reviewed_benchmark_report_is_regenerated_from_committed_evidence() -> None:
    records = tuple(load_evidence(path) for path in sorted(EVIDENCE_ROOT.glob("*.json")))
    assert (EVIDENCE_ROOT / "report.md").read_text(encoding="utf-8") == render_report(
        records,
        provisional=False,
        require_matrix=True,
    )


def test_cc0_scope_matches_the_packaged_convention_presets() -> None:
    actual_presets = {
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in (PROJECT_ROOT / "src/bundlewalker/convention_presets").glob("*.md")
    }
    scope = (PROJECT_ROOT / "LICENSE-SCOPE.md").read_text(encoding="utf-8")

    assert actual_presets == CC0_PRESET_PATHS
    assert all(f"`{relative}`" in scope for relative in CC0_PRESET_PATHS)
    assert "All other project-owned files are licensed under GPL-3.0-or-later." in scope
    assert "generated `conventions.md`" in scope


def test_all_python_files_have_gpl_spdx_headers() -> None:
    python_files = sorted((PROJECT_ROOT / "src").rglob("*.py"))
    python_files.extend(sorted((PROJECT_ROOT / "tests").rglob("*.py")))
    python_files.extend(sorted((PROJECT_ROOT / "benchmarks").rglob("*.py")))
    python_files.extend(sorted((PROJECT_ROOT / "scripts").rglob("*.py")))
    missing = [
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in python_files
        if not path.read_text(encoding="utf-8").startswith(PYTHON_HEADER)
    ]

    assert python_files
    assert not missing, "missing GPL SPDX header:\n" + "\n".join(missing)


def test_operational_python_scripts_are_strictly_type_checked() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["tool"]["pyright"]["include"] == [
        "src",
        "tests",
        "benchmarks",
        "scripts",
    ]


def test_benchmark_harness_is_not_packaged(tmp_path: Path) -> None:
    result = subprocess.run(
        ["uv", "build", "--clear", "--no-sources", "--out-dir", str(tmp_path)],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    wheel = next(tmp_path.glob("*.whl"))
    unpacked = tmp_path / "wheel"
    shutil.unpack_archive(wheel, unpacked, "zip")
    assert not (unpacked / "benchmarks").exists()
    static = unpacked / "bundlewalker/interfaces/web/static"
    assert (static / "index.html").is_file()
    assert (static / ".vite/manifest.json").is_file()
    wheel_assets = [path.name for path in (static / "assets").iterdir()]
    assert wheel_assets
    assert all(re.fullmatch(r".+-[A-Za-z0-9_-]{8,}\.(?:css|js)", asset) for asset in wheel_assets)
    assert any(unpacked.rglob("THIRD_PARTY_NOTICES.md"))
    sdist = next(tmp_path.glob("*.tar.gz"))
    with tarfile.open(sdist, "r:gz") as archive:
        names = archive.getnames()
        assert not any(PurePosixPath(name).parts[1:2] == ("benchmarks",) for name in names)
        assert any(
            name.endswith("/src/bundlewalker/interfaces/web/static/index.html") for name in names
        )
        assert any(
            name.endswith("/src/bundlewalker/interfaces/web/static/.vite/manifest.json")
            for name in names
        )
        sdist_assets = [
            PurePosixPath(name).name
            for name in names
            if "/src/bundlewalker/interfaces/web/static/assets/" in name
        ]
        assert sdist_assets
        assert all(
            re.fullmatch(r".+-[A-Za-z0-9_-]{8,}\.(?:css|js)", asset) for asset in sdist_assets
        )
        assert any(name.endswith("/THIRD_PARTY_NOTICES.md") for name in names)


def test_public_policy_documents_exist_and_are_linked() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    contributing = (PROJECT_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    security = (PROJECT_ROOT / "SECURITY.md").read_text(encoding="utf-8")
    support = (PROJECT_ROOT / "SUPPORT.md").read_text(encoding="utf-8")

    assert "[Security](SECURITY.md)" in readme
    assert "[Support](SUPPORT.md)" in readme
    assert "[Security Policy](SECURITY.md)" in contributing
    assert "[Support Policy](SUPPORT.md)" in contributing
    assert "security/advisories/new" in security
    assert "Do not report vulnerabilities in a public issue." in security
    assert "macOS and Linux" in support
    assert "Windows is experimental" in support
    assert "no guaranteed response time" in support


def test_active_documentation_publishes_the_standard_local_web_contract() -> None:
    active_paths = (
        "README.md",
        "docs/user-guide.md",
        "SUPPORT.md",
        "CONTRIBUTING.md",
        "CHANGELOG.md",
    )
    active = {
        relative: (PROJECT_ROOT / relative).read_text(encoding="utf-8") for relative in active_paths
    }

    for relative in ("README.md", "docs/user-guide.md"):
        document = active[relative]
        for required in (
            "pip install bundlewalker",
            "bundlewalker-web",
            "bundlewalker-web --workspace",
            "127.0.0.1",
            "one workspace",
            "macOS and Linux",
            "Windows is experimental",
        ):
            assert required in document

    combined = "\n".join(active.values()).casefold()
    for stale_claim in (
        "local web ui is planned",
        "web ui is not implemented",
        "web application or hosted service to start",
        "short-lived secret",
        "bundlewalker[web]",
        "web extra",
        "web optional extra",
        "optional-extra",
    ):
        assert stale_claim not in combined

    unreleased = (
        active["CHANGELOG.md"]
        .split("## [Unreleased]", maxsplit=1)[1]
        .split("\n## [", maxsplit=1)[0]
    )
    normalized_unreleased = " ".join(unreleased.split()).casefold()
    assert "final release verification remains pending" in normalized_unreleased
    assert re.search(r"not part of (?:the )?tagged `0\.4\.0`", normalized_unreleased)


def test_development_version_is_public_beta() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["version"] == "0.4.0"
    assert bundlewalker.__version__ == "0.4.0"
    assert "Development Status :: 4 - Beta" in project["project"]["classifiers"]
    assert "Development Status :: 3 - Alpha" not in project["project"]["classifiers"]


def test_source_distribution_excludes_untracked_superpowers_worker_state(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    artifacts = tmp_path / "dist"
    shutil.copytree(
        PROJECT_ROOT,
        source,
        ignore=shutil.ignore_patterns(
            ".git",
            ".pytest_cache",
            ".ruff_cache",
            ".superpowers",
            ".venv",
            "__pycache__",
            "dist",
        ),
    )
    worker_state = source / ".superpowers/sdd/sentinel.txt"
    worker_state.parent.mkdir(parents=True)
    worker_state.write_text("must not be packaged\n", encoding="utf-8")
    gitignore = source / ".gitignore"
    gitignore.write_text(
        gitignore.read_text(encoding="utf-8").replace(".superpowers/\n", ""),
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "--quiet"], cwd=source, check=True)

    subprocess.run(
        ["uv", "build", "--sdist", "--out-dir", str(artifacts), "--no-sources"],
        cwd=source,
        check=True,
    )

    sdist = next(artifacts.glob("bundlewalker-*.tar.gz"))
    with tarfile.open(sdist) as archive:
        packaged_paths = archive.getnames()

    assert not any("/.superpowers/" in path for path in packaged_paths)
    assert (
        "bundlewalker-0.4.0/docs/superpowers/plans/2026-07-19-bundlewalker-0.4.0a2-release.md"
    ) in packaged_paths


def test_source_distribution_contains_exact_tracked_historical_fixtures(
    tmp_path: Path,
) -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "--", "tests/fixtures/historical"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    expected = set(tracked.stdout.splitlines())
    assert expected

    source = tmp_path / "source"
    artifacts = tmp_path / "dist"
    shutil.copytree(
        PROJECT_ROOT,
        source,
        ignore=shutil.ignore_patterns(
            ".direnv",
            ".env",
            ".env.*",
            ".git",
            ".mypy_cache",
            ".nox",
            ".pytest_cache",
            ".ruff_cache",
            ".superpowers",
            ".tox",
            ".venv",
            "__pycache__",
            "dist",
            "venv",
        ),
    )
    sentinel = (
        source
        / "tests/fixtures/historical/v1-schema1-swapping/.bundlewalker/untracked-sentinel.txt"
    )
    sentinel.write_text("must not be packaged\n", encoding="utf-8")

    subprocess.run(
        ["uv", "build", "--sdist", "--out-dir", str(artifacts), "--no-sources"],
        cwd=source,
        check=True,
        capture_output=True,
        text=True,
    )
    sdist = next(artifacts.glob("bundlewalker-*.tar.gz"))
    with tarfile.open(sdist, "r:gz") as archive:
        packaged = {
            PurePosixPath(*PurePosixPath(member.name).parts[1:]).as_posix()
            for member in archive.getmembers()
            if member.isfile()
        }

    actual = {path for path in packaged if path.startswith("tests/fixtures/historical/")}
    assert actual == expected


def test_public_beta_documents_preserve_release_candidate_history() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    support = (PROJECT_ROOT / "SUPPORT.md").read_text(encoding="utf-8")
    user_guide = (PROJECT_ROOT / "docs/user-guide.md").read_text(encoding="utf-8")
    performance = (PROJECT_ROOT / "docs/performance-and-capacity.md").read_text(encoding="utf-8")
    vscode_setup = (PROJECT_ROOT / "docs/vscode-copilot-mcp-setup.md").read_text(encoding="utf-8")
    changelog = (PROJECT_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    releases = (PROJECT_ROOT / "docs/maintainers/releases.md").read_text(encoding="utf-8")
    normalized_readme = " ".join(readme.split())
    normalized_support = " ".join(support.split())
    normalized_user_guide = " ".join(user_guide.split())
    normalized_performance = " ".join(performance.split())

    assert "current public beta is `0.4.0`" in readme
    assert 'uv tool install "bundlewalker==0.4.0"' in readme
    assert "current public beta is `0.4.0`" in user_guide
    assert 'uv tool install "bundlewalker==0.4.0"' in user_guide
    for active_guide in (
        normalized_readme,
        normalized_support,
        normalized_user_guide,
        normalized_performance,
    ):
        assert "public beta" in active_guide.casefold()
        assert "proof of concept" not in active_guide.casefold()
        assert "approaching beta" not in active_guide.casefold()
        assert "release candidate" not in active_guide.casefold()
    assert "BundleWalker `0.4.0` installed as a tool" in vscode_setup
    assert "## [Unreleased]" in changelog
    assert "## [v0.4.0] - 2026-07-25" in changelog
    assert "## [v0.4.0rc3] - 2026-07-24" in changelog
    assert "## [v0.4.0rc2] - 2026-07-21" in changelog
    assert "## [v0.4.0rc1] - 2026-07-21" in changelog
    final_entry = changelog.split("## [v0.4.0] - 2026-07-25", maxsplit=1)[1].split(
        "## [v0.4.0rc3] - 2026-07-24", maxsplit=1
    )[0]
    normalized_final_entry = " ".join(final_entry.split())
    rc3_entry = changelog.split("## [v0.4.0rc3] - 2026-07-24", maxsplit=1)[1].split(
        "## [v0.4.0rc2] - 2026-07-21", maxsplit=1
    )[0]
    assert (
        "[Unreleased]: https://github.com/HendrikReh/BundleWalker/compare/v0.4.0...HEAD"
    ) in changelog
    assert (
        "[v0.4.0]: https://github.com/HendrikReh/BundleWalker/compare/v0.4.0rc3...v0.4.0"
    ) in changelog
    assert (
        "[v0.4.0rc3]: https://github.com/HendrikReh/BundleWalker/compare/v0.4.0rc2...v0.4.0rc3"
    ) in changelog
    assert (
        "[v0.4.0rc2]: https://github.com/HendrikReh/BundleWalker/compare/v0.4.0rc1...v0.4.0rc2"
    ) in changelog
    assert (
        "[v0.4.0rc1]: https://github.com/HendrikReh/BundleWalker/compare/v0.4.0a2...v0.4.0rc1"
    ) in changelog
    for phrase in (
        "publish-pypi.yml",
        "GitHub environment `pypi`",
        "pending trusted publisher",
        "v0.4.0rc1",
        "29847165596",
        "v0.4.0rc2",
        "Never move, delete, or reuse",
        "TestPyPI and production builds are separate",
        "fresh artifacts from its reviewed tag",
        'gh run rerun "$RUN_ID" --job "$VERIFY_JOB_ID"',
        "Never rerun a failed publish job",
        "For `0.4.0rc3`",
        "advance through review to `0.4.0rc4`",
    ):
        assert phrase in releases
    assert "advance to `0.4.0rc2`" not in releases
    assert "advance through review to `0.4.0rc2`" not in releases
    assert "Production `0.4.0` is forbidden" in releases

    assert "### Current rc3 publication" not in releases
    historical_rc3_publication = releases.split("### Historical rc3 publication", maxsplit=1)[
        1
    ].split("## Production-installed lifecycle rehearsal", maxsplit=1)[0]
    normalized_historical_rc3_publication = " ".join(historical_rc3_publication.split())
    for recovery_invariant in (
        "The exact-set production recovery matrix above also governs `0.4.0rc3`",
        "If PyPI exposes neither exact artifact after a tag or upload failure",
        "do not reuse `0.4.0rc3`",
        "advance through review to `0.4.0rc4`",
        "If PyPI exposes one artifact or any filename or digest differs",
        "treat `0.4.0rc3` as unsafe",
        "yank `0.4.0rc3`",
        "If PyPI exposes both exact filenames and digests despite an upload-action failure",
        "the same run's verification may continue",
        "the GitHub release may reuse the retained bytes",
        "Only exhaustion of the production-install propagation window may rerun the original "
        "verification job",
        'gh run rerun "$RUN_ID" --job "$VERIFY_JOB_ID"',
        "Never rerun a failed publish job",
        "If only GitHub release creation fails",
        "rerun only that original release job",
        "retained verified artifacts",
    ):
        assert recovery_invariant in normalized_historical_rc3_publication

    for resolution in (
        "pydantic-ai` to `2.16.0",
        "typer` to `0.27.0",
        "ruff` to `0.15.22",
        "pypa/gh-action-pypi-publish` to `v1.14.1",
    ):
        assert resolution in rc3_entry
    assert (
        "Promoted the verified `0.4.0rc3` candidate to the `0.4.0` public beta"
        in normalized_final_entry
    )
    assert "without changing product behavior or third-party dependencies" in normalized_final_entry
    assert "### Prepared 0.4.0 public-beta promotion" in releases
    prepared_beta = releases.split("### Prepared 0.4.0 public-beta promotion", maxsplit=1)[1].split(
        "### Historical rc3 publication", maxsplit=1
    )[0]
    normalized_prepared_beta = " ".join(prepared_beta.split())
    assert "Production `0.4.0` is the prepared public-beta identity" in normalized_prepared_beta
    assert "It becomes the current public beta only after the complete final gate passes" in (
        normalized_prepared_beta
    )
    assert "published to PyPI" in normalized_prepared_beta
    assert "released on GitHub" in normalized_prepared_beta
    assert "v0.4.0" in normalized_prepared_beta


def test_lifecycle_rehearsal_metadata_agrees_across_current_workflow_and_guides() -> None:
    workflow = yaml.load(
        (PROJECT_ROOT / ".github/workflows/rehearse-production-lifecycle.yml").read_text(
            encoding="utf-8"
        ),
        Loader=yaml.BaseLoader,
    )
    releases = (PROJECT_ROOT / "docs/maintainers/releases.md").read_text(encoding="utf-8")
    compatibility = (PROJECT_ROOT / "docs/workspace-compatibility.md").read_text(encoding="utf-8")
    normalized_releases = " ".join(releases.split())
    normalized_compatibility = " ".join(compatibility.split())

    version_description = workflow["on"]["workflow_dispatch"]["inputs"]["version"]["description"]
    version_shape = re.fullmatch(
        r"Exact production PyPI release candidate \((?P<shape>[^)]+)\)",
        version_description,
    )
    assert version_shape is not None
    for document in (releases, compatibility):
        assert f"`{version_shape.group('shape')}`" in document

    workflow_matrix = workflow["jobs"]["rehearse"]["strategy"]["matrix"]
    os_labels = {
        "ubuntu-24.04": "Ubuntu 24.04",
        "macos-15": "macOS 15",
    }
    for os_name in workflow_matrix["os"]:
        assert os_labels[os_name] in compatibility
    for python_version in workflow_matrix["python-version"]:
        assert f"Python {python_version}" in compatibility

    assert (
        "Windows remains experimental and is excluded from this certification matrix"
        in normalized_releases
    )
    assert (
        "Windows remains experimental and is excluded from this certification matrix"
        in normalized_compatibility
    )


def test_production_lifecycle_evidence_records_inspected_live_gate() -> None:
    evidence_path = (
        PROJECT_ROOT / "docs/maintainers/evidence/2026-07-22-production-lifecycle-0.4.0rc2.md"
    )
    assert evidence_path.is_file()

    evidence = evidence_path.read_text(encoding="utf-8")
    releases = (PROJECT_ROOT / "docs/maintainers/releases.md").read_text(encoding="utf-8")
    mcp_compatibility = (PROJECT_ROOT / "docs/mcp-compatibility.md").read_text(encoding="utf-8")
    changelog = (PROJECT_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    normalized_mcp_compatibility = " ".join(mcp_compatibility.split())

    for value in (
        "https://github.com/HendrikReh/BundleWalker/actions/runs/30024736071",
        "5fe237800c18d334720ac63a361b22946a427940",
        "0.4.0rc2",
        "c0c7ea79107c51015b99793994a603c25542c016ca84d53a363ffe48820f7e4b",
    ):
        assert value in evidence

    expected_artifact_rows = (
        "| `production-lifecycle-0.4.0rc2-macos-15-py3.13` | Python 3.13.14; "
        "Darwin arm64 | Pass | "
        "`33f6964967b754658a2641dd8f4da349242204990188e6e95d4a9d3d01154118` | 3375 |",
        "| `production-lifecycle-0.4.0rc2-macos-15-py3.14` | Python 3.14.6; "
        "Darwin arm64 | Pass | "
        "`6055b00c5bcf99ce2d047dd48599c46d68111166a542515e35909c4ff5d55115` | 3376 |",
        "| `production-lifecycle-0.4.0rc2-ubuntu-24.04-py3.13` | Python 3.13.14; "
        "Linux x86_64 | Pass | "
        "`84c4462d9af4d9dfa94d7357622f667ca6ae519e061c31bae0c692845629dbf8` | 3376 |",
        "| `production-lifecycle-0.4.0rc2-ubuntu-24.04-py3.14` | Python 3.14.6; "
        "Linux x86_64 | Pass | "
        "`a86986ccf880c2a4ce8c21f31a68d9dc3e5f64799ac8a8837cdf5ca5386b1387` | 3376 |",
    )
    for row in expected_artifact_rows:
        assert row in evidence

    normalized_evidence = " ".join(evidence.split())
    assert (
        "all nine recorded phases present in order and passing: `installed_identity`, "
        "`initialize`, `inspect_original`, `backup`, `restore`, `upgrade_noop`, `rollback`, "
        "`mcp`, and `final_invariants`"
    ) in normalized_evidence

    expected_tools = [
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
    ]
    tool_section = evidence.split("## Installed MCP surface", maxsplit=1)[1]
    observed_tools = re.findall(r"^- `([^`]+)`$", tool_section, flags=re.MULTILINE)
    assert observed_tools == expected_tools

    evidence_link = "evidence/2026-07-22-production-lifecycle-0.4.0rc2.md"
    assert evidence_link in releases
    assert "production-installed lifecycle gate for `0.4.0rc2` passed" in releases

    compatibility_evidence_link = "maintainers/evidence/2026-07-22-production-lifecycle-0.4.0rc2.md"
    assert compatibility_evidence_link in mcp_compatibility
    assert "installed `bundlewalker-mcp` exposed all 10 MCP tools" in normalized_mcp_compatibility
    assert "| Installed release path | Not covered |" in mcp_compatibility

    assert "Completed the live production-installed lifecycle rehearsal" in changelog


def test_rc3_production_lifecycle_evidence_records_inspected_live_gate() -> None:
    evidence_path = (
        PROJECT_ROOT / "docs/maintainers/evidence/2026-07-24-production-lifecycle-0.4.0rc3.md"
    )
    assert evidence_path.is_file()

    evidence = evidence_path.read_text(encoding="utf-8")
    releases = (PROJECT_ROOT / "docs/maintainers/releases.md").read_text(encoding="utf-8")
    mcp_compatibility = (PROJECT_ROOT / "docs/mcp-compatibility.md").read_text(encoding="utf-8")
    changelog = (PROJECT_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    release_plan = (
        PROJECT_ROOT / "docs/superpowers/plans/2026-07-24-bundlewalker-0.4.0rc3-and-public-beta.md"
    ).read_text(encoding="utf-8")
    normalized_evidence = " ".join(evidence.split())
    normalized_mcp_compatibility = " ".join(mcp_compatibility.split())

    for value in (
        "https://github.com/HendrikReh/BundleWalker/actions/runs/30098254437",
        "v0.4.0rc3",
        "1d38c96d9531a05c99b67b14b0e7d2615045877e",
        "0.4.0rc3",
        "b903b396e8df3e9bfbecfb24e628e0fe7ab8dafefdaf86a59d1d262b05413b53",
    ):
        assert value in evidence

    expected_artifact_rows = (
        "| `production-lifecycle-0.4.0rc3-macos-15-py3.13` | Python 3.13.14; "
        "Darwin arm64 | Passed | "
        "`93ec0bc7fce9b4a2d9fb6c8609e8cac3115a95833b9155ee0e3145c8666b740a` | "
        "3372 | `99074e4009aa1666da2752be75a3fa1db6772ffb92bd3fd91b47064555e74c7d` | "
        "14584 |",
        "| `production-lifecycle-0.4.0rc3-macos-15-py3.14` | Python 3.14.6; "
        "Darwin arm64 | Passed | "
        "`aed46653fa0aae9fa73b2698286cc290519553686e8d9f6b800194317fb36fbe` | "
        "3372 | `127e8a34d175f56905769e8b79d56e9dbcc93530cbee5b0601ec50522769fc33` | "
        "14577 |",
        "| `production-lifecycle-0.4.0rc3-ubuntu-24.04-py3.13` | Python 3.13.14; "
        "Linux x86_64 | Passed | "
        "`ddee5e0252c715b07c468c0359581d0fc92f6c4357d651513c0948f6cd26ab50` | "
        "3372 | `1960ddd88183b2ca9bab5dacfeff8163fa15a2ab7b871fc135a04fb2f8f930a2` | "
        "14583 |",
        "| `production-lifecycle-0.4.0rc3-ubuntu-24.04-py3.14` | Python 3.14.6; "
        "Linux x86_64 | Passed | "
        "`34b06d86a1f56b7b40fd6ec133c7c538101e714b6eede75d7f7a35318db0e894` | "
        "3369 | `ad802e204676231484fe3c97ea61c5272dd226cb5a75ffa8426f0378f0cfb622` | "
        "14581 |",
    )
    for row in expected_artifact_rows:
        assert row in evidence

    assert (
        "all nine recorded phases present in order and passing: `installed_identity`, "
        "`initialize`, `inspect_original`, `backup`, `restore`, `upgrade_noop`, `rollback`, "
        "`mcp`, and `final_invariants`"
    ) in normalized_evidence
    assert "installed exclusively from production PyPI" in normalized_evidence
    assert (
        "No local wheel, source checkout, TestPyPI package, or alternate package index was used "
        "to install BundleWalker."
    ) in normalized_evidence
    assert "overall result `passed`" in normalized_evidence

    expected_tools = [
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
    ]
    tool_section = evidence.split("## Installed MCP surface", maxsplit=1)[1]
    observed_tools = re.findall(r"^- `([^`]+)`$", tool_section, flags=re.MULTILINE)
    assert observed_tools == expected_tools

    evidence_link = "evidence/2026-07-24-production-lifecycle-0.4.0rc3.md"
    assert evidence_link in releases
    assert "production-installed lifecycle gate for `0.4.0rc3` passed" in releases

    compatibility_evidence_link = "maintainers/evidence/2026-07-24-production-lifecycle-0.4.0rc3.md"
    assert compatibility_evidence_link in mcp_compatibility
    assert "installed `bundlewalker-mcp` exposed all 10 MCP tools" in normalized_mcp_compatibility
    assert "production PyPI" in normalized_mcp_compatibility

    unreleased = changelog.split("## [Unreleased]", maxsplit=1)[1].split(
        "## [v0.4.0rc3]", maxsplit=1
    )[0]
    assert (
        "Completed the live production-installed lifecycle rehearsal for `0.4.0rc3`" in unreleased
    )

    assert '"$RC3_PYPI_ENV/bin/bundlewalker" --version' not in release_plan
    assert "\nbundlewalker --version\n" not in release_plan
    assert release_plan.count("from importlib.metadata import version") == 2
