# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import argparse
import os
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

from benchmarks.contracts import WorkspaceProfile
from benchmarks.evidence import load_evidence, write_new_text
from benchmarks.profiles import PROFILES
from benchmarks.report import render_report
from benchmarks.runner import BenchmarkRunError, RunConfig, run_benchmarks


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        del message
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: invalid arguments\n")


def _parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(prog="python -m benchmarks")
    subcommands = parser.add_subparsers(
        dest="command", required=True, parser_class=_SafeArgumentParser
    )

    run = subcommands.add_parser("run")
    run.add_argument("--profiles", default=",".join(PROFILES))
    run.add_argument("--correctness-only", action="store_true")
    run.add_argument("--output", required=True, type=Path)
    run.add_argument("--run-id")
    run.add_argument("--work-root", type=Path)

    report = subcommands.add_parser("report")
    report.add_argument("--evidence", required=True, type=Path)
    report.add_argument("--output", required=True, type=Path)
    report.add_argument("--provisional", action="store_true", required=True)
    report.add_argument("--require-matrix", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    arguments = parser.parse_args(argv)
    if arguments.command == "run":
        return _run_command(parser, arguments)
    if arguments.command == "report":
        return _report_command(parser, arguments)
    parser.error("unknown command")
    return 2


def _run_command(parser: argparse.ArgumentParser, arguments: argparse.Namespace) -> int:
    captured_start = datetime.now(UTC)
    try:
        profiles = _parse_profiles(arguments.profiles)
        if arguments.correctness_only and tuple(profile.name for profile in profiles) != ("smoke",):
            parser.error("correctness-only requires Smoke")
        run_id = arguments.run_id or captured_start.strftime("local-%Y%m%dT%H%M%SZ")
        if not _safe_run_id(run_id):
            parser.error("invalid run id")
        output = _absolute(arguments.output)
        work_root = _absolute(arguments.work_root or Path("benchmark-work") / run_id)
        _validate_output_path(parser, output)
        _validate_work_root(parser, work_root, output)
        _reject_workspace_output(parser, output)
        _ensure_output_parent(parser, output)
    except (KeyError, ValueError):
        parser.error("invalid run arguments")

    try:
        run_benchmarks(
            RunConfig(
                profiles=profiles,
                output=output,
                work_root=work_root,
                run_id=run_id,
                correctness_only=arguments.correctness_only,
            )
        )
    except (BenchmarkRunError, OSError, ValueError) as error:
        _bounded_error("Benchmark run failed", error)
        return 1
    print(os.path.relpath(output, Path.cwd()))
    return 0


def _report_command(parser: argparse.ArgumentParser, arguments: argparse.Namespace) -> int:
    evidence_directory = _absolute(arguments.evidence)
    output = _absolute(arguments.output)
    _validate_output_path(parser, output)
    _reject_workspace_output(parser, output)
    _ensure_output_parent(parser, output)
    if (
        evidence_directory.is_symlink()
        or not evidence_directory.is_dir()
        or _has_symlink_file(evidence_directory)
    ):
        parser.error("invalid evidence directory")

    try:
        evidence_paths = tuple(sorted(evidence_directory.glob("*.json")))
        if not evidence_paths:
            raise ValueError("no evidence records found")
        records = tuple(load_evidence(path) for path in evidence_paths)
        report = render_report(
            records,
            provisional=arguments.provisional,
            require_matrix=arguments.require_matrix,
        )
        write_new_text(output, report)
    except (OSError, ValueError) as error:
        _bounded_error("Benchmark report failed", error)
        return 1
    print(os.path.relpath(output, Path.cwd()))
    return 0


def _parse_profiles(value: str) -> tuple[WorkspaceProfile, ...]:
    names = tuple(value.split(","))
    if not names or any(not name for name in names):
        raise ValueError("profiles cannot be empty")
    if len(names) != len(set(names)):
        raise ValueError("profiles must be unique")
    if any(name not in PROFILES for name in names):
        raise ValueError("unknown benchmark profile")
    if names != tuple(name for name in PROFILES if name in names):
        raise ValueError("profiles must use catalog order")
    return tuple(PROFILES[name] for name in names)


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(path.expanduser()))


def _safe_run_id(value: str) -> bool:
    return 1 <= len(value) <= 128 and all(
        character.isascii() and (character.isalnum() or character in "._-") for character in value
    )


def _validate_output_path(parser: argparse.ArgumentParser, output: Path) -> None:
    if os.path.lexists(output):
        parser.error("output already exists")


def _validate_work_root(parser: argparse.ArgumentParser, work_root: Path, output: Path) -> None:
    if os.path.lexists(work_root) and (work_root.is_symlink() or not work_root.is_dir()):
        parser.error("invalid work root")
    if output == work_root or output.is_relative_to(work_root):
        parser.error("output overlaps work root")


def _reject_workspace_output(parser: argparse.ArgumentParser, output: Path) -> None:
    for ancestor in (output.parent, *output.parents):
        if (ancestor / "bundlewalker.toml").is_file():
            parser.error("output is inside a workspace")


def _ensure_output_parent(parser: argparse.ArgumentParser, output: Path) -> None:
    parent = output.parent
    if os.path.lexists(parent):
        if parent.is_symlink() or not parent.is_dir():
            parser.error("invalid output parent")
        return
    grandparent = parent.parent
    if grandparent.is_symlink() or not grandparent.is_dir():
        parser.error("output parent cannot be created")
    try:
        parent.mkdir(mode=0o700)
        parent.chmod(0o700)
    except OSError:
        parser.error("output parent cannot be created")


def _has_symlink_file(directory: Path) -> bool:
    for path in directory.glob("*.json"):
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            return True
    return False


def _bounded_error(prefix: str, error: Exception) -> None:
    print(f"{prefix}: {type(error).__name__}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
