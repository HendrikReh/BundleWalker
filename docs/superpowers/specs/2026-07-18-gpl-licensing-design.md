# GPL and Generated-Output Licensing Design

**Status:** Approved design

**Date:** 2026-07-18

**Copyright holder:** Hendrik Reh

## Purpose

BundleWalker currently has no repository license file, Python package license metadata, or
contribution-licensing statement. The project will adopt a genuine copyleft open-source license
instead of the previously considered noncommercial restriction. Commercial use remains allowed;
copyleft obligations apply when covered work is conveyed.

BundleWalker also copies packaged convention presets into user-created workspaces. Those preset
bytes need a separate permissive treatment so that the project license does not impose GPL terms
on a user's generated `conventions.md` or knowledge base.

This document defines the technical licensing boundary and repository changes. It is not a legal
opinion; the copyright holder should obtain qualified legal advice if a particular use or
enforcement decision depends on jurisdiction-specific interpretation.

## Licensing decision

BundleWalker's application code, tests, documentation, and internal agent prompts will be
available under the **GNU General Public License version 3 or any later version**. The SPDX
identifier is:

```text
GPL-3.0-or-later
```

The five packaged convention preset Markdown files will be dedicated under **Creative Commons
Zero v1.0 Universal**. The SPDX identifier is:

```text
CC0-1.0
```

This is a multi-license distribution with path-specific scope, not a choice between two licenses
for the same files. The package-level SPDX expression is therefore:

```text
GPL-3.0-or-later AND CC0-1.0
```

The root GPL grant uses copyright notice:

```text
Copyright (C) 2026 Hendrik Reh
```

## License scope

Unless a path is identified as CC0 below or contains a separate third-party notice, the repository
content is GPL-3.0-or-later. That default covers:

- Python application code under `src/bundlewalker/`;
- Python tests under `tests/`;
- repository documentation, including README, contributor documentation, tutorials, user guides,
  specifications, and implementation plans;
- internal agent prompt resources under `src/bundlewalker/agents/prompts/`; and
- repository configuration and build metadata to the extent they are copyrightable.

Exactly these generated-workspace inputs are CC0-1.0:

```text
src/bundlewalker/convention_presets/agent-context.md
src/bundlewalker/convention_presets/default.md
src/bundlewalker/convention_presets/personal-workbook.md
src/bundlewalker/convention_presets/research-agent.md
src/bundlewalker/convention_presets/software-agent.md
```

The CC0 assignment applies both to those source resource files and to the preset content copied
from them into a generated workspace. No inline marker will be added to the Markdown resources,
so their runtime instruction text and the generated `conventions.md` bytes remain unchanged.

Third-party dependencies retain their own copyrights and licenses. BundleWalker does not vendor
them into this repository, and this design does not relicense them.

## User-created content and generated output

The repository license does not claim copyright in a user's source material, knowledge content,
or model-generated output merely because BundleWalker processed it. GNU guidance says program
output is generally not covered unless its content constitutes covered work copied from the
program.

Convention presets are the material BundleWalker deliberately copies substantially into generated
output. Assigning them CC0 removes that licensing friction. Users may use, modify, publish, or
license their generated `conventions.md` and the rest of their workspace under terms they choose,
subject to rights in their inputs and any applicable third-party material.

## Repository artifacts

| Artifact | Change | Purpose |
| --- | --- | --- |
| `LICENSE` | Create with the complete, unmodified GNU GPL version 3 text. | Root license recognized by hosts and source recipients. |
| `LICENSES/CC0-1.0.txt` | Create with the complete, unmodified CC0 1.0 Universal legal code. | Carries the separate convention-preset grant. |
| `LICENSE-SCOPE.md` | Create with the path-specific GPL/CC0 mapping and generated-output explanation. | Makes the multi-license boundary readable without changing runtime resources. |
| `README.md` | Add License to navigation and a concise license/output section. | Gives users an immediate, accurate summary and links to the controlling texts. |
| `CONTRIBUTING.md` | Add contribution-licensing terms. | Makes inbound licensing match the target file's outbound license. |
| `CHANGELOG.md` | Add an `Unreleased` licensing entry. | Records the policy change without creating a release. |
| `pyproject.toml` | Add the SPDX expression and three license files. | Publishes PEP 639 package metadata and includes legal files in distributions. |
| `src/**/*.py`, `tests/**/*.py` | Add copyright and SPDX headers to every tracked Python file. | Preserves provenance when individual source files are copied. |
| `tests/test_release_metadata.py` | Extend release-policy coverage. | Prevents missing headers or stale license metadata. |

The repository currently contains 75 tracked Python files under `src/` and `tests/`. Verification
must discover those files dynamically rather than hard-code that count, so later Python files are
covered automatically.

## Python source annotations

Every tracked `.py` file under `src/` and `tests/` will begin with exactly:

```python
# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later
```

The comments precede module docstrings, imports, and `from __future__` statements. They do not alter
Python semantics. Empty package initializers receive the same two lines.

Markdown prompt and convention resources do not receive inline comments. The GPL prompt scope and
CC0 convention scope are declared centrally so model instruction text and generated workspace
content remain byte-stable.

## Python package metadata

The `[project]` table in `pyproject.toml` will add:

```toml
license = "GPL-3.0-or-later AND CC0-1.0"
license-files = ["LICENSE", "LICENSES/CC0-1.0.txt", "LICENSE-SCOPE.md"]
```

This uses the current PEP 639 string form. No legacy `License ::` classifier will be added because
license classifiers are deprecated when an SPDX `License-Expression` is present.

The source distribution and wheel must report:

```text
License-Expression: GPL-3.0-or-later AND CC0-1.0
License-File: LICENSE
License-File: LICENSES/CC0-1.0.txt
License-File: LICENSE-SCOPE.md
```

All three named files must be physically present in both built artifacts. `uv.lock` changes only if
`uv` requires a deterministic metadata refresh; dependency versions must not change for this work.

## README and contribution language

The README license section will say, in plain language:

- BundleWalker's code, tests, documentation, and internal prompts are GPL-3.0-or-later;
- convention presets are CC0-1.0 so copied scaffolding does not restrict generated workspaces;
- user-provided and generated knowledge remains subject to the rights in that content, not a new
  ownership claim by BundleWalker; and
- commercial use is allowed under the applicable GPL or CC0 terms.

`CONTRIBUTING.md` will state that inbound terms follow the license assigned to the target path:

- contributors to the five convention preset Markdown resources agree to the CC0 dedication,
  waiver, and fallback license; and
- contributors retain copyright in other contributions and license them under GPL-3.0-or-later
  unless the target path is explicitly documented otherwise.

This change does not add a contributor license agreement, copyright assignment, or Developer
Certificate of Origin process.

## Dependency compatibility

The implementation will record a direct-dependency license audit before committing. The current
direct dependencies are published under permissive licenses that can be used by a GPLv3-covered
application. The audit is a compatibility check, not an attempt to absorb dependency code into
BundleWalker's license.

If the audit discovers a conflicting or unclear direct dependency license, implementation stops
for a new design decision rather than silently publishing ambiguous metadata.

## Release boundary

The licensing commit applies to the repository state containing it and later distributions that
include the new legal files and metadata. It will not:

- amend, move, replace, or recreate the existing `v2` tag;
- publish a package or GitHub release;
- change version `0.2.0`; or
- claim that an old archive lacking these files contains the new notice.

`CHANGELOG.md` records the licensing work under `Unreleased`. A later release workflow can choose
the next version and tag normally.

## Verification design

### Repository policy tests

Extend `tests/test_release_metadata.py` to verify:

1. `pyproject.toml` declares the exact combined SPDX expression;
2. `license-files` lists the exact three repository artifacts;
3. all three legal files exist;
4. every `.py` file recursively discovered under `src/` and `tests/` starts with the exact two-line
   copyright/SPDX header; and
5. the five convention preset filenames match the path-specific CC0 scope declared by the design.

The test must not invoke Git, depend on a hard-coded count of Python files, or require network
access.

### Distribution verification

Build a source distribution and wheel into a temporary directory. Inspect them without installing
or publishing them, and verify:

- the wheel `METADATA` contains the exact `License-Expression` and three `License-File` entries;
- the wheel contains all three legal files in its `.dist-info/licenses/` area; and
- the source distribution contains all three legal files at its project root or declared relative
  path.

Temporary build artifacts must not be written to the repository's normal `dist/` directory or
left in the working tree.

### Existing quality gates

Run:

- the full offline pytest suite with live evaluations deselected;
- Ruff formatting and lint checks;
- Pyright strict type checking;
- lockfile integrity validation;
- rendered local Markdown link and heading-anchor validation for affected documentation;
- `git diff --check`; and
- a status and staged-file review confirming the unrelated backup archive remains unmodified,
  untracked, and unstaged. Its contents must not be read during implementation.

## Non-goals

This licensing change does not:

- prohibit commercial use;
- adopt GPL-2.0-only, AGPL, a noncommercial license, or a custom output exception;
- change BundleWalker runtime behavior or CLI/MCP interfaces;
- add license banners to generated workspaces;
- modify prompt or convention preset bytes;
- add a CLA, DCO, copyright assignment, or enforcement policy;
- relicense third-party dependencies; or
- create or publish a new release.

## Acceptance criteria

The design is complete when implementation proves all of the following:

1. repository and package consumers can identify the distribution as
   `GPL-3.0-or-later AND CC0-1.0`;
2. every tracked Python source and test file carries the exact GPL copyright/SPDX header;
3. the convention preset resources are clearly and exclusively mapped to CC0 without byte
   changes;
4. generated workspace content is not subjected to GPL merely because it includes a BundleWalker
   convention preset;
5. contribution terms follow the license of the target path;
6. wheel and source distributions contain complete license and scope files with correct metadata;
7. no application behavior, dependency version, release tag, or package version changes; and
8. the complete offline quality gate remains clean.

## Authoritative references

- [GNU General Public License version 3](https://www.gnu.org/licenses/gpl-3.0.txt)
- [How to use GNU licenses for your own software](https://www.gnu.org/licenses/gpl-howto.en.html)
- [GNU GPL FAQ: generated output](https://www.gnu.org/licenses/gpl-faq.en.html#WhatCaseIsOutputGPL)
- [Linux kernel licensing rules and SPDX practice](https://www.kernel.org/doc/html/latest/process/license-rules.html)
- [Creative Commons CC0 1.0 Universal legal code](https://creativecommons.org/publicdomain/zero/1.0/legalcode.txt)
- [Python Packaging User Guide: license metadata](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#license-and-license-files)
