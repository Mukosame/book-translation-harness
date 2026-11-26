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
        self.assertIn("placeholders differ", check.structural("{{1}}a{{/1}}", "a")[0])


class Numbers(unittest.TestCase):
    def test_scale_units(self):
        en, zh = load_lang("en"), load_lang("zh-Hans")
        self.assertEqual(check.numbers("3,000,000 people in 1975", en), [3e6, 1975])
        self.assertEqual(sorted(check.numbers("1975年有300万人", zh)), [1975, 3e6])
        self.assertEqual(check.numbers("1.5 million", en), check.numbers("150万", zh))
        self.assertEqual(check.numbers("the 1980s and the '70s", en), [])  # decades are rewritten, not checked

    def test_term_case(self):
        rows = [{"source": "The Managerial Revolution"}, {"source": "accountability sink"}]
        self.assertEqual(check.term_hits(rows, "the managerial revolution. Accountability sinks"), [rows[1]])


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


if __name__ == "__main__":
    unittest.main()


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
        (d / "b.txt").write_text("Stafford Beer met Allende.\n\nBeer again.\n\nThe Costco store.", "utf-8")
        main(["init", str(d / "p"), "--source", str(d / "b.txt"), "--from", "en", "--to", "zh-Hans", "--no-git"])
        book = Book(d / "p")
        next_step(book)  # extract
        (d / "p" / "glossary.csv").write_text("source,target,status,forbidden\nCostco,开市客,approved,好市多\n")
        ids = list(book.original())
        texts = ["作家斯塔福德·比尔（Stafford Beer）见了阿连德（Salvador Allende Gossens of Chile）。",
                 "斯塔福·比尔（Stafford Beer）又来了。", "好市多商店。"]
        book.write_translation("ch01", {i: {"type": "p", "text": t, "meta": {"mt": h8(t)}} for i, t in zip(ids, texts)})
        codes = {(i["code"], i["level"]) for i in check.run(book)}
        self.assertIn(("name-variant", "warn"), codes)   # 斯塔福德·比尔 vs 斯塔福·比尔 (prefix 作家 ignored)
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
