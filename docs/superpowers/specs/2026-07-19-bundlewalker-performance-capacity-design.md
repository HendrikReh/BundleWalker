# BundleWalker Performance and Capacity Evidence Design

**Date:** 2026-07-19
**Status:** Approved
**Milestone:** Public-beta Milestone B3 — performance and capacity evidence

## Summary

BundleWalker has completed the build/release foundation, workspace lifecycle safety, and
diagnostics portions of its reliability-first public-beta roadmap. The remaining Operational
Safety gate is objective evidence about how the file-based workspace behaves as it grows.

This design adds a development-only benchmark subsystem that generates deterministic synthetic
workspaces, exercises local production boundaries, records versioned evidence, and renders a
public performance and capacity report. The first published capacity envelope is conservative: it
is the largest complete profile that meets the agreed targets on the slowest valid result across
the supported macOS/Linux and Python 3.13/3.14 matrix.

The evidence describes tested behavior on named reference environments. It is not a universal
elapsed-time service-level agreement for arbitrary user hardware.

## Goals

1. Measure the local operations whose cost grows with a workspace.
2. Publish a practical, reproducible, and conservative supported capacity envelope.
3. Detect material performance regressions without making ordinary pull requests timing-flaky.
4. Measure transaction disk amplification at stable lifecycle checkpoints.
5. Keep benchmark machinery outside the production package and normal user workflows.
6. Preserve BundleWalker's local-first privacy boundary and deterministic safety guarantees.

## Decisions

- Use a layered standalone benchmark harness under `benchmarks/`.
- Keep all benchmark code development-only; add no runtime dependency or user command.
- Generate fixtures from fixed profiles and seeds instead of committing large workspaces.
- Exclude remote model latency from BundleWalker's capacity and performance claims.
- Exercise user-facing behavior through `WorkspaceApplication` where it exposes the operation.
- Use transaction/recovery services directly only to isolate a lifecycle phase that the facade
  intentionally combines with another phase.
- Verify benchmark correctness on every pull request, but run full timing measurements only in a
  scheduled or manually dispatched workflow.
- Keep timing comparisons informational until repeated data demonstrates stable variance.
- Publish one conservative supported envelope rather than separate macOS and Linux limits.
- Deliver the measurement foundation and the reviewed evidence in two repository changes.

## Scope

### Included

- deterministic synthetic OKF workspace generation;
- fixed Smoke, Small, Medium, Large, and Probe profiles;
- initialization, inspection, retrieval, lint, ingestion preparation, commit, MCP startup, and
  recovery scenarios;
- duration samples and portable environment metadata;
- materialized disk usage at transaction checkpoints;
- a versioned JSON evidence format;
- deterministic Markdown report generation;
- pull-request correctness tests;
- scheduled/manual supported-platform timing runs; and
- a public performance and capacity document.

### Excluded

- remote model-provider performance;
- Windows capacity claims while Windows remains experimental;
- automatic telemetry or crash reporting;
- a public `bundlewalker benchmark` command;
- a database, background index, daemon, or hosted collector;
- a broad rewrite of `src/bundlewalker/transactions.py`;
- the local web UI;
- production publication, a version bump, a tag, or a release; and
- replacing the proof-of-concept label before all public-beta gates pass.

## Architecture

The benchmark subsystem lives outside `src/bundlewalker` and has four responsibilities.
Although it is not shipped in the wheel, it remains first-class repository code: Ruff formats and
lints it, and the strict Pyright include set expands to cover `benchmarks` as well as `src` and
`tests`.

### Synthetic workspace generator

The generator creates an ordinary BundleWalker workspace from a profile and a fixed integer seed.
It writes only public workspace structures and valid OKF Markdown. Given the same suite version,
profile, and seed, it produces the same relative paths and file bytes on every supported platform.

Profile generation controls:

- document count and approximate wiki bytes;
- type distribution across sources, topics, entities, and syntheses;
- body size;
- link, citation, and tag density;
- stable searchable terms with known expected rankings;
- ingestion-source character count; and
- optional transaction state required by a recovery scenario.

Generated timestamps and identifiers are fixed from the seed. Files use UTF-8 and LF line endings.
The generator validates the completed workspace with BundleWalker's production loader and
deterministic linter before it is eligible for measurement.

### Scenario controller and workers

A controller prepares fixtures outside the timed interval and launches isolated workers. Each
worker receives a scenario name, profile, fixture path, and output path. For normal operations, the
worker starts the timer immediately before invoking the production boundary and stops it
immediately after the result returns. Python startup and controller-side fixture copying are
therefore excluded unless process startup is the behavior being measured.

MCP startup is the exception: the controller starts timing before launching `bundlewalker-mcp` and
stops after protocol initialization and tool discovery complete. The controller owns the child
process, enforces its deadline, closes stdio, and verifies termination.

Mutation and recovery workers receive an independent fixture copy for every sample. Read-only
workers may share a validated fixture because they must not change it. A post-scenario verifier
checks expected output, wiki identity, durable review state, and transaction cleanup before a
duration becomes valid evidence.

### Evidence recorder

Workers return structured sample results to the controller. The controller validates all records
and atomically writes a versioned JSON document. It never rewrites an existing evidence file.
Incomplete temporary files have a distinct suffix and are never accepted by the report renderer.

### Report renderer

The renderer accepts only complete evidence whose schema, suite version, profile digest, and
commit relationships are internally consistent. It produces deterministic Markdown containing:

- the supported envelope;
- environment descriptions;
- per-scenario median and p95 results;
- disk observations;
- profiles that were probed but are not supported;
- interpretation and non-guarantee wording; and
- exact reproduction commands.

The renderer contains no measurement logic. Published claims can therefore be regenerated from
reviewed evidence without rerunning benchmarks.

## Workspace profiles

The first suite defines these immutable profiles:

| Profile | Knowledge documents | Approximate wiki content | Ingestion source |
|---|---:|---:|---:|
| Smoke | 50 | 0.5 MiB | 10,000 characters |
| Small | 250 | 2.5 MiB | 25,000 characters |
| Medium | 1,000 | 10 MiB | 50,000 characters |
| Large | 5,000 | 50 MiB | 100,000 characters |
| Probe | 10,000 | 100 MiB | 100,000 characters |

"Approximate wiki content" is the total byte size of regular files under the configured wiki
directory after generation. The generator targets the stated size and records the exact result;
the exact bytes, document count, profile parameters, and tree digest appear in every evidence
record.

The ingestion source is deterministic ASCII text, so its Unicode character count equals its UTF-8
byte count. It never exceeds the existing default `max_source_characters = 100000` product
boundary. Large and Probe intentionally share that maximum: Probe increases workspace scale
without inventing a larger supported source contract.

All profiles use the same proportions and density rules. Increasing a profile therefore changes
scale rather than changing the semantic shape of the workload. Profile definitions are versioned
with the suite. Any material definition change creates a new suite version and baseline rather
than silently changing historical evidence.

Smoke exists for correctness checks. Small, Medium, and Large are candidates for the supported
envelope. Probe is exploratory and cannot become supported merely because one run succeeds.

## Scenarios

### Workspace initialization

Initialize an empty workspace with the standard preset and validate the resulting structure. This
scenario is environment-level rather than profile-dependent.

### Status and retrieval

Measure these `WorkspaceApplication` operations:

- `status`;
- first-page concept listing;
- reading a concept near the end of the generated ordering; and
- lexical search for fixed present and absent terms.

Expected counts, concept identities, and ranking order are verified after every sample. Search
measures BundleWalker's current scan-based retrieval behavior; the milestone does not introduce an
index to improve the result in advance.

### Deterministic lint

Run `WorkspaceApplication.lint` with semantic lint disabled. The fixture is valid, so the expected
finding set is empty. Remote or injected semantic-model timing is outside the capacity claim.

### Ingestion preparation

Call `WorkspaceApplication.prepare_ingestion` with an injected deterministic ingestion runner and
a fixed clock. The injected runner returns a valid prepared `ChangeSet` and audited read set; it
performs no network operation. The measured interval still covers workspace recovery, duplicate
detection, repository/context reads, change validation, transaction staging, prospective-tree
construction, diffing, hashing, durable review creation, and raw payload staging.

The model/provider call is excluded by design and reported separately as an external variable.

### Review commit

Start from the independently prepared durable review for that profile and measure
`WorkspaceApplication.apply_review`. Verify the expected source persistence, wiki tree, review
removal, transaction cleanup, and deterministic lint result.

### MCP startup and discovery

Launch the installed MCP entry point over stdio, complete protocol initialization, and list tools.
Verify the expected stable tool names and close the session cleanly. No model call occurs.

### Recovery

Measure representative recovery states whose cost grows with the wiki:

1. a complete prepared review that should remain pending after recovery; and
2. an authenticated interrupted commit at the swapping boundary that must resolve to the expected
   live tree and clean transaction state.

Recovery fixtures are created through production transaction behavior plus the existing
test-supported fault boundary. The benchmark does not invent an alternate journal format.

## Measurement policy

Durations use Python's monotonic `perf_counter_ns`. Each environment records:

- one untimed warm-up for each read-only scenario/profile pair;
- seven measured samples for status, list, read, search, lint, initialization, and MCP startup; and
- five measured samples for ingestion preparation, commit, and recovery.

The warm-up is a complete scenario execution and must pass correctness checks. Mutation warm-up
uses a disposable workspace copy. Samples run serially so concurrent benchmark workers do not
compete with one another.

The report publishes every sample, median, and nearest-rank p95. The median determines whether a
profile meets the initial performance target. p95 is descriptive because hosted-runner tail
variance is not stable enough for the first capacity boundary. No minimum, best-of-run, or
discarded slow sample may substitute for a median.

The runner records stable filesystem bytes at the prepared, interrupted, restored/committed, and
cleaned checkpoints. These are observed materialized sizes, not a claim that sampling captured an
unobservable instantaneous peak. Storage guidance uses the largest observed amplification plus an
explicit conservative margin stated in the public report.

### Reference targets

| Operation class | Median target at the supported envelope |
|---|---:|
| Status, list, read, and lexical search | at most 2 seconds each |
| Workspace initialization | at most 3 seconds |
| MCP startup and discovery | at most 5 seconds |
| Deterministic lint | at most 30 seconds |
| Ingestion preparation | at most 60 seconds |
| Review commit | at most 60 seconds |
| Interrupted-operation recovery | at most 60 seconds |

A scenario also fails correctness if it produces validation errors, unexpected output, data loss,
an unresolved transaction state, or incomplete cleanup. Correctness is never traded for speed.

Deadlines are three times the scenario target, with a minimum of 30 seconds. A deadline exceedance
terminates the worker. For Smoke through Medium it fails the benchmark job. At Large or Probe it
marks that profile incomplete and stops measuring larger profiles, while preserving valid evidence
for lower profiles. A correctness, integrity, cleanup, schema, or harness failure fails the entire
job at every profile, including Probe.

## Capacity claim

The supported capacity is the highest complete candidate profile for which every required
scenario meets its correctness and median targets in every evidence record selected for the
qualifying supported matrix:

- macOS, Python 3.13;
- macOS, Python 3.14;
- Linux, Python 3.13; and
- Linux, Python 3.14.

The slowest valid combination controls the single published envelope. The report names every
reference environment and records exact profile sizes so users can compare their hardware and
workload. It does not promise the same elapsed time on slower hardware or unusual filesystems.

Milestone B3 requires at least Medium—1,000 knowledge documents, approximately 10 MiB of wiki
content, and a 50,000-character ingestion source—to satisfy the complete matrix. Large is the
desired first envelope. If Medium fails, B3 remains incomplete and no smaller profile is presented
as sufficient for public beta. Specific bottlenecks are diagnosed before targeted optimization and
a fresh evidence run.

Probe results are always labeled exploratory. A future release may promote a larger envelope only
through a reviewed evidence update.

## Evidence format

The top-level JSON evidence record contains:

- `schema_version` and `suite_version`;
- benchmark start/end timestamps and run identifier;
- exact Git commit and BundleWalker distribution version;
- Python version and implementation;
- OS, release, architecture, logical CPU count, total memory when portable, runner image identity,
  and benchmark-filesystem type when portable;
- profile definitions, exact generated sizes, seeds, and tree digests;
- scenario names and scenario-version identifiers;
- warm-up and repetition policy;
- all duration samples and derived median/p95 values;
- correctness outcomes and expected-output digests;
- materialized-byte observations at defined checkpoints; and
- the final run disposition.

The schema uses bounded strings and numbers and rejects unknown schema versions. A scenario record
cannot claim success without the required sample count and successful correctness verifier.

Evidence eligible for publication lives under `benchmarks/evidence/`. Unreviewed local results,
generated fixtures, caches, and temporary files are ignored. Evidence filenames include the suite
version, commit, OS family, Python version, and run identifier; existing files are never silently
overwritten.

## Privacy

Evidence contains aggregate sizes and execution metadata only. It never contains:

- workspace or home-directory paths;
- usernames or hostnames;
- generated document text or raw source content;
- credentials, environment-variable names, or environment-variable values; or
- unrelated process or filesystem information.

Hardware fields are allowlisted. Publishing a locally collected result is a separate explicit
maintainer action. GitHub-hosted runner evidence is intended for review and publication.

## Continuous integration

### Pull-request correctness layer

Normal supported-platform CI runs fast benchmark contract tests and the Smoke correctness path. It
does not assert elapsed time. These tests cover generator determinism, schema behavior, scenario
outputs, isolation, and rendering without exposing ordinary pull requests to hosted-runner timing
noise. The Smoke path runs one correctness-checked sample per scenario, not the full repetition
policy.

### Measurement workflow

`.github/workflows/benchmarks.yml` supports `schedule` and `workflow_dispatch`. It runs the full
profile sequence on the existing supported macOS/Linux and Python 3.13/3.14 matrix. Matrix jobs
upload complete JSON records and a rendered preview as workflow artifacts. A final summary job
validates matrix completeness and reports the candidate conservative envelope.

The measurement workflow is not a required pull-request check during B3. Scheduled results compare
against the committed baseline and annotate a potential regression when a scenario median is both:

- at least 25 percent slower; and
- at least 250 milliseconds slower.

Correctness and integrity failures remain hard workflow failures. Timing regressions are
informational until at least ten successful scheduled runs demonstrate acceptable variance for the
scenario across the supported matrix. Enabling a blocking timing gate requires a separate reviewed
change with per-scenario evidence; it never happens automatically.

A single scheduled timing flag does not silently rewrite or revoke the published envelope. A
repeatable flag is investigated and either fixed or reflected in a reviewed evidence/report update
before the next release claim.

## Error handling

- Generation or validation failure aborts before measurement.
- Worker timeouts cause controlled termination and process reaping.
- Unexpected output invalidates the sample and fails correctness.
- Mutation workers verify final wiki identity, raw-source identity, review state, and transaction
  cleanup.
- Recovery workers verify the selected safe end state and clean durable topology.
- The recorder writes to a temporary sibling and atomically renames only after full validation.
- The renderer rejects incomplete files, mixed commits, mixed suite versions, profile-digest
  conflicts, insufficient samples, and unsupported schema versions.
- Report generation writes atomically, so a failed renderer cannot leave a partially updated report
  that appears current.

## Testing strategy

Focused tests under `tests/benchmarks/` cover:

1. identical fixture hashes for identical profile/seed inputs;
2. distinct and monotonically scaling profile sizes;
3. valid workspace and OKF structure for every profile definition using reduced test sizes where
   full materialization is unnecessary;
4. known counts, read results, and lexical rankings;
5. deterministic lint success;
6. injected-runner ingestion preparation without network access;
7. commit and recovery end-state identities;
8. fresh-copy isolation for mutation samples;
9. MCP subprocess startup, discovery, timeout, and cleanup;
10. evidence schema rejection and exact sample-count enforcement;
11. atomic output behavior under injected write failure;
12. deterministic Markdown rendering;
13. privacy-field allowlisting; and
14. regression classification at the absolute and relative boundaries.

One end-to-end Smoke test generates a real workspace and runs the complete scenario controller
without timing assertions. Existing transaction and crash-recovery tests remain authoritative;
benchmark tests supplement rather than replace them.

## Documentation

`docs/performance-and-capacity.md` becomes the public source for:

- what the supported envelope means;
- the current profile and exact measured sizes;
- reference environments;
- scenario medians and p95 observations;
- disk amplification and conservative free-space guidance;
- limitations, including remote model and hardware variability;
- reproduction commands; and
- the evidence files used to render the page.

The README, user guide, support policy, and changelog link to this document where their current
proof-of-concept or capacity wording is affected. Phase 1 uses explicit “measurement pending”
wording. Only Phase 2 publishes the supported envelope.

## Delivery sequence

### Phase 1: Measurement foundation

The first pull request adds the harness, correctness tests, workflow, ignore rules, reproduction
instructions, and provisional performance document. It makes no capacity claim. After supported CI
and review pass, it is merged to `master` so the scheduled/manual workflow is dispatchable from the
default branch.

### Phase 2: Reviewed evidence

Run the merged workflow across the complete supported matrix. Infrastructure failures may be
rerun; valid slow results may not be discarded. Download and validate complete artifacts, then
commit the qualifying evidence and deterministically rendered report in a second pull request.

The second pull request selects the conservative envelope, updates affected documentation, and
records the baseline. Review confirms that the committed JSON matches the referenced workflow
artifacts and exact source commit. B3 is not complete until this evidence change merges.

## Acceptance criteria

Milestone B3 is complete when:

1. every generated fixture is deterministic and valid;
2. all scenario correctness checks pass across macOS/Linux and Python 3.13/3.14;
3. at least Medium meets every reference target across the complete matrix;
4. reviewed evidence and a reproducible report are committed;
5. the report publishes one conservative supported envelope and names its reference environments;
6. disk observations and their limitations are documented;
7. another developer can reproduce the workflow from the documented commands;
8. scheduled/manual comparisons identify material regressions;
9. normal pull-request CI verifies benchmark correctness without wall-clock assertions; and
10. no benchmark path sends telemetry, calls a remote model, or bypasses production mutation rules.

## Maintainability constraint

Benchmark evidence may reveal a specific hotspot. Targeted optimization or extraction is allowed
only when it directly enables an accepted scenario and begins with characterization coverage.
There is no general transaction refactor in B3. In particular, the measurement harness must not
become a second implementation of locking, staging, commit, or recovery.

## Risks and controls

| Risk | Control |
|---|---|
| Hosted-runner timing variance | Median-based evidence, absolute plus relative regression thresholds, and initially informational timing comparisons |
| Benchmark gaming | Fixed versioned profiles, exact sizes/digests, complete scenario set, and slowest-matrix envelope selection |
| Invalid synthetic workloads | Production parsing/lint validation and stable type/link/citation distributions |
| Fixture setup contaminating timings | Controller/worker separation and setup outside timed intervals |
| Mutation samples influencing one another | Independent workspace copy and post-scenario identity checks |
| Remote model latency obscuring local cost | Injected deterministic runner and explicit exclusion from the claim |
| Private machine or content disclosure | Synthetic content, allowlisted metadata, and explicit publication of local results |
| Broad refactoring during measurement | Characterization-first, evidence-driven targeted changes only |
| Stale or cherry-picked evidence | Exact commits, immutable evidence files, complete matrix validation, and reviewed report generation |

## Follow-on work

After B3, the roadmap advances to Milestone C: certify Hermes and a second independent MCP host,
verify published-artifact installation and MCP setup, align error categories across CLI/MCP, and
complete public-beta documentation. External beta validation follows. The local web UI remains the
first planned product-surface expansion after the reliability-first public-beta gates.
