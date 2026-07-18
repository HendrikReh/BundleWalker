# Workspace Compatibility and Portable Backups

This document is the authoritative policy for BundleWalker workspace compatibility, portable
backup and restore, explicit upgrade, and rollback. The [user guide](user-guide.md) turns this
policy into task-oriented procedures; command `--help` remains authoritative for CLI spelling.

## Supported artifacts

Durable workspace data and temporary transaction data are versioned independently.

| Artifact | Current producer | Supported behavior |
| --- | --- | --- |
| `bundlewalker.toml` | Workspace format `1` | Format `1` is readable, writable, backup-capable, and restorable. It is the only supported workspace format. |
| Transaction manifest | Schema `2` | Authenticated schema-1 transaction states can be recovered where their phase permits, but a schema-1 proposal cannot continue as a durable pending review. |
| Durable review record | Schema `1` | Schema `1` remains readable with its authenticated identity digest. |
| OKF Markdown | Current bounded producer | Reads are permissive but bounded: representable unknown metadata and non-empty unknown concept types are preserved. |

Every released `v1`, `v2`, and `v3` durable workspace used workspace format `1`. Portable backups
exclude transaction manifests and durable review records because `.bundlewalker/` is temporary,
private coordination state.

## Compatibility status

`bundlewalker workspace status [PATH]` is a read-only inspection. It reports one of:

| Status | Meaning |
| --- | --- |
| `current` | The declared workspace format equals the current format. The complete current configuration is valid, and the workspace is readable and writable. |
| `upgradeable` | The format is older and a complete registered forward migration path reaches the current format. Production currently registers no migrations. |
| `too_new` | The declared format is newer than this BundleWalker version. Status can inspect it, but normal reads, writes, backups, and upgrades refuse it. |
| `unsupported` | The format is below the supported minimum or has no complete registered migration path. |

Malformed TOML, a missing or non-integer version, and unsafe current-format configuration are
configuration errors, not compatibility statuses. Inspection does not create `.bundlewalker/`,
run recovery, or mutate the workspace.

## No implicit migration

Discovery, status, backup, restore, lint, query, and mutation commands never migrate a workspace.
Only an explicit `bundlewalker workspace upgrade` invocation may run a registered migration.
Production currently registers none, so workspace format `1` is current and upgrade is an exact
no-op that creates no backup. A future format and its recoverable migration require a separate
reviewed design.

## Backup scope and privacy

A portable backup contains exactly:

- `bundlewalker.toml`;
- the configured conventions file;
- the configured raw directory and every descendant; and
- the configured wiki directory and every descendant.

Empty configured directories are preserved. `.bundlewalker/`, `.git/`, unrelated workspace-root
files, editor files, and existing or prior backup archives are excluded. Backup refuses configured
paths that overlap `.bundlewalker/`, never follows links, first performs authenticated recovery,
and refuses to proceed while a pending review or stale review remains. The archive therefore
captures accepted, quiescent durable state, not a private proposal.

The ZIP archive is **unencrypted** and may contain exact raw source bytes, including private,
licensed, regulated, or secret material. Keep it at an encrypted destination or protect it with
an external encryption tool. BundleWalker keeps backups local and does not upload them
automatically; provider credentials are process environment values and are not workspace files.

Each file record in the archive manifest includes its uncompressed byte size and SHA-256. The CLI
also prints the SHA-256 of the completed ZIP. ZIP CRC and compressed size are not treated as file
identity.

## Back up a workspace

Before taking a backup:

1. Inspect any pending review with `bundlewalker review show`, then apply or discard it explicitly.
2. Stop editors, synchronizers, and other external writers. BundleWalker coordinates its own
   processes; observable changes by other writers make the backup fail closed.
3. Choose an absent output path outside the workspace. Existing output is never overwritten.
4. Run the backup and record the printed archive SHA-256 with the artifact.

From the BundleWalker checkout:

```bash
mkdir -p ./backups
uv run bundlewalker workspace status ./knowledge
uv run bundlewalker workspace backup ./backups/knowledge.zip --workspace ./knowledge
```

Backup requires current workspace format `1`. It holds the workspace lock for the snapshot,
streams the managed files, verifies the completed archive through the production verifier, and
only then publishes the requested output.

## Restore and verify a backup

Restore does not require a current workspace. It verifies the complete archive before publishing
data and accepts only a new or empty target directory. It never replaces a file, symlink,
non-empty directory, or existing workspace.

```bash
uv run bundlewalker workspace restore ./backups/knowledge.zip ./knowledge-restored
uv run bundlewalker workspace status ./knowledge-restored
(
  cd ./knowledge-restored
  uv run --project .. bundlewalker lint
)
```

Use the BundleWalker checkout path in place of `..` when the restored target is elsewhere. Compare
the restore command's printed SHA-256 with the digest recorded at backup time. Deterministic lint
is a separate health signal: archive verification preserves exact managed bytes even if manually
edited OKF content has lint findings.

## Upgrade and rollback

Check the workspace before requesting an upgrade:

```bash
uv run bundlewalker workspace status ./knowledge
uv run bundlewalker workspace upgrade ./knowledge --backup-dir ./backups
```

For current format `1`, upgrade reports that the format is already current and performs no I/O in
the backup directory. A future registered migration must create and re-verify a pre-upgrade backup
outside the workspace before its first mutation, retain the workspace lock through every step,
and report the backup path and SHA-256 if later migration execution fails.

Rollback is explicit and non-destructive. Never restore over the upgraded or failed workspace:

```bash
uv run bundlewalker workspace restore ./backups/knowledge.zip ./knowledge-restored
uv run bundlewalker workspace status ./knowledge-restored
(
  cd ./knowledge-restored
  uv run --project .. bundlewalker lint
)
```

Inspect the restored compatibility status and deterministic lint result, then switch consumers to
`./knowledge-restored` only after accepting it. Retain the original workspace until the rollback
is accepted. BundleWalker never renames, deletes, or overwrites that original workspace and never
performs Git operations.

## Complete lifecycle CLI contract

```text
bundlewalker workspace status [PATH]
bundlewalker workspace backup OUTPUT [--workspace PATH]
bundlewalker workspace restore ARCHIVE TARGET
bundlewalker workspace upgrade [PATH] [--backup-dir DIRECTORY]
```

`status` and `upgrade` default to normal workspace discovery. `backup` also defaults to discovery
when `--workspace` is omitted. `restore` always requires both paths and works when no current
workspace exists.

## Exit codes

| Code | Lifecycle meaning |
| --- | --- |
| `0` | The lifecycle operation completed successfully, including a current-format upgrade no-op. |
| `2` | Input, incompatible-target, incompatible-configuration, or unavailable-migration-path error. This includes an invalid restore target. |
| `1` | Archive verification, backup I/O, restore I/O, migration execution, transaction, or post-upgrade verification failure. |

A pending review that blocks backup is a transaction failure and exits `1`; resolve it with the
printed review commands before retrying.

## Portability boundary

Portable restore preserves the exact canonical relative paths, explicit empty managed
directories, and exact file bytes recorded by the manifest. It does not preserve or promise
original permission modes, ownership, access-control lists (ACLs), extended attributes (xattrs),
or timestamps. Destination-platform filesystem rules and the restoring process's umask apply
after publication.
