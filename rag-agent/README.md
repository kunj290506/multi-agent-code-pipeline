# RAG Agent

**Owner**: Member A

The RAG (Retrieval-Augmented Generation) Agent is responsible for ingesting project documentation, API specs, and coding guidelines into a Qdrant or Chroma vector database and retrieving the most relevant context snippets on demand.
When the Planner assigns a code generation task, this agent supplies the Code-Gen agent with up-to-date, project-specific documentation so that generated code aligns with existing patterns and standards.
It uses LangChain's document loaders, text splitters, and embedding models (via Ollama) to build and query the vector store.
