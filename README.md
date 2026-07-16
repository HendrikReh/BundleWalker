# BundleWalker

BundleWalker is a local, review-first CLI that turns Markdown and text sources into a maintained,
cited Open Knowledge Format (OKF) wiki. Accepted source bytes stay immutable, every proposed
knowledge change is reviewable, and the resulting Markdown remains readable without BundleWalker.

[Tutorial](docs/tutorial.md) · [User Guide](docs/user-guide.md) · [Contributing](CONTRIBUTING.md)

## Why BundleWalker

| What you get | Why it matters |
| --- | --- |
| Local files | Your sources, conventions, and compiled knowledge remain ordinary files in your workspace. |
| Complete reviewed diffs | Model-backed knowledge changes are validated and shown in full before you decide whether to keep them. |
| Cited answers | Questions are answered from concepts the query actually read, with links back into the wiki. |
| Portable OKF | The knowledge layer is an interlinked Markdown bundle that other OKF-aware tools can read. |
| Recoverable writes | Accepted changes use transactions that can safely complete or roll back after interruption. |

## Quick start

BundleWalker requires Python 3.13 or newer and [`uv`](https://docs.astral.sh/uv/). Install the
locked repository environment, record its path, and configure a model supported by your installed
PydanticAI version:

```bash
git clone https://github.com/HendrikReh/BundleWalker.git
cd BundleWalker
uv sync --locked
PROJECT_ROOT="$(pwd)"
export BUNDLEWALKER_MODEL='<pydantic-ai-model-string>'
```

Create a small source note, initialize a personal workbook, and enter it:

```bash
cat > example-notes.md <<'EOF'
# Review-first knowledge

A review gate separates a model proposal from durable knowledge. Declining a proposal leaves the
knowledge base unchanged, while accepted source bytes remain immutable evidence.
EOF

uv run bundlewalker init ./my-knowledge --conventions-style personal-workbook
cd ./my-knowledge
```

Run the offline check, ingest the note, ask a read-only question, save a reviewed answer, and add
optional semantic advisories:

```bash
uv run --project "$PROJECT_ROOT" bundlewalker lint
uv run --project "$PROJECT_ROOT" bundlewalker ingest ../example-notes.md
uv run --project "$PROJECT_ROOT" bundlewalker ask \
  'Why does this workspace use a review gate?'
uv run --project "$PROJECT_ROOT" bundlewalker ask --save \
  'Why does this workspace use a review gate?'
uv run --project "$PROJECT_ROOT" bundlewalker lint --semantic
```

`ingest` and `ask --save` show a complete prospective diff. Answer `y` to apply it; answer `n`,
press Ctrl-C, or end input to discard it and exit successfully with live knowledge unchanged.
Model-backed commands use your configured provider and may incur network use or cost. Follow the
[tutorial](docs/tutorial.md) for the complete ingest, save, newer-evidence, and refresh journey, or
use the [provider setup guide](docs/user-guide.md#model-and-provider-setup) for configuration
details.

### OpenAI example

This labelled example is not a default or a model-availability claim. Replace both placeholders
with your own secret and a current model ID; never commit the key:

```bash
export OPENAI_API_KEY='replace-with-your-openai-api-key'
export BUNDLEWALKER_MODEL='openai:<current-openai-model-id>'
```

## Choose what you are building

| Preset | Best fit |
| --- | --- |
| `default` | Neutral general knowledge |
| `personal-workbook` | Evidence, reflection, and open questions |
| `agent-context` | Operational authority, constraints, procedures, and recovery |
| `software-agent` | Repository architecture, commands, invariants, and traps |
| `research-agent` | Methods, competing claims, limitations, and research gaps |

Preset selection only chooses the initial template. BundleWalker does not store or later enforce
the selection; the generated, fully editable `conventions.md` becomes the workspace authority.
See [Choosing a preset](docs/user-guide.md#choosing-a-preset) for examples and trade-offs.

## How reviewed writes work

```text
Model-backed proposal -> deterministic validation -> complete diff -> your decision -> commit
```

`ingest`, `ask --save`, and `ask ... --refresh` persist model-derived knowledge only after
acceptance. `init` creates deterministic scaffolding without review. Plain `ask`, plain `lint`,
and `lint --semantic` do not propose knowledge writes; semantic lint is model-backed but advisory.

Re-ingesting identical source bytes is a successful pre-model no-op. A refresh whose complete
canonical replacement is unchanged is also a successful no-op, without a review prompt or log
entry. Reviewed commits use authenticated transaction state so a later `ingest`, `ask`, or `lint`
can safely complete or roll back an interrupted write. The [user guide](docs/user-guide.md#maintain-and-recover-the-bundle)
documents the full recovery and process behavior.

## Common next steps

Run these from a workspace with `PROJECT_ROOT` pointing to the BundleWalker checkout:

| Goal | Command | Guide |
| --- | --- | --- |
| Ask without writing | `uv run --project "$PROJECT_ROOT" bundlewalker ask 'QUESTION'` | [Ask a cited question](docs/user-guide.md#ask-a-cited-question) |
| Save a reviewed answer | `uv run --project "$PROJECT_ROOT" bundlewalker ask --save 'QUESTION'` | [Save a Synthesis](docs/user-guide.md#save-a-synthesis) |
| Refresh one Synthesis | `uv run --project "$PROJECT_ROOT" bundlewalker ask 'REVISION INSTRUCTION' --refresh syntheses/ID` | [Refresh a Synthesis](docs/user-guide.md#refresh-a-synthesis) |
| Run offline checks | `uv run --project "$PROJECT_ROOT" bundlewalker lint` | [Maintain the bundle](docs/user-guide.md#maintain-and-recover-the-bundle) |
| Add semantic advisories | `uv run --project "$PROJECT_ROOT" bundlewalker lint --semantic` | [Semantic lint](docs/user-guide.md#maintain-and-recover-the-bundle) |

## Current scope

Version 1 ingests one regular UTF-8 `.md` or `.txt` file per command, with a default limit of
100,000 Unicode characters. It produces four knowledge types: Source, Topic, Entity, and
Synthesis. Model proposals, answers, paths, metadata, and citations are bounded; see the
[detailed producer limits](docs/user-guide.md#v1-producer-limits-and-permissive-reading).

V1 does not ingest URLs, PDFs, images, audio, video, or OCR; batch or watch directories; chunk
book-sized sources; use embeddings, vector databases, or background indexes; provide a web UI,
plugin, MCP server, or hosted service; let agents delete, rename, edit conventions, or resolve
contradictions automatically; or perform multi-user synchronization and Git operations. The
[user guide](docs/user-guide.md#ingest-and-review-a-source) covers source validation and the
operating boundary in detail.

## Documentation

Each document has one primary job:

- This README is the concise project overview and first-use landing page.
- The [Tutorial](docs/tutorial.md) is the copy-pasteable personal-workbook journey through ingest,
  save, newer evidence, refresh, and final health checks.
- The [User Guide](docs/user-guide.md) is authoritative for detailed user tasks, CLI behavior,
  provider setup, recovery, limits, and troubleshooting.
- [Contributing](CONTRIBUTING.md) is authoritative for architecture, development workflow,
  verification, and compatibility expectations.

## Development

The default suite is offline and requires no model credentials:

```bash
uv run pytest -m 'not eval' -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
```

Live model-quality evaluation is explicit and opt-in:

```bash
BUNDLEWALKER_EVAL_MODEL='<pydantic-ai-model-string>' uv run pytest -m eval -v
```

The current quality areas are faithful source summary, cross-source topic update, contradiction
preservation, cited answer, and stale-Synthesis refresh. Live evaluation may use the network and
incur provider cost; it never replaces offline acceptance coverage. See
[Contributing](CONTRIBUTING.md) for architecture and workflow detail.
