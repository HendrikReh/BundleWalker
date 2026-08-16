# BundleWalker Local Web UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a secure, loopback-only React review cockpit that exposes BundleWalker's existing workspace, knowledge, lint, ingestion, synthesis, refresh, and pending-review use cases through one local browser session.

**Architecture:** A Vite-built React/TypeScript SPA is packaged inside the Python distribution and served by a Starlette adapter in `bundlewalker-web`. The adapter maps a versioned same-origin JSON API to the existing `WorkspaceApplication`; React owns presentation and temporary view state, while Python owns security, workspace state, and every domain operation.

**Tech Stack:** Python 3.13/3.14, Pydantic, Starlette `>=1.3.1,<2`, Uvicorn `>=0.51,<1`, React 19.2.8, React Router 7.18.1, TanStack Query 5.101.4, TypeScript 5.9.3, Vite 8.1.5, Vitest 4.1.10, Testing Library 16.3.2, Playwright 1.62.0, Node 22.22.3.

## Global Constraints

- The server binds only an ephemeral port on `127.0.0.1`; there is no remote-bind option.
- One process is bound to one discovered or explicitly supplied workspace.
- A workspace has zero or one pending review; the UI must not create a review backlog abstraction.
- Every domain operation calls `WorkspaceApplication`; web code must not call workflows, repositories, transaction functions, or workspace paths directly.
- Preparation never mutates live `raw/` or `wiki/` content; Apply and Discard require the matching opaque review ID.
- React owns presentation and temporary view state; Python owns browser security, durable state, and domain operations.
- The bootstrap secret contains at least 256 bits, is single-use, and is exchanged for an in-memory `HttpOnly`, `SameSite=Strict`, `Path=/` session cookie.
- Every request validates the exact Host; state-changing requests also validate the exact Origin and a session-bound CSRF header.
- The browser loads no third-party scripts, fonts, analytics, or other remote assets.
- The first release accepts pasted text or one bounded UTF-8 `.md`/`.txt` file and normalizes both to `InlineSource`.
- Web source content is bounded to `1_000_000` Unicode characters and `4_000_000` UTF-8 bytes; the complete JSON request body is bounded to `4_100_000` bytes.
- Wide screens default to side-by-side exact diffs; narrow screens default to unified diffs; neither mode relies on color alone.
- Installed users need Python only. Node.js is required only for contributor, CI, and release asset builds.
- macOS and Linux are supported; Windows remains experimental and non-blocking.
- The UI does not add workspace initialization, migration, repair, configuration editing, multi-workspace operation, remote access, accounts, rich Markdown editing, partial apply, streaming, WebSockets, or background jobs.

---

## File and Responsibility Map

### Frontend source

- `frontend/package.json`: exact JavaScript dependency and command contract.
- `frontend/package-lock.json`: reproducible dependency graph.
- `frontend/tsconfig.json`, `frontend/tsconfig.app.json`: strict TypeScript boundaries.
- `frontend/vite.config.ts`: React build, packaged output, Vitest, and manifest settings.
- `frontend/eslint.config.js`: TypeScript/React lint policy.
- `frontend/index.html`: CSP-compatible SPA shell without inline script.
- `frontend/src/main.tsx`: React root and provider composition.
- `frontend/src/app/App.tsx`: route shell and global navigation.
- `frontend/src/app/routes.tsx`: browser route definitions.
- `frontend/src/api/types.ts`: explicit web DTO TypeScript types.
- `frontend/src/api/client.ts`: same-origin fetch, CSRF, and bounded error parsing.
- `frontend/src/api/queries.ts`: TanStack Query keys and capability hooks.
- `frontend/src/components/`: Markdown, status, error, progress, form, and diff primitives.
- `frontend/src/features/`: Browse, Ask, lint, ingestion, review, synthesis, and refresh screens.
- `frontend/src/styles/`: tokens, layout, responsive, focus, diff, and reduced-motion rules.
- `frontend/src/test/`: Vitest setup and canonical Python-contract fixtures.
- `frontend/e2e/`: Playwright browser journeys.

### Python web adapter

- `src/bundlewalker/interfaces/web/__init__.py`: public web-adapter exports only.
- `src/bundlewalker/interfaces/web/contracts.py`: strict request/response DTOs and explicit mapping.
- `src/bundlewalker/interfaces/web/errors.py`: `ApplicationErrorCode` to HTTP response mapping.
- `src/bundlewalker/interfaces/web/security.py`: bootstrap, session, Host, Origin, CSRF, and headers.
- `src/bundlewalker/interfaces/web/api.py`: `/api/v1` route handlers that call `WorkspaceApplication`.
- `src/bundlewalker/interfaces/web/app.py`: Starlette route and middleware assembly.
- `src/bundlewalker/interfaces/web/server.py`: workspace discovery, loopback socket, browser open, Uvicorn lifecycle, and command entry point.
- `src/bundlewalker/interfaces/web/static/`: committed Vite production output and manifest.

### Tests and automation

- `tests/interfaces/web/conftest.py`: workspace application, fake runners, and authenticated client fixtures.
- `tests/interfaces/web/test_contracts.py`: web DTO and canonical fixture coverage.
- `tests/interfaces/web/test_errors.py`: complete application-error mapping.
- `tests/interfaces/web/test_security.py`: bootstrap/session/Host/Origin/CSRF/header coverage.
- `tests/interfaces/web/test_server.py`: loopback launch, browser fallback, and shutdown.
- `tests/interfaces/web/test_browse_api.py`: workspace and concept reads.
- `tests/interfaces/web/test_knowledge_api.py`: Ask and lint.
- `tests/interfaces/web/test_ingestion_api.py`: inline/file-text ingestion.
- `tests/interfaces/web/test_review_api.py`: inspect/apply/discard and cross-adapter state.
- `tests/interfaces/web/test_synthesis_api.py`: synthesis and refresh variants.
- `tests/interfaces/web/test_assets.py`: packaged asset and build-manifest assertions.
- `scripts/generate_web_contract_fixtures.py`: deterministic Python DTO examples consumed by Vitest.
- `.github/workflows/ci.yml`: Node checks, asset reproducibility, browser smoke, and web artifact smokes.
- `THIRD_PARTY_NOTICES.md`: shipped browser dependency notices.

### Documentation and metadata

- `pyproject.toml`, `uv.lock`: optional web runtime, dev test availability, entry point, and package assets.
- `README.md`, `docs/user-guide.md`, `SUPPORT.md`, `CONTRIBUTING.md`: implemented user and contributor guidance.
- `CHANGELOG.md`: release-facing capability record.
- `docs/superpowers/specs/2026-07-17-mcp-web-interface-architecture-design.md`: replace future-tense web wording after verification.
- `docs/superpowers/specs/2026-07-25-local-web-ui-design.md`: advance status after implementation verification.

---

### Task 1: Establish the Reproducible React Build

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/package-lock.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.app.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/eslint.config.js`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/app/App.tsx`
- Create: `frontend/src/styles/base.css`
- Create: `frontend/src/test/setup.ts`
- Create: `frontend/src/app/App.test.tsx`
- Create: `src/bundlewalker/interfaces/web/static/`
- Create: `tests/interfaces/web/test_assets.py`
- Modify: `.gitignore`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: no earlier task.
- Produces: `npm run build` writes a CSP-compatible `index.html`, hashed assets, and `.vite/manifest.json` to `src/bundlewalker/interfaces/web/static/`.

- [ ] **Step 1: Write the failing packaged-asset test**

```python
# tests/interfaces/web/test_assets.py
from importlib.resources import files


def test_web_distribution_contains_vite_entrypoint_and_manifest() -> None:
    static = files("bundlewalker.interfaces.web").joinpath("static")
    assert static.joinpath("index.html").is_file()
    assert static.joinpath(".vite", "manifest.json").is_file()
    html = static.joinpath("index.html").read_text(encoding="utf-8")
    assert "<script type=\"module\"" in html
    assert "http://" not in html
    assert "https://" not in html
    assert all(not asset.name.endswith(".map") for asset in static.joinpath("assets").iterdir())
```

- [ ] **Step 2: Run the test and confirm the package does not exist**

Run: `uv run pytest tests/interfaces/web/test_assets.py -q`

Expected: FAIL because `bundlewalker.interfaces.web` and its static assets do not exist.

- [ ] **Step 3: Add the exact frontend package contract**

Create `frontend/package.json` with:

```json
{
  "name": "bundlewalker-web",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "engines": {"node": "22.22.3"},
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "test": "vitest run",
    "lint": "eslint .",
    "format:check": "prettier --check .",
    "format:write": "prettier --write ."
  },
  "dependencies": {
    "@tanstack/react-query": "5.101.4",
    "react": "19.2.8",
    "react-dom": "19.2.8",
    "react-markdown": "10.1.0",
    "react-router-dom": "7.18.1",
    "remark-gfm": "4.0.1"
  },
  "devDependencies": {
    "@testing-library/react": "16.3.2",
    "@testing-library/user-event": "14.6.1",
    "@types/react": "19.2.17",
    "@types/react-dom": "19.2.3",
    "@vitejs/plugin-react": "6.0.4",
    "eslint": "10.8.0",
    "eslint-plugin-react-hooks": "7.1.1",
    "eslint-plugin-react-refresh": "0.5.3",
    "jsdom": "29.1.1",
    "prettier": "3.9.6",
    "typescript": "5.9.3",
    "typescript-eslint": "8.65.0",
    "vite": "8.1.5",
    "vitest": "4.1.10"
  }
}
```

Run `cd frontend && npm install --package-lock-only --ignore-scripts` and commit the generated
`package-lock.json`. Do not use version ranges. TypeScript remains at `5.9.3` because the selected
`typescript-eslint` release declares support below TypeScript 6.1; do not upgrade TypeScript
independently of that peer contract.

- [ ] **Step 4: Add strict Vite, TypeScript, ESLint, and Vitest configuration**

Configure `vite.config.ts` to:

```ts
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../src/bundlewalker/interfaces/web/static",
    emptyOutDir: true,
    manifest: true,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
  },
});
```

Use strict TypeScript with `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`, and
`noImplicitOverride`. Configure ESLint's TypeScript, React Hooks, and React Refresh recommended
rules. Configure Prettier only for frontend files.

- [ ] **Step 5: Add the smallest tested React shell**

```tsx
// frontend/src/app/App.tsx
export function App() {
  return (
    <div className="app-shell">
      <aside aria-label="Workspace">
        <strong>BundleWalker</strong>
      </aside>
      <main>
        <h1>Local review cockpit</h1>
      </main>
    </div>
  );
}
```

Test it with `screen.getByRole("heading", {name: "Local review cockpit"})` and
`screen.getByRole("complementary", {name: "Workspace"})`.

- [ ] **Step 6: Build and include the assets in Python artifacts**

Add `src/bundlewalker/interfaces/web/__init__.py` with the project SPDX header. Configure Hatch to
include `src/bundlewalker/interfaces/web/static/**` in wheels and source distributions. Keep the
generated static directory tracked; ignore only `frontend/node_modules/`, `frontend/coverage/`,
and `frontend/test-results/`.

Run:

```bash
cd frontend
npm ci
npm run format:check
npm run lint
npm run test
npm run build
cd ..
uv run pytest tests/interfaces/web/test_assets.py -q
```

Expected: all commands PASS and `git status --short` shows the reviewed source plus hashed output.

- [ ] **Step 7: Commit**

```bash
git add .gitignore pyproject.toml frontend src/bundlewalker/interfaces/web tests/interfaces/web/test_assets.py
git commit -m "build: add packaged React web shell"
```

---

### Task 2: Add the Secure Local Server and Entry Point

**Files:**
- Create: `src/bundlewalker/interfaces/web/security.py`
- Create: `src/bundlewalker/interfaces/web/app.py`
- Create: `src/bundlewalker/interfaces/web/server.py`
- Create: `tests/interfaces/web/conftest.py`
- Create: `tests/interfaces/web/test_security.py`
- Create: `tests/interfaces/web/test_server.py`
- Modify: `src/bundlewalker/interfaces/web/__init__.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`

**Interfaces:**
- Consumes: packaged static assets from Task 1.
- Produces: `BrowserSessionStore`, `create_web_app(...)`, `bind_loopback_socket()`, `serve_web(...)`, `AuthenticatedWebClient`, and the `bundlewalker-web` entry point.

- [ ] **Step 1: Write failing bootstrap and request-security tests**

In `tests/interfaces/web/conftest.py`, define an `AuthenticatedWebClient` wrapper around
Starlette's `TestClient` with `get(path)`, `post_json(path, body)`, `csrf_token`, and
`expected_origin` members. Its constructor performs the bootstrap exchange once, reads the CSRF
token from the test session store, and applies exact Host/Origin/CSRF headers only in
`post_json`. Provide separate unauthenticated `client` and authenticated `authenticated_client`
fixtures so negative tests cannot inherit credentials accidentally.

```python
def test_bootstrap_is_single_use_and_redirects_to_clean_browse_url(client) -> None:
    response = client.get("/bootstrap?token=correct-secret", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/browse"
    assert "bundlewalker_session=" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    assert client.get("/bootstrap?token=correct-secret").status_code == 403


def test_mutation_requires_exact_origin_and_csrf(authenticated_client) -> None:
    assert authenticated_client.post("/api/v1/probe").status_code == 403
    assert authenticated_client.post(
        "/api/v1/probe",
        headers={
            "Origin": "http://127.0.0.1:43123",
            "X-BundleWalker-CSRF": authenticated_client.csrf_token,
        },
    ).status_code == 204
```

Also cover wrong Host, wrong port, missing session, wrong Origin, wrong CSRF, unsupported content
type, excessive request size, security headers, no-store HTML/API caching, and immutable hashed
asset caching.

- [ ] **Step 2: Run the security tests and confirm they fail**

Run: `uv run pytest tests/interfaces/web/test_security.py -q`

Expected: FAIL because the security store and Starlette app do not exist.

- [ ] **Step 3: Implement the in-memory bootstrap and session store**

Define:

```python
@dataclass(frozen=True, slots=True)
class BrowserSession:
    session_id: str
    csrf_token: str


class BrowserSessionStore:
    def __init__(self, bootstrap_secret: str) -> None: ...
    def exchange(self, candidate: str) -> BrowserSession | None: ...
    def get(self, session_id: str) -> BrowserSession | None: ...
    def clear(self) -> None: ...
```

Generate the startup secret with `secrets.token_urlsafe(32)`, compare bootstrap values with
`secrets.compare_digest`, delete the usable bootstrap digest after one successful exchange, and
generate independent 256-bit session and CSRF values. Never log any of them.

- [ ] **Step 4: Implement the secured static Starlette application**

Define:

```python
def create_web_app(
    application: WorkspaceApplication,
    *,
    expected_host: str,
    sessions: BrowserSessionStore,
    static_dir: Traversable | None = None,
) -> Starlette:
    ...
```

The route order must be:

1. `/bootstrap`;
2. authenticated `/api/v1/probe` used only by focused tests until Task 3 removes it;
3. authenticated hashed static assets; and
4. authenticated recognized SPA routes.

Middleware must reject any Host other than `expected_host`, require the session outside
`/bootstrap`, and require exact `Origin` plus `X-BundleWalker-CSRF` on POST/PUT/PATCH/DELETE.
Return CSP, `frame-ancestors 'none'`, `nosniff`, and no-referrer headers on every response.

- [ ] **Step 5: Write failing loopback lifecycle tests**

Test that `bind_loopback_socket()` returns host `127.0.0.1` with a nonzero ephemeral port, that
`serve_web()` discovers an explicit workspace before calling the browser opener, that browser-open
failure prints the complete authenticated URL without terminating the server setup path, and that
shutdown clears the session store.

Run: `uv run pytest tests/interfaces/web/test_server.py -q`

Expected: FAIL because lifecycle helpers do not exist.

- [ ] **Step 6: Implement the command and optional-extra behavior**

Add:

```toml
[project.optional-dependencies]
web = ["starlette>=1.3.1,<2", "uvicorn>=0.51,<1"]

[project.scripts]
bundlewalker-web = "bundlewalker.interfaces.web.server:main"
```

Make the same constraints available to the dev group so the default repository test environment
can import web tests. Implement `main(argv: Sequence[str] | None = None)` with `argparse`, an
optional `--workspace Path`, bounded application-error output, a pre-bound loopback socket, and
`uvicorn.Server.serve(sockets=[socket])`. The optional-dependency import guard must print:

```text
Error: local web UI dependencies are not installed; install with pip install "bundlewalker[web]"
```

Run `uv lock`, then run:

```bash
uv run pytest tests/interfaces/web/test_security.py tests/interfaces/web/test_server.py -q
uv run bundlewalker-web --help
```

Expected: PASS; help shows only `--workspace` and standard help.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock src/bundlewalker/interfaces/web tests/interfaces/web
git commit -m "feat: add secure local web server"
```

---

### Task 3: Define Web DTOs, Error Mapping, and Contract Fixtures

**Files:**
- Create: `src/bundlewalker/interfaces/web/contracts.py`
- Create: `src/bundlewalker/interfaces/web/errors.py`
- Create: `tests/interfaces/web/test_contracts.py`
- Create: `tests/interfaces/web/test_errors.py`
- Create: `scripts/generate_web_contract_fixtures.py`
- Create: `frontend/src/api/types.ts`
- Create: `frontend/src/test/fixtures/contracts.json`
- Create: `frontend/src/api/types.test.ts`

**Interfaces:**
- Consumes: `ApplicationError`, `ApplicationErrorCode`, and application result models.
- Produces: strict `Web*Request`/`Web*Response` models, `map_application_error(error)`, explicit result mappers, and canonical JSON consumed by TypeScript tests.

- [ ] **Step 1: Write failing strict-contract tests**

Test that unknown fields fail, question/source/model limits match application constants, review
responses contain no absolute paths, refresh uses discriminated `current`/`pending` states, and
workspace responses contain the session CSRF token without containing the session ID.

```python
def test_workspace_response_contains_safe_status_and_csrf() -> None:
    response = to_web_workspace(STATUS, csrf_token="csrf")
    assert response.csrf_token == "csrf"
    assert response.pending_review is None
    assert "workspace_path" not in response.model_dump()
    assert "session_id" not in response.model_dump()
```

- [ ] **Step 2: Write failing complete error-map tests**

Parametrize every `ApplicationErrorCode` from `src/bundlewalker/application/errors.py`. Require
this complete status map:

```python
EXPECTED_STATUS = {
    ApplicationErrorCode.INVALID_INPUT: 422,
    ApplicationErrorCode.CONFIGURATION_ERROR: 400,
    ApplicationErrorCode.WORKSPACE_ERROR: 500,
    ApplicationErrorCode.CONCEPT_NOT_FOUND: 404,
    ApplicationErrorCode.OKF_ERROR: 500,
    ApplicationErrorCode.CHANGE_INVALID: 422,
    ApplicationErrorCode.MODEL_FAILED: 502,
    ApplicationErrorCode.REVIEW_PENDING: 409,
    ApplicationErrorCode.REVIEW_NOT_FOUND: 404,
    ApplicationErrorCode.REVIEW_ID_MISMATCH: 409,
    ApplicationErrorCode.REVIEW_STALE: 409,
    ApplicationErrorCode.TRANSACTION_FAILED: 500,
    ApplicationErrorCode.WORKSPACE_INCOMPATIBLE: 409,
    ApplicationErrorCode.BACKUP_INVALID: 400,
    ApplicationErrorCode.BACKUP_FAILED: 500,
    ApplicationErrorCode.RESTORE_TARGET_INVALID: 400,
    ApplicationErrorCode.MIGRATION_UNAVAILABLE: 409,
    ApplicationErrorCode.MIGRATION_FAILED: 500,
    ApplicationErrorCode.DIAGNOSTIC_FAILED: 500,
}
```

Require a response body shaped as:

```json
{
  "error": {
    "code": "review_stale",
    "message": "review is stale",
    "retryable": false,
    "review_id": null
  }
}
```

Run: `uv run pytest tests/interfaces/web/test_contracts.py tests/interfaces/web/test_errors.py -q`

Expected: FAIL because the web models and mapping do not exist.

- [ ] **Step 3: Implement explicit Pydantic web models and mappers**

Create strict models for:

- `WebWorkspaceResponse`;
- `WebConceptPageResponse`, `WebConceptResponse`, `WebSearchResponse`;
- `WebAskRequest`, `WebAnswerResponse`;
- `WebLintRequest`, `WebLintResponse`;
- `WebIngestionRequest`, `WebIngestionResponse`;
- `WebSynthesisRequest`, `WebSynthesisResponse`;
- `WebRefreshRequest`, `WebRefreshResponse`;
- `WebReviewResponse`, `WebMutationResponse`; and
- `WebErrorResponse`, including optional `review_id` and `diagnostic_id`.

Use named mapping functions including
`to_web_workspace(status: WorkspaceStatus, csrf_token: str) -> WebWorkspaceResponse` and
`to_web_review(review: ReviewResult) -> WebReviewResponse`. Never call `model_dump()` on an
application result directly in a route.
Define `MAX_WEB_SOURCE_BYTES = 4_000_000` and `MAX_WEB_REQUEST_BYTES = 4_100_000`; validate both
the decoded source bytes and the complete request before model work.

Add an unexpected-exception handler that emits a fresh opaque diagnostic ID, writes the traceback
only to stderr logging, and returns a generic `500` `WebErrorResponse`. Test that provider text,
source text, absolute paths, and exception representations never enter that response.

- [ ] **Step 4: Generate and type-check canonical fixtures**

Implement `scripts/generate_web_contract_fixtures.py` so it creates deterministic examples and
writes sorted, indented JSON to `frontend/src/test/fixtures/contracts.json`. In
`frontend/src/api/types.ts`, define matching readonly TypeScript types and discriminated unions.
The Vitest contract test must import the JSON and assert the `current` and `pending` branches can be
narrowed without casts.

Run:

```bash
uv run python scripts/generate_web_contract_fixtures.py
cd frontend
npm run test -- src/api/types.test.ts
cd ..
git diff --exit-code frontend/src/test/fixtures/contracts.json
```

Expected: PASS and fixture regeneration produces no diff.

- [ ] **Step 5: Commit**

```bash
git add src/bundlewalker/interfaces/web scripts/generate_web_contract_fixtures.py tests/interfaces/web frontend/src/api
git commit -m "feat: define local web API contracts"
```

---

### Task 4: Deliver Workspace Status, Browse, Search, and Concept Reading

**Files:**
- Create: `src/bundlewalker/interfaces/web/api.py`
- Modify: `tests/interfaces/web/conftest.py`
- Create: `tests/interfaces/web/test_browse_api.py`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/queries.ts`
- Create: `frontend/src/app/routes.tsx`
- Create: `frontend/src/components/MarkdownContent.tsx`
- Create: `frontend/src/components/RequestError.tsx`
- Create: `frontend/src/features/browse/BrowsePage.tsx`
- Create: `frontend/src/features/browse/ConceptPage.tsx`
- Create: `frontend/src/features/browse/BrowsePage.test.tsx`
- Modify: `src/bundlewalker/interfaces/web/app.py`
- Modify: `frontend/src/app/App.tsx`
- Modify: `frontend/src/main.tsx`

**Interfaces:**
- Consumes: Task 2 authenticated Starlette app and Task 3 DTO mappers.
- Produces: `create_api_routes(application) -> tuple[Route, ...]`, `ApiClient`, query keys, and the Explorer + Browse workbench.

- [ ] **Step 1: Write failing authenticated browse API tests**

Cover:

```python
async def test_workspace_endpoint_returns_status_and_csrf(authenticated_client) -> None:
    response = authenticated_client.get("/api/v1/workspace")
    assert response.status_code == 200
    assert response.json()["display_name"] == "knowledge"
    assert response.json()["csrf_token"] == authenticated_client.csrf_token


async def test_hierarchical_concept_id_uses_path_converter(authenticated_client) -> None:
    response = authenticated_client.get("/api/v1/concepts/topics/agents")
    assert response.status_code == 200
    assert response.json()["concept_id"] == "topics/agents"
```

Also test bounded pagination, cursor pass-through, lexical query/type/limit parameters, invalid
dot segments, missing concepts, and no absolute paths.

- [ ] **Step 2: Implement the read-only API routes**

Add:

```text
GET /api/v1/workspace
GET /api/v1/concepts
GET /api/v1/concepts/search
GET /api/v1/concepts/{concept_id:path}
```

Register `/concepts/search` before the path-converter route so `search` cannot be interpreted as a
concept ID. Remove the temporary `/api/v1/probe` route from Task 2 when these real API routes are
mounted.

Decode hierarchical IDs once, reject `.`/`..` path segments before facade use, call only the
matching facade method, and map `ApplicationError` through Task 3.

Run: `uv run pytest tests/interfaces/web/test_browse_api.py -q`

Expected: PASS.

- [ ] **Step 3: Write failing frontend navigation and Markdown tests**

Test:

- Reviews is first when workspace status contains a pending review, otherwise Browse is first;
- the Explorer exposes Browse, Ask, Lint, Review, and New ingestion;
- search sends the submitted query once;
- later concept pages append without duplicates;
- raw HTML renders as text, `javascript:` links are absent, external links use
  `rel="noopener noreferrer"`; and
- opening `topics/agents` works through the `/browse/*` splat route.

Run: `cd frontend && npm run test -- src/features/browse`

Expected: FAIL because the client and screens do not exist.

- [ ] **Step 4: Implement the authenticated client and Browse screens**

`ApiClient` must:

- always use relative same-origin URLs;
- parse only the expected JSON success/error shapes;
- store the CSRF token obtained from `/api/v1/workspace` in memory;
- add the CSRF header only for state-changing requests; and
- turn bounded web errors into an `ApiError` without rendering raw response text.

Compose `BrowserRouter` and `QueryClientProvider` in `main.tsx`. Render Markdown with
`react-markdown` and `remark-gfm` without `rehype-raw`; provide safe link renderers.

Run:

```bash
cd frontend
npm run test -- src/features/browse src/components/MarkdownContent.tsx
npm run build
cd ..
uv run pytest tests/interfaces/web/test_browse_api.py tests/interfaces/web/test_assets.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bundlewalker/interfaces/web tests/interfaces/web frontend
git commit -m "feat: add local concept explorer"
```

---

### Task 5: Add Ask and Lint Vertical Slices

**Files:**
- Create: `tests/interfaces/web/test_knowledge_api.py`
- Create: `frontend/src/components/OperationProgress.tsx`
- Create: `frontend/src/features/ask/AskPage.tsx`
- Create: `frontend/src/features/ask/AskPage.test.tsx`
- Create: `frontend/src/features/lint/LintPage.tsx`
- Create: `frontend/src/features/lint/LintPage.test.tsx`
- Modify: `src/bundlewalker/interfaces/web/api.py`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/queries.ts`
- Modify: `frontend/src/app/routes.tsx`

**Interfaces:**
- Consumes: `WebAskRequest`, `WebLintRequest`, `WorkspaceApplication.ask`, and
  `WorkspaceApplication.lint`.
- Produces: `/api/v1/ask`, `/api/v1/lint`, `AskPage`, and `LintPage`.

- [ ] **Step 1: Write failing Ask and lint API tests**

Test valid read-only Ask, question limits, deterministic lint, semantic lint with an explicit
model, configuration failure preservation, and that neither operation creates or resolves a
review.

```python
async def test_ask_returns_cited_markdown_without_review(authenticated_client) -> None:
    before = authenticated_client.get("/api/v1/review").json()
    response = authenticated_client.post_json("/api/v1/ask", {"question": "What do agents use?"})
    assert response.status_code == 200
    assert "Agents can use tools" in response.json()["markdown"]
    assert authenticated_client.get("/api/v1/review").json() == before
```

Run: `uv run pytest tests/interfaces/web/test_knowledge_api.py -q`

Expected: FAIL with missing routes.

- [ ] **Step 2: Implement Ask and lint routes**

Validate with Task 3 DTOs, call facade methods exactly once, and map answers/findings explicitly.
Do not add streaming, polling, or server jobs.

Run: `uv run pytest tests/interfaces/web/test_knowledge_api.py -q`

Expected: PASS.

- [ ] **Step 3: Write failing Ask and lint component tests**

Require:

- progress text while the promise is pending;
- duplicate submit disabled;
- preserved question/semantic selection after bounded failure;
- cited Markdown links use `MarkdownContent`;
- deterministic findings remain distinct from semantic findings;
- severity includes visible text; and
- model selection is optional and bounded.

- [ ] **Step 4: Implement the screens and query mutations**

Use a regular request/response mutation for each action. Do not expose a cancellation button that
implies provider cancellation. Announce completion/failure through an `aria-live="polite"` status.

Run:

```bash
cd frontend
npm run test -- src/features/ask src/features/lint
npm run build
cd ..
uv run pytest tests/interfaces/web/test_knowledge_api.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bundlewalker/interfaces/web/api.py tests/interfaces/web/test_knowledge_api.py frontend
git commit -m "feat: add web ask and lint workbenches"
```

---

### Task 6: Add Paste and Single-File Ingestion Preparation

**Files:**
- Create: `tests/interfaces/web/test_ingestion_api.py`
- Create: `frontend/src/features/ingestion/IngestionPage.tsx`
- Create: `frontend/src/features/ingestion/IngestionPage.test.tsx`
- Modify: `src/bundlewalker/interfaces/web/api.py`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/queries.ts`
- Modify: `frontend/src/app/routes.tsx`

**Interfaces:**
- Consumes: `WebIngestionRequest`, `InlineSource`, and
  `WorkspaceApplication.prepare_ingestion`.
- Produces: `POST /api/v1/ingestions` and the paste/file ingestion workbench.

- [ ] **Step 1: Write failing ingestion API boundary tests**

Cover:

- valid inline `.md` and `.txt`;
- duplicate and pending discriminated results;
- empty, oversized, invalid UTF-8-equivalent input, unsupported suffix, separators, dot names,
  and control characters;
- review-pending conflict before runner work;
- browser filename never becomes a server path; and
- live `raw/`/`wiki/` bytes remain unchanged after preparation.

Use JSON only:

```json
{"source_name":"notes.md","content":"# Notes\n\nEvidence.","model":null}
```

Run: `uv run pytest tests/interfaces/web/test_ingestion_api.py -q`

Expected: FAIL with missing route.

- [ ] **Step 2: Implement the ingestion route**

Construct `InlineSource(source_name=request.source_name, content=request.content)` and call
`prepare_ingestion` exactly once. Return `duplicate` without navigation data; return `pending`
with the exact web review response. Never accept or create a client-selected filesystem path.

Run: `uv run pytest tests/interfaces/web/test_ingestion_api.py -q`

Expected: PASS.

- [ ] **Step 3: Write failing paste, picker, and drag/drop tests**

Use Testing Library's `userEvent.upload` with one `File`. Require:

- only one selected file;
- `.md`/`.txt` accept filtering plus repeated client validation;
- `File.text()` content and basename sent as JSON;
- paste and file modes cannot submit simultaneously;
- entered text survives a bounded error;
- duplicate shows a no-change result; and
- pending navigates to `/review/{review_id}`.

- [ ] **Step 4: Implement the ingestion workbench**

Use one accessible mode selector, one text area or file drop target, explicit size/help copy, and
one Prepare action. The drop target must remain operable by keyboard through its associated native
file input.

Run:

```bash
cd frontend
npm run test -- src/features/ingestion
npm run build
cd ..
uv run pytest tests/interfaces/web/test_ingestion_api.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bundlewalker/interfaces/web/api.py tests/interfaces/web/test_ingestion_api.py frontend
git commit -m "feat: prepare ingestion from the web cockpit"
```

---

### Task 7: Add Exact Review Inspection, Apply, Discard, and MCP Handoff

**Files:**
- Create: `tests/interfaces/web/test_review_api.py`
- Create: `frontend/src/components/ReviewDiff.tsx`
- Create: `frontend/src/components/ReviewDiff.test.tsx`
- Create: `frontend/src/features/review/ReviewPage.tsx`
- Create: `frontend/src/features/review/ReviewPage.test.tsx`
- Modify: `src/bundlewalker/interfaces/web/api.py`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/queries.ts`
- Modify: `frontend/src/app/routes.tsx`
- Modify: `frontend/src/styles/base.css`

**Interfaces:**
- Consumes: `get_pending_review`, `apply_review(review_id)`, `discard_review(review_id)`, and
  Task 6 pending navigation.
- Produces: `GET /api/v1/review`,
  `POST /api/v1/reviews/{review_id}/apply`,
  `POST /api/v1/reviews/{review_id}/discard`, and `ReviewPage`.

- [ ] **Step 1: Write failing review API tests**

Test no review, exact persisted review, matching apply/discard, wrong ID, stale review, repeat
resolution, CSRF/Origin rejection, authoritative post-mutation status, and this cross-adapter
journey:

```python
async def test_mcp_prepared_review_is_resolved_through_web(workspace, web_client) -> None:
    mcp_application = WorkspaceApplication(workspace, FAKE_DEPENDENCIES)
    prepared = await mcp_application.prepare_synthesis(
        "What do agents use?", explicit_model="test:model"
    )
    shown = web_client.get("/api/v1/review").json()
    assert shown["review_id"] == prepared.review.review_id
    applied = web_client.post_json(
        f"/api/v1/reviews/{prepared.review.review_id}/apply", {}
    )
    assert applied.json()["status"] == "applied"
    assert await mcp_application.get_pending_review() is None
```

- [ ] **Step 2: Implement review routes with authoritative IDs**

The route ID is passed unchanged to the facade. Do not fetch then apply a different ID. After a
successful mutation, return the mutation response; the frontend must reload workspace/review
queries rather than trusting the old cache.

Run: `uv run pytest tests/interfaces/web/test_review_api.py -q`

Expected: PASS.

- [ ] **Step 3: Write failing exact-diff and resolution component tests**

Require:

- review kind, summary, changed paths, and opaque ID details;
- complete diff text present in the DOM;
- visible `+`/`-` markers plus labels;
- side-by-side default at wide media query;
- unified default at narrow media query;
- a manual mode toggle;
- whole-proposal Apply/Discard only;
- confirmation before each resolution;
- both controls disabled during mutation and reconciliation; and
- conflict reloads and announces the current review rather than retrying.

- [ ] **Step 4: Implement `ReviewDiff` and `ReviewPage`**

Parse the persisted unified diff for presentation only; preserve the original complete diff string
as the evidence source. A parse failure must fall back to a labeled preformatted unified diff, not
hide content. On Apply/Discard success:

```ts
await Promise.all([
  queryClient.invalidateQueries({queryKey: queryKeys.workspace}),
  queryClient.invalidateQueries({queryKey: queryKeys.review}),
  queryClient.invalidateQueries({queryKey: queryKeys.concepts}),
  queryClient.invalidateQueries({queryKey: queryKeys.lint}),
]);
navigate("/browse");
```

Run:

```bash
cd frontend
npm run test -- src/components/ReviewDiff.test.tsx src/features/review
npm run build
cd ..
uv run pytest tests/interfaces/web/test_review_api.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bundlewalker/interfaces/web/api.py tests/interfaces/web/test_review_api.py frontend
git commit -m "feat: review and resolve exact web proposals"
```

---

### Task 8: Add Synthesis and Refresh Preparation

**Files:**
- Create: `tests/interfaces/web/test_synthesis_api.py`
- Create: `frontend/src/features/ask/SynthesisAction.tsx`
- Create: `frontend/src/features/ask/SynthesisAction.test.tsx`
- Create: `frontend/src/features/browse/RefreshPage.tsx`
- Create: `frontend/src/features/browse/RefreshPage.test.tsx`
- Modify: `src/bundlewalker/interfaces/web/api.py`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/queries.ts`
- Modify: `frontend/src/app/routes.tsx`
- Modify: `frontend/src/features/ask/AskPage.tsx`
- Modify: `frontend/src/features/browse/ConceptPage.tsx`

**Interfaces:**
- Consumes: `prepare_synthesis(question, explicit_model)` and
  `prepare_refresh(instruction, concept_id, explicit_model)`.
- Produces: `POST /api/v1/syntheses`, `POST /api/v1/refreshes`, distinct Prepare synthesis UI,
  and eligible-concept refresh UI.

- [ ] **Step 1: Write failing synthesis/refresh API tests**

Test:

- synthesis returns the generated answer and mandatory review;
- synthesis is a separate call from read-only Ask;
- pending-review conflict occurs before normal provider work where the facade guarantees it;
- refresh `current` returns an answer and no review;
- refresh `pending` returns the answer and exact review;
- empty/oversized instruction and invalid concept ID fail safely; and
- non-Synthesis refresh targets retain the existing application error behavior.

- [ ] **Step 2: Implement both preparation routes**

Use Task 3 discriminated web results. Do not accept a prior browser answer as synthesis content.
Do not manufacture a transaction for a `current` refresh.

Run: `uv run pytest tests/interfaces/web/test_synthesis_api.py -q`

Expected: PASS.

- [ ] **Step 3: Write failing frontend behavior tests**

Require:

- Ask and Prepare synthesis are visibly distinct actions;
- Prepare synthesis submits the question through its own endpoint;
- returned answer remains visible beside the pending-review link;
- only eligible generated concepts expose Prepare refresh;
- `current` announces no changes;
- `pending` navigates to the review; and
- model/configuration errors preserve question/instruction text.

- [ ] **Step 4: Implement synthesis and refresh screens**

Keep read-only Ask unchanged. Add one explicit Prepare synthesis action and one refresh route
`/refresh/*`, with an encoded hierarchical concept ID. Use the shared progress,
Markdown, error, and query-invalidation components.

Run:

```bash
cd frontend
npm run test -- src/features/ask src/features/browse
npm run build
cd ..
uv run pytest tests/interfaces/web/test_synthesis_api.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bundlewalker/interfaces/web/api.py tests/interfaces/web/test_synthesis_api.py frontend
git commit -m "feat: prepare synthesis and refresh in the web UI"
```

---

### Task 9: Complete Accessibility, Responsive Behavior, and Browser Smokes

**Files:**
- Create: `frontend/playwright.config.ts`
- Create: `frontend/e2e/launch-and-browse.spec.ts`
- Create: `frontend/e2e/review-workflows.spec.ts`
- Create: `frontend/e2e/security.spec.ts`
- Create: `frontend/src/test/accessibility.test.tsx`
- Create: `scripts/run_web_smoke.py`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `frontend/src/styles/base.css`
- Modify: `frontend/src/app/App.tsx`
- Modify: all frontend feature screens touched by audit findings

**Interfaces:**
- Consumes: complete authenticated UI from Tasks 1–8.
- Produces: keyboard/assistive-technology baseline and deterministic real-browser smoke commands.

- [ ] **Step 1: Add Playwright and accessibility dependencies**

Add exact dev dependencies:

```json
"@axe-core/playwright": "4.12.1",
"@playwright/test": "1.62.0",
"axe-core": "4.12.1"
```

Add scripts:

```json
"test:e2e": "playwright test",
"test:a11y": "vitest run src/test/accessibility.test.tsx"
```

Regenerate `package-lock.json` with `npm install --package-lock-only --ignore-scripts`.

- [ ] **Step 2: Write failing keyboard and accessibility tests**

Cover visible focus, skip link, single page heading, labeled inputs, focus placement after route
change and validation error, live completion/error announcements, no color-only diff/lint state,
reduced motion, and axe scans with no serious/critical violations.

Run: `cd frontend && npm run test:a11y`

Expected: FAIL on the first unimplemented accessibility assertion.

- [ ] **Step 3: Implement the accessibility and responsive fixes**

Add semantic `header`/`nav`/`aside`/`main`, skip link, route-title/focus management, status regions,
non-color labels, focus rings, mobile navigation, narrow unified diff, long-line containment, and:

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    scroll-behavior: auto !important;
    transition-duration: 0.01ms !important;
    animation-duration: 0.01ms !important;
  }
}
```

Run frontend unit, accessibility, lint, format, type, and production-build commands.

- [ ] **Step 4: Add deterministic real-browser journeys**

`scripts/run_web_smoke.py` creates a temporary workspace fixture and constructs the production
`create_web_app`/loopback-socket/session path with a `WorkspaceApplication` that has deterministic
fake runners. It writes the complete bootstrap URL to a temporary state file, starts Uvicorn,
runs the command following `--`, and terminates the server cleanly afterward. Separate
`test_server.py` subprocess coverage continues to verify the real `bundlewalker-web` entry point,
browser-open fallback, and Ctrl-C behavior.

Playwright must cover:

- bootstrap exchange and clean URL;
- Browse default with no review;
- Review default with an existing review;
- concept search/read;
- stubbed Ask and lint;
- pasted and uploaded-text ingestion;
- exact diff, Apply, and Discard;
- synthesis and refresh result variants;
- MCP-prepared review discovery;
- wrong-origin/unauthenticated API rejection; and
- narrow viewport unified diff.

Run:

```bash
uv run python scripts/run_web_smoke.py -- npm --prefix frontend run test:e2e
```

Expected: PASS with no live provider credentials or network access.

- [ ] **Step 5: Commit**

```bash
git add frontend scripts/run_web_smoke.py src/bundlewalker/interfaces/web/static
git commit -m "test: add accessible local web browser journeys"
```

---

### Task 10: Integrate CI, Audits, Licenses, and Distribution Smokes

**Files:**
- Create: `THIRD_PARTY_NOTICES.md`
- Modify: `.github/workflows/ci.yml`
- Modify: `.github/workflows/publish-testpypi.yml`
- Modify: `.github/workflows/publish-pypi.yml`
- Modify: `tests/test_release_metadata.py`
- Modify: `tests/test_project_automation.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`

**Interfaces:**
- Consumes: all build/test commands from Tasks 1–9.
- Produces: protected CI coverage for frontend reproducibility, browser smoke, optional-extra
  artifact installation, and browser dependency notices.

- [ ] **Step 1: Write failing repository-policy tests**

Require:

- Node version `22.22.3` and `npm ci` in supported CI;
- frontend format/lint/type/unit/build commands;
- `git diff --exit-code -- src/bundlewalker/interfaces/web/static`;
- `npm audit --audit-level=high`;
- browser smoke in required Linux CI;
- wheel and source archives contain `index.html`, hashed assets, and manifest;
- artifact smoke installs `"bundlewalker[web]"` and runs `bundlewalker-web --help`;
- base installation runs the missing-extra message smoke in an isolated environment; and
- `THIRD_PARTY_NOTICES.md` names every shipped direct browser dependency and license.

Run:

```bash
uv run pytest tests/test_release_metadata.py tests/test_project_automation.py -q
```

Expected: FAIL on missing workflow and notice requirements.

- [ ] **Step 2: Add the frontend CI job and required dependency edge**

Use pinned immutable action SHAs already approved in the repository. Install exact Node
`22.22.3`, enable npm cache with `frontend/package-lock.json`, run `npm ci`, frontend checks,
fixture regeneration, production build, clean static diff, npm high-severity audit, and Linux
Playwright smoke. Make the final `required` job depend on this job.

- [ ] **Step 3: Extend build and artifact smokes**

Before `uv build`, rebuild and verify static assets. After building, inspect wheel and source
archive member lists. Install the wheel with the `web` extra in macOS/Linux artifact jobs and run:

```bash
bundlewalker-web --help
python -c "from importlib.resources import files; assert files('bundlewalker.interfaces.web').joinpath('static/index.html').is_file()"
```

In a separate clean base-only environment, assert the bounded missing-extra message without
starting a listener.

- [ ] **Step 4: Add dependency notices and publishing gates**

Build `THIRD_PARTY_NOTICES.md` from exact locked direct runtime dependencies:
React, React DOM, React Router DOM, TanStack Query, react-markdown, remark-gfm, and their required
shipped transitive license notices. Update both publishing workflows so tag publication reruns the
same frontend build, clean-asset, audit, and artifact-content gates before upload.

- [ ] **Step 5: Run focused and complete automation tests**

Run:

```bash
uv run pytest tests/test_release_metadata.py tests/test_project_automation.py -q
cd frontend
npm ci
npm run format:check
npm run lint
npm run test
npm run build
npm audit --audit-level=high
cd ..
git diff --exit-code -- src/bundlewalker/interfaces/web/static
uv build --clear --no-sources
uv run twine check dist/*
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows pyproject.toml uv.lock THIRD_PARTY_NOTICES.md tests frontend/package-lock.json src/bundlewalker/interfaces/web/static
git commit -m "ci: verify packaged local web UI"
```

---

### Task 11: Publish Accurate User and Contributor Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/user-guide.md`
- Modify: `SUPPORT.md`
- Modify: `CONTRIBUTING.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/superpowers/specs/2026-07-17-mcp-web-interface-architecture-design.md`
- Modify: `docs/superpowers/specs/2026-07-25-local-web-ui-design.md`
- Modify: `tests/test_release_metadata.py`

**Interfaces:**
- Consumes: verified command, install, security, and capability behavior from Tasks 1–10.
- Produces: public guidance that no longer describes the implemented UI as merely planned.

- [ ] **Step 1: Write failing active-documentation assertions**

Require active docs to contain:

```text
pip install "bundlewalker[web]"
bundlewalker-web
bundlewalker-web --workspace
127.0.0.1
one workspace
macOS and Linux
Windows experimental
```

Also require active docs to omit “local web UI is planned, not implemented” while preserving that
historical wording in immutable older plans/specifications where it records past scope.

- [ ] **Step 2: Update README and user guide**

Document:

- optional-extra installation;
- launch and manual browser-URL fallback;
- Browse, Ask, lint, paste/file ingestion, synthesis, refresh, exact review, Apply, Discard;
- one pending review and MCP-to-web handoff;
- loopback/session/CSRF boundary in user language;
- Ctrl-C shutdown;
- model/configuration, stale review, browser launch, and missing-extra troubleshooting; and
- deferred remote/multi-workspace/lifecycle scope.

- [ ] **Step 3: Update support, contribution, architecture, and changelog material**

Document Node `22.22.3`, `npm ci`, each frontend command, committed generated-asset policy,
contract-fixture generation, Playwright, accessibility expectations, optional-extra artifact
checks, and license notices. Advance the 2026-07-25 spec to `Implemented; verification complete`
only after all Task 12 gates pass; until then use `Implementation in progress`.

- [ ] **Step 4: Run documentation and metadata tests**

Run:

```bash
uv run pytest tests/test_release_metadata.py tests/test_project_automation.py -q
rg -n "local web UI is planned|web UI is not implemented" README.md docs/user-guide.md SUPPORT.md CONTRIBUTING.md
git diff --check
```

Expected: tests PASS; the `rg` command finds no active-documentation stale claim.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/user-guide.md SUPPORT.md CONTRIBUTING.md CHANGELOG.md docs/superpowers/specs tests/test_release_metadata.py
git commit -m "docs: document the local web review cockpit"
```

---

### Task 12: Run the Final Supported Gate and Record Completion

**Files:**
- Modify: `docs/superpowers/specs/2026-07-25-local-web-ui-design.md`
- Modify: `CHANGELOG.md` only if verification wording needs finalization

**Interfaces:**
- Consumes: complete implementation and tests from Tasks 1–11.
- Produces: verified release-ready branch state and an implemented design status.

- [ ] **Step 1: Run the complete Python gate**

```bash
uv lock --check
uv run pytest -m 'not eval' -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
```

Expected: all commands PASS with no warnings treated as success exceptions.

- [ ] **Step 2: Run the complete frontend gate**

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

Expected: all commands PASS and generated assets are byte-identical to the committed output.

- [ ] **Step 3: Run browser and distribution gates**

```bash
uv run python scripts/run_web_smoke.py -- npm --prefix frontend run test:e2e
uv build --clear --no-sources
uv run twine check dist/*
```

Install the exact wheel and source distribution into clean Python 3.13 and 3.14 environments on
macOS and Linux with the `web` extra. Verify all three entry points, packaged assets, secure
loopback startup, browser smoke, and Ctrl-C shutdown. Observe experimental Windows without making
it required.

- [ ] **Step 4: Run repository hygiene and security scans**

```bash
git diff --check
git status --short
rg -n "(BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|api[_-]?key\\s*=|token\\s*=)" \
  --glob '!frontend/package-lock.json' \
  --glob '!src/bundlewalker/interfaces/web/static/**' .
rg -n "/Users/|/Volumes/" src tests frontend README.md docs/user-guide.md SUPPORT.md CONTRIBUTING.md
```

Expected: no secrets, developer-only absolute paths, untracked build output, or unintended files.

- [ ] **Step 5: Mark the design implemented and rerun the focused documentation test**

Change the design status to:

```markdown
**Status:** Implemented; verification complete
```

Run:

```bash
uv run pytest tests/test_release_metadata.py tests/test_project_automation.py -q
git diff --check
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/specs/2026-07-25-local-web-ui-design.md CHANGELOG.md
git commit -m "docs: record local web UI verification"
```

- [ ] **Step 7: Perform completion review**

Use `superpowers:requesting-code-review`, address only evidence-backed findings, rerun affected
tests, and then use `superpowers:finishing-a-development-branch` to choose PR/merge handling. Do
not tag, publish, or bump the package version unless the user separately authorizes a release.
