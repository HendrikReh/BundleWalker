# Performance and Capacity

## Status

BundleWalker has a reproducible measurement foundation for local workspace behavior.

Supported capacity is not yet published.

The current material describes how evidence will be collected; it does not set a capacity
boundary.

## What will be measured

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
call, a network connection, or a provider service.

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
public workspace limit; Phase 1 does not raise it.

Smoke is a correctness check. Small, Medium, and Large are candidates for later capacity
evaluation. Probe is exploratory and cannot become supported because a single run succeeds.

## Interpretation

Any result produced by this foundation is candidate only. It is evidence about named reference
environments and a deterministic synthetic workload, not a universal hardware SLA or a promise
about every filesystem, machine, or workspace.

## Exclusions and platforms

For this methodology, remote model-provider latency is excluded because BundleWalker does not
control it. macOS and Linux are the official supported platforms for the evidence workflow on
Python 3.13 and 3.14. Windows remains experimental, so it is not part of a capacity claim.

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

Inspect the generated evidence before sharing it. Local runs are useful for development, but they
do not themselves establish a supported capacity.

## Evidence process

The scheduled/manual macOS and Linux evidence workflow runs after the measurement foundation is
merged. It records the complete supported-platform matrix and uploads its JSON evidence and
provisional summary for review. A second, reviewed evidence pull request then validates those
artifacts and updates the public capacity documentation only when the full cross-platform evidence
supports it.
