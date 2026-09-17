# IDE Rebuild Plan — Multi-Agent Code Pipeline

## Top-Level Overview

**Goal:** Transform the existing single-page marketing dashboard into a real IDE-style product with three pages (Landing, Login, IDE), add real authentication, extend the pipeline to scaffold whole projects from one prompt, detect and auto-run finished projects, and keep every number/string/verdict in the UI sourced from real backend data — never invented.

**Scope:**
- `webapp/frontend` — full rebuild as a multi-page React app (Landing + Login + IDE with three-pane layout)
- `webapp/backend/main.py` — add auth endpoints, project-scoped workspace directories, agent `reasoning` field passthrough, project-run detection/launch endpoint, cancel that actually halts the asyncio task
- `planner-agent/planner.py` — extend offline path and Ollama prompt so whole-project requests produce one `codegen-agent` subtask **per file**, each carrying an explicit `target_filename` field
- Agent response schemas — add optional `reasoning` field to Planner, CodeGen, and Reviewer responses (the model produces it; the backend stores it in `data`; the frontend renders it verbatim)

**Non-goals:** Rewrite any agent's core LLM logic, change the Reviewer rule set, migrate from SQLite, or alter the n8n workflow.

**Approach:** Four sequential phases. Each phase must be confirmed working locally before the next starts. No fake data, no placeholder UI states — everything renders as loading/error if the real data isn't available yet.

---

## Phase 1 — Real Authentication

### Intent
Add a working `users` table (SQLite, bcrypt-hashed passwords), signup/login endpoints to the backend, and JWT-cookie session management, then build the Login page and wire the IDE page behind a session guard. Remove every "login skipped" bypass.

### Expected Outcomes
- `POST /auth/signup` and `POST /auth/login` work against a real SQLite `users` table
- Passwords stored as bcrypt hashes via `passlib`
- A `HttpOnly` session cookie (JWT, 24 h expiry) is issued on login
- `GET /auth/me` returns the current user or 401
- `POST /auth/logout` clears the cookie
- All non-auth API routes return 401 if the cookie is missing/invalid
- Frontend has a `/login` page with working signup + login form
- Frontend has a `/` landing page with a "Get Started" CTA pointing to `/login`
- `/ide` route redirects to `/login` if unauthenticated; successful login redirects to `/ide`
- No "skip login" bypass remains in the shipped build

### Todo List
- [ ] Add `passlib[bcrypt]`, `python-jose[cryptography]`, `python-multipart` to `webapp/backend/requirements.txt`
- [ ] Create `webapp/backend/auth.py` — SQLite `users` table init, `hash_password`, `verify_password`, `create_jwt`, `decode_jwt` helpers
- [ ] Add auth middleware to `webapp/backend/main.py` — dependency `get_current_user` that validates the JWT cookie, applied to all non-auth routes
- [ ] Add `POST /auth/signup`, `POST /auth/login`, `GET /auth/me`, `POST /auth/logout` endpoints
- [ ] Build `/` Landing page component — tool description, "Get Started" CTA, no fake stats
- [ ] Build `/login` Login page component — signup tab + login tab, form submission, error display, redirect on success
- [ ] Add React Router (or hash-based routing) to `webapp/frontend`
- [ ] Add `AuthGuard` component that redirects unauthenticated users to `/login`
- [ ] Wire all API calls to include credentials (`credentials: 'include'`) so the cookie is sent

### Relevant Context
- `webapp/backend/main.py` — add `auth.py` as a sibling; import and mount auth router
- `webapp/backend/requirements.txt` — currently only has fastapi, uvicorn, pydantic, websockets, httpx
- `webapp/frontend/src/App.tsx` — replace with multi-page routing shell; existing single-page content moves into the IDE page component
- Existing CORS middleware uses `allow_origins=["*"]` — must change to `allow_origins=["http://localhost:5173"]` and `allow_credentials=True` for cookies to work
- JWT secret must be loaded from an env var (`.env` file, not hardcoded)

### Status
[ ] pending

---

## Phase 2 — IDE Frontend (Three-Pane Layout)

### Intent
Rebuild `webapp/frontend` as a real IDE layout: left pane is a live file explorer, center pane is a syntax-highlighted code editor, right pane is the chat/agent panel with the prompt box and scrolling trace. All data comes from existing backend endpoints (`/files`, `/file`, `/runs/{id}/status`, SSE). The STOP button is fixed, red, and actually calls `POST /runs/{id}/cancel`.

### Expected Outcomes
- Three-pane IDE layout renders at `/ide`
- Left pane: calls `GET /files` on load and after each `file_update` WebSocket event; renders a real file tree with monospace font; clicking a file opens it in the center pane
- Center pane: calls `GET /file?path=` for the selected file; shows real content with Prism syntax highlighting; "no file selected" placeholder until user clicks; "file not yet generated" is not shown — the file simply does not appear in the explorer until it exists on disk
- Right pane: prompt input at bottom; scrolling transcript above showing each real agent step rendered as a reasoning block (reasoning text from `data.reasoning` if present, then the output — task list / snippets / code / verdict+issues); retry attempts threaded inline
- STOP button: red `#e22718`, uppercase white label, 0-radius, fixed bottom-right, visible only during active run; POSTs to `/runs/{id}/cancel`; transcript shows `cancelled` as the terminal state from the real backend response (not optimistically hidden)
- Pipeline diagram retained in right pane header area, showing active agent
- All design tokens applied: surface colors, hairline borders, 0px border-radius, accent stripe on active elements, monospace font for explorer/editor
- No drop shadows; depth via surface contrast only

### Todo List
- [ ] Scaffold `webapp/frontend/src/pages/IDEPage.tsx` with three-pane flex layout
- [ ] Build `FileExplorer` component — fetches `GET /files`, renders tree recursively, re-fetches on `file_update` WS message, emits selected path up to parent
- [ ] Build `CodeEditor` component — fetches `GET /file?path=` when selected path changes, renders with Prism highlighting, handles loading/error states
- [ ] Build `ChatPanel` component — contains prompt form and agent trace; migrates existing `StepCard`, `RagDetail`, `ReviewerDetail`, `CodeGenDetail`, `PlannerDetail`, `DbDetail` from `App.tsx` into this component
- [ ] Add `reasoning` rendering to each step card — if `step.data.reasoning` exists, render it as a collapsible "reasoning" block above the output block, verbatim from the model
- [ ] Add retry threading — `CodeGen → Reviewer → CodeGen → Reviewer` pairs grouped by `attempt_number`, displayed as indented thread with "RETRY — ATTEMPT N" label
- [ ] Wire STOP button to `POST /runs/{id}/cancel`; show "Stopping…" while waiting; reflect terminal state from next poll
- [ ] Apply design system tokens throughout — `#000000` canvas, `#1a1a1a` surface-card, `#0d0d0d` surface-soft, `#262626` surface-elevated, `#3c3c3c` hairlines; accent stripe `#0066b1/#1c69d4/#e22718` only as 4px indicators; no border radius except circular icon buttons; JetBrains Mono for explorer/editor
- [ ] Build `LandingPage` component at `/` with tool description and single "Get Started" CTA
- [ ] Integrate React Router for `/`, `/login`, `/ide` routing with `AuthGuard`

### Relevant Context
- Existing `StepCard`, `PipelineDiagram`, and detail sub-components in `webapp/frontend/src/App.tsx` — lift them into `ChatPanel`, don't rewrite them from scratch
- `GET /files` returns `{ name, type, path, children[] }` recursive tree — already implemented in backend
- `GET /file?path=` returns `{ content: string }` — already implemented
- WebSocket at `ws://localhost:8020/ws` broadcasts `file_update` and `file_delete` events — already implemented
- Prism.js is already in `node_modules` (used in existing `CodeGenDetail`)
- `lucide-react` is already installed for icons

### Status
[ ] pending

---

## Phase 3 — Whole-Project Generation + Project-Scoped Workspaces

### Intent
When a prompt describes a whole new project (not a single feature added to `target-app`), the pipeline must scaffold it from nothing in an isolated workspace directory, with Planner producing one `codegen-agent` subtask per output file, each file going through the full CodeGen→Reviewer loop. RAG and DB agent are only invoked when genuinely needed. Each agent's response must carry a real `reasoning` field (the model's own explanation, not synthesized by the backend).

### Expected Outcomes
- `POST /runs` accepts an optional `project_name` field; if provided (or if the request smells like a whole-project request), a fresh workspace directory `projects/{project_name}_{request_id}/` is created and all writes go there instead of `target-app/`
- Planner's Ollama prompt is updated so whole-project requests produce one subtask per file (e.g. `index.html`, `style.css`, `calculator.js`, `README.md`) with `target_filename` in the description or as a subtask metadata field
- The offline `decompose_offline` fallback similarly produces per-file subtasks for known project types (calculator, etc.) — already partially done, just needs `target_filename` wiring
- CodeGen agent receives `target_filename` in its payload and uses it as the output filename (overrides `_resolve_filename` heuristic)
- RAG subtask is omitted from plans for brand-new empty workspaces (nothing to index yet); included only when the workspace already has indexable content
- DB subtask is only included when the described app genuinely needs persistence
- Each agent's Ollama response includes a `reasoning` field — Planner includes `reasoning` in its JSON output schema, CodeGen includes `reasoning` in `GeneratedArtifact`, Reviewer includes `reasoning` in `ReviewResponse`; these are stored verbatim in `step.data.reasoning` (or nested within `step.data`) and passed through to the frontend without modification
- `GET /files?project_id=` accepts an optional project scoping parameter so the file explorer shows the right workspace
- `GET /file?path=` already validates path is within an allowed root — extend to cover project workspaces
- The frontend sends `project_name` if the user typed a whole-project request (detect by length/phrasing heuristic on the frontend, or let the user prefix the prompt — **decision needed, see below**)

### Todo List
- [ ] Add `project_id` / `workspace_dir` field to `RunRequest` and `RunState` in `webapp/backend/main.py`
- [ ] Update `_init_run_state` to create `projects/{name}_{request_id}/` directory when `project_name` is provided
- [ ] Update `_write_to_target_app` to write to the run's workspace dir (not always `target-app/`)
- [ ] Update `GET /files` to accept optional `?project_id=` query param, returning tree for that project's workspace
- [ ] Update `GET /file?path=` to validate against any registered workspace root (not just `target-app/`)
- [ ] Update `GET /projects` (new endpoint) returning list of past project workspaces with their `request_id`, `name`, `status`, `file_count`
- [ ] Extend Planner's Ollama system prompt to require per-file subtasks on whole-project requests, with `target_filename` as a field in each subtask's `description` (keep schema-compatible by encoding it as a JSON-extractable prefix in description)
- [ ] Extend `SUBTASK_SCHEMA` and `PlanResponse` to carry optional `target_filename` per subtask
- [ ] Update `decompose_offline` to embed `target_filename` in each codegen subtask
- [ ] Add `reasoning` field to Planner's JSON output schema and Ollama prompt
- [ ] Add `reasoning` field to CodeGen's `GeneratedArtifact` Pydantic model and Ollama prompt
- [ ] Add `reasoning` field to Reviewer's `ReviewResponse` Pydantic model and Ollama prompt
- [ ] Backend stores `reasoning` verbatim in `step.data` — no transformation
- [ ] Frontend `ChatPanel` renders `step.data.reasoning` as a collapsible block if present (covered in Phase 2 todo, but wiring depends on Phase 3 schema)
- [ ] Update frontend prompt form to allow specifying a project name (optional field below the main prompt) — sent as `project_name` in the POST body

### Relevant Context
- `webapp/backend/main.py` `_run_pipeline()` lines 472–674 — the pipeline loop; `_write_to_target_app` at line 783; `_resolve_filename` at line 791
- `planner-agent/planner.py` `decompose_offline()` at line 263 — already has per-file subtasks for calculator; needs `target_filename` threading through
- `planner-agent/planner.py` `SYSTEM_PROMPT` at line 70 — needs whole-project instruction and `target_filename` in schema
- `codegen-agent/api.py` `GeneratedArtifact` — needs `reasoning: Optional[str]` field
- `reviewer-agent/api.py` `ReviewResponse` — needs `reasoning: Optional[str]` field
- `planner-agent/api.py` `SubtaskResponse` — needs `target_filename: Optional[str]` field

### Open Question
How should "whole project" vs "single feature" be distinguished?
- **Option A:** Frontend sends an explicit `project_name` field only when user fills in the optional project name input — explicit user intent, cleanest
- **Option B:** Backend heuristic (if first subtask is a `system` cleanup task, treat as whole-project)
- **Option C:** Planner always returns `project_type: "whole"/"feature"` in its response, and the backend branches on that

**Recommended: Option A** — avoids fragile heuristics, puts the user in control, one extra optional field.

### Status
[ ] pending

---

## Phase 4 — Project Auto-Run + Live Preview

### Intent
When all files in a project workspace are written (all passed Reviewer or exhausted retries), the backend detects the project type, starts it on a free local port, returns the URL to the frontend, and the frontend opens that real URL in a new tab. If detection fails or the project can't run, the chat transcript shows a plain-text error — never fakes a running state.

### Expected Outcomes
- Backend `POST /projects/{project_id}/run` endpoint detects project type and starts the app:
  - `index.html` present with no `package.json` → serve static files via Python's `http.server` on a free port
  - `package.json` present → `npm install && npm run dev` (or `start`) in the workspace dir
  - `requirements.txt` + `app.py` (or `main.py`) → `pip install -r requirements.txt && python app.py`
  - Ambiguous / unknown → returns `{ "runnable": false, "reason": "..." }` — no fake "running" state
- Running processes tracked in memory: `running_processes[project_id]` — `pid`, `port`, `url`, `type`
- `GET /projects/{project_id}/status` returns `{ "status": "running"|"stopped"|"not_started", "url": str|null, "port": int|null }`
- `POST /projects/{project_id}/stop` kills the process (os.kill + SIGTERM/SIGKILL fallback on Windows)
- Frontend receives the URL from the run endpoint response and calls `window.open(url, '_blank')` — only if `runnable: true` and the backend confirmed it's actually up (poll the port once before opening)
- If the project can't be auto-run, the chat panel shows a real error message from the backend, not a silent failure
- Pipeline auto-triggers the run endpoint when it finalizes a project (all files complete) — optional, configurable

### Todo List
- [ ] Add `POST /projects/{project_id}/run` to `webapp/backend/main.py` — type detection logic, subprocess launch, port allocation (`socket.bind((0))` trick), process tracking
- [ ] Add `GET /projects/{project_id}/run-status` — returns current run state (running/stopped/error + url)
- [ ] Add `POST /projects/{project_id}/stop` — kills tracked process
- [ ] Add utility `_find_free_port()` and `_detect_project_type(workspace_dir)` helpers
- [ ] Track running processes in `running_processes: dict[str, dict]` in-memory store
- [ ] Add `subprocess` import and process lifecycle management (Windows-compatible — use `subprocess.Popen`, not `os.fork`)
- [ ] On pipeline `_finalize_run`, if status is `success` and run has a `project_id`, enqueue an SSE event `{ type: "project_ready", project_id, workspace_dir }` for the frontend to trigger auto-run
- [ ] Frontend: on receiving `project_ready` SSE event, call `POST /projects/{id}/run`, wait for `runnable: true` + URL, then `window.open(url)`
- [ ] Frontend: if `runnable: false`, display the backend's `reason` string in the chat panel as a terminal message
- [ ] Handle Windows-specific process launch (no `fork`, use `subprocess.CREATE_NEW_PROCESS_GROUP`)

### Relevant Context
- `webapp/backend/main.py` `_finalize_run()` at line 235 — add SSE event emission here for `project_ready`
- `webapp/backend/main.py` `_run_pipeline()` line 674 — success branch after all subtasks complete
- Project workspace from Phase 3: `projects/{name}_{request_id}/`
- Windows platform (from environment: `win32`) — must use `subprocess.Popen` with `creationflags=subprocess.CREATE_NEW_PROCESS_GROUP`; `npm` needs `shell=True` on Windows

### Status
[ ] pending

---

## Cross-Cutting Concerns

### Design System Enforcement (applies to all phases)
- Canvas `#000000`, surface-card `#1a1a1a`, surface-soft `#0d0d0d`, surface-elevated `#262626`, hairline `#3c3c3c`
- Accent stripe only (never fill): `#0066b1` → `#1c69d4` → `#e22718` as 4px top border on active elements; STOP button uses `#e22718` as its background fill (sole exception)
- Typography: Inter 700 headings/buttons/labels, Inter 300 body/comments; -0.5px tracking on `>32px` sizes; buttons 14px 700 1.5px letter-spacing uppercase
- 0px border-radius everywhere; circular icon buttons only exception
- No drop shadows — depth from surface contrast + hairline borders
- Monospace: JetBrains Mono or `ui-monospace` fallback — file explorer, code editor, file paths only

### CORS Fix Required
Existing CORS: `allow_origins=["*"]`, `allow_credentials=False` — this must change to `allow_origins=["http://localhost:5173"]`, `allow_credentials=True` for cookie auth to work. This is a **prerequisite for Phase 1**.

### Cancellation Improvement (Phase 2 / Backend)
Current cancel (`cancel_flags`) only stops dispatch of the *next* subtask — an in-flight Ollama HTTP call runs to completion. This is documented behavior in `main.py` and is acceptable per the brief ("A step already mid-call will finish that call before the cancellation takes effect"). No change needed beyond ensuring the transcript shows `cancelled` accurately.

### Hard Rule: No Fake Data
Every component that doesn't yet have data must render one of:
- A spinner/skeleton labeled "Loading…"
- An error state with the real error message from the backend
- Simply absent (e.g. files not yet generated don't appear in the explorer at all)

Never render invented content, placeholder agent output, or canned demo responses.

---

## File Change Map

| File | Change Type | Phase |
|------|-------------|-------|
| `webapp/backend/requirements.txt` | Add deps | 1 |
| `webapp/backend/auth.py` | New | 1 |
| `webapp/backend/main.py` | Extend | 1, 3, 4 |
| `webapp/frontend/src/App.tsx` | Replace with router shell | 1, 2 |
| `webapp/frontend/src/pages/LandingPage.tsx` | New | 1, 2 |
| `webapp/frontend/src/pages/LoginPage.tsx` | New | 1 |
| `webapp/frontend/src/pages/IDEPage.tsx` | New | 2 |
| `webapp/frontend/src/components/FileExplorer.tsx` | New | 2 |
| `webapp/frontend/src/components/CodeEditor.tsx` | New | 2 |
| `webapp/frontend/src/components/ChatPanel.tsx` | New | 2 |
| `webapp/frontend/src/components/StepCard.tsx` | Lift from App.tsx | 2 |
| `webapp/frontend/src/index.css` | Extend with IDE layout tokens | 2 |
| `webapp/frontend/package.json` | Add react-router-dom | 1 |
| `planner-agent/planner.py` | Extend prompt + schema | 3 |
| `planner-agent/api.py` | Add `target_filename`, `reasoning` to schema | 3 |
| `codegen-agent/api.py` | Add `reasoning` to `GeneratedArtifact` | 3 |
| `reviewer-agent/api.py` | Add `reasoning` to `ReviewResponse` | 3 |

---

## Implementation Order

```
Phase 1 (Auth)
  → confirm login/signup works end-to-end
Phase 2 (IDE layout)
  → confirm file explorer, code editor, chat panel all show real data
Phase 3 (Whole-project scaffolding + reasoning field)
  → submit "calculator app" prompt, confirm per-file subtasks + separate workspaces
Phase 4 (Auto-run + preview)
  → confirm completed project opens in new tab and actually works
Verification
  → STOP test, retry threading test, browser console clean, backend logs clean
Push
  → only after user confirms all four phases work locally
```

---

## Status Summary

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Real authentication (users table, JWT, login page) | [x] done |
| 2 | IDE frontend (three-pane layout, file explorer, code editor, chat panel) | [x] done |
| 3 | Whole-project generation + project-scoped workspaces + reasoning field | [x] done |
| 4 | Project auto-run + live preview | [x] done |
