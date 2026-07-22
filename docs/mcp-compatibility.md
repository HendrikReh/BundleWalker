# MCP host compatibility

This record distinguishes a documented configuration from an observed compatibility run. A host
is certified only for the capabilities listed as observed; BundleWalker's model-provider behavior
is a separate boundary from MCP transport and host behavior.

## Host status

| Host | Status | Configuration | Evidence scope |
| --- | --- | --- | --- |
| Hermes Agent | Supported integration | [Hermes MCP setup](hermes-mcp-setup.md) | Existing Hermes-specific registration, filtering, credential-forwarding, reload, and removal guide; not re-run as part of the 2026-07-21 VS Code certification. |
| Visual Studio Code with GitHub Copilot | Certified local MCP host | [VS Code/Copilot setup](vscode-copilot-mcp-setup.md) | Local source-checkout launch, ten-tool discovery, deterministic calls, approvals, exact-ID discard and apply, restart persistence, search, and resources on the named macOS environment below. |
| Other local `stdio` hosts | Unverified | [Host-neutral MCP reference](user-guide.md#use-bundlewalker-through-a-local-mcp-host) | The protocol contract is documented, but no host-specific certification claim is made. |

Certification does not mean that a host can bypass BundleWalker's review, validation, workspace,
provider, or transaction boundaries.

## VS Code certification environment

The observed run took place on 2026-07-21 with these exact components:

| Component | Observed value |
| --- | --- |
| Operating system | macOS 26.5.1 build 25F80, arm64 |
| Visual Studio Code | Visual Studio Code 1.129.1, commit `8a7abeba6e03ea3af87bfbce9a1b7e48fed567b8`, arm64 |
| Copilot host integration | Built-in GitHub Copilot 0.57.0, local Agent mode |
| BundleWalker | BundleWalker 0.4.0rc2 from the current source checkout |
| Python | CPython 3.13.5 |
| `uv` | 0.10.11 |
| MCP implementation | MCP Python SDK 1.28.1 |
| Protocol implementation constant | MCP protocol 2025-11-25 |
| PydanticAI | 2.10.0 |
| Transport | Local `stdio` subprocess |
| Workspace | Disposable initialized workspace outside the repository |
| VS Code sandbox | Disabled for this run |

The server log showed the local process entering `Running` state and discovering ten tools after
startup and after an explicit restart. The source-checkout command was:

```text
/absolute/path/to/uv run --project /absolute/path/to/BundleWalker \
  bundlewalker-mcp --workspace /absolute/path/to/disposable/knowledge
```

Absolute temporary paths and credentials are intentionally not retained in the repository.

## Capability results

| Capability | Result | Observed evidence |
| --- | --- | --- |
| Local `stdio` startup | Pass | VS Code started the production `bundlewalker-mcp` entry point and reported `Running`. |
| Tool discovery | Pass | VS Code reported all ten tools. |
| Deterministic status | Pass | Copilot called `workspace_status` and returned workspace `knowledge`, config version `1`, zero initial concepts, and no pending review. |
| Lexical search | Pass | Copilot called `search_concepts`; it returned zero results before acceptance and the accepted Source afterward. |
| Deterministic lint | Pass | Copilot called `lint` with semantic mode disabled and received zero findings. |
| Pending-review inspection | Pass | Copilot called `get_pending_review` and read exact IDs, status, summary, changed paths, and diff state. |
| Tool approval | Pass | VS Code required explicit approval for review-resolution calls and exposed the tool input before execution. |
| Review discard | Pass | Copilot matched review `a56e8c0e1e4147818a4475916587022b`, called `discard_review`, and returned zero live concepts; filesystem verification found no accepted raw or concept file. |
| Review restart persistence | Pass | Review `4157b6e4313e45f9bdd81310498715d5` remained pending after VS Code restarted the MCP process. |
| Review apply | Pass | Copilot called `apply_review` with that exact ID; status then showed one Source and no pending review. |
| Resource listing and read | Pass | `MCP: Browse Resources` listed the concept template and accepted Source. VS Code opened `bundlewalker://concept/sources/3f02617d30af-apply-candidate` as read-only Markdown with metadata, body, raw path, and citation. |
| Server diagnostics | Pass | `MCP: List Servers` exposed restart and `Show Output`; stderr traceback details were visible in the MCP output channel. |
| Transaction recovery | Project evidence | The offline transaction recovery suite covers interrupted prepared, accepted, raw-persisted, swapping, and live phases. The certification run observed clean MCP restart persistence but did not deliberately crash VS Code in every transaction phase. |
| Model-backed preparation | Provider-dependent; transport observed | VS Code invoked `prepare_ingestion` and displayed progress, request approval, and bounded structured errors. A certification-only PydanticAI `TestModel` did not produce a valid ingestion result, so no claim is made that a production provider was certified. |
| Installed release path | Not covered | The run used the current source checkout. It does not certify installation from production PyPI. |
| Linux host run | Not covered | BundleWalker and VS Code support Linux, but this host run was macOS-only. |
| Windows host run | Not covered | BundleWalker treats Windows as experimental, and the VS Code MCP sandbox is unavailable there. |

The exact synthetic review IDs and concept ID above belong only to the disposable run and are
included to make the evidence sequence auditable. They are not examples to reuse in another
workspace.

## Tool inventory

VS Code discovered the complete BundleWalker tool surface:

| Group | Tools | Certification note |
| --- | --- | --- |
| Read and inspect | `workspace_status`, `search_concepts`, `ask`, `lint`, `get_pending_review` | Status, search, deterministic lint, and pending-review inspection were called successfully. `ask` was discovered but not called because it requires a real configured BundleWalker provider. |
| Prepare private review state | `prepare_ingestion`, `prepare_synthesis`, `prepare_refresh` | All were discovered. `prepare_ingestion` reached the server through VS Code; successful model output was not certified with a production provider. The other preparation tools were not executed. |
| Resolve exact review | `apply_review`, `discard_review` | Both were executed successfully with exact lowercase 32-character review IDs. |

Discovery verifies that VS Code parsed the MCP schemas and made the tools selectable. It does not
turn an unexecuted provider-backed tool into an observed success.

## Review evidence procedure

The run used a disposable initialized workspace and this sequence:

1. Start BundleWalker from workspace-scoped `.vscode/mcp.json` and observe ten tools.
2. Call `workspace_status`, `search_concepts`, and non-semantic `lint` through Copilot.
3. Confirm that the initial resource browser has no concept resources.
4. Exercise `prepare_ingestion` transport and approval behavior without providing a real provider
   credential; record the bounded `model_failed` result rather than treating it as success.
5. Seed a standards-valid pending ingestion transaction with BundleWalker's deterministic
   transaction API so host-side review resolution can be tested without a remote provider.
6. Through Copilot, call `get_pending_review`, verify the exact ID, call `discard_review`, then
   call `workspace_status`; independently confirm that live content did not change.
7. Seed a second valid pending transaction and inspect its ID through Copilot.
8. Restart the `bundlewalker` server from VS Code and confirm that the same review is still
   pending.
9. Through Copilot, call `apply_review` with the exact ID, then call `search_concepts` and
   `workspace_status`.
10. Run `MCP: Browse Resources` and open the accepted concept URI as read-only Markdown.

The deterministic seed bypassed only model generation. It still used BundleWalker's production
change validation, durable transaction format, digest checks, apply/discard logic, OKF repository,
and production MCP tools for every host-visible review decision.

## Transaction recovery evidence

BundleWalker's transaction recovery is broader than a clean MCP process restart. The repository's
offline suite exercises abrupt termination in authenticated transaction phases and idempotent
second recovery:

```bash
uv run pytest tests/test_transaction_crash_recovery.py -q
```

The complete default suite remains:

```bash
uv run pytest -m 'not eval' -q
```

Passing those tests supports the transaction recovery claim for BundleWalker itself. The VS Code
certification specifically adds evidence that a pending review remains addressable across a host-
initiated MCP server restart and can then be applied by its exact ID.

## Limitations and interpretation

- GitHub Copilot's conversation model and BundleWalker's PydanticAI model are independent. Copilot
  sign-in does not supply `BUNDLEWALKER_MODEL` or a provider credential to the subprocess.
- PydanticAI's string `test` selects an internal test model, but that model is not guaranteed to
  generate a semantically valid BundleWalker change set. `test:model` is not a valid runtime
  provider identifier. Neither belongs in end-user setup.
- Model-backed success depends on the selected provider, current model, credential, network,
  provider policy, and cost. This record makes no provider-availability or model-quality claim.
- The source-checkout run proves compatibility with the tested checkout. It does not prove the
  production-PyPI installation path or a future BundleWalker version.
- macOS and Linux are BundleWalker's supported platforms, with Windows experimental. This single
  host certification run covers only the exact macOS environment above.
- VS Code can sandbox local MCP servers on macOS and Linux, but the certification run did not test
  sandbox policy. BundleWalker requires write access to its bound workspace, and model-backed
  operations require access to their provider.
- MCP resources are read-only context. Write authority remains in the explicit review-resolution
  tools and the exact persisted review ID.

## Recertification checklist

Repeat the host workflow when changing any of these boundaries:

- BundleWalker release or MCP tool/resource schema;
- MCP Python SDK or protocol constant;
- VS Code or built-in GitHub Copilot version;
- supported operating-system policy;
- subprocess command shape, sandbox policy, or trust behavior; or
- transaction review or recovery semantics.

Record exact versions, platform, transport, tool count, calls actually observed, approval
behavior, restart outcome, resource read, limitations, and whether the run used an installed
artifact or source checkout. Never copy provider credentials into evidence.

## References

- [VS Code: add and manage MCP servers](https://code.visualstudio.com/docs/agent-customization/mcp-servers)
- [VS Code: MCP configuration reference](https://code.visualstudio.com/docs/agents/reference/mcp-configuration)
- [BundleWalker VS Code/Copilot setup](vscode-copilot-mcp-setup.md)
- [BundleWalker host-neutral MCP reference](user-guide.md#use-bundlewalker-through-a-local-mcp-host)
- [BundleWalker Hermes setup](hermes-mcp-setup.md)
- [BundleWalker workspace compatibility](workspace-compatibility.md)
