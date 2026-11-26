# Standard operating procedure: whole-book AI translation (any language pair)

This is the method the harness implements. `AGENTS.md` is the short operational version for agents. This document explains **why** each step exists and **what** each gate checks.

It is distilled from translating two complete non-fiction books (one PDF, one EPUB) with parallel subagents, and from the reviews that followed.

## Principles

1. **Structured content is the single source of truth.**
   - Source and translation are stored per chapter, with a stable ID for every paragraph.
   - EPUB, PDF and HTML outputs are build artefacts.
2. **The core is separate from language rules.**
   - Code and this SOP contain no language-specific rules. Those live in three layers, and later layers override earlier ones:
     1. **Target-language pack** `bth/langs/<tag>.toml`: punctuation, quotes, title marks, number formats, naming standard, layout, navigation labels and check parameters. Shared by all books.
     2. **Pair profile** `bth/pairs/<src>__<tgt>.md`: structural transformations, typical mistranslations, naming conventions and expected length ratio for that pair.
     3. **Book spec** `style_guide.md`, `glossary.csv`, `examples.md`: decisions for this book only.
3. **The spec comes before translation.** Style guide, glossary, examples and online verification of names and titles are done **before** translating. Fixing names afterwards costs a full extra review-and-rebuild cycle.
4. **Detection is separate from correction.**
   - QA agents only report issues, with a segment ID, a severity and a rationale; a fixer applies minimal edits.
   - Anything a script can check is not left to an AI.
5. **Humans can correct anything, through three levers:**
   - the glossary (word choices);
   - the style guide and examples (voice);
   - direct segment edits (specific sentences).

   Every change is propagated only to the affected segments, and human edits are never overwritten. The pipeline never blocks waiting for a person, but it points reviewers to the passages that matter most. For languages where models are weaker, a fuller review is recommended (see quality tiers).
6. **Everything is traceable.** Git commits after each phase. Errata are located by segment ID and fixed, then the book is rebuilt and re-released.

## Project layout

```
<book>/
├── book.toml         # metadata, languages, options
├── source/           # original file (read-only)
├── original/         # extracted source: chNN.md (segment format)
├── translation/      # translations: chNN.md, same IDs
├── style_guide.md    # book background, chapter summaries, book decisions
├── glossary.csv      # terms, names, works, organisations
├── examples.md       # exemplary translations that set the voice
├── review/           # qa_rN.jsonl, fix_rN.jsonl, revise_rN.jsonl, backtranslation.jsonl, QA_REPORT.md
├── figures/          # optional: translated replacement images, same file names as in the EPUB
├── work/             # skeleton.epub + skeleton.json (build skeleton), figures.json + images/, tasks/, out/, entities.tsv
└── dist/             # <book>.<lang>.epub, bilingual.html
```

### Segment format

```
<!-- ch03-p0017 h2 -->
Can Machines Think?

<!-- ch03-p0018 p -->
Turing asked a simple question: {{1}}can machines think{{/1}}?{{2/}}
```

- **IDs** are assigned at extraction and never renumbered: chapter = spine document, then paragraph number. The same IDs are shared by every target language of the same source.
- **Types**: the block element (`h1` … `h6`, `p`, `li`, `blockquote`, `td`, `figcaption` …), or `fig` / `alt` for text inside an image (IDs `chNN-fNNNN`, see 1b).
- **Placeholders** carry all inline markup:
  - `{{n}}…{{/n}}` for elements with content (italics, links, note markers);
  - `{{n/}}` for empty elements (anchors, images, line breaks).
  - `{{i}}…{{/i}}` is the one placeholder a translator may add: italics the target needs but the source lacks (e.g. English titles for Chinese 《》). It is optional and only checked for nesting.
  - A translation must contain every placeholder exactly once. Pairs may move with their phrase but must not cross.
- **Translation headers** also carry `src=<hash of source>` and `mt=<hash of machine text>`, plus the worker name:
  - A changed source makes the translation **stale**, and it is re-planned.
  - Text that no longer matches `mt` was **edited by a human** and is never overwritten by machine output. So are segments marked `locked`.

## Phases and gates

| # | Phase | Who | Gate |
|---|---|---|---|
| 0 | `bth init` | user | language pack exists (otherwise draft one: appendix) |
| 1 | extract | script | coverage ≥ 98% of visible text |
| 1b | figures | N agents that can view images (`figures = true`) | one validated line per image; labels merged as `fig` segments |
| 2 | spec (+ entities) | 1 spec agent; 3 entity agents with web access | three spec files valid; user checkpoint on the spec (recommended) |
| 3 | translate | N agents | every segment merged and structurally valid |
| 4 | QA → fix (up to `qa_rounds`) | N QA agents, cross-assigned; fixers | no unresolved critical issues |
| 5 | human corrections | reviewer, at any time | — |
| 6 | build + verify | script | well-formed XML, manifest complete, links resolve; epubcheck when installed |
| 7 | release | user | git tag; errata loop |

`bth next` walks this table, running script phases itself and returning `dispatch` actions for agent phases.

### 1. Extract

Source preference: EPUB > HTML > TXT > text PDF > scanned PDF. Scanned PDFs need OCR first (e.g. `ocrmypdf -l <lang>`).

Every source is turned into an EPUB skeleton: EPUBs are used as they are, and other formats get a minimal generated EPUB. Extraction and build therefore have exactly one code path each.

- **EPUB:** leaf block elements become segments, and inline markup becomes placeholders. Navigation-only `<nav>` elements (toc, landmarks, page-list) are skipped. Other `<nav>` elements, such as an index wrapped in `<nav role="doc-index">`, are content.
- **PDF:** headings are detected from font size; running headers, footers and page numbers are dropped; paragraphs broken by page breaks are re-joined. Line joining follows the source pack:
  - space-separated scripts get a space, with de-hyphenation;
  - scripts without word spaces are joined directly.
- **Gate:** captured text must be at least 98% of visible text. Below that, `bth next` returns `attention`.

### 1b. Text inside images

Charts, diagrams, maps and tables are often pictures. Their labels are pixels, so extraction cannot see them and they would reach the reader untranslated.

- **Scan (script):** every image in the spine is listed in `work/figures.json`, anchored after the segment that precedes it, and copied to `work/images/` for viewing. Files under 2 KB (rules, ornaments) are skipped.
- **Transcribe (agents that can view images):** one JSON line per image, with its `kind` (chart, table, photo, cover …) and `items`, the labels a reader needs. Numbers, units and text already in the target language are left out.
- **Merge:** the labels go into `original/` as `fig` segments right after the anchor, and non-empty `alt` text as an `alt` segment. From there they are translated, checked against the glossary and reviewed like any other segment, and human edits lock them in the same way.
- **Build:** under each image with translated labels, the build adds a key such as `图中文字：Revenue＝收入；Costs＝成本`. The format comes from the language pack's `[figures]` section. Translated `alt` text replaces the original.
- **Human correction:** save a translated copy of an image under `figures/` with the same file name. The build swaps it in and drops the key. `QA_REPORT.md` lists every image with text.
- Turn the phase off with `figures = false` if your agents cannot view images.

### 2. Spec

The spec agent reads the language pack, the pair profile, the table of contents, the introduction and 2–3 representative chapters. It writes:
- **`style_guide.md`:** book background, **chapter summaries** (given to translators as context), and book decisions such as register, reader address, gender policy and abbreviations.
- **`glossary.csv`** with columns `source,target,target_forms,type,context,forbidden,locale,first_mention,status,evidence,note`:
  - one row per sense, with `context` filled when renderings differ (policy → 策略 in RL, 政策 in public affairs);
  - `forbidden` lists variants to avoid;
  - `locale` restricts a row to one regional variant;
  - only `approved` rows are enforced by `bth check`.
- **`examples.md`:** 5–10 exemplary passages with key points, plus optional negative examples.

Entity agents then verify names, works and organisations online:
1. **Wikidata labels** in the target language first (language-neutral);
2. the sources listed in the language pack;
3. official names.

They also check whether **the book already has a translation** in the target language, via WorldCat and national library catalogues; if it does, its title and key terms win. Approved rows are only overwritten by approved rows.

Checkpoint: the user confirms the title, core terms, register and the examples. This is the cheapest high-impact human touchpoint.

### 3. Translate

- **Units:** consecutive segments up to the token budget (`unit_tokens`, measured on source tokens), preferring breaks at chapter boundaries. Character counts are not comparable across languages.
- **Each prompt contains:**
  - pointers to the language pack, pair profile, style guide and examples;
  - the glossary rows that occur in the unit;
  - the previous two translated segments, for continuity;
  - the source segments.
- **Merging:** `bth done` validates the IDs and placeholders, then merges under a lock. Human-edited segments are never overwritten.

### 4. QA and fixes

**Script checks (`bth check`):**

| Check | Rule |
|---|---|
| structure | IDs aligned; placeholders identical and correctly nested |
| residue | untranslated source text: script-based when the scripts differ, language identification (`langdetect`) when they are the same |
| length | length-ratio outliers after calibrating on this book |
| numbers | numeric values compared after normalising separators and scale words (3,000,000 = 300万 = 3 million) |
| glossary | approved `target` (or `target_forms`) used; no `forbidden` variant |
| punctuation / quotes | punctuation and quote rules from the language pack |
| names | one rendering per source name, from the first-mention pattern |

**AI QA:**
- **Cross-assigned:** a QA worker never reviews units it translated.
- **Report-only:** it writes JSON Lines `{id, severity, category, src, tgt, suggestion, rationale, source_error}`.

| Severity | Meaning | Handling |
|---|---|---|
| critical | reversed or wrong meaning, wrong number, dropped sentence | must fix |
| major | skewed meaning, wrong term, clearly unnatural | must fix or justify |
| minor | wording, punctuation, mild translationese | fixed only if `fix_minor = true` |

**Fixing:** fixers apply minimal edits to critical and major issues, and the harness logs before/after. QA then re-runs on the changed segments, up to `qa_rounds`.

**Report:** `review/QA_REPORT.md` lists:
- counts and fix rates;
- high-risk segments;
- a stratified, reproducible spot-check sample;
- suspected errors in the original;
- name variants.

**Quality tiers** (`quality_tier` in the language pack):

| Tier | Human review | Sample | Extra |
|---|---|---|---|
| high | spot-check the sample | 4% | — |
| medium | recommended | 9% | back-translation of high-risk segments |
| low | strongly recommended | 15% | back-translation; consider a pivot language, with QA always against the original |

### 5. Human corrections

The reviewer works from `dist/bilingual.html` (source, translation, QA notes and back-translation, anchored by ID) and `review/QA_REPORT.md`.

| To change | Edit | Then |
|---|---|---|
| a word's rendering | `glossary.csv` | `bth impact <book> --since <rev>` (or `--terms`), then `bth next` |
| voice, register, address | `style_guide.md` / `examples.md` | `bth plan <book> translate --chapters chNN` on a sample chapter, compare, then widen the scope |
| one sentence | `translation/chNN.md` | nothing: the segment is locked automatically; `bth next` rebuilds |
| a language-wide rule | `bth/langs/<tag>.toml` | rebuild; affects every book in that language |

Lessons with general value belong in the glossary, the style guide, the pair profile or the language pack, so that later books and editions inherit them.

### 6. Build

1. Translations are injected into the skeleton.
2. Metadata (title, creator, `dc:language`), the `lang`/`xml:lang` attributes and navigation labels are localised from the book config and the language pack.
3. Right-to-left and vertical layouts are applied from `layout`.
4. The book is verified structurally, and with epubcheck when it is on PATH.
5. `dist/bilingual.html` is generated as well.

Untranslated segments keep their source text, and their count is reported. Image keys and replacement images are applied as described in 1b.

### 7. Release and errata

1. Tag releases.
2. For an erratum: locate the segment ID in `bilingual.html` → apply one of the three levers → `bth next` (re-check and rebuild) → new tag.
3. When the source changes (a new edition), re-extract into a new project, or keep the IDs and let the stale detection re-plan the changed segments.

## Appendix: adding a language

1. Copy `bth/langs/zh-Hans.toml` to `bth/langs/<tag>.toml` and fill in every key. Use the language's typographic authority (e.g. Imprimerie nationale for French, Duden for German, Kyodo style for Japanese).
2. Pay attention to:
   - quotes and spacing;
   - title marks;
   - decimal and group separators, and large-number units;
   - name order and transliteration;
   - direction and vertical writing;
   - fonts;
   - index collation;
   - navigation labels.
3. Draft `bth/pairs/<src>__<tgt>.md` with the pair's structural transformations and typical mistranslations.
4. Have a speaker of the language review both, and set `quality_tier`.
5. After the first book, feed the frequent QA categories back into the pair profile.

## Known limits (`shortcut:` in code)

- Index re-sorting by target-language collation is not implemented yet (`order = "keep_source"`).
- PDF extraction uses font-size heuristics. It does not handle footnotes or images.
- Text inside images is translated as a key under the image, not redrawn in the image; text in inline `<svg>` is not extracted.
- Token counts are estimated, not tokenised.
- Locking uses POSIX `fcntl`; there is no Windows support yet.
- Source-side glossary matching is a case-insensitive substring match; there is no stemming for highly inflected source languages.
