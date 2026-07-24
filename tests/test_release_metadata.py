# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

import hashlib
import importlib.metadata
import importlib.util
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
LICENSE_FILES = ["LICENSE", "LICENSES/CC0-1.0.txt", "LICENSE-SCOPE.md"]
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


def test_release_lock_uses_approved_rc3_dependency_versions() -> None:
    locked = tomllib.loads((PROJECT_ROOT / "uv.lock").read_text(encoding="utf-8"))
    versions = {package["name"]: package["version"] for package in locked["package"]}

    assert versions["pydantic-ai"] == "2.16.0"
    assert versions["typer"] == "0.27.0"
    assert versions["ruff"] == "0.15.22"

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
    assert "proof of concept" in performance

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
        "Development Status :: 3 - Alpha",
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
    sdist = next(tmp_path.glob("*.tar.gz"))
    with tarfile.open(sdist, "r:gz") as archive:
        assert not any(
            PurePosixPath(name).parts[1:2] == ("benchmarks",) for name in archive.getnames()
        )


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


def test_development_version_is_second_release_candidate() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["version"] == "0.4.0rc2"
    assert bundlewalker.__version__ == "0.4.0rc2"


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
        "bundlewalker-0.4.0rc2/docs/superpowers/plans/2026-07-19-bundlewalker-0.4.0a2-release.md"
    ) in packaged_paths


def test_second_release_candidate_documents_rc1_recovery_without_final_beta_claim() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (PROJECT_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    releases = (PROJECT_ROOT / "docs/maintainers/releases.md").read_text(encoding="utf-8")

    assert "current production release candidate is `0.4.0rc2`" in readme
    assert 'uv tool install "bundlewalker==0.4.0rc2"' in readme
    assert "proof of concept" in readme
    assert "## [v0.4.0rc2] - 2026-07-21" in changelog
    assert "## [v0.4.0rc1] - 2026-07-21" in changelog
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
    ):
        assert phrase in releases
    assert "advance to `0.4.0rc2`" not in releases
    assert "advance through review to `0.4.0rc2`" not in releases
    assert releases.count("advance to `0.4.0rc3`") == 1
    assert releases.count("advance through review to `0.4.0rc3`") == 2
    assert "Production `0.4.0` is forbidden" in releases


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
