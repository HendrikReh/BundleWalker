# TestPyPI Propagation Retry Design

## Context

BundleWalker's `0.4.0a2` trusted-publisher workflow built and uploaded valid wheel and source
distribution artifacts. The upload job succeeded, but the immediately dependent verification job
attempted to resolve `bundlewalker==0.4.0a2` from TestPyPI seven seconds later and received “no
version” from the simple index. The immutable version became visible shortly afterward, and the
same install verification then passed.

This was a TestPyPI index-propagation race, not a build, metadata, authentication, or package
runtime failure.

## Goals

- Tolerate a bounded TestPyPI simple-index propagation delay after a successful upload.
- Verify the exact published version using the same `uv pip install` operation users rely on.
- Preserve a hard failure when the version never becomes installable.
- Make retries visible in Actions logs and keep their maximum duration predictable.
- Document safe recovery without implying that immutable artifacts may be rebuilt or republished.

## Non-goals

- Do not retry the build or trusted-publisher upload inside the workflow.
- Do not add `continue-on-error`, suppress a permanent resolution failure, or weaken version and
  CLI smoke checks.
- Do not rerun the `0.4.0a2` publication workflow as part of this change.
- Do not publish to production PyPI or create another package version.
- Do not introduce a general-purpose retry framework or an external retry action.

## Considered Approaches

### Retry the exact install operation — selected

Run the TestPyPI-only `uv pip install` operation at most six times. After the first five failures,
wait 5, 10, 20, 40, and 80 seconds respectively. Stop immediately when installation succeeds and
fail after the sixth unsuccessful attempt.

This checks the real success condition: whether the resolver can install the exact published
version from TestPyPI. The worst-case added wait is bounded at 155 seconds.

### Poll the TestPyPI simple-index HTML

Polling the package's simple-index page would reduce repeated resolver output, but it would test
an HTTP representation rather than the actual install operation. HTML matching also adds filename
normalization and caching assumptions that the resolver already handles.

### Add one fixed delay

A fixed sleep is minimal but either remains flaky when propagation exceeds the chosen delay or
slows every successful publication unnecessarily. It does not expose progressive retry evidence.

## Workflow Design

The existing verify job continues to:

1. download the exact artifact produced by the build job;
2. create a Python 3.13 virtual environment;
3. install the workflow wheel and uninstall it, proving the artifact itself is installable;
4. install the exact requested version from TestPyPI without dependencies;
5. compare installed distribution metadata with the workflow input; and
6. run `bundlewalker --help` and `bundlewalker-mcp --help`.

Only step 4 gains retry behavior. A Bash loop runs attempts `1` through `6`. Each failure before
the last attempt emits a GitHub Actions notice containing the attempt number and delay, sleeps for
the corresponding exponential interval, and retries. A successful install breaks the loop. The
sixth failure exits nonzero immediately without another sleep.

The retry block remains inside the existing `Install and smoke-test published prerelease` step so
the downloaded artifact, virtual environment, version input, and subsequent smoke tests stay in
one auditable verification boundary.

## Failure Semantics

- Build, audit, metadata, upload, downloaded-artifact install, installed-version comparison, and
  CLI smoke failures remain immediate and non-retryable.
- Only TestPyPI resolution of the exact immutable version is retried.
- The loop performs no more than six installation attempts and waits no more than 155 seconds.
- The final failed attempt exits nonzero, preserving the workflow as a release gate.
- A successful upload must never be corrected by rebuilding or overwriting the same version.
- If upload succeeded but verification raced propagation, maintainers may rerun only the failed
  verification job after confirming the version is present on TestPyPI. They must not rerun build
  or publication for that immutable version.

## Tests

Extend `tests/test_project_automation.py` before editing the workflow. The focused automation test
must fail against the current immediate-install workflow and then prove that the YAML contains:

- exactly six bounded attempts;
- exponential delays of 5, 10, 20, 40, and 80 seconds;
- retry around the exact `uv pip install` TestPyPI command;
- an immediate break on success;
- a nonzero exit on the sixth failure; and
- no `continue-on-error` weakening of the verify job or step.

After the focused red-green cycle, run the complete non-evaluation suite, Ruff formatting and
lint, Pyright, lockfile verification, and `git diff --check`. The pull-request CI remains the
supported macOS/Linux and packaging integration gate. The TestPyPI publishing workflow itself is
not dispatched because `0.4.0a2` is immutable and already published.

## Documentation

Update `docs/maintainers/releases.md` to describe the bounded propagation retry and the safe
recovery distinction between a failed upload and a failed post-upload verification. Add an
`Unreleased` changelog entry for the workflow hardening; do not alter the historical
`v0.4.0a2` release entry.

## Rollout

Land the workflow, focused automation test, maintainer documentation, changelog entry, design,
and implementation plan through a protected-branch pull request. Required CI must pass before
merge. No tag, TestPyPI publication, GitHub release, or production PyPI action belongs to this
change.
