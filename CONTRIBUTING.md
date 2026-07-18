# Contributing to BundleWalker

BundleWalker is a local, review-first OKF knowledge tool. Start with the [project
overview](README.md), and use the [user guide](docs/user-guide.md) as the authority for
user-facing behavior. Contributors must preserve the trust boundary between agents and
deterministic code, and must keep the default test suite offline.

## Project boundaries

BundleWalker v2 ingests one UTF-8 Markdown or text source at a time and produces only four
concept types: Source, Topic, Entity, and Synthesis. Agents never write files directly. The
project does not perform automatic Git operations and does not run a background, hosted, or remote
service. Its MCP adapter is a foreground local `stdio` process bound to one workspace at startup;
the local web UI remains a separate next plan.

Before proposing an expansion of that scope, read the original
[v1 design](docs/superpowers/specs/2026-07-15-bundlewalker-v1-design.md), the accepted
[MCP and local web architecture](docs/superpowers/specs/2026-07-17-mcp-web-interface-architecture-design.md),
and the relevant records in [`docs/superpowers/specs/`](docs/superpowers/specs/) and
[`docs/superpowers/plans/`](docs/superpowers/plans/). A scope change should begin with an explicit
design decision, not an incidental implementation change.

## Architecture

| Layer | Main paths | Responsibility |
| --- | --- | --- |
| CLI compatibility | `src/bundlewalker/cli.py` | Re-export `app` and `main` for existing imports and the `bundlewalker` console entry point. |
| Delivery adapters | `src/bundlewalker/interfaces/cli.py`, `src/bundlewalker/interfaces/mcp.py`, `src/bundlewalker/interfaces/mcp_schemas.py`, `src/bundlewalker/interfaces/mcp_tools.py` | Typer parsing, display, confirmation, and bounded exits; plus local `stdio` MCP resources, strict tool schemas, and dispatch. |
| Application | `src/bundlewalker/application/` | Workspace-bound async facade, serializable contracts, and bounded error translation shared by delivery adapters |
| Workflows | `src/bundlewalker/workflows/` | Recovery, orchestration, pre-model checks, dependency construction, and transaction preparation |
| Agents | `src/bundlewalker/agents/` | PydanticAI prompts, read-only tools, typed model output, and output validation |
| Domain | `src/bundlewalker/domain.py` | Pydantic models and bounded proposal/answer/finding types |
| Changes | `src/bundlewalker/changes.py` | Operation validation, citation validation, rendering, and prospective wiki construction |
| OKF | `src/bundlewalker/okf/` | Document parsing/rendering, repository reads, indexes/logs/diffs, and deterministic lint |
| Retrieval | `src/bundlewalker/retrieval.py` | Local lexical concept ranking used by read-only agent tools |
| Transactions | `src/bundlewalker/transactions.py` | Durable one-at-a-time pending reviews, staging, locked apply/discard/recovery, digest revalidation, and authenticated recovery |
| Workspace | `src/bundlewalker/workspace.py` | Initialization, discovery, configuration, source identities, and safe paths |

The write flow is `CLI or MCP -> application facade -> workflow -> agent proposal -> deterministic
validation -> prospective tree -> durable review -> explicit apply/discard`. The model supplies a
typed proposal; application code owns path handling, validation, rendering, the complete diff,
review state, and persistence. A preparation may change only private `.bundlewalker/` transaction
state; applying its exact review ID is the operation that can change live `raw/` or `wiki/`
content. Plain `ask` and both lint modes do not authorize persistence of new model output or open
a new review. Read operations preserve a pending review; accepted interrupted transactions may be
completed or rolled back by authenticated recovery without authorizing new model output.

## Repository map

- `src/bundlewalker/` contains the installed Python package and the layer boundaries above.
- `tests/` mirrors those boundaries with unit, contract, integration, recovery, and acceptance
  coverage.
- `evals/` contains deterministic case data consumed by the opt-in model-quality evaluations.
- `docs/superpowers/specs/` records accepted designs and architectural decisions.
- `docs/superpowers/plans/` records implementation plans and exact historical contracts.

Agent instructions are packaged as Markdown under `src/bundlewalker/agents/prompts/`.
Convention presets are packaged Markdown resources under
`src/bundlewalker/convention_presets/`. Treat both sets as versioned product inputs: review their
behavioral effect and keep their package-loading tests current.

## Development setup

BundleWalker requires Python `>=3.13`. Use the locked dependency graph so local results match CI
and other contributors. Credentials are unnecessary for the default suite.

```bash
git clone https://github.com/HendrikReh/BundleWalker.git
cd BundleWalker
uv sync --locked
uv run bundlewalker --help
```

## Change workflow

Work on a focused `codex/` branch or a branch following the project's normal naming convention.
For a behavioral fix, first add a focused test and observe it fail for the expected reason. Make
the smallest implementation that satisfies the contract, rerun the focused verification, then
run the full offline verification. Review the diff and create an intentional commit whose scope
and message match the change.

Documentation-only changes still require validation against live command help and checks for
broken or stale links. Do not infer CLI or MCP syntax from prose when live help and `TOOL_SPECS`
can provide the current interface.

## Test layers

- `tests/okf/`: parser, renderer, repository, derived-file, and deterministic lint behavior;
- `tests/agents/`: tool boundaries, prompt framing, model-output validation, and sanitized errors;
- `tests/workflows/`: orchestration, preconditions, no-ops, and transaction preparation;
- `tests/cli/`: Typer arguments, output, prompts, exit codes, and routing;
- `tests/application/`: facade contracts, workspace confinement, and adapter-neutral use cases;
- `tests/interfaces/`: local MCP resources, strict schemas, tool dispatch, progress/cancellation,
  and `stdio` process behavior;
- `tests/test_acceptance.py`: complete offline user workflows and recovery;
- remaining `tests/test_*.py`: domain, workspace, retrieval, changes, conventions, and
  transactions; and
- `tests/evals/`: opt-in provider quality cases and deterministic refresh-quality contracts.

Use these checks for normal development:

```bash
uv run pytest -m 'not eval' -q
uv run pytest tests/workflows/test_ask.py -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
git diff --check
```

Live quality evaluation is optional. Running
`BUNDLEWALKER_EVAL_MODEL='<pydantic-ai-model-string>' uv run pytest -m eval -v` uses the named
provider and may cost money. It complements the offline suite; it never replaces deterministic,
workflow, CLI, or acceptance coverage.

## Documentation changes

Each document has one primary job:

- `README.md` is the concise project overview and first-use entry point.
- `docs/tutorial.md` is the copy-pasteable personal-workbook walkthrough.
- `docs/user-guide.md` is authoritative for detailed user tasks, CLI behavior, and
  troubleshooting.
- `CONTRIBUTING.md` is authoritative for architecture, development, and verification practice.

Validate documented commands against live `bundlewalker --help` output and the help for every
affected subcommand. Also check all local Markdown links whenever a document moves, gains a
section, or changes its navigation.

The historical plan `docs/superpowers/plans/2026-07-16-end-user-guide.md` embeds an exact copy of
`docs/user-guide.md`. Its synchronization contract locates that copy after the start marker
``Create `docs/user-guide.md` with exactly:`` and its opening four-backtick `markdown` fence, and
before the closing four-backtick fence followed by the Step 3 README-link marker. After every
user-guide edit, update the embedded block and verify byte equality with the canonical guide,
including the final newline.

## Security and compatibility

Public errors must stay bounded and must not leak source contents, protected context,
credentials, or provider details. Frame external source content and existing-knowledge payloads
as untrusted data before model use. Validate citations against the per-run read ledger, and keep
paths confined and safe at every filesystem boundary.

Preserve digest preconditions for replacements and prepared transactions, permissive OKF reading
for extension metadata and unknown consumer types, and strict producer types for BundleWalker
output. Transaction commit, discard, and authenticated recovery must remain intact across
interruption and concurrency.

Never weaken any of these boundaries merely to accept a model response; reject or retry invalid
output before persistence instead.

## Before opening a pull request

- [ ] The change is focused, remains within v2 scope, or links to an accepted scope decision.
- [ ] Focused tests cover the behavior and were observed failing before the fix where applicable.
- [ ] The full offline suite passes.
- [ ] `uv run ruff format --check .` and `uv run ruff check .` pass.
- [ ] `uv run pyright` reports no errors or warnings.
- [ ] `git diff --check` is silent for the working tree.
- [ ] `git diff --check origin/master...HEAD` is silent for the branch range.
- [ ] Documentation matches live help, links resolve, and the embedded user guide is synchronized.
- [ ] No credentials, private source material, or sensitive provider output appears in the diff.
- [ ] The pull request explicitly discloses whether any live provider evaluation was run, and
  names the configured model if it was.
