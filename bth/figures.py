"""Text inside images (charts, diagrams, tables saved as pictures).

Image pixels never reach the text pipeline, so labels inside a chart would stay in the source language.
The `figures` phase has an agent that can view images transcribe each image's text; the harness inserts
those strings into original/ as ordinary segments (type `fig`, plus `alt` for alt text), so translation,
glossary checks, QA and human edits apply to them unchanged. The build then adds a compact key under each
image ("source label = translation"), unless a translated replacement image was dropped into `figures/`.

work/figures.json: {image zip path: {file, uses: [{doc, xpath, alt}], chapter, after, context,
                                     kind, segments, alt_segment, done}}
"""
import json
import posixpath
import re
import zipfile
from pathlib import Path

from lxml import etree

from . import epub
from .book import PH, dump_segments, parse_segments

TYPES = ("fig", "alt")
KINDS = {"chart", "diagram", "table", "map", "photo", "illustration", "cover", "decorative", "text"}
PER_TASK = 8
MIN_BYTES = 2048  # shortcut: smaller files are taken to be rules/ornaments; lower it if tiny label images exist
FLOW = {"body", "div", "section", "article", "aside", "main", "header", "footer", "figure", "blockquote", "li",
        "td", "th", "dd", "nav"}  # containers that may hold a <p>; elsewhere the key is a block-styled <span>
XLINK = "{http://www.w3.org/1999/xlink}href"


def _path(book):
    return book.work / "figures.json"


def load(book):
    p = _path(book)
    return json.loads(p.read_text("utf-8")) if p.exists() else {}


def _save(book, data):
    _path(book).write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")


def _plain(text):
    return re.sub(r"\s+", " ", PH.sub("", text)).strip()


def scan(book):
    """Find images in spine documents and anchor each after the segment preceding it (once per project)."""
    if _path(book).exists():
        return load(book)
    mapping = json.loads((book.work / "skeleton.json").read_text("utf-8"))
    orig = book.original()
    images = book.work / "images"
    data, prev = {}, None  # prev: (chapter, last segment id) of the closest earlier document with segments
    with zipfile.ZipFile(book.work / "skeleton.epub") as z:
        names = set(z.namelist())
        docs = epub.spine_docs(z)
        first_ch = next((orig[m[0]["id"]]["chapter"] for d in docs if (m := mapping.get(d))), None)
        for doc in docs:
            tree = epub.parse(z.read(doc))
            seg_at = {}
            for e in mapping.get(doc, []):
                found = tree.xpath(e["xpath"])
                if found:
                    seg_at[found[0]] = e["id"]
            last = prev[1] if prev else None
            for el in tree.iter():
                if el in seg_at:
                    last = seg_at[el]
                if epub.local(el) not in ("img", "image") or any(epub.local(a) == "head" for a in el.iterancestors()):
                    continue
                href = el.get("src") or el.get(XLINK) or el.get("href") or ""
                key = posixpath.normpath(posixpath.join(posixpath.dirname(doc), href.split("#")[0]))
                if not href or re.match(r"^[a-z]+:", href) or key not in names or z.getinfo(key).file_size < MIN_BYTES:
                    continue
                use = {"doc": doc, "xpath": tree.getpath(el), "alt": (el.get("alt") or "").strip()}
                if key in data:
                    data[key]["uses"].append(use)
                    continue
                ch = orig[last]["chapter"] if last else first_ch
                if ch is None:
                    continue  # a book without any text: nothing to anchor figure segments to
                ids = list(book.original(ch))
                after_i = ids.index(last) if last in ids else -1
                context = " / ".join(_plain(orig[i]["text"])[:160] for i in ids[max(after_i, 0):after_i + 2])
                images.mkdir(parents=True, exist_ok=True)
                file = images / key.replace("/", "_")
                file.write_bytes(z.read(key))
                data[key] = {"file": str(file.relative_to(book.root)), "uses": [use], "chapter": ch,
                             "after": last if last in ids else None, "context": context, "kind": None,
                             "segments": [], "alt_segment": None, "done": False}
            if mapping.get(doc):
                prev = (orig[mapping[doc][0]["id"]]["chapter"], mapping[doc][-1]["id"])
    _save(book, data)
    return data


def groups(book):
    pending = [k for k, v in load(book).items() if not v["done"]]
    return [pending[i:i + PER_TASK] for i in range(0, len(pending), PER_TASK)]


def prompt_list(book, keys):
    data = load(book)
    return "\n".join(f"- image `{k}`\n  file: `{book.path(data[k]['file'])}`\n  nearby text: {data[k]['context'] or '(none)'}"
                     for k in keys if k in data)


def validate(rows, keys):
    errors, seen = [], set()
    for n, r in rows:
        if r.get("image") not in keys:
            errors.append(f"line {n}: image {r.get('image')!r} is not in this task")
        if r.get("kind") not in KINDS:
            errors.append(f"line {n}: kind must be one of {sorted(KINDS)}")
        items = r.get("items")
        if not isinstance(items, list) or not all(isinstance(x, str) and "{{" not in x and len(x) < 400 for x in items):
            errors.append(f"line {n}: items must be a list of strings (no '{{{{', under 400 characters each)")
        seen.add(r.get("image"))
    if set(keys) - seen:
        errors.append(f"images without a line: {sorted(set(keys) - seen)[:10]}")
    return errors


def merge(book, rows):
    """Insert transcribed strings (and alt text) into original/ right after each image's anchor segment."""
    data = load(book)
    for r in rows:
        e = data[r["image"]]
        if e["done"]:
            continue
        items = list(dict.fromkeys(x.strip() for x in r["items"] if x.strip()))
        alt = next((u["alt"] for u in e["uses"] if u["alt"] and u["alt"] != Path(r["image"]).name), "")
        ch = e["chapter"]
        segs = parse_segments(book.path("original", f"{ch}.md").read_text("utf-8"))
        n = sum("-f" in sid for sid in segs)
        new = {}
        for kind, text in [("alt", alt)] * bool(alt) + [("fig", x) for x in items]:
            n += 1
            new[f"{ch}-f{n:04d}"] = {"type": kind, "text": text}
        out = {} if e["after"] else dict(new)
        for sid, s in segs.items():
            out[sid] = s
            if sid == e["after"]:
                out.update(new)
        book.path("original", f"{ch}.md").write_text(
            dump_segments({k: {"type": v["type"], "text": v["text"]} for k, v in out.items()}), "utf-8")
        e.update(kind=r["kind"], done=True, segments=[k for k, v in new.items() if v["type"] == "fig"],
                 alt_segment=next((k for k, v in new.items() if v["type"] == "alt"), None))
    _save(book, data)


def build_edits(book, trans):
    """-> ({doc: edit(tree)}, {zip name: edit(bytes)}, info). Keys under images, translated alt, replacements."""
    orig, data = book.original(), load(book)
    fmt = {"label": "Text in the image: ", "pair": " = ", "sep": "; ", **book.tgt_lang.get("figures", {})}
    per_doc, other, info = {}, {}, {"with_text": 0, "keyed": 0, "replaced": 0}
    for key, e in data.items():
        if not e["done"]:
            continue
        info["with_text"] += bool(e["segments"])
        repl = book.path("figures", Path(key).name)
        if repl.exists():
            other[key] = lambda _, p=repl: p.read_bytes()
            info["replaced"] += 1
        pairs = [] if repl.exists() or e["kind"] == "cover" else \
            [(_plain(orig[s]["text"]), _plain(trans[s]["text"])) for s in e["segments"] if s in trans and s in orig]
        info["keyed"] += bool(pairs)
        alt = trans.get(e["alt_segment"] or "", {}).get("text")
        for u in e["uses"]:
            per_doc.setdefault(u["doc"], []).append((u["xpath"], pairs, _plain(alt) if alt and u["alt"] else None))
    src_tag = book.src_lang["tag"]

    def edit_for(items):
        def edit(tree):
            found = [(tree.xpath(x), pairs, alt) for x, pairs, alt in items]  # resolve all before inserting
            for els, pairs, alt in found:
                if not els:
                    continue
                img = els[0]
                if alt:
                    img.set("alt", alt)
                if pairs:
                    _insert_key(img, pairs, fmt, src_tag)
        return edit
    return {d: edit_for(items) for d, items in per_doc.items()}, other, info


def _insert_key(img, pairs, fmt, src_tag):
    node = img
    while (p := node.getparent()) is not None and epub.local(p) != "body" and not "".join(p.itertext()).strip():
        node = p  # climb wrappers that hold only the image (<p><img/></p>, <div><svg><image/></svg></div>)
    parent = node.getparent()
    tag = "p" if parent is not None and epub.local(parent) in FLOW else "span"
    key = etree.Element(f"{{{epub.XHTML}}}{tag}", {"class": "bth-figure-text", "style": (
        "display:block;font-size:0.85em;text-indent:0;text-align:start;margin:0.3em 0 1em")})
    key.text = fmt["label"]
    for i, (src, tgt) in enumerate(pairs):
        span = etree.SubElement(key, f"{{{epub.XHTML}}}span", {"lang": src_tag})
        span.text = src
        span.tail = fmt["pair"] + tgt + (fmt["sep"] if i < len(pairs) - 1 else "")
    node.addnext(key)


def report_lines(book):
    data = load(book)
    if not data:
        return []
    text = {k: v for k, v in data.items() if v["segments"]}
    replaced = {k for k in text if book.path("figures", Path(k).name).exists()}
    lines = ["", f"## Text in images ({len(text)} of {len(data)} images)", "",
             "Each image with text gets a key under it (source label = translation). For a fully translated image, "
             "save an edited copy under `figures/` with the same file name; it replaces the original at build "
             "time and the key is dropped.", ""]
    lines += [f"- `{Path(k).name}` ({v['kind']}, {len(v['segments'])} labels){' — replaced' if k in replaced else ''}: "
              f"`{v['file']}`, segments {v['segments'][0]}…" for k, v in text.items()] or ["none"]
    pending = sum(not v["done"] for v in data.values())
    return lines + (["", f"{pending} images not transcribed yet."] if pending else [])
