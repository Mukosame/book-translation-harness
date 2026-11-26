# Translate a unit of a book ($lang_from → $lang_to, locale $locale)

## Rules to read first (in this order; later files override earlier ones)
1. Target-language pack: `$lang_pack`. It covers punctuation, quotes, title marks, numbers, names and style defaults.
2. Language-pair profile: `$pair_profile`. It covers typical structural changes and the pitfalls to avoid.
3. Book style guide: `$style_guide`. Read the book background, the book decisions and the summary of **$chapter**. Other chapters' summaries and section-specific rules (index, notes) matter only if your unit contains such segments.
4. Style examples: `$examples`. Match their quality and voice.

## Glossary entries that occur in this unit (from `$glossary`)
```
$glossary_rows
```
- Use the `target` rendering of every `approved` row. `proposed` rows are suggestions: use them unless clearly wrong, and mention any doubts in your final one-line reply.
- Rows with a `context` apply only in that context.
- Never use a `forbidden` variant.
- Use `first_mention` the first time a name occurs in the chapter's running prose: `seen_earlier_in_chapter` tells you whether it already appeared in an earlier unit of this chapter.
- **Precedence:**
  - First-mention parentheses apply to running prose only, never to headings, epigraph attributions, the contents page, the title page or index entries. A term first seen in a heading gets its first-mention form in the first prose segment.
  - Fixed renderings in the style guide win over the glossary for those places.
  - If markup splits a glossary term, keep the term whole and move the placeholder pair to the nearest natural phrase.

## Preceding context (the two segments before this unit, for continuity; do not output)
$context

## Source segments
```
$source_block
```

## Output format
Write `$output` in exactly the same segment format:
- Each source segment's header line `<!-- id type -->`, unchanged, followed by its translation on the next lines and a blank line.
- Every id, in the same order. Do not merge or split segments.

## Hard rules
- **Placeholders:** `{{n}}…{{/n}}` and `{{n/}}` stand for markup (italics, links, note markers). `{{i}}…{{/i}}` adds italics the source lacks; use it only where the target pack's `titles.works` asks for it.
  - Every placeholder in a source segment must appear in its translation exactly once, unchanged.
  - A pair must keep wrapping the translation of the same phrase. It may move with that phrase when word order requires, but pairs must never cross.
- **Completeness:** translate everything; never summarise or skip. Keep the author's tone, irony and asides.
- **Kept in the original language:** bibliographic data (authors, titles of cited works in citations, publishers, years, pages, URLs). Translate the surrounding prose.
- **Index entries:** translate them, and keep locators and placeholders exactly.
- **Image text:** type `fig` segments are labels printed inside an image (axis titles, legends, callouts, table cells), and `alt` is an image description. Translate `fig` as short labels, using the same terms as the prose and the glossary.
- **Text only:** the output contains translation text only (no comments, notes, markdown fences or explanations).
- **Before running done**, check that the placeholder multiset of each segment matches its source.
