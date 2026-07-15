from __future__ import annotations

import re
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

from bundlewalker.domain import FindingOrigin, LintFinding, OkfDocument, Severity
from bundlewalker.errors import OkfError
from bundlewalker.okf.derived import render_index
from bundlewalker.okf.documents import RESERVED_NAMES, parse_document
from bundlewalker.paths import normalize_workspace_config_path

_SEVERITY_ORDER = {
    Severity.ERROR: 0,
    Severity.WARNING: 1,
    Severity.INFO: 2,
}
_LOG_HEADING = re.compile(r"^## (?P<date>.+)$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_RESOURCE = re.compile(r"^urn:bundlewalker:source:sha256:[0-9a-f]{64}$")
_CITATION_HEADING = re.compile(r"^# Citations[ \t]*$", re.MULTILINE)
_CITATION_MARKER = re.compile(r"\[(\d+)]")
_CITATION_REFERENCE_PREFIX = re.compile(r"^\[(\d+)]")
_CITATION_REFERENCE = re.compile(
    r"^\[(?P<number>\d+)]\s+\[[^]]+]\((?P<target>[^)]+)\)"
    r"(?:\s+[—-]\s+raw lines (?P<start>\d+)[\u2013-](?P<end>\d+))?\s*$"
)


@dataclass(frozen=True, slots=True)
class _RawSource:
    line_count: int


@dataclass(frozen=True, slots=True)
class _CitationReference:
    number: int
    target: str
    start_line: int | None
    end_line: int | None


def lint_bundle(wiki_root: Path, workspace_root: Path | None = None) -> list[LintFinding]:
    """Return all deterministic conformance and health findings for an OKF bundle."""
    if not wiki_root.is_dir():
        return [
            _finding(
                Severity.ERROR,
                "OKF001",
                "bundle root is not a directory",
            )
        ]

    documents, findings = _parse_documents(wiki_root)
    findings.extend(_lint_indexes(wiki_root, documents))
    findings.extend(_lint_logs(wiki_root))
    link_findings, inbound_counts = _lint_links(wiki_root, documents)
    findings.extend(link_findings)
    findings.extend(_lint_orphans(wiki_root, documents, inbound_counts))

    if workspace_root is not None:
        raw_sources, source_findings = _lint_sources(
            wiki_root,
            workspace_root,
            documents,
        )
        findings.extend(source_findings)
        findings.extend(
            _lint_citations(
                wiki_root,
                documents,
                raw_sources,
            )
        )

    return sorted(
        findings,
        key=lambda finding: (
            _SEVERITY_ORDER[finding.severity],
            finding.code,
            finding.path or "",
            finding.message,
        ),
    )


def has_errors(findings: Iterable[LintFinding]) -> bool:
    return any(finding.severity is Severity.ERROR for finding in findings)


def _parse_documents(root: Path) -> tuple[list[OkfDocument], list[LintFinding]]:
    documents: list[OkfDocument] = []
    findings: list[LintFinding] = []
    folded_ids: dict[str, OkfDocument] = {}

    try:
        paths = sorted(
            (
                path
                for path in root.rglob("*")
                if path.is_file()
                and path.suffix.casefold() == ".md"
                and path.name.casefold() not in RESERVED_NAMES
            ),
            key=lambda path: path.relative_to(root).as_posix(),
        )
    except OSError:
        return [], [_finding(Severity.ERROR, "OKF001", "cannot scan bundle root")]

    for path in paths:
        relative_path = path.relative_to(root).as_posix()
        try:
            document = parse_document(path, root)
        except OkfError as exc:
            message = str(exc).replace(str(path), relative_path)
            findings.append(_finding(Severity.ERROR, "OKF001", message, relative_path))
            continue

        if previous := folded_ids.get(document.concept_id.casefold()):
            findings.append(
                _finding(
                    Severity.ERROR,
                    "OKF001",
                    (
                        "case-folded concept path collision: "
                        f"{previous.concept_id} and {document.concept_id}"
                    ),
                    relative_path,
                )
            )
        else:
            folded_ids[document.concept_id.casefold()] = document
        documents.append(document)

    documents.sort(key=lambda document: document.concept_id)
    return documents, findings


def _lint_indexes(root: Path, documents: list[OkfDocument]) -> list[LintFinding]:
    findings: list[LintFinding] = []
    try:
        directories = {root}
        directories.update(
            path for path in root.rglob("*") if path.is_dir() and not path.is_symlink()
        )
    except OSError:
        return [_finding(Severity.ERROR, "INDEX001", "cannot scan bundle directories")]

    ordered_directories = sorted(
        directories,
        key=lambda path: path.relative_to(root).as_posix(),
    )
    for directory in ordered_directories:
        relative_directory = directory.relative_to(root)
        child_directories = sorted(
            (
                candidate
                for candidate in directories
                if candidate != root and candidate.parent == directory
            ),
            key=lambda path: path.relative_to(root).as_posix(),
        )
        child_documents = [
            document
            for document in documents
            if PurePosixPath(document.concept_id).parent
            == PurePosixPath(relative_directory.as_posix())
        ]
        index_path = directory / "index.md"
        relative_index = index_path.relative_to(root).as_posix()
        expected = render_index(
            directory,
            relative_directory,
            child_directories,
            child_documents,
        )
        if not index_path.is_file() or index_path.is_symlink():
            findings.append(
                _finding(
                    Severity.ERROR,
                    "INDEX001",
                    "missing generated index",
                    relative_index,
                )
            )
            continue
        try:
            actual = index_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            findings.append(
                _finding(
                    Severity.ERROR,
                    "INDEX001",
                    "generated index is not readable UTF-8",
                    relative_index,
                )
            )
            continue
        if actual != expected:
            findings.append(
                _finding(
                    Severity.ERROR,
                    "INDEX001",
                    "stale generated index",
                    relative_index,
                )
            )
    return findings


def _lint_logs(root: Path) -> list[LintFinding]:
    findings: list[LintFinding] = []
    try:
        log_paths = sorted(
            (
                path
                for path in root.rglob("*")
                if path.is_file() and path.name.casefold() == "log.md"
            ),
            key=lambda path: path.relative_to(root).as_posix(),
        )
    except OSError:
        return [_finding(Severity.ERROR, "LOG001", "cannot scan bundle logs")]

    for path in log_paths:
        relative_path = path.relative_to(root).as_posix()
        if path.is_symlink() or not path.resolve(strict=False).is_relative_to(
            root.resolve(strict=False)
        ):
            findings.append(
                _finding(Severity.ERROR, "LOG001", "log path escapes bundle", relative_path)
            )
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            findings.append(
                _finding(
                    Severity.ERROR,
                    "LOG001",
                    "log is not readable UTF-8",
                    relative_path,
                )
            )
            continue
        for line in lines:
            match = _LOG_HEADING.fullmatch(line)
            if match is None:
                continue
            value = match.group("date")
            try:
                parsed = date.fromisoformat(value)
            except ValueError:
                parsed = None
            if parsed is None or parsed.isoformat() != value:
                findings.append(
                    _finding(
                        Severity.ERROR,
                        "LOG001",
                        f"invalid log date: {value}",
                        relative_path,
                    )
                )
    return findings


def _lint_links(
    root: Path,
    documents: list[OkfDocument],
) -> tuple[list[LintFinding], dict[str, int]]:
    findings: list[LintFinding] = []
    inbound_counts = {document.concept_id: 0 for document in documents}
    documents_by_path = {
        document.path.resolve(strict=False): document for document in documents
    }
    reported_broken_links: set[tuple[str, str]] = set()

    for document in documents:
        relative_path = document.path.relative_to(root).as_posix()
        for href in document.links:
            internal, target = _resolve_internal_link(root, document.path, href)
            if not internal:
                continue
            if target is None or not target.is_file():
                key = (document.concept_id, href)
                if key not in reported_broken_links:
                    findings.append(
                        _finding(
                            Severity.WARNING,
                            "LINK001",
                            f"broken internal link: {href}",
                            relative_path,
                        )
                    )
                    reported_broken_links.add(key)
                continue
            if linked_document := documents_by_path.get(target):
                inbound_counts[linked_document.concept_id] += 1
    return findings, inbound_counts


def _lint_orphans(
    root: Path,
    documents: list[OkfDocument],
    inbound_counts: dict[str, int],
) -> list[LintFinding]:
    return [
        _finding(
            Severity.WARNING,
            "ORPHAN001",
            "concept has no inbound concept links",
            document.path.relative_to(root).as_posix(),
        )
        for document in documents
        if inbound_counts[document.concept_id] == 0
    ]


def _lint_sources(
    wiki_root: Path,
    workspace_root: Path,
    documents: list[OkfDocument],
) -> tuple[dict[str, _RawSource], list[LintFinding]]:
    sources: dict[str, _RawSource] = {}
    findings: list[LintFinding] = []
    resolved_workspace = workspace_root.resolve(strict=False)
    configured_raw_directory = _configured_raw_directory(workspace_root)

    for document in documents:
        if document.metadata.type != "Source":
            continue
        relative_document = document.path.relative_to(wiki_root).as_posix()
        extra = document.metadata.model_extra or {}
        source_digest = extra.get("source_sha256")
        raw_path_value = extra.get("raw_path")

        valid_digest = (
            isinstance(source_digest, str) and _SHA256.fullmatch(source_digest) is not None
        )
        if not valid_digest:
            findings.append(
                _finding(
                    Severity.ERROR,
                    "SOURCE001",
                    "source_sha256 must be a lowercase 64-character SHA-256 digest",
                    relative_document,
                )
            )

        resource = document.metadata.resource
        if resource is None or _SOURCE_RESOURCE.fullmatch(resource) is None:
            findings.append(
                _finding(
                    Severity.ERROR,
                    "SOURCE001",
                    "resource must be a BundleWalker source SHA-256 URN",
                    relative_document,
                )
            )
        elif valid_digest and resource != f"urn:bundlewalker:source:sha256:{source_digest}":
            findings.append(
                _finding(
                    Severity.ERROR,
                    "SOURCE001",
                    "resource must match source_sha256",
                    relative_document,
                )
            )

        raw_relative = _workspace_relative_path(raw_path_value)
        if raw_relative is None:
            findings.append(
                _finding(
                    Severity.ERROR,
                    "SOURCE001",
                    "raw_path must be a normalized workspace-relative path",
                    relative_document,
                )
            )
            continue
        if not raw_relative.is_relative_to(configured_raw_directory):
            findings.append(
                _finding(
                    Severity.ERROR,
                    "SOURCE001",
                    (
                        "raw_path must be below "
                        f"{configured_raw_directory.as_posix()}/"
                    ),
                    relative_document,
                )
            )
            continue
        if raw_relative.suffix not in {".md", ".txt"}:
            findings.append(
                _finding(
                    Severity.ERROR,
                    "SOURCE001",
                    "raw_path must identify a .md or .txt file",
                    relative_document,
                )
            )
            continue

        raw_path = workspace_root.joinpath(*raw_relative.parts)
        resolved_raw_path = raw_path.resolve(strict=False)
        if not resolved_raw_path.is_relative_to(resolved_workspace):
            findings.append(
                _finding(
                    Severity.ERROR,
                    "SOURCE001",
                    "raw_path escapes workspace",
                    relative_document,
                )
            )
            continue
        if raw_path.is_symlink() or not raw_path.is_file():
            findings.append(
                _finding(
                    Severity.ERROR,
                    "SOURCE001",
                    f"raw_path does not identify a regular file: {raw_relative.as_posix()}",
                    relative_document,
                )
            )
            continue
        try:
            raw_bytes = raw_path.read_bytes()
        except OSError:
            findings.append(
                _finding(
                    Severity.ERROR,
                    "SOURCE001",
                    f"cannot read raw_path: {raw_relative.as_posix()}",
                    relative_document,
                )
            )
            continue
        if valid_digest and sha256(raw_bytes).hexdigest() != source_digest:
            findings.append(
                _finding(
                    Severity.ERROR,
                    "SOURCE001",
                    "source_sha256 does not match raw bytes",
                    relative_document,
                )
            )
        try:
            raw_text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            findings.append(
                _finding(
                    Severity.ERROR,
                    "SOURCE001",
                    "raw source is not UTF-8",
                    relative_document,
                )
            )
            continue
        sources[document.concept_id] = _RawSource(
            line_count=len(raw_text.splitlines()),
        )
    return sources, findings


def _lint_citations(
    root: Path,
    documents: list[OkfDocument],
    raw_sources: dict[str, _RawSource],
) -> list[LintFinding]:
    findings: list[LintFinding] = []
    documents_by_path = {
        document.path.resolve(strict=False): document for document in documents
    }

    for document in documents:
        relative_path = document.path.relative_to(root).as_posix()
        heading = _CITATION_HEADING.search(document.body)
        claims = document.body if heading is None else document.body[: heading.start()]
        references_text = "" if heading is None else document.body[heading.end() :]
        marker_numbers = [int(number) for number in _CITATION_MARKER.findall(claims)]
        references, malformed_numbers = _parse_citation_references(references_text)
        reference_numbers = [reference.number for reference in references]

        for number in malformed_numbers:
            findings.append(
                _finding(
                    Severity.ERROR,
                    "CITATION001",
                    f"citation reference {number} is malformed",
                    relative_path,
                )
            )

        all_numbers = sorted(set(marker_numbers) | set(reference_numbers))
        contiguous_numbers = list(range(1, max(all_numbers) + 1)) if all_numbers else []
        if (
            set(marker_numbers) != set(reference_numbers)
            or len(reference_numbers) != len(set(reference_numbers))
            or all_numbers != contiguous_numbers
        ):
            findings.append(
                _finding(
                    Severity.ERROR,
                    "CITATION001",
                    (
                        "citation markers do not match references: "
                        f"markers={sorted(set(marker_numbers))}, "
                        f"references={sorted(reference_numbers)}"
                    ),
                    relative_path,
                )
            )

        for reference in references:
            internal, target_path = _resolve_internal_link(root, document.path, reference.target)
            target = documents_by_path.get(target_path) if internal and target_path else None
            if target is None:
                findings.append(
                    _finding(
                        Severity.ERROR,
                        "CITATION001",
                        f"citation {reference.number} does not reference an existing concept",
                        relative_path,
                    )
                )
                continue
            if reference.start_line is None or reference.end_line is None:
                continue
            if target.metadata.type != "Source":
                findings.append(
                    _finding(
                        Severity.ERROR,
                        "CITATION001",
                        f"citation {reference.number} line range does not target a Source concept",
                        relative_path,
                    )
                )
                continue
            raw_source = raw_sources.get(target.concept_id)
            if raw_source is None:
                findings.append(
                    _finding(
                        Severity.ERROR,
                        "CITATION001",
                        f"citation {reference.number} line range cannot be verified",
                        relative_path,
                    )
                )
                continue
            if (
                reference.start_line < 1
                or reference.end_line < reference.start_line
                or reference.end_line > raw_source.line_count
            ):
                findings.append(
                    _finding(
                        Severity.ERROR,
                        "CITATION001",
                        (
                            f"citation {reference.number} line range "
                            f"{reference.start_line}-{reference.end_line} is outside "
                            f"raw source lines 1-{raw_source.line_count}"
                        ),
                        relative_path,
                    )
                )
    return findings


def _parse_citation_references(
    text: str,
) -> tuple[list[_CitationReference], list[int]]:
    references: list[_CitationReference] = []
    malformed_numbers: list[int] = []
    for line in text.splitlines():
        prefix = _CITATION_REFERENCE_PREFIX.match(line)
        if prefix is None:
            continue
        match = _CITATION_REFERENCE.fullmatch(line)
        if match is None:
            malformed_numbers.append(int(prefix.group(1)))
            continue
        start = match.group("start")
        end = match.group("end")
        references.append(
            _CitationReference(
                number=int(match.group("number")),
                target=match.group("target"),
                start_line=int(start) if start is not None else None,
                end_line=int(end) if end is not None else None,
            )
        )
    return references, malformed_numbers


def _resolve_internal_link(
    root: Path,
    source_path: Path,
    href: str,
) -> tuple[bool, Path | None]:
    try:
        parsed = urlsplit(href)
        if parsed.scheme or parsed.netloc or not parsed.path:
            return False, None
        target_value = unquote(parsed.path)
        relative = PurePosixPath(target_value.lstrip("/"))
        candidate = (
            root.joinpath(*relative.parts)
            if target_value.startswith("/")
            else source_path.parent.joinpath(*relative.parts)
        )
        if target_value.endswith("/"):
            candidate /= "index.md"
        resolved_root = root.resolve(strict=False)
        resolved_candidate = candidate.resolve(strict=False)
    except (ValueError, OSError, RuntimeError):
        return True, None
    if not resolved_candidate.is_relative_to(resolved_root):
        return True, None
    return True, resolved_candidate


def _workspace_relative_path(value: object) -> PurePosixPath | None:
    if not isinstance(value, str) or not value:
        return None
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or relative == PurePosixPath(".")
        or relative.as_posix() != value
    ):
        return None
    return relative


def _configured_raw_directory(workspace_root: Path) -> PurePosixPath:
    try:
        with (workspace_root / "bundlewalker.toml").open("rb") as config_file:
            values = tomllib.load(config_file)
    except (OSError, tomllib.TOMLDecodeError):
        return PurePosixPath("raw")
    configured = normalize_workspace_config_path(values.get("raw_dir"))
    return PurePosixPath(configured or "raw")


def _finding(
    severity: Severity,
    code: str,
    message: str,
    path: str | None = None,
) -> LintFinding:
    return LintFinding(
        origin=FindingOrigin.DETERMINISTIC,
        severity=severity,
        code=code,
        message=message,
        path=path,
    )
