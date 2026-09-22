# Running the Multi-Agent Pipeline

## Prerequisites

- Python 3.11+
- Node.js 18+
- A Groq API key → https://console.groq.com

---

## 1. Set your Groq API key

Create a `.env` file in the repo root (if not already present):

```
GROQ_API_KEY=gsk_your_key_here
GROQ_MODEL=qwen/qwen3.8-27b
LLM_PROVIDER=groq
```

---

## 2. Install dependencies

```powershell
# Python deps (all agents + backend)
pip install `
  -r agents/planner/requirements.txt `
  -r agents/rag/requirements.txt `
  -r agents/codegen/requirements.txt `
  -r agents/reviewer/requirements.txt `
  -r agents/db/requirements.txt `
  -r webapp/backend/requirements.txt

# Frontend deps
cd webapp/frontend
npm install
cd ../..
```

---

## 3. Start everything

### Option A — Single command (recommended)

```powershell
.\scripts\start_groq.ps1
```

This starts all 7 backend services + the Vite frontend and opens the browser automatically.

### Option B — Manual (two terminals)

**Terminal 1 — Backend:**
```powershell
$env:LLM_PROVIDER="groq"
$env:GROQ_MODEL="qwen/qwen3.8-27b"
$env:GROQ_API_KEY="gsk_your_key_here"
python scripts/launch_backend.py
```

**Terminal 2 — Frontend:**
```powershell
cd webapp/frontend
npm run dev
```

---

## 4. Open the app

```
http://localhost:5173
```

Sign up / log in, type what you want to build, hit **Run Pipeline**.

---

## Service ports (for reference)

| Service        | Port  |
|----------------|-------|
| Planner        | 8010  |
| RAG            | 8011  |
| DB Query       | 8012  |
| DB Executor    | 8013  |
| CodeGen        | 8014  |
| Reviewer       | 8015  |
| Webapp Backend | 8020  |
| Frontend UI    | 5173  |
