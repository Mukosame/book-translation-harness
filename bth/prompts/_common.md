---
## Worker protocol (applies to every task)

- Task: `$task` (phase `$phase`) in book project `$book`.
- Write your result to: `$output` (for the spec phase this is the project directory; write the files listed above into it)
- When the file is complete, run: `$done_cmd`
  - It prints JSON. If `"ok": false`, fix every listed error in your output file and run it again.
  - Never edit files under `original/`, `translation/` or `work/tasks/` directly; the harness merges your output.
- Then claim the next task with the same `bth claim` command you used before, until it returns `"task": null`.
- Reply to your orchestrator with one line: tasks completed and any task ids you could not finish.
