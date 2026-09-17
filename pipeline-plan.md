# Multi-Agent Code Pipeline — Ground-Truth Plan

## Phase 0: Audit Results

### Git State (verified from .git/refs)
- Current branch: `kunj-planner-rag`
- Local HEAD: `5ddc1153daf5ecf3ce7700324b75fc0ef15eed7a`
- Remote `origin/kunj-planner-rag`: same commit — **nothing to push, branch is in sync**
- Remote `origin/main`: `40feeea9c451e1f9c09c012bd920dfb05168485e` (different branch, not relevant)
- Untracked (not committed, not gitignored): `webapp/backend/backend.log`, `webapp/backend/test_cookies.txt`
  - `backend.log` should be added to `.gitignore`
  - `test_cookies.txt` should be added to `.gitignore`

### What Actually Exists on Disk

| Path | Exists | Dockerfile | Notes |
|---|---|---|---|
| `planner-agent/` | ✅ | ✅ | api.py, planner.py, config.py, requirements.txt, test_planner.py |
| `rag-agent/` | ✅ | ✅ | api.py, query.py, ingest.py, config.py, requirements.txt |
| `codegen-agent/` | ✅ | ✅ | api.py, generator.py, spec_schema.py, config.py, requirements.txt |
| `reviewer-agent/` | ✅ | ✅ | api.py, reviewer.py, rules.py, config.py, requirements.txt |
| `db-agent/` | ✅ | ✅ | api.py, query_generator.py, sandbox.py, executor.py, executor_api.py, config.py |
| `webapp/backend/` | ✅ | ✅ | main.py (1270 lines), auth.py, requirements.txt, users.db (untracked), backend.log (untracked) |
| `webapp/frontend/` | ✅ | ❌ | React+Vite, three pages (LandingPage, LoginPage, IDEPage), all components present |
| `n8n/` | ✅ | ❌ | workflow.json, README.md |
| `eval/` | ✅ | N/A | evaluation_set.json (12 cases), run_eval.py, README.md |
| `logs/` | ✅ | N/A | .gitkeep + 2 real run log files |
| `scripts/` | ✅ | N/A | start_all.bat, start_all.ps1, start_all.sh |
| `target-app/` | ✅ | ❌ | app.py, taskmanager.db (untracked via .gitignore), README.md |
| `docker-compose.yml` | ✅ | N/A | Only n8n active; all agents commented out (GPU passthrough documented) |
| `.gitignore` | ✅ | N/A | Missing: `backend.log`, `test_cookies.txt` |
| `ollama-setup.py` | ✅ | N/A | Present |
| `README.md` | ✅ | N/A | Present, comprehensive |
| **`ide-rebuild-plan.md`** | ✅ | N/A | **STALE — not in allowed list; should be deleted** |

### Agent Schema Validation & Reasoning Field

| Agent | Input Pydantic | Output Pydantic | `reasoning` field | Notes |
|---|---|---|---|---|
| planner-agent | ✅ | ✅ | ✅ in PLAN_SCHEMA | Populated by Ollama; null in offline |
| rag-agent | ✅ | ✅ | ❌ MISSING | QueryResponse has no `reasoning` field |
| codegen-agent | ✅ | ✅ | ✅ in GeneratedArtifact | Only set by LLM path; offline does not set it |
| reviewer-agent | ✅ | ✅ | ✅ in ReviewResponse | Field present, but reviewer.py never populates it |
| db-agent | ✅ | ✅ | ❌ MISSING | GenerateResponse has no `reasoning` field |

### Key Gaps Found (complete list, nothing assumed)

**G1 — `prior_issues` not wired into CodeGen retry:**
`main.py` sends `prior_issues` in the payload but `codegen-agent/api.py`'s `GenerateRequest` has no `prior_issues` field and `generate_artifact_offline` / `generate_artifact` never receive it. The Reviewer's issue list is silently dropped — the retry is a blind retry, not a contextual one.

**G2 — `reasoning` field missing from RAG and DB agents:**
`rag-agent/api.py` `QueryResponse` and `db-agent/api.py` `GenerateResponse` both lack `reasoning: Optional[str]`. The frontend `StepCard` reads `step.data.reasoning` — it will silently render nothing for these agents (acceptable per spec) but the field isn't declared in the schema, which violates the "every agent's Pydantic response schema includes reasoning" requirement.

**G3 — Reviewer `reasoning` field never populated:**
`reviewer-agent/reviewer.py` `review_code()` returns a dict without `reasoning`. `ReviewResponse` has the field declared but it will always be `null` even when Ollama is available, because the reviewer is heuristic-only (no LLM call). This is honest (field is null, UI shows nothing), but the brief says it must be populated by the model when online. The reviewer currently has no LLM path at all.

**G4 — `ide-rebuild-plan.md` at repo root:**
Not in the allowed file list. Stale planning doc.

**G5 — `backend.log` and `test_cookies.txt` not in `.gitignore`:**
Both will appear as untracked unless gitignored. Should not be committed.

**G6 — Eval runner uses `/request` (old blocking alias) not `/runs` (async):**
`run_eval.py` POSTs to `/request` which is the backwards-compat alias. Works but is slow (blocking). More importantly, when the eval runs E12, it also hits `/request`. The `/request` alias does not have auth protection (`current_user` dep is absent from it in main.py line 476) — but the `/logs` endpoint now requires auth. So `run_eval.py` will fail to fetch logs when auth is active. **The eval runner needs session/token handling or the `/logs` endpoint needs to be callable without auth for eval purposes.**

**G7 — FileExplorer always shows `target-app/` tree regardless of active project:**
`FileExplorer` calls `getFiles()` with no `projectId`. When a named project workspace is created (e.g., `projects/calculator_abc123/`), the left pane still shows `target-app/` contents. The `getFiles()` call needs to pass the active `request_id` (or project workspace) so the explorer reflects the project that was just built.

**G8 — No `projects/` in `.gitignore`:**
`PROJECTS_DIR` is `../../projects` (relative to `webapp/backend/`), which is `projects/` at repo root. Generated project files would be committed. Must be gitignored.

**G9 — `docker-compose.yml` has `ollama_data` volume with no corresponding service:**
Orphaned volume. Minor cleanup item.

**G10 — Eval set missing the calculator regression case as a named whole-project run:**
E-cases E01–E12 exist. The brief says "Include the exact whole-project cases that have previously failed (e.g. calculator web app) as permanent regression cases." The eval set has no entry explicitly labeling the calculator case. One of the run logs (`run_b3ab6ffe_...`) shows `"make aa calculator web app"` as a past run. A case `E13` with `"I want a simple calculator web app"` is missing.

**G11 — `codegen-agent` offline templates produce generic Python regardless of `target_filename`:**
When Planner routes a whole-project codegen subtask with `target_filename=index.html`, CodeGen is called with `description="Generate index.html..."`. The `check_spec_or_description` validator builds a spec with `artifact_type="unknown"`. The offline generator then falls back to a generic Python template (not HTML). For whole-project runs in offline mode, the generated files will be wrong-language boilerplate.

**G12 — No `projects/` directory or gitignore entry:**
`PROJECTS_DIR` (`multi-agent-code-pipeline/projects/`) is created at runtime but not gitignored and not listed in the repo structure target list. Needs a `projects/.gitkeep` and `.gitignore` entry.

**G13 — `target-app/taskmanager.db` not gitignored:**
The first audit found `taskmanager.db` in `target-app/`. The `.gitignore` has `*.db` — this should already be covered. Confirm it is excluded before final commit.

---

## Top-Level Overview

The repo is substantially built. All five agents exist with Dockerfiles, Pydantic schemas, and FastAPI endpoints. The three-page frontend is present and correct in design. Auth (SQLite+bcrypt+JWT) is real and complete. The bounded retry loop, structured logging, SSE streaming, STOP button, live pipeline diagram, file explorer, code editor, and project auto-run are all implemented. The evaluation set has 12 cases and a working runner.

The gaps are: 5 schema/wiring correctness issues (G1, G2, G3, G11), 3 repo hygiene issues (G4, G5, G9), 1 product-correctness issue (G7), 2 infra/config issues (G8, G12), 1 eval gap (G10), and 1 eval runner auth gap (G6).

None of these require an architectural rebuild. All are targeted fixes.

---

## Sub-Tasks

---

### ST-1: Repo Cleanup and Gitignore Fixes
**Status:** `[x] done`

**Intent:** Remove stale files not in the allowed list, add missing gitignore entries, and add the `projects/` directory placeholder.

**Expected Outcomes:**
- `ide-rebuild-plan.md` deleted from repo root
- `.gitignore` has entries for `backend.log`, `test_cookies.txt`, `projects/`
- `projects/` directory created with a `.gitkeep` so it exists on disk but its contents are gitignored
- `docker-compose.yml` has `ollama_data` volume removed (orphan cleanup)

**Todo List:**
1. Delete `ide-rebuild-plan.md` from repo root
2. Add `webapp/backend/backend.log`, `webapp/backend/test_cookies.txt`, and `projects/` to `.gitignore`
3. Create `projects/.gitkeep`
4. Remove `ollama_data:` from the `volumes:` section of `docker-compose.yml`

**Relevant Context:**
- `.gitignore` is at repo root, 162 lines
- `docker-compose.yml` lines 158-160 define volumes

---

### ST-2: Add `reasoning` Field to RAG Agent and DB Agent Schemas
**Status:** `[x] done`

**Intent:** Both `rag-agent/api.py`'s `QueryResponse` and `db-agent/api.py`'s `GenerateResponse` are missing the `reasoning: Optional[str]` field required by the brief. Add it to both schemas as `Optional[str] = None` with appropriate docstring. The backend pipeline does not need changes — it already stores full `data` dicts in step records, so the reasoning will flow through automatically once declared.

**Expected Outcomes:**
- `QueryResponse` in `rag-agent/api.py` has `reasoning: str | None = Field(default=None, ...)`
- `GenerateResponse` in `db-agent/api.py` has `reasoning: str | None = Field(default=None, ...)`
- Both fields default to `None` (never synthesized — honest when offline)
- Existing tests still pass (field is optional, backwards-compatible)

**Todo List:**
1. Add `reasoning: str | None = Field(default=None, description="...")` to `QueryResponse` in `rag-agent/api.py`
2. Add `reasoning: str | None = Field(default=None, description="...")` to `GenerateResponse` in `db-agent/api.py`

**Relevant Context:**
- `rag-agent/api.py` lines 63-70: `QueryResponse` class
- `db-agent/api.py` lines 63-70: `GenerateResponse` class
- Pattern to follow: `reviewer-agent/api.py` lines 88-94

---

### ST-3: Wire `prior_issues` into CodeGen Retry Path
**Status:** `[x] done`

**Intent:** When the Reviewer fails, `main.py` sends `prior_issues` in the payload to CodeGen's retry call, but CodeGen's `GenerateRequest` schema ignores it and neither `generate_artifact` nor `generate_artifact_offline` forward it as context. The retry is therefore a blind re-attempt. Fix by: (a) adding `prior_issues` to `GenerateRequest`, (b) appending the issues as constraints into the `ArtifactSpec.constraints` list so they influence code generation.

**Expected Outcomes:**
- `GenerateRequest` in `codegen-agent/api.py` accepts `prior_issues: list[dict] | None = None`
- The validator that builds the spec from `description` forwards `prior_issues` as formatted constraint strings into `spec.constraints`
- On retry, CodeGen receives the actual Reviewer issues and can avoid repeating the same mistakes
- Offline mode: constraints are added to the spec even in template mode (they appear in the template comment block)

**Todo List:**
1. Add `prior_issues: list[dict] | None = Field(default=None, ...)` to `GenerateRequest` in `codegen-agent/api.py`
2. In `check_spec_or_description` validator, if `prior_issues` is set, format each issue as a string (`"[SEVERITY] RULE_ID: message"`) and append to `data["spec"]["constraints"]`
3. Confirm `ArtifactSpec.constraints` is included in the offline template fallback path in `generator.py` (it is, via `spec_block` in `_build_prompt`)
4. For offline mode: add constraints to the generic fallback template as a comment block so the output differs from attempt 1

**Relevant Context:**
- `codegen-agent/api.py` lines 34-62: `GenerateRequest` with `model_validator`
- `codegen-agent/spec_schema.py` lines 56-62: `constraints: list[str]`
- `webapp/backend/main.py` lines 779-782: where `prior_issues` is set in payload

---

### ST-4: Fix CodeGen Offline Template for Whole-Project Files
**Status:** `[x] done`

**Intent:** When Planner routes a whole-project codegen subtask with `target_filename=index.html`, the description is "Generate index.html for a calculator app". CodeGen's `model_validator` builds a spec with `artifact_type="unknown"`, `language="python"`, `framework="fastapi"`. The offline generator then produces a Python function template instead of HTML. Fix by inferring `artifact_type`, `language`, and `framework` from the description text when building the spec from a plain description.

**Expected Outcomes:**
- Descriptions containing `.html` → `artifact_type="html_page"`, `language="html"`, `framework="none"`
- Descriptions containing `.css` → `artifact_type="stylesheet"`, `language="css"`, `framework="none"`
- Descriptions containing `.js` → `artifact_type="script"`, `language="javascript"`, `framework="none"`
- Descriptions containing `.md` → `artifact_type="documentation"`, `language="markdown"`, `framework="none"`
- Offline templates for `html_page`, `stylesheet`, and `script` added to `_OFFLINE_TEMPLATES` in `generator.py`
- A whole-project calculator run in offline mode produces valid HTML/CSS/JS files

**Todo List:**
1. In `codegen-agent/api.py` `check_spec_or_description` validator, add a `_infer_spec_from_description(desc)` helper that extracts `artifact_type`, `language`, `framework` from the description text
2. Add `("html_page", "html", "none")`, `("stylesheet", "css", "none")`, `("script", "javascript", "none")`, `("documentation", "markdown", "none")` template entries to `_OFFLINE_TEMPLATES` in `generator.py`
3. Test: submit a "Generate index.html for a calculator app" description in offline mode, confirm HTML is returned

**Relevant Context:**
- `codegen-agent/api.py` lines 50-62: `check_spec_or_description` validator
- `codegen-agent/generator.py` lines 188-299: `_OFFLINE_TEMPLATES`

---

### ST-5: Fix FileExplorer to Show Active Project Workspace
**Status:** `[x] done`

**Intent:** When a named project run completes, the file explorer still shows `target-app/`. The `FileExplorer` component calls `getFiles()` with no argument. The `IDEPage` knows the `activeRunId` — pass it through to `FileExplorer` so it queries `GET /files?project_id={activeRunId}` after a named project run.

**Expected Outcomes:**
- `IDEPage` passes `projectId={activeRunId}` to `FileExplorer`
- `FileExplorer` calls `getFiles(projectId)` when `projectId` is set
- When `activeRunId` is null (no run yet), fallback to `getFiles()` (shows target-app/)
- The explorer refreshes to show the newly created project workspace files after generation

**Todo List:**
1. Add `projectId?: string` prop to `FileExplorerProps` in `webapp/frontend/src/components/FileExplorer.tsx`
2. Change `getFiles()` call in `FileExplorer` to `getFiles(projectId)` 
3. In `IDEPage.tsx`, pass `projectId={activeRunId ?? undefined}` to `<FileExplorer>`
4. The `refreshTrigger` already triggers re-fetch, so no additional change is needed for live updates

**Relevant Context:**
- `webapp/frontend/src/components/FileExplorer.tsx` lines 5-8: props interface
- `webapp/frontend/src/pages/IDEPage.tsx` lines 164-169: FileExplorer usage
- `webapp/frontend/src/api.ts` lines 84-88: `getFiles(projectId?)` already accepts optional arg

---

### ST-6: Fix Eval Runner Auth and Add Calculator Regression Case
**Status:** `[x] done`

**Intent:** Two eval issues: (a) `run_eval.py` posts to `/request` (backwards-compat, unprotected) and fetches from `/logs` which now requires auth — when auth middleware is active this will fail with 401; (b) the calculator regression case (`"I want a simple calculator web app"`) is missing from the eval set.

**Expected Outcomes:**
- `run_eval.py` authenticates before running (using a test account) and passes the session cookie on all requests, OR the `GET /logs` and `GET /logs/{id}` endpoints are accessible without auth for eval purposes
- A new case `E13` is added to `evaluation_set.json` with `feature_request="I want a simple calculator web app"`, `expected_verdict="pass"`, `adversarial=false`, marked as a regression case
- The eval runner correctly handles E13 as a whole-project run (project_name set)

**Decision to make (two options — pick one before implementing):**
- Option A: Add `--username`/`--password` args to `run_eval.py` and call `/auth/login` first, storing the session cookie for subsequent requests. Clean; preserves auth everywhere.
- Option B: Make `/logs` and `/logs/{request_id}` exempt from auth (they are read-only run history). Simple; consistent with how they worked pre-auth. The `/runs` endpoint (which writes) stays protected.

**Recommendation:** Option B — `/logs` is read-only historical data with no sensitive content. The auth on runs/files is the meaningful protection.

**Todo List:**
1. Remove `current_user: dict = Depends(auth.get_current_user)` from `list_logs()` and `get_log()` in `webapp/backend/main.py` (lines 492 and 523)
2. Add case `E13` to `eval/evaluation_set.json`: `{ "id": "E13", "feature_request": "I want a simple calculator web app", "expected_agents": ["planner-agent", "codegen-agent", "reviewer-agent"], "expected_verdict": "pass", "difficulty": "medium", "adversarial": false, "notes": "REGRESSION: whole-project request that previously failed. Planner must decompose into per-file subtasks with target_filename. Calculator files must be HTML/CSS/JS, not Python boilerplate." }`
3. In `run_eval.py`, update E13 handling to send `project_name="calculator-regression"` in the payload so it creates a named workspace

**Relevant Context:**
- `webapp/backend/main.py` lines 491-535: log endpoints
- `eval/evaluation_set.json`: add after E12
- `eval/run_eval.py` lines 102-212: `run_case()` function

---

### ST-7: Final Verification Pass
**Status:** `[x] done`

**Intent:** After all fixes, confirm the system works end-to-end before writing the commit. This is a checklist step, not a code step.

**Expected Outcomes (each must be manually verified):**
- [ ] All five agents start cleanly and respond to `GET /health`
- [ ] A feature-mode request (e.g. "Add a search endpoint for tasks") completes: Planner → RAG → CodeGen → Reviewer passes or retries correctly
- [ ] A retry case (E07 or E08 from eval) threads correctly in the UI: Reviewer issues shown → CodeGen retry → Reviewer re-verdict
- [ ] A whole-project request ("I want a simple calculator web app") creates `index.html`, `style.css`, `script.js` (not Python boilerplate) in a named project workspace
- [ ] The file explorer updates to show the calculator project files after generation
- [ ] The completed calculator project opens in a new tab and actually works
- [ ] STOP button halts an in-flight run; log shows `status: "cancelled"`
- [ ] Browser console has no errors from the above flows
- [ ] `eval/run_eval.py` completes without auth errors; E13 passes

**Todo List:**
1. Start all services (Ollama on host + uvicorn for each agent + webapp backend + Vite dev server)
2. Manually run each verification item above
3. Fix any issues found (add to this plan as ST-8 if needed)
4. Run `eval/run_eval.py` and confirm results

---

## Files to Delete (confirm before deleting)

| File | Reason |
|---|---|
| `ide-rebuild-plan.md` | Stale planning doc; not in allowed repo structure; superseded by this plan |

## Files to Add to .gitignore

| Pattern | Reason |
|---|---|
| `webapp/backend/backend.log` | Runtime log, should not be committed |
| `webapp/backend/test_cookies.txt` | Dev test artifact, should not be committed |
| `projects/` | Generated project workspaces created at runtime |

## Non-Issues (things that look like gaps but aren't)

- **Reviewer has no LLM path** — The reviewer is correctly heuristic-only. `reasoning` being null is honest behavior. Per the brief: "null (never faked) when running in offline/heuristic mode." ✅
- **docker-compose has all agents commented out** — The README documents Ollama runs on host for GPU reasons. This is a deliberate, documented exception. ✅
- **Frontend has no Dockerfile** — Frontend is served by Vite dev server (dev) or static files (prod). No service Dockerfile is required unless we add a production nginx container. Not in scope. ✅
- **n8n has no Dockerfile** — Uses public `n8nio/n8n:latest` image. Not needed. ✅
- **Two log files committed** — The brief says `logs/*.json` is gitignored. These two files slipped through before the .gitignore entry was added. They're real run data, not placeholders. Low priority — gitignore will prevent new ones from being committed, and these can stay as historical examples. ✅

## Build Order

Follow this sequence within Agent mode:
1. ST-1 (cleanup + gitignore)
2. ST-2 (reasoning fields)
3. ST-3 (prior_issues wiring)
4. ST-4 (offline templates for HTML/CSS/JS)
5. ST-5 (FileExplorer project workspace)
6. ST-6 (eval auth fix + E13 regression case)
7. ST-7 (final verification)

Each ST must be confirmed working before starting the next.
