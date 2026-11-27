# Locate and transcribe the text inside images ($lang_from → $lang_to)

Some figures in this book are pictures: charts, diagrams, maps, or tables saved as images. Their labels never reach the text pipeline. You transcribe each label **and mark where it sits**. Translators translate the labels later, and the build sets each translation **into the image in place of the original label**: it covers the old text with the background colour and fits the new text into the space you mark. Readers see a translated figure, so your positions decide the quality.

## Images in this task
$figures

Open each file and look at it. Coordinates are **pixels of the original file**, origin at the top left, x to the right, y down. The sizes are given above. If your viewer shows a scaled-down copy, convert your coordinates to the original size. If you can run code (for example Python with Pillow), crop each box to check that it holds exactly its label.

## What to transcribe
- Every piece of text a reader needs to understand the image: titles, axis titles, category and legend labels, annotations, callouts, column and row headers, and table cells.
- **One label per visual text block.** Join the lines of a label that wraps ("Annual / growth rate" → one label, its box covering both lines). The same text in two places is two labels.
- Copy the text exactly as printed; fix nothing.

## What to leave out
- Text that needs no translation: bare numbers, years, tick values, units and symbols (`%`, `km`, `2006`), single letters marking panels (`a`, `b`), and text already in $lang_to.
- Logos, signatures, publisher marks and copyright lines.
- Text on a busy background (a photo, a gradient, artwork), where covering it would damage the image. Leave such images to a person; most covers belong here.

## Fields of a label
- `text`: the label as printed.
- `box`: `[x0, y0, x1, y1]`, the tight box around the printed text. It is covered with `background`, so include every stroke of the text and nothing else.
- `space` (optional): `[x0, y0, x1, y1]`, the free area the translation may use, containing `box`. The translation may be longer than the original (Chinese → English often doubles the width), so extend it into **empty** background only, never over lines, bars, points or other labels. Without it, the translation is shrunk into `box`.
- `align`: `start` (left-aligned, e.g. legend entries and labels to the right of a marker), `middle` (centred, e.g. axis titles and table cells) or `end` (right-aligned, e.g. labels left of a y-axis).
- `rotate`: `0`, or `-90` / `90` for text running bottom-to-top / top-to-bottom. Vertical stacked $lang_from text can become `-90` in $lang_to.
- `color` and `background`: `#rrggbb` of the text and of the area behind it (default `#000000` on `#ffffff`). Sample them from the image.
- `weight`: `normal` or `bold`.

## Kind of image
Pick one: `chart`, `diagram`, `table`, `map`, `photo`, `illustration`, `cover`, `decorative`, `text` (a scanned page or quotation). Photos and decorative images usually have no labels.

## Output: JSON Lines written to `$output`, exactly one line per image above
```
{"image": "<image path as given above>", "kind": "chart", "labels": [{"text": "Average monthly rainfall", "box": [412, 18, 806, 52], "space": [300, 10, 920, 60], "align": "middle", "rotate": 0, "color": "#222222", "background": "#ffffff", "weight": "bold"}]}
```
Use `"labels": []` for an image without text that needs translating.

## Check your boxes before you finish
1. Run `$preview_cmd`. It prints the paths of PNG previews: each `box` in red with its number, each `space` dashed in blue.
2. Look at every preview. Fix any box that cuts off a stroke, includes a line or point of the chart, or is offset, and any space that overlaps content. Run the preview again after fixing.
3. If the command reports SVG files instead of PNGs, previews are not available here: check your coordinates by cropping instead.
