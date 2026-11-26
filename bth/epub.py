"""EPUB in/out: segment extraction from XHTML, re-injection of translations, packaging, verification."""
import copy
import html.entities
import posixpath
import re
import shutil
import subprocess
import zipfile

from lxml import etree

from .book import PH

XHTML = "http://www.w3.org/1999/xhtml"
OPF = "http://www.idpf.org/2007/opf"
DC = "http://purl.org/dc/elements/1.1/"
EPUB_NS = "http://www.idpf.org/2007/ops"
BLOCK = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "dt", "dd", "blockquote", "figcaption", "caption",
         "td", "th", "div", "section", "article", "aside", "header", "footer", "nav", "figure", "table",
         "tr", "ul", "ol", "dl", "body", "pre", "hr", "main"}
SKIP = {"pre", "code", "script", "style", "math", "svg", "head"}
SKIP_NAV = {"toc", "landmarks", "page-list", "doc-toc", "doc-pagelist"}  # real navigation, not content


def local(el):
    return etree.QName(el).localname if isinstance(el.tag, str) else ""


def xml_safe(raw):
    """Replace HTML named entities (&nbsp; …) that plain XML parsers reject with numeric references."""
    keep = {"amp", "lt", "gt", "quot", "apos"}
    return re.sub(rb"&([A-Za-z][A-Za-z0-9]*);", lambda m: m.group(0) if m.group(1).decode() in keep or
                  m.group(1).decode() not in html.entities.name2codepoint else
                  f"&#{html.entities.name2codepoint[m.group(1).decode()]};".encode(), raw)


def parse(raw):
    try:
        return etree.fromstring(xml_safe(raw), etree.XMLParser(resolve_entities=False)).getroottree()
    except etree.XMLSyntaxError:
        return etree.fromstring(xml_safe(raw), etree.XMLParser(recover=True)).getroottree()


def opf_path(z):
    c = etree.fromstring(z.read("META-INF/container.xml"))
    return c.find(".//{*}rootfile").get("full-path")


def spine_docs(z):
    """[(zip name, href relative to opf)] in reading order."""
    op = opf_path(z)
    opf = etree.fromstring(z.read(op))
    items = {i.get("id"): i.get("href") for i in opf.iter("{*}item")}
    base = posixpath.dirname(op)
    return [posixpath.normpath(posixpath.join(base, items[r.get("idref")]))
            for r in opf.iter("{*}itemref") if r.get("idref") in items]


def _skipped(el):
    for a in el.iterancestors():
        if local(a) in SKIP:
            return True
        if local(a) == "nav":
            kinds = set((a.get(f"{{{EPUB_NS}}}type") or "").split()) | {a.get("role") or ""}
            if kinds & SKIP_NAV:
                return True
    return local(el) in SKIP


def _leaf_blocks(tree):
    for el in tree.iter():
        if local(el) in BLOCK and local(el) not in ("body", "hr", "pre") and not _skipped(el) \
                and "".join(el.itertext()).strip() \
                and not any(local(d) in BLOCK for d in el.iterdescendants()):
            yield el


def _shell(el):
    s = copy.copy(el)
    for c in list(s):
        s.remove(c)
    s.text = s.tail = None
    return etree.tostring(s, encoding="unicode")


def _to_text(el, shells):
    """Inner content of a leaf block -> text with {{n}}…{{/n}} / {{n/}} placeholders for inline tags."""
    out = [el.text or ""]
    for c in el:
        if not isinstance(c.tag, str):  # comments / processing instructions
            out.append(c.tail or "")
            continue
        n = str(len(shells) + 1)
        shells[n] = _shell(c)
        inner = _to_text(c, shells)
        out.append(f"{{{{{n}}}}}{inner}{{{{/{n}}}}}" if inner or len(c) else f"{{{{{n}/}}}}")
        out.append(c.tail or "")
    return re.sub(r"\s+", " ", "".join(out))


def extract(epub_path):
    """-> (docs: [(zip name, [(type, text, xpath, shells)])], coverage ratio of captured visible text)."""
    docs, total, got = [], 0, 0
    with zipfile.ZipFile(epub_path) as z:
        for name in spine_docs(z):
            tree = parse(z.read(name))
            body = tree.find(".//{*}body")
            total += len(re.sub(r"\s+", "", "".join(body.itertext()))) if body is not None else 0
            segs = []
            for el in _leaf_blocks(tree):
                shells = {}
                text = _to_text(el, shells).strip()
                if "{{" in "".join(el.itertext()):
                    raise SystemExit(f"{name}: source text contains '{{{{', which collides with placeholders")
                if text:
                    got += len(re.sub(r"\s+", "", "".join(el.itertext())))
                    segs.append((local(el), text, tree.getpath(el), shells))
            docs.append((name, segs))
    return docs, got / max(total, 1)


def _fill(el, text, shells):
    for c in list(el):
        el.remove(c)
    el.text, stack, last = None, [el], None

    def add_text(t):
        if last is None:
            stack[-1].text = (stack[-1].text or "") + t
        else:
            last.tail = (last.tail or "") + t
    pos = 0
    for m in PH.finditer(text):
        add_text(text[pos:m.start()])
        pos = m.end()
        close, n, empty = m.groups()
        if close:
            last = stack.pop()
            continue
        child = etree.fromstring(shells[n])
        stack[-1].append(child)
        if empty:
            last = child
        else:
            stack.append(child)
            last = None
    add_text(text[pos:])


def rewrite(src, dst, doc_edits, other_edits=None):
    """Copy an EPUB, replacing spine docs via doc_edits[name](tree) and any file via other_edits[name](bytes)."""
    other_edits = other_edits or {}
    tmp = str(dst) + ".tmp"
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(tmp, "w") as zout:
        names = zin.namelist()
        order = ["mimetype"] + [n for n in names if n != "mimetype"] if "mimetype" in names else names
        for name in order:
            data = zin.read(name)
            if name in doc_edits:
                tree = parse(data)
                doc_edits[name](tree)
                data = etree.tostring(tree, xml_declaration=True, encoding="utf-8")
            if name in other_edits:
                data = other_edits[name](data)
            zout.writestr(zin.getinfo(name), data,
                          compress_type=zipfile.ZIP_STORED if name == "mimetype" else zipfile.ZIP_DEFLATED)
    shutil.move(tmp, dst)


def fill_doc(segs):
    """doc edit that injects [(xpath, text, shells)] into a parsed tree."""
    def edit(tree):
        for path, text, shells in segs:
            found = tree.xpath(path)
            if found:
                _fill(found[0], text, shells)
    return edit


def make_epub(path, title, lang, chapters, css=""):
    """Minimal EPUB3 from [(title, xhtml body inner markup)]; used to give non-EPUB sources a skeleton."""
    files = {"META-INF/container.xml": '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:'
             'tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type='
             '"application/oebps-package+xml"/></rootfiles></container>', "OEBPS/style.css": css}
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;")  # noqa: E731
    nav = []
    for i, (t, body) in enumerate(chapters, 1):
        files[f"OEBPS/ch{i:03d}.xhtml"] = (f'<?xml version="1.0" encoding="utf-8"?><html xmlns="{XHTML}" '
                                           f'xml:lang="{lang}" lang="{lang}"><head><title>{esc(t)}</title><link '
                                           f'rel="stylesheet" href="style.css"/></head><body>{body}</body></html>')
        nav.append(f'<li><a href="ch{i:03d}.xhtml">{esc(t)}</a></li>')
    files["OEBPS/nav.xhtml"] = (f'<?xml version="1.0" encoding="utf-8"?><html xmlns="{XHTML}" xmlns:epub='
                                f'"{EPUB_NS}"><head><title>{esc(title)}</title></head><body><nav epub:type="toc">'
                                f'<ol>{"".join(nav)}</ol></nav></body></html>')
    items = "".join(f'<item id="c{i}" href="ch{i:03d}.xhtml" media-type="application/xhtml+xml"/>'
                    for i in range(1, len(chapters) + 1))
    spine = "".join(f'<itemref idref="c{i}"/>' for i in range(1, len(chapters) + 1))
    files["OEBPS/content.opf"] = (
        f'<?xml version="1.0" encoding="utf-8"?><package xmlns="{OPF}" version="3.0" unique-identifier="id">'
        f'<metadata xmlns:dc="{DC}"><dc:identifier id="id">bth-{abs(hash(title))}</dc:identifier>'
        f'<dc:title>{esc(title)}</dc:title><dc:language>{lang}</dc:language>'
        f'<meta property="dcterms:modified">2000-01-01T00:00:00Z</meta></metadata><manifest>'
        f'<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        f'<item id="css" href="style.css" media-type="text/css"/>{items}</manifest><spine>{spine}</spine></package>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        for name, data in files.items():
            z.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)


def verify(path):
    """Structural checks: XML well-formed, manifest files present, internal links resolve. Runs epubcheck if found."""
    problems = []
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        if z.namelist()[0] != "mimetype":
            problems.append("mimetype is not the first entry")
        op = opf_path(z)
        base = posixpath.dirname(op)
        ids = {}
        for n in names:
            if n.endswith((".xhtml", ".html", ".opf", ".ncx", ".xml")):
                try:
                    t = etree.fromstring(z.read(n))
                    ids[n] = {e.get("id") for e in t.iter() if isinstance(e.tag, str) and e.get("id")}
                except etree.XMLSyntaxError as e:
                    problems.append(f"{n}: not well-formed XML ({e})")
        for item in etree.fromstring(z.read(op)).iter("{*}item"):
            target = posixpath.normpath(posixpath.join(base, item.get("href")))
            if target not in names:
                problems.append(f"manifest item missing: {target}")
        for n in [n for n in ids if n.endswith((".xhtml", ".html"))]:
            for a in etree.fromstring(z.read(n)).iter("{*}a"):
                href = a.get("href") or ""
                if not href or re.match(r"^[a-z]+:", href):
                    continue
                file, _, frag = href.partition("#")
                target = posixpath.normpath(posixpath.join(posixpath.dirname(n), file)) if file else n
                if target not in names:
                    problems.append(f"{n}: broken link {href}")
                elif frag and target in ids and frag not in ids[target]:
                    problems.append(f"{n}: missing anchor {href}")
    checker = shutil.which("epubcheck")
    if checker:
        r = subprocess.run([checker, str(path)], capture_output=True, text=True)
        if r.returncode:
            problems.append("epubcheck:\n" + (r.stdout + r.stderr)[-3000:])
    return problems, bool(checker)

