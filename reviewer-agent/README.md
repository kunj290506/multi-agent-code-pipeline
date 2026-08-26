# Reviewer / QA Agent

**Owner**: Member B

The Reviewer/QA Agent performs automated code review on every artifact produced by the Code-Gen Agent. It checks for correctness, adherence to coding standards, potential security vulnerabilities, and logical bugs using a combination of LLM-based reasoning and static analysis tools.
If the code does not meet quality thresholds, it generates a structured feedback report and triggers a re-generation loop with the Code-Gen Agent until the output passes all checks.
This agent ensures that only reviewed, high-quality code reaches the target application.
