# Production-installed lifecycle evidence: BundleWalker 0.4.0rc3

Status: **Passed and inspected**

The supported-platform production-installed lifecycle gate for BundleWalker `0.4.0rc3` ran on
2026-07-24. All four matrix jobs installed exclusively from production PyPI, used the immutable
release, completed the required nine-phase lifecycle, and uploaded bounded sanitized evidence.

## Source and workflow

- Workflow run:
  [production-installed lifecycle run 30098254437](https://github.com/HendrikReh/BundleWalker/actions/runs/30098254437)
- Workflow source: `master` commit `1d38c96d9531a05c99b67b14b0e7d2615045877e`
- Release tag: `v0.4.0rc3`
- Requested and installed package: `bundlewalker==0.4.0rc3`
- Package index: production PyPI
- Supported matrix: macOS 15 and Ubuntu 24.04 with Python 3.13 and 3.14
- Experimental Windows: excluded from this certification matrix

The workflow run completed successfully with exactly the four supported matrix jobs. No local
wheel, source checkout, TestPyPI package, or alternate package index was used to install
BundleWalker.

## Inspected artifacts

Each downloaded artifact contained exactly `evidence.json`, `original-doctor.json`,
`restored-doctor.json`, and `rollback-doctor.json`. The evidence-file digest and byte count below
identify the inspected `evidence.json`; the archive digest and byte count are the values recorded
by that evidence for the verified workspace backup.

| Artifact | Observed environment | Result | Backup archive SHA-256 | Archive bytes | `evidence.json` SHA-256 | Evidence bytes |
| --- | --- | --- | --- | ---: | --- | ---: |
| `production-lifecycle-0.4.0rc3-macos-15-py3.13` | Python 3.13.14; Darwin arm64 | Passed | `93ec0bc7fce9b4a2d9fb6c8609e8cac3115a95833b9155ee0e3145c8666b740a` | 3372 | `99074e4009aa1666da2752be75a3fa1db6772ffb92bd3fd91b47064555e74c7d` | 14584 |
| `production-lifecycle-0.4.0rc3-macos-15-py3.14` | Python 3.14.6; Darwin arm64 | Passed | `aed46653fa0aae9fa73b2698286cc290519553686e8d9f6b800194317fb36fbe` | 3372 | `127e8a34d175f56905769e8b79d56e9dbcc93530cbee5b0601ec50522769fc33` | 14577 |
| `production-lifecycle-0.4.0rc3-ubuntu-24.04-py3.13` | Python 3.13.14; Linux x86_64 | Passed | `ddee5e0252c715b07c468c0359581d0fc92f6c4357d651513c0948f6cd26ab50` | 3372 | `1960ddd88183b2ca9bab5dacfeff8163fa15a2ab7b871fc135a04fb2f8f930a2` | 14583 |
| `production-lifecycle-0.4.0rc3-ubuntu-24.04-py3.14` | Python 3.14.6; Linux x86_64 | Passed | `34b06d86a1f56b7b40fd6ec133c7c538101e714b6eede75d7f7a35318db0e894` | 3369 | `ad802e204676231484fe3c97ea61c5272dd226cb5a75ffa8426f0378f0cfb622` | 14581 |

The original, restored, and rollback workspaces shared the same portable digest in every job:

```text
b903b396e8df3e9bfbecfb24e628e0fe7ab8dafefdaf86a59d1d262b05413b53
```

Archive byte counts and SHA-256 values in `evidence.json` agreed with the backup phase in every
artifact. Archive bytes are environment-specific; the portable workspace digest is the
cross-platform content invariant.

## Accepted lifecycle contract

Inspection confirmed all of the following:

- evidence schema `1`, exact requested and installed version `0.4.0rc3`, overall result `passed`,
  and no failure category;
- all nine recorded phases present in order and passing: `installed_identity`, `initialize`,
  `inspect_original`, `backup`, `restore`, `upgrade_noop`, `rollback`, `mcp`, and
  `final_invariants`;
- identical original, restored, and rollback portable digests;
- a current-format upgrade that remained a no-op, left content unchanged, and created no backup;
- final invariants for archive identity, separate lifecycle targets, doctor-report presence,
  portable workspace identity, upgrade behavior, and exact MCP discovery all true;
- three sanitized doctor reports per environment, each at schema `1` with 12 passes, two expected
  warnings, and zero failures; `mcp.entrypoint` and `workspace.compatibility` passed;
- sanitized executable paths rooted at `$RUN_ROOT`, with no captured environment values,
  credentials, or raw runner temporary paths in the retained artifacts.

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
