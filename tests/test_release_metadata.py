# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

import hashlib
import importlib.metadata
import importlib.util
import shutil
import subprocess
import tarfile
import tomllib
from importlib.metadata import version as distribution_version
from pathlib import Path

import pytest

import bundlewalker

PROJECT_ROOT = Path(__file__).resolve().parents[1]

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


def test_package_import_survives_missing_distribution_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_version(_distribution_name: str) -> str:
        raise importlib.metadata.PackageNotFoundError("bundlewalker")

    monkeypatch.setattr(importlib.metadata, "version", missing_version)
    package_init = PROJECT_ROOT / "src/bundlewalker/__init__.py"
    spec = importlib.util.spec_from_file_location("isolated_bundlewalker", package_init)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)

    spec.loader.exec_module(module)

    assert module.__version__ == ""


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


def test_license_metadata_and_files_are_declared() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["license"] == LICENSE_EXPRESSION
    assert project["project"]["license-files"] == LICENSE_FILES
    assert all((PROJECT_ROOT / relative).is_file() for relative in LICENSE_FILES)


def test_official_license_texts_are_unmodified() -> None:
    for relative, expected_digest in OFFICIAL_LICENSE_SHA256.items():
        content = (PROJECT_ROOT / relative).read_bytes()
        assert hashlib.sha256(content).hexdigest() == expected_digest


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
    missing = [
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in python_files
        if not path.read_text(encoding="utf-8").startswith(PYTHON_HEADER)
    ]

    assert python_files
    assert not missing, "missing GPL SPDX header:\n" + "\n".join(missing)


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
