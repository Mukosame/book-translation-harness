# Transcribe the text inside images ($lang_from → $lang_to)

Some figures in this book are pictures: charts, diagrams, maps, or tables saved as images. Their labels never reach the text pipeline, so you transcribe them here. Translators translate your strings later, and the build adds a key under each image.

## Images in this task
Open each file and look at it (for SVG files, the text is in the file).
$figures

## What to transcribe
- Every piece of text a reader needs in order to understand the image: titles, axis titles, category and legend labels, annotations, callouts, column and row headers, and table cells.
- **One item per label.** Join the lines of a label that wraps across several lines ("Annual / growth rate" → "Annual growth rate").
- List each distinct label once, in reading order (top to bottom, left to right).
- Copy the text exactly as printed; fix nothing.

## What to leave out
- Text that needs no translation: bare numbers, years, tick values, units and symbols (`%`, `km`, `2006`), single letters marking panels (`a`, `b`), and text already in $lang_to.
- Logos, signatures, publisher marks and copyright lines.
- Text that also appears as a caption next to the image (shown under "nearby text"); it is translated there already.

## Kind of image
Pick one: `chart`, `diagram`, `table`, `map`, `photo`, `illustration`, `cover`, `decorative`, `text` (a scanned page or quotation). Photos and decorative images usually have no items.

## Output: JSON Lines written to `$output`, exactly one line per image above
```
{"image": "<image path as given above>", "kind": "chart", "items": ["Average monthly rainfall", "North", "South"]}
```
Use `"items": []` for an image without text that needs translating.
