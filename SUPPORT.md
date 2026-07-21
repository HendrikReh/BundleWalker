# BundleWalker Support

BundleWalker is moving from proof of concept toward a public beta for technical solo users.
Support is community-based and has no guaranteed response time or service-level agreement.

## Supported scope

- macOS and Linux are the officially supported operating systems.
- Python 3.13 and 3.14 are supported when their required CI jobs pass.
- Windows is experimental and may fail because some filesystem and locking behavior is
  POSIX-specific.
- The supported product surface is the local CLI and workspace-bound MCP `stdio` server.
- Current ingestion accepts one regular UTF-8 Markdown or text file at a time.
- The reviewed local-workspace envelope is 1,000 knowledge documents, approximately 10 MiB of
  wiki content, and a 50,000-character ingestion source on four named macOS/Linux reference
  environments. It excludes remote-model latency and is not a promise for every machine or
  filesystem; see the [reviewed performance and capacity evidence](docs/performance-and-capacity.md).

Hosted operation, remote MCP transport, multi-user synchronization, a web UI, embeddings, vector
databases, additional source formats, and automatic Git operations are outside the first beta.

## Ask for help or report a bug

Search [existing issues](https://github.com/HendrikReh/BundleWalker/issues) first. If the problem
is new, open an issue with the BundleWalker version, operating system, Python version, installation
method, command or MCP host, expected behavior, actual behavior, and a minimal reproduction.

Remove credentials, private source material, generated knowledge, and unnecessary absolute paths
from logs or diagnostics before posting them.

You may create an opt-in redacted JSON support report with
`bundlewalker doctor PATH --report bundlewalker-support.json`. Review the report before attaching
it to a public issue. The report omits credentials, model values, workspace content, filesystem
paths, host identity, and transaction or review identifiers, but it is still your responsibility
to confirm that the diagnostic context is appropriate to share.

If report creation fails after the target is created, BundleWalker retains the owner-only partial
target because automatic pathname cleanup could delete an unrelated replacement.
Inspect and remove the newly created report target when appropriate before retrying.

Security-sensitive reports do not belong in public issues. Follow the
[Security Policy](SECURITY.md) instead.

## Maintenance policy

Before 1.0, only the latest published version receives fixes. Compatibility commitments are
documented per release, and breaking changes must be called out in the changelog and migration
guidance.
