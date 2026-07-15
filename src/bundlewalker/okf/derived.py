from __future__ import annotations

import difflib
import re
from datetime import datetime
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from bundlewalker.domain import OkfDocument
from bundlewalker.okf.repository import OkfRepository

_LOG_TITLE = "# Knowledge Update Log"
_LOG_HEADING = re.compile(r"^## (?P<date>\d{4}-\d{2}-\d{2})$")


def regenerate_indexes(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    documents = OkfRepository(root).scan()
    directories = {root}
    directories.update(path for path in root.rglob("*") if path.is_dir() and not path.is_symlink())

    for directory in sorted(directories, key=lambda path: path.relative_to(root).as_posix()):
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
            for document in documents.values()
            if PurePosixPath(document.concept_id).parent
            == PurePosixPath(relative_directory.as_posix())
        ]
        (directory / "index.md").write_text(
            render_index(
                directory,
                relative_directory,
                child_directories,
                child_documents,
            ),
            encoding="utf-8",
        )


def prepend_log_entry(
    root: Path,
    summary: str,
    *,
    date: datetime,
    kind: str = "Update",
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    log_path = root / "log.md"
    sections = _read_log_sections(log_path)
    date_heading = date.date().isoformat()
    bullet = f"* **{_one_line(kind)}**: {_one_line(summary)}"

    for section_date, bullets in sections:
        if section_date == date_heading:
            bullets.insert(0, bullet)
            break
    else:
        sections.append((date_heading, [bullet]))
        sections.sort(key=lambda section: section[0], reverse=True)

    log_path.write_text(_render_log(sections), encoding="utf-8")


def tree_diff(old: Path, new: Path) -> str:
    old_files = _read_text_tree(old)
    new_files = _read_text_tree(new)
    chunks: list[str] = []
    relative_paths = sorted(set(old_files) | set(new_files), key=PurePosixPath.as_posix)

    for relative_path in relative_paths:
        old_text = old_files.get(relative_path)
        new_text = new_files.get(relative_path)
        if old_text == new_text:
            continue
        old_name = f"wiki/{relative_path.as_posix()}" if old_text is not None else "/dev/null"
        new_name = f"wiki/{relative_path.as_posix()}" if new_text is not None else "/dev/null"
        diff_chunks = difflib.unified_diff(
            [] if old_text is None else old_text.splitlines(keepends=True),
            [] if new_text is None else new_text.splitlines(keepends=True),
            fromfile=old_name,
            tofile=new_name,
            lineterm="\n",
        )
        chunks.extend(_terminate_diff_chunk(chunk) for chunk in diff_chunks)
    return "".join(chunks)


def _terminate_diff_chunk(chunk: str) -> str:
    if chunk.endswith(("\n", "\r")):
        return chunk
    return f"{chunk}\n\\ No newline at end of file\n"


def render_index(
    directory: Path,
    relative_directory: Path,
    child_directories: list[Path],
    child_documents: list[OkfDocument],
) -> str:
    title = (
        "Knowledge Index"
        if relative_directory == Path(".")
        else _directory_title(relative_directory.name)
    )
    sections = [f"# {title}"]
    if child_directories:
        directory_lines = [
            (
                f"* {_markdown_link(_directory_title(path.name), f'{path.name}/index.md')} - "
                f"Browse {_directory_title(path.name)} concepts."
            )
            for path in child_directories
        ]
        sections.append("## Directories\n\n" + "\n".join(directory_lines))
    if child_documents:
        concept_lines: list[str] = []
        for item in child_documents:
            target = item.path.relative_to(directory).as_posix()
            title = item.metadata.title or _directory_title(PurePosixPath(item.concept_id).name)
            description = item.metadata.description or ""
            concept_lines.append(f"* {_markdown_link(title, target)} - {description}")
        sections.append("## Concepts\n\n" + "\n".join(concept_lines))
    return "\n\n".join(sections) + "\n"


def _directory_title(name: str) -> str:
    return name.replace("-", " ").title()


def _markdown_link(label: str, target: str) -> str:
    escaped_label = label.replace("\\", "\\\\").replace("[", r"\[").replace("]", r"\]")
    return f"[{escaped_label}]({quote(target, safe='/')})"


def _one_line(value: str) -> str:
    return " ".join(value.split())


def _read_log_sections(path: Path) -> list[tuple[str, list[str]]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    sections: list[tuple[str, list[str]]] = []
    for line in lines:
        if match := _LOG_HEADING.fullmatch(line):
            sections.append((match.group("date"), []))
        elif line.startswith("* ") and sections:
            sections[-1][1].append(line)
    return sections


def _render_log(sections: list[tuple[str, list[str]]]) -> str:
    rendered_sections = [
        f"## {section_date}\n\n" + "\n".join(bullets) for section_date, bullets in sections
    ]
    if not rendered_sections:
        return f"{_LOG_TITLE}\n"
    return f"{_LOG_TITLE}\n\n" + "\n\n".join(rendered_sections) + "\n"


def _read_text_tree(root: Path) -> dict[PurePosixPath, str]:
    files: dict[PurePosixPath, str] = {}
    if not root.is_dir():
        return files
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        files[PurePosixPath(path.relative_to(root).as_posix())] = text
    return files
