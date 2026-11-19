#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
slopcheck - AI 生成代码的交付前体检

单文件、零依赖、只读不写。
用法:
    python slopcheck.py .              扫当前目录
    python slopcheck.py demo --md      输出 Markdown 报告
    python slopcheck.py demo --json    机器可读

设计原则:
  1. 每条结论必须给出 文件:行 的证据, 不猜。
  2. 只检查"可客观验证"的东西: 残留、缺失、矛盾。
  3. 扣分封顶, 单一规则不主导总分。
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

VERSION = "0.3.0"

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "dist", "build", "out",
    "vendor", "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache",
    ".next", ".nuxt", "target", "coverage", "site-packages",
}

CODE_EXT = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt",
    ".swift", ".php", ".rb", ".cs", ".vue", ".svelte", ".c", ".cpp", ".h",
}
TEXT_EXT = CODE_EXT | {
    ".md", ".json", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".html",
    ".css", ".scss", ".sh", ".ps1", ".txt", ".sql",
}

MAX_BYTES = 1_500_000
MAX_LINES_PER_FILE = 20_000

SEVERITY_WEIGHT = {"critical": 12, "high": 6, "medium": 3, "low": 1}
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
SEVERITY_LABEL = {"critical": "严重", "high": "较高", "medium": "中等", "low": "提示"}

# 客户视角：这类问题交付后大约几天会被发现（不是精确科学，是经验刻度）
CLIENT_DAYS = {
    "secret": 1, "envcommit": 1, "placeholder": 1, "readmefake": 1, "pkgjson": 1,
    "fake": 3, "silent": 7, "nolock": 7, "noreadme": 7, "debug": 7, "dupfunc": 7,
    "nogitignore": 7, "localhost": 14, "debloat": 14,
    "notests": 30, "aicomment": 30, "todo": 30, "nolicense": 30,
    "giant": 30, "commentheavy": 30,
}

SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{20,}"
    r"|ghp_[A-Za-z0-9]{30,}"
    r"|github_pat_[A-Za-z0-9_]{30,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|xox[baprs]-[A-Za-z0-9\-]{10,}"
    r"|AIza[0-9A-Za-z_\-]{30,}"
    r"|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    r"|(?:password|passwd|secret|token|api[_-]?key)\s*[:=]\s*[\"'][^\"'\s]{8,}[\"'])"
)

PLACEHOLDER_RE = re.compile(
    r"(YOUR_[A-Z0-9_]{2,}|<your[-_ ]?[a-z0-9_ ]+>|CHANGE[_-]?ME|REPLACE[_-]?ME"
    r"|xxx{3,}|TODO[_-]?KEY|填入|在这里填|请替换)"
)

FAKE_DATA_RE = re.compile(
    r"(example\.com|@example\.(?:com|org|net)|lorem ipsum|张三|李四|王五"
    r"|13800138000|192\.168\.1\.1\b|1\.1\.1\.1\b)"
)

AI_COMMENT_RE = re.compile(
    r"(?:#|//|/\*)\s*(This (?:function|module|code|script)|Note that|Here we"
    r"|In this (?:example|case|script)|The following (?:code|function)"
    r"|We (?:then|now|will)|Let's)",
    re.IGNORECASE,
)

TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b")
DEBUG_PY_RE = re.compile(r"^\s*print\(")
DEBUG_JS_RE = re.compile(r"\bconsole\.(?:log|debug)\(")
SILENT_PY_RE = re.compile(r"^\s*except[^:]*:\s*(pass|continue)\s*$")
SILENT_JS_RE = re.compile(r"catch\s*(?:\([^)]*\))?\s*\{\s*\}")
DEF_PY_RE = re.compile(r"^\s*def\s+([A-Za-z_]\w*)\s*\(")
DEF_JS_RE = re.compile(r"(?:^|\s)(?:function\s+([A-Za-z_$][\w$]*)|const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\()")
LOCALHOST_RE = re.compile(r"localhost:\d{2,5}")


class Ctx:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.files = []      # list of dicts
        self.findings = {}   # id -> finding
        self.notes = []

    def f(self, fid, title, severity, advice):
        if fid not in self.findings:
            self.findings[fid] = {
                "id": fid, "title": title, "severity": severity,
                "advice": advice, "hits": [], "days": CLIENT_DAYS.get(fid, 7),
            }
        return self.findings[fid]

    def hit(self, fid, title, severity, advice, rel, line, snippet):
        item = self.f(fid, title, severity, advice)
        if len(item["hits"]) < 20:
            item["hits"].append({
                "file": rel, "line": line,
                "snippet": snippet.strip()[:160],
            })


SPECIAL_FILES = {
    ".env", ".env.example", ".gitignore", ".dockerignore",
    "Dockerfile", "Makefile", "LICENSE", "LICENCE", "NOTICE", "Procfile",
}


def iter_files(root, excludes=()):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".git")]
        for name in filenames:
            p = Path(dirpath) / name
            rel = str(p.relative_to(root)).replace("\\", "/")
            if any(x in rel for x in excludes):
                continue
            ext = p.suffix.lower()
            if ext not in TEXT_EXT and name not in SPECIAL_FILES:
                continue
            try:
                if p.stat().st_size > MAX_BYTES:
                    continue
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            lines = text.splitlines()
            if len(lines) > MAX_LINES_PER_FILE:
                lines = lines[:MAX_LINES_PER_FILE]
            yield {
                "path": p,
                "rel": rel,
                "ext": ext,
                "lines": lines,
                "text": "\n".join(lines),
                "is_test": bool(re.search(r"(^|/)(tests?|spec|__tests__)(/|$)|(_test|\.test|\.spec)\.", str(p).replace("\\", "/"))),
            }


def is_comment_line(ln):
    s = ln.lstrip()
    return s.startswith(("#", "//", "*", "/*"))


def is_pattern_line(ln):
    """规则定义行不该被自己的规则命中。"""
    s = ln.lstrip()
    return s.startswith(('r"', "r'", 'r"""')) or "re.compile" in ln


def check_secrets(ctx, f):
    # .env 里本来就该有密钥，单独由 envcommit 规则处理
    if f["is_test"] or f["ext"] == ".md" or Path(f["rel"]).name == ".env":
        return
    for i, ln in enumerate(f["lines"], 1):
        m = SECRET_RE.search(ln)
        if not m:
            continue
        token = m.group(0)
        # 文档/示例里的 sk-... 与 <your-key> 不算泄露
        if PLACEHOLDER_RE.search(ln) or "..." in token or "<" in token:
            continue
        ctx.hit("secret", "硬编码密钥/口令", "critical",
                "移到 .env 并加入 .gitignore；已经提交过的要轮换密钥，不是删掉就完事。",
                f["rel"], i, ln)


def check_placeholder(ctx, f):
    for i, ln in enumerate(f["lines"], 1):
        if is_pattern_line(ln) or is_comment_line(ln):
            continue
        if PLACEHOLDER_RE.search(ln):
            ctx.hit("placeholder", "占位符没填", "high",
                    "交付前全局搜一遍占位符；这类东西最容易被客户第一眼看到。",
                    f["rel"], i, ln)


def check_fake_data(ctx, f):
    if f["is_test"] or f["ext"] == ".md":
        return
    hits = 0
    for i, ln in enumerate(f["lines"], 1):
        if is_pattern_line(ln) or is_comment_line(ln):
            continue
        if FAKE_DATA_RE.search(ln):
            hits += 1
            if hits <= 3:
                ctx.hit("fake", "示例/假数据残留", "medium",
                        "把 demo 数据挪到 fixtures 或 seed 脚本，别留在业务代码里。",
                        f["rel"], i, ln)


def check_silent_except(ctx, f):
    for i, ln in enumerate(f["lines"], 1):
        if f["ext"] == ".py" and SILENT_PY_RE.match(ln):
            ctx.hit("silent", "静默吞异常", "high",
                    "至少记一条日志再走；线上出问题时这是唯一线索。",
                    f["rel"], i, ln)
        elif f["ext"] in {".js", ".ts", ".jsx", ".tsx"} and SILENT_JS_RE.search(ln):
            ctx.hit("silent", "静默吞异常", "high",
                    "catch 块里加日志或重新抛出；空 catch 会把故障藏成玄学。",
                    f["rel"], i, ln)


def check_debug(ctx, f):
    if f["is_test"] or f["ext"] == ".md":
        return
    n = 0
    first = None
    for i, ln in enumerate(f["lines"], 1):
        if (f["ext"] == ".py" and DEBUG_PY_RE.match(ln)) or \
           (f["ext"] in {".js", ".ts", ".jsx", ".tsx", ".vue"} and DEBUG_JS_RE.search(ln)):
            n += 1
            if first is None:
                first = (i, ln)
    if n >= 8:
        ctx.hit("debug", "调试输出残留", "medium",
                "换 logging/logger，按级别输出；交付前删掉临时打印。",
                f["rel"], first[0], "%s  (全文共 %d 处)" % (first[1].strip()[:100], n))


def check_todo(ctx, f):
    n = sum(1 for ln in f["lines"] if TODO_RE.search(ln))
    if n >= 5:
        i = next(i for i, ln in enumerate(f["lines"], 1) if TODO_RE.search(ln))
        ctx.hit("todo", "TODO/FIXME 堆积", "low",
                "要么做完，要么转成 issue；留在代码里等于没写。",
                f["rel"], i, "%s  (全文共 %d 处)" % (f["lines"][i - 1].strip()[:100], n))


def check_ai_comment(ctx, f):
    for i, ln in enumerate(f["lines"], 1):
        if AI_COMMENT_RE.search(ln):
            ctx.hit("aicomment", "AI 腔注释", "low",
                    "注释写“为什么”，别写“是什么”；这类句子人不会写。",
                    f["rel"], i, ln)


def check_dup_funcs(ctx, f):
    if f["ext"] not in {".py", ".js", ".ts", ".jsx", ".tsx"}:
        return
    seen = {}
    for i, ln in enumerate(f["lines"], 1):
        m = DEF_PY_RE.match(ln) if f["ext"] == ".py" else DEF_JS_RE.search(ln)
        if not m:
            continue
        name = m.group(1) or (m.lastindex and m.group(m.lastindex))
        if not name:
            continue
        if name in seen:
            ctx.hit("dupfunc", "同名函数重复定义", "medium",
                    "多半是复制粘贴留下的；合并成一个，否则后者静默覆盖前者。",
                    f["rel"], i, "%s  (首次出现在第 %d 行)" % (ln.strip()[:100], seen[name]))
        else:
            seen[name] = i


def check_giant_file(ctx, f):
    n = len(f["lines"])
    if n > 800:
        ctx.hit("giant", "单文件过长", "low",
                "按职责拆分；超过 800 行的文件几乎无法被 review。",
                f["rel"], 1, "%d 行" % n)


def check_comment_ratio(ctx, f):
    if f["ext"] not in CODE_EXT:
        return
    code = [ln for ln in f["lines"] if ln.strip()]
    if len(code) < 120:
        return
    comments = [ln for ln in code if ln.lstrip().startswith(("#", "//", "/*", "*"))]
    ratio = len(comments) / len(code)
    if ratio > 0.35:
        ctx.hit("commentheavy", "注释比例过高", "medium",
                "注释比代码还长通常是解释性废话；删掉“是什么”，留下“为什么”。",
                f["rel"], 1, "注释占比 %.0f%%，共 %d 行" % (ratio * 100, len(comments)))


def check_localhost(ctx, f):
    n = len(LOCALHOST_RE.findall(f["text"]))
    if n >= 4:
        i = next(i for i, ln in enumerate(f["lines"], 1) if LOCALHOST_RE.search(ln))
        ctx.hit("localhost", "本地地址硬编码", "medium",
                "抽成配置项，默认值可以写 localhost，但不能散落在业务代码里。",
                f["rel"], i, "全文 %d 处 localhost" % n)


def check_project_level(ctx, files):
    rels = {f["rel"] for f in files}
    names = {Path(r).name for r in rels}

    if not any(n.lower().startswith(("license", "licence", "copying")) for n in names):
        ctx.hit("nolicense", "缺少 LICENSE", "medium",
                "没有许可证等于默认保留全部权利，别人不敢用、公司不敢采。",
                "(项目根目录)", 0, "未找到 LICENSE / LICENSE.md")

    readme = next((f for f in files if f["rel"].lower() in {"readme.md", "readme.txt", "readme"} or
                   f["rel"].lower().startswith("readme.")), None)
    if readme is None:
        ctx.hit("noreadme", "缺少 README", "high",
                "README 是交付物的一部分，不是文档的附件。",
                "(项目根目录)", 0, "未找到 README")
    else:
        body = [ln for ln in readme["lines"] if ln.strip()]
        if len(body) < 12:
            ctx.hit("noreadme", "README 过短", "medium",
                    "至少写清：这是什么、怎么装、怎么跑、怎么用。",
                    readme["rel"], 1, "有效行数 %d" % len(body))

    has_pkg = "package.json" in names
    if has_pkg:
        if not any(n in names for n in {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb"}):
            ctx.hit("nolock", "锁文件缺失", "high",
                    "没有锁文件，别人的机器上装出来的依赖和你不是一套，故障无法复现。",
                    "package.json", 0, "未找到任何 lock 文件")
        try:
            pkg = json.loads(next(f for f in files if Path(f["rel"]).name == "package.json")["text"])
            deps = pkg.get("dependencies") or {}
            if len(deps) > 30:
                ctx.hit("debloat", "依赖过多", "medium",
                        "逐个问“能不能用标准库替代”；依赖是长期利息。",
                        "package.json", 0, "dependencies 共 %d 个" % len(deps))
        except (ValueError, StopIteration):
            ctx.hit("pkgjson", "package.json 无法解析", "critical",
                    "JSON 语法错误，装依赖会直接失败。", "package.json", 0, "parse error")

    if not any(f["is_test"] for f in files) and not any(
            n in names for n in {"pytest.ini", "tox.ini", "jest.config.js"}) and len(files) > 5:
        ctx.hit("notests", "没有任何测试", "high",
                "至少给核心逻辑写三个断言；没有测试的交付，改一行都心虚。",
                "(项目根目录)", 0, "未发现 tests/ 或 *.test.* / *_test.*")

    gi_file = next((f for f in files if Path(f["rel"]).name == ".gitignore"), None)
    gi_text = gi_file["text"] if gi_file else ""

    if any(n == ".env" for n in names) and ".env" not in gi_text:
        ctx.hit("envcommit", "密钥文件没被忽略", "critical",
                "加 .env 到 .gitignore；如果曾经提交过，直接轮换密钥，删文件没用。",
                ".env", 0, "存在 .env，但没有 .gitignore 规则覆盖它")

    if gi_file is None:
        ctx.hit("nogitignore", "缺少 .gitignore", "medium",
                "node_modules / .env / 构建产物会全部进库。",
                "(项目根目录)", 0, "未找到 .gitignore")


def check_readme_mismatch(ctx, files):
    readme = next((f for f in files if Path(f["rel"]).name.lower().startswith("readme")), None)
    if not readme:
        return
    # 只有 README 同目录存在 package.json 时才比对命令，避免拿纯文档仓库开刀
    rdir = readme["rel"].rsplit("/", 1)[0] if "/" in readme["rel"] else ""
    pkg_rel = (rdir + "/package.json") if rdir else "package.json"
    pkg = next((f for f in files if f["rel"] == pkg_rel), None)
    if pkg is None:
        return
    scripts = {}
    try:
        scripts = json.loads(pkg["text"]).get("scripts") or {}
    except ValueError:
        scripts = {}
    rels = {f["rel"] for f in files}

    for i, ln in enumerate(readme["lines"], 1):
        for m in re.finditer(r"npm run ([A-Za-z0-9:_\-]+)", ln):
            name = m.group(1)
            if scripts and name not in scripts:
                ctx.hit("readmefake", "README 里的命令跑不通", "high",
                        "README 抄下来第一次就报错的仓库，等于没写文档。",
                        readme["rel"], i, "npm run %s（package.json 里没有这个 script）" % name)
        for m in re.finditer(r"python3? ([A-Za-z0-9_./\-]+\.py)", ln):
            target = m.group(1).lstrip("./")
            if not any(r.endswith(target) for r in rels):
                ctx.hit("readmefake", "README 里的命令跑不通", "high",
                        "README 抄下来第一次就报错的仓库，等于没写文档。",
                        readme["rel"], i, "python %s（文件不存在）" % m.group(1))


def run(root, want_color=False, excludes=()):
    ctx = Ctx(root)
    files = list(iter_files(ctx.root, excludes))
    if not files:
        return {
            "score": 100, "grade": "S", "findings": [],
            "stats": {"root": str(ctx.root), "files": 0, "lines": 0,
                      "by_severity": {s: 0 for s in SEVERITY_ORDER}},
        }
    for f in files:
        check_secrets(ctx, f)
        check_placeholder(ctx, f)
        check_fake_data(ctx, f)
        check_silent_except(ctx, f)
        check_debug(ctx, f)
        check_todo(ctx, f)
        check_ai_comment(ctx, f)
        check_dup_funcs(ctx, f)
        check_giant_file(ctx, f)
        check_comment_ratio(ctx, f)
        check_localhost(ctx, f)
    check_project_level(ctx, files)
    check_readme_mismatch(ctx, files)

    findings = sorted(
        ctx.findings.values(),
        key=lambda x: (SEVERITY_ORDER[x["severity"]], -len(x["hits"])),
    )
    penalty = 0
    for f in findings:
        penalty += SEVERITY_WEIGHT[f["severity"]] * min(len(f["hits"]), 3)
    score = max(0, 100 - penalty)
    grade = "S" if score >= 90 else "A" if score >= 75 else "B" if score >= 60 else "C" if score >= 40 else "D"

    stats = {
        "root": str(ctx.root),
        "files": len(files),
        "lines": sum(len(f["lines"]) for f in files),
        "by_severity": {s: sum(1 for f in findings if f["severity"] == s) for s in SEVERITY_ORDER},
    }
    return {"score": score, "grade": grade, "findings": findings, "stats": stats}


# ---------------------------------------------------------------- 交付基线


def hit_fingerprint(fid, hit):
    raw = "%s|%s|%s" % (fid, hit["file"], re.sub(r"\s+", " ", hit["snippet"].lower()))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def collect_fingerprints(result):
    out = {}
    for f in result["findings"]:
        for h in f["hits"]:
            out[hit_fingerprint(f["id"], h)] = h["file"]
    return out


def save_baseline(result, path):
    data = {
        "tool": "slopcheck", "version": VERSION,
        "saved_at": datetime.date.today().isoformat(),
        "score": result["score"],
        "fingerprints": sorted(collect_fingerprints(result)),
    }
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def load_baseline(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def apply_baseline(result, base):
    """只保留基线之后新增的破绽：这才是"这次交付"该看的。"""
    cur = collect_fingerprints(result)
    old = set(base.get("fingerprints", []))
    fresh = {k for k in cur if k not in old}
    fixed = len(old - set(cur))
    kept = []
    for f in result["findings"]:
        f["hits"] = [h for h in f["hits"] if hit_fingerprint(f["id"], h) in fresh]
        if f["hits"]:
            kept.append(f)
    result["findings"] = kept
    result["baseline"] = {
        "new": len(fresh), "fixed": fixed,
        "score_before": base.get("score"), "score_after": result["score"],
    }
    return result


# ---------------------------------------------------------------- 安全修复

GITIGNORE_MIN = [".env", "__pycache__/", "*.pyc", "node_modules/", ".venv/"]


def plan_fixes(root):
    """只做零判断的修复：其余一律留给人。"""
    root = Path(root)
    acts = []

    gi = root / ".gitignore"
    if not gi.exists():
        acts.append(("create", gi, "\n".join(GITIGNORE_MIN) + "\n",
                     "新建 .gitignore"))
    else:
        text = gi.read_text(encoding="utf-8", errors="replace")
        missing = [x for x in GITIGNORE_MIN if x not in text]
        if missing:
            acts.append(("append", gi, "\n".join(missing) + "\n",
                         "补充 .gitignore 缺失规则: " + ", ".join(missing)))

    env = root / ".env"
    example = root / ".env.example"
    if env.exists() and not example.exists():
        out = []
        for ln in env.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in ln and not ln.lstrip().startswith("#"):
                out.append(ln.split("=", 1)[0] + "=")
            else:
                out.append(ln)
        acts.append(("create", example, "\n".join(out) + "\n",
                     "从 .env 生成 .env.example（值清空）"))
    return acts


def apply_fixes(acts):
    for op, path, content, _ in acts:
        mode = "a" if op == "append" else "w"
        with open(path, mode, encoding="utf-8") as fh:
            if op == "append":
                fh.write("\n")
            fh.write(content)


VERDICT = {
    "S": "干净得不像 AI 写的。可以交付。",
    "A": "基本能用，剩下的是细节卫生问题。",
    "B": "能跑，但一交付就会挨骂。先清前三条。",
    "C": "这是原型，不是交付物。",
    "D": "建议退回重做；这几条任何一条都会让客户失去信任。",
}


def render_text(r, color=False):
    def c(code, s):
        return "\033[%sm%s\033[0m" % (code, s) if color else s
    st = r["stats"]
    out = []
    out.append("")
    out.append(c("1", "slopcheck v%s  ·  AI 生成代码交付前体检" % VERSION))
    out.append("目录  %s" % st["root"])
    out.append("扫描  %d 个文本文件 / %d 行" % (st["files"], st["lines"]))
    out.append("")
    color = {"S": "32", "A": "32", "B": "33", "C": "31", "D": "31"}[r["grade"]]
    out.append("得分  %s / 100   等级 %s" % (c(color, str(r["score"])), c(color, r["grade"])))
    out.append("结论  %s" % VERDICT[r["grade"]])
    bl = r.get("baseline")
    if bl:
        out.append("基线  新增 %d 处 / 已修 %d 处 / 分数 %s -> %s" % (
            bl["new"], bl["fixed"], bl.get("score_before"), bl.get("score_after")))
    out.append("")
    if not r["findings"]:
        out.append("基线之后没有新增破绽。" if r.get("baseline") else "没有发现问题。")
        return "\n".join(out)
    for f in r["findings"]:
        head = "[%s] %s  (%d 处)" % (SEVERITY_LABEL[f["severity"]], f["title"], len(f["hits"]))
        out.append(head)
        for h in f["hits"][:3]:
            loc = "%s:%d" % (h["file"], h["line"]) if h["line"] else h["file"]
            out.append("    %-28s %s" % (loc, h["snippet"]))
        if len(f["hits"]) > 3:
            out.append("    ... 另有 %d 处" % (len(f["hits"]) - 3))
        out.append("    客户可见: 交付后约 %d 天" % f["days"])
        out.append("    建议: %s" % f["advice"])
        out.append("")
    return "\n".join(out)


def render_md(r):
    st = r["stats"]
    out = []
    out.append("# slopcheck 体检报告")
    out.append("")
    out.append("- 目录: `%s`" % st["root"])
    out.append("- 扫描: %d 个文本文件 / %d 行" % (st["files"], st["lines"]))
    out.append("- 得分: **%d / 100**（等级 %s）" % (r["score"], r["grade"]))
    out.append("- 结论: %s" % VERDICT[r["grade"]])
    bl = r.get("baseline")
    if bl:
        out.append("- 基线: 新增 %d 处 / 已修 %d 处 / 分数 %s -> %s" % (
            bl["new"], bl["fixed"], bl.get("score_before"), bl.get("score_after")))
    out.append("")
    if r["findings"]:
        out.append("| 等级 | 问题 | 处数 | 客户可见 | 建议 |")
        out.append("|---|---|---|---|---|")
        for f in r["findings"]:
            out.append("| %s | %s | %d | 约 %d 天 | %s |" % (
                SEVERITY_LABEL[f["severity"]], f["title"], len(f["hits"]), f["days"], f["advice"]))
        out.append("")
        out.append("## 证据")
        out.append("")
        for f in r["findings"]:
            out.append("### %s（%s）" % (f["title"], SEVERITY_LABEL[f["severity"]]))
            for h in f["hits"][:5]:
                loc = "%s:%d" % (h["file"], h["line"]) if h["line"] else h["file"]
                out.append("- `%s` — `%s`" % (loc, h["snippet"].replace("`", "'")))
            out.append("")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="AI 生成代码交付前体检")
    ap.add_argument("path", nargs="?", default=".", help="要扫描的目录")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--md", action="store_true", help="输出 Markdown")
    ap.add_argument("--color", action="store_true", help="彩色输出")
    ap.add_argument("--exclude", action="append", default=[], metavar="SUBSTR",
                    help="跳过路径中包含该字符串的文件，可重复")
    ap.add_argument("--baseline", nargs="?", const=".slopcheck-baseline.json", metavar="FILE",
                    help="只报基线之后新增的破绽（交付回归检测）")
    ap.add_argument("--save-baseline", nargs="?", const=".slopcheck-baseline.json", metavar="FILE",
                    help="把当前结果存为基线")
    ap.add_argument("--fix", action="store_true", help="列出可安全自动修复的项（默认只预演）")
    ap.add_argument("--apply", action="store_true", help="配合 --fix 真正写入")
    ap.add_argument("--version", action="version", version="slopcheck " + VERSION)
    args = ap.parse_args(argv)

    root = Path(args.path)
    if not root.exists():
        print("路径不存在: %s" % root)
        return 2

    result = run(root, args.color, args.exclude)

    if args.fix:
        acts = plan_fixes(root)
        if not acts:
            print("没有可以安全自动修复的项。")
        else:
            print("可安全修复 %d 项：" % len(acts))
            for op, path, _, desc in acts:
                print("  [%s] %s  %s" % (op, path, desc))
            if args.apply:
                apply_fixes(acts)
                print("已写入。其余问题需要人判断，工具不代劳。")
            else:
                print("以上是预演，加 --apply 才真正写入。")
        print("")

    if args.save_baseline:
        data = save_baseline(result, args.save_baseline)
        print("基线已保存到 %s（%d 条指纹，分数 %d）" % (
            args.save_baseline, len(data["fingerprints"]), data["score"]))
        return 0

    if args.baseline:
        base = load_baseline(args.baseline)
        if base is None:
            print("基线文件不存在或损坏: %s" % args.baseline)
            return 2
        result = apply_baseline(result, base)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.md:
        print(render_md(result))
    else:
        print(render_text(result, args.color))
    return 0


if __name__ == "__main__":
    sys.exit(main())
