# BundleWalker v2 Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the current BundleWalker capability set as repository release `v2` with Python
package version `0.2.0`, accurate current documentation, and a remotely verified annotated tag.

**Architecture:** Treat metadata, active documentation, and the synchronized user-guide mirror as
one release state and commit them together only after focused and full verification. Preserve
historical v1 records, then publish in two guarded phases: push and verify `master`, followed by
creating, pushing, and verifying the annotated `v2` tag.

**Tech Stack:** Python 3.13, uv, Hatchling metadata, pytest, Ruff, Pyright, Markdown, Git, MCP
Python SDK

## Global Constraints

- The repository release tag is exactly `v2`.
- `pyproject.toml`, `bundlewalker.__version__`, installed distribution metadata, and `uv.lock`
  must consistently report `0.2.0`.
- `v2` is an annotated tag with the exact message `BundleWalker v2`.
- The release documentation commit is part of the tagged state.
- The verified release commit and tag are pushed to `origin`.
- V2 retains one regular UTF-8 Markdown or text source per ingestion, a 100,000-character default
  limit, and the Source, Topic, Entity, and Synthesis producer types.
- V2 adds no local web UI, hosted service, remote MCP transport, new source format, dependency
  range, or application behavior.
- Historical v1 specifications and plans retain their original wording, except for the required
  exact user-guide mirror in `docs/superpowers/plans/2026-07-16-end-user-guide.md`.
- The pre-existing `2026-07-17T19-22-38.740+02-00-openclaw-backup.tar.gz` remains untracked,
  unmodified, and excluded from every commit and tag.
- Stop before tag creation if any verification or branch-publication step fails.

---

## File map

- Create `CHANGELOG.md`: concise public release ledger for v2 and v1.
- Create `tests/test_release_metadata.py`: executable consistency contract for the v2 package
  version across source, project metadata, installed metadata, and lockfile.
- Modify `pyproject.toml`: set the Python distribution version to `0.2.0`.
- Modify `src/bundlewalker/__init__.py`: set the runtime package version to `0.2.0`.
- Modify `uv.lock`: refresh the editable BundleWalker package record to `0.2.0`; dependency ranges
  and resolved dependency versions remain otherwise unchanged.
- Modify `README.md`: identify v2, link the changelog, and describe the actual v2 scope and MCP
  boundary.
- Modify `CONTRIBUTING.md`: identify the current project boundary as v2 and link the historical v1
  design plus the MCP architecture record.
- Modify `docs/user-guide.md`: update current-release language and the producer-limits anchor to
  v2 without changing the limits themselves.
- Modify `docs/tutorial.md`: link the current rendered command-reference link to the canonical
  user-guide heading.
- Modify `docs/superpowers/plans/2026-07-16-end-user-guide.md`: mechanically synchronize only the
  embedded canonical user-guide block.
- Modify `docs/superpowers/plans/2026-07-18-bundlewalker-v2-release.md`: validate rendered links
  only in current user-facing documentation and include the scoped tutorial correction in the
  verified release state.

### Task 1: Build and Commit the Verified v2 Release State

**Files:**
- Create: `CHANGELOG.md`
- Create: `tests/test_release_metadata.py`
- Modify: `pyproject.toml:3`
- Modify: `src/bundlewalker/__init__.py:1`
- Modify: `uv.lock:111-112`
- Modify: `README.md:1-9,123-174`
- Modify: `CONTRIBUTING.md:8-20,151-161`
- Modify: `docs/user-guide.md:168-181,588-610,651-656`
- Modify: `docs/tutorial.md:243`
- Modify: `docs/superpowers/plans/2026-07-16-end-user-guide.md:66-754`
- Modify: `docs/superpowers/plans/2026-07-18-bundlewalker-v2-release.md:42-55,374-455,489-503`

**Interfaces:**
- Consumes: approved design at
  `docs/superpowers/specs/2026-07-18-bundlewalker-v2-release-design.md`; current `v1` tag; console
  scripts `bundlewalker` and `bundlewalker-mcp`; the embedded-guide markers documented in
  `CONTRIBUTING.md`.
- Produces: one committed, fully verified release state whose `HEAD` is safe to publish and tag as
  `v2`; an executable `test_v2_release_versions_are_consistent()` contract; current release notes
  in `CHANGELOG.md`.

- [ ] **Step 1: Confirm the release name is unused and the worktree contains only the known local archive**

Run:

```bash
test -z "$(git tag --list v2)"
test -z "$(git ls-remote --tags origin 'refs/tags/v2' 'refs/tags/v2^{}')"
git status --branch --short
```

Expected: both `test` commands exit `0`; status shows `master` ahead only by the approved design
and implementation-plan commits and lists only
`?? 2026-07-17T19-22-38.740+02-00-openclaw-backup.tar.gz` as untracked. If either tag lookup is
non-empty, stop without changing or replacing that tag.

- [ ] **Step 2: Add the failing release-version consistency test**

Create `tests/test_release_metadata.py` with exactly:

```python
import tomllib
from importlib.metadata import version as distribution_version
from pathlib import Path

import bundlewalker

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_v2_release_versions_are_consistent() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((PROJECT_ROOT / "uv.lock").read_text(encoding="utf-8"))
    editable_package = next(
        package
        for package in lock["package"]
        if package["name"] == "bundlewalker" and package.get("source") == {"editable": "."}
    )

    assert project["project"]["version"] == "0.2.0"
    assert bundlewalker.__version__ == "0.2.0"
    assert distribution_version("bundlewalker") == "0.2.0"
    assert editable_package["version"] == "0.2.0"
```

- [ ] **Step 3: Run the release-version test and observe the expected failure**

Run:

```bash
uv run pytest tests/test_release_metadata.py::test_v2_release_versions_are_consistent -v
```

Expected: FAIL because the current project, runtime package, installed distribution, and lockfile
still report `0.1.0`.

- [ ] **Step 4: Update the two canonical package-version declarations**

Change `pyproject.toml` to begin with:

```toml
[project]
name = "bundlewalker"
version = "0.2.0"
```

Change `src/bundlewalker/__init__.py` to exactly:

```python
__version__ = "0.2.0"
```

- [ ] **Step 5: Refresh and inspect the lockfile**

Run:

```bash
uv lock
git diff -- pyproject.toml src/bundlewalker/__init__.py uv.lock
```

Expected: `uv lock` succeeds; the BundleWalker entry in `uv.lock` changes from `0.1.0` to `0.2.0`;
no dependency range or resolved third-party package version changes.

- [ ] **Step 6: Run the release-version test and observe it pass**

Run:

```bash
uv run pytest tests/test_release_metadata.py::test_v2_release_versions_are_consistent -v
```

Expected: PASS with all four version surfaces reporting `0.2.0`.

- [ ] **Step 7: Create the public release ledger**

Create `CHANGELOG.md` with exactly:

```markdown
# Changelog

All notable BundleWalker releases are recorded here.

## [v2] - 2026-07-18

### Added

- Added a local MCP `stdio` server that exposes one workspace through bounded resources and ten
  strict tools.
- Added separate MCP prepare, inspect, apply, and discard operations for review-first writes.
- Added coarse MCP progress reporting and cancellation support for model-backed operations.

### Changed

- Routed CLI and MCP delivery through one workspace-bound application facade with serializable
  contracts and bounded public errors.
- Made prepared reviews durable across CLI and MCP process restarts while preserving one pending
  review per workspace.
- Expanded the user and contributor documentation for MCP setup, review recovery, and adapter
  boundaries.

### Security

- Hardened transaction compatibility checks, authenticated recovery, raw-source link accounting,
  and fail-closed handling of ambiguous post-commit states.
- Kept MCP workspace selection at process startup and prohibited MCP tool inputs from accepting
  local workspace or source paths.

## [v1] - 2026-07-16

- Initial local, review-first CLI release.
- Added immutable raw-source ingestion, deterministic proposal validation, complete review diffs,
  cited questions, saved and refreshed Syntheses, offline lint, and recoverable transactions.
- Added configurable conventions and presets for personal, agent, software, and research knowledge
  workspaces.

[v2]: https://github.com/HendrikReh/BundleWalker/compare/v1...v2
[v1]: https://github.com/HendrikReh/BundleWalker/tree/v1
```

- [ ] **Step 8: Update the README release identity, navigation, scope, and MCP wording**

After the opening paragraph in `README.md`, add:

```markdown
Current release: **v2** (Python package `0.2.0`). See the [changelog](CHANGELOG.md) for the release
history.
```

Replace the navigation line with:

```markdown
[Tutorial](docs/tutorial.md) · [User Guide](docs/user-guide.md) ·
[Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md)
```

In `## Current scope`, replace only current-milestone wording so the section reads:

```markdown
## Current scope

Version 2 ingests one regular UTF-8 `.md` or `.txt` file per command, with a default limit of
100,000 Unicode characters. It produces four knowledge types: Source, Topic, Entity, and
Synthesis. Model proposals, answers, paths, metadata, and citations are bounded; see the
[detailed producer limits](docs/user-guide.md#v2-producer-limits-and-permissive-reading).

V2 does not ingest URLs, PDFs, images, audio, video, or OCR; batch or watch directories; chunk
book-sized sources; use embeddings, vector databases, or background indexes; provide a web UI,
plugin, hosted or remote service; let agents delete, rename, edit conventions, or resolve
contradictions automatically; or perform multi-user synchronization and Git operations. The local
web UI remains unimplemented and is a separate next plan. The
[user guide](docs/user-guide.md#ingest-and-review-a-source) covers source validation and the
operating boundary in detail.
```

Change the first sentence under `## Local MCP server` to:

```markdown
BundleWalker v2 also exposes one workspace through a local MCP `stdio` server. Configure your MCP
host to launch this command, replacing the two placeholders with absolute local paths:
```

Add this item to the `## Documentation` list after the user-guide item:

```markdown
- The [Changelog](CHANGELOG.md) records the public capability changes in each tagged release.
```

- [ ] **Step 9: Update current contributor guidance without rewriting historical v1 records**

Replace the opening paragraph under `## Project boundaries` in `CONTRIBUTING.md` with:

```markdown
BundleWalker v2 ingests one UTF-8 Markdown or text source at a time and produces only four
concept types: Source, Topic, Entity, and Synthesis. Agents never write files directly. The
project does not perform automatic Git operations and does not run a background, hosted, or remote
service. Its MCP adapter is a foreground local `stdio` process bound to one workspace at startup;
the local web UI remains a separate next plan.
```

Replace the following design-guidance paragraph with:

```markdown
Before proposing an expansion of that scope, read the original
[v1 design](docs/superpowers/specs/2026-07-15-bundlewalker-v1-design.md), the accepted
[MCP and local web architecture](docs/superpowers/specs/2026-07-17-mcp-web-interface-architecture-design.md),
and the relevant records in [`docs/superpowers/specs/`](docs/superpowers/specs/) and
[`docs/superpowers/plans/`](docs/superpowers/plans/). A scope change should begin with an explicit
design decision, not an incidental implementation change.
```

Change the first pull-request checklist item to:

```markdown
- [ ] The change is focused, remains within v2 scope, or links to an accepted scope decision.
```

- [ ] **Step 10: Update the canonical user guide's current-release wording**

Make these exact replacements in `docs/user-guide.md`:

```text
Version 1 accepts one regular UTF-8 `.md` or `.txt` file per invocation.
-> Version 2 accepts one regular UTF-8 `.md` or `.txt` file per invocation.

### V1 producer limits and permissive reading
-> ### V2 producer limits and permissive reading

BundleWalker's v1 producer is deliberately stricter than its OKF reader.
-> BundleWalker's v2 producer is deliberately stricter than its OKF reader.

without letting v1 model proposals invent new producer types.
-> without letting v2 model proposals invent new producer types.

watched-directory ingestion are outside v1.
-> watched-directory ingestion are outside v2.
```

Do not change any command, limit, concept type, MCP tool, review behavior, or troubleshooting
instruction.

- [ ] **Step 11: Synchronize the historical plan's exact embedded user-guide mirror**

Run this mechanical synchronization script:

```bash
uv run python - <<'PY'
from pathlib import Path

guide_path = Path("docs/user-guide.md")
plan_path = Path("docs/superpowers/plans/2026-07-16-end-user-guide.md")
start_marker = "Create `docs/user-guide.md` with exactly:\n\n````markdown\n"
end_marker = (
    "\n````\n\n- [ ] **Step 3: Link the guide from the README**"
)

guide = guide_path.read_text(encoding="utf-8")
plan = plan_path.read_text(encoding="utf-8")
prefix, separator, remainder = plan.partition(start_marker)
assert separator == start_marker
embedded, separator, suffix = remainder.partition(end_marker)
assert separator == end_marker
assert embedded != guide
plan_path.write_text(prefix + start_marker + guide + end_marker + suffix, encoding="utf-8")
PY
```

Expected: only the embedded guide block changes; the historical plan around that block remains
byte-for-byte unchanged.

- [ ] **Step 12: Verify exact embedded-guide equality**

Run:

```bash
uv run python - <<'PY'
from pathlib import Path

guide = Path("docs/user-guide.md").read_text(encoding="utf-8")
plan = Path("docs/superpowers/plans/2026-07-16-end-user-guide.md").read_text(
    encoding="utf-8"
)
start_marker = "Create `docs/user-guide.md` with exactly:\n\n````markdown\n"
end_marker = "\n````\n\n- [ ] **Step 3: Link the guide from the README**"
remainder = plan.split(start_marker, 1)[1]
embedded = remainder.split(end_marker, 1)[0]
assert embedded == guide
print("embedded user guide matches")
PY
```

Expected: prints `embedded user guide matches`.

- [ ] **Step 13: Confirm active v2 wording and preserved historical scope**

Run:

```bash
rg -n 'v2|Version 2|0\.2\.0|CHANGELOG' README.md CONTRIBUTING.md docs/user-guide.md CHANGELOG.md
if rg -n 'Version 1|\bV1\b|#v1-producer-limits' README.md CONTRIBUTING.md docs/user-guide.md; then
    printf 'unexpected current-document v1 wording\n' >&2
    exit 1
fi
git diff -- docs/superpowers/specs docs/superpowers/plans \
  ':!docs/superpowers/plans/2026-07-16-end-user-guide.md' \
  ':!docs/superpowers/plans/2026-07-18-bundlewalker-v2-release.md'
```

Expected: the first search shows the intended current-release statements; the second returns no
matches; the final diff is empty, proving other historical specifications and plans were not
rewritten. The two excluded plans are the required embedded-guide mirror and this current
release-plan correction.

- [ ] **Step 14: Validate rendered current-document Markdown links and heading anchors**

Run:

```bash
uv run python - <<'PY'
import re
from pathlib import Path
from urllib.parse import unquote

from markdown_it import MarkdownIt

ROOT = Path.cwd().resolve()
HTML_ANCHOR = re.compile(
    r"\b(?:id|name)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s\"'=<>`]+))",
    re.IGNORECASE,
)

MARKDOWN = MarkdownIt("commonmark")
SOURCES = [
    ROOT / "README.md",
    ROOT / "CHANGELOG.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "docs/tutorial.md",
    ROOT / "docs/user-guide.md",
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
        if token.type == "heading_open":
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
        for child in token.children or []:
            if child.type == "html_inline":
                for match in HTML_ANCHOR.finditer(child.content):
                    result.add(next(value for value in match.groups() if value is not None))
        if token.type == "html_block":
            for match in HTML_ANCHOR.finditer(token.content):
                result.add(next(value for value in match.groups() if value is not None))
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
                errors.append(f"{source.relative_to(ROOT)} -> {target}: missing or outside repository")
                continue
            if separator and destination.is_file() and unquote(fragment) not in anchors(destination):
                errors.append(f"{source.relative_to(ROOT)} -> {target}: missing anchor")

assert not errors, "\n".join(errors)
print(f"validated {checked} rendered local Markdown links")
PY
```

Expected: prints a positive validated-link count and exits `0` with no missing file or anchor in
the current user-facing documentation set. Markdown-it token parsing excludes fenced and other
non-rendered example links from this rendered-link check.

- [ ] **Step 15: Validate all documented executable surfaces against live help**

Run:

```bash
uv run bundlewalker --help
uv run bundlewalker init --help
uv run bundlewalker ingest --help
uv run bundlewalker ask --help
uv run bundlewalker lint --help
uv run bundlewalker review --help
uv run bundlewalker-mcp --help
```

Expected: every command exits `0`; the CLI exposes `init`, `ingest`, `ask`, `lint`, and `review`;
the MCP help exposes the required `--workspace` option; documented syntax remains accurate.

- [ ] **Step 16: Run the complete offline release gate**

Run each command and stop on the first failure:

```bash
uv run pytest -m 'not eval' -q
uv run pytest tests/interfaces -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv lock --check
git diff --check
```

Expected: all offline tests pass with five live-model evaluations deselected; all interface tests
pass; Ruff reports all files formatted and no lint findings; Pyright reports zero errors, warnings,
or information messages; the lockfile is current; `git diff --check` is silent.

- [ ] **Step 17: Review the exact release diff and stage only release files**

Run:

```bash
git diff --stat
git diff -- CHANGELOG.md pyproject.toml src/bundlewalker/__init__.py uv.lock README.md CONTRIBUTING.md docs/user-guide.md docs/tutorial.md docs/superpowers/plans/2026-07-16-end-user-guide.md docs/superpowers/plans/2026-07-18-bundlewalker-v2-release.md tests/test_release_metadata.py
git status --short
git add CHANGELOG.md pyproject.toml src/bundlewalker/__init__.py uv.lock README.md CONTRIBUTING.md docs/user-guide.md docs/tutorial.md docs/superpowers/plans/2026-07-16-end-user-guide.md docs/superpowers/plans/2026-07-18-bundlewalker-v2-release.md tests/test_release_metadata.py
git diff --cached --check
git status --short
```

Expected: the diff contains only the specified release changes; the final status shows those exact
paths staged and the backup archive still untracked and unstaged.

- [ ] **Step 18: Commit the verified release state**

Run:

```bash
git commit -m "chore: release BundleWalker v2"
git log -2 --oneline
git status --branch --short
```

Expected: the release commit succeeds above the approved design and implementation-plan commits;
`master` is ahead of `origin/master`; only the backup archive remains untracked.

### Task 2: Publish and Verify the v2 Branch and Tag

**Files:**
- Modify: none

**Interfaces:**
- Consumes: verified release commit from Task 1; remote `origin`; exact annotated-tag identity
  `v2` / `BundleWalker v2`.
- Produces: `origin/master` at the verified release commit and remote annotated tag `v2` peeled to
  that same commit.

- [ ] **Step 1: Revalidate publication preconditions**

Run:

```bash
test "$(git branch --show-current)" = "master"
test -z "$(git tag --list v2)"
test -z "$(git ls-remote --tags origin 'refs/tags/v2' 'refs/tags/v2^{}')"
test -z "$(git status --porcelain=v1 --untracked-files=no)"
release_commit="$(git rev-parse HEAD)"
printf 'release_commit=%s\n' "$release_commit"
git status --branch --short
```

Expected: all tests exit `0`; `release_commit` is the Task 1 commit; only the known backup archive
is untracked. If a local or remote `v2` tag appears, stop rather than replacing it.

- [ ] **Step 2: Push the release commit to `origin/master`**

Run:

```bash
git push origin master
```

Expected: push succeeds and reports `master -> master`. If it fails, stop without creating `v2`.

- [ ] **Step 3: Fetch and verify the published branch**

Run:

```bash
git fetch origin master --quiet
test "$(git rev-parse master)" = "$(git rev-parse origin/master)"
printf 'local=%s\nremote=%s\n' "$(git rev-parse master)" "$(git rev-parse origin/master)"
```

Expected: local and remote commit IDs are identical. If they differ, stop without creating `v2`.

- [ ] **Step 4: Create and inspect the local annotated tag**

Run:

```bash
git tag -a v2 -m "BundleWalker v2" "$(git rev-parse master)"
test "$(git cat-file -t v2)" = "tag"
test "$(git rev-parse 'v2^{}')" = "$(git rev-parse master)"
git tag -n99 --list v2
```

Expected: `v2` is an annotated tag, peels to `master`, and displays `BundleWalker v2`. If local
inspection fails, stop and report the exact mismatch; do not push the tag.

- [ ] **Step 5: Push only the new release tag**

Run:

```bash
git push origin refs/tags/v2
```

Expected: push succeeds and reports `[new tag] v2 -> v2`. If it fails, retain the valid local tag
and report that remote tag publication needs retrying; do not replace or force-push any tag.

- [ ] **Step 6: Fetch and verify the remote annotated tag**

Run:

```bash
git fetch --force --quiet origin tag v2
local_commit="$(git rev-parse master)"
tag_commit="$(git rev-parse 'v2^{}')"
remote_commit="$(git ls-remote --tags origin 'refs/tags/v2^{}' | cut -f1)"
printf 'local=%s\ntag=%s\nremote_tag=%s\n' "$local_commit" "$tag_commit" "$remote_commit"
test "$local_commit" = "$tag_commit"
test "$local_commit" = "$remote_commit"
```

Expected: all three commit IDs are identical.

- [ ] **Step 7: Record the final release state**

Run:

```bash
git status --branch --short
git show --no-patch --format=fuller v2
git log -1 --oneline --decorate
```

Expected: `master` and `origin/master` are synchronized; `HEAD` is decorated by `tag: v2`; the tag
annotation is `BundleWalker v2`; only the pre-existing backup archive remains untracked.
