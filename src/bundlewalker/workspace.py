from __future__ import annotations

import hashlib
import re
import shutil
import tomllib
import unicodedata
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal, cast

from bundlewalker.errors import BundleWalkerError, ConfigurationError, UsageError, WorkspaceError
from bundlewalker.okf.derived import prepend_log_entry, regenerate_indexes
from bundlewalker.okf.lint import has_errors, lint_bundle
from bundlewalker.okf.repository import OkfRepository

CONFIG_FILENAME = "bundlewalker.toml"
DEFAULT_CONFIG_TEXT = (
    'version = 1\n'
    'wiki_dir = "wiki"\n'
    'raw_dir = "raw"\n'
    'conventions_file = "conventions.md"\n'
    "max_source_characters = 100000\n"
)
DEFAULT_CONVENTIONS_TEXT = """# BundleWalker Conventions

## Writing

- Prefer concise, factual prose and descriptive headings.
- Preserve uncertainty and record conflicting claims explicitly.
- Link related concepts using OKF Markdown links.

## Naming

- Use stable, lowercase ASCII slugs for concept filenames.
- Keep tags short, normalized, and relevant.

## Knowledge maintenance

- Source pages describe what an immutable source says.
- Topic and Entity pages accumulate knowledge across sources.
- Synthesis pages capture reviewed, question-driven conclusions.
"""

_SOURCE_CATEGORIES = ("sources", "topics", "entities", "syntheses")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_MINIMUM_DIGEST_PREFIX = 12


@dataclass(frozen=True, slots=True)
class WorkspaceConfig:
    version: int = 1
    wiki_dir: str = "wiki"
    raw_dir: str = "raw"
    conventions_file: str = "conventions.md"
    max_source_characters: int = 100_000


@dataclass(frozen=True, slots=True)
class Workspace:
    root: Path
    config: WorkspaceConfig

    @property
    def wiki_dir(self) -> Path:
        return self.root / self.config.wiki_dir

    @property
    def raw_dir(self) -> Path:
        return self.root / self.config.raw_dir

    @property
    def conventions_file(self) -> Path:
        return self.root / self.config.conventions_file


@dataclass(frozen=True, slots=True)
class RawSource:
    input_path: Path
    content: bytes
    text: str
    sha256: str
    line_count: int
    extension: Literal[".md", ".txt"]
    slug: str
    stored_relative_path: Path
    concept_id: str


def discover_workspace(start: Path | None = None) -> Workspace:
    candidate = (start or Path.cwd()).expanduser().resolve(strict=False)
    if candidate.is_file():
        candidate = candidate.parent

    for directory in (candidate, *candidate.parents):
        config_path = directory / CONFIG_FILENAME
        if config_path.is_file() and not config_path.is_symlink():
            return Workspace(root=directory, config=_load_config(config_path))
    raise WorkspaceError(f"could not find {CONFIG_FILENAME} from {candidate}")


def initialize_workspace(
    path: Path,
    *,
    occurred_at: datetime | None = None,
) -> Workspace:
    root = path.expanduser().resolve(strict=False)
    created_root = not root.exists()
    created_parents = _missing_parents(root.parent) if created_root else []

    if root.is_symlink() or (root.exists() and not root.is_dir()):
        raise UsageError(f"workspace target must be a new or empty directory: {root}")
    if root.exists():
        try:
            if any(root.iterdir()):
                raise UsageError(f"workspace target must be empty: {root}")
        except OSError as exc:
            raise WorkspaceError(f"could not inspect workspace target: {root}") from exc

    try:
        root.mkdir(parents=True, exist_ok=not created_root)
        (root / CONFIG_FILENAME).write_text(DEFAULT_CONFIG_TEXT, encoding="utf-8")
        (root / "conventions.md").write_text(DEFAULT_CONVENTIONS_TEXT, encoding="utf-8")
        (root / "raw").mkdir()
        wiki_dir = root / "wiki"
        for category in _SOURCE_CATEGORIES:
            (wiki_dir / category).mkdir(parents=True)

        regenerate_indexes(wiki_dir)
        prepend_log_entry(
            wiki_dir,
            "Initialized the knowledge workspace.",
            date=occurred_at or datetime.now(UTC),
            kind="Initialization",
        )
        workspace = Workspace(root=root, config=_load_config(root / CONFIG_FILENAME))
        findings = lint_bundle(workspace.wiki_dir, workspace.root)
        if has_errors(findings):
            codes = ", ".join(sorted({finding.code for finding in findings}))
            raise WorkspaceError(f"initialized workspace failed deterministic lint: {codes}")
        return workspace
    except BaseException as exc:
        _rollback_initialization(root, created_root, created_parents)
        if isinstance(exc, BundleWalkerError):
            raise
        if isinstance(exc, Exception):
            raise WorkspaceError(f"could not initialize workspace: {root}") from exc
        raise


def stable_source_paths(
    workspace: Workspace,
    sha256: str,
    slug: str,
    extension: Literal[".md", ".txt"],
) -> tuple[Path, str]:
    if _SHA256.fullmatch(sha256) is None:
        raise WorkspaceError("source identity must be a lowercase SHA-256 digest")
    if _SLUG.fullmatch(slug) is None:
        raise WorkspaceError(f"invalid source slug: {slug}")
    if extension not in {".md", ".txt"}:
        raise WorkspaceError("source extension must be .md or .txt")

    existing = _source_identities(workspace)
    if duplicate := existing.get(sha256):
        return duplicate

    other_digests = tuple(existing)
    prefix_length = _MINIMUM_DIGEST_PREFIX
    while prefix_length < len(sha256):
        prefix = sha256[:prefix_length]
        if not any(digest.startswith(prefix) for digest in other_digests):
            break
        prefix_length += 1

    while True:
        prefix = sha256[:prefix_length]
        stored_path = Path(workspace.config.raw_dir) / f"{prefix}-{slug}{extension}"
        absolute_path = workspace.root / stored_path
        concept_id = f"sources/{prefix}-{slug}"
        concept_path = workspace.wiki_dir / f"{concept_id}.md"
        raw_available = not absolute_path.exists() or _file_matches_digest(
            absolute_path, sha256
        )
        concept_available = not concept_path.exists() and not concept_path.is_symlink()
        if raw_available and concept_available:
            return stored_path, concept_id
        if prefix_length == len(sha256):
            raise WorkspaceError(f"source destination is occupied: {stored_path.as_posix()}")
        prefix_length += 1


def load_raw_source(path: Path, workspace: Workspace) -> RawSource:
    candidate = path.expanduser()
    if candidate.is_symlink() or not candidate.is_file():
        raise WorkspaceError(f"source must be a regular file: {candidate}")
    extension_value = candidate.suffix
    if extension_value not in {".md", ".txt"}:
        raise WorkspaceError("source extension must be .md or .txt")
    extension = cast(Literal[".md", ".txt"], extension_value)

    try:
        content = candidate.read_bytes()
    except OSError as exc:
        raise WorkspaceError(f"could not read source file: {candidate}") from exc
    try:
        text = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise WorkspaceError(f"source must contain valid UTF-8: {candidate}") from exc
    if len(text) > workspace.config.max_source_characters:
        raise WorkspaceError(
            "source exceeds the configured limit of "
            f"{workspace.config.max_source_characters} characters"
        )

    digest = hashlib.sha256(content).hexdigest()
    slug = _slugify(candidate.stem)
    stored_path, concept_id = stable_source_paths(
        workspace,
        digest,
        slug,
        extension,
    )
    return RawSource(
        input_path=candidate.resolve(strict=True),
        content=content,
        text=text,
        sha256=digest,
        line_count=len(text.splitlines()),
        extension=extension,
        slug=slug,
        stored_relative_path=stored_path,
        concept_id=concept_id,
    )


def _load_config(path: Path) -> WorkspaceConfig:
    try:
        values = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigurationError(f"could not read workspace configuration: {path}") from exc

    expected = {
        "version",
        "wiki_dir",
        "raw_dir",
        "conventions_file",
        "max_source_characters",
    }
    if set(values) != expected:
        raise ConfigurationError(f"workspace configuration has unexpected keys: {path}")

    version = values["version"]
    max_characters = values["max_source_characters"]
    if type(version) is not int or version != 1:
        raise ConfigurationError("workspace configuration version must be 1")
    if type(max_characters) is not int or max_characters < 1:
        raise ConfigurationError("max_source_characters must be a positive integer")

    path_values: dict[str, str] = {}
    for key in ("wiki_dir", "raw_dir", "conventions_file"):
        value = values[key]
        if not isinstance(value, str) or not _safe_relative_path(value):
            raise ConfigurationError(f"{key} must be a safe workspace-relative path")
        path_values[key] = value

    return WorkspaceConfig(
        version=version,
        wiki_dir=path_values["wiki_dir"],
        raw_dir=path_values["raw_dir"],
        conventions_file=path_values["conventions_file"],
        max_source_characters=max_characters,
    )


def _safe_relative_path(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(value) and not path.is_absolute() and ".." not in path.parts


def _slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.casefold()).strip("-")
    return slug or "source"


def _source_identities(workspace: Workspace) -> dict[str, tuple[Path, str]]:
    identities: dict[str, tuple[Path, str]] = {}
    try:
        documents = OkfRepository(workspace.wiki_dir).scan().values()
    except BundleWalkerError as exc:
        raise WorkspaceError("could not inspect existing source identities") from exc

    for document in documents:
        if document.metadata.type != "Source":
            continue
        extra = document.metadata.model_extra or {}
        digest = extra.get("source_sha256")
        raw_path_value = extra.get("raw_path")
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            continue
        if not isinstance(raw_path_value, str) or not _safe_relative_path(raw_path_value):
            continue
        identities.setdefault(digest, (Path(raw_path_value), document.concept_id))
    return identities


def _file_matches_digest(path: Path, expected: str) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest() == expected
    except OSError:
        return False


def _missing_parents(path: Path) -> list[Path]:
    missing: list[Path] = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
    return missing


def _rollback_initialization(
    root: Path,
    created_root: bool,
    created_parents: list[Path],
) -> None:
    if created_root:
        shutil.rmtree(root, ignore_errors=True)
    elif root.is_dir():
        for name in (CONFIG_FILENAME, "conventions.md", "raw", "wiki"):
            created_path = root / name
            if created_path.is_dir() and not created_path.is_symlink():
                shutil.rmtree(created_path, ignore_errors=True)
            else:
                created_path.unlink(missing_ok=True)
    for directory in created_parents:
        with suppress(OSError):
            directory.rmdir()
