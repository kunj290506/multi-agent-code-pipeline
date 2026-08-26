# Planner Agent

**Owner**: Member A

The Planner Agent acts as the central orchestrator of the multi-agent pipeline. It receives high-level user intent (e.g., "build a REST API for user authentication"), decomposes it into structured subtasks, and delegates each subtask to the appropriate downstream agent (RAG, Code-Gen, Reviewer, or DB).
It maintains conversation context, tracks task state, and aggregates results from all agents before returning a coherent final output to the user.
