# Security Policy

## Supported versions

Before BundleWalker 1.0, security fixes are provided for the latest published version only.
Older releases remain available as historical artifacts but do not receive security updates.

| Version | Security support |
| --- | --- |
| Latest published version | Supported |
| Older versions | Not supported |

## Report a vulnerability

Do not report vulnerabilities in a public issue.

Use [GitHub private vulnerability reporting](https://github.com/HendrikReh/BundleWalker/security/advisories/new)
to report suspected credential exposure, path traversal, review bypass, unsafe transaction or
recovery behavior, MCP workspace-boundary violations, dependency vulnerabilities, or another
security-sensitive defect.

Include the affected BundleWalker version, operating system, impact, reproduction steps, and the
smallest safe diagnostic evidence. Do not include real credentials, private source material, or a
user knowledge base. If private reporting is temporarily unavailable, open a public issue asking
the maintainer to establish private contact without disclosing vulnerability details.

Reports are handled on a best-effort basis. The maintainer will validate impact, coordinate a fix
and disclosure when possible, and credit reporters who request attribution.

## Security boundaries

BundleWalker is a local application, but configured model-provider calls may send documented
workflow context to the selected provider. The local MCP server is a foreground `stdio` process
bound to one workspace at startup. BundleWalker does not provide a hosted service, remote MCP
transport, automatic telemetry, or remote crash reporting.

Security reports and support bundles must not contain credentials, raw source content, generated
knowledge content, or unnecessary absolute paths by default.
