# Verify quotations ($lang_from → $lang_to, locale $locale)

**Goal:** when the book quotes someone who wrote in another language, the $lang_from text is itself a translation. Translating it again drifts away from what the author actually wrote. Find the original wording, so the translation can use the author's own words (or an established $lang_to translation), and so unverified quotations are never presented as the author's original words.

## Inputs
- Candidates: `$quote_candidates` (segment id and quoted text: quoted spans and block quotations).
- Source chapters: `$original_dir`, for context (who is quoted, the note that gives the source).
- Current quotation table: `$book/quotes.csv` (if it exists).

## Which quotations
Only direct quotations whose original language is **not $lang_from**: quotations attributed to a foreign author, work, speech or document, and quotations carrying a note reference to a foreign source. Skip quotations originally written in $lang_from, scare quotes, and short phrases. Prioritise epigraphs, quotations on the cover and title pages, and quotations that recur.

## Method
1. Identify the author, the work and, if a note gives it, the exact source.
2. Search for the original text: the author's book or article, an official transcript, a reputable archive, Wikiquote with a cited source. Search in the original language and in $lang_from.
3. If the original language is not $lang_to, look for an established $lang_to translation (a published translation of the work).
4. Never reconstruct a quotation from memory or by back-translating. If you cannot find it in a source you can cite, the row is `unverified`.

## Output
A CSV file written to `$output`, header `$quote_columns`, one row per quotation:
- `id`: the segment id. `quote`: the $lang_from text as it appears in the book (the quoted part only).
- `author`, `work`, `lang`: who, where, and the BCP-47 tag of the original language.
- `original`: the original wording, copied exactly from the source.
- `use`: the exact $lang_to wording the translation must use. It is `original` when `lang` is $lang_to, or an established published $lang_to translation, or empty (translators then translate from `original`).
- `status`: `verified` only with an `evidence` URL where the original wording can be read; otherwise `unverified`.
- `evidence`: the URL. `note`: anything a translator should know (a misquotation in the book, a partial quotation).

**If you have no web access**, write every row as `unverified`; the translation will then mark these quotations.
