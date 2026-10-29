# ADR 0001: LangGraph for review orchestration

Status: Accepted

Context: Reviews last days or weeks and pause for human gates. Work must resume after crashes and must not repeat completed steps.

Decision: Use LangGraph with explicit nodes, persisted checkpoints, and interrupts at each human gate.

Consequences: The orchestrator decides what happens next. Agents only produce content. Graph changes need a recompile and a test run.
