# AGENTS.md: driving the book translation harness

This file is for AI agents. Any agent runtime works (Claude Code, Codex, Cursor, Gemini CLI, Copilot, an SDK loop…) as long as the agent can **run shell commands** and **read/write files**.

The harness (`bth`) does every deterministic step and validates all agent output. Agents do only the language work: spec, entity verification, translation, QA, fixes and back-translation.

## Roles

There are two roles. One agent can play both, but parallel workers are much faster.

### Orchestrator

Loop until done:

```
bth next <book>          # prints one JSON action
```

| `action` | What to do |
|---|---|
| `dispatch` | Start `workers` agents **in parallel**. Give each one the worker brief below, with a unique `--worker` name and the `phase` from the action. Wait for all of them to finish, then call `bth next` again. |
| `wait` | Tasks are claimed by workers that are still running. Wait for them, then call `bth next`. |
| `attention` | A gate failed (e.g. extraction coverage). Show the JSON to the user and stop. |
| `done` | Report the `output` EPUB, `report` (QA_REPORT.md), `problems` and `qa` stats to the user. |

### Worker brief

Paste this into each worker agent and fill in the placeholders:

> You are a worker for the book translation harness. Repeat until the claim returns `"task": null`:
> 1. Run `bth claim <book> --phase <phase> --worker <name>`. It prints JSON with `prompt` and `output` paths.
> 2. Read the prompt file and do exactly what it says. Write the result to the `output` path.
> 3. Run the `bth done …` command given at the end of the prompt. If it prints `"ok": false`, fix your output file and run it again.
>
> Finish with one line: the tasks you completed and any you could not finish.

## Rules for every agent

- **Never edit `original/`, `translation/` or `work/tasks/` by hand.** The harness merges outputs under a lock, keeps an audit trail, and protects human edits.
- **Entity verification needs web access.** The prompts say how to proceed without it. Turn the phase off with `entities = false` in `book.toml` if needed.
- **The `figures` phase needs agents that can view images.** They transcribe the labels inside charts, diagrams and tables saved as pictures. Turn it off with `figures = false` if your agents cannot view images.
- **Report counts by running commands** such as `bth status` and `bth check`, not from memory.

## Commands

| Command | Purpose |
|---|---|
| `bth init <book> --source FILE --from en --to zh-Hans [--locale zh-Hans-CN]` | Create a project (EPUB > HTML > TXT > PDF; scanned PDFs need OCR first). |
| `bth next <book>` | Advance the pipeline; prints the next action. |
| `bth claim <book> [--phase P] [--worker W]` / `bth done <book> TASK` | Worker protocol. |
| `bth status <book>` | Task and segment counts. |
| `bth check <book> [--ids …] [--json]` | Deterministic checks (structure, numbers, glossary, punctuation, names, length). |
| `bth report <book>` | Write `review/QA_REPORT.md` (high-risk segments, spot-check sample). |
| `bth build <book>` | Write `dist/<book>.<lang>.epub` and `dist/bilingual.html`, and verify them. |
| `bth plan <book> translate --chapters ch05` | Re-translate a scope, e.g. after a style-guide change. Human edits are kept. |
| `bth impact <book> --since <git-rev>` or `--terms "policy"` | Plan revisions for the segments affected by glossary changes. |

## Human corrections

People can correct the translation at any point, with three levers:
- `glossary.csv`, followed by `bth impact`;
- `style_guide.md` / `examples.md`, followed by `bth plan … translate --chapters …`;
- direct edits in `translation/*.md`.

For images, a translated copy saved under `figures/` with the original file name replaces the image at build time.

Directly edited segments are detected automatically and locked against future machine merges. Then run `bth next` again. The full method is in `docs/SOP.md`.

## Working on the harness code itself

Follow the ponytail rules (https://github.com/DietrichGebert/ponytail):
- Make the smallest complete change. Reuse before adding, prefer the stdlib, and add no new dependencies for a few lines.
- Language-specific behaviour belongs in `bth/langs/*.toml` / `bth/pairs/*.md`, never in code.
- Non-trivial logic gets a small test in `tests/`. Run `python -m unittest discover -s tests`.
- Mark known limits with `shortcut: <limit>, <when to upgrade>` comments.
- Never cut input validation, data-loss protection (locks, human-edit protection) or security.
