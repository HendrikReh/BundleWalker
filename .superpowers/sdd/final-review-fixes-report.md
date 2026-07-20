# B3 final whole-branch review fixes

## Scope and baseline

- Baseline: `89c6cb7346de4a23cbbf9d7ba1112bddc67d65b2`.
- Scope stayed within benchmark contracts, fixture generation, worker reconstruction, evidence
  metadata, the runner workaround, and corresponding benchmark tests.
- No production dependency, workflow, public documentation, release metadata, version, tag,
  publication, push, or merge changed.

## RED to GREEN evidence

| Finding | RED | GREEN |
| --- | --- | --- |
| Canonical profile identity | Importing `profile_sha256` from `benchmarks.contracts` failed during collection. After the shared helper existed, arbitrary digest and off-by-one exact-wiki-byte probes were both accepted. | The shared helper matches the independent Smoke literal `b1723d2a96337355d40c61c87a68e613adc8a141449105e0dc91b43f75fc30e8`; both mismatches are rejected by `EvidenceRecord`, while canonical records and report matrices pass. The private fixture duplicate was removed. |
| End-of-order read workload | Smoke expected the final canonical ID but received `topics/concept-000042`; after fixture generation moved, a fresh fixture was rejected by the worker's old frozen identity. | Every frozen profile targets `document_count - 1`, contains the present-search needle in exactly that document, retains its exact source-character bound, and matches the regenerated suite-v1 digest catalog. A worker reads a fresh final concept and rejects the exact previous concept-42 Smoke tree identity. |
| Darwin filesystem type | The Darwin unit probe reached `stat -f %T`; the failure probe returned `/`. The runner converted an injected `/` value to `None`. | Darwin uses a complete fixed-size `statfs` structure and accepts only the bounded `f_fstypename` token; library/call/decoding failures return `None`. Linux retains its bounded pipe. The runner preserves collected metadata without a slash workaround. |

## Deterministically regenerated suite-v1 tree SHA-256 catalog

| Profile | SHA-256 |
| --- | --- |
| Smoke | `2056081991941f2b9aab5a32ff1fa22058d959cb86f122caab1aea29e8ed5676` |
| Small | `9727173321acf3c9193865d0f31df12a1a0221b4e05d25d6cfda2092409057df` |
| Medium | `3f5a4083bcbab9a69169eaca55c122e2cfde01852a988d315822074b12d65cf5` |
| Large | `9f99b5a5c5c7bdac10981e8889bb9ef69c25b63fc1cd424ea1030535bd869072` |
| Probe | `fa6f7de49a3d3ebd2e032e5a421f4946465ec606d5d19c14523cc3257029d644` |

The catalog was produced from the official deterministic generator in profile order. Persistent
parameterized tests independently regenerate every profile and compare all five identities.

## Real Darwin probes

- Direct worktree probe: `collect_environment(Path.cwd()).filesystem_type` returned exact `apfs`;
  it was ASCII, case-normalized, and within the 64-character evidence bound.
- Final real CLI Smoke used a canonical unaliased `/private/tmp` directory and returned:
  disposition `pass`, filesystem `apfs`, profile digest
  `b1723d2a96337355d40c61c87a68e613adc8a141449105e0dc91b43f75fc30e8`, tree digest
  `2056081991941f2b9aab5a32ff1fa22058d959cb86f122caab1aea29e8ed5676`, and twelve scenarios.
- A preliminary CLI attempt through macOS's `/var` alias was correctly rejected by the existing
  unaliased-path safety contract. A subsequent validation script used an incorrect expected count
  of fourteen instead of twelve scenarios; the corrected fresh run above passed.

## Verification

| Command | Result |
| --- | --- |
| Focused evidence, fixtures, worker, report, runner, and read-only scenario tests | Passed. |
| Five-profile end-of-order fixture/digest test | Passed for Smoke, Small, Medium, Large, and Probe. |
| `uv run ruff check .` | Passed. |
| `uv run ruff format --check .` | Passed; 119 files already formatted. |
| `uv run pyright` | Passed with 0 errors, 0 warnings, and 0 informations. |
| `uv run pytest -m 'not eval' -q` | Passed. |
| `uv run pytest tests/test_release_metadata.py::test_benchmark_harness_is_not_packaged -q` | Passed after rebuilding wheel and source distribution. |
| Final real `python -m benchmarks run --profiles smoke --correctness-only ...` | Passed with canonical evidence and twelve scenarios. |
| `git diff --check` | Passed before report creation and repeated before commit. |

## Self-review

- Standards axis (`CONTRIBUTING.md` plus the repository smell baseline): no findings.
- Spec axis (the approved performance/capacity design plus the final-review brief): no missing,
  incorrect, or out-of-scope behavior found.
- The profile digest implementation preserves the exact prior semantics: ASCII JSON, sorted keys,
  compact separators, and SHA-256.
- Evidence validation binds each ordered fixture to its paired frozen profile's document count,
  target wiki bytes, source size, and canonical digest; the existing profile/catalog controls
  remain authoritative at runner and matrix boundaries.
- Generator and worker derive the final concept separately. There is no retained `42` constraint
  or index constant, and the ingestion source ceiling remains 100,000 characters.
- Darwin collection reads only a 16-byte filesystem-type field from a fixed 2,168-byte native
  structure, case-folds an allowlisted bounded token, and serializes no path, stdout, environment,
  mount point, or mount source. Linux's bounded subprocess behavior is unchanged.
- The five official wiki targets remain exact, benchmark code remains development-only, and the
  changed Python sources remain below the existing 100 KiB source-file limit.
