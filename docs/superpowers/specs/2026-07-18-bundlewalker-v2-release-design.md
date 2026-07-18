# BundleWalker v2 Release Design

**Date:** 2026-07-18
**Status:** Approved for implementation

## Context

The lightweight `v1` tag identifies the initial review-first BundleWalker release and carries
Python package version `0.1.0`. Since that tag, BundleWalker has gained a workspace-bound local
MCP `stdio` server, a shared application facade for CLI and MCP delivery, durable reviews that
survive process boundaries, and stronger authenticated transaction recovery. The current
repository has already passed its offline release gate at commit `21b58aa`.

The v2 release documents and publishes that current capability set. It does not add the planned
local web UI or expand the existing source-ingestion and producer-type boundaries.

## Release identity

- The repository release tag is `v2`.
- The Python distribution and `bundlewalker.__version__` are both `0.2.0`.
- `v2` is an annotated tag with the message `BundleWalker v2`.
- The release documentation commit is part of the tagged state.
- The verified release commit and tag are pushed to `origin`.

This continues the repository's milestone convention (`v1`, `v2`) while using pre-1.0 semantic
package versions (`0.1.0`, `0.2.0`).

## User-facing release definition

BundleWalker v2 is a local, review-first knowledge tool with two supported delivery adapters:

1. the existing CLI; and
2. a local MCP `stdio` server bound to one workspace at process startup.

Both adapters use the same workspace application facade and durable review model. MCP write tools
prepare a complete review separately from apply or discard, and a prepared review survives server
restart. MCP inputs cannot select arbitrary workspaces or local source paths.

The following boundaries remain unchanged in v2:

- one regular UTF-8 Markdown or text source per ingestion;
- a default maximum of 100,000 Unicode characters per source;
- four producer concept types: Source, Topic, Entity, and Synthesis;
- no URL, PDF, image, audio, video, OCR, batch, or watched-directory ingestion;
- no embeddings, vector database, hosted service, remote MCP transport, or automatic Git
  operations; and
- no local web UI in this release.

## Documentation changes

### Release history

Create `CHANGELOG.md` as the concise release ledger. Its v2 entry summarizes the MCP adapter,
shared facade, durable review lifecycle, transaction hardening, and documentation updates. Its v1
entry identifies the initial CLI release without reconstructing every historical commit.

### Current documentation

Update the following active documents:

- `README.md`: identify the current release and package version, add the changelog to navigation,
  describe the v2 capability boundary, retain the MCP launch example, and keep the local web UI
  explicitly unavailable.
- `docs/user-guide.md`: update current-release language and the producer-limits heading/anchor from
  v1 to v2 while preserving the unchanged behavioral limits.
- `CONTRIBUTING.md`: update current project-boundary and contribution-checklist language to v2,
  and point contributors to both the original v1 design and the later MCP architecture record.
- `docs/superpowers/plans/2026-07-16-end-user-guide.md`: replace only the embedded canonical user
  guide block required by the repository's byte-equality synchronization contract.

Update any other current Markdown file only when a link or current-version statement becomes
incorrect as a direct result of these changes.

### Historical documentation

Do not globally replace v1 references in historical specifications or implementation plans. Those
references describe the scope and decisions of the v1 milestone, including limitations that were
true at the time. The synchronized user-guide block is the sole intentional exception because the
repository explicitly treats that block as an exact mirror of the current guide.

## Package metadata

Change both canonical version declarations:

- `pyproject.toml`: `version = "0.2.0"`
- `src/bundlewalker/__init__.py`: `__version__ = "0.2.0"`

Refresh `uv.lock` so its editable BundleWalker package metadata records the same version. No
dependency range changes are part of this release.

## Verification and publication flow

The release is created in this order:

1. Confirm `v2` does not already exist locally or on `origin`.
2. Update package metadata, lockfile, and release documentation.
3. Verify package-version consistency and inspect the complete diff.
4. Verify the embedded user-guide block is byte-identical to `docs/user-guide.md`.
5. Validate all repository-local Markdown links and heading anchors.
6. Compare documented CLI and MCP commands with live help.
7. Run the complete offline test, formatting, lint, type-check, lockfile, and diff-integrity gates.
8. Commit the release state with an intentional release commit.
9. Push `master` to `origin` and verify the remote branch matches locally.
10. Create annotated tag `v2` at that verified commit and push only that tag.
11. Fetch the remote tag and verify its peeled commit matches local `master` and `origin/master`.

If any verification or publication step fails, stop before creating or pushing the tag. The
pre-existing untracked backup archive is excluded from every commit and tag.

## Out of scope

- Implementing the local web UI.
- Changing application, CLI, MCP, transaction, or producer behavior.
- Adding a hosted release artifact or GitHub Release page beyond the Git tag.
- Changing dependency ranges.
- Rewriting historical v1 design and plan records.
- Running opt-in live-model evaluations without separately configured credentials and approval.

## Acceptance criteria

The v2 release is complete when:

- package metadata consistently reports `0.2.0`;
- active documentation consistently identifies the current v2 release and its actual scope;
- `CHANGELOG.md` records v2 and v1 without contradicting the detailed guides;
- historical records retain their original milestone meaning;
- the embedded user guide matches the canonical guide exactly;
- repository-local Markdown links and anchors resolve;
- all offline release checks pass;
- `master` and `origin/master` point to the same release commit;
- local and remote annotated tag `v2` peel to that release commit; and
- the unrelated untracked backup archive remains uncommitted and unchanged.
