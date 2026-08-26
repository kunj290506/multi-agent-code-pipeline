# Code-Gen Agent

**Owner**: Member B

The Code-Gen Agent specialises in generating production-ready code from structured specifications provided by the Planner Agent. It can scaffold REST API endpoints (FastAPI / Express) and React components, using context retrieved by the RAG Agent to ensure the output follows project conventions.
It leverages Ollama-hosted models (e.g., `codellama`, `deepseek-coder`) via LangChain chains and applies carefully engineered prompts to produce clean, typed, and testable code.
Generated code is immediately forwarded to the Reviewer/QA Agent before being surfaced to the user.
