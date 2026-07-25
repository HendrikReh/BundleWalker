# BundleWalker Local Web UI Design

**Date:** 2026-07-25

**Status:** Design approved; implementation awaits written-spec review

## Summary

BundleWalker will add an explicitly launched, loopback-only local web UI as its third first-party
delivery adapter after the CLI and MCP server. The UI is a review cockpit for one workspace. It
combines concept browsing, lexical search, cited Ask answers, lint results, ingestion preparation,
saved-synthesis preparation, refresh preparation, and exact pending-review resolution in one
browser surface.

The selected implementation is a React and TypeScript single-page application built with Vite,
served together with a small versioned JSON API by a Starlette application in the
`bundlewalker-web` Python process. React owns presentation and temporary view state. The Python
adapter owns browser-session security, request validation, application-contract mapping, and
process lifecycle. Every domain operation calls the existing workspace-bound
`WorkspaceApplication`; the web adapter never calls workflows, repositories, or transaction
functions directly.

Node.js is a contributor and release-build requirement, not an end-user runtime requirement.
Vite's compiled, hashed assets ship inside BundleWalker's wheel and source distribution. The web
server dependencies are installed through a `web` optional extra so existing CLI- and MCP-only
installations stay lean.

The first release remains intentionally local and single-user. It binds an ephemeral port on
`127.0.0.1`, opens a browser with an unguessable bootstrap secret, exchanges that secret for an
in-memory browser session, and rejects requests that fail exact Host, Origin, session, or CSRF
checks. It does not provide remote binding, accounts, collaboration, multiple workspaces, a
daemon, or lifecycle administration.

## Relationship to the Existing Architecture

This design specializes the web portion of the approved
[MCP and Local Web Interface Architecture](2026-07-17-mcp-web-interface-architecture-design.md).
That earlier design remains authoritative for:

- the shared `WorkspaceApplication` facade;
- strict serializable application contracts;
- one workspace per adapter process;
- zero or one durable pending review per workspace;
- opaque review IDs and exact persisted diffs;
- prepare-before-apply semantics;
- cross-adapter review handoff;
- error translation at the application boundary; and
- the rule that models propose while deterministic code validates and persists.

This design does not revise those invariants. It selects the frontend technology, user journey,
web API, local browser security, packaging model, accessibility baseline, and first-release scope
needed to implement the web adapter.

## Current State

BundleWalker is a Python 3.13/3.14 modular monolith with supported macOS and Linux operation and
experimental Windows operation. Its first-party adapters are:

- the Typer CLI; and
- the local MCP `stdio` server.

Both adapters use `WorkspaceApplication`, which already exposes:

- workspace status;
- paginated concept listing, concept reading, and lexical search;
- cited question answering;
- deterministic and optional semantic lint;
- inline and file-based ingestion preparation;
- synthesis preparation;
- synthesis refresh preparation;
- pending-review reading; and
- review apply and discard operations.

The application facade therefore contains the required use cases. The web milestone adds a
delivery adapter and browser experience, not a second orchestration layer.

Active documentation currently describes the local web UI as planned and unimplemented. The
implementation milestone must update that wording only when the corresponding capability is
actually available and verified.

## Goals

1. Provide a graphical review cockpit for one existing BundleWalker workspace.
2. Make exact model-derived changes easier to inspect without weakening review-before-write.
3. Expose Browse, search, Ask, and lint as context alongside review workflows.
4. Support paste and one-file `.md`/`.txt` ingestion.
5. Support prepare, inspect, apply, and discard for ingestion, synthesis, and refresh.
6. Make a pending review prepared by MCP immediately resolvable in the web UI for the same
   workspace.
7. Preserve `WorkspaceApplication` as the only complete-use-case boundary.
8. Keep end-user operation Python-only and package the built frontend with the Python
   distribution.
9. Provide a secure loopback browser session despite the absence of user accounts.
10. Meet an explicit keyboard, responsive-layout, and assistive-technology baseline.
11. Preserve supported macOS/Linux behavior and experimental Windows coverage.

## Non-goals

- Workspace creation, migration, repair, backup, restore, or configuration editing.
- A browser-side workspace chooser or multi-workspace sidebar.
- Remote access, non-loopback binding, TLS termination, accounts, teams, or synchronization.
- A persistent daemon or system service.
- A native desktop wrapper such as Electron or Tauri.
- A mobile-specific application or offline browser mode.
- Raw arbitrary filesystem browsing or browser-provided server paths.
- Rich Markdown editing or direct mutation of workspace files.
- Partial-file apply, selective hunks, review history, or rollback UI.
- Multiple simultaneous pending reviews or a review backlog.
- Streaming responses, WebSockets, background jobs, or a job database.
- Replacing the CLI or MCP server.
- Changing the OKF format, retrieval engine, model workflows, or transaction engine.
- Loading scripts, fonts, analytics, or other assets from a third-party origin.

## Approaches Considered

### Lightweight bundled JavaScript

A Starlette adapter could serve a build-free HTML, CSS, and vanilla JavaScript application. This
would minimize tooling and dependencies while supporting the required API calls.

This was the initial recommendation because it fits BundleWalker's existing Python-first
architecture. It was not selected because the maintainer prefers the stronger component model,
frontend test tooling, and future visual headroom of a TypeScript SPA.

### Server-rendered pages

The Python process could render complete pages or fragments and use small JavaScript enhancements.
This would keep most presentation state on the server.

It was not selected because responsive exact diffs, upload state, concept navigation, lint
filtering, long-running Ask calls, and review-state reconciliation would produce a larger set of
presentation-specific routes and tighter coupling between UI state and server templates.

### React and TypeScript SPA

A Vite-built React application communicates with a small same-origin JSON API. The browser owns
components and temporary view state; Python owns durable state, security, and domain use cases.

This is the selected approach. It intentionally accepts a second contributor toolchain and a
larger dependency-maintenance surface in exchange for clearer component boundaries and a more
capable long-term GUI foundation.

## Target Architecture

```text
Installed user runtime

┌──────────────────────────────────────┐
│ Browser tab                          │
│ React + TypeScript SPA               │
│                                      │
│ Explorer, workbench, responsive diff │
│ forms, query state, temporary UI     │
└──────────────────┬───────────────────┘
                   │ same-origin JSON
                   │ session + CSRF
┌──────────────────▼───────────────────┐
│ bundlewalker-web Python process      │
│ Starlette web adapter                │
│                                      │
│ assets, API mapping, validation,     │
│ browser security, process lifecycle  │
└──────────────────┬───────────────────┘
                   │ direct async calls
┌──────────────────▼───────────────────┐
│ WorkspaceApplication                │
│ existing use cases and contracts     │
└──────────────┬───────────────┬───────┘
               │               │
┌──────────────▼─────┐  ┌──────▼──────────────┐
│ Knowledge core     │  │ Review/transaction  │
│ OKF, retrieval,    │  │ persistence, locks, │
│ workflows, models  │  │ apply and recovery  │
└────────────────────┘  └─────────────────────┘
```

The web adapter is a leaf dependency. `application` never imports `interfaces.web`, and frontend
code knows only web DTOs and URL routes. Browser code cannot import Python application contracts
or construct transaction paths.

### Proposed source shape

```text
frontend/
├── package.json
├── package-lock.json
├── tsconfig.json
├── vite.config.ts
└── src/
    ├── app/                 # application shell, routing, providers
    ├── api/                 # typed request functions and web DTOs
    ├── components/          # reusable visual components
    ├── features/
    │   ├── browse/
    │   ├── ask/
    │   ├── lint/
    │   ├── ingestion/
    │   └── reviews/
    └── test/

src/bundlewalker/interfaces/web/
├── __init__.py
├── api.py                   # capability-shaped API routes
├── app.py                   # Starlette construction and middleware
├── contracts.py             # explicit web request/response DTOs
├── errors.py                # application-to-HTTP mapping
├── security.py              # bootstrap, session, CSRF, Host/Origin
├── server.py                # launch, port selection, browser, shutdown
└── static/                  # Vite production output included in packages
```

The implementation plan may refine filenames, but it must preserve these dependency directions.

## Installation and Launch

The web runtime is installed explicitly:

```bash
pip install "bundlewalker[web]"
```

The console entry point is:

```bash
bundlewalker-web
bundlewalker-web --workspace /path/to/workspace
```

Without `--workspace`, the command discovers the workspace from the current directory using the
same rules as existing workspace-bound commands. It validates the workspace before opening a
browser.

If the optional web dependencies are absent, the entry point exits with a bounded message that
shows the exact `bundlewalker[web]` installation command. It does not expose an import traceback.

The command:

1. discovers and validates one workspace;
2. constructs one `WorkspaceApplication`;
3. binds an ephemeral port on `127.0.0.1`;
4. generates the browser bootstrap secret;
5. starts the local HTTP server;
6. opens the authenticated bootstrap URL in the default browser; and
7. remains attached to the terminal until Ctrl-C or a fatal startup error.

There is no `--host`, daemon mode, browser-side workspace switcher, or persisted server
configuration in the first release. A browser-open failure prints the complete local bootstrap URL
so the user can open it manually.

## Information Architecture

The selected layout is **Explorer + workbench**.

### Persistent Explorer

The left Explorer identifies the workspace and provides:

- Browse concepts;
- Ask;
- Lint;
- Review, with a badge of `1` only when a pending review exists; and
- New ingestion.

The Explorer also shows a compact workspace-health state. It does not expose lifecycle,
configuration, transaction-directory, or raw filesystem controls.

### Workbench

The right workbench displays one active capability. Wide screens retain the Explorer and use the
full remaining width. Narrow screens collapse navigation and switch review diffs from side-by-side
to unified presentation.

On launch:

- if the workspace has a pending review, the UI opens that review; otherwise
- it opens Browse.

This is not a multi-review queue. The workspace invariant remains zero or one pending review.

### Browser routes

Stable client routes support refresh and back/forward navigation:

```text
/browse
/browse/*
/ask
/lint
/ingest
/review/:reviewId
```

The Browse splat carries the URL-encoded hierarchical concept ID, including its type directory,
without exposing an absolute path.

The Starlette application serves the SPA shell for recognized client routes after session
validation. Unknown browser routes return a bounded not-found page rather than silently opening
the workspace.

## Capability Journeys

### Browse and search

Browse initially requests the first bounded concept page. Users can:

- filter by lexical search;
- narrow results by concept type where supported;
- load later result pages;
- open a concept without exposing its absolute path; and
- follow safe internal concept references.

Concept content is rendered from Markdown using an allowlisted local renderer. Raw HTML from
workspace Markdown is not executed. External links are clearly marked and open with safe
`noopener`/`noreferrer` behavior.

### Ask

Ask accepts one bounded question and optional supported model selection when the application
contract permits it. While the request runs, the form shows an operation-specific progress state
and prevents duplicate submission. The result renders the cited Markdown answer and provides
navigation to cited concepts.

Read-only Ask does not create a review.

### Prepare synthesis

The UI provides a distinct **Prepare synthesis** action for a question. It calls
`WorkspaceApplication.prepare_synthesis`, which generates the answer and pending review together.
The returned answer is displayed beside the exact proposal.

The UI does not take a previously returned Ask answer and submit it as trusted model output.
Pressing Prepare synthesis is a separate model-backed operation and may produce an answer that
differs from an earlier read-only Ask response.

### Lint

Lint supports:

- deterministic lint; and
- explicit semantic lint when model configuration is available.

Findings are grouped by severity and concept, and every finding includes non-color status text.
Deterministic errors remain distinct from optional semantic advice. Running lint never mutates the
workspace.

### New ingestion

The ingestion workbench offers:

- paste into a bounded text editor; or
- drag-and-drop/file-picker selection of one `.md` or `.txt` file.

The browser validates suffix, empty content, and configured size limits before submission. The
server repeats all validation authoritatively.

An uploaded file is decoded as text and normalized to an `InlineSource` with a simple safe display
name. The browser never supplies a server-side source or destination path. The first release does
not support multiple files, directories, watched folders, or binary formats.

Successful preparation navigates to the returned pending review. No live `raw/` or `wiki/` content
changes during preparation.

### Prepare refresh

Eligible generated concepts offer **Prepare refresh**. The user supplies a bounded instruction.
The result is:

- `current`, with the model-backed answer and no review; or
- `pending`, with the answer and exact pending review.

The UI handles both outcomes explicitly and never implies that `current` created a transaction.

### Inspect and resolve a review

The review workbench shows:

- review kind and summary;
- opaque review ID in a secondary details area;
- changed files/concepts;
- relevant validation or lint warnings;
- the complete exact diff; and
- Apply and Discard actions for the whole proposal.

The desktop default is side-by-side current/proposed content. A visible control switches between
side-by-side and unified views. Narrow screens default to unified view. Additions and deletions use
signs and labels as well as color.

There is no partial-file or hunk-level apply. Apply and Discard always include the current opaque
review ID. After either operation, the UI reloads workspace status, concepts, lint state, and
pending review before confirming the final state.

A review prepared through MCP is ordinary workspace review state. Opening the web UI on that
workspace displays and resolves it without MCP-specific translation.

## Web API

All JSON endpoints live below `/api/v1`. The API is local and private to the shipped frontend, but
its contracts are explicit and tested rather than relying on arbitrary Pydantic serialization.

The capability-shaped surface is:

| Capability | Method and route | Application operation |
| --- | --- | --- |
| Bootstrap data | `GET /api/v1/workspace` | `status` |
| Concept page | `GET /api/v1/concepts` | `list_concepts` |
| Concept search | `GET /api/v1/concepts/search` | `search_concepts` |
| Concept content | `GET /api/v1/concepts/{concept_id:path}` | `read_concept` |
| Ask | `POST /api/v1/ask` | `ask` |
| Lint | `POST /api/v1/lint` | `lint` |
| Pending review | `GET /api/v1/review` | `get_pending_review` |
| Inline/file ingestion | `POST /api/v1/ingestions` | `prepare_ingestion` |
| Synthesis | `POST /api/v1/syntheses` | `prepare_synthesis` |
| Refresh | `POST /api/v1/refreshes` | `prepare_refresh` |
| Apply | `POST /api/v1/reviews/{review_id}/apply` | `apply_review` |
| Discard | `POST /api/v1/reviews/{review_id}/discard` | `discard_review` |

The implementation may distinguish JSON and multipart ingestion routes if that produces clearer
bounded parsing, but both normalize to `InlineSource`; neither accepts a server path.

### Web DTO rules

Web request and response models:

- are strict Pydantic models at the Python boundary;
- contain only JSON-safe bounded values;
- do not contain absolute paths, provider exceptions, transaction directories, repository
  objects, or model instances;
- use explicit discriminators where a result has multiple states;
- preserve application error codes in a bounded public form; and
- include only UI-required review data already allowed by the application contract.

Frontend TypeScript types are maintained beside the API client. Canonical JSON contract fixtures
are produced from explicit Python DTO examples and consumed by frontend tests. CI fails when
Python response fixtures and TypeScript consumers drift.

Automatic code generation is not required for the first release. It may be introduced later only
if it simplifies rather than obscures the contract-review boundary.

## State Ownership and Concurrency

Server-owned query state includes:

- workspace status;
- concept pages and content;
- search results;
- Ask answers;
- lint results; and
- the pending review.

Browser-only view state includes:

- selected navigation item;
- filters and search input before submission;
- expanded review files;
- side-by-side/unified preference;
- temporary form contents; and
- focus/announcement state.

The frontend may use a small query-state layer, but it must not treat cached values as authority
for mutations. After every successful prepare, apply, or discard operation, it invalidates and
reloads workspace status and pending-review state. Apply and Discard are disabled until that
reconciliation completes.

The UI permits one state-changing request at a time. This is a usability control, not the
correctness mechanism. The application and transaction layers continue to enforce:

- one pending review;
- review-ID matching;
- transaction locking;
- recovery; and
- stale/conflicting operation rejection.

Another first-party adapter may change the workspace while the browser is open. A conflict causes
the UI to reload authoritative state and explain what changed; it never retries a write silently.

## Long-running Operations

Ask, semantic lint, ingestion preparation, synthesis preparation, and refresh may involve model
latency. The first release uses ordinary awaited HTTP requests:

1. React validates and submits once.
2. The workbench shows operation-specific progress and prevents duplicate mutation actions.
3. Starlette awaits the facade call.
4. The response returns either the complete result or a bounded error.
5. React reconciles workspace and review state before enabling later writes.

The first release does not add streaming, WebSockets, polling, persistent jobs, or a background
worker. There is no UI promise that closing a tab or aborting a browser request cancels an
underlying model operation. Reopening or refreshing the UI reloads authoritative pending-review
state.

## Error Model

The web adapter maps `ApplicationErrorCode` values to stable HTTP statuses and bounded response
bodies. The exact table is finalized against the existing error enum during implementation, with
these user behaviors:

- invalid input returns `400` or `422` and identifies the affected field;
- missing concepts or reviews return `404`;
- pending-review, stale-review, or transaction conflicts return `409` and trigger authoritative
  state reload;
- model or configuration failures preserve entered input and show actionable local setup
  guidance;
- unsupported or unavailable optional capability returns a bounded capability error; and
- unexpected failures return a sanitized message and local diagnostic ID while details remain on
  stderr.

React has explicit loading, empty, success, validation, conflict, model-configuration, and
unexpected-error states. It does not render raw Python exceptions or provider responses.

## Local Browser Security

Loopback binding reduces exposure but is not authentication. The process establishes a browser
session before serving workspace data.

### Bootstrap exchange

1. The process generates at least 256 bits of cryptographically secure random material.
2. The startup URL includes that secret in a single-use bootstrap parameter.
3. The bootstrap handler compares it in constant time.
4. A valid exchange creates an unguessable in-memory session and CSRF token.
5. The response sets an `HttpOnly`, `SameSite=Strict`, `Path=/` non-persistent session cookie.
6. The browser is redirected immediately to the same URL without the bootstrap parameter.
7. The bootstrap secret cannot be reused.

No secret, cookie, or CSRF token is written to the workspace. Restarting the process invalidates
all browser sessions.

### Request checks

Every protected request must satisfy:

- exact expected `Host` and selected port;
- loopback-only server binding;
- valid in-memory session cookie; and
- accepted method, path, content type, and bounded body size.

Every state-changing request additionally requires:

- exact same-origin `Origin`; and
- the per-session CSRF token in a dedicated header.

Missing or opaque Origin behavior is defined conservatively and covered by tests. CORS is not
enabled because the frontend and API share one origin.

### Browser hardening

Responses use:

- a restrictive Content Security Policy allowing only packaged same-origin assets;
- `frame-ancestors 'none'`;
- `X-Content-Type-Options: nosniff`;
- a no-referrer policy;
- no-store caching for HTML and API data; and
- long-lived immutable caching only for content-hashed static assets.

The frontend contains no inline script requirement, CDN import, analytics, remote font, or
third-party browser resource.

### Markdown and links

Workspace Markdown is untrusted presentation input. Rendering must:

- disable or sanitize raw HTML;
- allow only required Markdown constructs;
- escape code and text correctly;
- reject executable URL schemes;
- mark external navigation clearly; and
- prevent a workspace document from injecting script, style, event handlers, or arbitrary frames.

### Upload containment

Uploads:

- accept one bounded `.md` or `.txt` file;
- validate extension, media type where useful, bytes, UTF-8 decoding, and text limits;
- reduce the client filename to a valid simple source name;
- never use the client filename as a server path; and
- normalize content through `InlineSource`.

## Frontend Build and Python Packaging

The repository contains a committed JavaScript package lock. Contributor commands provide:

- development server;
- formatting/linting;
- TypeScript checking;
- unit/component tests;
- production build; and
- browser tests.

Vite writes production output directly to the Python web adapter's packaged static directory or
to a staging directory copied there by a deterministic repository command. Production output
uses content-hashed assets and a build manifest suitable for backend integration.

Compiled assets are versioned with the repository. This is deliberate:

- users installing a wheel need no Node.js;
- users building the Python source distribution need no implicit networked frontend build;
- the wheel and source distribution contain the same reviewed UI;
- release tooling can inspect the exact packaged assets; and
- CI can rebuild and fail on any source/output difference.

Generated assets must contain no absolute developer paths, source-map secrets, bootstrap values,
or network origins. Production source maps are omitted unless a later accepted diagnostics design
defines how to ship them safely.

The Python package declares a `web` optional extra containing compatible bounded Starlette and
ASGI-server dependencies. Frontend libraries are locked through the JavaScript lockfile and
included only as compiled browser assets at Python runtime.

## Accessibility and Responsive Behavior

The first release must be usable without a mouse and must not rely on color alone.

Required behavior includes:

- semantic landmarks, headings, forms, tables/lists, and native button behavior;
- one visible page heading and an accurate browser title;
- visible focus and logical tab order;
- focus placement after client navigation, dialog actions, and validation failures;
- non-modal operation where a regular page or inline disclosure suffices;
- programmatic labels and descriptions for every input;
- status and error announcements through appropriate live regions;
- text/sign indicators in addition to diff and lint colors;
- sufficient contrast in default, hover, selected, disabled, and focus states;
- responsive navigation;
- unified diffs on narrow screens;
- horizontal overflow containment for long code or unbroken content; and
- respect for reduced-motion preferences.

Automated accessibility checks complement, but do not replace, keyboard and screen-reader-oriented
manual review.

## Testing Strategy

### Python adapter tests

In-process tests cover:

- application construction and workspace binding;
- every API route and DTO mapping;
- facade dependency injection with deterministic fakes;
- upload parsing and all size/name/content boundaries;
- application-error to HTTP mapping;
- SPA shell/static asset handling;
- launch failure and browser-open fallback; and
- clean shutdown.

Tests do not require live model providers.

### Security tests

Security tests cover:

- missing, invalid, reused, and valid bootstrap secrets;
- session creation and invalidation;
- exact Host enforcement;
- accepted and rejected Origin values;
- missing, invalid, and valid CSRF tokens;
- method/content-type/body-size limits;
- cookie attributes;
- security headers;
- cross-origin and unauthenticated asset/API behavior;
- traversal-shaped concept IDs and upload filenames;
- malicious Markdown and unsafe links; and
- absence of third-party browser resources.

### Frontend tests

Frontend unit and component tests cover:

- Explorer and client routing;
- loading, empty, success, conflict, and error states;
- Browse, search, concept reading, Ask, and lint;
- paste and file ingestion forms;
- synthesis and refresh result variants;
- exact-diff presentation and responsive mode selection;
- Apply/Discard confirmation and reconciliation;
- prevention of duplicate mutations;
- contract fixtures; and
- keyboard/focus/status-announcement behavior.

### Browser smoke

A real-browser smoke suite covers:

1. launch and bootstrap exchange;
2. default Browse behavior without a review;
3. default Review behavior with a pending review;
4. concept browse/search/read;
5. deterministic Ask and lint fakes;
6. inline and uploaded ingestion preparation;
7. exact review inspection;
8. Apply and Discard;
9. synthesis and refresh variants;
10. MCP-prepared review discovery through shared fixtures; and
11. responsive unified-diff behavior.

The required browser smoke runs on Linux CI. Supported macOS receives process-launch and adapter
coverage plus a proportionate browser smoke where CI reliability permits. Windows remains
experimental and does not block the supported-platform gate.

### Repository and distribution gates

The complete gate includes:

- existing Python formatting, lint, strict type checks, tests, audit, and artifact checks;
- frontend formatting/lint, TypeScript check, unit/component tests, and production build;
- a clean generated-asset diff after rebuilding;
- JavaScript dependency audit under the repository's documented severity policy;
- a third-party browser dependency and license-notice inventory;
- wheel and source-distribution content assertions for all required UI assets;
- clean installation of `bundlewalker[web]`;
- `bundlewalker-web` startup/help smokes;
- no-web-extra error-message smoke;
- supported macOS/Linux CI;
- experimental Windows observation;
- CodeQL/dependency review; and
- real-browser smoke.

## Documentation

The implementation updates:

- `README.md` with installation, launch, scope, and a short review workflow;
- `docs/user-guide.md` with Browse, Ask, lint, ingestion, synthesis, refresh, review, shutdown,
  security, and troubleshooting;
- `SUPPORT.md` with the local UI support boundary;
- `CONTRIBUTING.md` with Node setup, frontend commands, generated-asset policy, tests, and
  accessibility expectations;
- architecture documentation that currently says the UI is planned;
- packaging/release documentation for frontend build and artifact verification; and
- the changelog and project metadata appropriate to the eventual release.

Documentation must continue to call the UI local, explicitly launched, single-workspace, and
loopback-only. It must not imply hosted operation or multi-user protection.

## Delivery Sequence

The implementation plan should use test-driven, reviewable slices:

1. frontend toolchain, packaged-asset path, optional dependencies, and entry-point skeleton;
2. secure launch handshake, session, Host/Origin/CSRF protections, and static shell;
3. workspace status plus Browse/search/read;
4. Ask and lint;
5. inline/file ingestion preparation and exact review rendering;
6. Apply and Discard with authoritative reconciliation;
7. synthesis and refresh;
8. responsive/accessibility hardening;
9. browser smoke, distribution verification, and documentation; and
10. final full-repository verification.

Each slice must preserve a usable supported branch state. No documentation may announce the UI as
available before the complete supported gate passes.

## Failure and Recovery

- Startup validation failure occurs before the browser opens.
- Port binding uses the operating system's ephemeral-port allocation; a bind failure exits
  without falling back to a remote or fixed port.
- Browser-open failure leaves the server running and prints the complete bootstrap URL once.
- Model/configuration failure leaves form input available for correction and does not invent a
  review.
- A network or tab interruption is followed by authoritative status/review reload; the UI does
  not assume the underlying operation was cancelled.
- A stale review ID or concurrent adapter change returns a conflict and reloads the current review.
- Ctrl-C shuts down the HTTP server and invalidates the in-memory browser session.
- Existing transaction recovery remains authoritative for a prepared review after process
  interruption.
- Missing or corrupt packaged frontend assets cause a bounded startup error, not a partially
  functioning server.

## Acceptance Criteria

The local web UI milestone is complete only when:

1. `bundlewalker[web]` installs from clean wheel and source-distribution environments.
2. `bundlewalker-web` discovers or accepts exactly one workspace, binds only to
   `127.0.0.1` on an ephemeral port, and opens or prints the authenticated URL.
3. A valid bootstrap exchange creates the in-memory session and removes the secret from the
   visible URL.
4. Host, Origin, session, CSRF, content-type, body-size, Markdown, and upload security tests pass.
5. Browse, search, concept read, Ask, and deterministic/semantic lint work through
   `WorkspaceApplication`.
6. Paste and one-file `.md`/`.txt` ingestion prepare an exact pending review without mutating live
   content.
7. Synthesis and refresh prepare or return their documented result states through the facade.
8. The UI displays the one workspace pending review, including one prepared through MCP.
9. Side-by-side and unified complete diffs are available, with unified default on narrow screens.
10. Apply and Discard require the matching review ID and reconcile authoritative state.
11. React never calls workflows, repositories, transactions, or filesystem paths directly.
12. Node.js is unnecessary for installed end-user operation.
13. Rebuilt frontend assets match the reviewed packaged assets exactly.
14. Keyboard, focus, announcement, responsive, and non-color accessibility requirements pass.
15. Python, frontend, security, browser, distribution, macOS/Linux, audit, and code-scanning gates
    pass.
16. Windows results remain visible and experimental rather than silently unsupported.
17. Active documentation describes the implemented UI accurately and preserves local-only scope.
