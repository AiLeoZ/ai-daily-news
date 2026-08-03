#!/usr/bin/env python3
"""构建阶段：把 data/feed.json 渲染为静态网页产物（output/）。

产物：
  output/archive/YYYY-MM-DD.html  —— 每日独立静态页（预渲染、自包含内容，仅依赖共享 style.css）
  output/history.html             —— 历史索引，按日期倒序列出全部过往页面链接
  output/index.html               —— 静态首页，展示当日最新内容

预渲染策略：优先用 Python markdown 把 Markdown 转 HTML（产物为纯静态，
无需运行时 JS）；若环境无 markdown，则回退为内嵌原始 Markdown + marked.js CDN。

用法：
  python3 scripts/build.py                 # 全量构建
  python3 scripts/build.py --date 2026-08-03   # 仅校验该日期存在并构建
"""
import argparse
import datetime
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEED_PATH = os.path.join(ROOT, "data", "feed.json")
OUT = os.path.join(ROOT, "output")
ARCHIVE = os.path.join(OUT, "archive")
os.makedirs(ARCHIVE, exist_ok=True)

try:
    from yamlutil import load_file
    _CFG = load_file(os.path.join(ROOT, "config", "site.yaml"))
except Exception:
    _CFG = {}
SITE_TITLE = _CFG.get("title", "AI 每日资讯")
SITE_SUB = _CFG.get("subtitle", "每天追踪最新 AI 动态与 GitHub 趋势")
CONTACT = _CFG.get("contact_email", "")
SECTION_TITLES = _CFG.get("section_titles", {}) or {"aiNews": "AI 新闻", "github": "GitHub 趋势"}


def md_to_html(md):
    if not md or not md.strip():
        return '<p class="loading">今日尚未更新</p>'
    try:
        import markdown
        return markdown.markdown(md, extensions=["tables", "fenced_code", "sane_lists"])
    except Exception:
        # 回退：内嵌原始 Markdown，运行时用 marked 渲染
        esc = md.replace("`", "\\`").replace("${", "\\${")
        return (
            '<div class="md-raw" style="display:none">' + esc + "</div>"
            '<div class="md-out"></div>'
            '<script src="https://cdn.jsdelivr.net/npm/marked@12/marked.min.js"></script>'
            "<script>document.querySelector('.md-out').innerHTML="
            "marked.parse(document.querySelector('.md-raw').textContent);</script>"
        )


def fmt_date(d):
    y, m, day = d.split("-")
    return f"{y}年{int(m)}月{int(day)}日"


def count_items(md):
    return len(re.findall(r"^###\s", md or "", re.M))


def render_day_html(date, entry, asset_rel):
    """生成单日完整 HTML 文档。asset_rel 为到 assets/style.css 的相对路径。"""
    ai = (entry.get("aiNews") or {}).get("markdown", "")
    gh = (entry.get("github") or {}).get("markdown", "")
    ai_time = (entry.get("aiNews") or {}).get("generatedAt", "")
    gh_time = (entry.get("github") or {}).get("generatedAt", "")

    def fmt_time(iso):
        if not iso:
            return "暂无"
        t = datetime.datetime.fromisoformat(iso)
        return f"更新于 {t.year}-{t.month:02d}-{t.day:02d} {t.hour:02d}:{t.minute:02d}"

    ai_html = md_to_html(ai)
    gh_html = md_to_html(gh)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{SITE_TITLE} · {fmt_date(date)}</title>
  <link rel="stylesheet" href="{asset_rel}assets/style.css" />
</head>
<body>
  <header class="site-header">
    <div class="header-inner">
      <div class="brand">
        <h1>{SITE_TITLE}</h1>
        <p class="subtitle">{SITE_SUB}</p>
      </div>
      <div class="header-meta">
        <span class="viewing-date">{fmt_date(date)}</span>
        <a class="latest-btn" href="{asset_rel}../index.html" style="text-decoration:none">首页</a>
      </div>
    </div>
  </header>

  <main class="layout">
    <section class="section" id="section-ai">
      <div class="section-head">
        <span class="dot dot-ai"></span>
        <h2>{SECTION_TITLES.get('aiNews', 'AI 新闻')}</h2>
        <span class="gen-time">{fmt_time(ai_time)}</span>
      </div>
      <article id="ai-content" class="content card">{ai_html}</article>
    </section>

    <section class="section" id="section-gh">
      <div class="section-head">
        <span class="dot dot-gh"></span>
        <h2>{SECTION_TITLES.get('github', 'GitHub 趋势')}</h2>
        <span class="gen-time">{fmt_time(gh_time)}</span>
      </div>
      <article id="gh-content" class="content card">{gh_html}</article>
    </section>
  </main>

  <section class="history">
    <div class="history-inner">
      <div class="history-head">
        <h3>历史归档</h3>
        <a class="history-select" style="text-decoration:none" href="{asset_rel}history.html">查看全部日期 →</a>
      </div>
      <div class="history-bar">
        <a class="date-chip" style="text-decoration:none" href="{asset_rel}../index.html">最新一日</a>
        <a class="date-chip" style="text-decoration:none" href="{asset_rel}history.html">历史索引</a>
      </div>
    </div>
  </section>

  <footer class="site-footer">
    <p>本页为 {fmt_date(date)} 的独立归档，由自动化流程每日生成。</p>
    {f'<p>联系：<a href="mailto:{CONTACT}">{CONTACT}</a></p>' if CONTACT else ''}
  </footer>
</body>
</html>"""


def render_history_html(dates):
    cards = []
    for d in dates:
        cards.append(
            f'    <a class="date-chip" style="text-decoration:none" href="archive/{d}.html">{fmt_date(d)}</a>'
        )
    chips = "\n".join(cards)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{SITE_TITLE} · 历史归档</title>
  <link rel="stylesheet" href="assets/style.css" />
</head>
<body>
  <header class="site-header">
    <div class="header-inner">
      <div class="brand">
        <h1>{SITE_TITLE}</h1>
        <p class="subtitle">历史归档 · 共 {len(dates)} 天</p>
      </div>
      <div class="header-meta">
        <a class="latest-btn" href="index.html" style="text-decoration:none">← 回到最新</a>
      </div>
    </div>
  </header>

  <section class="history">
    <div class="history-inner">
      <div class="history-head">
        <h3>按日期浏览（倒序）</h3>
      </div>
      <div class="history-bar">
{chips}
      </div>
    </div>
  </section>

  <footer class="site-footer">
    <p>每日独立归档页，按日期倒序排列。点击任意日期查看当日完整内容。</p>
    {f'<p>联系：<a href="mailto:{CONTACT}">{CONTACT}</a></p>' if CONTACT else ''}
  </footer>
</body>
</html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="仅校验该日期存在")
    args = ap.parse_args()

    if not os.path.exists(FEED_PATH):
        print("feed.json 不存在，无法构建")
        return
    with open(FEED_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    entries = data.get("entries", {})
    dates = sorted(entries.keys(), reverse=True)
    if args.date and args.date not in entries:
        print(f"指定日期 {args.date} 不在 feed.json 中")
        return

    # 1) 每日独立归档页
    for d in dates:
        html = render_day_html(d, entries[d], "../../")
        with open(os.path.join(ARCHIVE, f"{d}.html"), "w", encoding="utf-8") as f:
            f.write(html)
    print(f"已生成 {len(dates)} 个每日归档页 → output/archive/")

    # 2) 历史索引
    with open(os.path.join(OUT, "history.html"), "w", encoding="utf-8") as f:
        f.write(render_history_html(dates))
    print("已生成 output/history.html")

    # 3) 静态首页（当日最新）
    latest = dates[0]
    with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as f:
        f.write(render_day_html(latest, entries[latest], "../"))
    print(f"已生成 output/index.html（最新：{latest}）")
    print("构建完成。")


if __name__ == "__main__":
    main()
