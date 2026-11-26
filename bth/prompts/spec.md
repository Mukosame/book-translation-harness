# Write the translation spec for this book ($lang_from → $lang_to, locale $locale)

You set the rules that every translator and reviewer will follow. Work only from the files below.

## Read
- **Project config:** `$book_toml`. It holds the title, languages and options (register, reader address).
- **Target-language pack:** `$lang_pack`. Don't repeat its rules; only record overrides.
- **Language-pair profile:** `$pair_profile`.
- **Extracted source:** `$original_dir`, one file per chapter in segment format. The chapters are:
$chapters
- **Reading:** read the table of contents, the preface/introduction, and 2–3 representative chapters closely (different kinds: narrative, technical, notes/index). Skim **every** chapter well enough to summarise it and to collect its terminology.
- **Entity candidates:** `$candidates`, a frequency list of capitalised sequences.

## Write these three files into `$book` (templates in `$templates`)
1. **`style_guide.md`**
   - Book background: one paragraph on the topic, argument, audience and the author's voice.
   - **Chapter summaries**: one line per chapter file id (e.g. `- ch05: …`, 2–3 sentences each). Translators get these as context.
   - Book decisions: register, reader address, gender policy, abbreviations, what stays untranslated, and overrides of the language pack.
   - **Recurring decisions** that translators working in parallel would otherwise each make differently:
     - fixed renderings of every chapter/part heading, so the contents page, the headings and the running text match;
     - how placeholders sit around title marks and footnote markers;
     - how to handle index sub-entries.
   - **Target title:** if `title_tgt` in `book.toml` is set, it is the target title; the title page must use it. Record it here.
2. **`glossary.csv`**, with columns `$columns`
   - Recurring terms, coined concepts, people, works, organisations and places.
   - Use established $lang_to renderings where you know them. Mark rows you are sure of as `approved`, and everything else as `proposed`. $entities_note
   - **Column meanings:**
     - `target_forms`: other acceptable forms, separated by `;`: inflected forms, and short forms allowed after the first mention (e.g. 荷航 for 荷兰皇家航空);
     - `first_mention`: the full form to use the first time the item appears in a chapter (e.g. 艾伦·图灵（Alan Turing）);
     - `type`: one of person, title, term, org, place, event.
   - **How `bth check` matches rows:**
     - An approved row without a `context` is enforced wherever its `source` occurs in a segment. Matching is a substring match: case-sensitive if `source` contains a capital letter, otherwise case-insensitive.
     - Generic words like "policy" or "intelligence" would therefore raise false alarms. Give them a `context` (context rows are judged by AI QA, not by the script), or leave them out.
   - If a term needs different renderings by context (e.g. "policy" in RL vs. public affairs), use one row per sense and fill `context`.
   - Put variants to avoid in `forbidden`, separated by `;`.
   - For inflected target languages, fill `target_forms`.
3. **`examples.md`**: 5–10 representative passages (argument, humour/irony, term-dense passage, quotation, note, index entry).
   - Each passage: source, exemplary translation, and the key points.
   - Optionally add negative examples of translationese.
   - These set the voice for all translators, so make them excellent.

If the book's target-language title is decided (e.g. a published translation exists), state it in `style_guide.md`.

The harness checks that all three files exist and that the glossary has the required columns.
