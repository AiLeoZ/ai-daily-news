#!/usr/bin/env python3
"""构建每日资讯速览页：从 data/feed.json 的 summary 段生成 output/summary/$DATE.html。"""
import datetime
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEED_PATH = os.path.join(ROOT, "data", "feed.json")
OUT = os.path.join(ROOT, "output", "summary")
os.makedirs(OUT, exist_ok=True)

try:
    from yamlutil import load_file
    _CFG = load_file(os.path.join(ROOT, "config", "site.yaml"))
except Exception:
    _CFG = {}
SITE_TITLE = _CFG.get("title", "AI 每日资讯")
SITE_SUB = _CFG.get("subtitle", "每天追踪最新 AI 动态与 GitHub 趋势")
CONTACT = _CFG.get("contact_email", "")


def md_to_html(md):
    if not md or not md.strip():
        return '<p class="loading">今日尚未生成速览</p>'
    try:
        import markdown
        return markdown.markdown(md, extensions=["tables", "fenced_code", "sane_lists"])
    except Exception:
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


def split_summary_sections(md):
    """把 summary Markdown 按二级标题拆成 (标题, 内容) 列表。"""
    parts = re.split(r"^## ", md, flags=re.M)
    sections = []
    for p in parts[1:]:
        lines = p.splitlines()
        title = lines[0].strip()
        content = "\n".join(lines[1:]).strip()
        sections.append((title, content))
    return sections


def dot_for(title):
    if "新闻" in title:
        return "dot-ai"
    return "dot-gh"


def render_summary_html(date, md):
    sections = split_summary_sections(md)
    section_html = ""
    for title, content in sections:
        html = md_to_html(content)
        section_html += f"""
    <section class="section">
      <div class="section-head">
        <span class="dot {dot_for(title)}"></span>
        <h2>{title}</h2>
      </div>
      <article class="content card">{html}</article>
    </section>
"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{SITE_TITLE} · 资讯速览 · {fmt_date(date)}</title>
  <link rel="stylesheet" href="../../assets/style.css" />
</head>
<body>
  <header class="site-header">
    <div class="header-inner">
      <div class="brand">
        <h1>{SITE_TITLE}</h1>
        <p class="subtitle">资讯速览 · {fmt_date(date)}</p>
      </div>
      <div class="header-meta">
        <a class="summary-btn" href="../poster/{date}.png" target="_blank" style="text-decoration:none">🖼 今日海报</a>
        <a class="latest-btn" href="../archive/{date}.html" style="text-decoration:none">查看完整版</a>
        <a class="latest-btn" href="../../index.html" style="text-decoration:none">首页</a>
      </div>
    </div>
  </header>

  <main class="layout">
{section_html}
  </main>

  <section class="history">
    <div class="history-inner">
      <div class="history-head">
        <h3>觉得太精简？</h3>
      </div>
      <div class="history-bar">
        <a class="date-chip" style="text-decoration:none" href="../archive/{date}.html">查看 {fmt_date(date)} 完整版</a>
        <a class="date-chip" style="text-decoration:none" href="../../index.html">回到首页</a>
      </div>
    </div>
  </section>

  <footer class="site-footer">
    <p>本页为 {fmt_date(date)} 的 AI 提炼精简版，由自动化流程每日生成。</p>
    {f'<p>联系：<a href="mailto:{CONTACT}">{CONTACT}</a></p>' if CONTACT else ''}
  </footer>
</body>
</html>"""


def render_redirect_html(date):
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="refresh" content="0; url={date}.html" />
  <title>{SITE_TITLE} · 资讯速览 · 最新</title>
</head>
<body>
  <p>正在跳转到最新资讯速览… <a href="{date}.html">点击这里</a></p>
</body>
</html>"""


def main():
    if not os.path.exists(FEED_PATH):
        print("feed.json 不存在，无法构建速览页")
        return
    with open(FEED_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    entries = data.get("entries", {})
    dates = sorted(entries.keys(), reverse=True)
    generated = []
    for d in dates:
        md = (entries[d].get("summary") or {}).get("markdown", "")
        if not md.strip():
            continue
        html = render_summary_html(d, md)
        with open(os.path.join(OUT, f"{d}.html"), "w", encoding="utf-8") as f:
            f.write(html)
        generated.append(d)

    if generated:
        latest = generated[0]
        with open(os.path.join(OUT, "latest.html"), "w", encoding="utf-8") as f:
            f.write(render_redirect_html(latest))
        print(f"已生成 {len(generated)} 个资讯速览页 → output/summary/，最新：{latest}")
    else:
        print("未检测到 summary 内容，跳过生成")


if __name__ == "__main__":
    main()
