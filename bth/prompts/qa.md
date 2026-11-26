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
- Logic and coherence.
- Naturalness of the target language: translationese, the patterns on the language pack's watchlist.
- Tone, register and form of address: consistent with the style guide?
- Pronouns and inferred subjects, when the source language drops them.
- Grammatical gender, when the target language has it.
- Locale-specific wording (locale is set in `$book_toml`).

## Output: JSON Lines, one issue per line, written to `$output`
```
{"id": "<segment id>", "severity": "critical|major|minor", "category": "<one of: omission addition mistranslation negation number terminology logic fluency tone register gender pronoun punctuation locale structure source>", "src": "<short source excerpt>", "tgt": "<short translation excerpt>", "suggestion": "<corrected target text for that excerpt>", "rationale": "<one sentence in $report_lang>", "source_error": false}
```

**Severity levels**
- `critical`: the meaning is reversed or wrong, a number is wrong, or a sentence is dropped.
- `major`: the meaning is skewed, a term is wrong, or the text is clearly unnatural.
- `minor`: wording, punctuation, or mild translationese.

**Other rules**
- **Errors in the original:** a wrong name, title, date or fact in the source is reported as category `source`, with `"source_error": true` and severity `minor`.
  - `suggestion` is the correct form, or empty.
  - The translation follows the original unless the glossary says otherwise.
  - Typos in the source that the translation silently fixes are not worth reporting.
- **Minor issues:** $minor_note
- Report real problems only. Write an empty file if there are none.
