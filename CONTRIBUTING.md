# Contributing to BundleWalker

BundleWalker is a local, review-first OKF knowledge tool. Start with the [project
overview](README.md), and use the [user guide](docs/user-guide.md) as the authority for
user-facing behavior. Contributors must preserve the trust boundary between agents and
deterministic code, and must keep the default test suite offline.

## Project boundaries

BundleWalker v3 ingests one UTF-8 Markdown or text source at a time and produces only four
concept types: Source, Topic, Entity, and Synthesis. Agents never write files directly. The
project does not perform automatic Git operations and does not run a background, hosted, or remote
service. Its MCP adapter is a foreground local `stdio` process bound to one workspace at startup.
Its separately launched web adapter binds an ephemeral `127.0.0.1` port and serves one workspace
until Ctrl-C; it is not a daemon, remote service, or lifecycle-management interface.

Before proposing an expansion of that scope, read the original
[v1 design](docs/superpowers/specs/2026-07-15-bundlewalker-v1-design.md), the accepted
[MCP and local web architecture](docs/superpowers/specs/2026-07-17-mcp-web-interface-architecture-design.md),
the approved
[public-beta roadmap](docs/superpowers/specs/2026-07-18-bundlewalker-public-beta-roadmap-design.md),
and the relevant records in `docs/superpowers/specs/` and `docs/superpowers/plans/`. A scope
change should begin with an explicit design decision, not an incidental implementation change.

## Architecture

| Layer | Main paths | Responsibility |
| --- | --- | --- |
| CLI compatibility | `src/bundlewalker/cli.py` | Re-export `app` and `main` for existing imports and the `bundlewalker` console entry point. |
| Delivery adapters | `src/bundlewalker/interfaces/cli.py`, `src/bundlewalker/interfaces/mcp.py`, `src/bundlewalker/interfaces/mcp_schemas.py`, `src/bundlewalker/interfaces/mcp_tools.py`, `src/bundlewalker/interfaces/web/` | Typer parsing, display, and bounded exits; local `stdio` MCP resources, strict tool schemas, and dispatch; plus loopback browser security, explicit web DTOs/API mapping, packaged assets, and foreground lifecycle. |
| Browser UI | `frontend/` | React presentation and temporary view/query state; it consumes only the versioned same-origin web API and cannot own workspace or transaction authority. |
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

Historical release workspaces under `tests/fixtures/historical/` preserve files byte-for-byte from
their recorded release provenance. Git and source distributions cannot represent an empty
directory directly, so release-owned empty directories are listed in the BundleWalker-owned
`empty-directories.json` sidecar outside the managed fixture roots. Historical tests must copy or
inspect fixtures through `tests.historical_fixtures.HistoricalFixtures`; do not add `.gitkeep` or
other placeholder bytes to a managed `raw/` or `wiki/` tree. When adding a historical fixture,
record any release-created empty directory in the sidecar, keep representation metadata distinct
from release provenance, and retain the explicit Hatch source-distribution inclusion contract.

## Development setup

BundleWalker development requires Python 3.13 or 3.14. Required CI tests both versions on macOS
and Linux; Windows is experimental and remains visible without being a supported gate. Use the
locked dependency graph so local results match CI and other contributors. Credentials are
unnecessary for the default suite. Browser-interface work additionally requires exact Node
`22.22.3`; installed users do not need Node because reviewed production assets ship in the normal
Python package.

```bash
git clone https://github.com/HendrikReh/BundleWalker.git
cd BundleWalker
uv sync --locked
uv run bundlewalker --help
```

Install the locked frontend graph before running browser checks:

```bash
cd frontend
npm ci
cd ..
```

The frontend command surface is:

| Command | Purpose |
| --- | --- |
| `npm run dev` | Run Vite's contributor development server; it is not an installed-user or supported remote service. |
| `npm run format:check` | Check frontend formatting without changes. |
| `npm run format:write` | Apply frontend formatting intentionally. |
| `npm run lint` | Run the TypeScript, React Hooks, and React Refresh ESLint policy. |
| `npm run test` | Run Vitest unit, component, and contract-consumer tests. |
| `npm run test:a11y` | Run the focused keyboard, focus, announcement, and axe baseline. |
| `npm run build` | Type-check and rebuild the packaged production assets. |
| `npm run test:e2e` | Run Playwright journeys through the production smoke harness described below. |

Maintainers must follow the [Release Procedure](docs/maintainers/releases.md); contributors must
not create tags or publish package artifacts from feature branches.

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
  `stdio` process behavior, plus local-web contracts, APIs, browser security, assets, and
  loopback lifecycle;
- `frontend/src/**/*.test.tsx`: browser client, component, workbench, contract, focus, and
  accessibility behavior;
- `frontend/e2e/`: deterministic production-stack Chromium journeys;
- `tests/test_acceptance.py`: complete offline user workflows and recovery;
- remaining `tests/test_*.py`: domain, workspace, retrieval, changes, conventions, and
  transactions; and
- `tests/evals/`: opt-in provider quality cases and deterministic refresh-quality contracts.

Use these checks for normal development:

```bash
uv sync --locked
uv lock --check
uv run pytest -m 'not eval' -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
git diff --check
```

For any frontend or web-adapter change, also run:

```bash
cd frontend
npm ci
npm run format:check
npm run lint
npm run test
npm run test:a11y
npm run build
npm audit --audit-level=high
cd ..
git diff --exit-code -- src/bundlewalker/interfaces/web/static
```

`npm run build` includes strict TypeScript compilation and writes the Vite output directly to the
packaged Python static directory. Run the real-browser suite with the production loopback/session
path after installing the locked Chromium version:

```bash
cd frontend
npx playwright install chromium
cd ..
uv run python scripts/run_web_smoke.py -- npm --prefix frontend run test:e2e
```

Run the smallest relevant focused test before this standard verification gate; for example,
`uv run pytest tests/workflows/test_ask.py -q` when changing the ask workflow.

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

Historical plans and specifications are immutable project records.
Do not synchronize them with later edits to active documentation. Validate the current README,
tutorial, user guide, specialist guides, and policy files against the live product instead.

### Web source, contracts, and packaged assets

Treat `frontend/package-lock.json`, `frontend/src/test/fixtures/contracts.json`, and
`src/bundlewalker/interfaces/web/static/` as reviewed product inputs and outputs:

- keep the frontend dependency graph exact and update
  [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) whenever its production inventory changes;
- regenerate canonical Python-to-TypeScript examples with
  `uv run python scripts/generate_web_contract_fixtures.py`, then require their Git diff to remain
  clean;
- never hand-edit compiled Vite output; change frontend source, run `npm run build`, and commit the
  new manifest, HTML shell, and content-hashed assets together;
- keep production source maps, remote scripts, fonts, analytics, credentials, bootstrap values,
  and developer-only absolute paths out of packaged assets;
- preserve keyboard operation, visible focus, status announcements, non-color labels, reduced
  motion, narrow-screen behavior, and the serious/critical axe baseline; and
- use the Playwright smoke for cross-boundary journeys instead of replacing lower-level Python or
  component tests with browser-only assertions.

The web runtime is part of the standard Python dependency set. Distribution checks install the
ordinary wheel and source archive, run `bundlewalker-web --help`, inspect the packaged
`static/index.html`, manifest, and hashed assets, and verify that
`THIRD_PARTY_NOTICES.md` ships with the artifacts.

For every active-document change, check relative links and local heading anchors, compare affected
commands with live help, and preserve versioned statements that intentionally describe a tagged
release or reviewed evidence set.

## Security and compatibility

Use the [Security Policy](SECURITY.md) for private vulnerability reports and the
[Support Policy](SUPPORT.md) for public bug-report scope. Never disclose a suspected
vulnerability, credential, or private workspace in a public issue.

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

## Licensing contributions

By intentionally submitting a contribution to BundleWalker, you agree that its inbound terms
match the license assigned to the target path in [License Scope](LICENSE-SCOPE.md):

- contributions to the five Markdown files under `src/bundlewalker/convention_presets/` are made
  under the CC0 1.0 Universal dedication, waiver, and fallback license; and
- contributions to all other project-owned paths are licensed under GPL-3.0-or-later unless that
  path is explicitly documented otherwise.

GPL contributors retain copyright in their contributions. BundleWalker does not require a
copyright assignment, contributor license agreement, or Developer Certificate of Origin.

## Before opening a pull request

- [ ] The change is focused, remains within v3 scope, or links to an accepted scope decision.
- [ ] Focused tests cover the behavior and were observed failing before the fix where applicable.
- [ ] The full offline suite passes.
- [ ] Frontend format, lint, unit/component, accessibility, build, audit, clean-asset, and
  Playwright checks pass when browser code or contracts changed.
- [ ] `uv run ruff format --check .` and `uv run ruff check .` pass.
- [ ] `uv run pyright` reports no errors or warnings.
- [ ] `git diff --check` is silent for the working tree.
- [ ] `git diff --check origin/master...HEAD` is silent for the branch range.
- [ ] Active documentation matches live help, local links and anchors resolve, and historical
  records remain unchanged.
- [ ] No credentials, private source material, or sensitive provider output appears in the diff.
- [ ] The pull request explicitly discloses whether any live provider evaluation was run, and
  names the configured model if it was.
