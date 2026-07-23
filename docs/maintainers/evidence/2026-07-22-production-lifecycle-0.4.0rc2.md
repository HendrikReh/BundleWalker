# Production-installed lifecycle evidence: BundleWalker 0.4.0rc2

Status: **Passed and independently inspected**

The supported-platform production-installed lifecycle gate for BundleWalker `0.4.0rc2` was
observed on 2026-07-23. All four matrix jobs installed the immutable release from production PyPI,
completed the required nine-phase lifecycle, and uploaded bounded sanitized evidence.

## Source and workflow

- Workflow run:
  [production-installed lifecycle run 30024736071](https://github.com/HendrikReh/BundleWalker/actions/runs/30024736071)
- Workflow source: `master` commit `5fe237800c18d334720ac63a361b22946a427940`
- Requested and installed package: `bundlewalker==0.4.0rc2`
- Package index: production PyPI
- Supported matrix: macOS 15 and Ubuntu 24.04 with Python 3.13 and 3.14
- Experimental Windows: excluded from this certification matrix

The first dispatch, run `30017021861`, exposed a workflow-only PATH defect after a successful
production installation. Pull request 17 fixed the workflow's PATH boundary without changing the
Python harness or already-published package. The passing run above exercised the same immutable
`0.4.0rc2` release.

## Inspected artifacts

Each downloaded artifact contained exactly `evidence.json`, `original-doctor.json`,
`restored-doctor.json`, and `rollback-doctor.json`.

| Artifact | Observed environment | Result | Backup archive SHA-256 | Bytes |
| --- | --- | --- | --- | ---: |
| `production-lifecycle-0.4.0rc2-macos-15-py3.13` | Python 3.13.14; Darwin arm64 | Pass | `33f6964967b754658a2641dd8f4da349242204990188e6e95d4a9d3d01154118` | 3375 |
| `production-lifecycle-0.4.0rc2-macos-15-py3.14` | Python 3.14.6; Darwin arm64 | Pass | `6055b00c5bcf99ce2d047dd48599c46d68111166a542515e35909c4ff5d55115` | 3376 |
| `production-lifecycle-0.4.0rc2-ubuntu-24.04-py3.13` | Python 3.13.14; Linux x86_64 | Pass | `84c4462d9af4d9dfa94d7357622f667ca6ae519e061c31bae0c692845629dbf8` | 3376 |
| `production-lifecycle-0.4.0rc2-ubuntu-24.04-py3.14` | Python 3.14.6; Linux x86_64 | Pass | `a86986ccf880c2a4ce8c21f31a68d9dc3e5f64799ac8a8837cdf5ca5386b1387` | 3376 |

The original, restored, and rollback workspaces shared the same portable digest in every job:

```text
c0c7ea79107c51015b99793994a603c25542c016ca84d53a363ffe48820f7e4b
```

Archive byte counts and SHA-256 values in `evidence.json` agreed with the backup phase in every
artifact. Archive bytes are environment-specific; the portable workspace digest is the
cross-platform content invariant.

## Accepted lifecycle contract

Independent inspection confirmed all of the following:

- evidence schema `1`, exact requested and installed version `0.4.0rc2`, overall result `passed`,
  and no failure category;
- all nine recorded phases present in order and passing: `installed_identity`, `initialize`,
  `inspect_original`, `backup`, `restore`, `upgrade_noop`, `rollback`, `mcp`, and
  `final_invariants`;
- identical original, restored, and rollback portable digests;
- a current-format upgrade that remained a no-op, left content unchanged, and created no backup;
- final invariants for original preservation, separate targets, archive agreement, restore,
  rollback, upgrade behavior, doctor results, and MCP discovery all true;
- three sanitized doctor reports per environment, each at schema `1` with 12 passes, two expected
  warnings, and zero failures; `mcp.entrypoint` and `workspace.compatibility` passed;
- sanitized executable paths rooted at `$RUN_ROOT`, with no captured environment values or raw
  runner temporary paths in the retained artifacts.

The two doctor warnings reflect the intentionally absent model selection and provider credential.
They do not affect this offline lifecycle and installed-entry-point gate.

## Installed MCP surface

The production-installed `bundlewalker-mcp` entry point initialized successfully and exposed
exactly these ten tools in every supported matrix job:

- `apply_review`
- `ask`
- `discard_review`
- `get_pending_review`
- `lint`
- `prepare_ingestion`
- `prepare_refresh`
- `prepare_synthesis`
- `search_concepts`
- `workspace_status`

This is package-level evidence for installed local `stdio` server initialization and tool
discovery. It does not certify a particular MCP host, execute provider-backed model calls, broaden
the existing VS Code/Copilot certification, or claim supported Windows behavior.
