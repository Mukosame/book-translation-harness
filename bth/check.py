"""Deterministic checks (SOP 4.1). All language specifics come from the language packs."""
import collections
import csv
import io
import re
import statistics

from .book import PH, h8, placeholders, script_re

GLOSSARY_COLUMNS = ["source", "target", "target_forms", "type", "context", "forbidden", "locale",
                    "first_mention", "status", "evidence", "note"]


def glossary(book, approved_only=True):
    p = book.path("glossary.csv")
    if not p.exists():
        return []
    locale = book.cfg["lang"].get("locale", "")
    rows = list(csv.DictReader(io.StringIO(p.read_text("utf-8"))))
    return [r for r in rows if (not approved_only or r.get("status") == "approved")
            and (not r.get("locale") or r["locale"] == locale)]


def term_hits(rows, text):
    """Rows whose source occurs in text: case-sensitive for proper nouns (any capital), else case-insensitive."""
    low = text.lower()
    # shortcut: substring match (covers English plurals); add stemming for heavily inflected source languages
    return [r for r in rows if r["source"] and
            (r["source"] in text if r["source"] != r["source"].lower() else r["source"] in low)]


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
            for bad in filter(None, r.get("forbidden", "").split(";")):
                if bad in tgt:
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
