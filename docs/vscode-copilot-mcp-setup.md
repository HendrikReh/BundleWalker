# Connect Visual Studio Code and GitHub Copilot to BundleWalker over MCP

Use this guide after installing BundleWalker and initializing a workspace. Visual Studio Code
starts `bundlewalker-mcp` as a local subprocess, communicates over `stdio`, and makes the bound
workspace's tools and read-only resources available to the local GitHub Copilot agent.

For the complete resource, tool-schema, and durable-review contracts, use the
[host-neutral MCP reference](user-guide.md#use-bundlewalker-through-a-local-mcp-host). For the
observed host versions and evidence, see the [MCP compatibility record](mcp-compatibility.md).

## Understand the two model connections

GitHub Copilot chooses whether to call an MCP tool. BundleWalker's own PydanticAI model performs
model-backed knowledge work inside `ask`, semantic `lint`, and the three `prepare_*` tools. These
are separate model connections: signing in to Copilot does not configure BundleWalker's model or
provider credential.

Deterministic tools such as `workspace_status`, `search_concepts`, non-semantic `lint`,
`get_pending_review`, `apply_review`, and `discard_review` do not contact BundleWalker's model
provider.

## Prerequisites

You need:

- Visual Studio Code with GitHub Copilot chat and local Agent mode available;
- BundleWalker `0.4.0rc2` installed as a tool, or a source checkout prepared with
  `uv sync --locked`;
- an initialized workspace containing `bundlewalker.toml`; and
- absolute paths to the MCP executable or source checkout and to the knowledge workspace.

Check the paths in a terminal before editing VS Code configuration:

```bash
BUNDLEWALKER_MCP="$(command -v bundlewalker-mcp)"
WORKSPACE="/absolute/path/to/your/knowledge-workspace"

test -x "$BUNDLEWALKER_MCP"
test -f "$WORKSPACE/bundlewalker.toml"
printf 'MCP executable: %s\nWorkspace: %s\n' "$BUNDLEWALKER_MCP" "$WORKSPACE"
```

If `command -v bundlewalker-mcp` is empty, use the source-checkout configuration below.

## Configure an installed BundleWalker command

Open the folder in which you want to use Copilot, create `.vscode/mcp.json`, and replace both
absolute placeholders:

```json
{
  "servers": {
    "bundlewalker": {
      "type": "stdio",
      "command": "/absolute/path/to/bundlewalker-mcp",
      "args": [
        "--workspace",
        "/absolute/path/to/your/knowledge-workspace"
      ]
    }
  }
}
```

The workspace path is fixed when the process starts. BundleWalker tools cannot switch to another
workspace and do not accept arbitrary local source paths.

## Configure a source checkout

For development or checkout-based use, run the project entry point through `uv`. Replace all three
absolute paths:

```json
{
  "servers": {
    "bundlewalker": {
      "type": "stdio",
      "command": "/absolute/path/to/uv",
      "args": [
        "run",
        "--project",
        "/absolute/path/to/BundleWalker",
        "bundlewalker-mcp",
        "--workspace",
        "/absolute/path/to/your/knowledge-workspace"
      ]
    }
  }
}
```

Run `command -v uv` to obtain the command path. This form executes the selected checkout, not an
installed release.

## Add the BundleWalker model and provider credential

Read-only deterministic verification works without this section. Complete it before using `ask`,
semantic lint, or any `prepare_*` tool.

VS Code supports input variables so a secret does not have to appear in `.vscode/mcp.json`. The
following OpenAI-shaped example is illustrative; replace the model ID and provider variable when
using another PydanticAI provider:

```json
{
  "inputs": [
    {
      "type": "promptString",
      "id": "bundlewalker-model",
      "description": "BundleWalker PydanticAI model string"
    },
    {
      "type": "promptString",
      "id": "bundlewalker-openai-key",
      "description": "OpenAI API key used by BundleWalker",
      "password": true
    }
  ],
  "servers": {
    "bundlewalker": {
      "type": "stdio",
      "command": "/absolute/path/to/bundlewalker-mcp",
      "args": [
        "--workspace",
        "/absolute/path/to/your/knowledge-workspace"
      ],
      "env": {
        "BUNDLEWALKER_MODEL": "${input:bundlewalker-model}",
        "OPENAI_API_KEY": "${input:bundlewalker-openai-key}"
      }
    }
  }
}
```

VS Code prompts for an `${input:...}` value when the server first needs it and stores the value
securely for reuse. The model string is not secret; the provider key is.

Alternatively, add `"envFile": "/absolute/path/to/bundlewalker-mcp.env"` to the server object and
store the variables in that file:

```dotenv
BUNDLEWALKER_MODEL=openai:<current-model-id>
OPENAI_API_KEY=<your-api-key>
```

Keep an `envFile` outside source control, restrict its file permissions, and use the credential
name required by the selected provider. Do not use `test` or `test:model` as end-user model
configuration; PydanticAI's built-in test model is not a production ingestion model.

The official [VS Code MCP configuration reference](https://code.visualstudio.com/docs/agents/reference/mcp-configuration)
documents `stdio`, `env`, `envFile`, input variables, and sandbox fields.

## Review and start the server

Local MCP servers execute commands on your machine. Review every resolved command and absolute
path before trusting it.

1. Open the Command Palette and run `MCP: Open Workspace Folder MCP Configuration`.
2. Inspect `.vscode/mcp.json` and confirm that only the intended BundleWalker executable and
   workspace are named.
3. Run `MCP: List Servers`, select `bundlewalker`, and start it.
4. Confirm that VS Code reports the server as running and discovers ten tools.

VS Code can also start a server from the inline action above its `mcp.json` entry. The official
[MCP server management guide](https://code.visualstudio.com/docs/agent-customization/mcp-servers)
explains that local servers can run arbitrary code and describes VS Code's trust behavior.

## Choose the smallest tool set

In Copilot Chat, select `Configure Tools` and expand the `bundlewalker` server. Start with:

- `workspace_status`
- `search_concepts`
- `lint`
- `get_pending_review`

Add `ask` only when BundleWalker may contact its configured provider for a read-only answer. Add
`prepare_ingestion`, `prepare_synthesis`, and `prepare_refresh` only when Copilot may create one
private pending review. Add `apply_review` and `discard_review` only when the session may resolve
the exact current review ID.

Tool selection limits what Copilot can request. BundleWalker's workspace binding, strict schemas,
pending-review state, and exact-ID revalidation remain authoritative.

## Verify read-only behavior first

Ask the local Agent:

```text
Use only BundleWalker MCP tools. Call workspace_status, search_concepts for
"review-first knowledge", and non-semantic lint. Report the workspace name,
concept counts, search result count, lint finding count, and pending-review status.
```

Confirm that Copilot shows calls to the `bundlewalker` MCP server and that no provider credential
is required. Non-semantic lint uses `{"semantic": false}`.

To inspect resources, run `MCP: Browse Resources`, choose `bundlewalker`, and open a concept URI:

```text
bundlewalker://concept/<concept_id>
```

Concept resources are read-only. When a review is pending,
`bundlewalker://review/pending` exposes its exact persisted diff.

## Perform a reviewed write sequentially

Never combine preparation and acceptance into an unreviewed instruction. Use this sequence:

1. Ask Copilot to call one `prepare_*` tool and stop.
2. Inspect the complete diff from `get_pending_review` or
   `bundlewalker://review/pending`.
3. Record the lowercase 32-character review ID.
4. In a separate prompt, choose either `apply_review` or `discard_review` with that exact ID.
5. Approve the VS Code tool confirmation only after checking the tool name and input.
6. Call `workspace_status` and `search_concepts` to verify the outcome.

Example preparation prompt:

```text
Call BundleWalker's prepare_ingestion with source_name notes.md and the Markdown
content below. Do not apply it. Return the exact review ID and complete diff.
```

Example decision prompt:

```text
Call get_pending_review. If and only if its ID is <REVIEW_ID>, call discard_review
with that exact ID. Then call workspace_status. Do not apply the review.
```

Discarding removes private pending state without changing live `raw/` or `wiki/` content.
Applying revalidates the exact review before committing accepted source bytes and compiled
knowledge atomically.

## Restart, inspect logs, and recover

After changing `.vscode/mcp.json` or its credential source, run `MCP: List Servers`, choose
`bundlewalker`, and select Restart. A pending review is durable across MCP process restarts.

If startup or a tool call fails:

1. Run `MCP: List Servers`.
2. Select `bundlewalker` and choose `Show Output`.
3. Check the executable path, `--project` path when used, workspace path, model string, provider
   credential name, and sandbox rules.
4. Run `bundlewalker doctor /absolute/path/to/workspace` in a terminal.
5. Use `bundlewalker review show` to inspect durable pending state before retrying a mutation.

If tool definitions appear stale, run `MCP: Reset Cached Tools` and restart the server. For the
full CLI recovery sequence, see [Maintain and recover the bundle](user-guide.md#maintain-and-recover-the-bundle).

## Optional VS Code sandbox

VS Code can sandbox local `stdio` servers on macOS and Linux. If enabled, BundleWalker needs read
and write access to the bound knowledge workspace. Model-backed tools also need network access to
the configured provider domain. An incomplete sandbox policy can make deterministic reads work
while provider calls or reviewed writes fail. Windows does not currently provide this VS Code MCP
sandbox.

Review the official sandbox documentation before setting `sandboxEnabled`; the compatibility run
did not enable the VS Code sandbox.

## Remove the connection

Delete the `bundlewalker` entry from `.vscode/mcp.json`, or remove the file if it contains no other
servers. Then run `MCP: List Servers` to confirm that the server and tools are gone. Run
`MCP: Reset Trust` if you also want VS Code to forget its trust decision.

Removing the MCP configuration does not delete or change the BundleWalker workspace.

## Related documentation

- [MCP compatibility record](mcp-compatibility.md)
- [Host-neutral MCP reference](user-guide.md#use-bundlewalker-through-a-local-mcp-host)
- [Model and provider setup](user-guide.md#model-and-provider-setup)
- [Hermes MCP setup](hermes-mcp-setup.md)
- [Workspace compatibility and portable backups](workspace-compatibility.md)
- [VS Code: add and manage MCP servers](https://code.visualstudio.com/docs/agent-customization/mcp-servers)
- [VS Code: MCP configuration reference](https://code.visualstudio.com/docs/agents/reference/mcp-configuration)
