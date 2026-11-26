# Pair profile: English → Simplified Chinese (en → zh-Hans)

Pair-specific guidance only. General target rules live in `langs/zh-Hans.toml`; book decisions live in the book's `style_guide.md`.
Derived from two full book translations (popular science and economics), including their review logs.

## Expected metrics
- Length ratio (Chinese characters / English characters): about 0.45–0.70. `bth check` recalibrates per book.

## Structural transformations
- **Long sentences:** split them by sense group. Turn relative clauses and participle phrases into short clauses or short pre-modifiers; avoid chains like "……的……的……".
- **Passives:** prefer active voice, or 受到 / 遭到 / 由…; avoid stacked 被.
- **Nominalisations:** turn them into verbs, e.g. "the implementation of X" becomes 实施X.
- **Pronouns:** English uses far more of them. Repeat the noun or omit the pronoun.
- **Connectives:** however / therefore need not always be translated; follow the Chinese flow.

## Common mistranslations (QA checks these first)
- **Transferred negation:** "I don't think X" means 我认为不是X, not a literal 我不认为X.
- **Partial negation:** "not all / not every" is 并非所有, never 所有……都不.
- **Comparatives and multiples:** "three times more than" is ambiguous; "less than" is 不到.
- **Modality:** distinguish the degree of may / might / could, and whether "should" means advice or inference.
- **Time:** Chinese has no tense, so add 曾 / 已经 / 将 / 正在 where the time relation would otherwise be lost.
- **Emphasis:** italic emphasis must survive. "a control system *is* a model" becomes 就是, not a weakened 包含.
- **British understatement:** quite / rather / not bad are often praise or irony.
- **Idioms and jokes:** use a Chinese equivalent, or paraphrase while keeping the humour. Add no translator's notes unless comprehension needs one.

## Names and titles
- **Famous people:** use the established rendering (凯恩斯, 哈耶克, 图灵).
- **Other people:** use Xinhua transliteration, with the original in parentheses on first mention per chapter, e.g. 艾伦·图灵（Alan Turing）.
- **Coined concepts:** add the English in parentheses where the book defines them, e.g. 过滤气泡（filter bubble）.
- **Books:** use the title of the published Chinese edition when there is one; otherwise translate the title, in 《》. Albums and artworks without an established Chinese title keep the original inside 《》.
- **Organisations:** use the official mainland name. Where mainland and Taiwan/HK names differ, use the mainland one (Costco 开市客, not 好市多).
- **Abbreviations:** common ones (AI, GDP, CEO) may stay, but be consistent within a book.

## Keep in the original
- Bibliographic data in notes and further reading.
- Index locators. Translate the index entries themselves and keep the source order.

## Punctuation conversion
- British ‘ ’ quotes become “ ”; nested quotes use ‘ ’.
- Dashes – / — become ——; "..." becomes ……
- Parenthetical originals go in full-width parentheses: 艾伦·图灵（Alan Turing）.
