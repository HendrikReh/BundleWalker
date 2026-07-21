# Build a Personal Knowledge Workbook

This tutorial follows one personal workbook from an empty directory to accepted source knowledge,
a saved and refreshed Synthesis, and a verified backup. Run the commands in order from the root
of a BundleWalker checkout and keep them in one shell session.

## What you will build

You will create a workspace with the `personal-workbook` preset, ingest a cautious observation,
ask a cited question, save its answer as a reviewed Synthesis, add a limited comparison as newer
evidence, and refresh the same Synthesis. You will then check the workspace and restore a backup
to a separate target.

The journey never depends on a model-generated title, filename, slug, or exact prose. It checks
only durable outcomes that BundleWalker controls.

## Prerequisites

You need Python 3.13 or 3.14, [`uv`](https://docs.astral.sh/uv/), a PydanticAI model string, and
the provider credential required by that model. The
[model and provider setup guide](user-guide.md#model-and-provider-setup) explains provider-specific
configuration.

The `ingest` and `ask` commands below use the configured model. They can use the network and incur
provider cost. `init`, deterministic `lint`, `doctor`, backup, and restore are local and do not
call a model. Never commit a provider credential or place it in a source note.

## 1. Prepare BundleWalker and your model

Install the locked dependencies, declare the checkout and tutorial paths once, and fill in the two
placeholders. Replace `PROVIDER_API_KEY` with the environment-variable name required by your
provider.

```bash
uv sync --locked
PROJECT_ROOT="$(pwd -P)"
TUTORIAL_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/bundlewalker-tutorial.XXXXXX")"
WORKSPACE_PATH="$TUTORIAL_ROOT/knowledge"
RESTORE_PATH="$TUTORIAL_ROOT/knowledge-restored"
BACKUP_DIR="$TUTORIAL_ROOT/backups"
BACKUP_PATH="$BACKUP_DIR/knowledge.zip"
export BUNDLEWALKER_MODEL='<pydantic-ai-model-string>'
export PROVIDER_API_KEY='<provider-credential>'
printf 'Tutorial root: %s\nWorkspace: %s\n' "$TUTORIAL_ROOT" "$WORKSPACE_PATH"
```

The temporary root is unique for this run. Keep its printed path until the cleanup step.

## 2. Create the source notes

Create two notes outside the workspace. Ingestion will preserve each accepted source's exact bytes
under `raw/`.

```bash
cat > "$TUTORIAL_ROOT/initial-notes.md" <<'EOF'
Review-first knowledge workflow

A review gate separates a model proposal from durable knowledge. A declined proposal leaves the
knowledge base unchanged. Accepted source bytes remain immutable, while the compiled wiki may be
refined as new evidence arrives.

This note is a working observation, not a controlled comparison. It does not establish that a
review-first workflow improves every knowledge task.
EOF

cat > "$TUTORIAL_ROOT/newer-evidence.md" <<'EOF'
Small comparison of review workflows

In a four-week internal comparison across three personal research projects, reviewed proposals
produced fewer unsupported wiki claims than automatically persisted proposals. The comparison
used one model and one reviewer, did not randomize task order, and did not measure long-term
maintenance cost.

The result supports testing a review gate in similar personal workflows. It does not establish
generalization to other models, teams, domains, or longer time horizons.
EOF
```

These commands create local files and make no provider calls.

## 3. Initialize the workspace

Initialize the declared workspace with conventions that distinguish evidence from personal
interpretation, then enter it.

```bash
uv run --project "$PROJECT_ROOT" bundlewalker init "$WORKSPACE_PATH" \
  --conventions-style personal-workbook
cd "$WORKSPACE_PATH"
uv run --project "$PROJECT_ROOT" bundlewalker lint
```

Initialization should create `bundlewalker.toml`, `conventions.md`, `raw/`, and `wiki/` under the
workspace. Deterministic lint should report `No lint findings.` for the empty bundle. Neither
command uses the model or network.

## 4. Ingest and review the first source

Before this reviewed write, expect a proposal for one Source and possibly related Topic or Entity
concepts, followed by the complete prospective diff. Titles, slugs, prose, and the optional
concept set depend on the model; the source limits must not.

```bash
uv run --project "$PROJECT_ROOT" bundlewalker ingest \
  "$TUTORIAL_ROOT/initial-notes.md" --model "$BUNDLEWALKER_MODEL"
```

Read the entire diff. Accept only if the proposal preserves that this is a working observation,
not a controlled comparison or a general performance claim. If you accept, one exact raw-source
copy and one Source concept should now exist, along with any accepted Topic or Entity concepts. If
you reject the proposal or interrupt before accepting it, accepted knowledge remains unchanged.

## 5. Explore accepted knowledge

Inspect the accepted files without guessing model-generated names, then check them deterministically.

```bash
find "raw" "wiki" -maxdepth 2 -type f -print | sort
uv run --project "$PROJECT_ROOT" bundlewalker lint
```

The listing should contain the accepted raw copy, a Source page, generated support files, and any
other concepts you approved. Lint should report no deterministic errors. These commands are local
and do not call the model.

## 6. Ask and save a Synthesis

First ask a cited question without proposing a write:

```bash
uv run --project "$PROJECT_ROOT" bundlewalker ask \
  'What does this workspace establish about review before persistence?' \
  --model "$BUNDLEWALKER_MODEL"
```

Plain `ask` returns one validated, cited answer but does not persist model output or open a review.
Before the next command, expect one proposed Synthesis based on that same validated answer and a
complete creation diff. Its wording and slug may vary, but its citations and caution must reflect
the accepted observation.

```bash
uv run --project "$PROJECT_ROOT" bundlewalker ask --save \
  'What does this workspace establish about review before persistence?' \
  --model "$BUNDLEWALKER_MODEL"
```

Accept only a supported, cautious answer. After acceptance, one new Synthesis should exist under
`wiki/syntheses/`. Rejection or interruption before acceptance leaves the previously accepted
knowledge unchanged. Discover the accepted Synthesis ID instead of assuming its generated slug:

```bash
SYNTHESIS_FILE="$(find "wiki/syntheses" -maxdepth 1 -type f -name '*.md' \
  ! -name 'index.md' -print -quit)"
test -n "$SYNTHESIS_FILE"
SYNTHESIS_ID="${SYNTHESIS_FILE#wiki/}"
SYNTHESIS_ID="${SYNTHESIS_ID%.md}"
printf 'Saved Synthesis: %s\n' "$SYNTHESIS_ID"
```

The discovery commands are local and make no provider call.

## 7. Add newer evidence

Before this reviewed write, expect a second Source proposal plus any related concepts and a full
prospective diff. The proposal must retain the comparison's duration, project count, one-model and
one-reviewer setup, lack of randomization, unmeasured maintenance cost, and limits on
generalization.

```bash
uv run --project "$PROJECT_ROOT" bundlewalker ingest \
  "$TUTORIAL_ROOT/newer-evidence.md" --model "$BUNDLEWALKER_MODEL"
```

If you accept, a second exact raw-source copy and Source concept should now exist, together with
only the additional concepts you reviewed. If you reject or interrupt before acceptance, the
first source and saved Synthesis remain the accepted knowledge.

## 8. Refresh the Synthesis

Before this reviewed write, expect either a full replacement diff for the existing Synthesis or a
successful no-op if the canonical replacement is unchanged. The proposal must keep the stable
concept path, cite accepted knowledge, and preserve the comparison's methodological limits.

```bash
uv run --project "$PROJECT_ROOT" bundlewalker ask \
  'Refresh this Synthesis with the newer comparison while preserving its methodological limits.' \
  --refresh "$SYNTHESIS_ID" --model "$BUNDLEWALKER_MODEL"
```

Accept only if the refreshed answer preserves the three-project sample, four-week duration, and
limits on other models, teams, domains, and time horizons. After acceptance, the same Synthesis
path should exist with its reviewed content and citations updated. If no canonical content
changed, BundleWalker reports `Synthesis is already current; no changes applied.` Rejection or
interruption before acceptance leaves the previously accepted Synthesis unchanged.

## 9. Check workspace health

Run deterministic lint, then create an offline, read-only diagnostic report outside the workspace:

```bash
uv run --project "$PROJECT_ROOT" bundlewalker lint
uv run --project "$PROJECT_ROOT" bundlewalker doctor "$WORKSPACE_PATH" \
  --report "$TUTORIAL_ROOT/bundlewalker-support.json"
```

Lint should report no deterministic errors. Doctor should print bounded check results and create a
redacted schema-version-1 JSON report; warnings exit successfully, while a failed check exits
`1`. Review the report yourself before sharing it. Neither command repairs state, changes accepted
knowledge, calls a model, or incurs provider cost.

## 10. Back up and restore the workspace

With every review resolved, create a verified archive outside the workspace and restore it to the
declared new target. `RESTORE_PATH` has not been created by any earlier step.

```bash
mkdir -p "$BACKUP_DIR"
uv run --project "$PROJECT_ROOT" bundlewalker workspace backup \
  "$BACKUP_PATH" --workspace "$WORKSPACE_PATH"
uv run --project "$PROJECT_ROOT" bundlewalker workspace restore \
  "$BACKUP_PATH" "$RESTORE_PATH"
```

Record the `SHA-256` printed by backup and restore and confirm that the values match. The
[backup scope and privacy policy](workspace-compatibility.md#backup-scope-and-privacy) explains
that the ZIP contains accepted raw-source bytes and is unencrypted. Keep it on encrypted storage
or apply external encryption before moving it through an untrusted system.

Check the restored copy without changing the original workspace:

```bash
(
  cd "$RESTORE_PATH"
  uv run --project "$PROJECT_ROOT" bundlewalker lint
)
```

Lint should report no deterministic errors. The restored target should contain the same durable
configuration, conventions, raw sources, and wiki as the backup, while `WORKSPACE_PATH` remains
in place.

## What you learned

You completed one review-first knowledge journey:

- deterministic commands created, checked, diagnosed, backed up, and restored the workspace
  without a model call;
- model-backed commands could use the network and incur cost, but they could not persist a
  reviewed write without your explicit acceptance;
- every accepted ingestion preserved exact source bytes, while generated concept names and prose
  remained model-dependent;
- a saved Synthesis could be discovered and refreshed without assuming its slug; and
- rejecting or interrupting before acceptance left the last accepted knowledge unchanged.

BundleWalker performed no Git operation during this journey.

## Next steps

- Use the [user guide](user-guide.md) for detailed tasks, command behavior, recovery, and safety.
- Configure another client through the
  [local MCP host section](user-guide.md#use-bundlewalker-through-a-local-mcp-host).
- Follow the [Hermes MCP setup guide](hermes-mcp-setup.md) for a Hermes-specific connection.
- Read the [workspace compatibility policy](workspace-compatibility.md) before moving, upgrading,
  or publishing a workspace.
- Consult the [reviewed performance and capacity evidence](performance-and-capacity.md) before
  planning a larger bundle.

## Clean up

Return to the checkout. Inspect the printed path first; when you no longer need either workspace
or the backup, remove the tutorial root you created in step 1.

```bash
cd "$PROJECT_ROOT"
printf 'Removing tutorial root: %s\n' "$TUTORIAL_ROOT"
rm -rf "$TUTORIAL_ROOT"
```
