# BundleWalker Performance and Capacity Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the reviewed four-environment benchmark evidence and a conservative Medium supported-capacity envelope for public-beta Milestone B3.

**Architecture:** Extend the existing report renderer with an explicit publication mode that derives the highest complete successful candidate from a required supported-platform matrix. Commit the immutable workflow artifacts and a deterministic rendered report under `benchmarks/evidence/`, then make the public performance document summarize and link that evidence while release metadata tests enforce provenance and wording.

**Tech Stack:** Python 3.13/3.14, Pydantic evidence contracts, argparse, pytest, Markdown, GitHub Actions artifacts.

## Global Constraints

- Evidence source commit is exactly `dfaa31dfca3a431e7b2e2cb1ceda1e2cc0df286c` from workflow run `29789436063`.
- The supported matrix is exactly macOS/Linux on Python 3.13/3.14.
- The published envelope is derived from evidence; it is never supplied as unchecked prose.
- Milestone B3 requires at least Medium: 1,000 knowledge documents, approximately 10 MiB of wiki content, and a 50,000-character ingestion source.
- Large and Probe observations remain unsupported boundary evidence.
- Remote model-provider latency is excluded, Windows remains experimental, and the project remains a proof of concept until every beta gate passes.
- Keep package version `0.4.0a2`; `0.4.0rc1` belongs to the next production-PyPI gate.

---

### Task 1: Add a safe published-report mode

**Files:**
- Modify: `tests/benchmarks/test_report.py`
- Modify: `tests/benchmarks/test_runner.py`
- Modify: `benchmarks/report.py`
- Modify: `benchmarks/__main__.py`

**Interfaces:**
- Consumes: `EvidenceRecord`, the frozen `PROFILES` catalog, and exact matrix validation.
- Produces: `render_report(records, provisional=False, require_matrix=True)` that derives and publishes the conservative envelope.
- Produces: `python -m benchmarks report ... --published --require-matrix` as the explicit publication command.

- [ ] **Step 1: Write failing renderer tests**

Add tests requiring a complete four-record matrix to render `Status: reviewed evidence`, identify Medium as the supported capacity, retain Large/Probe as unsupported, name the source commit, and reject publication when only Small qualifies or when matrix validation is disabled.

- [ ] **Step 2: Run the renderer tests and verify RED**

Run:

```bash
uv run pytest tests/benchmarks/test_report.py -q
```

Expected: the new publication tests fail because `render_report(..., provisional=False)` currently rejects every non-provisional report.

- [ ] **Step 3: Implement minimal publication derivation**

Refactor the common report body without weakening provisional behavior. For publication mode:

1. require `require_matrix=True`;
2. compute candidate status for Small, Medium, and Large across every record;
3. select the highest `complete successful candidate measurement`;
4. reject an envelope below Medium;
5. render the exact profile dimensions from the frozen record; and
6. label larger measured or stopped profiles as unsupported boundary evidence.

Keep provisional output unchanged: it must still say `Supported capacity: not yet published` and must never imply support.

- [ ] **Step 4: Add failing CLI publication tests**

Test that `--provisional` and `--published` are explicit mutually exclusive modes, that `--published` requires `--require-matrix`, and that a qualifying evidence directory writes a reviewed report.

- [ ] **Step 5: Run the CLI tests and verify RED**

Run:

```bash
uv run pytest tests/benchmarks/test_runner.py -q
```

Expected: the new parser and publication tests fail because only required `--provisional` exists.

- [ ] **Step 6: Implement the explicit CLI mode**

Add a required mutually exclusive mode group with `--provisional` and `--published`. Pass `provisional=not arguments.published` to the renderer and reject `--published` without `--require-matrix` before reading or writing report content.

- [ ] **Step 7: Verify Task 1**

Run:

```bash
uv run pytest tests/benchmarks/test_report.py tests/benchmarks/test_runner.py -q
uv run ruff format --check benchmarks tests/benchmarks
uv run ruff check benchmarks tests/benchmarks
uv run pyright benchmarks tests/benchmarks
```

Expected: all commands exit zero.

### Task 2: Commit immutable evidence and deterministic report

**Files:**
- Create: `benchmarks/evidence/suite-1-dfaa31dfca3a431e7b2e2cb1ceda1e2cc0df286c-Linux-py3.13-29789436063.json`
- Create: `benchmarks/evidence/suite-1-dfaa31dfca3a431e7b2e2cb1ceda1e2cc0df286c-Linux-py3.14-29789436063.json`
- Create: `benchmarks/evidence/suite-1-dfaa31dfca3a431e7b2e2cb1ceda1e2cc0df286c-macOS-py3.13-29789436063.json`
- Create: `benchmarks/evidence/suite-1-dfaa31dfca3a431e7b2e2cb1ceda1e2cc0df286c-macOS-py3.14-29789436063.json`
- Create: `benchmarks/evidence/SHA256SUMS`
- Create: `benchmarks/evidence/report.md`
- Modify: `tests/test_release_metadata.py`

**Interfaces:**
- Consumes: the four downloaded artifacts from GitHub Actions run `29789436063`.
- Produces: four byte-identical JSON records, a checksum manifest, and a report regenerated solely from those records.

- [ ] **Step 1: Write failing provenance tests**

Require exactly four JSON files under `benchmarks/evidence/`; validate each through `load_evidence`; require schema/suite 1, full-policy timing, source commit `dfaa31d...`, run ID `github-29789436063`, package `0.4.0a2`, and the four supported environment keys. Require the committed checksum manifest to match the four reviewed SHA-256 values and `report.md` to equal `render_report(records, provisional=False, require_matrix=True)` byte for byte.

- [ ] **Step 2: Run the provenance test and verify RED**

Run:

```bash
uv run pytest tests/test_release_metadata.py -q
```

Expected: failure because `benchmarks/evidence/` has not been published.

- [ ] **Step 3: Copy and verify the immutable JSON artifacts**

Copy only the four reviewed JSON records into `benchmarks/evidence/`, create `SHA256SUMS` with repository-relative filenames, and verify:

```text
cb22e213cbd7af4ac7203d055cab95b1207d5d232a2daf8fe2bf60f677d2d645  suite-1-dfaa31dfca3a431e7b2e2cb1ceda1e2cc0df286c-Linux-py3.13-29789436063.json
6abfd90b0fba6b2f7fcbcffd6aa6e7ef91a485262bceac5cab6e49f815c8311e  suite-1-dfaa31dfca3a431e7b2e2cb1ceda1e2cc0df286c-Linux-py3.14-29789436063.json
624a81b85f69b41bec7680c3b69b1ec45e6f8b91c9f0303ec0ed36d953ff4b84  suite-1-dfaa31dfca3a431e7b2e2cb1ceda1e2cc0df286c-macOS-py3.13-29789436063.json
5edc699e5fd4fd2becf6d52d24bd471d93e9b287f585a194742664df1fbe6689  suite-1-dfaa31dfca3a431e7b2e2cb1ceda1e2cc0df286c-macOS-py3.14-29789436063.json
```

- [ ] **Step 4: Render the reviewed report**

Run once to a nonexistent destination:

```bash
uv run python -m benchmarks report \
  --evidence benchmarks/evidence \
  --output benchmarks/evidence/report.md \
  --published \
  --require-matrix
```

Expected: exit zero and a report publishing Medium while identifying Large/Probe as unsupported boundary evidence.

- [ ] **Step 5: Verify Task 2**

Run:

```bash
(cd benchmarks/evidence && shasum -a 256 -c SHA256SUMS)
uv run pytest tests/test_release_metadata.py tests/benchmarks -q
```

Expected: all four checksums report `OK`; all tests pass.

### Task 3: Publish the user-facing capacity interpretation

**Files:**
- Modify: `docs/performance-and-capacity.md`
- Modify: `README.md`
- Modify: `SUPPORT.md`
- Modify: `docs/user-guide.md`
- Modify: `CHANGELOG.md`
- Modify: `tests/test_release_metadata.py`

**Interfaces:**
- Consumes: the reviewed Medium envelope and committed evidence/report paths.
- Produces: one public support statement with explicit limits, environments, provenance, disk observations, and non-guarantees.

- [ ] **Step 1: Replace provisional metadata assertions with published-contract assertions**

Require the public document to state exactly one supported capacity of 1,000 documents, approximately 10 MiB, and a 50,000-character ingestion source. Require source commit/run links, all four evidence links, the deterministic report link, the four reference environments, the Medium transaction checkpoint maximum of 12,951,552 bytes, the existing 1-GiB free-space advisory, remote-model exclusion, experimental Windows wording, and proof-of-concept wording.

- [ ] **Step 2: Run the metadata test and verify RED**

Run:

```bash
uv run pytest tests/test_release_metadata.py -q
```

Expected: failure because the public documents still describe evidence as provisional.

- [ ] **Step 3: Update the public documentation**

Rewrite `docs/performance-and-capacity.md` around the reviewed Medium envelope. Preserve the scenario/timing methodology, explain why `capacity_exceeded` at larger profiles does not invalidate Medium, document the exact reference environments, link the workflow and committed evidence/report, describe the observed Medium checkpoint bytes and conservative 1-GiB advisory, and retain all non-guarantees.

Update README, SUPPORT, and the user guide to link the reviewed capacity rather than provisional methodology. Add an Unreleased changelog entry for the reviewed evidence and Medium support envelope. Do not change the package version or call the public beta complete.

- [ ] **Step 4: Verify Task 3**

Run:

```bash
uv run pytest tests/test_release_metadata.py -q
uv run python -m markdown_it docs/performance-and-capacity.md >/dev/null
```

Expected: all commands exit zero.

### Task 4: Verify and publish the protected-branch change

**Files:**
- Review: all files changed since `master`

**Interfaces:**
- Produces: a reviewed pull request from `codex/b3-reviewed-evidence` into `master`.

- [ ] **Step 1: Run the full repository verification**

Run:

```bash
uv lock --check
uv run pytest -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv build
uv run twine check dist/*
```

Expected: every command exits zero.

- [ ] **Step 2: Review provenance and the complete diff**

Confirm the worktree is clean except for intended files, evidence checksums match, no absolute local path or secret appears in the JSON/report/docs, the report regenerates byte-for-byte, and package version remains `0.4.0a2`.

- [ ] **Step 3: Commit the coherent Phase 2 change**

```bash
git add benchmarks docs README.md SUPPORT.md CHANGELOG.md tests
git commit -m "docs: publish reviewed Medium capacity evidence"
```

- [ ] **Step 4: Push and open the ready pull request**

```bash
git push -u origin codex/b3-reviewed-evidence
gh pr create --base master --head codex/b3-reviewed-evidence --title "docs: publish reviewed Medium capacity evidence" --body-file PR_BODY.md
```

Expected: GitHub returns a pull-request URL. Required macOS/Linux CI and CodeQL must pass before merge; experimental Windows remains non-blocking.
