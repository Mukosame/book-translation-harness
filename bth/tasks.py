"""Agent task protocol: plan -> claim -> (agent works) -> done. Any agent runtime that can run a shell
command and read/write files can act as a worker; the harness validates and merges every output."""
import csv
import io
import json
import os
import re
import shutil
import string
import subprocess
import sys
import time

from . import errata, figures
from .book import PKG, h8, parse_segments, dump_segments, tokens
from .check import GLOSSARY_COLUMNS, QUOTE_COLUMNS, glossary, quotes, structural, term_hits

PHASES = ["figures", "spec", "entities", "translate", "qa", "fix", "revise", "backtranslate"]
SEVERITIES = {"critical", "major", "minor"}
CATEGORIES = {"omission", "addition", "mistranslation", "negation", "number", "terminology", "logic", "fluency",
              "tone", "register", "gender", "pronoun", "punctuation", "locale", "structure", "source"}
STALE_CLAIM_S = 3600  # shortcut: fixed claim timeout; make configurable if workers run longer than an hour
BTH = shutil.which("bth") or f"{sys.executable} -m bth"  # same interpreter if bth is not on PATH
ENTITY_SCOPES = {"people": "people's names", "titles": "titles of books, articles, films, albums, periodicals",
                 "terms": "terms, organisations, places, events, projects",
                 "quotes": "direct quotations originally written in another language"}


def _is_quotes(t):
    """The entities task for quotations has its own prompt and output (quotes.csv)."""
    return t["phase"] == "entities" and t["ids"] == ["quotes"]


def _dir(book):
    d = book.work / "tasks"
    d.mkdir(parents=True, exist_ok=True)
    (book.work / "out").mkdir(exist_ok=True)
    return d


def load(book, tid):
    return json.loads((_dir(book) / f"{tid}.json").read_text("utf-8"))


def save(book, task):
    p = _dir(book) / f"{task['id']}.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(task, ensure_ascii=False, indent=1), "utf-8")
    os.replace(tmp, p)


def all_tasks(book, phase=None):
    ts = [json.loads(p.read_text("utf-8")) for p in sorted(_dir(book).glob("*.json"))]
    return [t for t in ts if phase in (None, t["phase"])]


def units(book, ids=None):
    """Consecutive segments packed up to the token budget; prefer breaking at chapter boundaries."""
    lo, hi = book.opt.get("unit_tokens", book.src_lang.get("segmentation", {}).get("unit_tokens", [1500, 2500]))
    out, cur, size, ch = [], [], 0, None
    for sid, s in book.original().items():
        if ids is not None and sid not in ids:
            continue
        t = tokens(s["text"])
        if cur and (size + t > hi or (s["chapter"] != ch and size >= lo / 2)):
            out.append(cur)
            cur, size = [], 0
        cur.append(sid)
        size += t
        ch = s["chapter"]
    return out + ([cur] if cur else [])


def plan(book, phase, ids=None, rnd=1, extra=None):
    """Create tasks for a phase (idempotent: existing task ids are kept). Returns new task ids."""
    assert phase in PHASES, phase
    existing = {t["id"] for t in all_tasks(book)}
    if phase == "spec":
        groups = [[]]
    elif phase == "entities":
        groups = [[k] for k in ENTITY_SCOPES]
    elif phase == "figures":
        groups = figures.groups(book)
    else:
        groups = units(book, set(ids) if ids is not None else None)
    new, extra, trans = [], extra or {}, book.translation()
    for i, g in enumerate(groups, 1):
        tid = f"{phase}-r{rnd}-{g[0] if phase == 'entities' else f'{i:03d}'}"
        if tid in existing:
            continue
        ex = {**extra, "issues": [x for x in extra.get("issues", []) if x["id"] in g]}
        if phase == "qa":
            ex["translated_by"] = sorted({trans[s]["meta"].get("by", "") for s in g if s in trans} - {""})
        save(book, {"id": tid, "phase": phase, "round": rnd, "status": "pending", "ids": g, "worker": None,
                    "claimed_at": None, "errors": [], "extra": ex})
        new.append(tid)
    return new


def claim(book, phase=None, worker=None):
    """Atomically take the next pending (or stale) task and render its prompt. Returns task or None."""
    with book.lock():
        now = time.time()
        for t in all_tasks(book, phase):
            stale = t["status"] == "claimed" and now - (t["claimed_at"] or 0) > STALE_CLAIM_S
            if t["status"] != "pending" and not stale:
                continue
            if worker and t["phase"] == "qa" and worker in t["extra"].get("translated_by", []):
                continue  # cross-check: QA never reviews its own translations
            t.update(status="claimed", worker=worker, claimed_at=now)
            save(book, t)
            prompt = render(book, t)
            (_dir(book) / f"{t['id']}.prompt.md").write_text(prompt, "utf-8")
            return {"task": t["id"], "phase": t["phase"], "prompt": str(_dir(book) / f"{t['id']}.prompt.md"),
                    "output": str(output_path(book, t))}
    return None


def output_path(book, t):
    if t["phase"] == "spec":
        return book.root
    ext = {"entities": "csv", "qa": "jsonl", "backtranslate": "jsonl", "figures": "jsonl"}.get(t["phase"], "md")
    return book.work / "out" / f"{t['id']}.{ext}"


def _block(segs):
    return dump_segments({k: {"type": v["type"], "text": v["text"]} for k, v in segs.items()})


def render(book, t):
    orig, trans = book.original(), book.translation()
    segs = {i: orig[i] for i in t["ids"] if i in orig}
    unit_src = " ".join(s["text"] for s in segs.values())
    rows = term_hits(glossary(book, approved_only=False), unit_src) if segs else []
    ids = list(orig)
    start = ids.index(t["ids"][0]) if segs else 0
    if segs:  # parallel workers can't see earlier units: tell them whether each name already occurred in the chapter
        ch = orig[t["ids"][0]]["chapter"]
        earlier = " ".join(orig[i]["text"] for i in ids[:start] if orig[i]["chapter"] == ch)
        rows = [{**r, "seen_earlier_in_chapter": "yes" if term_hits([r], earlier) else "no"} for r in rows]
    gl = io.StringIO()
    if rows:
        w = csv.DictWriter(gl, GLOSSARY_COLUMNS + ["seen_earlier_in_chapter"], extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    context = "\n".join(f"{i}\nSOURCE: {orig[i]['text']}\nTRANSLATION: {trans[i]['text'] if i in trans else '(not yet translated)'}"
                        for i in ids[max(start - 2, 0):start]) if segs else ""
    context = context or "(start of book)"
    qrows = [r for r in quotes(book) if r.get("id") in set(t["ids"])]
    qcsv = io.StringIO()
    if qrows:
        w = csv.DictWriter(qcsv, QUOTE_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(qrows)
    if _is_quotes(t) and not (book.work / "quotes.tsv").exists():  # projects extracted before quotes existed
        from .extract import quote_candidates
        quote_candidates(book)
    issues = t["extra"].get("issues", [])
    fig_keys = figures.figure_keys(book, t["ids"]) if t["phase"] == "qa" else []
    v = {
        "book": str(book.root), "task": t["id"], "phase": t["phase"], "output": str(output_path(book, t)),
        "lang_from": book.cfg["lang"]["from"], "lang_to": book.cfg["lang"]["to"],
        "locale": book.cfg["lang"].get("locale", book.cfg["lang"]["to"]),
        "lang_pack": str(PKG / "langs" / f"{book.tgt_lang['tag']}.toml"),
        "pair_profile": str(book.pair_profile or "(none for this pair)"),
        "style_guide": str(book.path("style_guide.md")), "glossary": str(book.path("glossary.csv")),
        "examples": str(book.path("examples.md")), "book_toml": str(book.path("book.toml")),
        "source_block": _block(segs), "chapter": orig[t["ids"][0]]["chapter"] if segs else "", "current_block": _block({i: trans[i] for i in t["ids"] if i in trans}),
        "glossary_rows": gl.getvalue() or "(no glossary entries occur in this unit)", "context": context,
        "issues": "\n".join(json.dumps(i, ensure_ascii=False) for i in issues) or "(none)",
        "terms": json.dumps(t["extra"].get("terms", []), ensure_ascii=False, indent=1),
        "chapters": "\n".join(f"- {c}: {len(book.original(c))} segments, first: "
                              f"{next(iter(book.original(c).values()))['text'][:80]}" for c in book.chapters()),
        "original_dir": str(book.path("original")), "scope": ENTITY_SCOPES.get((t["ids"] or [""])[0], ""),
        "candidates": str(book.work / "entities.tsv"), "columns": ",".join(GLOSSARY_COLUMNS),
        "entities_note": "The entities phase will verify `proposed` rows online." if book.opt.get("entities", True)
        else "Online verification is off for this project (`entities = false`): `proposed` rows go to the QA report "
             "for human review, so keep them few and specific.",
        "minor_note": "they are fixed too in this project (`fix_minor = true`); report them." if book.opt.get("fix_minor")
        else "they are not fixed automatically in this project (`fix_minor = false`); report one only if it clearly "
             "hurts readability, never as a matter of taste.",
        "figures": figures.prompt_list(book, t["ids"]) if t["phase"] == "figures" else "",
        "preview_cmd": f"{BTH} preview {book.root} --task {t['id']}",
        "figure_previews": "\n".join(f"    - `{p}`" for p in figures.preview(book, fig_keys)) or "    - (none)",
        "quote_rows": qcsv.getvalue() or "(no verified-quotation entries for this unit)",
        "quote_candidates": str(book.work / "quotes.tsv"), "quote_columns": ",".join(QUOTE_COLUMNS),
        "unverified_note": book.tgt_lang.get("quotes", {}).get("unverified_note", "").strip(),
        "source_errors_rule": errata.rule(book),
        "report_lang": book.opt.get("report_lang", "en"), "templates": str(PKG / "templates"), "done_cmd": f"{BTH} done {book.root} {t['id']}",
    }
    common = string.Template((PKG / "prompts" / "_common.md").read_text("utf-8")).safe_substitute(v)
    name = "quotes" if _is_quotes(t) else t["phase"]
    body = string.Template((PKG / "prompts" / f"{name}.md").read_text("utf-8")).safe_substitute(v)
    return body + "\n\n" + common


def _merge(book, t, segs, log_name=None):
    orig, trans = book.original(), book.translation()
    skipped, log = [], []
    by_ch = {}
    for sid, s in segs.items():
        old = trans.get(sid)
        if old and book.human_edited(old):
            skipped.append(sid)
            continue
        if log_name and old and old["text"] != s["text"]:
            log.append({"id": sid, "task": t["id"], "before": old["text"], "after": s["text"]})
        by_ch.setdefault(orig[sid]["chapter"], {})[sid] = {
            "type": orig[sid]["type"], "text": s["text"],
            "meta": {"src": h8(orig[sid]["text"]), "mt": h8(s["text"]), "by": t.get("worker") or "agent"}}
    for ch, new in by_ch.items():
        cur = {k: v for k, v in book.translation(ch).items()}
        cur.update(new)
        book.write_translation(ch, cur)
    if log:
        book.path("review").mkdir(exist_ok=True)
        with book.path("review", log_name).open("a", encoding="utf-8") as f:
            f.writelines(json.dumps(x, ensure_ascii=False) + "\n" for x in log)
    return skipped


def _append_jsonl(book, name, rows):
    book.path("review").mkdir(exist_ok=True)
    with book.path("review", name).open("a", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def _validate_glossary_csv(text):
    reader = csv.DictReader(io.StringIO(text))
    missing = {"source", "target"} - set(reader.fieldnames or [])
    if missing:
        return None, [f"glossary CSV lacks columns {sorted(missing)}; expected header: {','.join(GLOSSARY_COLUMNS)}"]
    rows = [r for r in reader if (r.get("source") or "").strip() and (r.get("target") or "").strip()]
    keys = [(r["source"].strip().lower(), (r.get("context") or "").strip()) for r in rows]
    dups = sorted({k[0] for k in keys if keys.count(k) > 1})
    if dups:
        return None, [f"duplicate glossary rows (same source and context): {dups[:10]}; merge them or add a context"]
    return rows, []


def _validate_quotes_csv(text, orig):
    reader = csv.DictReader(io.StringIO(text))
    missing = {"id", "quote", "status", "evidence"} - set(reader.fieldnames or [])
    if missing:
        return None, [f"quotes CSV lacks columns {sorted(missing)}; expected header: {','.join(QUOTE_COLUMNS)}"]
    rows, errors = list(reader), []
    for n, r in enumerate(rows, 2):
        if r.get("id") not in orig:
            errors.append(f"row {n}: id {r.get('id')!r} is not a segment id")
        if r.get("status") not in ("verified", "unverified"):
            errors.append(f"row {n}: status must be verified or unverified")
        elif r["status"] == "verified" and not (re.match(r"^https?://", r.get("evidence") or "") and r.get("original")):
            errors.append(f"row {n}: a verified quotation needs the original wording and an evidence URL")
    return rows, errors


def merge_quotes(book, rows):
    """quotes.csv keyed by (id, quote); verified rows are only replaced by verified rows."""
    p = book.path("quotes.csv")
    cur = list(csv.DictReader(io.StringIO(p.read_text("utf-8")))) if p.exists() else []
    index = {(r["id"], r["quote"]): r for r in cur}
    for r in rows:
        old = index.get((r["id"], r["quote"]))
        if old is None:
            cur.append(r)
            index[(r["id"], r["quote"])] = r
        elif old.get("status") != "verified" or r.get("status") == "verified":
            old.update({k: v for k, v in r.items() if v})
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, QUOTE_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(cur)


def merge_glossary(book, rows):
    p = book.path("glossary.csv")
    cur = list(csv.DictReader(io.StringIO(p.read_text("utf-8")))) if p.exists() else []
    key = lambda r: (r["source"].strip().lower(), (r.get("context") or "").strip())  # noqa: E731
    index = {key(r): r for r in cur}
    for r in rows:
        old = index.get(key(r))
        if old is None:
            cur.append(r)
            index[key(r)] = r
        elif old.get("status") != "approved" or r.get("status") == "approved":
            old.update({k: v for k, v in r.items() if v})  # approved rows only change with approved evidence
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, GLOSSARY_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(cur)


def done(book, tid):
    """Validate a worker's output and merge it. Returns {"ok", "errors", ...}; on errors the task stays claimed
    so the same worker can fix its output and call done again."""
    with book.lock():
        t = load(book, tid)
        if t["status"] == "done":
            return {"ok": True, "note": "already done"}
        out, errors, info = output_path(book, t), [], {}
        if t["phase"] == "spec":
            for f in ("style_guide.md", "glossary.csv", "examples.md"):
                if not book.path(f).exists() or not book.path(f).read_text("utf-8").strip():
                    errors.append(f"{f} missing or empty")
            if not errors:
                rows, errors = _validate_glossary_csv(book.path("glossary.csv").read_text("utf-8"))
                if rows is not None:
                    merge_glossary(book, [])  # normalise header/column order
        elif not out.exists():
            errors.append(f"output file not found: {out}")
        elif _is_quotes(t):
            rows, errors = _validate_quotes_csv(out.read_text("utf-8"), book.original())
            if not errors:
                merge_quotes(book, rows)
                info["rows"] = len(rows)
        elif t["phase"] == "entities":
            rows, errors = _validate_glossary_csv(out.read_text("utf-8"))
            if not errors:
                merge_glossary(book, rows)
                info["rows"] = len(rows)
        elif t["phase"] == "figures":
            rows = []
            for n, line in enumerate(out.read_text("utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    rows.append((n, json.loads(line)))
                except json.JSONDecodeError as e:
                    errors.append(f"line {n}: invalid JSON ({e})")
            errors += figures.validate(book, rows, t["ids"])
            if not errors:
                figures.merge(book, [r for _, r in rows])
                info["images"] = len(rows)
        elif t["phase"] in ("qa", "backtranslate"):
            rows = []
            for n, line in enumerate(out.read_text("utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError as e:
                    errors.append(f"line {n}: invalid JSON ({e})")
                    continue
                if r.get("id") not in t["ids"]:
                    errors.append(f"line {n}: id {r.get('id')!r} is not in this task")
                if t["phase"] == "qa" and (r.get("severity") not in SEVERITIES or r.get("category") not in CATEGORIES):
                    errors.append(f"line {n}: severity must be one of {sorted(SEVERITIES)}, category one of "
                                  f"{sorted(CATEGORIES)}")
                if t["phase"] == "backtranslate" and not r.get("text"):
                    errors.append(f"line {n}: missing text")
                rows.append({**r, "qid": f"{tid}-{n:03d}", "round": t["round"]})
            if not errors:
                _append_jsonl(book, f"qa_r{t['round']}.jsonl" if t["phase"] == "qa" else "backtranslation.jsonl",
                              rows)
                info["rows"] = len(rows)
        else:  # translate / fix / revise: segment files
            segs = parse_segments(out.read_text("utf-8"))
            orig = book.original()
            unknown = set(segs) - set(t["ids"])
            if unknown:
                errors.append(f"ids not in this task: {sorted(unknown)[:10]}")
            if t["phase"] == "translate":
                trans = book.translation()
                need = {i for i in t["ids"] if not (i in trans and book.human_edited(trans[i]))}
                if need - set(segs):
                    errors.append(f"missing segments: {sorted(need - set(segs))[:10]}")
            for sid, s in segs.items():
                if sid in orig:
                    errors += [f"{sid}: {p}" for p in structural(orig[sid]["text"], s["text"])]
            if not errors:
                log = None if t["phase"] == "translate" else f"{t['phase']}_r{t['round']}.jsonl"
                info["skipped_human_edited"] = _merge(book, t, {k: v for k, v in segs.items() if k in orig}, log)
        t["errors"] = errors
        if not errors:
            t["status"] = "done"
        save(book, t)
        return {"ok": not errors, "errors": errors, **info}


def changed_glossary_terms(book, since):
    """Glossary rows added/changed since a git revision (for `bth impact`)."""
    rel = book.path("glossary.csv").relative_to(book.root)
    r = subprocess.run(["git", "-C", str(book.root), "show", f"{since}:./{rel}"], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"git: {r.stderr.strip()}")
    old = {tuple(sorted(x.items())) for x in csv.DictReader(io.StringIO(r.stdout))}
    return [x for x in glossary(book, approved_only=False) if tuple(sorted(x.items())) not in old]


def impact_ids(book, terms):
    """Segments whose source contains any of the given terms."""
    pats = [re.compile(re.escape(x), re.I) for x in terms if x]
    return [sid for sid, s in book.original().items() if any(p.search(s["text"]) for p in pats)]
