# Fix reported issues ($lang_from → $lang_to)

QA found the issues below. Revise the affected segments with **minimal, targeted edits**. Don't rewrite sentences that are fine.

Follow these, as in translation:
- `$lang_pack`
- `$pair_profile`
- `$style_guide`
- `$glossary`

## Issues (JSON Lines)
$issues

## Source
```
$source_block
```

## Current translation
```
$current_block
```

## Output
Write `$output` in the segment format:
- Include **only the segments you changed**, each with its unchanged header line `<!-- id type -->` followed by the full revised text.
- Keep every placeholder exactly as in the source.

If you judge that an issue is not a real problem, leave the segment out. The harness logs before/after for every change.
