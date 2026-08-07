#!/usr/bin/env python3
"""生成阶段：调用 LLM API，把采集到的素材写成三份原始 Markdown。

这一步是「AI 每日资讯」流水线中唯一需要大模型的环节。
在 WorkBuddy 本地自动化里由对话模型完成；在 GitHub Actions 等无人值守环境里由本脚本完成。

职责：
  - 读取 docs/generation-guide.md 作为唯一生成规范（system prompt）。
  - 读取 data/collected/rss_$DATE.json 与 gh_$DATE.json 作为事实素材。
  - 依次生成 data/raw/$DATE_ai.md、$DATE_github.md、$DATE_summary.md。
  - 输出结构自检；不合格时带着具体问题重试一次。

设计约束：
  - 纯标准库（urllib），与 collect.py 保持一致，云端无需 pip 装依赖。
  - API key 只从环境变量读取，绝不落盘、不写进仓库。
  - 任一 section 失败不影响已成功的 section（已写盘的文件保留）。

用法：
  export DEEPSEEK_API_KEY=sk-xxx
  python3 scripts/generate.py --date 2026-08-04
  python3 scripts/generate.py --date 2026-08-04 --section aiNews
  python3 scripts/generate.py --date 2026-08-04 --dry-run   # 只打印提示词不调用 API
"""
import argparse
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

COLLECTED = os.path.join(ROOT, "data", "collected")
RAW = os.path.join(ROOT, "data", "raw")
GUIDE = os.path.join(ROOT, "docs", "generation-guide.md")

SECTION_FILES = {
    "aiNews": "{date}_ai.md",
    "github": "{date}_github.md",
    "summary": "{date}_summary.md",
}

DEFAULT_LLM = {
    "provider": "deepseek",
    "base_url": "https://api.deepseek.com/chat/completions",
    "model": "deepseek-chat",
    "api_key_env": "DEEPSEEK_API_KEY",
    "temperature": 0.6,
    "max_tokens": 8000,
    "timeout": 300,
    "retries": 3,
}


# --------------------------------------------------------------------------
# 配置
# --------------------------------------------------------------------------
def load_llm_cfg():
    """从 config/runtime.yaml 读取 generate.llm，缺项用默认值补齐。"""
    cfg = dict(DEFAULT_LLM)
    try:
        from yamlutil import load_file
        rt = load_file(os.path.join(ROOT, "config", "runtime.yaml")) or {}
        llm = ((rt.get("generate") or {}).get("llm")) or {}
        for k, v in llm.items():
            if v not in (None, ""):
                cfg[k] = v
    except Exception as e:
        print(f"  [警告] 读取 runtime.yaml 失败，使用默认 LLM 配置：{e}")
    return cfg


def get_api_key(cfg):
    env = cfg.get("api_key_env") or "DEEPSEEK_API_KEY"
    key = os.environ.get(env, "").strip()
    if not key:
        # 兼容几个常见别名，方便本地调试
        for alt in ("DEEPSEEK_API_KEY", "LLM_API_KEY", "OPENAI_API_KEY"):
            key = os.environ.get(alt, "").strip()
            if key:
                print(f"  [提示] 使用环境变量 {alt}")
                break
    return key


# --------------------------------------------------------------------------
# 素材准备
# --------------------------------------------------------------------------
def read_guide():
    with open(GUIDE, "r", encoding="utf-8") as f:
        return f.read()


def load_json(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _parse_pubdate(s):
    """把 RSS 的 published 字段尽量归一化成 YYYY-MM-DD。"""
    if not s:
        return ""
    s = s.strip()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return m.group(0)
    months = {m: i for i, m in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
         "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
    m = re.search(r"(\d{1,2})\s+([A-Z][a-z]{2})\s+(\d{4})", s)
    if m:
        d, mon, y = int(m.group(1)), months.get(m.group(2)), int(m.group(3))
        if mon:
            return f"{y:04d}-{mon:02d}-{d:02d}"
    return ""


def load_digest_cfg():
    """素材分层配额。ArXiv 之类的预印本源条目极多，若不设配额会淹没产业新闻。"""
    cfg = {"industry_limit": 90, "academic_limit": 25,
           "academic_sources": ["arxiv", "paper", "预印本"]}
    try:
        from yamlutil import load_file
        rt = load_file(os.path.join(ROOT, "config", "runtime.yaml")) or {}
        d = ((rt.get("generate") or {}).get("digest")) or {}
        for k, v in d.items():
            if v not in (None, ""):
                cfg[k] = v
    except Exception:
        pass
    cfg["industry_limit"] = int(cfg["industry_limit"])
    cfg["academic_limit"] = int(cfg["academic_limit"])
    if isinstance(cfg["academic_sources"], str):
        cfg["academic_sources"] = [cfg["academic_sources"]]
    return cfg


def build_rss_digest(date, window_days=7):
    """把 RSS 候选压成紧凑清单：近 7 天、去重、按日期倒序、按来源分层配额。

    分两层输出：
      - 产业动态：TechCrunch / The Verge / 量子位 等，是选题主力，尽量全给模型看。
      - 学术前沿：ArXiv 等预印本源，条目基数极大，限量给出避免挤占版面。
    """
    data = load_json(os.path.join(COLLECTED, f"rss_{date}.json"))
    items = data.get("items") or []
    dcfg = load_digest_cfg()
    academic_kw = [s.lower() for s in dcfg["academic_sources"]]

    try:
        today = datetime.date.fromisoformat(date)
    except ValueError:
        today = datetime.date.today()
    earliest = today - datetime.timedelta(days=window_days - 1)

    seen, industry, academic = set(), [], []
    for it in items:
        title = (it.get("title") or "").strip()
        if not title:
            continue
        key = re.sub(r"\W+", "", title.lower())[:60]
        if key in seen:
            continue
        seen.add(key)
        pub = _parse_pubdate(it.get("published"))
        if pub:
            try:
                if not (earliest <= datetime.date.fromisoformat(pub) <= today):
                    continue
            except ValueError:
                pass
        source = (it.get("source") or "").strip()
        summary = re.sub(r"<[^>]+>", " ", it.get("summary") or "")
        summary = re.sub(r"\s+", " ", summary).strip()[:220]
        row = {
            "date": pub or "未标注",
            "source": source,
            "title": title,
            "summary": summary,
            "link": (it.get("link") or "").strip(),
        }
        if any(k in source.lower() for k in academic_kw):
            academic.append(row)
        else:
            industry.append(row)

    for bucket in (industry, academic):
        bucket.sort(key=lambda r: r["date"], reverse=True)
    industry = industry[:dcfg["industry_limit"]]
    academic = academic[:dcfg["academic_limit"]]

    def fmt(rows):
        return "\n".join(
            f"- [{r['date']}][{r['source']}] {r['title']}\n"
            f"  摘要：{r['summary']}\n  链接：{r['link']}"
            for r in rows
        )

    parts = []
    if industry:
        parts.append("### A 类 · 产业动态（选题主力，优先从这里挑）\n\n" + fmt(industry))
    if academic:
        parts.append("### B 类 · 学术前沿（仅在确有重大影响时才选，最多 1–2 条）\n\n"
                     + fmt(academic))
    return "\n\n".join(parts), len(industry) + len(academic)


def build_gh_digest(date):
    """把 GitHub Trending 抓取结果整理成结构化清单，供模型填注解。"""
    data = load_json(os.path.join(COLLECTED, f"gh_{date}.json"))

    def fmt(entries, kind):
        out = []
        for e in (entries or [])[:10]:
            desc = (e.get("description") or "").strip() or "暂无描述"
            base = (f"- 排名 {e.get('rank')} | {e.get('repo')} | {e.get('url')}\n"
                    f"  语言：{e.get('language') or '未知'} | 总 Star：{e.get('total_stars')}")
            if kind == "daily":
                base += f" | 今日新增：{e.get('gained')}"
            else:
                base += f" | 本周新增：{e.get('gained')}"
            base += f"\n  官方描述：{desc}"
            out.append(base)
        return "\n".join(out)

    daily = fmt(data.get("daily"), "daily")
    weekly = fmt(data.get("weekly"), "weekly")
    return daily, weekly, data


def week_range(date):
    d = datetime.date.fromisoformat(date)
    monday = d - datetime.timedelta(days=d.weekday())
    return f"{monday.isoformat()} ~ {d.isoformat()}"


# --------------------------------------------------------------------------
# LLM 调用
# --------------------------------------------------------------------------
def call_llm(cfg, api_key, system, user):
    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": float(cfg["temperature"]),
        "max_tokens": int(cfg["max_tokens"]),
        "stream": False,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        cfg["base_url"],
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    retries = int(cfg["retries"])
    last = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=int(cfg["timeout"])) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8")[:300]
            except Exception:
                pass
            last = f"HTTP {e.code} {detail}"
        except Exception as e:
            last = str(e)
        wait = min(2 ** attempt * 5, 60)
        print(f"  [重试 {attempt}/{retries}] {last}；{wait}s 后重试")
        if attempt < retries:
            time.sleep(wait)
    raise RuntimeError(f"LLM 调用失败：{last}")


def strip_fence(text):
    """去掉模型可能套上的 ```markdown 围栏。"""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*\n", "", t)
        t = re.sub(r"\n```\s*$", "", t)
    return t.strip()


# --------------------------------------------------------------------------
# 提示词
# --------------------------------------------------------------------------
SYSTEM_TMPL = """你是「AI 每日资讯」网站的内容编辑，负责按既定规范撰写每日中文资讯。

以下是本站唯一的内容生成规范，你必须严格遵守其中关于条数、分类、Markdown 结构、
标题格式、文风、注解写法的全部要求：

<generation_guide>
{guide}
</generation_guide>

铁律：
1. 所有事实、数字、项目名、日期、公司名只能来自用户消息中提供的素材，禁止编造。
   素材里没有的内容宁可不写，也不要凭印象补充。
2. 只输出 Markdown 正文本身，不要输出任何解释、前言、结语，也不要用 ``` 围栏包裹。
3. 全文使用简体中文。
"""

AI_TMPL = """请撰写 {date}（Asia/Shanghai）的「AI 新闻」板块。

## 素材：近 7 天 RSS 抓取结果（共 {count} 条候选，已按日期倒序）

{digest}

## 任务要求

- 从上述候选中筛选出 10 条最重要的 AI 领域动态（不足则 8–10 条）。
- 判断重要性时优先考虑：头部厂商模型发布与定价、重大融资与并购、监管与政策落地、
  有实际影响的技术突破、行业格局变化。纯学术预印本除非影响重大否则不选。
- 严格按规范分为「## 🔝 今日要闻」（日期 == {date}，1–4 条）与「## 近期其他要闻」
  （日期 < {date}，按时间倒序），序号从 1 连续编号。
- 每条必须包含：`### 序号. 标题（日期）`、事件说明段落、`- **为什么关注**：`、`- **注解**：`。
- 注解要写给完全不懂技术的读者看，可用生活化比喻或例子；禁止出现「通俗解释」四个字。
- 若候选中当天（{date}）的条目不足，可把当天最接近的重要动态归入今日要闻，但日期必须写素材里的真实日期。

现在直接输出完整 Markdown。"""

GH_TMPL = """请撰写 {date} 的「GitHub 趋势」板块。

## 素材：今日榜（真实抓取）

{daily}

## 素材：本周榜（真实抓取）

{weekly}

## 任务要求

- 严格输出两个分区：`## 一、今日榜（{date}）` 与 `## 二、本周榜（{wrange}）`。标题中不得出现 since= 字样。
- 今日榜表格列：排名、项目、今日新增 Star、注解，取前 10。
- 本周榜表格列：排名、项目、总 Star、本周新增、注解，取前 10。
- 项目列格式严格为：
  `[owner/repo](url)<br><span class="repo-desc">极简中文简介</span>`
  其中简介一句话讲清项目是干嘛的，必须与最右「注解」列内容不重复。
- 排名、项目名、Star 数字必须原样使用素材中的真实数值，一个都不能改。
- 注解用大白话多写几句，代入 IT 小白视角讲清「这东西能拿来干嘛、为什么火」，可用比喻。
  官方描述为「暂无描述」的项目，注解里如实说明信息有限，不要编造功能。
- 今日榜表格后加一行 `> 📊 今日榜看点：...`；本周榜表格后加一行 `> 🔍 趋势点评：...`。

现在直接输出完整 Markdown。"""

SUM_TMPL = """请为 {date} 撰写「每日资讯速览」。

以下是当日已定稿的两个板块全文，速览只能从中提炼，禁止引入任何新的事实、数字或项目。

<ai_news>
{ai}
</ai_news>

<github_trending>
{gh}
</github_trending>

## 任务要求

你是一名在语言理解和摘要生成方面训练有素的高级 AI。请阅读上述整个网页的内容并将其概括
为简洁的总结。目标是保留最重要的要点，提供连贯且易读的内容，使读者无需通读全文即可理解
讨论的主要内容。请避免不必要的细节或偏离主题的旁枝末节。

严格输出且仅输出两个分区：

## 摘要

（一段连贯的概括性段落，不分点。既点明当日 AI 行业整体趋势，也涵盖 GitHub 榜单反映出的
开发者关注方向。）

## 关键要点

- （每条一句话，6–10 条。覆盖重要新闻事件并保留关键数字与日期，同时覆盖 GitHub 日榜 /
  周榜的趋势特征。）

现在直接输出完整 Markdown。"""


# --------------------------------------------------------------------------
# AI 新闻 · 写盘前的日期排序兜底
# 背景：门禁 regression_check 要求 aiNews 所有 ### 标题的日期严格倒序，
# 但 LLM 偶尔不遵守（当日素材不足时会混排不同日期的旧闻），提示词无法 100% 约束。
# 此函数在写盘前按标题日期做全局倒序重排，保证 order 断言稳定通过。
# --------------------------------------------------------------------------
AI_DATE_RE = re.compile(r"（(\d{4}-\d{2}-\d{2}|\d+月\d+日)）")


def _ai_item_date(title, year):
    m = AI_DATE_RE.search(title)
    if not m:
        return None
    d = m.group(1)
    if re.match(r"\d{4}-\d{2}-\d{2}", d):
        return tuple(map(int, d.split("-")))
    mm = re.match(r"(\d+)月(\d+)日", d)
    if mm:
        return (year, int(mm.group(1)), int(mm.group(2)))
    return None


def normalize_ai_order(md, date):
    """把 aiNews 的 ### 条目按标题日期全局倒序重排。

    - 保持「## 🔝 今日要闻」在前、「## 近期其他要闻」在后，今日要闻沿用其原有条数。
    - 无日期条目不参与排序（门禁会跳过它们），保持原相对顺序放在末尾。
    - 条目序号从 1 重新连续编号。
    - 分区结构缺失时原样返回，交回门禁报错。
    """
    year = int(date.split("-")[0]) if date else None
    lines = md.splitlines(keepends=True)
    h_idx = [i for i, ln in enumerate(lines) if ln.strip().startswith("## 🔝 今日要闻")]
    r_idx = [i for i, ln in enumerate(lines) if ln.strip().startswith("## 近期其他要闻")]
    if not (h_idx and r_idx and r_idx[0] > h_idx[0]):
        return md
    hi, ri = h_idx[0], r_idx[0]

    def blocks(seg):
        out, cur = [], None
        for ln in seg:
            if ln.strip().startswith("### "):
                if cur:
                    out.append(cur)
                cur = [ln]
            elif cur is not None:
                cur.append(ln)
        if cur:
            out.append(cur)
        return out

    head_blocks = blocks(lines[hi + 1:ri])
    rest_blocks = blocks(lines[ri + 1:])

    def sort_b(bs):
        dated = [b for b in bs if _ai_item_date(b[0].strip(), year) is not None]
        undated = [b for b in bs if _ai_item_date(b[0].strip(), year) is None]
        dated.sort(key=lambda b: _ai_item_date(b[0].strip(), year), reverse=True)
        return dated + undated

    n_head = len(head_blocks)
    ordered = sort_b(head_blocks + rest_blocks)
    new_head, new_rest = ordered[:n_head], ordered[n_head:]

    def renum(bs, start):
        out, n = [], start
        for b in bs:
            new_first = re.sub(r"^\s*###\s+\d+[\.、]?\s*", "", b[0]).strip()
            out.append(f"### {n}. {new_first}\n")
            out.extend(b[1:])
            n += 1
        return out

    prefix = "".join(lines[:hi])
    head_title = "## 🔝 今日要闻\n"
    rest_title = "## 近期其他要闻\n"
    # 尾部仅保留「非条目块」的行（如末尾注释/空行），条目正文已由上面的块重建
    block_line_ids = set()
    for b in head_blocks + rest_blocks:
        block_line_ids.update(id(ln) for ln in b)
    tail_lines = []
    for ln in lines[ri + 1:]:
        if id(ln) not in block_line_ids:
            tail_lines.append(ln)
    tail = "".join(tail_lines)

    out = prefix + head_title + "\n" + "".join(renum(new_head, 1))
    if new_rest:
        out = out.rstrip("\n") + "\n\n" + rest_title + "\n" + "".join(renum(new_rest, n_head + 1))
    tail_stripped = tail.strip("\n")
    if tail_stripped:
        out = out.rstrip("\n") + "\n\n" + tail_stripped + "\n"
    return out


# --------------------------------------------------------------------------
# 自检
# --------------------------------------------------------------------------
def self_check(section, md, date):
    """复用 filter.py 的校验逻辑，返回问题列表。"""
    problems = []
    try:
        import filter as filter_mod
        ok, warns = filter_mod.validate(md, 10, section, date)
        if not ok:
            problems.extend(warns)
        else:
            # 只把结构性问题当作需要重试的硬伤
            for w in warns:
                if any(k in w for k in ("缺少", "repo-desc", "since=", "通俗解释", "为空", "过短", "时间序")):
                    problems.append(w)
    except Exception as e:
        print(f"  [提示] 自检模块加载失败，跳过结构校验：{e}")
    if section == "aiNews":
        n = len(re.findall(r"^###\s", md, re.M))
        if n < 8:
            problems.append(f"AI 新闻仅 {n} 条，少于 8 条下限")
    if section == "github":
        rows = len(re.findall(r"^\|\s*\d+\s*\|", md, re.M))
        if rows < 12:
            problems.append(f"表格数据行仅 {rows} 行，两榜合计应约 20 行")
    return problems


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def generate_section(section, date, cfg, api_key, guide, dry_run=False):
    system = SYSTEM_TMPL.format(guide=guide)

    if section == "aiNews":
        digest, count = build_rss_digest(date)
        if count == 0:
            print("  [错误] RSS 候选为空，无法生成 AI 新闻（请先运行 collect.py）")
            return False
        user = AI_TMPL.format(date=date, count=count, digest=digest)
    elif section == "github":
        daily, weekly, _ = build_gh_digest(date)
        if not daily and not weekly:
            print("  [错误] GitHub 抓取结果为空，无法生成趋势板块")
            return False
        user = GH_TMPL.format(date=date, daily=daily or "（今日榜抓取为空）",
                              weekly=weekly or "（本周榜抓取为空）", wrange=week_range(date))
    elif section == "summary":
        ai_path = os.path.join(RAW, f"{date}_ai.md")
        gh_path = os.path.join(RAW, f"{date}_github.md")
        if not (os.path.exists(ai_path) and os.path.exists(gh_path)):
            print("  [错误] 速览依赖当日 ai.md 与 github.md，请先生成这两块")
            return False
        with open(ai_path, encoding="utf-8") as f:
            ai_md = f.read()
        with open(gh_path, encoding="utf-8") as f:
            gh_md = f.read()
        user = SUM_TMPL.format(date=date, ai=ai_md, gh=gh_md)
    else:
        print(f"  [错误] 未知 section：{section}")
        return False

    if dry_run:
        print(f"\n===== [{section}] system {len(system)} 字 / user {len(user)} 字 =====")
        print(user[:2000])
        print("... （已截断）")
        return True

    md = strip_fence(call_llm(cfg, api_key, system, user))
    problems = self_check(section, md, date)

    if problems:
        print(f"  [自检未过] {'; '.join(problems)}")
        print("  [修正] 带着问题重试一次 ...")
        fix = (user + "\n\n## 上一版存在以下问题，请修正后重新输出完整 Markdown\n\n"
               + "\n".join(f"- {p}" for p in problems))
        md2 = strip_fence(call_llm(cfg, api_key, system, fix))
        p2 = self_check(section, md2, date)
        if len(p2) <= len(problems):
            md, problems = md2, p2
        if problems:
            print(f"  [警告] 修正后仍有：{'; '.join(problems)}（仍写盘，交由 filter.py 复核）")

    if section == "aiNews":
        norm = normalize_ai_order(md, date)
        if norm != md:
            print("  [排序兜底] 已按标题日期倒序重排 AI 新闻条目")
            md = norm

    os.makedirs(RAW, exist_ok=True)
    out = os.path.join(RAW, SECTION_FILES[section].format(date=date))
    with open(out, "w", encoding="utf-8") as f:
        f.write(md.rstrip() + "\n")
    print(f"  已写入 {os.path.relpath(out, ROOT)}（{len(md)} 字）")
    return True


def main():
    ap = argparse.ArgumentParser(description="调用 LLM 生成当日原始 Markdown")
    ap.add_argument("--date", default=None, help="日期 YYYY-MM-DD，默认 Asia/Shanghai 当天")
    ap.add_argument("--section", default="all",
                    choices=["all", "aiNews", "github", "summary"])
    ap.add_argument("--dry-run", action="store_true", help="只打印提示词，不调用 API")
    ap.add_argument("--force", action="store_true", help="已存在同日文件也覆盖重写")
    args = ap.parse_args()

    date = args.date
    if not date:
        os.environ["TZ"] = "Asia/Shanghai"
        try:
            time.tzset()
        except AttributeError:
            pass
        date = datetime.datetime.now().strftime("%Y-%m-%d")

    cfg = load_llm_cfg()
    api_key = ""
    if not args.dry_run:
        api_key = get_api_key(cfg)
        if not api_key:
            print(f"[错误] 未找到 API key，请设置环境变量 {cfg.get('api_key_env')}")
            return 2

    guide = read_guide()
    sections = ["aiNews", "github", "summary"] if args.section == "all" else [args.section]

    print(f"=== generate.py @ {date} · {cfg['provider']}/{cfg['model']} ===")
    failed = []
    for sec in sections:
        out = os.path.join(RAW, SECTION_FILES[sec].format(date=date))
        if os.path.exists(out) and not args.force and not args.dry_run:
            print(f"[{sec}] 已存在 {os.path.relpath(out, ROOT)}，跳过（--force 可覆盖）")
            continue
        print(f"[{sec}] 生成中 ...")
        try:
            if not generate_section(sec, date, cfg, api_key, guide, args.dry_run):
                failed.append(sec)
        except Exception as e:
            print(f"  [失败] {sec}：{e}")
            failed.append(sec)

    if failed:
        print(f"=== 完成，但以下板块失败：{', '.join(failed)} ===")
        return 1
    print("=== 全部生成完成 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
