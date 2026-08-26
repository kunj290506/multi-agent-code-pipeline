# n8n Orchestration Workflows

**Owner**: Member A

This directory contains n8n workflow JSON definitions that visually orchestrate the entire multi-agent pipeline. Each workflow maps to a specific pipeline stage — triggering agents, routing data between them, handling retries, and surfacing results to the end user via webhooks or a chat interface.
n8n connects to each agent's HTTP/gRPC endpoint and manages the event-driven flow, making it easy to inspect, debug, and modify the pipeline without touching agent code.
Workflows are version-controlled here as exported JSON files and can be imported directly into a running n8n instance via the n8n UI or the n8n CLI.
