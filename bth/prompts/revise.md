# Apply glossary changes ($lang_from → $lang_to)

A reviewer changed the glossary. Update the segments below so that they follow the new entries.

## Changed glossary rows
```
$terms
```
- If a row only has `source`, look up its current entry in `$glossary`.
- If a row has a `context`, apply it only where that context holds.

## Source
```
$source_block
```

## Current translation
```
$current_block
```

## Output
Write `$output` in the segment format.
- Include **only the segments you changed**: the unchanged header line, then the full revised text.
- Change only what the glossary change requires. Adjust the surrounding grammar if needed, and keep everything else, including every placeholder.
