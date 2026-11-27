---
name: book-translation
description: Translate a whole book (EPUB, HTML, TXT or PDF) between any two languages with parallel subagents, using the bth harness. It covers extraction, the translation spec (style guide, glossary, examples), online verification of names, translation, QA and fixes, and an EPUB build. Use when the user asks to translate a book or to revise an existing bth translation project.
---

# Book translation with bth

You are the **orchestrator**. The `bth` CLI does every deterministic step and validates every output. You and your subagents do the language work.

## Setup (once per book)

1. Make sure `bth` is installed: `pip install git+https://github.com/Mukosame/book-translation-harness` (or `pip install -e .` in a clone). For PDF sources, also install `pymupdf`.
2. Create the project:
   `bth init <book_dir> --source <file> --from <bcp47> --to <bcp47> [--locale <variant>]`
3. Confirm with the user before starting:
   - the target title, if known;
   - register and form of address;
   - whether names may be verified online (`entities` in `book.toml`);
   - whether your subagents can view images (`figures` in `book.toml`; needed to translate text inside charts and tables);
   - how to treat errors in the original (`source_errors`: `keep`, `fix-obvious`, or `fix-with-note` with an errata page or inline translator's notes).
4. If `bth init` reports a missing language pack, draft `bth/langs/<tag>.toml` from `bth/langs/zh-Hans.toml` and ask the user to review it.

## Loop

Run `bth next <book_dir>` and act on its JSON:

- **`dispatch`**: launch `workers` subagents **in a single message, in parallel**. Give each one the worker brief from `AGENTS.md`, with its own `--worker` name and the `phase` from the action. When all of them have returned, run `bth next` again.
- **`wait`**: some tasks are still claimed. Wait for those workers, then run `bth next` again.
- **`attention`**: show the JSON to the user and stop.
- **`done`**: report the EPUB path, `review/QA_REPORT.md`, `problems`, and the QA statistics.

## Checkpoint: let the user shape the spec

After the `spec` phase, offer the user a look at these before translating:
- `style_guide.md`
- the key rows of `glossary.csv`
- `examples.md`

It is cheap and has a big effect on quality. Proceed when the user is satisfied or asks you to continue.

## After delivery

The user can change the translation through three levers:
1. **Glossary:** edit `glossary.csv`, then run `bth impact <book> --since <rev>` (or `--terms …`), then `bth next`.
2. **Style:** edit `style_guide.md` or `examples.md`, run `bth plan <book> translate --chapters <ids>` on a sample chapter, compare the output, then widen the scope.
3. **Direct edits:** edit `translation/*.md`. These segments are locked automatically. Rebuild with `bth next`.
4. **Images:** labels inside images are `fig` segments and are set into the image at build time; correct them like any segment. For a redrawn figure, save it under `<book_dir>/figures/` with the same file name, then rebuild. `review/QA_REPORT.md` lists the images that contain text.
5. **Quotations:** edit `quotes.csv` (verified wording with an evidence URL), then `bth impact <book> --terms "<quote excerpt>"` and `bth next`.
