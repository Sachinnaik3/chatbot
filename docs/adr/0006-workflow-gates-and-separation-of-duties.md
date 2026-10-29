# ADR 0006: Six human gates with separation of duties

Status: Accepted

Context: Regulated change approval needs maker-checker controls, clear ownership per step, and resistance to replayed or out-of-order requests.

Decision: A LangGraph interrupt before every gate. Gate policy in configs/gates.yaml defines deciding teams, editable fields, and separation of duties. The service accepts a decision only for the gate the review is waiting at. Returned gates rerun the producing step; a rejected approval ends the review.

Consequences: Process changes are configuration changes, reviewed like code. Agents run with the requester's access, never more.
