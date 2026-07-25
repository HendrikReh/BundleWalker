# Post-Beta Dependency and Source-Distribution Maintenance

**Status:** Design approved for implementation planning

**Scope:** Focused maintenance after the `0.4.0` public-beta release

## Summary

BundleWalker `0.4.0` is published from annotated tag `v0.4.0`. Two post-release maintenance
problems now obstruct routine dependency work:

1. the current `uv.lock` is still tested against the exact dependency versions approved for the
   historical `0.4.0rc3` release; and
2. a source distribution built from a normal Git checkout omits 28 tracked files below historical
   fixture `.bundlewalker/` directories because the repository intentionally ignores that name.

This maintenance change separates immutable release evidence from current dependency policy and
makes the sdist contain exactly the tracked historical fixture representation. It changes no
runtime behavior, public interface, dependency version, package version, support claim, or release
workflow.

## Context

Dependabot PRs for `pydantic-ai` `2.17.0` and Ruff `0.16.0` complete the full supported test suite
except for `test_release_lock_uses_approved_rc3_dependency_versions`. That test compares the moving
current lock against `pydantic-ai` `2.16.0`, Typer `0.27.0`, and Ruff `0.15.22`, so every legitimate
post-`rc3` update must fail.

The `rc3` resolution remains durably recorded by:

- annotated tag `v0.4.0rc3`;
- the `v0.4.0rc3` changelog entry;
- the accepted release design and implementation plan; and
- the existing release-history assertions in `tests/test_release_metadata.py`.

During the final `0.4.0` gate, a normal checkout and a linked worktree produced different sdists.
The linked worktree included the tracked `.bundlewalker/` fixture data, while the normal checkout
respected the repository-wide `.bundlewalker/` ignore rule and omitted it. Production CI uses a
normal checkout, so the omission is present in the published `0.4.0` sdist. Runtime installation,
wheel construction, CLI, and MCP behavior are unaffected, but two historical compatibility tests
cannot run successfully from the unpacked sdist.

## Goals

1. Allow routine dependency updates without rewriting historical `rc3` evidence.
2. Preserve checks for the declared direct dependency floors and the presence of their resolved
   packages in the current lock.
3. Include every Git-tracked historical fixture file in sdists built from normal checkouts and
   linked worktrees.
4. Exclude untracked historical fixture files from the archive contract.
5. Add a behavioral archive-content regression test that fails for the published `0.4.0` packaging
   configuration.
6. Record both fixes under the changelog's existing `Unreleased` section.

## Non-Goals

- Updating `pydantic-ai`, Typer, Ruff, or any transitive dependency.
- Changing package version `0.4.0`.
- Publishing `0.4.1`.
- Modifying runtime source under `src/`.
- Changing CI or publishing workflows.
- Expanding Windows support.
- Rewriting any accepted historical plan, specification, fixture, or release record.
- Making the complete project test suite a supported end-user surface of the sdist.

## Design

### Current dependency policy

Replace `test_release_lock_uses_approved_rc3_dependency_versions` with a current-policy test. The
test will continue to require these declared floors:

- `pydantic-ai>=2.10.0`;
- `typer>=0.16.0`; and
- development dependency `ruff>=0.12.0`.

It will also require `pydantic-ai`, `typer`, and `ruff` to be present in the resolved lock. It will
not assert their exact resolved versions. `uv lock --check` remains the authority that the lock is
consistent with `pyproject.toml`.

The existing release-history test continues to require the `v0.4.0rc3` changelog entry to name the
exact approved resolution. The annotated tag remains the immutable source tree for that release.
No duplicate lock snapshot or new historical fixture is introduced.

### Deterministic historical-fixture packaging

Keep the current force-inclusion of
`tests/fixtures/historical/empty-directories.json`. Add one file-to-same-path force-inclusion
mapping for each of the 28 Git-tracked files below the historical `.bundlewalker/` roots that are
hidden by the repository-wide ignore rule:

- `tests/fixtures/historical/v1-schema1-swapping/.bundlewalker/`; and
- `tests/fixtures/historical/v3-schema2-pending/.bundlewalker/`.

Directory sources are prohibited because Hatch recursively includes their ambient contents. The
file-granular mappings retain the same paths inside the archive, while non-hidden historical
fixture files continue to enter the sdist through Hatch's normal VCS selection.

Using exact file sources prevents arbitrary untracked fixture files from entering package
contents. If a future historical fixture adds another tracked file below an ignored
`.bundlewalker/` root, the behavioral and configuration regressions will fail until that exact file
mapping is added explicitly.

### Archive-content contract

Add a test that:

1. obtains the authoritative historical fixture file set with
   `git ls-files -- tests/fixtures/historical`;
2. copies the project into a disposable non-Git tree while excluding `.git`, caches, environments,
   `dist/`, and `.superpowers/`;
3. seeds an ignored untracked sentinel below one mapped historical `.bundlewalker/` root;
4. builds an sdist from that disposable tree with `uv build --sdist --no-sources`;
5. normalizes archive members by removing the generated `bundlewalker-<version>/` root; and
6. compares the archive's complete historical fixture file set exactly with the Git-tracked set
   obtained from the real project.

Exact equality proves both directions of the contract:

- no tracked historical fixture file is omitted; and
- no untracked historical fixture file is included.

The packaging-configuration test will derive the 28 ignored tracked files from Git and assert that
the force-inclusion table equals their file-to-same-path mappings plus the existing sidecar mapping.
The existing `.superpowers/` and benchmark exclusions remain unchanged.

## Files

- Modify `tests/test_release_metadata.py`
  - replace the obsolete exact-current-lock test;
  - add the behavioral sdist historical-fixture content test.
- Modify `tests/test_project_automation.py`
  - require the exact tracked-file Hatch mappings plus the representation sidecar.
- Modify `pyproject.toml`
  - replace the two recursive directory mappings with 28 exact file mappings.
- Modify `CHANGELOG.md`
  - document the dependency-policy test correction and complete sdist fixture packaging under
    `Unreleased`.

No other tracked file is in scope unless verification exposes a direct requirement.

## Test-Driven Sequence

1. Update the archive-content regression to build from a disposable project copy containing an
   ignored untracked sentinel.
2. Confirm it fails because the sentinel is the archive's only extra historical fixture file.
3. Update the Hatch mappings and the configuration assertion.
4. Confirm the archive-content and configuration tests pass.
5. Replace the obsolete current-lock exact-version assertions while retaining current floor,
   lock-presence, and historical changelog coverage.
6. Run the focused release and automation test modules.
7. Run the complete non-evaluation suite, Ruff formatting and linting, Pyright, locked dependency
   verification, build, Twine validation, and wheel/sdist smoke installations.

## Risks and Controls

| Risk | Control |
|---|---|
| Historical `rc3` evidence is weakened | Exact versions remain asserted in release history and recoverable from the immutable annotated tag |
| Force-inclusion packages untracked fixture data | Use exact file sources and exercise an ignored untracked sentinel in the archive regression |
| A future ignored fixture file is silently omitted | The behavioral and configuration tests derive their expected sets from all tracked historical fixture files |
| Maintenance accidentally changes product behavior | No `src/`, dependency, version, workflow, or support-policy change is allowed |
| The sdist grows unexpectedly | The expected addition is limited to the 28 already tracked ignored fixture files |

## Acceptance Criteria

1. The current lock may resolve a newer compatible `pydantic-ai` or Ruff without failing a
   historical `rc3` exact-version assertion.
2. Declared direct dependency floors and the presence of their resolved lock packages remain
   tested.
3. A newly built sdist contains exactly every Git-tracked file under
   `tests/fixtures/historical/`, including all 28 currently ignored `.bundlewalker/` files.
4. No untracked historical fixture file is included.
5. The normal-checkout and linked-worktree build paths have the same historical fixture contents.
6. Existing `.superpowers/` and benchmark exclusions remain effective.
7. The complete non-evaluation test suite, formatting, linting, typing, dependency audit, package
   build, Twine checks, and clean wheel/sdist installation smokes pass.
8. `pyproject.toml` still declares version `0.4.0`, and `uv.lock` has no dependency or editable
   package change.
