"""bth: command-line entry point. `bth next <book>` is the only command an orchestrator needs to loop on."""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from . import build, check, errata, extract, figures, report, tasks
from .book import Book, h8, read_jsonl

BOOK_TOML = """\
title_src = {title_src}
title_tgt = ""          # filled in after the spec phase / by the user
author_src = ""
author_tgt = ""
source = {source}

[lang]
from = "{src}"
to = "{tgt}"
locale = "{locale}"     # regional variant for wording and official names (pt-BR, zh-Hans-CN, en-GB …)

[options]
workers = 10            # parallel agents per phase
qa_rounds = 2           # QA -> fix loops
fix_minor = false       # also fix minor issues
entities = true         # online verification of names/titles/terms before translating (needs web access)
figures = true          # transcribe and translate text inside images (needs agents that can view images)
source_errors = "fix-with-note"   # errors in the original (name, date, title, fact): keep | fix-obvious | fix-with-note
source_error_notes = "appendix"   # fix-with-note: a translator's errata page (appendix) or inline translator's notes
git_commit = true       # commit after each phase
report_lang = "en"      # language of QA reports
register = ""           # override the language pack's default register
reader_address = ""     # e.g. Sie / du, vous / tu
"""


def _out(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=1))


def _commit(book, msg):
    if not book.opt.get("git_commit", True) or not shutil.which("git"):
        return
    g = ["git", "-C", str(book.root)]
    if subprocess.run(g + ["rev-parse"], capture_output=True).returncode:
        return
    subprocess.run(g + ["add", "-A", "."], capture_output=True)
    subprocess.run(g + ["commit", "-q", "-m", msg], capture_output=True)


def _open(book, phase):
    ts = tasks.all_tasks(book, phase)
    return [t for t in ts if t["status"] == "pending"], [t for t in ts if t["status"] == "claimed"]


def _dispatch(book, phase, n_workers=None):
    pending, claimed = _open(book, phase)
    if not pending and not claimed:
        return None
    if not pending:
        return {"action": "wait", "phase": phase, "claimed": [t["id"] for t in claimed],
                "hint": "other workers are still running; call `bth next` again when they finish"}
    n = min(n_workers or book.opt.get("workers", 10), len(pending))
    return {"action": "dispatch", "phase": phase, "pending": len(pending), "workers": n,
            "worker_instructions": f"Start {n} agents in parallel. Each runs the worker loop in AGENTS.md with: "
                                   f"bth claim {book.root} --phase {phase} --worker <unique-name>"}


def _next_round(book, phase):
    return max((t["round"] for t in tasks.all_tasks(book, phase)), default=0) + 1


def next_step(book):
    """Advance the deterministic parts and return the next action for the orchestrator."""
    if not book.path("original").exists():
        info = extract.run(book)
        extract.entity_candidates(book)
        extract.quote_candidates(book)
        _commit(book, f"extract: {info['segments']} segments in {info['chapters']} chapters")
        if info["coverage"] < 0.98:
            return {"action": "attention", "step": "extract", **info,
                    "hint": "coverage below 98%: some text was not captured; inspect original/ before continuing"}
    if book.opt.get("figures", True):
        figures.scan(book)
        tasks.plan(book, "figures")
        step = _dispatch(book, "figures")
        if step:
            return step
    if not all(book.path(f).exists() for f in ("style_guide.md", "glossary.csv", "examples.md")) \
            or not all(t["status"] == "done" for t in tasks.all_tasks(book, "spec")):
        tasks.plan(book, "spec")
        return _dispatch(book, "spec", 1)
    if book.opt.get("entities", True):
        tasks.plan(book, "entities")
        step = _dispatch(book, "entities", 3)
        if step:
            return step
    orig, trans = book.original(), book.translation()
    if not trans:  # once only: later calls would sweep translations into a "spec" commit
        _commit(book, "spec: style guide, glossary, examples")
    need = [s for s in orig if s not in trans or
            (trans[s]["meta"].get("src") != h8(orig[s]["text"]) and not book.human_edited(trans[s]))]
    step = _dispatch(book, "translate")
    if step:
        return step
    if need:
        tasks.plan(book, "translate", need, _next_round(book, "translate"))
        return _dispatch(book, "translate")
    if not tasks.all_tasks(book, "qa"):  # shortcut: once QA starts, later re-translations land in the qa/build commits
        _commit(book, "translate: all segments translated")
    for phase in ("revise",):  # human-triggered glossary revisions (bth impact)
        step = _dispatch(book, phase)
        if step:
            return step
    sev = {"critical", "major"} | ({"minor"} if book.opt.get("fix_minor") else set())
    for rnd in range(1, book.opt.get("qa_rounds", 2) + 1):
        if not any(t["round"] == rnd for t in tasks.all_tasks(book, "qa")):
            if rnd == 1:
                ids = list(orig)
            else:  # revised segments, the segments sharing a title/quotation/term with them, consistency warnings
                prev = book.path("review", f"fix_r{rnd - 1}.jsonl")
                fixed = {r["id"] for r in read_jsonl(prev)}
                issues = read_jsonl(book.path("review", f"qa_r{rnd - 1}.jsonl"))
                ids = fixed | check.related(book, fixed, [i for i in issues if i["id"] in fixed])
                ids |= {i["id"] for i in check.run(book) if i["code"] in check.CONSISTENCY}
                ids = sorted(ids & set(orig))
            if not ids:
                break
            tasks.plan(book, "qa", ids, rnd)
        step = _dispatch(book, "qa")
        if step:
            return step
        qa = book.path("review", f"qa_r{rnd}.jsonl")
        issues = read_jsonl(qa)
        todo = [i for i in issues if i["severity"] in sev and not i.get("source_error")] + \
            errata.selected(issues, errata.policy(book))  # source errors follow the project policy, not severity
        if todo and not any(t["round"] == rnd for t in tasks.all_tasks(book, "fix")):
            tasks.plan(book, "fix", sorted({i["id"] for i in todo}), rnd, {"issues": todo})
        step = _dispatch(book, "fix")
        if step:
            return step
        _commit(book, f"qa: round {rnd}")
    info = report.run(book)
    if book.tgt_lang.get("quality_tier", "high") != "high" and info["high_risk"] \
            and not tasks.all_tasks(book, "backtranslate"):
        tasks.plan(book, "backtranslate", info["high_risk"])
    step = _dispatch(book, "backtranslate")
    if step:
        return step
    result = build.run(book)
    _commit(book, f"build: {Path(result['output']).name}")
    info["high_risk"] = len(info["high_risk"])
    return {"action": "done", **result, "qa": info, "report": str(book.path("review", "QA_REPORT.md"))}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="bth", description="Book translation harness (see AGENTS.md)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init", help="create a book project")
    p.add_argument("book")
    p.add_argument("--source", required=True)
    p.add_argument("--from", dest="src", required=True)
    p.add_argument("--to", dest="tgt", required=True)
    p.add_argument("--locale")
    p.add_argument("--no-git", action="store_true")
    for name, hlp in (("next", "advance the pipeline; prints the next action as JSON"),
                      ("status", "task and segment counts"), ("report", "write review/QA_REPORT.md"),
                      ("build", "build dist/*.epub and dist/bilingual.html")):
        sub.add_parser(name, help=hlp).add_argument("book")
    p = sub.add_parser("claim", help="take the next task (worker)")
    p.add_argument("book")
    p.add_argument("--phase", choices=tasks.PHASES)
    p.add_argument("--worker")
    p = sub.add_parser("done", help="validate and merge a task output (worker)")
    p.add_argument("book")
    p.add_argument("task")
    p = sub.add_parser("check", help="deterministic checks")
    p.add_argument("book")
    p.add_argument("--ids", nargs="*")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("plan", help="plan tasks manually, e.g. re-translate chapters after a style change")
    p.add_argument("book")
    p.add_argument("phase", choices=tasks.PHASES)
    p.add_argument("--ids", nargs="*")
    p.add_argument("--chapters", nargs="*")
    p = sub.add_parser("preview", help="render figure previews: label boxes of a task output, or translated overlays")
    p.add_argument("book")
    p.add_argument("--task", help="figures task whose (unmerged) output to draw; default: all translated overlays")
    p = sub.add_parser("impact", help="plan revisions for segments affected by glossary changes")
    p.add_argument("book")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--since", help="git revision to diff glossary.csv against")
    g.add_argument("--terms", nargs="+", help="source terms whose rendering changed")
    a = ap.parse_args(argv)

    if a.cmd == "init":
        root = Path(a.book)
        (root / "source").mkdir(parents=True, exist_ok=True)
        src = Path(a.source)
        shutil.copy(src, root / "source" / src.name)
        (root / "book.toml").write_text(BOOK_TOML.format(
            title_src=json.dumps(src.stem), source=json.dumps(f"source/{src.name}"), src=a.src, tgt=a.tgt,
            locale=a.locale or a.tgt), "utf-8")
        (root / ".gitignore").write_text("work/.lock\nwork/tasks/*.prompt.md\n", "utf-8")
        Book(root)  # validates language packs exist
        if not a.no_git and shutil.which("git") and subprocess.run(
                ["git", "-C", str(root), "rev-parse"], capture_output=True).returncode:
            subprocess.run(["git", "init", "-q", str(root)])
        return _out({"created": str(root.resolve()), "next": f"bth next {root}"})
    book = Book(a.book)
    if a.cmd == "next":
        _out(next_step(book))
    elif a.cmd == "claim":
        _out(tasks.claim(book, a.phase, a.worker) or {"task": None, "hint": "no work left in this phase; stop"})
    elif a.cmd == "done":
        r = tasks.done(book, a.task)
        _out(r)
        return 0 if r["ok"] else 1
    elif a.cmd == "check":
        issues = check.run(book, a.ids)
        if a.json:
            _out(issues)
        else:
            for i in issues:
                print(f"{i['level']:5} {i['code']:12} {i['id']}  {i['msg']}")
            print(f"{sum(i['level'] == 'error' for i in issues)} errors, "
                  f"{sum(i['level'] == 'warn' for i in issues)} warnings")
        return 1 if any(i["level"] == "error" for i in issues) else 0
    elif a.cmd == "status":
        ts = tasks.all_tasks(book)
        orig, trans = book.original() if book.path("original").exists() else {}, book.translation()
        counts = {}
        for t in ts:
            counts.setdefault(t["phase"], {}).setdefault(t["status"], 0)
            counts[t["phase"]][t["status"]] += 1
        _out({"segments": len(orig), "translated": len(trans),
              "human_edited": sum(book.human_edited(s) for s in trans.values()), "tasks": counts})
    elif a.cmd == "report":
        r = report.run(book)
        _out({**r, "high_risk": len(r["high_risk"]), "report": str(book.path("review", "QA_REPORT.md"))})
    elif a.cmd == "build":
        r = build.run(book)
        _out(r)
        return 1 if r["problems"] else 0
    elif a.cmd == "plan":
        ids = a.ids
        if a.chapters:
            ids = [s for c in a.chapters for s in book.original(c)]
        _out({"planned": tasks.plan(book, a.phase, ids, _next_round(book, a.phase))})
    elif a.cmd == "preview":
        if a.task:
            rows = read_jsonl(tasks.output_path(book, tasks.load(book, a.task)))
            _out({"previews": figures.preview(book, rows=rows)})
        else:
            _out({"previews": figures.preview(book, keys=list(figures.load(book)))})
    elif a.cmd == "impact":
        rows = tasks.changed_glossary_terms(book, a.since) if a.since else [{"source": t} for t in a.terms]
        ids = tasks.impact_ids(book, [r["source"] for r in rows])
        planned = tasks.plan(book, "revise", ids, _next_round(book, "revise"), {"terms": rows}) if ids else []
        _out({"terms": [r["source"] for r in rows], "segments": len(ids), "planned": planned,
              "next": f"bth next {book.root}"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
