# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import cast

from bundlewalker.errors import ConfigurationError
from bundlewalker.transactions import QuiescentWorkspace
from bundlewalker.workspace import (
    MAX_WORKSPACE_CONFIG_BYTES,
    Workspace,
    discover_workspace,
    find_workspace_config,
)

CURRENT_WORKSPACE_FORMAT = 1
MINIMUM_WORKSPACE_FORMAT = 1


class CompatibilityStatus(StrEnum):
    CURRENT = "current"
    UPGRADEABLE = "upgradeable"
    TOO_NEW = "too_new"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class MigrationStep:
    source_version: int
    target_version: int
    apply: Callable[[QuiescentWorkspace], None]
    verify: Callable[[Workspace], None]


@dataclass(frozen=True, slots=True)
class WorkspaceCompatibility:
    root: Path
    config_path: Path
    workspace_format_version: int
    status: CompatibilityStatus
    readable: bool
    writable: bool
    upgrade_available: bool


def migration_path(
    source_version: int,
    *,
    target_version: int = CURRENT_WORKSPACE_FORMAT,
    migrations: Mapping[int, MigrationStep] | None = None,
) -> tuple[MigrationStep, ...] | None:
    if source_version > target_version:
        return None
    if source_version == target_version:
        return ()
    registered = migrations or {}
    current = source_version
    path: list[MigrationStep] = []
    seen: set[int] = set()
    while current < target_version:
        if current in seen:
            return None
        seen.add(current)
        step = registered.get(current)
        if (
            step is None
            or step.source_version != current
            or step.target_version <= current
            or step.target_version > target_version
        ):
            return None
        path.append(step)
        current = step.target_version
    return tuple(path) if current == target_version else None


def classify_workspace_version(
    version: int,
    *,
    target_version: int = CURRENT_WORKSPACE_FORMAT,
    migrations: Mapping[int, MigrationStep] | None = None,
) -> CompatibilityStatus:
    """Classify a parsed workspace version against an explicit migration policy."""
    if version > CURRENT_WORKSPACE_FORMAT:
        return CompatibilityStatus.TOO_NEW
    if version < MINIMUM_WORKSPACE_FORMAT:
        return CompatibilityStatus.UNSUPPORTED
    if version < target_version:
        path = migration_path(
            version,
            target_version=target_version,
            migrations=migrations,
        )
        return (
            CompatibilityStatus.UPGRADEABLE if path is not None else CompatibilityStatus.UNSUPPORTED
        )
    return CompatibilityStatus.CURRENT


def inspect_workspace(
    start: Path | None = None,
    *,
    target_version: int = CURRENT_WORKSPACE_FORMAT,
    migrations: Mapping[int, MigrationStep] | None = None,
) -> WorkspaceCompatibility:
    config_path = find_workspace_config(start)
    version = read_workspace_format_version(config_path)
    root = config_path.parent
    status = classify_workspace_version(
        version,
        target_version=target_version,
        migrations=migrations,
    )
    if status is CompatibilityStatus.TOO_NEW:
        return WorkspaceCompatibility(
            root, config_path, version, CompatibilityStatus.TOO_NEW, False, False, False
        )
    if status is CompatibilityStatus.UNSUPPORTED:
        return WorkspaceCompatibility(
            root, config_path, version, CompatibilityStatus.UNSUPPORTED, False, False, False
        )
    if status is CompatibilityStatus.UPGRADEABLE:
        return WorkspaceCompatibility(
            root,
            config_path,
            version,
            CompatibilityStatus.UPGRADEABLE,
            False,
            False,
            True,
        )
    discover_workspace(root)
    return WorkspaceCompatibility(
        root, config_path, version, CompatibilityStatus.CURRENT, True, True, False
    )


def read_workspace_format_version(config_path: Path) -> int:
    try:
        content = config_path.read_bytes()
    except OSError as exc:
        raise ConfigurationError(f"could not read workspace configuration: {config_path}") from exc
    if len(content) > MAX_WORKSPACE_CONFIG_BYTES:
        raise ConfigurationError("workspace configuration exceeds the supported size")
    try:
        parsed = tomllib.loads(content.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ConfigurationError(f"could not read workspace configuration: {config_path}") from exc
    return workspace_format_version(cast(dict[str, object], parsed))


def workspace_format_version(values: Mapping[str, object]) -> int:
    """Return the format version from one already parsed TOML mapping."""
    version = values.get("version")
    if type(version) is not int:
        raise ConfigurationError("workspace configuration version must be an integer")
    return version
