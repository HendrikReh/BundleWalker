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
