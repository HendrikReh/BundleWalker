# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import errno
import os
import stat
from contextlib import suppress
from pathlib import Path

from bundlewalker.application import (
    DiagnosticResult,
    DiagnosticSeverity,
    SupportReport,
)


class SupportReportTargetError(Exception):
    pass


class SupportReportWriteError(Exception):
    pass


_TOKENS = {
    DiagnosticSeverity.PASS: "PASS",
    DiagnosticSeverity.WARNING: "WARN",
    DiagnosticSeverity.FAILURE: "FAIL",
}


def render_diagnostic_lines(result: DiagnosticResult) -> tuple[str, ...]:
    lines: list[str] = []
    for check in result.checks:
        lines.append(f"{_TOKENS[check.severity]} {check.code} — {check.summary}")
        lines.extend(f"  Next: {instruction}" for instruction in check.remediation)
    counts = result.counts
    lines.append(
        "Doctor: "
        f"{counts.passed} {_noun(counts.passed, 'passed', 'passed')}, "
        f"{counts.warnings} {_noun(counts.warnings, 'warning', 'warnings')}, "
        f"{counts.failures} {_noun(counts.failures, 'failure', 'failures')}."
    )
    return tuple(lines)


def _noun(value: int, singular: str, plural: str) -> str:
    return singular if value == 1 else plural


def write_support_report(report: SupportReport, destination: Path) -> None:
    content = (report.model_dump_json(indent=2) + "\n").encode("utf-8")
    try:
        descriptor = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
    except (FileExistsError, FileNotFoundError, IsADirectoryError, NotADirectoryError):
        raise SupportReportTargetError from None
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise SupportReportTargetError from None
        raise SupportReportWriteError from None

    identity: tuple[int, int] | None = None
    try:
        metadata = os.fstat(descriptor)
        identity = (metadata.st_dev, metadata.st_ino)
        if not stat.S_ISREG(metadata.st_mode):
            raise SupportReportTargetError
        os.fchmod(descriptor, 0o600)
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if written == 0:
                raise OSError
            view = view[written:]
        os.fsync(descriptor)
    except SupportReportTargetError:
        if identity is not None:
            _unlink_created_file(destination, identity)
        raise
    except OSError:
        if identity is not None:
            _unlink_created_file(destination, identity)
        raise SupportReportWriteError from None
    finally:
        with suppress(OSError):
            os.close(descriptor)


def _unlink_created_file(destination: Path, identity: tuple[int, int]) -> None:
    with suppress(OSError):
        metadata = destination.lstat()
        if stat.S_ISREG(metadata.st_mode) and (metadata.st_dev, metadata.st_ino) == identity:
            destination.unlink()
