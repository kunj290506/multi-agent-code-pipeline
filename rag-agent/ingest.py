"""
Document Ingestion Pipeline.

Reads source code and documentation files from a directory tree, splits them
into chunks suitable for embedding, and stores the resulting vectors in a
local ChromaDB collection.
"""

import os
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma

import config


def collect_documents(source_dir: str) -> list[dict]:
    """Walk *source_dir* and return a list of dicts with 'content' and 'metadata'.

    Only files whose extension is in ``config.SUPPORTED_EXTENSIONS`` are
    included.  Binary files and files that cannot be decoded as UTF-8 are
    silently skipped.
    """
    source_path = Path(source_dir).resolve()
    if not source_path.exists():
        raise FileNotFoundError(
            f"Source directory does not exist: {source_path}"
        )

    documents: list[dict] = []
    for root, _dirs, files in os.walk(source_path):
        for filename in files:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in config.SUPPORTED_EXTENSIONS:
                continue
            filepath = os.path.join(root, filename)
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as fh:
                    content = fh.read()
            except (OSError, UnicodeDecodeError):
                continue
            if not content.strip():
                continue
            relative = os.path.relpath(filepath, source_path)
            documents.append({
                "content": content,
                "metadata": {
                    "source": relative,
                    "extension": ext,
                    "absolute_path": filepath,
                },
            })
    return documents


def chunk_documents(
    documents: list[dict],
    chunk_size: int = config.CHUNK_SIZE,
    chunk_overlap: int = config.CHUNK_OVERLAP,
) -> tuple[list[str], list[dict]]:
    """Split raw documents into overlapping text chunks.

    Returns:
        A tuple of (texts, metadatas) suitable for direct insertion into
        a vector store.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", " ", ""],
    )

    texts: list[str] = []
    metadatas: list[dict] = []

    for doc in documents:
        chunks = splitter.split_text(doc["content"])
        for idx, chunk in enumerate(chunks):
            texts.append(chunk)
            metadatas.append({
                **doc["metadata"],
                "chunk_index": idx,
                "total_chunks": len(chunks),
            })

    return texts, metadatas


def build_vector_store(
    texts: list[str],
    metadatas: list[dict],
    persist_directory: str = config.CHROMA_PERSIST_DIR,
    collection_name: str = config.CHROMA_COLLECTION_NAME,
) -> Chroma:
    """Create (or overwrite) a ChromaDB collection from the given chunks.

    The collection is persisted to disk so it can be loaded later without
    re-ingesting.
    """
    embeddings = HuggingFaceEmbeddings(
        model_name=config.EMBEDDING_MODEL_NAME,
        model_kwargs={"device": "cpu"},
    )

    vector_store = Chroma.from_texts(
        texts=texts,
        metadatas=metadatas,
        embedding=embeddings,
        persist_directory=persist_directory,
        collection_name=collection_name,
    )
    print(
        f"[OK] Stored {len(texts)} chunks in ChromaDB "
        f"(collection: '{collection_name}', path: '{persist_directory}')"
    )
    return vector_store


def ingest(source_dir: str | None = None) -> Chroma:
    """End-to-end ingestion: collect -> chunk -> embed -> store.

    Args:
        source_dir: Path to the directory containing source files.
                    Defaults to ``config.DEFAULT_SOURCE_DIR``.

    Returns:
        The populated ChromaDB vector store instance.
    """
    source_dir = source_dir or config.DEFAULT_SOURCE_DIR
    print(f"[...] Collecting documents from: {source_dir}")
    documents = collect_documents(source_dir)
    print(f"[OK] Found {len(documents)} files to ingest.")

    if not documents:
        print("[WARN] No documents found. The vector store will be empty.")
        # Still create an empty store so downstream code does not break.
        embeddings = HuggingFaceEmbeddings(
            model_name=config.EMBEDDING_MODEL_NAME,
            model_kwargs={"device": "cpu"},
        )
        return Chroma(
            persist_directory=config.CHROMA_PERSIST_DIR,
            embedding_function=embeddings,
            collection_name=config.CHROMA_COLLECTION_NAME,
        )

    texts, metadatas = chunk_documents(documents)
    print(f"[OK] Split into {len(texts)} chunks.")

    return build_vector_store(texts, metadatas)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Ingest documents into the RAG vector store.")
    parser.add_argument(
        "--source-dir",
        default=None,
        help=f"Source directory (default: {config.DEFAULT_SOURCE_DIR})",
    )
    args = parser.parse_args()
    ingest(source_dir=args.source_dir)
