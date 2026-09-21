"""
RAG Query Engine.

Loads the persisted ChromaDB vector store and provides a function that:
1. Retrieves the most relevant document chunks for a given question.
2. Sends those chunks along with the question to the local Ollama model.
3. Returns a structured JSON answer with the response and source references.
"""

import json
import os
import sys

from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma

import config

# Shared LLM dispatch
_SHARED = os.path.join(os.path.dirname(__file__), "..", "shared")
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)
from llm import call_llm  # noqa: E402


def load_vector_store() -> Chroma:
    """Load the persisted ChromaDB collection."""
    embeddings = HuggingFaceEmbeddings(
        model_name=config.EMBEDDING_MODEL_NAME,
        model_kwargs={"device": "cpu"},
    )
    return Chroma(
        persist_directory=config.CHROMA_PERSIST_DIR,
        embedding_function=embeddings,
        collection_name=config.CHROMA_COLLECTION_NAME,
    )


def retrieve_context(vector_store: Chroma, question: str, top_k: int = 5) -> list[dict]:
    """Return the top-k most relevant chunks for *question*.

    Each result is a dict with 'content' and 'metadata' keys.
    """
    results = vector_store.similarity_search_with_relevance_scores(
        question, k=top_k
    )
    context_items = []
    for doc, score in results:
        context_items.append({
            "content": doc.page_content,
            "metadata": doc.metadata,
            "relevance_score": round(float(score), 4),
        })
    return context_items


def generate_answer(question: str, context_items: list[dict]) -> str:
    """Call the Ollama model with the question and retrieved context.

    Returns the raw text response from the model.
    """
    context_text = "\n\n---\n\n".join(
        f"Source: {item['metadata'].get('source', 'unknown')}\n{item['content']}"
        for item in context_items
    )

    prompt = (
        "You are a knowledgeable assistant for a software codebase. "
        "Use the following context excerpts to answer the user's question. "
        "If the context does not contain enough information, say so honestly.\n\n"
        "=== CONTEXT ===\n"
        f"{context_text}\n\n"
        "=== QUESTION ===\n"
        f"{question}\n\n"
        "=== ANSWER ===\n"
    )

    llm_result = call_llm(
        prompt,
        temperature=0.2,
        max_tokens=512,
        timeout=120,
    )
    if llm_result.schema_errors:
        print(f"[WARN] LLM backend issues: {llm_result.schema_errors}")
    return llm_result.text.strip()


def query(question: str, top_k: int = 5) -> dict:
    """Full RAG pipeline: retrieve context, generate answer, return structured result.

    Returns:
        A dict with keys:
        - question: the original question
        - answer: the model's response
        - sources: list of source references used
        - num_chunks_used: number of context chunks sent to the model
        - confidence: max similarity score across retrieved chunks (0–1)
        - low_confidence: True if confidence < 0.5
    """
    vector_store = load_vector_store()
    context_items = retrieve_context(vector_store, question, top_k=top_k)

    if not context_items:
        return {
            "question": question,
            "answer": "No relevant documentation was found in the vector store.",
            "sources": [],
            "num_chunks_used": 0,
            "confidence": 0.0,
            "low_confidence": True,
        }

    answer = generate_answer(question, context_items)

    sources = list({
        item["metadata"].get("source", "unknown")
        for item in context_items
    })

    # Confidence is the MAX relevance score across retrieved chunks (0–1).
    scores = [item.get("relevance_score", 0.0) for item in context_items]
    confidence = round(max(scores), 4) if scores else 0.0
    low_confidence = confidence < 0.5

    return {
        "question": question,
        "answer": answer,
        "sources": sorted(sources),
        "num_chunks_used": len(context_items),
        "confidence": confidence,
        "low_confidence": low_confidence,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Query the RAG agent.")
    parser.add_argument("question", help="Natural-language question to ask.")
    parser.add_argument(
        "--top-k", type=int, default=5, help="Number of chunks to retrieve."
    )
    args = parser.parse_args()

    result = query(args.question, top_k=args.top_k)
    print(json.dumps(result, indent=2))
