# Performance and Capacity

## Reviewed envelope

Status: reviewed evidence.

BundleWalker remains a proof of concept for technical solo users. The reviewed, reproducible
evidence establishes one conservative envelope for the local CLI and workspace-bound MCP server.

Supported capacity is 1,000 knowledge documents, approximately 10 MiB of wiki content, and a 50,000-character ingestion source.

This statement is limited to the deterministic synthetic workload, the scenarios below, and the
four reference environments. It is not a universal hardware SLA or a promise for every
filesystem, machine, workspace shape, source, or model provider.

## Reviewed provenance

The evidence was measured from [source commit
`dfaa31dfca3a431e7b2e2cb1ceda1e2cc0df286c`](https://github.com/HendrikReh/BundleWalker/commit/dfaa31dfca3a431e7b2e2cb1ceda1e2cc0df286c)
in [GitHub Actions run 29789436063](https://github.com/HendrikReh/BundleWalker/actions/runs/29789436063).
The immutable records and [deterministic rendered report](../benchmarks/evidence/report.md) are
committed with this repository:

- [Linux, Python 3.13 evidence](../benchmarks/evidence/suite-1-dfaa31dfca3a431e7b2e2cb1ceda1e2cc0df286c-Linux-py3.13-29789436063.json)
- [Linux, Python 3.14 evidence](../benchmarks/evidence/suite-1-dfaa31dfca3a431e7b2e2cb1ceda1e2cc0df286c-Linux-py3.14-29789436063.json)
- [macOS, Python 3.13 evidence](../benchmarks/evidence/suite-1-dfaa31dfca3a431e7b2e2cb1ceda1e2cc0df286c-macOS-py3.13-29789436063.json)
- [macOS, Python 3.14 evidence](../benchmarks/evidence/suite-1-dfaa31dfca3a431e7b2e2cb1ceda1e2cc0df286c-macOS-py3.14-29789436063.json)

The four reference environments were:

- macOS 15 (Darwin 24.6.0), CPython 3.13.14, arm64, APFS
- macOS 15 (Darwin 24.6.0), CPython 3.14.6, arm64, APFS
- Ubuntu 24 (Linux 6.17.0-1020-azure), CPython 3.13.14, x86_64, ext2/ext3
- Ubuntu 24 (Linux 6.17.0-1020-azure), CPython 3.14.6, x86_64, ext2/ext3

Each record also retains the runner CPU and memory inventory, generated tree digest, complete
samples, and checkpoint observations. The complete matrix meets the Medium targets. The overall
report disposition is `capacity_exceeded` because the larger profiles miss targets or reach their
deadline; that result is the measured boundary above Medium, not a failure of its completed,
passing lower profile.

## Observed disk behavior

The largest Medium transaction checkpoint observed across the matrix was 12,951,552 bytes. That
is an observation of this workload, not a reservation calculation or a guarantee that a write will
fit on another workspace. `bundlewalker doctor` retains its conservative 1-GiB free-space advisory:
it warns below that threshold and cannot determine whether any particular ingestion, backup, or
transaction will fit.

## What is measured

The benchmark harness generates deterministic synthetic workspaces from fixed profiles and seeds.
It measures these twelve local scenarios:

### Scenario inventory

1. Workspace initialization (`initialize`).
2. Workspace status (`status`).
3. First-page concept listing (`list_concepts`).
4. End-of-order concept reading (`read_concept`).
5. Lexical present-result search (`search_present`).
6. Lexical absent-result search (`search_absent`).
7. Deterministic lint (`lint`).
8. MCP startup and discovery (`mcp_startup`).
9. Ingestion preparation (`prepare_ingestion`).
10. Review commit (`commit`).
11. Prepared-review recovery (`recover_prepared`).
12. Swapping-boundary recovery (`recover_swapping`).

Correctness, cleanup, and durable transaction state are checked for every scenario. Ingestion
preparation uses a deterministic runner, and the recovery scenarios cover both a prepared review
and an interrupted commit at the swapping boundary.

### Timing boundary

For ordinary scenarios, fixture generation and preparation are excluded from timing; controller
workspace copying is excluded from timing; and ordinary Python worker startup is excluded from
timing. The ordinary scenario timers bracket only the specified production call. Setup and
correctness checks happen outside those timers.

MCP startup is exceptional: its timer includes process launch and protocol initialization through
sorted tool discovery. The clean shutdown happens after the timer stops and is outside the
measurement.

These measurements deliberately exercise local production behavior. They do not measure a model
call, a network connection, or a provider service. In particular, remote model-provider latency is excluded because BundleWalker does not control it.

## Profiles

| Profile | Knowledge documents | Approximate wiki content | Ingestion source |
| --- | ---: | ---: | ---: |
| Smoke | 50 | 0.5 MiB | 10,000 Unicode characters |
| Small | 250 | 2.5 MiB | 25,000 Unicode characters |
| Medium | 1,000 | 10 MiB | 50,000 Unicode characters |
| Large | 5,000 | 50 MiB | 100,000 Unicode characters |
| Probe | 10,000 | 100 MiB | 100,000 Unicode characters |

Approximate wiki content is the total byte size of regular files in the configured wiki directory
after generation; each evidence record retains the exact bytes, document count, parameters, and
tree digest. Large and Probe both use 100,000 Unicode characters because that is the existing
public workspace limit; this evidence does not raise it. Smoke is a correctness profile and Probe
is exploratory, not a promise of successful operation at that size.

## Platforms and exclusions

macOS and Linux are the official supported platforms for the evidence workflow on Python 3.13 and
3.14. Windows remains experimental, so it is not part of this envelope. The evidence does not
cover hosted operation, remote MCP transport, multi-user synchronization, a web UI, embeddings,
vector databases, additional source formats, automatic Git operations, or remote-model behavior.

## Privacy

The harness uses synthetic content and allowlisted metadata only. It does not collect workspace
content, credentials, environment-variable names or values, or unrelated host and filesystem
details. Publishing locally collected evidence remains an explicit maintainer decision.

## Reproduction

`benchmarks` is a maintainer and developer harness available from a repository checkout. It is
intentionally absent from installed wheels and source distributions, and it is not a user-facing
BundleWalker command.

Run the correctness-only Smoke path without timing assertions:

```text
uv run python -m benchmarks run --profiles smoke --correctness-only \
  --output benchmark-results/smoke.json
```

Run the full local sequence:

```text
uv run python -m benchmarks run \
  --profiles smoke,small,medium,large,probe \
  --output benchmark-results/local.json
```

Inspect generated local evidence before sharing it. It is useful for development, but it neither
changes the reviewed envelope nor substitutes for a complete reviewed cross-platform matrix.
