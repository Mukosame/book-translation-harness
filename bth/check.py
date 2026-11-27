"""Deterministic checks (SOP 4.1). All language specifics come from the language packs."""
import collections
import csv
import io
import re
import statistics

from .book import PH, h8, placeholders, script_re, tokens

GLOSSARY_COLUMNS = ["source", "target", "target_forms", "type", "context", "forbidden", "locale",
                    "first_mention", "status", "evidence", "note"]
QUOTE_COLUMNS = ["id", "quote", "author", "work", "lang", "original", "use", "status", "evidence", "note"]
QUOTE_MIN_TOKENS = 8  # shorter quoted spans are phrases or scare quotes, not quotations
CONSISTENCY = ("inconsistent", "quote-variant", "title", "quote", "quote-unmarked")  # codes that join QA round 2


def glossary(book, approved_only=True):
    p = book.path("glossary.csv")
    if not p.exists():
        return []
    locale = book.cfg["lang"].get("locale", "")
    rows = list(csv.DictReader(io.StringIO(p.read_text("utf-8"))))
    return [r for r in rows if (not approved_only or r.get("status") == "approved")
            and (not r.get("locale") or r["locale"] == locale)]


def quotes(book):
    p = book.path("quotes.csv")
    return list(csv.DictReader(io.StringIO(p.read_text("utf-8")))) if p.exists() else []


def spans(text, marks, min_tokens=1):
    """Text between an opening and a closing mark (《…》, “…”), placeholders removed."""
    if len(marks) < 2 or any("{{" in m for m in marks[:2]):
        return []  # shortcut: titles marked by italics (placeholders) are not detected
    o, c = map(re.escape, marks[:2])
    return [m.strip() for m in re.findall(rf"{o}([^{o}{c}]+){c}", PH.sub("", text)) if tokens(m.strip()) >= min_tokens]


def title_spans(book, text):
    return spans(text, book.src_lang.get("titles", {}).get("works", []))


def quote_spans(book, text):
    return spans(text, book.src_lang.get("quotes", {}).get("primary", []), QUOTE_MIN_TOKENS)


def _norm(text):
    return re.sub(r"\s+", " ", PH.sub("", text)).strip()


def related(book, ids, issues=()):
    """Segments sharing a title, a quotation, or an issue's glossary term with any of ids (QA round 2 scope)."""
    orig = book.original()
    keys = {k for i in ids if i in orig for k in title_spans(book, orig[i]["text"]) + quote_spans(book, orig[i]["text"])}
    excerpts = " ".join(i.get("src", "") for i in issues)
    keys |= {r["source"] for r in term_hits(glossary(book, approved_only=False), excerpts)}
    return {sid for sid, s in orig.items() if any(k in PH.sub("", s["text"]) for k in keys)}


def consistency(book, orig, trans, add):
    """Repeated source text, repeated quotations and titles must be rendered the same way everywhere;
    verified quotations must use their established wording, unverified ones must be marked."""
    tl = book.tgt_lang
    groups = collections.defaultdict(list)
    for sid, s in orig.items():
        if sid in trans and len(_norm(s["text"])) >= 4:  # shorter repeats ("Note", "1") may differ by context
            groups[_norm(s["text"])].append(sid)
    for sids in groups.values():
        if len({_norm(trans[s]["text"]) for s in sids}) > 1:
            for s in sids:
                add(s, "warn", "inconsistent", f"same source as {[x for x in sids if x != s][:5]}, translated differently")
    rows = {r["source"]: r for r in glossary(book, approved_only=False)}
    tmarks = tl.get("quotes", {}).get("primary", [])
    for kind, find in (("quote-variant", quote_spans), ("title", title_spans)):
        where = collections.defaultdict(list)
        for sid, s in orig.items():
            for k in set(find(book, s["text"])):
                where[k].append(sid)
        for k, sids in where.items():
            done = [s for s in sids if s in trans]
            if kind == "quote-variant" and len(done) > 1:  # the quoted renderings must share at least one form
                if not set.intersection(*(set(spans(trans[s]["text"], tmarks)) for s in done)):
                    for s in done:
                        add(s, "warn", kind, f"quotation {k[:30]!r} also in {[x for x in done if x != s][:5]}, "
                                             "translated differently")
            elif kind == "title" and (r := rows.get(k)):
                forms = [r["target"]] + [f for f in r.get("target_forms", "").split(";") if f]
                for s in done:
                    if not any(f in _norm(trans[s]["text"]) for f in forms):
                        add(s, "warn", kind, f"title {k!r} should be rendered {r['target']!r} as everywhere else")
            elif kind == "title" and len(sids) > 1:
                add(sids[0], "warn", "title-unlisted",
                    f"title {k!r} occurs in {len(sids)} segments but has no glossary row; add one to keep it consistent")
    note = tl.get("quotes", {}).get("unverified_note", "")
    for r in quotes(book):
        sid = r.get("id")
        if sid not in trans:
            continue
        tgt = _norm(trans[sid]["text"])
        if r.get("status") == "verified" and r.get("use") and _norm(r["use"]) not in tgt:
            add(sid, "warn", "quote", f"verified quotation should read {r['use'][:60]!r}")
        elif r.get("status") != "verified" and note and note.strip() not in tgt:
            add(sid, "warn", "quote-unmarked", f"unverified quotation must carry {note.strip()!r}")


def term_hits(rows, text):
    """Rows whose source occurs in text: case-sensitive for proper nouns (any capital), else case-insensitive."""
    # Longest source wins: a source inside a longer matched one (马克 in 马克思) is not a separate hit.
    # shortcut: substring match (covers English plurals); add stemming for heavily inflected source languages
    hit = set()
    for src in sorted({r["source"] for r in rows if r["source"]}, key=len, reverse=True):
        flags = 0 if src != src.lower() else re.I
        if re.search(re.escape(src), text, flags):
            hit.add(src)
            text = re.sub(re.escape(src), "\0", text, flags=flags)
    return [r for r in rows if r["source"] in hit]


def structural(src, tgt):
    """Problems that block merging a translated segment."""
    if not tgt.strip():
        return ["empty translation"]
    sp, _ = placeholders(src)
    tp, nested = placeholders(tgt)
    out = []
    if sp != tp:
        lost = collections.Counter(sp) - collections.Counter(tp)
        extra = collections.Counter(tp) - collections.Counter(sp)
        out.append(f"placeholders differ: lost {sorted(lost.elements())} extra {sorted(extra.elements())}")
    elif not nested:
        out.append("placeholders crossed or unbalanced")
    if re.search(r"\{\s*\{|\}\s*\}", PH.sub("", tgt)):
        out.append("malformed placeholder")
    if re.search(r"^<!-- \S+ \S+.*-->$", tgt, re.M):
        out.append("segment header inside text")
    return out


def numbers(text, lang):
    """Numeric values in text, scaled by unit words (万/亿, million …) from the language pack."""
    nums = lang.get("numbers", {})
    dec, grp = nums.get("decimal_separator", "."), nums.get("group_separator", ",")
    units = {**nums.get("large_number_units", {}), **nums.get("scale_words", {})}
    unit_re = "|".join(map(re.escape, sorted(units, key=len, reverse=True)))
    pat = re.compile(rf"(\d[\d{re.escape(grp)}]*(?:{re.escape(dec)}\d+)?)\s*({unit_re})?" if unit_re else
                     rf"(\d[\d{re.escape(grp)}]*(?:{re.escape(dec)}\d+)?)()", re.I)
    out = []
    text = PH.sub(" ", text)
    for skip in nums.get("skip_patterns", []):  # e.g. decades ("1980s") that are legitimately rewritten
        text = re.sub(skip, " ", text)
    for num, unit in pat.findall(text):
        try:
            v = float(num.replace(grp, "").replace(dec, "."))
        except ValueError:
            continue
        mult = (units.get(unit) or units.get(unit.lower(), 1)) if unit else 1
        out.append(round(v * mult, 6))
    return out


def run(book, ids=None):
    """-> list of {id, level: error|warn, code, msg}"""
    orig, trans = book.original(), book.translation()
    sl, tl = book.src_lang, book.tgt_lang
    ids = ids or list(orig)
    issues = []
    add = lambda sid, level, code, msg: issues.append({"id": sid, "level": level, "code": code, "msg": msg})  # noqa
    rows = glossary(book)
    src_script = script_re(sl["script"]) if sl["script"] != tl["script"] else None
    max_run = tl.get("checks", {}).get("residue_max_run", 40)
    forbid_p = tl.get("punctuation", {}).get("forbidden_in_text", [])
    tgt_chars = script_re(tl["script"]).pattern.strip("[]")
    ratios = {}
    names = collections.defaultdict(set)
    pattern = tl.get("names", {}).get("first_mention_pattern", "")
    for sid in ids:
        if sid not in orig:
            add(sid, "error", "unknown-id", "id not in original/")
            continue
        src = orig[sid]["text"]
        if sid not in trans:
            add(sid, "error", "missing", "not translated")
            continue
        seg = trans[sid]
        tgt = seg["text"]
        if seg["meta"].get("src") and seg["meta"]["src"] != h8(src):
            add(sid, "warn", "stale", "source changed since translation")
        for p in structural(src, tgt):
            add(sid, "error", "structure", p)
        if tgt.strip() == src.strip():
            continue  # kept verbatim (bibliography, index locators): skip content checks
        plain = PH.sub("", tgt)
        if src_script:
            bare = plain
            if pattern:  # originals given in first-mention parentheses are intended, not residue
                left, right = pattern.split("{source}")[0][-1:], pattern.split("{source}")[1][:1]
                bare = re.sub(rf"{re.escape(left)}[^{re.escape(right)}]*{re.escape(right)}", "", plain)
            runs = [m.group(0) for m in re.finditer(rf"(?:{src_script.pattern}[\s\-'’.]*)+", bare)]
            longest = max((len(r) for r in runs), default=0)
            if longest > max_run:
                add(sid, "warn", "residue", f"untranslated run of {longest} chars: {max(runs, key=len)[:60]!r}")
        elif tl.get("checks", {}).get("residue") == "langid" and len(plain) > 40:
            try:
                from langdetect import detect  # optional: pip install langdetect
                if detect(plain) == sl["tag"].split("-")[0]:
                    add(sid, "warn", "residue", f"segment looks like {sl['name']}, not {tl['name']}")
            except Exception:  # missing package or undetectable text: skip silently, AI QA still covers it
                pass
        ratios[sid] = len(plain) / max(len(PH.sub("", src)), 1)
        missing = collections.Counter(numbers(src, sl)) - collections.Counter(numbers(tgt, tl))
        if missing:
            add(sid, "warn", "number", f"numbers not found in translation: {sorted(missing)[:6]}")
        for r in term_hits(rows, src):
            if r.get("context"):
                continue  # context-dependent senses are judged by AI QA
            forms = [r["target"]] + [f for f in r.get("target_forms", "").split(";") if f]
            if not any(re.search(f[3:], tgt) if f.startswith("re:") else f in tgt for f in forms):
                add(sid, "warn", "term", f"{r['source']!r} should be rendered {r['target']!r}")
            rest = tgt.replace(r["target"], "\0")  # a forbidden short form inside the full target is fine
            for bad in filter(None, r.get("forbidden", "").split(";")):
                if bad in rest:
                    add(sid, "error", "forbidden", f"{bad!r} is forbidden (use {r['target']!r})")
        for ch in forbid_p:
            if re.search(rf"[{tgt_chars}]{re.escape(ch)}|{re.escape(ch)}[{tgt_chars}]", plain):
                add(sid, "warn", "punctuation", f"{ch!r} next to {tl['name']} text")
        if tl.get("quotes", {}).get("straight_forbidden") and '"' in plain:
            add(sid, "warn", "quotes", 'straight " quote; use ' + "".join(tl["quotes"]["primary"]))
        if pattern:
            left, right = pattern.split("{target}")[1].split("{source}")
            sep = re.escape(tl.get("names", {}).get("separator", ""))
            for m in re.finditer(rf"([{tgt_chars}{sep}]+){re.escape(left)}([A-Z][^{re.escape(right)}]{{1,60}})"
                                 rf"{re.escape(right)}", plain):
                names[m.group(2).strip()].add(m.group(1))
    consistency(book, orig, {k: v for k, v in trans.items() if k in set(ids)}, add)
    if len(ratios) >= 20:  # per-book calibration of the expected length ratio
        mean, sd = statistics.mean(ratios.values()), statistics.pstdev(ratios.values()) or 1
        z = tl.get("checks", {}).get("length_warn_z", 2.5)
        for sid, r in ratios.items():
            if abs(r - mean) / sd > z and len(orig[sid]["text"]) > 80:
                add(sid, "warn", "length", f"length ratio {r:.2f} vs book mean {mean:.2f}")
    for source, variants in names.items():
        # captured runs may include leading words; variants that are suffixes of each other are the same name
        core = {v for v in variants if not any(o != v and v.endswith(o) for o in variants)}
        if len(core) > 1:
            add("*", "warn", "name-variant", f"{source}: {sorted(core)}")
    return issues
