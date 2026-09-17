# RAG Agent

Retrieval-Augmented Generation (RAG) microservice for the multi-agent code pipeline.  
It ingests source files from `target-app/`, stores their embeddings in a local ChromaDB
collection, and answers natural-language questions by retrieving relevant chunks and
forwarding them to a local Ollama LLM.

---

## Quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Ingest the target-app source tree
python ingest.py

# 3. Start the API server
python api.py
# → listening on http://0.0.0.0:8011
```

---

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness probe |
| `POST` | `/ingest` | Re-ingest documents from `source_dir` |
| `POST` | `/query` | Answer a natural-language question |

### POST /query — request

```json
{
  "question": "How does the Flask app handle authentication?",
  "top_k": 5
}
```

The `description` field is accepted as an alias for `question` (Planner-agent compatibility).

### POST /query — response

```json
{
  "question": "How does the Flask app handle authentication?",
  "answer": "...",
  "sources": ["app.py", "requirements.txt"],
  "num_chunks_used": 5,
  "confidence": 0.8123,
  "low_confidence": false
}
```

---

## Confidence scoring

### `confidence` (float, 0–1)

The maximum similarity score across all retrieved document chunks for the query.  
It is derived from ChromaDB's `similarity_search_with_relevance_scores`, which already
returns scores in the 0–1 range (higher = more relevant).

- **1.0** — a retrieved chunk is an exact or near-exact match.
- **0.5** — moderate relevance; the answer may still be useful but should be reviewed.
- **0.0** — no relevant chunks were found; the answer is entirely speculative.

### `low_confidence` (bool)

Set to `true` when `confidence < 0.5`.

Answers with `low_confidence: true` are still returned because the LLM may still
produce a useful response from loosely related context.  However, **callers must not
treat low-confidence answers as authoritative facts**.  Downstream agents should either:

- Surface the uncertainty to the end user, or
- Discard the answer and request a human review.

---

## Configuration

All settings can be overridden via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server |
| `OLLAMA_MODEL` | `qwen2.5:7b-instruct-q4_K_M` | LLM model tag |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | HuggingFace embedding model |
| `CHROMA_PERSIST_DIR` | `.chroma_store/` | ChromaDB persistence path |
| `CHROMA_COLLECTION` | `codebase_docs` | Collection name |
| `RAG_SOURCE_DIR` | `../target-app/` | Source directory to ingest |
| `CHUNK_SIZE` | `1000` | Token chunk size |
| `CHUNK_OVERLAP` | `200` | Chunk overlap |
| `RAG_API_HOST` | `0.0.0.0` | API bind host |
| `RAG_API_PORT` | `8011` | API bind port |

## Supported file extensions

`.py` `.js` `.ts` `.jsx` `.tsx` `.md` `.txt` `.rst` `.json` `.yaml` `.yml` `.html` `.css` `.sql`
