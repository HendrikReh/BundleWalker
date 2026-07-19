# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import NoReturn

import bundlewalker.transactions as transactions
from bundlewalker.transactions import apply_pending_review
from bundlewalker.workspace import discover_workspace

_CRASH_EXIT = 86
_COMMIT_PHASES = ("accepted", "raw-persisted", "swapping", "new-live")


def crash_after_manifest(workspace_root: Path, phase: str, review_id: str) -> NoReturn:
    if phase not in _COMMIT_PHASES:
        raise ValueError("crash phase must be a durable commit phase")
    original = transactions._write_manifest  # pyright: ignore[reportPrivateUsage]

    def write_then_exit(
        transaction_dir: Path,
        manifest: transactions._Manifest,  # pyright: ignore[reportPrivateUsage]
    ) -> None:
        original(transaction_dir, manifest)
        if manifest.phase == phase:
            os._exit(_CRASH_EXIT)

    transactions._write_manifest = write_then_exit  # pyright: ignore[reportPrivateUsage]
    workspace = discover_workspace(workspace_root)
    apply_pending_review(workspace, review_id)
    raise AssertionError("crash phase was not reached")


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", type=Path)
    parser.add_argument("phase", choices=_COMMIT_PHASES)
    parser.add_argument("review_id")
    return parser.parse_args()


def main() -> NoReturn:
    arguments = _arguments()
    crash_after_manifest(arguments.workspace, arguments.phase, arguments.review_id)


if __name__ == "__main__":
    main()
