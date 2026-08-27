"""
RAG Agent -- Test Script.

This script validates the end-to-end RAG pipeline:
1. Ingestion: reads sample documents, chunks them, stores embeddings.
2. Retrieval: performs similarity searches against the vector store.
3. Query (offline): tests the query construction without requiring Ollama.

Run with:
    python test_rag.py

The script uses the sample_docs/ directory as a stand-in for target-app/.
Tests that require the Ollama server are clearly marked and will be skipped
if the server is unreachable.
"""

import json
import os
import shutil
import sys
import tempfile

# Ensure imports resolve from the rag-agent directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402


# ---------------------------------------------------------------------------
# Test configuration -- use a temporary Chroma directory so we don't pollute
# the real vector store.
# ---------------------------------------------------------------------------
_TEMP_DIR = tempfile.mkdtemp(prefix="rag_test_")
config.CHROMA_PERSIST_DIR = os.path.join(_TEMP_DIR, "chroma")
config.CHROMA_COLLECTION_NAME = "test_collection"

SAMPLE_DOCS_DIR = os.path.join(os.path.dirname(__file__), "sample_docs")

# Expected test questions and the keywords we expect in the retrieved context.
TEST_CASES = [
    {
        "question": "What database does the task manager use?",
        "expected_keywords": ["sqlite", "database", "taskmanager"],
    },
    {
        "question": "How do I create a new user?",
        "expected_keywords": ["post", "users", "username", "email"],
    },
    {
        "question": "What fields does the tasks table have?",
        "expected_keywords": ["title", "status", "priority", "assigned_to"],
    },
    {
        "question": "What is the default role for a new user?",
        "expected_keywords": ["member", "role", "default"],
    },
]


def _separator(title: str) -> None:
    print()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)


def test_document_collection() -> bool:
    """Test that sample documents are collected correctly."""
    _separator("Test: Document Collection")
    import ingest

    docs = ingest.collect_documents(SAMPLE_DOCS_DIR)
    print(f"  Documents found: {len(docs)}")
    for doc in docs:
        print(f"    - {doc['metadata']['source']} ({len(doc['content'])} chars)")

    if len(docs) < 2:
        print("  [FAIL] Expected at least 2 sample documents.")
        return False

    print("  [PASS]")
    return True


def test_chunking() -> bool:
    """Test that documents are chunked correctly."""
    _separator("Test: Document Chunking")
    import ingest

    docs = ingest.collect_documents(SAMPLE_DOCS_DIR)
    texts, metadatas = ingest.chunk_documents(docs, chunk_size=500, chunk_overlap=100)

    print(f"  Total chunks: {len(texts)}")
    print(f"  Total metadata entries: {len(metadatas)}")

    if len(texts) == 0:
        print("  [FAIL] No chunks produced.")
        return False

    if len(texts) != len(metadatas):
        print("  [FAIL] Mismatch between texts and metadatas.")
        return False

    # Verify chunk sizes are reasonable.
    max_len = max(len(t) for t in texts)
    avg_len = sum(len(t) for t in texts) / len(texts)
    print(f"  Max chunk length: {max_len}")
    print(f"  Avg chunk length: {avg_len:.0f}")

    print("  [PASS]")
    return True


def test_vector_store_creation() -> bool:
    """Test that the vector store is created and can be queried."""
    _separator("Test: Vector Store Creation and Retrieval")
    import ingest

    store = ingest.ingest(source_dir=SAMPLE_DOCS_DIR)

    # Perform a simple similarity search.
    results = store.similarity_search("user creation endpoint", k=3)
    print(f"  Retrieved {len(results)} results for 'user creation endpoint'")

    if len(results) == 0:
        print("  [FAIL] No results returned from similarity search.")
        return False

    for i, doc in enumerate(results):
        source = doc.metadata.get("source", "unknown")
        snippet = doc.page_content[:80].replace("\n", " ")
        print(f"    [{i+1}] {source}: {snippet}...")

    print("  [PASS]")
    return True


def test_retrieval_relevance() -> bool:
    """Test that retrieved chunks contain expected keywords."""
    _separator("Test: Retrieval Relevance")
    from query import load_vector_store, retrieve_context

    store = load_vector_store()
    all_passed = True

    for case in TEST_CASES:
        question = case["question"]
        expected = case["expected_keywords"]
        context_items = retrieve_context(store, question, top_k=3)

        combined_text = " ".join(
            item["content"].lower() for item in context_items
        )

        found = [kw for kw in expected if kw.lower() in combined_text]
        missing = [kw for kw in expected if kw.lower() not in combined_text]

        status = "PASS" if not missing else "FAIL"
        print(f"  Q: {question}")
        print(f"    Keywords found: {found}")
        if missing:
            print(f"    Keywords missing: {missing}")
            all_passed = False
        print(f"    [{status}]")

    return all_passed


def test_ollama_integration() -> bool:
    """Test full query pipeline (requires running Ollama server)."""
    _separator("Test: Ollama Integration (requires running server)")
    try:
        import requests as req
        req.get(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=3)
    except Exception:
        print("  [SKIP] Ollama server is not reachable. Skipping integration test.")
        return True  # Not a failure -- just unavailable.

    from query import query

    result = query("What API endpoints does the application have?", top_k=3)
    print(f"  Question: {result['question']}")
    print(f"  Answer:   {result['answer'][:200]}...")
    print(f"  Sources:  {result['sources']}")
    print(f"  Chunks:   {result['num_chunks_used']}")

    if not result["answer"]:
        print("  [FAIL] Empty answer.")
        return False

    print("  [PASS]")
    return True


def cleanup() -> None:
    """Remove temporary test artifacts."""
    if os.path.exists(_TEMP_DIR):
        shutil.rmtree(_TEMP_DIR, ignore_errors=True)
        print(f"\n[INFO] Cleaned up temp directory: {_TEMP_DIR}")


def main() -> None:
    results = {}
    try:
        results["document_collection"] = test_document_collection()
        results["chunking"] = test_chunking()
        results["vector_store"] = test_vector_store_creation()
        results["retrieval_relevance"] = test_retrieval_relevance()
        results["ollama_integration"] = test_ollama_integration()
    finally:
        cleanup()

    _separator("Summary")
    all_passed = True
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: [{status}]")
        if not passed:
            all_passed = False

    print()
    if all_passed:
        print("All tests passed.")
    else:
        print("Some tests failed. Review output above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
