# QA review of a translated unit ($lang_from → $lang_to)

You are an independent reviewer. You **report** problems; you do not edit any file except your output.

Read for reference:
- `$lang_pack`
- `$pair_profile` (its "common mistranslations" section lists what to look for first)
- `$style_guide`: the book decisions and the summary of **$chapter**.

Book files (style guide, glossary) override the pair profile and language pack. `seen_earlier_in_chapter` says whether a name already appeared earlier in the chapter (relevant for first-mention forms).

Preceding context (not under review):
$context

Glossary rows that occur in this unit:
```
$glossary_rows
```

## Source
```
$source_block
```

## Current translation
```
$current_block
```

## What to check, segment by segment (compare with the source)
- Omissions and additions.
- Mistranslations, especially **negation, comparison, causality, condition and modality**.
- Numbers and formulas.
- Terminology: does it match the glossary and the context?
- Quotations: verified ones use the wording in `$book/quotes.csv`; unverified ones carry the marker from the language pack; a title or quotation that recurs is rendered as elsewhere in the book.
- Logic and coherence.
- Naturalness of the target language: translationese, the patterns on the language pack's watchlist.
- Tone, register and form of address: consistent with the style guide?
- Pronouns and inferred subjects, when the source language drops them.
- Grammatical gender, when the target language has it.
- Locale-specific wording (locale is set in `$book_toml`).
- Type `fig` segments are labels inside an image: check that they are concise, consistent with the prose and the glossary, and do not add words the label lacks.
  - Rendered images with the translated labels set in (if this unit has any):
$figure_previews
  - Look at each one. Report a label that is cut off, too small to read, overlaps the chart, or leaves original text visible, as category `structure` on the label's segment id; suggest a shorter wording if that would help.

## Output: JSON Lines, one issue per line, written to `$output`
```
{"id": "<segment id>", "severity": "critical|major|minor", "category": "<one of: omission addition mistranslation negation number terminology logic fluency tone register gender pronoun punctuation locale structure source>", "src": "<short source excerpt>", "tgt": "<short translation excerpt>", "suggestion": "<corrected target text for that excerpt>", "rationale": "<one sentence in $report_lang>", "source_error": false}
```
For errors in the original, add `"obvious": true|false`, `"evidence": "<URL or reasoning>"` and `"note": "<one-sentence translator's note in $lang_to, e.g. the original gives 1987; the correct year is 1978>"`.

**Severity levels**
- `critical`: the meaning is reversed or wrong, a number is wrong, or a sentence is dropped.
- `major`: the meaning is skewed, a term is wrong, or the text is clearly unnatural.
- `minor`: wording, punctuation, or mild translationese.

**Other rules**
- **Errors in the original:** a wrong name, title, date or fact in the source is reported as category `source`, with `"source_error": true` and severity `minor`.
  - `suggestion` is the translation as it would read **with the error corrected**, or empty if you are unsure of the correct form.
  - `obvious`: true only for a slip nobody would dispute (a misspelled name, a wrong year or title confirmed by a reliable source).
  - Project policy: $source_errors_rule Report errors whatever the policy; the harness decides which are corrected. A translation that already corrected an error on its own is a deviation from the policy unless the policy allows it: report it too.
- **Minor issues:** $minor_note
- Report real problems only. Write an empty file if there are none.
