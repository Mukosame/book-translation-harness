"""Text inside images (charts, diagrams, tables saved as pictures), translated in place.

Image pixels never reach the text pipeline, so the labels inside a chart would stay in the source language.
1. `scan`: every raster image in the spine is listed in work/figures.json and copied to work/images/.
   The manifest cover is listed too, not transcribed (its text is the title and author): replace it via figures/.
2. The `figures` phase: an agent that can view images transcribes each label with its position (pixel box,
   free space around it, alignment, rotation, colours) and checks the boxes on a rendered preview.
3. `merge`: each distinct label text becomes an ordinary `fig` segment (and alt text an `alt` segment) right
   after the image's anchor, so translation, glossary checks, QA and human edits apply unchanged.
4. Build: an SVG overlay per image covers each original label with its background colour and sets the
   translation in the label's space, shrinking or wrapping it to fit. The <img> then points at the SVG.
   A translated image saved by a person in `figures/` (same file name) wins over the overlay.

work/figures.json: {image zip path: {file, size, uses: [{doc, xpath, alt}], chapter, after, context,
                                     kind, labels: [{sid, box, space, align, rotate, color, background,
                                     weight}], segments, alt_segment, done}}
"""
import base64
import itertools
import json
import posixpath
import re
import struct
import unicodedata
import zipfile
from html import escape
from pathlib import Path

from lxml import etree

from . import epub
from .book import PH, dump_segments, parse_segments

TYPES = ("fig", "alt")
KINDS = {"chart", "diagram", "table", "map", "photo", "illustration", "cover", "decorative", "text"}
PER_TASK = 6
MIN_BYTES = 2048  # shortcut: smaller files are taken to be rules/ornaments; lower it if tiny label images exist
XLINK = "{http://www.w3.org/1999/xlink}href"
MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif"}
COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
LINE = 1.15  # line height in em


def _path(book):
    return book.work / "figures.json"


def load(book):
    p = _path(book)
    return json.loads(p.read_text("utf-8")) if p.exists() else {}


def _save(book, data):
    _path(book).write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")


def _plain(text):
    return re.sub(r"\s+", " ", PH.sub("", text)).strip()


def image_size(data):
    """(width, height) of a PNG, GIF or JPEG from its header, else None."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return struct.unpack("<HH", data[6:10])
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker, length = data[i + 1], struct.unpack(">H", data[i + 2:i + 4])[0]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):  # start of frame
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return w, h
            i += 2 + length
    return None  # shortcut: WebP/SVG sources are not overlaid; add parsers if books use them


def scan(book):
    """Find raster images in spine documents and anchor each after the segment preceding it (once per project)."""
    if _path(book).exists():
        return load(book)
    mapping = json.loads((book.work / "skeleton.json").read_text("utf-8"))
    orig = book.original()
    images = book.work / "images"
    data, prev = {}, None  # prev: last segment id of the closest earlier document with segments
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
            last = prev
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
                raw = z.read(key)
                size = image_size(raw)
                ch = orig[last]["chapter"] if last else first_ch
                if ch is None or size is None or posixpath.splitext(key)[1].lower() not in MIME:
                    continue
                ids = list(book.original(ch))
                after_i = ids.index(last) if last in ids else -1
                context = " / ".join(_plain(orig[i]["text"])[:160] for i in ids[max(after_i, 0):after_i + 2])
                images.mkdir(parents=True, exist_ok=True)
                file = images / key.replace("/", "_")
                file.write_bytes(raw)
                data[key] = {"file": str(file.relative_to(book.root)), "size": list(size), "uses": [use],
                             "chapter": ch, "after": last if last in ids else None, "context": context,
                             "kind": None, "labels": [], "segments": [], "alt_segment": None, "done": False}
            if mapping.get(doc):
                prev = mapping[doc][-1]["id"]
        cover = epub.cover_image(z)
        if cover in names and cover not in data and first_ch and posixpath.splitext(cover)[1].lower() in MIME:
            # its text is the title and author: not transcribed, only replaceable via figures/
            raw = z.read(cover)
            images.mkdir(parents=True, exist_ok=True)
            file = images / cover.replace("/", "_")
            file.write_bytes(raw)
            data[cover] = {"file": str(file.relative_to(book.root)), "size": list(image_size(raw) or (0, 0)),
                           "uses": [], "chapter": first_ch, "after": None, "context": "", "kind": "cover",
                           "labels": [], "segments": [], "alt_segment": None, "done": True}
    _save(book, data)
    return data


def groups(book):
    pending = [k for k, v in load(book).items() if not v["done"]]
    return [pending[i:i + PER_TASK] for i in range(0, len(pending), PER_TASK)]


def prompt_list(book, keys):
    data = load(book)
    return "\n".join(f"- image `{k}`: {data[k]['size'][0]} × {data[k]['size'][1]} px\n"
                     f"  file: `{book.path(data[k]['file'])}`\n  nearby text: {data[k]['context'] or '(none)'}"
                     for k in keys if k in data)


def _box_ok(b, size):
    return (isinstance(b, list) and len(b) == 4 and all(isinstance(x, (int, float)) for x in b)
            and 0 <= b[0] < b[2] <= size[0] and 0 <= b[1] < b[3] <= size[1])


def validate(book, rows, keys):
    data, errors, seen = load(book), [], set()
    for n, r in rows:
        key = r.get("image")
        if key not in keys:
            errors.append(f"line {n}: image {key!r} is not in this task")
            continue
        seen.add(key)
        if r.get("kind") not in KINDS:
            errors.append(f"line {n}: kind must be one of {sorted(KINDS)}")
        labels = r.get("labels")
        if not isinstance(labels, list):
            errors.append(f"line {n}: labels must be a list")
            continue
        size = data[key]["size"]
        for j, lb in enumerate(labels, 1):
            where = f"line {n} label {j}"
            if not isinstance(lb, dict) or not isinstance(lb.get("text"), str) or not lb["text"].strip() \
                    or "{{" in lb["text"] or len(lb["text"]) > 300:
                errors.append(f"{where}: text must be a non-empty string without '{{{{' (under 300 characters)")
                continue
            for f in ("box", "space"):
                if (f == "box" or f in lb) and not _box_ok(lb.get(f), size):
                    errors.append(f"{where}: {f} must be [x0, y0, x1, y1] in pixels inside {size[0]} × {size[1]}")
            if lb.get("align", "start") not in ("start", "middle", "end") or lb.get("rotate", 0) not in (0, 90, -90):
                errors.append(f"{where}: align is start|middle|end, rotate is 0|90|-90")
            for f in ("color", "background"):
                if f in lb and not COLOR.match(str(lb[f])):
                    errors.append(f"{where}: {f} must be a #rrggbb colour")
    if set(keys) - seen:
        errors.append(f"images without a line: {sorted(set(keys) - seen)[:10]}")
    return errors


def merge(book, rows):
    """Insert each distinct label (and alt text) into original/ right after the image's anchor segment."""
    data = load(book)
    for r in rows:
        e = data[r["image"]]
        if e["done"]:
            continue
        alt = next((u["alt"] for u in e["uses"] if u["alt"] and u["alt"] != Path(r["image"]).name), "")
        ch = e["chapter"]
        segs = parse_segments(book.path("original", f"{ch}.md").read_text("utf-8"))
        n = sum("-f" in sid for sid in segs)
        new, by_text = {}, {}

        def add(kind, text):
            nonlocal n
            n += 1
            new[f"{ch}-f{n:04d}"] = {"type": kind, "text": text}
            return f"{ch}-f{n:04d}"
        alt_sid = add("alt", alt) if alt else None
        labels = []
        for lb in r["labels"]:
            text = " ".join(lb["text"].split())
            if text not in by_text:
                by_text[text] = add("fig", text)
            labels.append({"sid": by_text[text], **{k: v for k, v in lb.items() if k != "text"}})
        out = {} if e["after"] else dict(new)
        for sid, s in segs.items():
            out[sid] = s
            if sid == e["after"]:
                out.update(new)
        book.path("original", f"{ch}.md").write_text(
            dump_segments({k: {"type": v["type"], "text": v["text"]} for k, v in out.items()}), "utf-8")
        e.update(kind=r["kind"], done=True, labels=labels, segments=list(by_text.values()), alt_segment=alt_sid)
    _save(book, data)


def _em(text):
    """Estimated advance width in em (shortcut: no font metrics; generous for Latin, exact-ish for CJK)."""
    w = 0.0
    for c in text:
        if unicodedata.east_asian_width(c) in "WF":
            w += 1.0
        elif c in " iljtfrI.,;:'!|()-":
            w += 0.3
        elif c.isupper() or c in "mw@%&":
            w += 0.7
        else:
            w += 0.52
    return w


def fit(text, width, height, size0):
    """Best (lines, font size) for text in a width × height area: shrink, or wrap (more than 3 lines only greedily)."""
    if " " in text:
        toks = re.findall(r"\S+\s*", text)
    elif any(unicodedata.east_asian_width(c) in "WF" for c in text):
        toks = list(text)  # CJK may break between any two characters
    else:
        toks = [text]  # a single Latin word is shrunk, never split
    best = ([text], 0.0)
    for n in range(1, min(3, len(toks)) + 1):
        for cuts in itertools.combinations(range(1, len(toks)), n - 1) if len(toks) <= 40 or n == 1 else []:
            lines = ["".join(toks[a:b]).strip() for a, b in zip((0,) + cuts, cuts + (len(toks),))]
            size = min(size0, 0.92 * width / max(max(map(_em, lines)), 0.1), height / (n * LINE))  # 8% margin
            if size > best[1] * 1.15 or (size > best[1] and len(lines) == len(best[0])):
                best = (lines, size)  # a wrap must buy a clearly larger font to beat fewer lines
    if " " in text and len(toks) > 3:  # tall narrow spaces: a greedy wrap onto more than 3 lines may read better
        size = size0
        while size >= 6 and size > best[1] * 1.15:
            lines, cur = [], ""
            for tok in toks:
                if cur and _em((cur + tok).strip()) * size > 0.92 * width:
                    lines.append(cur.strip())
                    cur = tok
                else:
                    cur += tok
            lines.append(cur.strip())
            if len(lines) > 3 and len(lines) * size * LINE <= height and max(map(_em, lines)) * size <= 0.92 * width:
                best = (lines, size)
                break
            size -= 0.5
    return best


def svg(book, e, texts, mode="overlay"):
    """SVG of the image with labels replaced by texts[sid] (overlay), or with label boxes drawn (boxes)."""
    w, h = e["size"]
    raw = book.path(e["file"]).read_bytes()
    uri = f"data:{MIME[Path(e['file']).suffix.lower()]};base64,{base64.b64encode(raw).decode()}"
    font = escape(book.tgt_lang.get("figures", {}).get("font", "sans-serif"))
    covers, marks = [], []
    src = {k: _plain(v["text"]) for k, v in book.original(e["chapter"]).items()} if mode == "overlay" else {}

    def start_size(lb):
        # Never larger than the original type, about sqrt(box area / characters) since CJK glyphs are square,
        # so the tall box of a wrapped label does not set huge type.
        x0, y0, x1, y1 = lb["box"]
        orig = ((x1 - x0) * (y1 - y0) / max(_em(src.get(lb["sid"], "")), 1.0)) ** 0.5
        return min(0.9 * ((y1 - y0) if lb.get("rotate", 0) == 0 else (x1 - x0)), orig)
    sizes = sorted(start_size(lb) for lb in e["labels"])
    typical = sizes[len(sizes) // 2] if sizes else 0  # and no label above the image's typical size
    for i, lb in enumerate(e["labels"], 1):
        x0, y0, x1, y1 = lb["box"]
        sx0, sy0, sx1, sy1 = lb.get("space") or lb["box"]
        if mode == "boxes":
            marks.append(f'<rect x="{sx0}" y="{sy0}" width="{sx1 - sx0}" height="{sy1 - sy0}" fill="none" '
                         f'stroke="#1e88e5" stroke-width="2" stroke-dasharray="6 4"/><rect x="{x0}" y="{y0}" '
                         f'width="{x1 - x0}" height="{y1 - y0}" fill="none" stroke="#e53935" stroke-width="2"/>'
                         f'<text x="{x0}" y="{max(y0 - 3, 12)}" font-size="13" fill="#e53935" '
                         f'font-family="sans-serif">{i}</text>')
            continue
        text = texts.get(lb["sid"])
        if not text:
            continue
        bg, rot = lb.get("background", "#ffffff"), lb.get("rotate", 0)
        # Cover the box with a margin for anti-aliased strokes, but never paint outside the label's space:
        # borders, lines and points next to a label must survive. Without a space only 1.5 px of margin.
        pad = max(2.0, 0.12 * min(x1 - x0, y1 - y0)) if lb.get("space") else 1.5
        cx0, cy0 = max(x0 - pad, sx0 if lb.get("space") else 0), max(y0 - pad, sy0 if lb.get("space") else 0)
        cx1, cy1 = min(x1 + pad, sx1 if lb.get("space") else w), min(y1 + pad, sy1 if lb.get("space") else h)
        covers.append(f'<rect x="{cx0:.1f}" y="{cy0:.1f}" width="{cx1 - cx0:.1f}" height="{cy1 - cy0:.1f}" fill="{bg}"/>')
        aw, ah = (sx1 - sx0, sy1 - sy0) if rot == 0 else (sy1 - sy0, sx1 - sx0)
        lines, size = fit(text, aw, ah, min(start_size(lb), typical))
        cx, cy = (sx0 + sx1) / 2, (sy0 + sy1) / 2
        align = lb.get("align", "start")  # rotated text: start/end along its own reading direction
        x = {"start": sx0, "middle": cx, "end": sx1}[align] if rot == 0 else \
            {"start": cx - aw / 2, "middle": cx, "end": cx + aw / 2}[align]
        top = cy - len(lines) * size * LINE / 2
        rotate = f' transform="rotate({rot} {cx:.1f} {cy:.1f})"' if rot else ""  # the space is free background
        spans = "".join(f'<tspan x="{x:.1f}" y="{top + size * (k * LINE + 0.84):.1f}">{escape(ln)}</tspan>'
                        for k, ln in enumerate(lines))
        marks.append(f'<text font-family="{font}" font-size="{size:.1f}" font-weight="{lb.get("weight", "normal")}" '
                     f'fill="{lb.get("color", "#000000")}" text-anchor="{align}" xml:space="preserve"{rotate}>'
                     f'{spans}</text>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" version="1.1" '
            f'width="{w}" height="{h}" viewBox="0 0 {w} {h}"><image width="{w}" height="{h}" xlink:href="{uri}"/>'
            f'{"".join(covers)}{"".join(marks)}</svg>')


def preview(book, keys=None, rows=None):
    """Render PNG previews to work/images/preview/: label boxes from an unmerged task output (rows), or the
    translated overlays of merged images (keys). Needs PyMuPDF; without it only the SVGs are written."""
    try:
        import pymupdf
    except ImportError:
        pymupdf = None
    data, trans = load(book), {k: _plain(v["text"]) for k, v in book.translation().items()}
    out_dir = book.work / "images" / "preview"
    out_dir.mkdir(parents=True, exist_ok=True)
    jobs = []
    for r in rows or []:
        if r.get("image") in data and isinstance(r.get("labels"), list):
            e = {**data[r["image"]], "labels": [{**lb, "sid": str(i)} for i, lb in enumerate(r["labels"])]}
            jobs.append((r["image"], "boxes", e))
    for k in keys or []:
        if data.get(k, {}).get("labels"):
            jobs.append((k, "overlay", data[k]))
    paths = []
    for key, mode, e in jobs:
        base = out_dir / f"{key.replace('/', '_')}.{mode}"
        doc = svg(book, e, trans, mode)
        base.with_suffix(".svg").write_text(doc, "utf-8")
        if pymupdf:
            pymupdf.open(stream=doc.encode("utf-8"), filetype="svg")[0].get_pixmap().save(str(base) + ".png")
        paths.append(str(base) + (".png" if pymupdf else ".svg"))
    return paths


def figure_keys(book, ids):
    """Images whose label segments occur among ids."""
    ids = set(ids)
    return [k for k, v in load(book).items() if ids & set(v["segments"])]


def build_edits(book, trans):
    """-> {"docs": {doc: edit(tree)}, "other": {name: edit(bytes)}, "add": {name: bytes}, "manifest": [href],
    "info": {...}}: overlays, translated alt text and human replacement images."""
    data, texts = load(book), {k: _plain(v["text"]) for k, v in trans.items()}
    res = {"docs": {}, "other": {}, "add": {}, "manifest": [],
           "info": {"with_text": 0, "overlaid": 0, "replaced": 0}}
    per_doc = {}
    for key, e in data.items():
        if not e["done"]:
            continue
        res["info"]["with_text"] += bool(e["labels"])
        target = None
        repl = book.path("figures", Path(key).name)
        if repl.exists():
            res["other"][key] = lambda _, p=repl: p.read_bytes()
            res["info"]["replaced"] += 1
        elif any(texts.get(lb["sid"]) for lb in e["labels"]):
            target = posixpath.splitext(key)[0] + ".bth.svg"
            res["add"][target] = svg(book, e, texts).encode("utf-8")
            res["manifest"].append(target)
            res["info"]["overlaid"] += 1
        alt = texts.get(e["alt_segment"] or "")
        for u in e["uses"]:
            per_doc.setdefault(u["doc"], []).append((u["xpath"], target, alt if u["alt"] else None))

    def edit_for(doc, items):
        def edit(tree):
            for xpath, target, alt in items:
                found = tree.xpath(xpath)
                if not found:
                    continue
                img = found[0]
                if alt:
                    img.set("alt", alt)
                for attr in ("src", XLINK, "href") if target else ():
                    if img.get(attr):
                        img.set(attr, posixpath.relpath(target, posixpath.dirname(doc)))
        return edit
    res["docs"] = {d: edit_for(d, items) for d, items in per_doc.items()}
    return res


def manifest_edit(opf_name, hrefs):
    """OPF edit that adds the overlay SVGs to the manifest."""
    def edit(data):
        root = etree.fromstring(data)
        manifest = root.find("{*}manifest")
        for i, target in enumerate(hrefs, 1):
            etree.SubElement(manifest, f"{{{epub.OPF}}}item", {
                "id": f"bth-figure-{i:03d}", "media-type": "image/svg+xml",
                "href": posixpath.relpath(target, posixpath.dirname(opf_name))})
        return etree.tostring(root, xml_declaration=True, encoding="utf-8")
    return edit


def report_lines(book):
    data = load(book)
    if not data:
        return []
    text = {k: v for k, v in data.items() if v["labels"]}
    lines = ["", f"## Text in images ({len(text)} of {len(data)} images)", "",
             "Labels are translated in place (an SVG overlay over the original image). Check them in the EPUB or with "
             "`bth preview <book>`. To use your own translated image instead, save it under `figures/` with the same "
             "file name; it replaces the original at build time.", ""]
    lines += [f"- `{Path(k).name}` ({v['kind']}, {len(v['labels'])} labels)"
              f"{' — replaced by figures/' if book.path('figures', Path(k).name).exists() else ''}: "
              f"segments {v['segments'][0]}…{v['segments'][-1]}" for k, v in text.items()] or ["none"]
    lines += [f"- Cover `{Path(k).name}`: " + ("replaced by figures/" if book.path("figures", Path(k).name).exists()
                                               else f"untranslated; save a translated copy as `figures/{Path(k).name}`")
              for k, v in data.items() if v["kind"] == "cover" and not v["labels"]]
    pending = sum(not v["done"] for v in data.values())
    return lines + (["", f"{pending} images not transcribed yet."] if pending else [])
