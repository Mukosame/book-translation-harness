"""review/QA_REPORT.md: issue statistics, high-risk segments, stratified spot-check sample (SOP 4.4/4.5)."""
import collections
import json
import random

from . import check, figures

SAMPLE_RATE = {"high": 0.04, "medium": 0.09, "low": 0.15}


def _jsonl(path):
    return [json.loads(x) for x in path.read_text("utf-8").splitlines() if x.strip()] if path.exists() else []


def sample(book, rate):
    """Stratified by chapter, reproducible (seeded by book name)."""
    rng = random.Random(book.root.name)
    by_ch = collections.defaultdict(list)
    for sid, s in book.original().items():
        by_ch[s["chapter"]].append(sid)
    return [sid for ids in by_ch.values() for sid in rng.sample(ids, max(1, round(len(ids) * rate)))]


def run(book):
    review = book.path("review")
    review.mkdir(exist_ok=True)
    rounds = sorted(review.glob("qa_r*.jsonl"))
    issues = [i for p in rounds for i in _jsonl(p)]
    fixed = {(x["id"], int(p.stem.split("_r")[1])) for p in review.glob("fix_r*.jsonl") for x in _jsonl(p)}
    last = max((i["round"] for i in issues), default=0)
    checks = check.run(book)
    tier = book.tgt_lang.get("quality_tier", "high")
    risky = sorted({i["id"] for i in issues if i["severity"] == "critical"} |
                   {i["id"] for i in issues if i["round"] == last and i["severity"] == "major"
                    and (i["id"], last) not in fixed} |
                   {c["id"] for c in checks if c["level"] == "error" or c["code"] in ("length", "number")} - {"*"})
    picks = sample(book, SAMPLE_RATE.get(tier, 0.04))
    lines = [f"# QA report: {book.root.name} ({book.cfg['lang']['from']} → {book.cfg['lang']['to']})", "",
             f"Quality tier: **{tier}**; suggested human review: "
             f"{ {'high': 'spot-check the sample below', 'medium': 'review the high-risk segments and the sample', 'low': 'full read-through'}.get(tier, 'spot-check the sample below')}.",
             "", "## AI QA issues", "", "| round | severity | count | segment revised |", "|---|---|---|---|"]
    for (rnd, sev), n in sorted(collections.Counter((i["round"], i["severity"]) for i in issues).items()):
        nf = sum(1 for i in issues if i["round"] == rnd and i["severity"] == sev and (i["id"], rnd) in fixed)
        lines.append(f"| {rnd} | {sev} | {n} | {nf} |")
    lines += ["", "By category: " + ", ".join(f"{k} {v}" for k, v in
                                               collections.Counter(i["category"] for i in issues).most_common()),
              "", "## Deterministic checks", "",
              ", ".join(f"{k} {v}" for k, v in collections.Counter(
                  f"{c['level']}:{c['code']}" for c in checks).most_common()) or "clean",
              "", f"## High-risk segments ({len(risky)})", "", " ".join(f"`{x}`" for x in risky) or "none",
              "", f"## Spot-check sample ({len(picks)})", "", " ".join(f"`{x}`" for x in picks),
              "", "## Possible errors in the original", ""]
    lines += [f"- `{i['id']}`: {i.get('rationale', '')}" for i in issues if i.get("source_error")] or ["none reported"]
    lines += ["", "## Name variants", ""] + [f"- {c['msg']}" for c in checks if c["code"] == "name-variant"]
    proposed = [r for r in check.glossary(book, approved_only=False) if r.get("status") != "approved"]
    lines += ["", f"## Unverified glossary rows ({len(proposed)})", ""] + \
        [f"- {r['source']} → {r['target']} {('(' + r['note'] + ')') if r.get('note') else ''}" for r in proposed]
    lines += figures.report_lines(book)
    lines += ["", "Open `dist/bilingual.html#<id>` to review a segment side by side."]
    (review / "QA_REPORT.md").write_text("\n".join(lines) + "\n", "utf-8")
    return {"issues": len(issues), "high_risk": risky, "sample": len(picks),
            "check_errors": sum(c["level"] == "error" for c in checks)}
