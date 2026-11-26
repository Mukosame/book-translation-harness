# Verify established renderings: $scope ($lang_from → $lang_to, locale $locale)

**Goal:** wherever an established $lang_to rendering exists, the translation must use it. Your scope is **$scope** only.

## Inputs
- Candidates: `$candidates` (frequency list).
- Current glossary: `$glossary`.
- Source chapters: `$original_dir`. Search them for further items in your scope.
- Language pack: `$lang_pack`. Its `[names]` section has the transliteration standard and the preferred sources.

## Method
1. **Check for an existing translation.** Find out whether this book already has a $lang_to translation, via WorldCat, the national library catalogue, or retailer and catalogue sites. If it does, its title and its renderings of key terms take priority.
2. **Look up each item** in this order:
   1. Wikidata labels in $lang_to;
   2. the sources listed in the language pack;
   3. official sites (for organisations) and catalogue entries of published translations (for works).

   Search in both languages.
3. **Prioritise:** handle well-known items and published works first. For obscure people with no established form, apply the transliteration standard and flag only clear errors.
4. **Report errors in the original** (e.g. a misnamed person) in `note`, with the correct form as `target`.
5. **If you have no web access**, still give your best rendering, but write `unverified` in `evidence` and set `status` to `proposed`.

## Output
A CSV file written to `$output`.
- **Header:** `$columns`
- **Rows to include:** one per item that is new, corrected, or confirmed with evidence.
- **`status`:** `approved` only when backed by a source; put the URL in `evidence`.
- **Variants:** list variants that must not be used in `forbidden`.

The harness merges your rows into the glossary. Approved rows are only overwritten by other approved rows.
