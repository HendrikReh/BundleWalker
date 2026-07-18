# GPL and Generated-Output Licensing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** License BundleWalker's software under GPL-3.0-or-later while dedicating copied
convention presets under CC0-1.0, publishing accurate package metadata, and preserving unrestricted
user-created workspaces.

**Architecture:** Treat legal texts and path scope as immutable release inputs, expose their
combined SPDX expression through PEP 639 metadata, and verify the built wheel and source archive.
Keep generated-workspace inputs byte-stable by declaring their CC0 scope centrally, while adding
machine-readable GPL headers only to Python source and test files.

**Tech Stack:** GNU GPL v3, CC0 1.0 Universal, SPDX, PEP 639, TOML, Markdown, Python 3.13,
Hatchling, uv, pytest, Markdown-it, Git

## Global Constraints

- Use the package license expression exactly `GPL-3.0-or-later AND CC0-1.0`.
- Use `Copyright (C) 2026 Hendrik Reh` for the current GPL-covered Python files.
- Create root `LICENSE` from the complete, unmodified GNU GPL version 3 plaintext.
- Create `LICENSES/CC0-1.0.txt` from the complete, unmodified CC0 1.0 Universal legal code.
- Map exactly the five existing `src/bundlewalker/convention_presets/*.md` files to CC0-1.0.
- Keep every convention preset and internal agent prompt byte-for-byte unchanged.
- Do not add license banners or notices to generated workspaces.
- Add the exact GPL copyright/SPDX header to every `.py` file under `src/` and `tests/`.
- Discover Python files dynamically in the policy test; do not hard-code the current file count.
- Keep third-party dependencies under their own terms and stop if the direct-license audit is
  conflicting or unclear.
- Do not change runtime behavior, CLI/MCP interfaces, dependency versions, package version `0.2.0`,
  or the existing `v2` tag.
- Do not create or publish a package release, GitHub release, tag, or remote change.
- Preserve the pre-existing untracked backup archive without reading, staging, modifying, moving,
  or deleting it.

---

## File map

- Create `LICENSE`: complete official GNU GPL version 3 text.
- Create `LICENSES/CC0-1.0.txt`: complete official CC0 1.0 Universal legal code.
- Create `LICENSE-SCOPE.md`: authoritative path mapping and generated-output explanation.
- Modify `pyproject.toml`: PEP 639 SPDX expression and included legal files.
- Modify `README.md`: license navigation and user-facing policy summary.
- Modify `CONTRIBUTING.md`: inbound terms matching the target path's outbound license.
- Modify `CHANGELOG.md`: unreleased licensing entry.
- Modify `tests/test_release_metadata.py`: legal-text, package-metadata, scope, and Python-header
  policy tests.
- Modify every `.py` file under `src/` and `tests/`: two-line GPL copyright/SPDX header.

### Task 1: Add Legal Artifacts, Package Metadata, and Policy Documentation

**Files:**
- Create: `LICENSE`
- Create: `LICENSES/CC0-1.0.txt`
- Create: `LICENSE-SCOPE.md`
- Modify: `pyproject.toml:1-20`
- Modify: `README.md:1-220`
- Modify: `CONTRIBUTING.md:1-190`
- Modify: `CHANGELOG.md:1-45`
- Test: `tests/test_release_metadata.py`

**Interfaces:**
- Consumes: the approved design in
  `docs/superpowers/specs/2026-07-18-gpl-licensing-design.md`; official GPL and CC0 plaintext;
  current PEP 639 `[project]` metadata; the five packaged convention preset paths.
- Produces: `LICENSE_EXPRESSION`, `LICENSE_FILES`, `OFFICIAL_LICENSE_SHA256`, and
  `CC0_PRESET_PATHS` policy constants in `tests/test_release_metadata.py`; three legal artifacts
  included by the build backend; public license and contribution documentation used by Task 2's
  final verification.

- [ ] **Step 1: Establish repository and immutable-release baselines**

Run:

```bash
test ! -e LICENSE
test ! -e LICENSES/CC0-1.0.txt
test ! -e LICENSE-SCOPE.md
test "$(git rev-parse 'v2^{}')" = "12ef119ac3b2ba84cff7ca9aee0fbf14b239d975"
test "$(uv run python -c 'import bundlewalker; print(bundlewalker.__version__)')" = "0.2.0"
git status --short --branch
```

Expected: all commands exit `0`; no legal artifacts exist; `v2` still peels to `12ef119`; the
package version is `0.2.0`. In the main checkout the unrelated backup archive remains the only
pre-existing untracked artifact; in an isolated worktree it is absent.

- [ ] **Step 2: Audit direct dependency license grants before relicensing**

Run:

```bash
uv run python - <<'PY'
from importlib.metadata import distribution

PACKAGES = (
    "jsonschema",
    "markdown-it-py",
    "mcp",
    "pydantic-ai",
    "PyYAML",
    "typer",
)

for package in PACKAGES:
    installed = distribution(package)
    license_files = [
        item
        for item in installed.files or []
        if ".dist-info/licenses/" in item.as_posix()
    ]
    texts = [
        installed.locate_file(item).read_text(encoding="utf-8", errors="strict")
        for item in license_files
    ]
    assert any(
        "Permission is hereby granted" in text
        and "sublicense" in text
        and "sell copies" in text
        for text in texts
    ), f"unclear or non-permissive direct license: {package} {installed.version}"
    print(f"{package} {installed.version}: permissive grant found")
PY
```

Expected: prints one `permissive grant found` line for each of the six direct dependencies and
exits `0`. If any assertion fails, stop for a new licensing decision; do not weaken this audit or
continue with ambiguous terms.

- [ ] **Step 3: Add failing release-policy tests for metadata, legal text, and CC0 scope**

In `tests/test_release_metadata.py`, add `hashlib` to the imports and add these constants below
`PROJECT_ROOT`:

```python
LICENSE_EXPRESSION = "GPL-3.0-or-later AND CC0-1.0"
LICENSE_FILES = ["LICENSE", "LICENSES/CC0-1.0.txt", "LICENSE-SCOPE.md"]
OFFICIAL_LICENSE_SHA256 = {
    "LICENSE": "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986",
    "LICENSES/CC0-1.0.txt": "a2010f343487d3f7618affe54f789f5487602331c0a8d03f49e9a7c547cf0499",
}
CC0_PRESET_PATHS = {
    "src/bundlewalker/convention_presets/agent-context.md",
    "src/bundlewalker/convention_presets/default.md",
    "src/bundlewalker/convention_presets/personal-workbook.md",
    "src/bundlewalker/convention_presets/research-agent.md",
    "src/bundlewalker/convention_presets/software-agent.md",
}
```

Add these tests after `test_v2_release_versions_are_consistent`:

```python
def test_license_metadata_and_files_are_declared() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["license"] == LICENSE_EXPRESSION
    assert project["project"]["license-files"] == LICENSE_FILES
    assert all((PROJECT_ROOT / relative).is_file() for relative in LICENSE_FILES)


def test_official_license_texts_are_unmodified() -> None:
    for relative, expected_digest in OFFICIAL_LICENSE_SHA256.items():
        content = (PROJECT_ROOT / relative).read_bytes()
        assert hashlib.sha256(content).hexdigest() == expected_digest


def test_cc0_scope_matches_the_packaged_convention_presets() -> None:
    actual_presets = {
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in (PROJECT_ROOT / "src/bundlewalker/convention_presets").glob("*.md")
    }
    scope = (PROJECT_ROOT / "LICENSE-SCOPE.md").read_text(encoding="utf-8")

    assert actual_presets == CC0_PRESET_PATHS
    assert all(f"`{relative}`" in scope for relative in CC0_PRESET_PATHS)
    assert "All other project-owned files are licensed under GPL-3.0-or-later." in scope
    assert "generated `conventions.md`" in scope
```

- [ ] **Step 4: Run the focused tests to verify the policy is absent**

Run:

```bash
uv run pytest \
  tests/test_release_metadata.py::test_license_metadata_and_files_are_declared \
  tests/test_release_metadata.py::test_official_license_texts_are_unmodified \
  tests/test_release_metadata.py::test_cc0_scope_matches_the_packaged_convention_presets -q
```

Expected: FAIL before implementation. The first failure reports missing `project.license`; the
legal-artifact tests also cannot pass because the three files do not exist.

- [ ] **Step 5: Create the two official legal texts verbatim and verify their fingerprints**

Retrieve the complete plaintext bodies from these authoritative sources:

```text
https://www.gnu.org/licenses/gpl-3.0.txt
https://creativecommons.org/publicdomain/zero/1.0/legalcode.txt
```

Use `apply_patch` to create `LICENSE` from the first response body and
`LICENSES/CC0-1.0.txt` from the second response body. Copy each response byte-for-byte as UTF-8
with LF line endings. Do not prepend a project copyright, Markdown fence, explanation, or SPDX
header to either standardized legal text.

Run:

```bash
test "$(shasum -a 256 LICENSE | awk '{print $1}')" = \
  "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986"
test "$(wc -l < LICENSE | tr -d ' ')" = "674"
test "$(shasum -a 256 LICENSES/CC0-1.0.txt | awk '{print $1}')" = \
  "a2010f343487d3f7618affe54f789f5487602331c0a8d03f49e9a7c547cf0499"
test "$(wc -l < LICENSES/CC0-1.0.txt | tr -d ' ')" = "121"
```

Expected: all four checks exit `0`. A fingerprint mismatch means the local legal text is not the
approved authoritative body; fix it before proceeding.

- [ ] **Step 6: Create the path-specific license scope document**

Create `LICENSE-SCOPE.md` with exactly:

```markdown
# BundleWalker License Scope

BundleWalker is an open-source distribution containing project-owned material under two sets of
terms. The license assigned to a file depends on its path.

## GPL-3.0-or-later

All other project-owned files are licensed under GPL-3.0-or-later. This includes BundleWalker's
application code, tests, documentation, internal agent prompts, and repository configuration.

See the complete [GNU General Public License version 3](LICENSE). BundleWalker grants the option
to use GPL version 3 or any later version.

Copyright (C) 2026 Hendrik Reh

## CC0-1.0 convention presets

Exactly these convention preset resources are dedicated under CC0-1.0:

- `src/bundlewalker/convention_presets/agent-context.md`
- `src/bundlewalker/convention_presets/default.md`
- `src/bundlewalker/convention_presets/personal-workbook.md`
- `src/bundlewalker/convention_presets/research-agent.md`
- `src/bundlewalker/convention_presets/software-agent.md`

The CC0 dedication applies to the source resources and to their preset content copied into a
generated `conventions.md`. See the complete [CC0 1.0 Universal legal
code](LICENSES/CC0-1.0.txt).

## User content and generated workspaces

BundleWalker does not claim copyright in user-provided sources, user-authored knowledge, or
model-generated content merely because BundleWalker processed it. The CC0 convention scaffolding
does not restrict the terms users choose for their generated workspaces. Users remain responsible
for rights in their inputs and any third-party material.

## Third-party software

BundleWalker's dependencies retain their own copyrights and licenses. They are not relicensed by
this repository.
```

- [ ] **Step 7: Declare the combined PEP 639 package license**

In `pyproject.toml`, immediately after `readme = "README.md"`, add:

```toml
license = "GPL-3.0-or-later AND CC0-1.0"
license-files = ["LICENSE", "LICENSES/CC0-1.0.txt", "LICENSE-SCOPE.md"]
```

Do not add legacy `License ::` classifiers or alter the project version, dependencies, or build
backend.

- [ ] **Step 8: Add the public README license summary**

In the README navigation line, append ` · [License](LICENSE-SCOPE.md)` after the Contributing link.
The complete navigation must become:

```markdown
[Tutorial](docs/tutorial.md) · [User Guide](docs/user-guide.md) ·
[Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md) · [License](LICENSE-SCOPE.md)
```

After the `## Development` section, add:

```markdown
## License

BundleWalker is an open-source, multi-license distribution. Its application code, tests,
documentation, and internal agent prompts are available under the
[GNU General Public License version 3 or later](LICENSE). Commercial use is permitted under the
GPL's terms, including its source-sharing requirements when covered work is distributed.

The five packaged convention presets are dedicated under
[CC0 1.0 Universal](LICENSES/CC0-1.0.txt). Their content can be copied into a generated
`conventions.md` without imposing BundleWalker's GPL terms on the resulting workspace.
User-provided sources and generated knowledge remain subject to the rights in that content; they
do not become BundleWalker-owned merely because the program processed them.

See [License Scope](LICENSE-SCOPE.md) for the exact path mapping.

Copyright (C) 2026 Hendrik Reh
```

- [ ] **Step 9: Document inbound contribution terms**

In `CONTRIBUTING.md`, add this section immediately before `## Before opening a pull request`:

```markdown
## Licensing contributions

By intentionally submitting a contribution to BundleWalker, you agree that its inbound terms
match the license assigned to the target path in [License Scope](LICENSE-SCOPE.md):

- contributions to the five Markdown files under `src/bundlewalker/convention_presets/` are made
  under the CC0 1.0 Universal dedication, waiver, and fallback license; and
- contributions to all other project-owned paths are licensed under GPL-3.0-or-later unless that
  path is explicitly documented otherwise.

GPL contributors retain copyright in their contributions. BundleWalker does not require a
copyright assignment, contributor license agreement, or Developer Certificate of Origin.
```

- [ ] **Step 10: Record the unreleased licensing change**

In `CHANGELOG.md`, immediately after the introductory sentence, add:

```markdown
## [Unreleased]

### Added

- Licensed BundleWalker's application code, tests, documentation, and internal prompts under
  GPL-3.0-or-later.
- Dedicated the five convention preset resources under CC0-1.0 so their copied scaffolding does
  not restrict generated workspaces.

```

Do not create an Unreleased link target, version bump, release date, or tag.

- [ ] **Step 11: Run the focused policy tests to verify the implementation**

Run:

```bash
uv run pytest \
  tests/test_release_metadata.py::test_license_metadata_and_files_are_declared \
  tests/test_release_metadata.py::test_official_license_texts_are_unmodified \
  tests/test_release_metadata.py::test_cc0_scope_matches_the_packaged_convention_presets -q
```

Expected: all three tests pass with no warnings or stray output.

- [ ] **Step 12: Build and inspect the wheel and source distribution in a temporary directory**

Run:

```bash
uv run python - <<'PY'
from email.parser import Parser
from pathlib import Path
import subprocess
import tarfile
import tempfile
from zipfile import ZipFile

LICENSE_EXPRESSION = "GPL-3.0-or-later AND CC0-1.0"
LICENSE_FILES = ["LICENSE", "LICENSES/CC0-1.0.txt", "LICENSE-SCOPE.md"]

with tempfile.TemporaryDirectory(prefix="bundlewalker-license-build-") as temporary:
    output = Path(temporary)
    subprocess.run(
        ["uv", "build", "--out-dir", str(output), "--no-create-gitignore"],
        check=True,
    )
    wheel = next(output.glob("*.whl"))
    source = next(output.glob("*.tar.gz"))

    with ZipFile(wheel) as archive:
        names = set(archive.namelist())
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = Parser().parsestr(archive.read(metadata_name).decode("utf-8"))
        licenses_root = metadata_name.rsplit("/", 1)[0] + "/licenses/"
        assert metadata["License-Expression"] == LICENSE_EXPRESSION
        assert set(metadata.get_all("License-File", [])) == set(LICENSE_FILES)
        for relative in LICENSE_FILES:
            assert licenses_root + relative in names

    with tarfile.open(source, mode="r:gz") as archive:
        names = set(archive.getnames())
        for relative in LICENSE_FILES:
            assert any(name.endswith("/" + relative) for name in names), relative

print("wheel and sdist contain exact license metadata and all three legal files")
PY
```

Expected: `uv build` creates both artifact types under the temporary directory, the script prints
`wheel and sdist contain exact license metadata and all three legal files`, and the temporary
directory is removed automatically.

- [ ] **Step 13: Validate affected rendered Markdown links**

Run:

```bash
uv run python - <<'PY'
import re
from pathlib import Path
from urllib.parse import unquote

from markdown_it import MarkdownIt

ROOT = Path.cwd().resolve()
MARKDOWN = MarkdownIt("commonmark")
SOURCES = [
    ROOT / "README.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "CHANGELOG.md",
    ROOT / "LICENSE-SCOPE.md",
]


def slug(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text).lower()
    text = re.sub(r"[`*_~]", "", text)
    text = re.sub(r"[^\w\- ]", "", text)
    return re.sub(r"[ ]+", "-", text.strip())


def anchors(path: Path) -> set[str]:
    counts: dict[str, int] = {}
    result: set[str] = set()
    tokens = MARKDOWN.parse(path.read_text(encoding="utf-8"))
    for index, token in enumerate(tokens):
        if token.type != "heading_open":
            continue
        heading = tokens[index + 1]
        text = "".join(
            child.content
            for child in heading.children or []
            if child.type in {"text", "code_inline", "softbreak", "hardbreak"}
        )
        base = slug(text)
        count = counts.get(base, 0)
        counts[base] = count + 1
        result.add(base if count == 0 else f"{base}-{count}")
    return result


errors: list[str] = []
checked = 0
for source in SOURCES:
    for token in MARKDOWN.parse(source.read_text(encoding="utf-8")):
        for child in token.children or []:
            if child.type != "link_open" or not isinstance(href := child.attrGet("href"), str):
                continue
            target = href.strip().split()[0].strip("<>")
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            path_text, separator, fragment = target.partition("#")
            destination = source if not path_text else (source.parent / unquote(path_text)).resolve()
            checked += 1
            if not destination.exists() or ROOT not in (destination, *destination.parents):
                errors.append(f"{source.relative_to(ROOT)} -> {target}: missing or outside repo")
                continue
            if separator and destination.is_file() and unquote(fragment) not in anchors(destination):
                errors.append(f"{source.relative_to(ROOT)} -> {target}: missing anchor")

assert not errors, "\n".join(errors)
print(f"validated {checked} rendered local links in licensing documentation")
PY
```

Expected: prints a positive link count and exits `0` without missing local files or anchors.

- [ ] **Step 14: Review and commit the policy artifacts**

Run:

```bash
uv run pytest tests/test_release_metadata.py -q
uv run ruff format --check tests/test_release_metadata.py
uv run ruff check tests/test_release_metadata.py
uv lock --check
git diff --check
git diff --stat
git diff -- \
  LICENSE LICENSES/CC0-1.0.txt LICENSE-SCOPE.md \
  pyproject.toml README.md CONTRIBUTING.md CHANGELOG.md tests/test_release_metadata.py
git status --short
git add \
  LICENSE LICENSES/CC0-1.0.txt LICENSE-SCOPE.md \
  pyproject.toml README.md CONTRIBUTING.md CHANGELOG.md tests/test_release_metadata.py
git diff --cached --check
git commit -m "docs: add GPL and CC0 licensing policy"
```

Expected: the focused tests and checks pass; the commit contains exactly the eight listed policy,
metadata, documentation, and test paths. The unrelated backup archive remains untracked and
unstaged.

### Task 2: Add GPL Copyright and SPDX Headers to Python Files

**Files:**
- Modify: every `*.py` file recursively under `src/`
- Modify: every `*.py` file recursively under `tests/`
- Test: `tests/test_release_metadata.py`

**Interfaces:**
- Consumes: Task 1's `PROJECT_ROOT` and release-policy tests; the exact header
  `# Copyright (C) 2026 Hendrik Reh` followed by
  `# SPDX-License-Identifier: GPL-3.0-or-later`.
- Produces: a repository-wide invariant that dynamically discovered Python source and test files
  begin with the exact approved two-line header, without changing packaged Markdown resources or
  runtime behavior.

- [ ] **Step 1: Add the failing dynamic Python-header policy test**

In `tests/test_release_metadata.py`, add this constant below `CC0_PRESET_PATHS`:

```python
PYTHON_HEADER = (
    "# Copyright (C) 2026 Hendrik Reh\n"
    "# SPDX-License-Identifier: GPL-3.0-or-later\n"
)
```

Add this test after the CC0 scope test:

```python
def test_all_python_files_have_gpl_spdx_headers() -> None:
    python_files = sorted((PROJECT_ROOT / "src").rglob("*.py"))
    python_files.extend(sorted((PROJECT_ROOT / "tests").rglob("*.py")))
    missing = [
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in python_files
        if not path.read_text(encoding="utf-8").startswith(PYTHON_HEADER)
    ]

    assert python_files
    assert not missing, "missing GPL SPDX header:\n" + "\n".join(missing)
```

The test discovers the current and future Python file set dynamically. Do not add a numeric file
count assertion.

- [ ] **Step 2: Run the header test to verify the repository is red**

Run:

```bash
uv run pytest tests/test_release_metadata.py::test_all_python_files_have_gpl_spdx_headers -q
```

Expected: FAIL and list the Python files missing the header, including
`src/bundlewalker/__init__.py` and `tests/test_release_metadata.py`.

- [ ] **Step 3: Apply the exact header as one mechanical rewrite**

Run this bounded mechanical rewrite from the repository root:

```bash
uv run python - <<'PY'
from pathlib import Path

HEADER = (
    "# Copyright (C) 2026 Hendrik Reh\n"
    "# SPDX-License-Identifier: GPL-3.0-or-later\n\n"
)

paths = sorted(Path("src").rglob("*.py"))
paths.extend(sorted(Path("tests").rglob("*.py")))
assert paths
for path in paths:
    content = path.read_text(encoding="utf-8")
    assert not content.startswith("#!"), f"preserve shebang manually: {path}"
    assert not content.startswith(
        ("# Copyright (C) 2026 Hendrik Reh", "# SPDX-License-Identifier:")
    ), f"existing license header: {path}"
    path.write_text(HEADER + content, encoding="utf-8")
print(f"added GPL SPDX headers to {len(paths)} Python files")
PY
```

Expected: prints `added GPL SPDX headers to 75 Python files` for the current repository. The script
does not hard-code `75`; a different positive count means the repository changed since planning
and must be reviewed before commit.

- [ ] **Step 4: Run the focused policy test to verify all headers are green**

Run:

```bash
uv run pytest tests/test_release_metadata.py::test_all_python_files_have_gpl_spdx_headers -q
```

Expected: PASS with no missing paths.

- [ ] **Step 5: Prove packaged Markdown resources remained byte-stable**

Run:

```bash
git diff --exit-code HEAD -- \
  'src/bundlewalker/agents/prompts/*.md' \
  'src/bundlewalker/convention_presets/*.md'
```

Expected: exits `0` with no diff. Any prompt or convention resource change is out of scope and
must be reverted without touching the new Python headers.

- [ ] **Step 6: Rebuild and re-inspect final distribution artifacts**

Run:

```bash
uv run python - <<'PY'
from email.parser import Parser
from pathlib import Path
import subprocess
import tarfile
import tempfile
from zipfile import ZipFile

LICENSE_EXPRESSION = "GPL-3.0-or-later AND CC0-1.0"
LICENSE_FILES = ["LICENSE", "LICENSES/CC0-1.0.txt", "LICENSE-SCOPE.md"]

with tempfile.TemporaryDirectory(prefix="bundlewalker-license-final-") as temporary:
    output = Path(temporary)
    subprocess.run(
        ["uv", "build", "--out-dir", str(output), "--no-create-gitignore"],
        check=True,
    )
    wheel = next(output.glob("*.whl"))
    source = next(output.glob("*.tar.gz"))
    with ZipFile(wheel) as archive:
        names = set(archive.namelist())
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = Parser().parsestr(archive.read(metadata_name).decode("utf-8"))
        licenses_root = metadata_name.rsplit("/", 1)[0] + "/licenses/"
        assert metadata["License-Expression"] == LICENSE_EXPRESSION
        assert set(metadata.get_all("License-File", [])) == set(LICENSE_FILES)
        assert all(licenses_root + relative in names for relative in LICENSE_FILES)
    with tarfile.open(source, mode="r:gz") as archive:
        names = set(archive.getnames())
        assert all(
            any(name.endswith("/" + relative) for name in names)
            for relative in LICENSE_FILES
        )
print("final wheel and sdist licensing verified")
PY
```

Expected: prints `final wheel and sdist licensing verified`; no build artifacts remain in the
repository.

- [ ] **Step 7: Run the complete repository verification gate**

Run:

```bash
uv run pytest -m 'not eval' -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv lock --check
test "$(git rev-parse 'v2^{}')" = "12ef119ac3b2ba84cff7ca9aee0fbf14b239d975"
test "$(uv run python -c 'import bundlewalker; print(bundlewalker.__version__)')" = "0.2.0"
git diff --check
```

Expected: the offline suite passes; Ruff reports all files formatted and no lint findings;
Pyright reports zero errors and warnings; the lock is current; tag and version checks pass; and
the diff check is silent.

- [ ] **Step 8: Review and commit the Python annotations**

Run:

```bash
git diff --stat
git diff -- tests/test_release_metadata.py src tests
git status --short
git add src tests
git diff --cached --check
task_unexpected_staged="$(
  git diff --cached --name-only |
    rg -v '^(src|tests)/.*\.py$' || true
)"
if [ -n "$task_unexpected_staged" ]; then
  printf 'unexpected staged paths:\n%s\n' "$task_unexpected_staged" >&2
  exit 1
fi
git commit -m "chore: add GPL source headers"
```

Expected: the staged set contains only Python paths under `src/` and `tests/`; every change is the
two-line header plus Task 2's policy test; the commit succeeds. The unrelated backup archive
remains untracked and unstaged.

- [ ] **Step 9: Verify the final two-commit licensing range**

After the two planned commits exist, compute the licensing baseline as their parent and verify
that the expected commits are the only commits in the range:

```bash
task_licensing_base="$(git rev-parse HEAD~2)"
test "$(git log -2 --format='%s')" = "$(printf '%s\n%s' \
  'chore: add GPL source headers' \
  'docs: add GPL and CC0 licensing policy')"
git log --oneline "$task_licensing_base"..HEAD
git diff --check "$task_licensing_base"..HEAD
git diff --stat "$task_licensing_base"..HEAD
git status --short --branch
```

Expected: exactly the policy-artifact commit and source-header commit appear in the range; the
range is whitespace-clean; the working tree is clean apart from the known unrelated backup
archive when operating in the main checkout. No tag, remote, version, dependency, prompt, or
convention-preset change is present.
