# Runbook: wrong or outdated knowledge item

Signal: reviewers reject drafts citing the same source; feedback rejection rate rises for one source.
1. Retire the item (`retire_where` on the index; `retired = true` in `knowledge_chunks`).
2. List reviews that cited it (draft sources carry source_id and version) and notify their owners.
3. Fix the item with its owner, publish a new version, and add a golden case.
