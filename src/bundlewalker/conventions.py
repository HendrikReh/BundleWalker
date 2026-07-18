# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from enum import StrEnum
from importlib import resources

from bundlewalker.errors import WorkspaceError


class ConventionsStyle(StrEnum):
    """Creation-time conventions templates supported by workspace initialization."""

    DEFAULT = "default"
    PERSONAL_WORKBOOK = "personal-workbook"
    AGENT_CONTEXT = "agent-context"
    SOFTWARE_AGENT = "software-agent"
    RESEARCH_AGENT = "research-agent"


_PRESET_FILES: dict[ConventionsStyle, str] = {
    ConventionsStyle.DEFAULT: "default.md",
    ConventionsStyle.PERSONAL_WORKBOOK: "personal-workbook.md",
    ConventionsStyle.AGENT_CONTEXT: "agent-context.md",
    ConventionsStyle.SOFTWARE_AGENT: "software-agent.md",
    ConventionsStyle.RESEARCH_AGENT: "research-agent.md",
}


def load_conventions(style: ConventionsStyle) -> str:
    """Load and validate one trusted packaged conventions template."""
    try:
        text = (
            resources.files("bundlewalker.convention_presets")
            .joinpath(_PRESET_FILES[style])
            .read_text(encoding="utf-8")
        )
    except (ImportError, OSError, UnicodeError) as exc:
        raise WorkspaceError(f"could not load conventions style: {style.value}") from exc
    if not text.strip() or not text.endswith("\n") or text.endswith("\n\n"):
        raise WorkspaceError(f"could not load conventions style: {style.value}")
    return text
