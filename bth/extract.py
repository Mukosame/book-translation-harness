"""Source file -> original/<chapter>.md segments + work/skeleton.json (EPUB skeleton used by build).

Every source type is first turned into an EPUB (non-EPUB sources get a minimal generated one), so there
is exactly one extraction path and one build path.
"""
import collections
import json
import re
import shutil
from html import escape

from . import epub
from .book import dump_segments


def _paragraphs_to_body(chapters):
    """[(title, [(type, text)])] -> [(title, xhtml body)]"""
    return [(t, "".join(f"<{k}>{escape(x)}</{k}>" for k, x in paras)) for t, paras in chapters]


def _join_lines(lines, lang):
    sep = "" if lang.get("segmentation", {}).get("word_boundaries") == "none" else " "
    out = ""
    for ln in (x.strip() for x in lines):
        if not ln:
            continue
        if out.endswith("-") and ln[:1].islower():  # de-hyphenate "conti-\nnued"
            out = out[:-1] + ln
        else:
            out = f"{out}{sep}{ln}" if out else ln
    return out


def from_txt(path, lang):
    pat = re.compile(lang.get("extract", {}).get("chapter_pattern", r"^(chapter|part)\b.*$"), re.I)
    chapters, title, paras = [], "Start", []
    for block in re.split(r"\n\s*\n", path.read_text("utf-8")):
        text = _join_lines(block.splitlines(), lang)
        if not text:
            continue
        if pat.match(text) and len(text) < 120:
            if paras:
                chapters.append((title, paras))
            title, paras = text, [("h1", text)]
        else:
            paras.append(("p", text))
    chapters.append((title, paras))
    return chapters


def from_pdf(path, lang):
    try:
        import pymupdf
    except ImportError:
        raise SystemExit("PDF sources need PyMuPDF: pip install pymupdf")
    doc = pymupdf.open(path)
    blocks, sizes, seen = [], collections.Counter(), collections.Counter()
    textless = sum(not page.get_text().strip() for page in doc)
    if textless > len(doc) / 2:
        raise SystemExit(f"{textless}/{len(doc)} pages have no text layer: OCR first, e.g. `ocrmypdf -l <lang> in out`")
    for page in doc:
        for b in page.get_text("dict")["blocks"]:
            spans = [s for ln in b.get("lines", []) for s in ln["spans"] if s["text"].strip()]
            if not spans:
                continue
            text = _join_lines(["".join(s["text"] for s in ln["spans"]) for ln in b["lines"]], lang)
            size = max(s["size"] for s in spans)
            for s in spans:
                sizes[round(s["size"])] += len(s["text"])
            seen[text] += 1
            blocks.append((text, size))
    body = sizes.most_common(1)[0][0] if sizes else 10
    ends = tuple(lang.get("punctuation", {}).get("sentence_end", [".", "?", "!"]))
    repeated = {t for t, n in seen.items() if n > max(3, len(doc) * 0.3)}  # running headers/footers
    chapters, title, paras = [], "Start", []
    # shortcut: font-size heuristics for headings, no footnote/image handling; refine per book if needed
    for text, size in blocks:
        if text in repeated or re.fullmatch(r"[\divxlcIVXLC\s]+", text):
            continue
        if size >= body * 1.3 and len(text) < 120:
            if paras and paras[-1] == ("h1", title):  # title set on two lines
                title = f"{title} {text}"
                paras[-1] = ("h1", title)
                continue
            carry = [paras.pop()] if paras and paras[-1][0] == "h2" else []  # "CHAPTER 3" label above title
            if paras:
                chapters.append((title, paras))
            title, paras = text, carry + [("h1", text)]
        elif size >= body * 1.12 and len(text) < 160:
            paras.append(("h2", text))
        elif paras and paras[-1][0] == "p" and not paras[-1][1].endswith(ends) and text[:1].islower():
            paras[-1] = ("p", _join_lines([paras[-1][1], text], lang))  # paragraph split by a page break
        else:
            paras.append(("p", text))
    chapters.append((title, paras))
    return chapters


def from_html(path):
    from lxml import html as lhtml
    from lxml import etree
    tree = lhtml.parse(str(path))
    body = tree.find(".//body")
    title = (tree.findtext(".//title") or path.stem).strip()
    inner = "".join(etree.tostring(c, method="xml", encoding="unicode") for c in body)
    return [(title, (body.text or "") + inner)]


def entity_candidates(book, limit=600):
    """Frequent capitalised word sequences in the source -> work/entities.tsv (input for entity agents)."""
    counts, lower = collections.Counter(), collections.Counter()
    for s in book.original().values():
        text = re.sub(r"\{\{/?\d+/?\}\}", " ", s["text"])
        lower.update(re.findall(r"\b[a-z][\w'’\-]+", text))
        # shortcut: capitalisation heuristic only works for Latin/Cyrillic/Greek sources; CJK sources rely on
        # the agents reading the text
        for m in re.finditer(r"(?<![.!?]\s)(?<!^)\b([A-Z][\w'’\-]+(?:\s+(?:of|the|and|de|von|van|&)?\s*[A-Z][\w'’\-]+)*)",
                             text):
            counts[m.group(1)] += 1
    # single words that mostly occur in lower case are sentence-initial ordinary words ("The", "System")
    rows = [f"{k}\t{n}" for k, n in counts.most_common(limit)
            if (n > 1 or " " in k) and (" " in k or lower[k.lower()] < n)]
    (book.work / "entities.tsv").write_text("candidate\tcount\n" + "\n".join(rows), "utf-8")
    return len(rows)


def run(book):
    src = book.path(book.cfg["source"])
    kind = src.suffix.lower().lstrip(".")
    book.work.mkdir(exist_ok=True)
    skel = book.work / "skeleton.epub"
    if kind == "epub":
        shutil.copy(src, skel)
    else:
        lang = book.src_lang
        if kind == "txt":
            chapters = _paragraphs_to_body(from_txt(src, lang))
        elif kind == "pdf":
            chapters = _paragraphs_to_body(from_pdf(src, lang))
        elif kind in ("html", "htm", "xhtml"):
            chapters = from_html(src)
        else:
            raise SystemExit(f"unsupported source type: {kind}")
        epub.make_epub(skel, book.cfg.get("title_src", src.stem), book.cfg["lang"]["from"], chapters,
                       book.tgt_lang.get("layout", {}).get("css_extra", ""))
    docs, coverage = epub.extract(skel)
    out = book.path("original")
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} already has content; extraction never renumbers IDs. Remove it to re-extract.")
    out.mkdir(exist_ok=True)
    mapping, n_seg = {}, 0
    for i, (name, segs) in enumerate(docs, 1):
        if not segs:
            continue
        ch = f"ch{i:02d}"
        entries = {}
        mapping[name] = []
        for j, (kind_, text, xpath, shells) in enumerate(segs, 1):
            sid = f"{ch}-p{j:04d}"
            entries[sid] = {"type": kind_, "text": text}
            mapping[name].append({"id": sid, "xpath": xpath, "shells": shells})
        (out / f"{ch}.md").write_text(dump_segments(entries), "utf-8")
        n_seg += len(segs)
    (book.work / "skeleton.json").write_text(json.dumps(mapping, ensure_ascii=False), "utf-8")
    return {"chapters": len(mapping), "segments": n_seg, "coverage": round(coverage, 4)}
