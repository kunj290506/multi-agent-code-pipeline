# Multi-Agent Orchestration Pipeline for Automated Code Generation, Review and Documentation Retrieval

## Project Overview

This project implements a **Multi-Agent Orchestration Pipeline** that automates the end-to-end software development workflow — from understanding documentation to generating production-ready code, reviewing it for quality, managing database operations, and coordinating everything through an intelligent planner. Built on top of **n8n** for visual workflow orchestration and **Ollama** for local LLM inference, the system leverages five specialized AI agents that communicate and collaborate to deliver high-quality code artifacts with minimal human intervention. The pipeline is designed for a sample full-stack application (REST backend + React frontend) with a local SQL database.

---

## 5-Agent Architecture Overview

```

                     n8n Orchestration Layer                  

                           
              
                  Planner Agent           <- Orchestrates all agents
              
                                
       
      RAG Agent    Code      DB Agent       
      (Docs/Chroma  Gen     (Migrations &   
       retrieval)  Agent     SQL Queries)   
       
                             
                   
                    Reviewer       
                      / QA Agent  
                   
```

| Agent | Role | Owner |
|-------|------|-------|
| **Planner Agent** | Orchestrates task flow, breaks user intent into subtasks, delegates to other agents | Member A |
| **RAG Agent** | Retrieves relevant documentation snippets from Chroma vector DB | Member A |
| **Code-Gen Agent** | Generates REST API endpoints and React components from specs | Member B |
| **Reviewer/QA Agent** | Reviews generated code for bugs, style, and security issues | Member B |
| **DB Agent** | Handles database migrations and query generation (shared) | Shared |

###  Advanced CI/CD Upgrades

This pipeline has been hardened into a continuous integration engine:
- **Veteran Personas:** The Planner and Code-Gen agents operate with strict "30-year veteran architect/engineer" prompts. Placeholders, shortcuts, and boilerplate are strictly forbidden.
- **Hedged LLM Execution:** To combat single-provider outages or rate limits, the core LLM execution layer (`call_llm`) utilizes Python's `concurrent.futures`. It simultaneously races primary requests (Groq API) alongside local fallbacks (Ollama). The pipeline instantly claims the first successful code generation, eliminating random hangs and timeouts.
- **Logic Verification Gate:** The Reviewer Agent features a dedicated LLM-driven `check_logic_completeness` rule that cross-references generated code against the original feature request. It acts as an automated CI/CD gate, rejecting logically incomplete code back to the Code-Gen agent for self-healing up to 5 times.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Orchestration** | [n8n](https://n8n.io/) — visual workflow automation |
| **Local LLM** | [Ollama](https://ollama.ai/) — runs models like `codellama`, `mistral` locally |
| **LLM Framework** | [LangChain](https://www.langchain.com/) — chains, agents, prompt management |
| **Vector Store** | [Chroma](https://www.trychroma.com/) — document embeddings & retrieval |
| **Containerization** | [Docker](https://www.docker.com/) + Docker Compose |
| **Backend (target)** | Python FastAPI / Node.js Express |
| **Frontend (target)** | React + Vite |
| **Database (target)** | SQLite / PostgreSQL |

---

## Team Responsibilities

### Member A
- **Planner Agent**: Architecture, task decomposition logic, inter-agent communication
- **RAG Agent**: Document ingestion pipeline, Chroma integration, embedding setup
- **n8n Workflows**: Visual orchestration of all agent triggers and data flows
- **Ollama Setup**: Local model deployment, model selection, inference configuration
- **DB Agent** (shared): Schema design, migration strategy

### Member B
- **Code-Gen Agent**: REST endpoint generation, React component scaffolding, prompt engineering
- **Reviewer/QA Agent**: Static analysis integration, code quality checks, feedback loops
- **Target App**: Sample backend + frontend application with local SQL database
- **DB Agent** (shared): Query generation, ORM integration

---

## Setup Instructions

### Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| [Docker](https://docs.docker.com/get-docker/) + Docker Compose | 24+ | For n8n and optional containerised agents |
| [Python](https://www.python.org/downloads/) | 3.11+ | Run agents directly on the host |
| [Node.js](https://nodejs.org/) | 18+ | Webapp frontend |
| [Ollama](https://ollama.ai/) | latest | **Must be installed on the host** — see note below |
| Git | any | |

### Model Requirements

| Model | RAM Required | Notes |
|---|---|---|
| `qwen2.5:7b-instruct-q4_K_M` | ~4.7 GB | **Default** — balanced quality/speed |
| `mistral:7b-instruct-q4_K_M` | ~4.1 GB | Smaller alternative |
| `llama3.1:8b` | ~5.0 GB | Larger alternative |
| `all-MiniLM-L6-v2` | ~90 MB | Embedding model for RAG — handled by `sentence-transformers`, **not** Ollama |

### Why Ollama runs on the host (not in Docker)

Ollama is run on the host rather than inside Docker because GPU passthrough to a containerised Ollama requires WSL2 + CUDA-on-WSL configuration. On a 4 GB GPU this is a hardware risk not worth taking two days before a deadline. The commented-out service block in `docker-compose.yml` shows the intent and can be enabled on hardware with proper GPU passthrough support.

### Step-by-step Setup

**Step 1 — Install and start Ollama on the host**

Download Ollama from https://ollama.ai/ and follow the installer. Verify it is running:

```bash
curl http://localhost:11434/api/tags
```

**Step 2 — Pull the LLM**

```bash
pip install requests
python ollama-setup.py
# Default model: qwen2.5:7b-instruct-q4_K_M (~4.7 GB)
# Override with a different model:
#   python ollama-setup.py --model mistral:7b-instruct-q4_K_M
```

**Step 3 — Start n8n**

```bash
docker compose up -d
# n8n will be available at http://localhost:5678
# Default credentials: admin / changeme
```

**Step 4 — Start all services (2 windows only)**

```powershell
# Windows — opens 2 terminals: one backend, one frontend
.\scripts\start_all.bat

# or PowerShell
.\scripts\start_all.ps1

# Linux / macOS
bash scripts/start_all.sh
```

This starts all 8 backend agents inside a **single** terminal window via
`scripts/launch_backend.py`, and the Vite frontend in a second window.

**Step 5 — Open the UI**

Navigate to **http://localhost:5173**, sign up (first time), then type a
prompt and click **Run Pipeline**.

### Ollama Manual Commands

```bash
# Verify Ollama is running
curl http://localhost:11434/api/tags

# Pull a model manually
curl -X POST http://localhost:11434/api/pull -d '{"name": "qwen2.5:7b-instruct-q4_K_M"}'

# Test the model manually
curl -X POST http://localhost:11434/api/generate \
  -d '{"model": "qwen2.5:7b-instruct-q4_K_M", "prompt": "Hello", "stream": false}'
```

---

## Repository Structure

```
multi-agent-code-pipeline/
 agents/
    planner/       # Planner / Orchestrator agent        :8010
    rag/           # RAG / Documentation retrieval agent :8011
    db/            # Database migration & query agent    :8012–8013
    codegen/       # Code generation agent               :8014
    reviewer/      # Code review & QA agent              :8015
 webapp/
    backend/       # Orchestration API + auth            :8020
    frontend/      # React IDE / UI                      :5173
 target-app/        # Workspace where generated files land :8000
 scripts/
    launch_backend.py  # Single-window backend launcher
    start_all.bat      # Windows 2-window startup
    start_all.ps1      # PowerShell 2-window startup
    start_all.sh       # Linux/macOS startup
 eval/              # Evaluation harness (12 test cases)
 n8n/               # n8n workflow definitions
 docker-compose.yml # Infrastructure services (n8n)
 .gitignore
```

---

## Running the Evaluation

The evaluation set consists of 12 test cases that measure success rate, retry rate, and failure modes across all five agents.

### Prerequisites
1. All services must be running (use `scripts/start_all.ps1` or `scripts/start_all.sh`)
2. The RAG agent must have ingested the target-app codebase:
   ```bash
   cd agents/rag
   python ingest.py
   ```

### Run the evaluation
```bash
python eval/run_eval.py
```

This will:
- Submit each of the 12 test cases to the pipeline
- Wait for each run to complete (up to 300 seconds per case)
- Write results to `eval/results.csv`
- Print a summary with success rate, retry rate, and p50/max duration

### What the evaluation covers
| Case ID | Type | What it tests |
|---------|------|---------------|
| E01–E06 | Happy path | Basic agent routing, CodeGen+Review pass, DB queries, RAG retrieval |
| E07–E08 | Retry triggers | Proves the bounded retry loop fires on error/critical issues |
| E09 | Adversarial — ambiguous | Graceful handling of underspecified requests |
| E10–E11 | Adversarial — DB safety | DB Agent blocks destructive operations |
| E12 | Adversarial — schema | Input validation rejects empty requests before pipeline starts |

See `eval/README.md` for full details on interpreting results.

---

*Multi-Agent AI Orchestration Project*
