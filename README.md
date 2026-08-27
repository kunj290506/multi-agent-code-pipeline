# Multi-Agent Orchestration Pipeline for Automated Code Generation, Review and Documentation Retrieval

## Project Overview

This project implements a **Multi-Agent Orchestration Pipeline** that automates the end-to-end software development workflow — from understanding documentation to generating production-ready code, reviewing it for quality, managing database operations, and coordinating everything through an intelligent planner. Built on top of **n8n** for visual workflow orchestration and **Ollama** for local LLM inference, the system leverages five specialized AI agents that communicate and collaborate to deliver high-quality code artifacts with minimal human intervention. The pipeline is designed for a sample full-stack application (REST backend + React frontend) with a local SQL database.

---

## 5-Agent Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     n8n Orchestration Layer                  │
└──────────────────────────┬──────────────────────────────────┘
                           │
              ┌────────────▼────────────┐
              │    Planner Agent         │  <- Orchestrates all agents
              └──┬──────┬──────┬───┬───┘
                 │      │      │   │
    ┌────────────▼─┐ ┌──▼───┐ │ ┌─▼──────────────┐
    │  RAG Agent   │ │Code  │ │ │  DB Agent       │
    │  (Docs/Qdrant│ │ Gen  │ │ │ (Migrations &   │
    │   retrieval) │ │Agent │ │ │  SQL Queries)   │
    └──────────────┘ └──┬───┘ │ └────────────────┘
                        │     │
                   ┌────▼─────▼────┐
                   │ Reviewer       │
                   │   / QA Agent  │
                   └───────────────┘
```

| Agent | Role | Owner |
|-------|------|-------|
| **Planner Agent** | Orchestrates task flow, breaks user intent into subtasks, delegates to other agents | Member A |
| **RAG Agent** | Retrieves relevant documentation snippets from Qdrant/Chroma vector DB | Member A |
| **Code-Gen Agent** | Generates REST API endpoints and React components from specs | Member B |
| **Reviewer/QA Agent** | Reviews generated code for bugs, style, and security issues | Member B |
| **DB Agent** | Handles database migrations and query generation (shared) | Shared |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Orchestration** | [n8n](https://n8n.io/) — visual workflow automation |
| **Local LLM** | [Ollama](https://ollama.ai/) — runs models like `codellama`, `mistral` locally |
| **LLM Framework** | [LangChain](https://www.langchain.com/) — chains, agents, prompt management |
| **Vector Store** | [Qdrant](https://qdrant.tech/) / [Chroma](https://www.trychroma.com/) — document embeddings & retrieval |
| **Containerization** | [Docker](https://www.docker.com/) + Docker Compose |
| **Backend (target)** | Python FastAPI / Node.js Express |
| **Frontend (target)** | React + Vite |
| **Database (target)** | SQLite / PostgreSQL |

---

## Team Responsibilities

### Member A
- **Planner Agent**: Architecture, task decomposition logic, inter-agent communication
- **RAG Agent**: Document ingestion pipeline, Qdrant integration, embedding setup
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

> **NOTE**: To be filled in later — Full setup documentation will be added as agents are implemented.

### Prerequisites
- Docker & Docker Compose
- Python 3.10+
- Node.js 18+
- Git

### Quick Start

```bash
# 1. Start core infrastructure (n8n, Ollama, Qdrant)
docker compose up -d

# 2. Wait for Ollama to become healthy, then pull and verify the local model
#    Default model: mistral. Use --model to specify another (e.g. llama3.1:8b).
pip install requests
python ollama-setup.py
#    Or specify a different model:
#    python ollama-setup.py --model llama3.1:8b

# 3. Access the n8n dashboard
#    URL:      http://localhost:5678
#    User:     admin
#    Password: changeme

# 4. Set up individual agents (see each agent's README for details)
cd rag-agent     && pip install -r requirements.txt
cd planner-agent && pip install -r requirements.txt
cd db-agent      && pip install -r requirements.txt
```

### Ollama Model Setup Commands

```bash
# Verify Ollama is running
curl http://localhost:11434/api/tags

# Pull a model manually (alternative to the setup script)
curl -X POST http://localhost:11434/api/pull -d '{"name": "mistral"}'

# Test the model manually
curl -X POST http://localhost:11434/api/generate \
  -d '{"model": "mistral", "prompt": "Hello", "stream": false}'
```

---

## Repository Structure

```
multi-agent-code-pipeline/
├── planner-agent/     # Planner / Orchestrator agent
├── rag-agent/         # RAG / Documentation retrieval agent
├── codegen-agent/     # Code generation agent
├── reviewer-agent/    # Code review & QA agent
├── db-agent/          # Database migration & query agent
├── target-app/        # Sample full-stack application
├── n8n/               # n8n workflow definitions
├── docker-compose.yml # Infrastructure services
└── .gitignore
```

---

*B.Tech AI/ML Project*
