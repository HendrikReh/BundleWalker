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
        resolved_output = _resolved_nonexistent_path(parser, output, "output")
        resolved_work_root = _resolved_work_root(parser, work_root)
        _validate_work_root(parser, resolved_work_root, resolved_output)
        _reject_workspace_output(parser, resolved_output)
        _reject_workspace_output(parser, resolved_work_root)
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
    resolved_output = _resolved_nonexistent_path(parser, output, "output")
    _reject_workspace_output(parser, resolved_output)
    _ensure_output_parent(parser, output)

    try:
        evidence_directory = _require_unaliased_directory(evidence_directory)
        if _has_symlink_file(evidence_directory):
            raise ValueError("evidence directory contains a nonregular JSON entry")
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
    if output == work_root or output.is_relative_to(work_root) or work_root.is_relative_to(output):
        parser.error("output overlaps work root")


def _reject_workspace_output(parser: argparse.ArgumentParser, output: Path) -> None:
    for ancestor in output.parents:
        configuration = ancestor / "bundlewalker.toml"
        if configuration.is_file() and not configuration.is_symlink():
            parser.error("output is inside a workspace")


def _resolved_nonexistent_path(parser: argparse.ArgumentParser, path: Path, label: str) -> Path:
    parent = path.parent
    try:
        if os.path.lexists(parent):
            resolved_parent = _require_unaliased_directory(parent)
        else:
            resolved_grandparent = _require_unaliased_directory(parent.parent)
            resolved_parent = resolved_grandparent / parent.name
    except ValueError:
        parser.error(f"invalid {label} path")
    return resolved_parent / path.name


def _resolved_work_root(parser: argparse.ArgumentParser, work_root: Path) -> Path:
    cursor = work_root
    missing_names: list[str] = []
    while not os.path.lexists(cursor):
        if cursor == cursor.parent:
            parser.error("invalid work root")
        missing_names.append(cursor.name)
        cursor = cursor.parent
    try:
        resolved = _require_unaliased_directory(cursor)
    except ValueError:
        parser.error("invalid work root")
    for name in reversed(missing_names):
        resolved /= name
    return resolved


def _require_unaliased_directory(path: Path) -> Path:
    absolute = _absolute(path)
    if path.is_symlink() or not path.is_dir():
        raise ValueError("path must be an existing non-symlink directory")
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise ValueError("path could not be resolved") from error
    if resolved != absolute:
        raise ValueError("path must not cross a symlink boundary")
    return resolved


def _ensure_output_parent(parser: argparse.ArgumentParser, output: Path) -> None:
    parent = output.parent
    if os.path.lexists(parent):
        try:
            _require_unaliased_directory(parent)
        except ValueError:
            parser.error("invalid output parent")
        return
    grandparent = parent.parent
    try:
        _require_unaliased_directory(grandparent)
    except ValueError:
        parser.error("output parent cannot be created")
    try:
        parent.mkdir(mode=0o700)
        parent.chmod(0o700)
        _require_unaliased_directory(parent)
    except OSError:
        parser.error("output parent cannot be created")
    except ValueError:
        parser.error("output parent changed during creation")


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
