# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

"""Validated, immutable access to the packaged Vite application."""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from html.parser import HTMLParser
from importlib.resources import files
from importlib.resources.abc import Traversable
from types import MappingProxyType
from typing import cast

from bundlewalker.application import ApplicationError, ApplicationErrorCode

_HASHED_ASSET = re.compile(
    r"^[A-Za-z0-9_.]+-[A-Za-z0-9_-]{8,}\.(?:css|gif|ico|jpe?g|js|png|svg|webp|woff2?)$"
)
_ASSET_ERROR_MESSAGE = "web interface assets are unavailable"
_HTML_ASCII_WHITESPACE = "\t\n\f\r "


@dataclass(frozen=True, slots=True)
class ValidatedWebAssets:
    """One immutable snapshot of a validated packaged Vite application."""

    index_html: bytes
    files: Mapping[str, bytes]


@dataclass(frozen=True, slots=True)
class _IndexAssets:
    all: frozenset[str]
    module_scripts: frozenset[str]
    stylesheets: frozenset[str]


class _IndexAssetParser(HTMLParser):
    """Collect browser-loaded shell resources without filesystem assumptions."""

    def __init__(self) -> None:
        super().__init__()
        self.references: list[tuple[str, str]] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag == "script":
            reference = _single_attribute(attrs, "src")
            if reference is None:
                return
            script_type = _single_attribute(attrs, "type")
            role = (
                "module-script"
                if script_type is not None
                and _html_ascii_lower(script_type.strip(_HTML_ASCII_WHITESPACE)) == "module"
                else "other"
            )
            self.references.append((reference, role))
            return
        if tag == "link":
            reference = _single_attribute(attrs, "href")
            if reference is None:
                return
            rel = _single_attribute(attrs, "rel")
            rel_tokens: frozenset[str] = _html_ascii_tokens(rel) if rel is not None else frozenset()
            role = "stylesheet" if "stylesheet" in rel_tokens else "other"
            self.references.append((reference, role))


def _single_attribute(
    attrs: list[tuple[str, str | None]],
    expected_name: str,
) -> str | None:
    values = [value for name, value in attrs if name == expected_name]
    if len(values) > 1:
        raise ValueError("web asset element has duplicate attributes")
    return values[0] if values else None


def _html_ascii_tokens(value: str) -> frozenset[str]:
    normalized = _html_ascii_lower(value)
    for character in _HTML_ASCII_WHITESPACE.removesuffix(" "):
        normalized = normalized.replace(character, " ")
    return frozenset(token for token in normalized.split(" ") if token)


def _html_ascii_lower(value: str) -> str:
    return "".join(
        chr(ord(character) + 32) if "A" <= character <= "Z" else character for character in value
    )


def validate_web_assets(static_dir: Traversable | None = None) -> ValidatedWebAssets:
    """Load and validate the complete local Vite shell before server startup."""
    static = (
        static_dir
        if static_dir is not None
        else files("bundlewalker.interfaces.web").joinpath("static")
    )
    try:
        index_html = _read_required_resource(static.joinpath("index.html"))
        index_text = index_html.decode("utf-8")
        manifest_bytes = _read_required_resource(static.joinpath(".vite", "manifest.json"))
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        manifest_assets, entry_script, entry_stylesheets = _manifest_assets(manifest)
        index_assets = _index_assets(index_text)
        if index_assets.module_scripts != frozenset({entry_script}) or (
            index_assets.stylesheets != frozenset(entry_stylesheets)
        ):
            raise ValueError("Vite entry asset loading roles are invalid")

        loaded: dict[str, bytes] = {}
        for relative in sorted(manifest_assets | index_assets.all):
            asset_name = _validate_asset_path(relative)
            loaded[asset_name] = _read_required_resource(static.joinpath("assets", asset_name))
        return ValidatedWebAssets(
            index_html=index_html,
            files=MappingProxyType(loaded),
        )
    except ApplicationError:
        raise
    except Exception as error:
        raise ApplicationError(
            ApplicationErrorCode.CONFIGURATION_ERROR,
            _ASSET_ERROR_MESSAGE,
        ) from error


def _read_required_resource(resource: Traversable) -> bytes:
    if not resource.is_file():
        raise ValueError("required web resource is not a file")
    return resource.read_bytes()


def _manifest_assets(manifest: object) -> tuple[set[str], str, set[str]]:
    if not isinstance(manifest, dict):
        raise ValueError("Vite manifest must be an object")
    records = cast(dict[object, object], manifest)
    entry = records.get("index.html")
    if not isinstance(entry, dict):
        raise ValueError("Vite manifest has no index entry")
    entry_record = cast(dict[object, object], entry)
    if entry_record.get("src") != "index.html" or entry_record.get("isEntry") is not True:
        raise ValueError("Vite manifest index entry is invalid")

    all_assets: set[str] = set()
    entry_script: str | None = None
    entry_stylesheets: set[str] = set()
    for key, value in records.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            raise ValueError("Vite manifest record is invalid")
        record = cast(dict[object, object], value)
        file_asset = _manifest_asset(record.get("file"))
        record_assets = {file_asset}
        css_assets: set[str] = set()
        for field in ("css", "assets"):
            raw_references = record.get(field, [])
            if not isinstance(raw_references, list):
                raise ValueError("Vite manifest asset list is invalid")
            references = cast(list[object], raw_references)
            field_assets = {_manifest_asset(reference) for reference in references}
            record_assets.update(field_assets)
            if field == "css":
                css_assets.update(field_assets)
        for field in ("imports", "dynamicImports"):
            imports = record.get(field, [])
            if not isinstance(imports, list):
                raise ValueError("Vite manifest import list is invalid")
            import_values = cast(list[object], imports)
            if not all(
                isinstance(reference, str) and reference in records for reference in import_values
            ):
                raise ValueError("Vite manifest import list is invalid")
        all_assets.update(record_assets)
        if key == "index.html":
            entry_script = file_asset
            entry_stylesheets.update(css_assets)
    if entry_script is None:
        raise ValueError("Vite manifest has no index entry")
    return all_assets, entry_script, entry_stylesheets


def _manifest_asset(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Vite manifest asset path is invalid")
    _validate_asset_path(value)
    return value


def _index_assets(index_html: str) -> _IndexAssets:
    parser = _IndexAssetParser()
    parser.feed(index_html)
    parser.close()
    assets: set[str] = set()
    module_scripts: set[str] = set()
    stylesheets: set[str] = set()
    for reference, role in parser.references:
        relative = reference.removeprefix("/")
        _validate_asset_path(relative)
        if relative in assets:
            raise ValueError("web asset has ambiguous loading roles")
        assets.add(relative)
        if role == "module-script":
            module_scripts.add(relative)
        if role == "stylesheet":
            stylesheets.add(relative)
    return _IndexAssets(
        all=frozenset(assets),
        module_scripts=frozenset(module_scripts),
        stylesheets=frozenset(stylesheets),
    )


def _validate_asset_path(relative: str) -> str:
    prefix, separator, asset_name = relative.partition("/")
    if (
        prefix != "assets"
        or separator != "/"
        or "/" in asset_name
        or "\\" in relative
        or _HASHED_ASSET.fullmatch(asset_name) is None
    ):
        raise ValueError("web asset path is unsafe")
    return asset_name
