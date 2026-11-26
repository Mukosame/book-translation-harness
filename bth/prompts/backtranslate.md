# Back-translate high-risk segments into $report_lang

A reviewer who may not read both languages uses your back-translation to judge whether the meaning drifted.

- Translate the **current translation** below back into $report_lang **literally**. Do not look at or polish toward the source; the point is to expose what the translation actually says.
- Ignore placeholders `{{n}}`.

## Current translation
```
$current_block
```

## Output: JSON Lines, written to `$output`
One line per segment:

```
{"id": "<segment id>", "text": "<literal back-translation>"}
```
