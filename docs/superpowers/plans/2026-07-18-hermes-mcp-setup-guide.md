# Hermes Agent MCP Setup Guide Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a portable, Hermes-specific user guide for connecting one local BundleWalker
workspace over MCP, and make that guide discoverable from BundleWalker's existing documentation.

**Architecture:** Keep Hermes launch, filtering, credential forwarding, reload, and troubleshooting
instructions in one standalone page. Keep BundleWalker's tool schemas and durable-review semantics
canonical in `docs/user-guide.md`, then add concise discovery links and mechanically synchronize the
repository's required embedded guide copy.

**Tech Stack:** Markdown, Hermes Agent CLI and YAML configuration, BundleWalker v2 MCP `stdio`
server, uv, Python 3.13, Markdown-it, Git

## Global Constraints

- Create the dedicated guide at exactly `docs/hermes-mcp-setup.md`.
- The guide remains Hermes-specific; `docs/user-guide.md` remains the host-neutral MCP authority.
- Use `PROJECT_ROOT`, `WORKSPACE`, `UV_COMMAND`, and `HERMES_CONFIG_DIR` as portable setup values.
- Use absolute BundleWalker project and workspace paths; preserve paths containing spaces.
- The Hermes server name is `bundlewalker`, and `--args` is the final `hermes mcp add` option.
- Document exactly the ten current BundleWalker MCP tools and distinguish read-oriented,
  preparation, and review-resolution groups.
- Describe `ask` and semantic `lint` as model-backed; deterministic `lint` remains model-free.
- Keep actual credentials in the active Hermes `.env`; explicitly forward only
  `BUNDLEWALKER_MODEL` and the selected provider credential through the MCP server `env` mapping.
- Do not recommend `supports_parallel_tool_calls` for BundleWalker.
- Do not include personal usernames, mounted-volume names, workspace counts, credentials, or a
  specific current model as a default.
- Do not change BundleWalker application behavior, schemas, dependencies, or console scripts.
- Update `docs/superpowers/plans/2026-07-16-end-user-guide.md` only by synchronizing its required
  exact embedded copy of `docs/user-guide.md`; leave other historical records unchanged.
- Preserve the pre-existing untracked backup archive without reading, staging, modifying, moving,
  or deleting it.

---

## File map

- Create `docs/hermes-mcp-setup.md`: standalone Hermes integration workflow and troubleshooting
  guide.
- Modify `README.md`: add a prominent link from the local MCP section and documentation map.
- Modify `docs/user-guide.md`: link from the host-neutral local MCP section to the dedicated Hermes
  guide.
- Modify `docs/superpowers/plans/2026-07-16-end-user-guide.md`: synchronize only the required exact
  embedded user-guide block.

### Task 1: Write the Portable Hermes Integration Guide

**Files:**
- Create: `docs/hermes-mcp-setup.md`

**Interfaces:**
- Consumes: BundleWalker console command `bundlewalker-mcp --workspace WORKSPACE`; the ten names in
  `bundlewalker.interfaces.mcp_schemas.TOOL_SPECS`; Hermes CLI commands `mcp add`, `list`, `test`,
  `configure`, and `remove`; Hermes `mcp_servers` configuration and filtered stdio environment.
- Produces: a self-contained setup guide that Task 2 links from README and the canonical user
  guide.

- [ ] **Step 1: Establish the missing-guide baseline**

Run:

```bash
test ! -e docs/hermes-mcp-setup.md
```

Expected: exits `0`, proving the dedicated guide does not already exist. If the file exists, stop
and inspect it rather than overwriting unknown user work.

- [ ] **Step 2: Create the dedicated guide with the approved content**

Create `docs/hermes-mcp-setup.md` with exactly:

````markdown
# Connect Hermes Agent to BundleWalker over MCP

This guide connects Hermes Agent to one local BundleWalker OKF workspace through BundleWalker's
`stdio` MCP server. It covers Hermes-specific registration, tool selection, credential forwarding,
reload, troubleshooting, and removal.

For BundleWalker's complete MCP resource, tool-schema, and durable-review contracts, use the
[host-neutral MCP reference](user-guide.md#use-bundlewalker-through-a-local-mcp-host).

## What this connection does

Hermes starts BundleWalker as a local subprocess and communicates with it over stdin and stdout.
The server binds one workspace at startup. No MCP tool can switch workspaces or accept an arbitrary
workspace or local source path.

The connection is local, but some BundleWalker tools call the model provider you configure for
BundleWalker. Hermes's own conversation model and BundleWalker's PydanticAI model are separate.

## Prerequisites

You need:

- a local BundleWalker v2 checkout installed with `uv sync --locked`;
- an initialized BundleWalker workspace containing `bundlewalker.toml`;
- Hermes Agent with MCP support; and
- terminal access to `uv` and `hermes`.

Hermes's standard installation includes MCP support. If your installation was intentionally
minimal, follow the official [Hermes MCP documentation](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp)
before continuing.

## Record your local setup values

The examples use four shell variables:

| Variable | Meaning |
| --- | --- |
| `PROJECT_ROOT` | Absolute path to the BundleWalker checkout containing `pyproject.toml`. |
| `WORKSPACE` | Absolute path to the initialized OKF workspace containing `bundlewalker.toml`. |
| `UV_COMMAND` | Absolute path to the `uv` executable Hermes should launch. |
| `HERMES_CONFIG_DIR` | Active Hermes configuration directory, usually `~/.hermes`. |

From the BundleWalker checkout, set and validate them:

```bash
PROJECT_ROOT="$(pwd -P)"
WORKSPACE="/absolute/path/to/your/bundlewalker-workspace"
UV_COMMAND="$(command -v uv)"
HERMES_CONFIG_DIR="${HERMES_HOME:-$HOME/.hermes}"

test -f "$PROJECT_ROOT/pyproject.toml"
test -f "$WORKSPACE/bundlewalker.toml"
test -x "$UV_COMMAND"
test -d "$HERMES_CONFIG_DIR"
```

Replace the workspace example before running the checks. Keep quotation marks around shell path
variables so paths containing spaces remain one argument.

## Register BundleWalker with Hermes

Add a local server named `bundlewalker`:

```bash
hermes mcp add bundlewalker \
  --command "$UV_COMMAND" \
  --args \
    run \
    --project "$PROJECT_ROOT" \
    bundlewalker-mcp \
    --workspace "$WORKSPACE"
```

`--args` must be the final Hermes option. Everything after it belongs to the BundleWalker process.

Hermes writes an equivalent entry under `mcp_servers` in its active `config.yaml`. For manual
review or configuration, the entry has this shape:

```yaml
mcp_servers:
  bundlewalker:
    command: "/absolute/path/to/uv"
    args:
      - run
      - --project
      - "/absolute/path/to/BundleWalker"
      - bundlewalker-mcp
      - --workspace
      - "/absolute/path/to/your/bundlewalker-workspace"
```

Use separate YAML list items for every argument. Quoted YAML scalars preserve paths containing
spaces without embedding shell quotation marks in the argument value.

## Test the connection

List configured MCP servers and probe BundleWalker:

```bash
hermes mcp list
hermes mcp test bundlewalker
```

A successful test starts the server, performs MCP discovery, and lists its available capabilities.
It does not require a BundleWalker model merely to start the server or discover tools.

## Choose which tools Hermes may use

Open Hermes's per-server tool selector:

```bash
hermes mcp configure bundlewalker
```

Start with this read-oriented set:

- `workspace_status` — inspect counts and pending-review state;
- `search_concepts` — run deterministic lexical search;
- `ask` — ask cited questions without changing workspace content;
- `lint` — run deterministic checks or optional model-assisted advisories; and
- `get_pending_review` — inspect the one pending review, if present.

This set is read-oriented, not fully offline: `ask` needs a BundleWalker model, and `lint` needs one
when called with semantic analysis enabled.

Enable these only when Hermes should be able to prepare knowledge changes:

- `prepare_ingestion`
- `prepare_synthesis`
- `prepare_refresh`

Enable these only when Hermes should also be able to resolve the exact pending review:

- `apply_review`
- `discard_review`

The write lifecycle remains review-first:

```text
prepare_ingestion | prepare_synthesis | prepare_refresh
    -> inspect get_pending_review
    -> apply_review REVIEW_ID | discard_review REVIEW_ID
```

Preparation creates private pending state under `.bundlewalker/`; it does not immediately change
live `raw/` or `wiki/` content. Applying or discarding requires the exact review ID. BundleWalker
allows at most one pending review per workspace.

Do not set `supports_parallel_tool_calls: true` for this server. BundleWalker has shared workspace
state and a single pending-review slot, so sequential calls are the conservative configuration.

## Configure model-backed BundleWalker tools

These tools do not need a BundleWalker model:

- `workspace_status`
- `search_concepts`
- `get_pending_review`
- deterministic `lint`
- `apply_review`
- `discard_review`

These operations are model-backed:

- `ask`
- `prepare_ingestion` for a new source
- `prepare_synthesis`
- `prepare_refresh`
- semantic `lint`

BundleWalker does not automatically reuse the model currently running Hermes. Store the
BundleWalker model string and provider credential in the active Hermes secret environment file:

```text
$HERMES_CONFIG_DIR/.env
```

For example, an OpenAI-backed setup could contain:

```dotenv
BUNDLEWALKER_MODEL=openai:<current-model-id>
OPENAI_API_KEY=<your-api-key>
```

This is an example, not a default or model-availability claim. For another PydanticAI provider,
use its model string and credential variable. Never commit the Hermes `.env` file.

Hermes filters the environment inherited by local MCP subprocesses. Explicitly forward only the
variables BundleWalker needs by extending the server entry in `config.yaml`:

```yaml
mcp_servers:
  bundlewalker:
    command: "/absolute/path/to/uv"
    args:
      - run
      - --project
      - "/absolute/path/to/BundleWalker"
      - bundlewalker-mcp
      - --workspace
      - "/absolute/path/to/your/bundlewalker-workspace"
    env:
      BUNDLEWALKER_MODEL: "${BUNDLEWALKER_MODEL}"
      OPENAI_API_KEY: "${OPENAI_API_KEY}"
```

Hermes resolves `${VARIABLE}` values from its active environment, including values loaded from its
`.env`, and passes explicitly configured `env` entries to the stdio subprocess. Replace
`OPENAI_API_KEY` when using another provider.

## Reload MCP and confirm discovery

After changing MCP configuration or the Hermes `.env`, reload the integration from Hermes:

```text
/reload-mcp
```

Start a fresh conversation if the current one does not show the updated tools. Tool schemas are
part of the conversation's tool context.

Hermes prefixes discovered tool names to avoid collisions. With the server name `bundlewalker`,
registered names resemble:

```text
mcp_bundlewalker_workspace_status
mcp_bundlewalker_search_concepts
mcp_bundlewalker_ask
```

You normally ask for the capability in natural language instead of naming the prefixed tool.

## Example requests

Try read-only requests first:

- “Show me the status of my BundleWalker knowledge base.”
- “Search the knowledge base for agent evaluation.”
- “Ask the knowledge base what it knows about review-before-persistence, with citations.”
- “Run deterministic lint on the BundleWalker workspace.”
- “Show me the current pending review.”

For write-capable workflows, state the authorization boundary explicitly:

- “Prepare a synthesis about X and show me the complete review, but do not apply it.”
- “Prepare this inline Markdown source for ingestion, but leave the review pending.”
- “Inspect the pending review and summarize the changed paths without applying it.”
- “Apply review REVIEW_ID.”
- “Discard review REVIEW_ID without changing live knowledge.”

Do not authorize apply or discard until you have inspected the complete diff and confirmed the
exact review ID.

## Troubleshooting

### Hermes cannot start the server

Re-establish the shell variables from [Record your local setup values](#record-your-local-setup-values),
then confirm the executable and paths:

```bash
test -x "$UV_COMMAND"
test -f "$PROJECT_ROOT/pyproject.toml"
test -f "$WORKSPACE/bundlewalker.toml"
```

Run BundleWalker's MCP help in a clean environment:

```bash
env -u PYTHONPATH -u VIRTUAL_ENV \
  "$UV_COMMAND" run \
  --project "$PROJECT_ROOT" \
  bundlewalker-mcp --help
```

Then retry:

```bash
hermes mcp test bundlewalker
```

### Read-only deterministic tools work, but model-backed tools fail

For the OpenAI-shaped example, check that both assignments exist without printing their values:

```bash
rg -q '^BUNDLEWALKER_MODEL=.+' "$HERMES_CONFIG_DIR/.env"
rg -q '^OPENAI_API_KEY=.+' "$HERMES_CONFIG_DIR/.env"
```

For another provider, check its credential variable instead. Confirm that the same variable names
appear under `mcp_servers.bundlewalker.env`, then use `/reload-mcp`.

### Tools are missing

Check connection and filtering:

```bash
hermes mcp list
hermes mcp test bundlewalker
hermes mcp configure bundlewalker
```

Reload MCP and start a fresh conversation. A tool excluded by the per-server selector is
intentionally unavailable.

### A preparation is blocked by another review

BundleWalker permits one pending review. Inspect it with `get_pending_review` or from a terminal:

```bash
(
  cd "$WORKSPACE"
  "$UV_COMMAND" run --project "$PROJECT_ROOT" bundlewalker review show
)
```

Apply or discard that exact review before preparing another write. A stale review remains
inspectable but cannot be applied; discard it and prepare a new one. See
[Maintain and recover the bundle](user-guide.md#maintain-and-recover-the-bundle) for the full CLI
recovery workflow.

## Security and data boundaries

- BundleWalker's MCP server is local `stdio`, not a hosted or remote service.
- The configured workspace is fixed for the server process.
- Raw sources, arbitrary workspace files, transaction paths, and credentials are not MCP
  resources.
- MCP ingestion accepts inline `.md` or `.txt` content, not arbitrary local file paths.
- Expose the smallest Hermes tool allowlist that supports your workflow.
- Forward only the environment variables BundleWalker needs.
- Inspect the complete pending diff before applying an exact review ID.
- Accepted source bytes remain under the workspace's `raw/` directory; review sensitive or
  licensed material before publishing the workspace.

## Remove the integration

Disconnect BundleWalker from Hermes:

```bash
hermes mcp remove bundlewalker
```

Then use `/reload-mcp` or start a fresh Hermes session so the removed tools disappear from the
conversation context.

## References

- [BundleWalker host-neutral MCP reference](user-guide.md#use-bundlewalker-through-a-local-mcp-host)
- [BundleWalker model and provider setup](user-guide.md#model-and-provider-setup)
- [Hermes MCP documentation](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp)
- [Hermes CLI reference](https://hermes-agent.nousresearch.com/docs/reference/cli-commands)
- [Hermes configuration documentation](https://hermes-agent.nousresearch.com/docs/user-guide/configuration)
- [Hermes security documentation](https://hermes-agent.nousresearch.com/docs/user-guide/security)
````

- [ ] **Step 3: Verify the guide contains no personal installation data**

Run:

```bash
if rg -n -i 'hendrik|OWC Envoy|/opt/homebrew|9 Sources|4 Topics|2 Entities|4 Syntheses' docs/hermes-mcp-setup.md; then
  printf 'personal installation data found\n' >&2
  exit 1
fi
```

Expected: exits `0` with no matches.

- [ ] **Step 4: Verify the guide names the exact BundleWalker MCP surface**

Run:

```bash
uv run python - <<'PY'
from pathlib import Path

from bundlewalker.interfaces.mcp_schemas import TOOL_SPECS

guide = Path("docs/hermes-mcp-setup.md").read_text(encoding="utf-8")
tool_names = {spec.name for spec in TOOL_SPECS}
assert len(tool_names) == 10
missing = sorted(name for name in tool_names if f"`{name}`" not in guide)
assert not missing, missing
assert "supports_parallel_tool_calls: true" in guide
assert "Do not set `supports_parallel_tool_calls: true`" in guide
print("documented all 10 BundleWalker MCP tools")
PY
```

Expected: prints `documented all 10 BundleWalker MCP tools`.

- [ ] **Step 5: Verify command syntax against live help**

Run:

```bash
uv run bundlewalker-mcp --help
uv run bundlewalker review --help
hermes mcp add --help
hermes mcp --help
```

Expected: every command exits `0`; BundleWalker exposes `--workspace`; Hermes exposes `add`,
`list`, `test`, `configure`, and `remove`; Hermes help says `--args` must be the last option.

- [ ] **Step 6: Review and commit the standalone guide**

Run:

```bash
git diff --check
git diff -- docs/hermes-mcp-setup.md
git status --short
git add docs/hermes-mcp-setup.md
git diff --cached --check
git commit -m "docs: add Hermes MCP setup guide"
```

Expected: only `docs/hermes-mcp-setup.md` is committed; the unrelated backup archive remains
untracked and unstaged.

### Task 2: Link, Synchronize, and Verify the Guide

**Files:**
- Modify: `README.md:144-180`
- Modify: `docs/user-guide.md:422-432`
- Modify: `docs/superpowers/plans/2026-07-16-end-user-guide.md:66-754`

**Interfaces:**
- Consumes: `docs/hermes-mcp-setup.md` from Task 1; the README documentation map; the host-neutral
  MCP section in `docs/user-guide.md`; the embedded-guide synchronization markers documented in
  `CONTRIBUTING.md`.
- Produces: discoverable navigation to the Hermes guide and an exact synchronized embedded copy of
  the canonical user guide.

- [ ] **Step 1: Establish the missing-link baseline**

Run:

```bash
if rg -n -F 'hermes-mcp-setup.md' README.md docs/user-guide.md; then
  printf 'Hermes guide link already exists\n' >&2
  exit 1
fi
```

Expected: exits `0`, proving neither discovery location already links the new guide.

- [ ] **Step 2: Link the guide from README's local MCP section and documentation map**

After the final paragraph of `README.md`'s `## Local MCP server` section, add:

```markdown
Hermes Agent users can follow the dedicated
[Hermes MCP setup guide](docs/hermes-mcp-setup.md) for registration, tool filtering, credential
forwarding, reload, and troubleshooting.
```

In `README.md`'s `## Documentation` list, add after the user-guide item:

```markdown
- The [Hermes MCP Setup Guide](docs/hermes-mcp-setup.md) connects a Hermes Agent installation to
  one local BundleWalker workspace with a minimal, review-first tool surface.
```

- [ ] **Step 3: Link the guide from the host-neutral user-guide section**

In `docs/user-guide.md`, after the introductory paragraph under
`## Use BundleWalker through a local MCP host`, add:

```markdown
If your MCP host is Hermes Agent, follow the dedicated
[Hermes MCP setup guide](hermes-mcp-setup.md) for registration, tool filtering, provider-variable
forwarding, reload, and Hermes-specific troubleshooting.
```

- [ ] **Step 4: Synchronize the historical plan's exact embedded user-guide copy**

Run:

```bash
uv run python - <<'PY'
from pathlib import Path

guide_path = Path("docs/user-guide.md")
plan_path = Path("docs/superpowers/plans/2026-07-16-end-user-guide.md")
start_marker = "Create `docs/user-guide.md` with exactly:\n\n````markdown\n"
end_marker = "\n````\n\n- [ ] **Step 3: Link the guide from the README**"

guide = guide_path.read_text(encoding="utf-8")
plan = plan_path.read_text(encoding="utf-8")
prefix, separator, remainder = plan.partition(start_marker)
assert separator == start_marker
embedded, separator, suffix = remainder.partition(end_marker)
assert separator == end_marker
assert embedded != guide
plan_path.write_text(prefix + start_marker + guide + end_marker + suffix, encoding="utf-8")
PY
```

Expected: only the embedded guide block changes; historical plan content around it remains
unchanged.

- [ ] **Step 5: Verify exact embedded-guide equality**

Run:

```bash
uv run python - <<'PY'
from pathlib import Path

guide = Path("docs/user-guide.md").read_text(encoding="utf-8")
plan = Path("docs/superpowers/plans/2026-07-16-end-user-guide.md").read_text(encoding="utf-8")
start_marker = "Create `docs/user-guide.md` with exactly:\n\n````markdown\n"
end_marker = "\n````\n\n- [ ] **Step 3: Link the guide from the README**"
embedded = plan.split(start_marker, 1)[1].split(end_marker, 1)[0]
assert embedded == guide
print("embedded user guide matches")
PY
```

Expected: prints `embedded user guide matches`.

- [ ] **Step 6: Validate rendered links and heading anchors in affected user documentation**

Run:

```bash
uv run python - <<'PY'
import re
from pathlib import Path
from urllib.parse import unquote

from markdown_it import MarkdownIt

ROOT = Path.cwd().resolve()
HTML_ANCHOR = re.compile(
    r"\b(?:id|name)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s\"'=<>`]+))",
    re.IGNORECASE,
)
MARKDOWN = MarkdownIt("commonmark")
SOURCES = [
    ROOT / "README.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "docs/hermes-mcp-setup.md",
    ROOT / "docs/tutorial.md",
    ROOT / "docs/user-guide.md",
]


def slug(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text).lower()
    text = re.sub(r"[`*_~]", "", text)
    text = re.sub(r"[^\w\- ]", "", text)
    return re.sub(r"[ ]+", "-", text.strip())


def anchors(path: Path) -> set[str]:
    counts: dict[str, int] = {}
    result: set[str] = set()
    tokens = MARKDOWN.parse(path.read_text(encoding="utf-8"))
    for index, token in enumerate(tokens):
        if token.type == "heading_open":
            heading = tokens[index + 1]
            text = "".join(
                child.content
                for child in heading.children or []
                if child.type in {"text", "code_inline", "softbreak", "hardbreak"}
            )
            base = slug(text)
            count = counts.get(base, 0)
            counts[base] = count + 1
            result.add(base if count == 0 else f"{base}-{count}")
        for child in token.children or []:
            if child.type == "html_inline":
                for match in HTML_ANCHOR.finditer(child.content):
                    result.add(next(value for value in match.groups() if value is not None))
        if token.type == "html_block":
            for match in HTML_ANCHOR.finditer(token.content):
                result.add(next(value for value in match.groups() if value is not None))
    return result


errors: list[str] = []
checked = 0
for source in SOURCES:
    for token in MARKDOWN.parse(source.read_text(encoding="utf-8")):
        for child in token.children or []:
            if child.type != "link_open" or not isinstance(href := child.attrGet("href"), str):
                continue
            target = href.strip().split()[0].strip("<>")
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            path_text, separator, fragment = target.partition("#")
            destination = source if not path_text else (source.parent / unquote(path_text)).resolve()
            checked += 1
            if not destination.exists() or ROOT not in (destination, *destination.parents):
                errors.append(f"{source.relative_to(ROOT)} -> {target}: missing or outside repository")
                continue
            if separator and destination.is_file() and unquote(fragment) not in anchors(destination):
                errors.append(f"{source.relative_to(ROOT)} -> {target}: missing anchor")

assert not errors, "\n".join(errors)
print(f"validated {checked} rendered local Markdown links")
PY
```

Expected: prints a positive link count and exits `0` with no missing local file or heading anchor.

- [ ] **Step 7: Run documentation and repository verification**

Run:

```bash
uv run bundlewalker-mcp --help
uv run bundlewalker review --help
hermes mcp add --help
hermes mcp --help
uv run pytest -m 'not eval' -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv lock --check
git diff --check
```

Expected: live help matches the guide; the complete offline suite passes with live-model tests
deselected; Ruff formatting/lint, Pyright, lockfile, and diff-integrity checks pass.

- [ ] **Step 8: Review and commit discovery and synchronization changes**

Run:

```bash
git diff --stat
git diff -- README.md docs/user-guide.md docs/superpowers/plans/2026-07-16-end-user-guide.md
git status --short
git add README.md docs/user-guide.md docs/superpowers/plans/2026-07-16-end-user-guide.md
git diff --cached --check
git commit -m "docs: link Hermes MCP setup guide"
```

Expected: exactly the three discovery/synchronization files are committed; the unrelated backup
archive remains untracked and unstaged.
