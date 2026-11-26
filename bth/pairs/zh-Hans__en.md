# Pair profile: Simplified Chinese → English (zh-Hans → en)

Pair-specific guidance only. General target rules live in `langs/en.toml`; book decisions live in the book's `style_guide.md`.
First drafted for a mid-20th-century Chinese social-science monograph; extend it after each book with the frequent QA categories.

## Expected metrics
- Length ratio (English characters / Chinese characters): about 2.5–3.8. `bth check` recalibrates per book.

## Structural transformations
- **Topic–comment and run-on sentences:** Chinese strings clauses with commas (流水句). Re-segment into English sentences by logic, and supply the subordination the Chinese leaves implicit (because, although, so that, which).
- **Dropped subjects and objects:** Chinese omits them freely. Restore them in English from context; never leave a dangling verb or guess a subject the context does not support.
- **Number and articles:** Chinese marks neither. Decide singular/plural and a/the/zero article from context; generic statements usually take bare plurals ("families", "children") or "the family" as an institution.
- **Tense and aspect:** inferred from 了/过/着/已/曾/将 and context. Keep a consistent narrative tense; general claims in present tense.
- **Four-character idioms (成语) and parallelism:** render the sense, not the image, unless the image carries the argument. Don't over-translate decorative couplets into two redundant English clauses.
- **Repetition:** Chinese repeats nouns where English would use pronouns or synonyms; English may vary or pronominalise, but keep defined technical terms fixed.
- **Rhetorical questions and 呢/吗/罢 particles:** convert to the English register equivalent (a real question, a statement, or "surely…").

## Common mistranslations (QA checks these first)
- **Scope of 不/没 and 都:** 都不 = "none"; 不都 = "not all".
- **的 attribution chains:** identify the head noun correctly in long 的…的… phrases.
- **Ambiguous 他:** pre-1950s texts often use 他 for people and things (他们 for objects) and 伊/她 inconsistently; resolve by meaning.
- **False friends:** 社会 (society vs. social), 文化 (culture, sometimes "civilisation"), 经济 (economy vs. economical), 问题 (problem vs. question vs. issue), 意义 (meaning vs. significance), 关系 (relationship vs. relations vs. connection).
- **Hedging and emphasis:** 似乎/大概/恐怕 are softer than "seems"; 固然…但 is concessive ("granted…, but"); 正是/就是 is emphatic.
- **Quotations from classics:** translate the sense, use an established translation (Legge, Lau, Waley, etc.) when one fits, and keep the source reference.

## Names and titles
- **Chinese people:** Hanyu Pinyin, surname first, no hyphen or apostrophe errors (Fei Xiaotong, Pan Guangdan). Use the established Western form for people known by it (Confucius, Mencius, Sun Yat-sen, Chiang Kai-shek), and for authors who published under a romanised name.
- **Western authors cited in Chinese transliteration:** identify the original person and restore the original spelling (马林诺斯基 → Malinowski, 涂尔干 → Durkheim, 拉德克利夫-布朗 → Radcliffe-Brown). Never back-transliterate from the Chinese characters.
- **Works:** use the original title if the work was written in a Western language; for Chinese works give an English rendering in italics, with pinyin on first mention where the book relies on the title (e.g. *Book of Rites* (*Liji*)).
- **Places:** Pinyin for mainland places, established forms for historical/foreign ones; ethnic group names use current English ethnonyms (Yao, Miao, Lolo/Yi as the book's period requires, noted in the style guide).
- **Kinship terms:** keep the distinctions the argument relies on (父系 patrilineal, 母系 matrilineal, 舅舅 mother's brother); add pinyin in parentheses where the book discusses the Chinese term itself.

## Keep in the original
- Bibliographic data in notes (author names, titles in the original language); translate only connective text.
- Pinyin with characters for Chinese terms that the author analyses as words, e.g. *xiao* (孝) only where the term is the topic.

## Punctuation conversion
- Full-width marks become half-width English punctuation with spacing: ，→ , 。→ . ；→ ; ：→ :
- 《》 and 〈〉 become italics (keep or add the placeholder from the source; never type 《》 in English).
- “” stay as curly English double quotes; 「」 and 『』 become “ ” and ‘ ’.
- —— becomes an em dash (—); …… becomes an ellipsis (…); 、 becomes a comma or "and".
- Chinese inline parentheses （） become (), with a space before.
