# Running the Multi-Agent Pipeline

## Prerequisites

- Python 3.11+
- Node.js 18+
- Docker Desktop (for n8n orchestration)
- A Groq API key → https://console.groq.com

---

## 1. Quick Start (Single Command)

Double-click `start.bat` or run in terminal:

```cmd
start.bat
```

To stop all services cleanly:
```cmd
stop.bat
```

---

## 2. Environment Setup

Create or update `.env` in the repository root:

```env
GROQ_API_KEY=gsk_your_key_here
GROQ_MODEL=openai/gpt-oss-120b
LLM_PROVIDER=groq
```

---

## 3. Application Links & Credentials

| Service | URL | Credentials |
|---|---|---|
| **Frontend Webapp** | http://localhost:5173 | `admin` / `admin@123` |
| **Backend API (Swagger)** | http://localhost:8020/docs | None |
| **Backend Health** | http://localhost:8020/health | None |
| **n8n Workflow Dashboard**| http://localhost:5678 | `kunjchauhan05@gmail.com` / `Kunj@1269` |
| **n8n Webhook Endpoint** | http://localhost:5678/webhook/feature-request | Basic Auth: `admin` / `changeme` |

---

## 4. Microservice Agent Ports

| Agent | Port | Swagger Docs |
|---|---|---|
| Planner Agent | 8010 | http://localhost:8010/docs |
| RAG Agent | 8011 | http://localhost:8011/docs |
| DB Query Agent | 8012 | http://localhost:8012/docs |
| DB Executor | 8013 | http://localhost:8013/docs |
| CodeGen Agent | 8014 | http://localhost:8014/docs |
| Reviewer Agent | 8015 | http://localhost:8015/docs |
| Webapp Backend | 8020 | http://localhost:8020/docs |
| Frontend UI | 5173 | http://localhost:5173 |
