"""Errors in the original book (a wrong name, date, title or fact): one policy for the whole project.

book.toml `source_errors`:
  keep           translate as printed; QA still reports errors, for the record
  fix-obvious    fixers silently correct slips QA marks `obvious`; anything debatable stays as printed
  fix-with-note  fixers correct every error QA backs with evidence, and each correction is documented
book.toml `source_error_notes` (fix-with-note): `appendix` (a "translator's errata" page with links back to
each passage) or `inline` (a translator's note after the corrected passage).

Every prompt states the same rule, and only the fix phase applies corrections, so translators and fixers
cannot disagree. Documented corrections are collected into errata.csv (QA issues whose correction is in the
translation, and glossary rows whose note starts with "source error:"); people may edit the notes there or set
`status` to `omit`.
"""
import csv
import io
import posixpath
import re
import zipfile
from html import escape

from lxml import etree

from . import epub
from .book import PH, read_jsonl

POLICIES = ("keep", "fix-obvious", "fix-with-note")
COLUMNS = ["id", "original", "corrected", "note", "status"]
NAME = "bth-errata.xhtml"
RULES = {
    "keep": "translate the original as printed, even where it is wrong. Never correct it silently.",
    "fix-obvious": "translators translate as printed; fixers correct, silently, only slips nobody would dispute "
                   "(a misspelled name, a wrong year or title that a reliable source confirms). Anything debatable "
                   "stays as printed.",
    "fix-with-note": "translators translate as printed; fixers correct every error that a reliable source confirms, "
                     "and each correction is documented in a translator's note. Anything debatable stays as printed.",
}


def policy(book):
    p = book.opt.get("source_errors", "fix-with-note")
    if p not in POLICIES:
        raise SystemExit(f"book.toml: source_errors must be one of {POLICIES}, not {p!r}")
    return p


def rule(book):
    p = policy(book)
    return f"**Errors in the original** (wrong name, date, title or fact; `source_errors = {p}`): {RULES[p]}"


def selected(issues, pol):
    """Source-error issues the fixers must apply under the policy."""
    errs = [i for i in issues if i.get("source_error") and i.get("suggestion")]
    return [] if pol == "keep" else [i for i in errs if i.get("obvious")] if pol == "fix-obvious" else errs


def _plain(text):
    return re.sub(r"\s+", " ", PH.sub("", text)).strip()


def _issues(book):
    out = []
    for p in sorted(book.path("review").glob("qa_r*.jsonl")) if book.path("review").exists() else []:
        out += [r for r in read_jsonl(p) if r.get("source_error")]
    return out


def collect(book):
    """Refresh errata.csv from QA issues and glossary rows (fix-with-note) and return the rows to print."""
    if policy(book) != "fix-with-note":
        return []
    from .check import glossary
    orig, trans = book.original(), {k: _plain(v["text"]) for k, v in book.translation().items()}
    found = [{"id": i["id"], "original": i.get("src", ""), "corrected": i["suggestion"], "note": i.get("note", "")}
             for i in selected(_issues(book), "fix-with-note") if _plain(i["suggestion"]) in trans.get(i["id"], "")]
    for r in glossary(book, approved_only=False):
        if not r.get("note", "").lower().startswith("source error:"):
            continue
        sid = next((s for s, v in orig.items() if r["source"] in v["text"] and r["target"] in trans.get(s, "")), None)
        if sid:
            found.append({"id": sid, "original": r["source"], "corrected": r["target"],
                          "note": r["note"].split(":", 1)[1].strip()})
    p = book.path("errata.csv")
    cur = list(csv.DictReader(io.StringIO(p.read_text("utf-8")))) if p.exists() else []
    keys = {(r["id"], r["original"]) for r in cur}
    cur += [{**r, "status": "applied"} for r in found if (r["id"], r["original"]) not in keys]  # human edits kept
    if cur:
        with p.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, COLUMNS, extrasaction="ignore")
            w.writeheader()
            w.writerows(cur)
    return [r for r in cur if r.get("status") != "omit" and r["id"] in orig]


def build_edits(book, trans, mapping, skeleton, opf):
    """-> {"docs": {doc: edit(tree)}, "add": {name: bytes}, "opf": edit(bytes) or None}"""
    rows = collect(book)
    res = {"docs": {}, "add": {}, "opf": None}
    if not rows:
        return res
    tl = book.tgt_lang
    fmt = {"title": "Translator's errata", "intro": "", "inline": " [Translator's note: {note}]",
           **tl.get("errata", {})}
    where = {e["id"]: (doc, e["xpath"]) for doc, entries in mapping.items() for e in entries}
    rows = [r for r in rows if r["id"] in where]
    inline = book.opt.get("source_error_notes", "appendix") == "inline"
    per_doc = {}
    for r in rows:
        per_doc.setdefault(where[r["id"]][0], []).append(r)

    def edit_for(items):
        def edit(tree):
            for r in items:
                found = tree.xpath(where[r["id"]][1])
                if not found:
                    continue
                el = found[0]
                if inline:
                    span = etree.SubElement(el, f"{{{epub.XHTML}}}span", {"class": "bth-translator-note"})
                    span.text = fmt["inline"].format(note=r["note"] or r["corrected"])
                else:  # an anchor for the link from the errata page
                    a = etree.Element(f"{{{epub.XHTML}}}a", {"id": f"bth-{r['id']}"})
                    a.tail, el.text = el.text, None
                    el.insert(0, a)
        return edit
    res["docs"] = {d: edit_for(items) for d, items in per_doc.items()}
    if inline:
        return res
    orig = book.original()
    heading = {}
    for sid, s in orig.items():
        if s["type"] in ("h1", "h2") and sid in trans:
            heading.setdefault(s["chapter"], _plain(trans[sid]["text"]))
    name = posixpath.join(posixpath.dirname(opf), NAME)
    items = "".join(
        f'<li><a href="{escape(posixpath.relpath(where[r["id"]][0], posixpath.dirname(name)))}#bth-{r["id"]}">'
        f'{escape(heading.get(orig[r["id"]]["chapter"], r["id"]))}</a>: {escape(r["note"] or r["corrected"])}</li>'
        for r in rows)
    tag, intro = tl["tag"], f"<p>{escape(fmt['intro'])}</p>" if fmt["intro"] else ""
    res["add"][name] = (f'<?xml version="1.0" encoding="utf-8"?><html xmlns="{epub.XHTML}" xml:lang="{tag}" '
                        f'lang="{tag}"><head><title>{escape(fmt["title"])}</title></head><body><h1>'
                        f'{escape(fmt["title"])}</h1>{intro}<ol>{items}</ol></body></html>').encode("utf-8")
    with zipfile.ZipFile(skeleton) as z:
        nav_doc = next((posixpath.normpath(posixpath.join(posixpath.dirname(opf), i.get("href")))
                        for i in etree.fromstring(z.read(opf)).iter("{*}item")
                        if "nav" in (i.get("properties") or "").split()), None)
    if nav_doc:
        def nav_edit(tree):
            ol = next((n.find("{*}ol") for n in tree.iter("{*}nav")
                       if "toc" in (n.get(f"{{{epub.EPUB_NS}}}type") or "").split()), None)
            if ol is not None:
                li = etree.SubElement(ol, f"{{{epub.XHTML}}}li")
                etree.SubElement(li, f"{{{epub.XHTML}}}a", {
                    "href": posixpath.relpath(name, posixpath.dirname(nav_doc))}).text = fmt["title"]
        prev = res["docs"].get(nav_doc)
        res["docs"][nav_doc] = (lambda t: (prev(t), nav_edit(t))) if prev else nav_edit

    def opf_edit(data):
        root = etree.fromstring(data)
        etree.SubElement(root.find("{*}manifest"), f"{{{epub.OPF}}}item",
                         {"id": "bth-errata", "href": NAME, "media-type": "application/xhtml+xml"})
        etree.SubElement(root.find("{*}spine"), f"{{{epub.OPF}}}itemref", {"idref": "bth-errata"})
        return etree.tostring(root, xml_declaration=True, encoding="utf-8")
    res["opf"] = opf_edit  # shortcut: EPUB 2 NCX navigation does not list the errata page
    return res


def report_lines(book):
    issues = _issues(book)
    if not issues:
        return ["none reported"]
    pol, trans = policy(book), {k: _plain(v["text"]) for k, v in book.translation().items()}
    chosen = {id(i) for i in selected(issues, pol)}
    lines = [f"Policy: `source_errors = {pol}`."]
    for i in issues:
        applied = i.get("suggestion") and _plain(i["suggestion"]) in trans.get(i["id"], "")
        state = "corrected" if applied else "NOT corrected (policy asks for it)" if id(i) in chosen else "kept as printed"
        lines.append(f"- `{i['id']}` ({state}): {i.get('src', '')} → {i.get('suggestion', '')}. {i.get('rationale', '')}")
    return lines
