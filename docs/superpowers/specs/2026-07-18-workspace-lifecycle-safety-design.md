# BundleWalker Workspace Lifecycle Safety Design

**Date:** 2026-07-18
**Status:** Approved
**Milestone:** Public-beta Milestone B1
**Target:** Workspace compatibility, verified backup and restore, explicit upgrade, and rollback

## Context

BundleWalker now has a verified package and release foundation, supported macOS and Linux CI,
experimental Windows coverage, trusted TestPyPI publishing, and protected release checks. Its
review-first transaction core already provides durable pending reviews, authenticated recovery,
cross-process coordination, and fail-closed mutation behavior.

The next reliability gap spans software versions and whole workspaces. The project does not yet
publish a compatibility policy, preserve fixtures from historical releases, create a portable
verified backup, restore one safely, or expose an explicit upgrade boundary. Users can use Git or
manual copies, but BundleWalker cannot currently prove that those copies are complete or that a
restored workspace matches the source bytes.

This design implements the workspace-lifecycle portion of public-beta Milestone B. Diagnostics,
support reports, benchmarks, and capacity claims remain separate follow-on projects.

## Goals

- Publish exact compatibility rules for durable workspace configuration, transaction journals,
  durable reviews, and permissively read OKF Markdown.
- Preserve representative, immutable workspace fixtures from the `v1`, `v2`, and `v3` releases.
- Create a portable backup only from recovered, quiescent, durable workspace state.
- Verify every archive path, size, and byte digest before accepting a backup or publishing a
  restore.
- Restore only to a new or empty target and leave the source or existing workspace untouched.
- Provide an explicit, forward-only upgrade boundary without inventing an unnecessary workspace
  format change.
- Require a verified pre-upgrade backup before any future migration mutation.
- Rehearse rollback by restoring the pre-upgrade backup to a separate target.
- Run compatibility, archive, restore, and abrupt-termination recovery evidence on every
  officially supported operating-system and Python combination.

## Non-goals

- No workspace format `2` is introduced by this milestone.
- No automatic or implicit migration occurs during discovery or ordinary commands.
- No existing workspace is overwritten by restore or rollback.
- No pending review or internal transaction journal is included in a portable backup.
- No built-in backup encryption or password handling is added.
- No Git operation is performed by BundleWalker.
- No `bundlewalker doctor`, support-report serialization, benchmark harness, MCP host
  certification, production PyPI release, local web UI, hosted service, or multi-user behavior is
  included.

## Selected approach

Use focused lifecycle services behind an application boundary and share the existing workspace
lock with the transaction system. This is preferred over adding more responsibilities to the
2,300-line transaction module or orchestrating recovery and archive creation in the CLI.

The shared lock closes the otherwise unavoidable race between checking transaction state and
reading workspace files. The transaction phase machine remains unchanged.

## Architecture

```text
bundlewalker workspace ...
          |
          v
application/lifecycle.py
          |
          +---------------- compatibility.py
          |
          +---------------- backups.py
          |
          v
transactions.quiescent_workspace(...)
          |
          +-- coordination.workspace_lock(...)
          +-- authenticated transaction recovery
          +-- pending/stale review rejection
          |
          v
bundlewalker.toml + configured conventions/raw/wiki paths
```

### `coordination.py`

Move the existing cross-process workspace-lock implementation from `transactions.py` into a
focused module. The lock continues to use `.bundlewalker/transaction.lock` and keeps the same
symlink, containment, error, and cleanup behavior.

All existing transaction entry points continue to acquire this lock. This is an extraction with
characterization tests, not a locking-policy rewrite.

### `transactions.quiescent_workspace(...)`

Add one public context manager that:

1. acquires the shared workspace lock;
2. creates or validates transaction storage as the existing recovery path requires;
3. runs authenticated recovery for interrupted transactions;
4. detects any remaining pending or stale durable review;
5. raises the existing pending-review failure when unresolved review state remains; and
6. yields a private quiescent-workspace token while retaining the lock.

The token proves to lifecycle internals that transaction recovery and the pending-review check
occurred under the lock. Backup and future upgrade orchestration consume the token instead of
calling transaction-private locked helpers.

An accepted interrupted transaction may finish or roll back through the existing authenticated
recovery rules. A prepared pending or stale review is never silently discarded for backup.

### `compatibility.py`

Own the durable compatibility constants, inspection result, compatibility status, and future
migration-step registry. It performs a read-only version inspection before full workspace
discovery so a too-new workspace can receive a useful error without being interpreted as a
current format.

The inspection statuses are:

- `current`: fully readable and writable by the installed version;
- `upgradeable`: older than current with a complete registered forward path;
- `too_new`: newer than the installed writer and therefore inspection-only; and
- `unsupported`: a well-formed version older than the minimum supported format or missing a
  complete migration path.

Malformed TOML and non-integer versions remain configuration errors rather than compatibility
statuses.

### `backups.py`

Own strict backup-manifest parsing, durable-path collection, archive creation, archive
verification, restore staging, and restore publication. It does not format CLI output and does
not interpret transaction phases.

Archive creation requires a quiescent-workspace token. Restore accepts only an archive and a
target path because it never mutates or relies on a source workspace.

### `application/lifecycle.py`

Expose adapter-safe lifecycle use cases and structured result records for:

- compatibility status;
- verified backup creation;
- verified restore;
- current or future upgrade; and
- pre-upgrade backup identity.

The application layer translates core lifecycle failures into the closed public error vocabulary.
The CLI and a future local UI may format results differently without duplicating compatibility,
archive, or migration rules.

### `interfaces/cli.py`

Add the `workspace` command group. The root callback skips automatic workspace discovery for this
group because `restore` must work when no workspace exists. Each lifecycle command performs only
the discovery required by its use case.

Existing `init`, `ingest`, `ask`, `lint`, and `review` behavior does not change.

## Compatibility policy

Durable workspace compatibility and temporary transaction compatibility are versioned
independently.

| Artifact | Current producer | Supported historical behavior |
| --- | --- | --- |
| `bundlewalker.toml` | Workspace format `1` | Format `1` is readable, writable, backup-capable, and restorable |
| Transaction manifest | Schema `2` | Schema `1` can be authenticated and recovered where its phase permits, but cannot continue as a durable pending review |
| Durable review record | Schema `1` | Schema `1` remains readable with its authenticated identity digest |
| OKF Markdown | Current bounded producer | The existing permissive reader preserves representable unknown metadata and non-empty unknown concept types |

### Workspace format 1 remains current

Every historical `v1`, `v2`, and `v3` release wrote `version = 1` in `bundlewalker.toml`. This
milestone therefore keeps workspace format `1` as the sole current readable and writable format.
Adding a synthetic field only to demonstrate migration would create user churn without a product
requirement.

Normal application commands require the complete current-format configuration contract. A
workspace whose declared version is greater than `1` is inspection-only: ordinary reads, writes,
backups, and upgrades refuse it and instruct the user to use a BundleWalker version that supports
that format. BundleWalker cannot safely back up a too-new configuration because it cannot know
which paths that format manages.

Versions below `1`, absent versions, malformed configuration, and unsafe configured paths are
rejected without mutation.

### Transaction and review compatibility

Transaction manifest schema `2` and durable review schema `1` remain the current internal
formats. Historical schema-1 transaction states are never upgraded in place merely to make them
look current:

- a schema-1 prepared proposal may be cleaned because it was never durably accepted;
- an interrupted schema-1 commit is recovered or rolled back using its authenticated topology;
  and
- a schema-1 proposal cannot be presented as a current durable pending review because it has no
  authenticated review record.

The compatibility policy documents internal transaction state for recovery expectations, but
portable backups exclude `.bundlewalker/` entirely.

### No implicit migration

Discovery, status, backup, restore, lint, query, and mutation commands never rewrite the workspace
format. Migration is available only through an explicit `bundlewalker workspace upgrade`
invocation.

## Historical fixtures

Commit immutable fixture directories under `tests/fixtures/historical/`:

- a clean durable workspace produced by `v1`;
- a clean durable workspace produced by `v2`;
- a clean durable workspace produced by `v3`;
- representative schema-1 interrupted transaction states from `v1`;
- a schema-2 durable pending review from `v2` or `v3`;
- malformed configuration;
- workspace format `0`; and
- a future workspace format greater than `1`.

Each released fixture includes provenance containing the source tag, source commit, package
version, workspace format, transaction/review schema when applicable, and expected compatibility
behavior. Provenance is test metadata outside the copied workspace and is not interpreted as a
runtime workspace file.

Historical fixtures are generated once with their release code, reviewed, and committed as
static bytes. Current tests copy them to temporary directories; they never regenerate them using
current initialization logic.

Tests cover read-only inspection, supported normal reads, current backup and restore, historical
transaction recovery, and clear rejection. Because all released durable workspaces use format
`1`, no historical fixture requires a durable workspace migration in this milestone.

## Portable backup contract

### Durable scope

A portable backup contains exactly:

- `bundlewalker.toml`;
- the configured conventions file;
- the configured raw directory and all descendants; and
- the configured wiki directory and all descendants.

Configured paths are normalized, contained within the workspace, and de-duplicated when they
overlap. A managed path equal to or below the reserved `.bundlewalker/` internal directory is
rejected. Files elsewhere in the workspace, including `.git/`, editor files, unrelated notes,
and prior backup archives, are outside the managed backup contract.

`.bundlewalker/` is always excluded. Backup creation first performs authenticated recovery and
then refuses every remaining pending or stale review. The archive therefore represents accepted,
quiescent durable state rather than a resumable private proposal.

### ZIP layout

```text
bundlewalker-backup.json
workspace/bundlewalker.toml
workspace/<configured conventions file>
workspace/<configured raw directory>/...
workspace/<configured wiki directory>/...
```

Payload entries always live below `workspace/`, preventing a workspace filename from colliding
with the archive manifest.

The archive uses UTF-8 ZIP names, DEFLATE compression for regular files, and ZIP64 when required
by a legitimate large file or archive. Compression changes storage size only; uncompressed byte
size and SHA-256 define file identity.

The strict JSON manifest contains exactly:

- `archive_format`: the literal `bundlewalker-workspace-backup`;
- `schema_version`: integer `1`;
- `created_at`: an RFC 3339 UTC timestamp;
- `bundlewalker_version`: the installed package version;
- `workspace_format_version`: integer `1`;
- `directories`: sorted canonical POSIX paths relative to the workspace root; and
- `files`: sorted records with canonical relative `path`, non-negative byte `size`, and lowercase
  64-character `sha256`.

Directories are explicit so an empty configured raw directory survives restore. Duplicate paths,
overlapping file/directory identities, unknown manifest fields, unsafe paths, and non-canonical
path spellings are invalid.

Defensive parser ceilings are not capacity claims: the manifest is limited to 32 MiB, the combined
file-and-directory count to 100,000, and each relative path to 4,096 Unicode characters. Restore
stops streaming an entry as soon as it exceeds its declared size rather than trusting a ZIP size
field and discovering the mismatch only after decompression.

The archive itself is not self-hashed inside its manifest. The application result and CLI print
the SHA-256 digest of the completed ZIP so users can record or compare the exact artifact.

### Encryption and permissions

The archive is not encrypted. It may contain exact private, licensed, regulated, or secret raw
source bytes. Documentation warns users to keep it on appropriately encrypted storage or apply an
external encryption workflow.

BundleWalker creates temporary and final archives with owner-only permissions where the platform
supports POSIX modes. Restore does not promise to reproduce original permission bits, ownership,
extended attributes, access-control lists, or timestamps. Restored directories and files are
created privately and become subject to the destination platform and process umask after
publication. File bytes and relative paths are the portable contract.

## Backup creation flow

`bundlewalker workspace backup OUTPUT [--workspace PATH]` performs these steps:

1. Discover the selected workspace and require current workspace format `1`.
2. Require `OUTPUT` to be outside the workspace and absent. Existing output is never overwritten.
3. Enter `quiescent_workspace(...)`, retaining the lock for the complete snapshot read.
4. Enumerate the managed durable scope without following symlinks.
5. Reject symlinks, sockets, devices, FIFOs, and every non-regular file or non-directory entry.
6. Open files with no-follow behavior where available, stream their bytes, and compare file
   identity, size, and modification metadata before and after the read.
7. Abort if any file changes, disappears, is replaced, or resolves outside the workspace.
8. Conservatively require the archive destination filesystem to report at least the total source
   byte count as free space when the check is available.
9. Write a temporary sibling ZIP with canonical members and the strict manifest.
10. Close and re-open the ZIP through the production archive verifier.
11. Sync the temporary file, atomically publish it as `OUTPUT`, and sync the parent directory where
    supported.
12. Return the final path, archive SHA-256, creation timestamp, workspace format, file count, and
    uncompressed byte count.

The BundleWalker lock prevents application mutations. Descriptor identity and metadata checks
detect ordinary replacement, truncation, append, disappearance, and concurrent-edit races from
actors that do not honor the lock. Every observed race fails closed. Portable filesystems cannot
exclude a deliberately evasive same-inode writer that restores metadata between checks; the
portable guarantee is therefore exact recoverability of the captured and verified bytes, while
single-instant snapshot consistency requires all writers to honor BundleWalker's lock.

Every failure removes only BundleWalker-owned temporary archive files. It leaves the workspace and
pre-existing filesystem entries unchanged.

## Archive verification

The same verifier is used after backup creation and before restore. It validates before accepting
payload bytes:

- one and only one manifest;
- recognized archive magic and schema;
- no duplicate ZIP member names;
- no encrypted entries;
- no symlink or special-file external attributes;
- no absolute path, drive prefix, backslash, NUL, empty segment, `.` segment, or `..` segment;
- every payload member below `workspace/`;
- an exact match between ZIP members and manifest directories/files;
- canonical sorted manifest paths without duplicates;
- a required `bundlewalker.toml` payload;
- matching declared and actual uncompressed sizes;
- matching streamed SHA-256 digests;
- a current supported workspace format; and
- a managed payload set that agrees with the configuration paths contained in the archive.

Verification streams payloads and never trusts compressed size or CRC as content identity. Before
extraction, restore compares the manifest's total declared file bytes with reported free space on
the destination filesystem. A smaller reported free-space value causes refusal; ordinary I/O
errors still fail closed if the filesystem fills despite preflight.

Verification proves archive structure and byte identity. It does not reject an otherwise valid
backup merely because manually edited OKF content has deterministic lint findings. Data
preservation and knowledge health are separate signals.

## Restore flow

`bundlewalker workspace restore ARCHIVE TARGET` works without a current workspace:

1. Require `TARGET` to be absent or an existing empty, non-symlink directory.
2. Verify the complete archive and destination-space preflight before publishing any target data.
3. Create a private temporary sibling directory owned by the restore operation.
4. Create declared directories and stream each file to a new exclusive no-follow destination while
   recomputing byte count and SHA-256.
5. Re-verify the extracted member set and digests from the temporary tree.
6. Discover the temporary workspace with the current configuration reader.
7. Confirm that the discovered workspace version and configured managed paths match the manifest.
8. If `TARGET` existed empty, confirm it is still empty and remove only that empty directory.
9. Atomically rename the verified temporary workspace to `TARGET`.
10. Sync the target parent where supported and return the restored path, archive SHA-256, workspace
    format, file count, and byte count.

If a concurrent actor makes an existing empty target non-empty, publication refuses and preserves
that target. If publication fails after removing an originally empty target, BundleWalker
recreates the empty directory before reporting failure when possible.

Any failure before publication removes the owned temporary tree. Restore never alters another
workspace and never follows archive-provided links.

## Upgrade and migration contract

### Current behavior

`bundlewalker workspace upgrade [PATH] [--backup-dir DIRECTORY]` reports that workspace format `1`
is already current. It creates no backup because no mutation is planned.

A format below the current version is `upgradeable` only when a complete, contiguous sequence of
registered forward steps reaches the current version. A too-new or incomplete path is refused
without mutation.

### Future migration steps

The migration service defines a focused step interface with:

- one exact source version;
- one exact target version greater than the source;
- an apply operation;
- a post-step verifier; and
- migration-specific interruption and recovery tests.

Production has no migration steps in this milestone. Unit tests inject a synthetic registry to
exercise orchestration without claiming that workspace format `0` is supported or creating a
meaningless format `2`.

Before the first future mutation, upgrade:

1. enters the quiescent-workspace guard;
2. creates and re-verifies a uniquely named backup outside the workspace;
3. aborts if the backup cannot be created or verified;
4. applies each registered step in order while retaining the workspace lock;
5. verifies the declared version and step-specific invariants after every step; and
6. reports the backup path and digest even when a later migration step fails.

Adding the first real migration requires a separate reviewed design for that format change and its
recoverable mutation mechanism. The presence of a backup does not authorize an unsafe in-place
rewrite.

## Rollback contract

Rollback is explicit and non-destructive:

1. identify the verified pre-upgrade archive;
2. restore it to a separate new or empty path;
3. run `bundlewalker workspace status` in the restored workspace;
4. run deterministic `bundlewalker lint`;
5. inspect the result and explicitly switch consumers to the restored path; and
6. retain the original workspace until the user accepts the rollback.

BundleWalker does not rename, delete, or overwrite the original workspace and does not perform Git
operations.

## CLI contract

```text
bundlewalker workspace status [PATH]
bundlewalker workspace backup OUTPUT [--workspace PATH]
bundlewalker workspace restore ARCHIVE TARGET
bundlewalker workspace upgrade [PATH] [--backup-dir DIRECTORY]
```

### `workspace status`

- Defaults `PATH` to the current directory and walks upward using normal workspace discovery.
- Is read-only: it does not create `.bundlewalker/`, acquire a mutation lock, or run recovery.
- Prints the installed BundleWalker version, detected workspace format, compatibility status,
  readable/writable decisions, and whether an upgrade path exists.
- Can report a too-new version without interpreting its unknown configuration keys as current
  settings.

### `workspace backup`

- Defaults `--workspace` to discovery from the current directory.
- Requires an explicit output archive path.
- Prints the verified archive path, SHA-256, workspace format, file count, and byte count.
- Uses the existing pending-review remediation when a durable review blocks the snapshot.

### `workspace restore`

- Requires the archive and target paths explicitly.
- Does not require discovery of a current workspace.
- Prints the verified restored target, source archive SHA-256, workspace format, file count, and
  byte count.

### `workspace upgrade`

- Defaults `PATH` to the current workspace.
- Prints an exact no-op result for current format `1`.
- Uses `--backup-dir` only when a real migration is available; otherwise it performs no I/O there.
- Reports the verified pre-upgrade backup identity before reporting a later migration failure.

## Error model

Extend the stable application error vocabulary with:

- `workspace_incompatible`;
- `backup_invalid`;
- `backup_failed`;
- `restore_target_invalid`;
- `migration_unavailable`; and
- `migration_failed`.

An unresolved review continues to use `review_pending` and its existing review commands.

Invalid arguments, invalid restore targets, incompatible configuration, and unavailable migration
paths exit `2`. Archive verification, backup I/O, restore I/O, migration execution, transaction,
and post-upgrade verification failures exit `1`.

Safe user messages include the next action and may identify a relative managed path, archive path,
or user-supplied target. They never include file contents, credentials, raw source excerpts, or
provider values.

## Privacy and security

- Backups remain local and are never uploaded automatically.
- No telemetry, remote crash reporting, or diagnostic submission is introduced.
- The archive contains no provider credentials because BundleWalker credentials remain in the
  process environment rather than the workspace configuration.
- The archive may contain sensitive raw source content and is explicitly labeled unencrypted.
- Archive extraction uses strict allowlisting rather than sanitizing unsafe names.
- ZIP CRC values are not treated as cryptographic identity; SHA-256 is mandatory for every file.
- Restore never extracts directly into the final target.
- Backup never follows workspace links or copies transaction-private state.
- Observable manual concurrent filesystem changes fail backup creation. The documentation states
  that external writers must be stopped to obtain the same single-instant consistency guarantee
  provided between BundleWalker processes.

## Testing strategy

### Compatibility tests

- Inspect current format `1` without mutation.
- Reject malformed, missing, non-integer, zero, negative, and future versions with the correct
  status or configuration error.
- Prove that `v1`, `v2`, and `v3` durable fixtures remain discoverable and readable.
- Prove current writing still emits workspace format `1`, transaction schema `2`, and review schema
  `1`.
- Recover supported historical schema-1 transaction states.
- Preserve schema-2 pending review identity and refuse backup until it is resolved.

### Backup tests

- Back up each historical durable fixture and a current custom-path workspace.
- Preserve empty configured directories and exact file bytes.
- Exclude `.bundlewalker/`, `.git/`, unrelated files, and prior archives.
- Reject an output inside the workspace or an existing output.
- Reject configured paths overlapping `.bundlewalker/`.
- Reject symlinks and every non-regular managed entry.
- Detect replacement, truncation, append, metadata change, and disappearance during streaming.
- Inject failures before ZIP creation, during file streaming, before verification, and before
  publication; assert no final archive and no workspace mutation.

### Archive-adversary tests

- Reject duplicate names, encrypted members, symlink attributes, special-file attributes,
  unexpected members, unsafe path forms, missing manifest, duplicate manifest, unknown fields,
  malformed JSON, unsupported schema, non-canonical paths, duplicate manifest paths, size
  mismatch, digest mismatch, configuration/manifest mismatch, and insufficient reported space.
- Confirm verification streams uncompressed bytes and does not trust CRC or compressed size.

### Restore tests

- Restore to absent and existing empty targets.
- Refuse files, symlinks, and non-empty target directories.
- Compare every restored managed file byte-for-byte with the source fixture.
- Preserve empty configured directories.
- Discover, inspect, lint, and perform supported read operations in the restored workspace.
- Inject failures during extraction, extracted-tree verification, discovery, and publication;
  assert cleanup and target preservation.
- Simulate a concurrent writer populating an initially empty target and verify fail-closed
  publication.

### Upgrade and rollback tests

- Confirm current format `1` upgrade is a no-op and creates no backup.
- Confirm too-new and incomplete paths refuse without mutation.
- Inject a synthetic contiguous migration registry and prove the verified backup completes before
  the first mutation.
- Inject a migration failure and prove the pre-upgrade archive remains verifiable and restorable
  to a separate target.
- Rehearse status and deterministic lint on the restored rollback workspace.

### Abrupt-termination recovery tests

Use subprocesses that terminate with `os._exit(...)` after durable transaction phase boundaries.
The parent process then invokes authenticated recovery and compares accepted raw and wiki bytes,
the preserved live workspace after rollback, journal cleanup/retention, and idempotent second
recovery.

These tests run in the full supported matrix:

- Ubuntu 24.04 with Python 3.13 and 3.14; and
- macOS 15 with Python 3.13 and 3.14.

Windows remains visible and experimental.

## Documentation

Create `docs/workspace-compatibility.md` as the authoritative public policy. Update:

- `README.md` with lifecycle commands and a policy link;
- `docs/user-guide.md` with backup, restore, upgrade, and rollback procedures;
- `docs/tutorial.md` with a short verified backup/restore exercise;
- `docs/maintainers/releases.md` with post-upgrade and rollback evidence; and
- command help and expected exit codes.

Documentation states that archives are unencrypted, may contain exact raw source bytes, exclude
pending reviews, do not include unrelated workspace-root files, and never replace an existing
workspace.

## B1 exit criteria

Workspace lifecycle safety is complete only when all of the following are fresh evidence:

1. The compatibility and migration policy is public and linked from primary documentation.
2. Static `v1`, `v2`, and `v3` fixtures pass their documented compatibility behavior.
3. Current backups are quiescent, verified, portable ZIPs that exclude internal transaction state.
4. Restore verifies before publication and preserves every managed file byte-for-byte.
5. Current-format upgrade is an exact no-op, while unavailable paths refuse without mutation.
6. Synthetic migration tests prove backup-before-mutation and restorable rollback evidence.
7. Abrupt-termination recovery tests pass across all transaction phase boundaries.
8. The supported macOS/Linux Python 3.13/3.14 CI matrix is green.
9. No known critical or high-severity data-loss, workspace-corruption, credential-exposure, or
   review-bypass defect remains in this scope.

Passing B1 does not complete all of Milestone B. Diagnostics/support reports and the performance
baseline/capacity envelope remain separate B2 and B3 plans.
