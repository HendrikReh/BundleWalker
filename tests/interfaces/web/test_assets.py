# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

import json
from importlib.resources import files
from pathlib import Path

import pytest

from bundlewalker.application import ApplicationError
from bundlewalker.interfaces.web.assets import validate_web_assets


def _write_static_bundle(
    static: Path,
    *,
    index: bytes | None = None,
    manifest: bytes | None = None,
    include_javascript: bool = True,
) -> None:
    javascript = "assets/index-abcdefgh.js"
    stylesheet = "assets/index-abcdefgh.css"
    static.joinpath(".vite").mkdir(parents=True)
    static.joinpath("assets").mkdir()
    static.joinpath("index.html").write_bytes(
        index
        if index is not None
        else (
            "<!doctype html><html><head>"
            f'<script type="module" src="/{javascript}"></script>'
            f'<link rel="stylesheet" href="/{stylesheet}">'
            "</head><body></body></html>"
        ).encode()
    )
    static.joinpath(".vite", "manifest.json").write_bytes(
        manifest
        if manifest is not None
        else json.dumps(
            {
                "index.html": {
                    "file": javascript,
                    "src": "index.html",
                    "isEntry": True,
                    "css": [stylesheet],
                }
            }
        ).encode()
    )
    if include_javascript:
        static.joinpath(javascript).write_text("export {};\n", encoding="utf-8")
    static.joinpath(stylesheet).write_text("body {}\n", encoding="utf-8")


def test_web_distribution_contains_vite_entrypoint_and_manifest() -> None:
    static = files("bundlewalker.interfaces.web").joinpath("static")
    assets = validate_web_assets(static)
    html = assets.index_html.decode("utf-8")
    assert '<script type="module"' in html
    assert "http://" not in html
    assert "https://" not in html
    assert {name.rpartition(".")[2] for name in assets.files} == {"css", "js"}


def test_web_asset_validation_rejects_missing_index(tmp_path: Path) -> None:
    static = tmp_path / "static"
    _write_static_bundle(static)
    static.joinpath("index.html").unlink()

    with pytest.raises(ApplicationError, match="web interface assets are unavailable"):
        validate_web_assets(static)


@pytest.mark.parametrize(
    "manifest",
    [
        b"{",
        b'{"index.html": "\xff"}',
    ],
    ids=["malformed-json", "non-utf8"],
)
def test_web_asset_validation_rejects_invalid_manifest(
    tmp_path: Path,
    manifest: bytes,
) -> None:
    static = tmp_path / "static"
    _write_static_bundle(static, manifest=manifest)

    with pytest.raises(ApplicationError, match="web interface assets are unavailable"):
        validate_web_assets(static)


def test_web_asset_validation_rejects_missing_referenced_asset(tmp_path: Path) -> None:
    static = tmp_path / "static"
    _write_static_bundle(static, include_javascript=False)

    with pytest.raises(ApplicationError, match="web interface assets are unavailable"):
        validate_web_assets(static)


def test_web_asset_validation_rejects_non_file_referenced_asset(tmp_path: Path) -> None:
    static = tmp_path / "static"
    _write_static_bundle(static, include_javascript=False)
    static.joinpath("assets", "index-abcdefgh.js").mkdir()

    with pytest.raises(ApplicationError, match="web interface assets are unavailable"):
        validate_web_assets(static)


def test_web_asset_validation_accepts_code_loaded_manifest_asset(tmp_path: Path) -> None:
    static = tmp_path / "static"
    manifest = json.dumps(
        {
            "index.html": {
                "file": "assets/index-abcdefgh.js",
                "src": "index.html",
                "isEntry": True,
                "css": ["assets/index-abcdefgh.css"],
                "assets": ["assets/logo-abcdefgh.svg"],
            }
        }
    ).encode()
    _write_static_bundle(static, manifest=manifest)
    static.joinpath("assets", "logo-abcdefgh.svg").write_text(
        "<svg></svg>\n",
        encoding="utf-8",
    )

    assets = validate_web_assets(static)

    assert "logo-abcdefgh.svg" in assets.files


def test_web_asset_validation_rejects_swapped_loading_roles(tmp_path: Path) -> None:
    static = tmp_path / "static"
    _write_static_bundle(
        static,
        index=(
            b"<!doctype html><html><head>"
            b'<script type="module" src="/assets/index-abcdefgh.css"></script>'
            b'<link rel="stylesheet" href="/assets/index-abcdefgh.js">'
            b"</head><body></body></html>"
        ),
    )

    with pytest.raises(ApplicationError, match="web interface assets are unavailable"):
        validate_web_assets(static)


@pytest.mark.parametrize(
    "index",
    [
        (
            "<!doctype html><html><head>"
            '<script src="/assets/index-abcdefgh.js"></script>'
            '<link rel="stylesheet" href="/assets/index-abcdefgh.css">'
            "</head><body></body></html>"
        ),
        (
            "<!doctype html><html><head>"
            '<script type="text/javascript" src="/assets/index-abcdefgh.js"></script>'
            '<link rel="stylesheet" href="/assets/index-abcdefgh.css">'
            "</head><body></body></html>"
        ),
        (
            "<!doctype html><html><head>"
            '<script type="module" src="/assets/index-abcdefgh.js"></script>'
            '<link href="/assets/index-abcdefgh.css">'
            "</head><body></body></html>"
        ),
        (
            "<!doctype html><html><head>"
            '<script type="module" src="/assets/index-abcdefgh.js"></script>'
            '<link rel="preload" href="/assets/index-abcdefgh.css">'
            "</head><body></body></html>"
        ),
        (
            "<!doctype html><html><head>"
            '<script type="module" src="/assets/index-abcdefgh.js"></script>'
            '<script type="module" src="/assets/index-abcdefgh.js"></script>'
            '<link rel="stylesheet" href="/assets/index-abcdefgh.css">'
            "</head><body></body></html>"
        ),
    ],
    ids=[
        "missing-module-type",
        "wrong-module-type",
        "missing-stylesheet-rel",
        "wrong-stylesheet-rel",
        "duplicate-entry-script",
    ],
)
def test_web_asset_validation_rejects_missing_wrong_or_ambiguous_loading_role(
    tmp_path: Path,
    index: str,
) -> None:
    static = tmp_path / "static"
    _write_static_bundle(static, index=index.encode())

    with pytest.raises(ApplicationError, match="web interface assets are unavailable"):
        validate_web_assets(static)


def test_web_asset_validation_rejects_extra_distinct_module_script(tmp_path: Path) -> None:
    static = tmp_path / "static"
    _write_static_bundle(
        static,
        index=(
            b"<!doctype html><html><head>"
            b'<script type="module" src="/assets/index-abcdefgh.js"></script>'
            b'<script type="module" src="/assets/extra-abcdefgh.js"></script>'
            b'<link rel="stylesheet" href="/assets/index-abcdefgh.css">'
            b"</head><body></body></html>"
        ),
    )
    static.joinpath("assets", "extra-abcdefgh.js").write_text(
        "export {};\n",
        encoding="utf-8",
    )

    with pytest.raises(ApplicationError, match="web interface assets are unavailable"):
        validate_web_assets(static)


def test_web_asset_validation_rejects_extra_distinct_stylesheet(tmp_path: Path) -> None:
    static = tmp_path / "static"
    _write_static_bundle(
        static,
        index=(
            b"<!doctype html><html><head>"
            b'<script type="module" src="/assets/index-abcdefgh.js"></script>'
            b'<link rel="stylesheet" href="/assets/index-abcdefgh.css">'
            b'<link rel="stylesheet" href="/assets/extra-abcdefgh.css">'
            b"</head><body></body></html>"
        ),
    )
    static.joinpath("assets", "extra-abcdefgh.css").write_text(
        "body {}\n",
        encoding="utf-8",
    )

    with pytest.raises(ApplicationError, match="web interface assets are unavailable"):
        validate_web_assets(static)


@pytest.mark.parametrize(
    "whitespace",
    ["\u00a0", "\u2003"],
    ids=["nbsp", "em-space"],
)
def test_web_asset_validation_rejects_non_ascii_whitespace_around_module_type(
    tmp_path: Path,
    whitespace: str,
) -> None:
    static = tmp_path / "static"
    _write_static_bundle(
        static,
        index=(
            "<!doctype html><html><head>"
            f'<script type="{whitespace}module{whitespace}" '
            'src="/assets/index-abcdefgh.js"></script>'
            '<link rel="stylesheet" href="/assets/index-abcdefgh.css">'
            "</head><body></body></html>"
        ).encode(),
    )

    with pytest.raises(ApplicationError, match="web interface assets are unavailable"):
        validate_web_assets(static)


@pytest.mark.parametrize(
    "whitespace",
    ["\u00a0", "\u2003"],
    ids=["nbsp", "em-space"],
)
def test_web_asset_validation_rejects_non_ascii_whitespace_around_stylesheet_rel(
    tmp_path: Path,
    whitespace: str,
) -> None:
    static = tmp_path / "static"
    _write_static_bundle(
        static,
        index=(
            "<!doctype html><html><head>"
            '<script type="module" src="/assets/index-abcdefgh.js"></script>'
            f'<link rel="{whitespace}stylesheet{whitespace}" '
            'href="/assets/index-abcdefgh.css">'
            "</head><body></body></html>"
        ).encode(),
    )

    with pytest.raises(ApplicationError, match="web interface assets are unavailable"):
        validate_web_assets(static)


def test_web_asset_validation_accepts_ascii_whitespace_and_case_in_role_attributes(
    tmp_path: Path,
) -> None:
    static = tmp_path / "static"
    _write_static_bundle(
        static,
        index=(
            b"<!doctype html><html><head>"
            b'<script type="\tMoDuLe\r" src="/assets/index-abcdefgh.js"></script>'
            b'<link rel="preload\nStyleSheet" href="/assets/index-abcdefgh.css">'
            b"</head><body></body></html>"
        ),
    )

    assets = validate_web_assets(static)

    assert set(assets.files) == {
        "index-abcdefgh.css",
        "index-abcdefgh.js",
    }


@pytest.mark.parametrize(
    "asset_path",
    [
        "../index-abcdefgh.js",
        "/assets/index-abcdefgh.js",
        "assets/index.js",
    ],
    ids=["traversal", "absolute", "non-hashed"],
)
def test_web_asset_validation_rejects_unsafe_manifest_asset_path(
    tmp_path: Path,
    asset_path: str,
) -> None:
    static = tmp_path / "static"
    manifest = json.dumps(
        {
            "index.html": {
                "file": asset_path,
                "src": "index.html",
                "isEntry": True,
                "css": ["assets/index-abcdefgh.css"],
            }
        }
    ).encode()
    _write_static_bundle(static, manifest=manifest)

    with pytest.raises(ApplicationError, match="web interface assets are unavailable"):
        validate_web_assets(static)
