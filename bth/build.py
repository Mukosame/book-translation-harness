"""Build: inject translations into the EPUB skeleton, localise metadata/navigation, verify; bilingual HTML."""
import json
import re
import zipfile
from html import escape

from lxml import etree

from . import epub, figures
from .book import PH


def _opf_edit(book):
    tl, cfg = book.tgt_lang, book.cfg

    def edit(data):
        root = etree.fromstring(data)
        for tag, value in (("title", cfg.get("title_tgt")), ("creator", cfg.get("author_tgt")),
                           ("language", tl["tag"])):
            el = root.find(f".//{{{epub.DC}}}{tag}")
            if el is not None and value:
                el.text = value
        lay = tl.get("layout", {})
        spine = root.find(".//{*}spine")
        if spine is not None and (lay.get("page_progression") == "rtl"):
            spine.set("page-progression-direction", "rtl")
        return etree.tostring(root, xml_declaration=True, encoding="utf-8")
    return edit


def _ncx_edit(book):
    def edit(data):
        root = etree.fromstring(data)
        root.set("{http://www.w3.org/XML/1998/namespace}lang", book.tgt_lang["tag"])
        for tag, value in (("docTitle", book.cfg.get("title_tgt")), ("docAuthor", book.cfg.get("author_tgt"))):
            el = root.find(f"{{*}}{tag}/{{*}}text")
            if el is not None and value:
                el.text = value
        return etree.tostring(root, xml_declaration=True, encoding="utf-8")
    return edit


def _labels_edit(labels):
    """Replace whole text nodes equal to a known label (nav/NCX entries, headings) with its translation."""
    def edit(data):
        text = data.decode("utf-8")
        for src, local in labels.items():  # any whitespace run matches (目  录, 第一章\u3000…)
            pat = r"\s+".join(map(re.escape, escape(src, quote=False).split()))
            text = re.sub(rf">(\s*){pat}(\s*)<",
                          lambda m: f">{m.group(1)}{escape(local, quote=False)}{m.group(2)}<", text)
        return text.encode("utf-8")
    return edit


def _nav_labels(book, trans):
    """Language-pack labels plus short translated segments (headings, printed contents entries), placeholders
    stripped: navigation documents are outside the spine, so their entries are matched by source text."""
    first = lambda v: v[0] if isinstance(v, list) else v  # pack values may list aliases; the first is canonical
    tgt = {k: first(v) for k, v in book.tgt_lang.get("nav_labels", {}).items()}
    labels = dict(tgt)
    for key, src in book.src_lang.get("nav_labels", {}).items():  # source-language labels, e.g. 书名页 -> Title Page
        for s in (src if isinstance(src, list) else [src]):
            labels.setdefault(s, tgt.get(key, key))
    for sid, s in book.original().items():
        if s["type"] in figures.TYPES:
            continue  # image labels are short too, but they are not navigation entries
        plain = re.sub(r"\s+", " ", PH.sub("", s["text"])).strip()
        if sid in trans and len(plain) < 150 and not PH.search(PH.sub("", trans[sid]["text"])):
            labels.setdefault(plain, re.sub(r"\s+", " ", PH.sub("", trans[sid]["text"])).strip())
    return labels


def _doc_edit(book, segs, labels=None):
    tl = book.tgt_lang
    lay = tl.get("layout", {})
    fill = epub.fill_doc(segs)
    style = []
    if lay.get("direction") == "rtl":
        style.append("html { direction: rtl; }")
    if lay.get("writing_mode", "horizontal-tb") != "horizontal-tb":
        style.append(f"html {{ writing-mode: {lay['writing_mode']}; -epub-writing-mode: {lay['writing_mode']}; }}")

    def edit(tree):
        fill(tree)
        root = tree.getroot()
        root.set("lang", tl["tag"])
        root.set("{http://www.w3.org/XML/1998/namespace}lang", tl["tag"])
        if lay.get("direction") == "rtl":
            root.set("dir", "rtl")
        head = root.find("{*}head")
        title = head.find("{*}title") if head is not None else None
        if title is not None and title.text and labels:  # <head><title> is shown by some readers
            title.text = labels.get(" ".join(title.text.split()), title.text)
        if style and head is not None:
            etree.SubElement(head, f"{{{epub.XHTML}}}style").text = " ".join(style)
    return edit


def run(book, verify=True):
    mapping = json.loads((book.work / "skeleton.json").read_text("utf-8"))
    trans = book.translation()
    doc_edits, untranslated = {}, 0
    labels = _nav_labels(book, trans)
    for name, entries in mapping.items():
        segs = []
        for e in entries:
            if e["id"] in trans:
                segs.append((e["xpath"], trans[e["id"]]["text"], e["shells"]))
            else:
                untranslated += 1
        doc_edits[name] = _doc_edit(book, segs, labels)
    skel = book.work / "skeleton.epub"
    with zipfile.ZipFile(skel) as z:
        names = z.namelist()
        opf = epub.opf_path(z)
    for n in names:  # documents outside the spine (nav.xhtml …) still get the target language attributes
        if n.endswith((".xhtml", ".html")) and n not in doc_edits:
            doc_edits[n] = _doc_edit(book, [], labels)
    fig_docs, fig_other, fig_info = figures.build_edits(book, trans)
    for n, fn in fig_docs.items():  # after the translations are filled in, so segment xpaths still match
        if n in doc_edits:
            doc_edits[n] = (lambda f, g: lambda t: (f(t), g(t)))(doc_edits[n], fn)
    other = {n: _labels_edit(labels) for n in names if n.endswith((".ncx", ".opf")) or
             (n.endswith((".xhtml", ".html")) and n not in mapping)}
    for n, fn in [(opf, _opf_edit(book))] + [(n, _ncx_edit(book)) for n in names if n.endswith(".ncx")]:
        other[n] = (lambda f, g: lambda d: g(f(d)))(other[n], fn)  # labels first, then metadata
    book.path("dist").mkdir(exist_ok=True)
    tag = book.tgt_lang["tag"]
    name = book.root.name if book.root.name.endswith(f".{tag}") else f"{book.root.name}.{tag}"
    out = book.path("dist", f"{name}.epub")
    epub.rewrite(skel, out, doc_edits, {**other, **fig_other})
    problems, epubcheck = epub.verify(out) if verify else ([], False)
    bilingual(book)
    return {"output": str(out), "untranslated_segments": untranslated, "images": fig_info, "problems": problems,
            "epubcheck_ran": epubcheck}


def bilingual(book):
    """dist/bilingual.html: source | translation | QA issues | back-translation, anchored by segment id."""
    orig, trans = book.original(), book.translation()
    notes = {}
    for p in sorted(book.path("review").glob("qa_r*.jsonl")) if book.path("review").exists() else []:
        for line in p.read_text("utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                notes.setdefault(r["id"], []).append(f"[{r['severity']}/{r['category']}] {r.get('rationale', '')}")
    back = {}
    bt = book.path("review", "backtranslation.jsonl")
    if bt.exists():
        back = {r["id"]: r["text"] for r in map(json.loads, filter(str.strip, bt.read_text("utf-8").splitlines()))}
    rows = "".join(
        f'<tr id="{sid}"><td><a href="#{sid}">{sid}</a></td><td lang="{book.src_lang["tag"]}">{escape(s["text"])}'
        f'</td><td lang="{book.tgt_lang["tag"]}">{escape(trans.get(sid, {}).get("text", "—"))}</td>'
        f'<td>{"<br>".join(map(escape, notes.get(sid, [])))}</td><td>{escape(back.get(sid, ""))}</td></tr>'
        for sid, s in orig.items())
    page = (f'<!doctype html><meta charset="utf-8"><title>{escape(book.root.name)} bilingual</title><style>'
            'body{font-family:sans-serif}table{border-collapse:collapse;width:100%}td{border:1px solid #ccc;'
            'vertical-align:top;padding:4px}td:first-child{white-space:nowrap;font-size:small}</style><table>'
            '<tr><th>id</th><th>source</th><th>translation</th><th>QA</th><th>back-translation</th></tr>'
            f'{rows}</table>')
    book.path("dist").mkdir(exist_ok=True)
    book.path("dist", "bilingual.html").write_text(page, "utf-8")
