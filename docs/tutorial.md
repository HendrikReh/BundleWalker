# BundleWalker Personal Workbook Tutorial

This hands-on companion to the [BundleWalker README](../README.md), the complete
[user guide](user-guide.md), and the [contributor guide](../CONTRIBUTING.md) follows one personal
workbook from empty workspace to refreshed Synthesis.

Start at the root of a BundleWalker checkout. The tutorial creates all of its notes and workbook
data under a new temporary directory. Initialization and deterministic lint are local and
model-free; `ingest`, `ask`, `ask --save`, `ask --refresh`, and optional semantic lint are
model-backed commands that call your configured provider and may incur provider charges.

Run every command block in the same shell session. That keeps `PROJECT_ROOT`, `TUTORIAL_ROOT`,
`BUNDLEWALKER_MODEL`, and, later, `SYNTHESIS_ID` available throughout the journey.

## What you will build

You will create a `personal-workbook` workspace, ingest a cautious observation, inspect and query
the accepted knowledge, save a reviewed Synthesis, add a small comparison as newer evidence, and
refresh the same Synthesis without assuming any model-generated title, prose, or slug. You will
finish by checking the bundle and, optionally, putting its durable files under Git.

## Before you start

You need Python 3.13 or newer, [`uv`](https://docs.astral.sh/uv/), a PydanticAI model string, and
the provider credential required by that model. Export both in the shell you will use for the
tutorial. Keep the model choice provider-neutral here; the
[model and provider setup guide](user-guide.md#model-and-provider-setup) has provider-specific
details.

```bash
export BUNDLEWALKER_MODEL='<pydantic-ai-model-string>'
# Export the provider-specific credential required by that model.
```

Do not commit provider credentials or paste them into the workbook.

## 1. Prepare BundleWalker and your model

From the BundleWalker checkout, install the locked dependencies and record both the checkout and
a fresh temporary directory:

```bash
uv sync --locked
PROJECT_ROOT="$(pwd)"
TUTORIAL_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/bundlewalker-tutorial.XXXXXX")"
printf 'Tutorial files: %s\n' "$TUTORIAL_ROOT"
```

The printed temporary path is deliberately retained. You can inspect the notes and workbook there
after the tutorial, then delete the whole directory when you no longer need it. These preparation
commands make no provider calls.

## 2. Create two source notes

Create an initial working observation and a later, limited comparison. Both remain outside the
workbook so that ingestion can preserve their exact bytes in `raw/`.

```bash
cat > "$TUTORIAL_ROOT/initial-notes.md" <<'EOF'
# Review-first knowledge workflow

A review gate separates a model proposal from durable knowledge. A declined proposal leaves the
knowledge base unchanged. Accepted source bytes remain immutable, while the compiled wiki may be
refined as new evidence arrives.

This note is a working observation, not a controlled comparison. It does not establish that a
review-first workflow improves every knowledge task.
EOF

cat > "$TUTORIAL_ROOT/newer-evidence.md" <<'EOF'
# Small comparison of review workflows

In a four-week internal comparison across three personal research projects, reviewed proposals
produced fewer unsupported wiki claims than automatically persisted proposals. The comparison
used one model and one reviewer, did not randomize task order, and did not measure long-term
maintenance cost.

The result supports testing a review gate in similar personal workflows. It does not establish
generalization to other models, teams, domains, or longer time horizons.
EOF
```

Creating these local files makes no provider calls.

## 3. Initialize the personal workbook

Initialize the workbook with conventions that emphasize the boundary between evidence and
personal interpretation, enter it, and validate the deterministic scaffold:

```bash
uv run bundlewalker init "$TUTORIAL_ROOT/workbook" \
  --conventions-style personal-workbook
cd "$TUTORIAL_ROOT/workbook"
uv run --project "$PROJECT_ROOT" bundlewalker lint
```

Initialization should succeed, and lint should report `No lint findings.` for the empty bundle.
Both commands are deterministic and make no provider calls.

## 4. Ingest and review the first source

Ingest the initial note. This is the first model-backed command and may incur a provider charge:

```bash
uv run --project "$PROJECT_ROOT" bundlewalker ingest ../initial-notes.md
```

BundleWalker prints a summary and the full prospective diff before prompting. Inspect the entire
diff. Answer `y` only if the Source and every proposed concept faithfully reflect the observation,
including its limits. Answering `n`, pressing Ctrl-C, or ending input at the prompt leaves live
knowledge unchanged. The exact filenames, concept slugs, titles, and prose can vary by model, so
the remaining steps do not depend on them.

## 5. Inspect accepted knowledge

After accepting the proposal, list the accepted raw and compiled files without guessing their
generated names, then run the offline deterministic checks again:

```bash
find raw wiki -maxdepth 2 -type f -print | sort
uv run --project "$PROJECT_ROOT" bundlewalker lint
```

The listing should include one immutable raw copy, a Source, any accepted Topic or Entity pages,
and generated wiki support files. The precise set of concepts is proposal-dependent. Lint checks
the accepted bundle without making a provider call.

## 6. Ask and save a Synthesis

First ask the workbook a question without proposing or persisting a knowledge change:

```bash
uv run --project "$PROJECT_ROOT" bundlewalker ask \
  'What does this workspace currently establish about review before persistence?'
```

Plain `ask` is model-backed and may incur a provider charge. It prints one validated, cited answer,
but does not propose or persist new model output and opens no review prompt. Before querying,
however, it may complete or roll back an already-reviewed interrupted transaction.

Now ask the same question and save its answer:

```bash
uv run --project "$PROJECT_ROOT" bundlewalker ask --save \
  'What does this workspace currently establish about review before persistence?'
```

This is another model-backed command and may incur a provider charge. Within this invocation,
`--save` reuses the one validated answer and does not make a second model call. It proposes a new
Synthesis through the normal full diff and review gate. Accept only if the answer remains cautious
about what the first note can establish. The generated Synthesis path and wording may vary; the
refresh steps discover its ID.

## 7. Add newer evidence

Ingest the comparison note. This model-backed command may incur a provider charge:

```bash
uv run --project "$PROJECT_ROOT" bundlewalker ingest ../newer-evidence.md
```

Review the complete proposal. Accept it only if it preserves the four-week duration, the three
personal research projects, the one-model and one-reviewer setup, the lack of randomization, the
unmeasured maintenance cost, and the stated limits on generalization.

After acceptance, discover the single saved Synthesis rather than assuming its model-generated
slug, and derive the canonical ID by removing only `wiki/` and the `.md` suffix:

```bash
SYNTHESIS_FILE="$(find wiki/syntheses -maxdepth 1 -type f -name '*.md' \
  ! -name 'index.md' -print -quit)"
test -n "$SYNTHESIS_FILE"
SYNTHESIS_ID="${SYNTHESIS_FILE#wiki/}"
SYNTHESIS_ID="${SYNTHESIS_ID%.md}"
printf 'Refreshing: %s\n' "$SYNTHESIS_ID"
```

These discovery commands are local and make no provider calls.

## 8. Refresh the Synthesis

Ask BundleWalker to revise that exact Synthesis with the newer evidence. This is one model-backed
query and may incur a provider charge:

```bash
uv run --project "$PROJECT_ROOT" bundlewalker ask \
  'Refresh this Synthesis with the newer comparison while preserving its methodological limits.' \
  --refresh "$SYNTHESIS_ID"
```

Refresh keeps the stable concept path, so inbound links remain valid, while the visible title,
body, and citations may change. Existing description, tags, and representable metadata extensions
are preserved. BundleWalker records the target digest and refuses to overwrite the page if it
changes during the operation.

One model call produces the refreshed answer; preparation makes no second model call. If the
canonical replacement differs, BundleWalker shows the rendered answer and a full replacement diff
before review. Accept only if the new Synthesis preserves the comparison's sample of three
projects, four-week duration, and limits on generalizing to other models, teams, domains, or time
horizons.

If the entire canonical replacement is unchanged, no review is needed and the exact successful
no-op message is:

```text
Synthesis is already current; no changes applied.
```

## 9. Check final health

Run deterministic lint first, then optionally ask the configured provider for semantic
advisories:

```bash
uv run --project "$PROJECT_ROOT" bundlewalker lint
uv run --project "$PROJECT_ROOT" bundlewalker lint --semantic
```

Plain lint is offline and provider-free. `lint --semantic` is optional, model-backed, and may incur
a provider charge. Its findings vary by model and remain advisory. Neither lint mode proposes or
persists knowledge changes, opens a review, or approves a refresh. Before linting, either mode may
complete or roll back an already-reviewed interrupted transaction.

## 10. Optional Git checkpoint

If the workbook is suitable for version control, ignore temporary transaction state and commit
the durable configuration, conventions, source bytes, and wiki:

```bash
printf '.bundlewalker/\n' > .gitignore
git init
git add .gitignore bundlewalker.toml conventions.md raw wiki
git commit -m 'Create BundleWalker personal workbook'
```

Git may ask you to configure your author name and email before committing. The `raw/` directory
contains exact source bytes; review it for personal, confidential, licensed, or regulated content
before publishing the repository to any remote. BundleWalker does not publish it for you.

## What to try next

- Compare the [preset choices](user-guide.md#choosing-a-preset) for other kinds of workspace.
- Explore the [full command reference](user-guide.md#command-reference).
- Consult [troubleshooting and safety](user-guide.md#troubleshooting-and-safety) for provider,
  workspace, proposal, refresh, and privacy problems.
- Read the [contributor guidance](../CONTRIBUTING.md) before changing BundleWalker itself.

Leave the workbook available for inspection by returning to the checkout and printing its
location. Remove it later, from outside the workspace, only when you no longer need it:

```bash
cd "$PROJECT_ROOT"
printf 'Tutorial workspace retained at: %s\n' "$TUTORIAL_ROOT"
# Remove it later only when you no longer need it:
# rm -rf "$TUTORIAL_ROOT"
```
