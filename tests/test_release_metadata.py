import tomllib
from importlib.metadata import version as distribution_version
from pathlib import Path

import bundlewalker


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_v2_release_versions_are_consistent() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((PROJECT_ROOT / "uv.lock").read_text(encoding="utf-8"))
    editable_package = next(
        package
        for package in lock["package"]
        if package["name"] == "bundlewalker" and package.get("source") == {"editable": "."}
    )

    assert project["project"]["version"] == "0.2.0"
    assert bundlewalker.__version__ == "0.2.0"
    assert distribution_version("bundlewalker") == "0.2.0"
    assert editable_package["version"] == "0.2.0"
