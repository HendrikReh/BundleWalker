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
from dataclasses import replace
from importlib.metadata import version as distribution_version
from pathlib import Path, PurePosixPath

import pytest
from markdown_it import MarkdownIt

import bundlewalker
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
ALLOWED_SUPPORTED_CAPACITY_SENTENCES = frozenset(
    {
        "Supported capacity is not yet published.",
        (
            "Local runs are useful for development, but they do not themselves establish a "
            "supported capacity."
        ),
    }
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


def _assert_provisional_capacity_claims(markdown: str) -> None:
    assert _supported_capacity_sentences(markdown) == ALLOWED_SUPPORTED_CAPACITY_SENTENCES


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


def test_performance_document_is_provisional_and_linked() -> None:
    performance_path = PROJECT_ROOT / "docs/performance-and-capacity.md"
    performance = performance_path.read_text(encoding="utf-8")
    markdown = MarkdownIt("commonmark")

    assert performance.count("Supported capacity is not yet published.") == 1
    assert "candidate only" in performance
    assert "100,000 Unicode characters" in performance
    assert "remote model-provider latency is excluded" in performance
    assert "Windows remains experimental" in performance

    _assert_provisional_capacity_claims(performance)
    assert "BundleWalker supports up to" not in performance
    assert re.search(r"\bbeta\s+(?:is\s+)?complete\b", performance, re.IGNORECASE) is None
    assert re.search(r"\b(?:release|version)\s+(?:is|:|\d)", performance, re.IGNORECASE) is None

    profile_section = performance.partition("## Profiles\n")[2].partition("\n## ")[0]
    profile_names = {"Smoke", "Small", "Medium", "Large", "Probe"}
    profile_rows = tuple(
        cells
        for line in profile_section.splitlines()
        if line.startswith("|")
        and (cells := tuple(cell.strip() for cell in line.strip("|").split("|")))[0]
        in profile_names
    )
    assert profile_rows == (
        ("Smoke", "50", "0.5 MiB", "10,000 Unicode characters"),
        ("Small", "250", "2.5 MiB", "25,000 Unicode characters"),
        ("Medium", "1,000", "10 MiB", "50,000 Unicode characters"),
        ("Large", "5,000", "50 MiB", "100,000 Unicode characters"),
        ("Probe", "10,000", "100 MiB", "100,000 Unicode characters"),
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


@pytest.mark.parametrize(
    "affirmative_claim",
    [
        "BundleWalker has a supported workspace capacity of 50 MiB.",
        "A capacity of 50 MiB is supported.",
        "A CAPACITY of 50 MiB is SUPPORTED.",
    ],
)
def test_performance_contract_rejects_affirmative_supported_capacity_claims(
    affirmative_claim: str,
) -> None:
    performance = (PROJECT_ROOT / "docs/performance-and-capacity.md").read_text(encoding="utf-8")

    with pytest.raises(AssertionError):
        _assert_provisional_capacity_claims(f"{performance}\n\n{affirmative_claim}\n")


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
    missing = [
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in python_files
        if not path.read_text(encoding="utf-8").startswith(PYTHON_HEADER)
    ]

    assert python_files
    assert not missing, "missing GPL SPDX header:\n" + "\n".join(missing)


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


def test_development_version_is_second_alpha() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["version"] == "0.4.0a2"
    assert bundlewalker.__version__ == "0.4.0a2"


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
        "bundlewalker-0.4.0a2/docs/superpowers/plans/2026-07-19-bundlewalker-0.4.0a2-release.md"
    ) in packaged_paths
