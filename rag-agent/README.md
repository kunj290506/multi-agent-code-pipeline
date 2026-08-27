# RAG / Documentation Agent

## Purpose

The RAG (Retrieval-Augmented Generation) agent is responsible for:

1. **Ingesting** source code and documentation from the target application.
2. **Chunking** and **embedding** the text using a local sentence-transformer model.
3. **Storing** the resulting vectors in a local ChromaDB collection.
4. **Answering** natural-language questions by retrieving relevant chunks and
   generating responses through the local Ollama model.

This agent serves as the knowledge backbone for the entire multi-agent pipeline,
providing context-aware answers to queries from the Planner and other agents.

---

## Architecture

```
source files (target-app/)
        |
        v
  [collect_documents] -- walks the directory, filters by extension
        |
        v
  [chunk_documents]   -- splits into overlapping text chunks
        |
        v
  [build_vector_store] -- embeds with sentence-transformers, stores in ChromaDB
        |
        v
  [query]             -- retrieves top-k chunks, sends to Ollama, returns answer
```

---

## Project Structure

```
rag-agent/
  config.py          -- Centralized configuration (Ollama URL, model, Chroma path, etc.)
  ingest.py          -- Document collection, chunking, and vector store creation
  query.py           -- Retrieval and answer generation via Ollama
  api.py             -- FastAPI HTTP wrapper for inter-agent communication
  test_rag.py        -- End-to-end test script with sample question-answer pairs
  requirements.txt   -- Python dependencies
  sample_docs/       -- Placeholder source files for testing when target-app is empty
    app.py           -- Sample FastAPI application (task manager)
    README.md        -- Sample application documentation
```

---

## Setup

### Prerequisites

- Python 3.10+
- Ollama running locally (or in Docker) on port 11434
- A pulled model (e.g., `mistral`)

### Installation

```bash
cd rag-agent
pip install -r requirements.txt
```

### Configuration

All settings are controlled via environment variables or defaults in `config.py`:

| Variable            | Default                        | Description                        |
|---------------------|--------------------------------|------------------------------------|
| `OLLAMA_BASE_URL`   | `http://localhost:11434`       | Ollama server URL                  |
| `OLLAMA_MODEL`      | `mistral`                      | Model name for answer generation   |
| `EMBEDDING_MODEL`   | `all-MiniLM-L6-v2`            | Sentence-transformer model         |
| `CHROMA_PERSIST_DIR`| `.chroma_store/` (local)       | ChromaDB persistence directory     |
| `RAG_SOURCE_DIR`    | `../target-app/`               | Directory to ingest documents from |
| `CHUNK_SIZE`        | `1000`                         | Characters per chunk               |
| `CHUNK_OVERLAP`     | `200`                          | Overlap between consecutive chunks |
| `RAG_API_HOST`      | `0.0.0.0`                      | API server bind address            |
| `RAG_API_PORT`      | `8001`                         | API server port                    |

---

## Usage

### 1. Ingest documents

```bash
# Ingest from the default source directory (target-app/)
python ingest.py

# Or specify a custom directory
python ingest.py --source-dir ./sample_docs
```

### 2. Query the knowledge base

```bash
# Requires Ollama to be running with a model loaded
python query.py "What API endpoints does the application expose?"
```

### 3. Run as an HTTP service

```bash
python api.py
# Server starts at http://localhost:8001
```

API endpoints:

- `GET  /health`  -- Health check
- `POST /ingest`  -- `{ "source_dir": "/path/to/source" }`
- `POST /query`   -- `{ "question": "...", "top_k": 5 }`

### 4. Run tests

```bash
python test_rag.py
```

The test script validates:
- Document collection from `sample_docs/`
- Text chunking correctness
- Vector store creation and similarity search
- Retrieval relevance against expected keywords
- Full Ollama integration (skipped if Ollama is not running)

---

## Integration with Other Agents

The RAG agent communicates via structured JSON over HTTP. Other agents (or the
n8n workflow) can call `POST /query` with a question and receive a JSON response:

```json
{
  "question": "What database does the app use?",
  "answer": "The application uses a local SQLite database...",
  "sources": ["README.md", "app.py"],
  "num_chunks_used": 3
}
```
