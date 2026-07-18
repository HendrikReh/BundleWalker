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

Hosted operation, remote MCP transport, multi-user synchronization, a web UI, embeddings, vector
databases, additional source formats, and automatic Git operations are outside the first beta.

## Ask for help or report a bug

Search [existing issues](https://github.com/HendrikReh/BundleWalker/issues) first. If the problem
is new, open an issue with the BundleWalker version, operating system, Python version, installation
method, command or MCP host, expected behavior, actual behavior, and a minimal reproduction.

Remove credentials, private source material, generated knowledge, and unnecessary absolute paths
from logs or diagnostics before posting them.

Security-sensitive reports do not belong in public issues. Follow the
[Security Policy](SECURITY.md) instead.

## Maintenance policy

Before 1.0, only the latest published version receives fixes. Compatibility commitments are
documented per release, and breaking changes must be called out in the changelog and migration
guidance.
