import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from bth import check, epub, tasks
from bth.book import Book, dump_segments, h8, load_lang, parse_segments, placeholders
from bth.cli import main, next_step


class Segments(unittest.TestCase):
    def test_roundtrip_and_meta(self):
        segs = {"ch01-p0001": {"type": "h1", "text": "Title"},
                "ch01-p0002": {"type": "p", "text": "Line {{1}}one{{/1}}\nline two", "meta": {"src": "ab", "locked": True}}}
        back = parse_segments(dump_segments(segs))
        self.assertEqual(back["ch01-p0002"]["text"], "Line {{1}}one{{/1}}\nline two")
        self.assertEqual(back["ch01-p0002"]["meta"], {"src": "ab", "locked": True})
        self.assertTrue(Book.human_edited(back["ch01-p0002"]))

    def test_placeholders(self):
        self.assertEqual(placeholders("a{{1}}b{{2/}}{{/1}}"), (["/1", "1", "2/"], True))
        self.assertFalse(placeholders("{{1}}{{2}}x{{/1}}{{/2}}")[1])  # crossed
        self.assertEqual(placeholders("{{1}}{{i}}T{{/i}}{{/1}}"), (["/1", "1"], True))  # target-added italics
        self.assertFalse(placeholders("{{i}}{{1}}T{{/i}}{{/1}}")[1])
        self.assertIn("placeholders differ", check.structural("{{1}}a{{/1}}", "a")[0])


class Numbers(unittest.TestCase):
    def test_scale_units(self):
        en, zh = load_lang("en"), load_lang("zh-Hans")
        self.assertEqual(check.numbers("3,000,000 people in 1975", en), [3e6, 1975])
        self.assertEqual(sorted(check.numbers("1975年有300万人", zh)), [1975, 3e6])
        self.assertEqual(check.numbers("1.5 million", en), check.numbers("150万", zh))
        self.assertEqual(check.numbers("the 1980s and the '70s", en), [])  # decades are rewritten, not checked

    def test_term_case(self):
        rows = [{"source": "The Wealth of Nations"}, {"source": "opportunity cost"}]
        self.assertEqual(check.term_hits(rows, "the wealth of nations. Opportunity costs"), [rows[1]])
        rows = [{"source": "马克"}, {"source": "马克思"}, {"source": "马克", "context": "x"}]
        self.assertEqual(check.term_hits(rows, "马克思说"), [rows[1]])  # longest source wins
        self.assertEqual(check.term_hits(rows, "马克思与马克"), rows)


class NavLabels(unittest.TestCase):
    def test_label_whitespace_and_source_pack(self):
        from bth import build
        edit = build._labels_edit({"第一章 绪论": "Chapter 1"})
        self.assertEqual(edit("<text>第一章\u3000绪论</text>".encode()).decode(), "<text>Chapter 1</text>")
        edit = build._labels_edit({"第二节 债台为何高筑：欧美的教训": "Section 2", "开始": "Start"})
        self.assertEqual(edit("<text>第二节 债台为何高筑欧美的教训</text>".encode()).decode(),
                         "<text>Section 2</text>")  # a converter dropped the colon
        self.assertEqual(edit('<reference title="开始"/>'.encode()).decode(), '<reference title="Start"/>')
        book = type("B", (), {"tgt_lang": load_lang("en"), "src_lang": load_lang("zh-Hans"),
                              "original": lambda self: {}})()
        labels = build._nav_labels(book, {})
        self.assertEqual(labels["书名页"], "Title Page")
        self.assertEqual(labels["封面"], "Cover")


class EpubRoundtrip(unittest.TestCase):
    def test_extract_fill_verify(self):
        d = Path(tempfile.mkdtemp())
        body = ('<h1>One</h1><p>Hello <em>big</em> world<a id="n1" href="ch001.xhtml#n1">1</a></p>'
                '<nav role="doc-index"><ul><li>Index entry, <a href="ch001.xhtml#n1">5</a></li></ul></nav>')
        epub.make_epub(d / "a.epub", "T", "en", [("One", body)])
        docs, coverage = epub.extract(d / "a.epub")
        self.assertGreater(coverage, 0.95)
        segs = docs[0][1]
        self.assertEqual([s[1] for s in segs], ["One", "Hello {{1}}big{{/1}} world{{2}}1{{/2}}", "Index entry, {{1}}5{{/1}}"])
        edits = {docs[0][0]: epub.fill_doc([(x, t.upper(), sh) for _, t, x, sh in segs])}
        epub.rewrite(d / "a.epub", d / "b.epub", edits)
        docs2, _ = epub.extract(d / "b.epub")
        self.assertEqual([s[1] for s in docs2[0][1]], [s[1].upper() for s in segs])
        self.assertEqual(epub.verify(d / "b.epub")[0], [])
        el = epub.parse(b"<p xmlns='http://www.w3.org/1999/xhtml'>x</p>").getroot()
        epub._fill(el, "See {{i}}Title{{/i}}.", {})
        self.assertEqual(el[0].tag, "{http://www.w3.org/1999/xhtml}i")
        with zipfile.ZipFile(d / "b.epub") as z:
            self.assertEqual(z.namelist()[0], "mimetype")


class Flow(unittest.TestCase):
    def test_txt_book_end_to_end(self):
        d = Path(tempfile.mkdtemp())
        (d / "book.txt").write_text("Chapter 1\n\nIt cost 3,000,000 dollars.\n\nChapter 2\n\nThe end.", "utf-8")
        root = d / "proj"
        main(["init", str(root), "--source", str(d / "book.txt"), "--from", "en", "--to", "zh-Hans", "--no-git"])
        (root / "book.toml").write_text((root / "book.toml").read_text().replace("entities = true", "entities = false")
                                        .replace("qa_rounds = 2", "qa_rounds = 1"))
        book = Book(root)
        self.assertEqual(next_step(book)["phase"], "spec")
        c = tasks.claim(book, "spec", "w1")
        for f in ("style_guide.md", "examples.md"):
            (root / f).write_text("x")
        (root / "glossary.csv").write_text("source,target,status,forbidden\ndollars,美元,approved,刀\n")
        self.assertTrue(tasks.done(book, c["task"])["ok"])
        step = next_step(book)
        self.assertEqual((step["action"], step["phase"]), ("dispatch", "translate"))
        c = tasks.claim(book, "translate", "w1")
        src = parse_segments(Path(book.path("original", "ch01.md")).read_text()) | \
            parse_segments(Path(book.path("original", "ch02.md")).read_text())
        out = Path(c["output"])
        out.write_text(dump_segments({k: {"type": v["type"], "text": "{{9}}"} for k, v in src.items()}))
        self.assertFalse(tasks.done(book, c["task"])["ok"])  # invented placeholder is rejected
        zh = {"Chapter 1": "第1章", "It cost 3,000,000 dollars.": "它花了300万美元。", "Chapter 2": "第2章",
              "The end.": "完。"}
        out.write_text(dump_segments({k: {"type": v["type"], "text": zh[v["text"]]} for k, v in src.items()}))
        self.assertTrue(tasks.done(book, c["task"])["ok"])
        self.assertEqual([i for i in check.run(book) if i["level"] == "error"], [])
        self.assertEqual(next_step(book)["phase"], "qa")
        c = tasks.claim(book, "qa", "w2")
        Path(c["output"]).write_text("")
        self.assertTrue(tasks.done(book, c["task"])["ok"])
        result = next_step(book)
        self.assertEqual(result["action"], "done")
        self.assertEqual(result["problems"], [])
        docs, _ = epub.extract(result["output"])
        self.assertIn("它花了300万美元。", [s[1] for _, segs in docs for s in segs])
        with zipfile.ZipFile(result["output"]) as z:  # nav entries follow translated headings, lang is set
            nav = z.read("OEBPS/nav.xhtml").decode()
            self.assertIn("第1章", nav)
            self.assertIn('xml:lang="zh-Hans"', nav)
        # a human edit locks the segment against later machine merges
        ch = book.translation("ch01")
        sid = next(k for k, v in ch.items() if v["text"] == "完。" or "美元" in v["text"])
        ch[sid]["text"] = "人工修改。"
        book.write_translation("ch01", ch)
        self.assertTrue(Book.human_edited(book.translation("ch01")[sid]))
        self.assertNotEqual(h8("人工修改。"), book.translation("ch01")[sid]["meta"]["mt"])
        shutil.rmtree(d)


class Consistency(unittest.TestCase):
    def test_titles_quotes_repeats_and_round_two_scope(self):
        d = Path(tempfile.mkdtemp())
        q = "“学习就是在不确定之中不断修正自己的模型。”"
        (d / "b.txt").write_text(f"《国富论》很有名。\n\n他读了《国富论》。\n\n{q}\n\n书中写道：{q}\n\n《资本论》\n\n《资本论》", "utf-8")
        main(["init", str(d / "p"), "--source", str(d / "b.txt"), "--from", "zh-Hans", "--to", "en", "--no-git"])
        book = Book(d / "p")
        next_step(book)  # extract
        ids = list(book.original())
        self.assertIn("国富论", (d / "p" / "work" / "entities.tsv").read_text())
        self.assertEqual(len((d / "p" / "work" / "quotes.tsv").read_text().splitlines()), 3)
        (d / "p" / "glossary.csv").write_text("source,target,type,status\n国富论,The Wealth of Nations,title,proposed\n")
        texts = ["The Wealth of Nations is famous.", "He read Wealth of Nations.",
                 "“Learning is constantly correcting one's model.”", "The book says: “To learn is to correct.”",
                 "Capital", "Das Kapital"]
        book.write_translation("ch01", {i: {"type": "p", "text": t} for i, t in zip(ids, texts)})
        found = {(i["code"], i["id"]) for i in check.run(book)}
        self.assertIn(("title", ids[1]), found)                     # title rendered differently from its row
        self.assertNotIn(("title", ids[0]), found)
        self.assertIn(("quote-variant", ids[3]), found)             # same quotation, two renderings
        self.assertIn(("inconsistent", ids[5]), found)              # identical source segments differ
        self.assertIn(("title-unlisted", ids[4]), found)            # recurring title without a glossary row
        self.assertEqual(check.related(book, [ids[2]]), {ids[2], ids[3]})  # shares the quotation
        (d / "p" / "quotes.csv").write_text("id,quote,status\n")
        tasks.plan(book, "entities")  # the quotes scope: the agent's CSV is validated, then merged into quotes.csv
        c = next(x for x in iter(lambda: tasks.claim(book, "entities", "w"), None) if x["task"].endswith("quotes"))
        self.assertIn("quotes.tsv", Path(c["prompt"]).read_text())
        out = Path(c["output"])
        out.write_text(f"id,quote,lang,original,use,status,evidence\n{ids[2]},学习就是…,en,x,,verified,\n")
        self.assertIn("evidence URL", str(tasks.done(book, c["task"])["errors"]))
        (d / "p" / "quotes.csv").unlink()
        out.write_text(f"id,quote,lang,original,use,status,evidence\n"
                       f"{ids[2]},学习就是…,en,x,To learn is to correct.,verified,https://e.org\n"
                       f"{ids[3]},学习就是…,en,,,unverified,\n")
        self.assertTrue(tasks.done(book, c["task"])["ok"])
        t = tasks.plan(book, "translate", ids[2:4])[0]
        self.assertIn("To learn is to correct.", tasks.render(book, tasks.load(book, t)))
        found = {(i["code"], i["id"]) for i in check.run(book)}
        self.assertIn(("quote", ids[2]), found)                     # verified wording not used
        self.assertIn(("quote-unmarked", ids[3]), found)            # unverified but not marked
        shutil.rmtree(d)


class SourceErrors(unittest.TestCase):
    def test_policy_selection_appendix_and_inline_notes(self):
        import json
        from bth import build, errata
        issue = {"id": "ch01-p0002", "severity": "minor", "category": "source", "source_error": True, "obvious": False,
                 "src": "1942", "suggestion": "1492年", "note": "原文作1942年，应为1492年。"}
        self.assertEqual(errata.selected([issue], "keep"), [])
        self.assertEqual(errata.selected([issue], "fix-obvious"), [])          # not obvious: stays as printed
        self.assertEqual(errata.selected([issue], "fix-with-note"), [issue])
        d = Path(tempfile.mkdtemp())
        (d / "b.txt").write_text("Chapter 1\n\nColumbus sailed in 1942.\n\nThe end.", "utf-8")
        root = d / "p"
        main(["init", str(root), "--source", str(d / "b.txt"), "--from", "en", "--to", "zh-Hans", "--no-git"])
        book = Book(root)
        next_step(book)  # extract
        self.assertIn("fix-with-note", tasks.render(book, tasks.load(book, tasks.plan(book, "translate")[0])))
        (root / "review").mkdir()
        (root / "review" / "qa_r1.jsonl").write_text(json.dumps(issue, ensure_ascii=False) + "\n")
        texts = {"ch01-p0001": "第1章", "ch01-p0002": "哥伦布于1492年出航。", "ch01-p0003": "完。"}
        book.write_translation("ch01", {k: {"type": "p", "text": v} for k, v in texts.items()})
        r = build.run(book)
        self.assertEqual(r["problems"], [])                                    # link and anchor resolve
        with zipfile.ZipFile(r["output"]) as z:
            page = z.read("OEBPS/bth-errata.xhtml").decode()
            self.assertIn('href="ch001.xhtml#bth-ch01-p0002">第1章</a>: 原文作1942年，应为1492年。', page)
            self.assertIn("译者勘误", z.read("OEBPS/nav.xhtml").decode())
            self.assertIn('idref="bth-errata"', z.read("OEBPS/content.opf").decode())
        self.assertIn("applied", (root / "errata.csv").read_text())
        (root / "book.toml").write_text((root / "book.toml").read_text().replace('"appendix"', '"inline"'))
        r = build.run(Book(root))
        with zipfile.ZipFile(r["output"]) as z:
            self.assertNotIn("OEBPS/bth-errata.xhtml", z.namelist())
            self.assertIn("哥伦布于1492年出航。<span class=\"bth-translator-note\">（译者注：原文作1942年，应为1492年。）",
                          z.read("OEBPS/ch001.xhtml").decode())
        shutil.rmtree(d)


class Figures(unittest.TestCase):
    @staticmethod
    def png(w, h):
        import random
        import struct
        import zlib
        rnd = random.Random(w)
        raw = b"".join(b"\x00" + bytes(rnd.randrange(200, 256) for _ in range(w * 3)) for _ in range(h))
        chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))  # noqa: E731
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))

    def test_fit(self):
        from bth.figures import fit
        self.assertEqual(fit("China", 200, 30, 20), (["China"], 20))
        self.assertEqual(fit("United States", 50, 40, 20)[0], ["United", "States"])  # wrap beats a tiny font
        self.assertEqual(len(fit("中华人民共和国", 30, 100, 20)[0]), 3)
        self.assertEqual(fit("Consumption", 60, 60, 20)[0], ["Consumption"])  # one word: shrink, do not split
        lines, size = fit("Stock market crash, capital flight, debt swaps, wealth management product boom", 100, 340, 20)
        self.assertGreater(len(lines), 3)  # a tall narrow space wraps onto many lines
        self.assertGreaterEqual(size, 9)

    def test_image_text_is_located_translated_and_set_in_place(self):
        import json
        from bth import build, figures, report
        d = Path(tempfile.mkdtemp())
        epub.make_epub(d / "b.epub", "T", "en", [
            ("One", '<h1>One</h1><p>Before the chart.</p><p><img src="img/chart.png" alt="Sales chart"/></p>'
                    '<p>Figure 1: Sales.</p>'),
            ("Two", "<p>Next.</p>"), ("Plate", '<div><img src="img/plate.png" alt=""/></div>')])
        with zipfile.ZipFile(d / "b.epub", "a") as z:
            z.writestr("OEBPS/img/chart.png", self.png(200, 100))
            z.writestr("OEBPS/img/plate.png", self.png(120, 60))
        cover = '<item id="cover" href="img/cover.png" media-type="image/png" properties="cover-image"/>'
        epub.rewrite(d / "b.epub", d / "c.epub", {}, {"OEBPS/content.opf": lambda b: b.replace(
            b"</manifest>", cover.encode() + b"</manifest>")}, {"OEBPS/img/cover.png": self.png(90, 120)})
        shutil.move(d / "c.epub", d / "b.epub")
        root = d / "p"
        main(["init", str(root), "--source", str(d / "b.epub"), "--from", "en", "--to", "zh-Hans", "--no-git"])
        book = Book(root)
        self.assertEqual(next_step(book)["phase"], "figures")
        c = tasks.claim(book, "figures", "w")
        self.assertIn("200 × 100 px", Path(c["prompt"]).read_text())
        out = Path(c["output"])
        chart = {"image": "OEBPS/img/chart.png", "kind": "chart", "labels": [
            {"text": "Sales", "box": [10, 10, 60, 30], "space": [10, 10, 150, 30], "align": "start"},
            {"text": "Costs", "box": [10, 40, 60, 60], "color": "#333333"},
            {"text": "Sales", "box": [10, 70, 60, 300]}]}
        plate = {"image": "OEBPS/img/plate.png", "kind": "table",
                 "labels": [{"text": "Revenue", "box": [5, 5, 60, 25], "rotate": -90}]}
        out.write_text(json.dumps(chart) + "\n" + json.dumps(plate))
        self.assertIn("inside 200 × 100", str(tasks.done(book, c["task"])["errors"]))  # box outside the image
        chart["labels"][2]["box"] = [10, 70, 60, 90]
        out.write_text(json.dumps(chart) + "\n" + json.dumps(plate))
        self.assertEqual(len(figures.preview(book, rows=[chart, plate])), 2)  # label boxes, before merging
        self.assertTrue(tasks.done(book, c["task"])["ok"])
        self.assertEqual(next_step(book)["phase"], "spec")  # transcribed once, then the normal pipeline
        o = book.original()
        self.assertEqual([(k, v["text"]) for k, v in o.items() if k.startswith("ch01")][2:5],
                         [("ch01-f0001", "Sales chart"), ("ch01-f0002", "Sales"), ("ch01-f0003", "Costs")])
        self.assertEqual(list(book.original("ch02")), ["ch02-p0001", "ch02-f0001"])  # image-only page
        for ch in book.chapters():  # stand-in translation: prefix every segment
            book.write_translation(ch, {k: {"type": v["type"], "text": "译" + v["text"]}
                                        for k, v in book.original(ch).items()})
        r = build.run(book)
        self.assertEqual(r["problems"], [])  # the overlay SVGs are in the manifest
        self.assertEqual(r["images"], {"with_text": 2, "overlaid": 2, "replaced": 0})
        with zipfile.ZipFile(r["output"]) as z:
            one, overlay = z.read("OEBPS/ch001.xhtml").decode(), z.read("OEBPS/img/chart.bth.svg").decode()
            self.assertIn('media-type="image/svg+xml" href="img/chart.bth.svg"', z.read("OEBPS/content.opf").decode())
        self.assertIn('src="img/chart.bth.svg"', one)
        self.assertIn('alt="译Sales chart"', one)
        self.assertEqual(overlay.count(">译Sales</tspan>"), 2)
        self.assertIn('fill="#333333"', overlay)
        report.run(book)
        qa = (root / "review" / "QA_REPORT.md").read_text()
        self.assertIn("Text in images (2 of 3 images)", qa)  # the manifest cover is listed, not transcribed
        self.assertIn("Cover `cover.png`: untranslated", qa)
        (root / "figures").mkdir()
        (root / "figures" / "chart.png").write_bytes(b"translated chart")
        (root / "figures" / "cover.png").write_bytes(b"translated cover")
        r = build.run(book, verify=False)
        with zipfile.ZipFile(r["output"]) as z:
            self.assertEqual(z.read("OEBPS/img/chart.png"), b"translated chart")
            self.assertEqual(z.read("OEBPS/img/cover.png"), b"translated cover")
            self.assertIn('src="img/chart.png"', z.read("OEBPS/ch001.xhtml").decode())
        shutil.rmtree(d)


class PdfHeadings(unittest.TestCase):
    def test_label_and_two_line_title(self):
        try:
            import pymupdf
        except ImportError:
            self.skipTest("pymupdf not installed")
        d = Path(tempfile.mkdtemp())
        doc = pymupdf.open()
        for chapter in ("One", "Two"):
            page = doc.new_page()
            page.insert_text((72, 80), f"CHAPTER {chapter.upper()}", fontsize=12)
            page.insert_text((72, 120), "A Long Title", fontsize=20)
            page.insert_text((72, 150), f"Set on Two Lines {chapter}", fontsize=20)
            page.insert_text((72, 200), "Body text of the chapter goes here and is long enough.", fontsize=10)
        doc.save(d / "b.pdf")
        from bth.extract import from_pdf
        chapters = from_pdf(d / "b.pdf", load_lang("en"))
        self.assertEqual([t for t, _ in chapters], ["A Long Title Set on Two Lines One", "A Long Title Set on Two Lines Two"])
        self.assertEqual(chapters[1][1][0], ("h2", "CHAPTER TWO"))


class ChecksOnBook(unittest.TestCase):
    def test_name_variants_terms_and_human_lock(self):
        d = Path(tempfile.mkdtemp())
        (d / "b.txt").write_text("Ada Lovelace met Babbage.\n\nLovelace again.\n\nThe Costco store.", "utf-8")
        main(["init", str(d / "p"), "--source", str(d / "b.txt"), "--from", "en", "--to", "zh-Hans", "--no-git"])
        book = Book(d / "p")
        next_step(book)  # extract
        (d / "p" / "glossary.csv").write_text("source,target,status,forbidden\nCostco,开市客,approved,好市多\n")
        ids = list(book.original())
        texts = ["作家阿达·洛夫莱斯（Ada Lovelace）见了巴贝奇（Charles Babbage of the Royal Society, London）。",
                 "艾达·洛夫莱斯（Ada Lovelace）又来了。", "好市多商店。"]
        book.write_translation("ch01", {i: {"type": "p", "text": t, "meta": {"mt": h8(t)}} for i, t in zip(ids, texts)})
        codes = {(i["code"], i["level"]) for i in check.run(book)}
        self.assertIn(("name-variant", "warn"), codes)   # 阿达·洛夫莱斯 vs 艾达·洛夫莱斯 (prefix 作家 ignored)
        self.assertIn(("forbidden", "error"), codes)
        self.assertIn(("term", "warn"), codes)
        self.assertNotIn(("residue", "warn"), codes)  # English inside first-mention parentheses is intended
        t = tasks.plan(book, "fix", ids[2:])[0]
        tasks.claim(book, "fix", "w")
        seg = book.translation()[ids[2]]
        seg["text"] = "人工改的。"           # human edit after the plan
        book.write_translation("ch01", {**book.translation(), ids[2]: seg})
        Path(tasks.output_path(book, tasks.load(book, t))).write_text(f"<!-- {ids[2]} p -->\n开市客商店。\n")
        self.assertEqual(tasks.done(book, t)["skipped_human_edited"], [ids[2]])
        self.assertEqual(book.translation()[ids[2]]["text"], "人工改的。")

if __name__ == "__main__":
    unittest.main()
