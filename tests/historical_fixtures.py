# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import cast

EMPTY_DIRECTORIES = "empty-directories.json"


@dataclass(frozen=True, slots=True)
class HistoricalFixtures:
    """Materialize historical workspaces from their file-only representation."""

    root: Path

    def materialize(self, name: str, destination: Path) -> Path:
        _require_safe_component(name)
        shutil.copytree(self.root / name, destination)
        for fixture, parts in self._empty_directories():
            if fixture != name:
                continue
            empty_directory = destination.joinpath(*parts)
            empty_directory.mkdir(parents=True, exist_ok=True)
            if any(empty_directory.iterdir()):
                raise ValueError(
                    f"represented empty directory contains content: {fixture}/{'/'.join(parts)}"
                )
        return destination

    def read_metadata(self, name: str) -> dict[str, object]:
        _require_safe_component(name)
        loaded = cast(object, json.loads((self.root / name).read_text(encoding="utf-8")))
        if not isinstance(loaded, dict):
            raise ValueError(f"historical fixture metadata must be a JSON object: {name}")
        metadata = cast(dict[object, object], loaded)
        if any(not isinstance(key, str) for key in metadata):
            raise ValueError(f"historical fixture metadata keys must be strings: {name}")
        return cast(dict[str, object], metadata)

    def _empty_directories(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        manifest = self.read_metadata(EMPTY_DIRECTORIES)
        if manifest.get("schema_version") != 1:
            raise ValueError("unsupported historical empty-directory representation")
        paths = manifest.get("empty_directories")
        if not isinstance(paths, list):
            raise ValueError("historical empty-directory representation must contain a path list")

        represented: list[tuple[str, tuple[str, ...]]] = []
        for value in cast(list[object], paths):
            if not isinstance(value, str):
                raise ValueError("historical empty-directory paths must be strings")
            parts = tuple(value.split("/"))
            if len(parts) < 2 or any(not part or part in {".", ".."} for part in parts):
                raise ValueError(f"unsafe historical empty-directory path: {value}")
            represented.append((parts[0], parts[1:]))
        return tuple(represented)


def copy_file_representation(source: Path, destination: Path) -> None:
    """Copy regular fixture files without inheriting ambient empty directories."""
    destination.mkdir(parents=True)
    for source_path in sorted(source.rglob("*")):
        if source_path.is_symlink():
            raise ValueError(f"historical fixture representation contains a symlink: {source_path}")
        if not source_path.is_file():
            continue
        destination_path = destination / source_path.relative_to(source)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, destination_path)


def _require_safe_component(value: str) -> None:
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError(f"unsafe historical fixture name: {value}")
