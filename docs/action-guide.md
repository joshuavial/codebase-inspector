# Action Guide: Judgement Task Inspection and Submission Across Refs

This guide documents how agents and CI automation interact with open architectural judgement tasks (such as `summarise-architecture-change`, `summarise-files`, `define-concepts`, and `confirm-structure`) across working trees and historical Git refs via MCP.

---

## Background & Historical Ref Resolution

When performing automated architectural reviews (via `cbi review` or `cbi_review`) and diffs (via `cbi diff` or `cbi_diff`), change tasks such as `summarise-architecture-change` (`sac-...`) are opened directly in the head commit's database:

```
.cbi/refs/<head_sha>/model.db
```

To enable agents reviewing PRs and commits over MCP to inspect and resolve these tasks, the judgement task tools declare an optional `ref` parameter matching the CLI's `--ref` capabilities:

- `cbi_tasks`: Query open judgement tasks on a branch, tag, or commit ref (`ref` defaults to working tree).
- `cbi_task`: Read full task brief, examine partitioned parts, or pre-validate draft answers against the schema on a specific ref (`ref` defaults to working tree).
- `cbi_submit`: Submit a verified JSON answer to resolve a task on a specific ref (`ref` defaults to working tree), writing directly to the ref's `model.db` and updating the answer cache.

---

## MCP Tool Parameters

### 1. `cbi_tasks`
- `ref` (*string, optional*): Git ref, branch, or commit SHA to inspect tasks from (default: working tree).
- `kind` (*string, optional*): Filter tasks by kind (e.g., `summarise-architecture-change`, `summarise-files`, `define-concepts`).
- `task_id` (*string, optional*): Specific task ID to fetch brief for.
- `limit` (*integer, optional*): Maximum number of open tasks to return (default: 20).
- `offset` (*integer, optional*): Pagination offset (default: 0).
- `format` (*string, optional*): Output format (`text` or `json`).

### 2. `cbi_task`
- `task_id` (*string, required*): The task ID to inspect (e.g. `sac-...`, `sf-...`, `dc-...`).
- `ref` (*string, optional*): Git ref, branch, or commit SHA where the task was created (default: working tree).
- `parts` (*boolean, optional*): Return index of partitioned parts for large briefs.
- `part` (*integer, optional*): 1-based part index to read for a large brief.
- `check` (*string, optional*): JSON string draft to validate against task schema without submitting.
- `format` (*string, optional*): Output format (`text` or `json`).

### 3. `cbi_submit`
- `task_id` (*string, required*): ID of the open judgement task.
- `answer` (*object or string, required*): Answer matching the task's JSON schema.
- `ref` (*string, optional*): Git ref, branch, or commit SHA where the task was created (default: working tree).

---

## Agent Review Workflow Example

1. **Perform Architecture Review**:
   ```json
   {
     "name": "cbi_review",
     "arguments": {"target": "HEAD", "base": "main", "format": "json"}
   }
   ```

2. **List Open Change Tasks on the Head Ref**:
   ```json
   {
     "name": "cbi_tasks",
     "arguments": {"ref": "HEAD", "kind": "summarise-architecture-change", "format": "json"}
   }
   ```

3. **Inspect the Task Brief & Allowed Citations**:
   ```json
   {
     "name": "cbi_task",
     "arguments": {"task_id": "sac-...", "ref": "HEAD", "format": "json"}
   }
   ```

4. **Pre-validate the Proposed Answer**:
   ```json
   {
     "name": "cbi_task",
     "arguments": {
       "task_id": "sac-...",
       "ref": "HEAD",
       "check": "{\"input_hash\":\"...\",\"narrative\":\"...\",\"citations\":[...]}"
     }
   }
   ```

5. **Submit the Answer to Resolve the Task on the Ref**:
   ```json
   {
     "name": "cbi_submit",
     "arguments": {
       "task_id": "sac-...",
       "ref": "HEAD",
       "answer": {
         "input_hash": "...",
         "narrative": "...",
         "citations": [...]
       }
     }
   }
   ```

Submitted answers are cached across reviews and diffs, closing the task on `.cbi/refs/<head_sha>/model.db` and clearing pending review notices.
