"""Book project: config, language packs, segment files, locking. Everything else builds on this."""
import contextlib
import fcntl  # shortcut: POSIX-only file locking, add msvcrt fallback if Windows support is needed
import hashlib
import json
import re
import tomllib
from pathlib import Path

PKG = Path(__file__).parent
HEADER = re.compile(r"^<!-- (\S+) (\S+)((?: \S+)*) -->$", re.M)
PH = re.compile(r"\{\{(/?)(\d+|i)(/?)\}\}")  # {{i}}…{{/i}}: italics the target adds (title marks), not in source
SCRIPTS = {  # Unicode ranges per ISO 15924 script, enough for residue/punctuation checks
    "Latn": "A-Za-zÀ-ɏ", "Cyrl": "Ѐ-ӿ", "Grek": "Ͱ-Ͽ",
    "Arab": "؀-ۿ", "Hebr": "֐-׿", "Deva": "ऀ-ॿ", "Thai": "฀-๿",
    "Hani": "㐀-䶿一-鿿", "Jpan": "぀-ヿ㐀-䶿一-鿿",
    "Hang": "가-힯ᄀ-ᇿ",
}


def read_jsonl(path):
    return [json.loads(x) for x in path.read_text("utf-8").splitlines() if x.strip()] if path.exists() else []


def h8(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


def script_re(script):
    return re.compile(f"[{SCRIPTS[script]}]")


def tokens(text):
    # shortcut: rough estimate (CJK char ~1 token, else ~4 chars/token); use a real tokenizer if budgets get tight
    cjk = len(re.findall(f"[{SCRIPTS['Jpan']}{SCRIPTS['Hang']}]", text))
    return cjk + (len(text) - cjk) // 4 + 1


def placeholders(text):
    """Return (multiset list, nesting_ok) for {{n}}…{{/n}} / {{n/}} placeholders."""
    found, stack, ok = [], [], True
    for close, n, empty in PH.findall(text):
        if n != "i":  # target-added italics are optional, so only their nesting is checked
            found.append(f"{close}{n}{empty}")
        if empty:
            continue
        if close:
            ok = ok and bool(stack) and stack.pop() == n
        else:
            stack.append(n)
    return sorted(found), ok and not stack


def load_lang(tag):
    """Language pack for a BCP-47 tag, falling back zh-Hans-CN -> zh-Hans -> zh."""
    parts = tag.split("-")
    for i in range(len(parts), 0, -1):
        p = PKG / "langs" / ("-".join(parts[:i]) + ".toml")
        if p.exists():
            return tomllib.loads(p.read_text("utf-8"))
    raise SystemExit(f"no language pack for {tag!r}; create bth/langs/{tag}.toml (see docs/SOP.md, appendix E)")


def parse_segments(text):
    """Segment file -> {id: {"type", "text", "meta": {k: v}}} in file order."""
    out, heads = {}, list(HEADER.finditer(text))
    for i, m in enumerate(heads):
        body = text[m.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)].strip()
        meta = dict(kv.split("=", 1) if "=" in kv else (kv, True) for kv in m.group(3).split())
        out[m.group(1)] = {"type": m.group(2), "text": body, "meta": meta}
    return out


def dump_segments(segs):
    lines = []
    for sid, s in segs.items():
        meta = "".join(f" {k}" if v is True else f" {k}={v}" for k, v in s.get("meta", {}).items())
        lines.append(f"<!-- {sid} {s['type']}{meta} -->\n{s['text']}\n")
    return "\n".join(lines)


class Book:
    def __init__(self, root):
        self.root = Path(root).resolve()
        cfg = self.root / "book.toml"
        if not cfg.exists():
            raise SystemExit(f"{cfg} not found; run `bth init` first")
        self.cfg = tomllib.loads(cfg.read_text("utf-8"))
        self.opt = self.cfg.get("options", {})
        self.src_lang = load_lang(self.cfg["lang"]["from"])
        self.tgt_lang = load_lang(self.cfg["lang"]["to"])
        self.work = self.root / "work"

    def path(self, *parts):
        return self.root.joinpath(*parts)

    @property
    def pair_profile(self):
        p = PKG / "pairs" / f"{self.cfg['lang']['from']}__{self.cfg['lang']['to']}.md"
        return p if p.exists() else None

    def chapters(self):
        return sorted(p.stem for p in self.path("original").glob("*.md"))

    def original(self, ch=None):
        chs = [ch] if ch else self.chapters()
        out = {}
        for c in chs:
            for sid, s in parse_segments(self.path("original", f"{c}.md").read_text("utf-8")).items():
                out[sid] = {**s, "chapter": c}
        return out

    def translation(self, ch=None):
        out = {}
        for c in ([ch] if ch else self.chapters()):
            p = self.path("translation", f"{c}.md")
            if p.exists():
                for sid, s in parse_segments(p.read_text("utf-8")).items():
                    out[sid] = {**s, "chapter": c}
        return out

    @staticmethod
    def human_edited(seg):
        """Locked explicitly, or text changed since the machine wrote it (mt hash mismatch)."""
        m = seg["meta"]
        return m.get("locked") is True or ("mt" in m and m["mt"] != h8(seg["text"]))

    def write_translation(self, ch, segs):
        order = list(self.original(ch))
        self.path("translation").mkdir(exist_ok=True)
        ordered = {sid: segs[sid] for sid in order if sid in segs}
        self.path("translation", f"{ch}.md").write_text(dump_segments(ordered), "utf-8")

    @contextlib.contextmanager
    def lock(self):
        self.work.mkdir(exist_ok=True)
        with open(self.work / ".lock", "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            yield
