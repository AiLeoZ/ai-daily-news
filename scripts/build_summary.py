#!/usr/bin/env python3
"""构建每日速览模式页：从 data/feed.json 的 summary 段生成 output/summary/$DATE.html。

速览页采用「统一总结」结构：
  - ## 摘要      ：一段连贯的概括性段落，点明当日 AI 行业整体趋势并涵盖 GitHub 榜单反映的开发者关注方向
  - ## 关键要点  ：条目式列表，每条一句话，覆盖重要新闻事件与 GitHub 趋势特征

说明：本脚本只负责「渲染」。真正的 AI 总结在每日流水线中由大模型对「完整页面内容
（新闻条目 + GitHub 榜单项目）」一次性生成并写入 feed.json。

重要约定：本脚本**仅当某日期在 feed.json 中确有 summary 段时才生成速览页**。
没有 summary 的历史日期一律跳过、不生成任何文件 —— 否则会在 output/summary/ 下留下
空兜底页，被 build.py 的资产索引误注册成速览入口，导致用户在历史日期看到空的「今日速览」。
（若某日 summary 段存在但 Markdown 渲染后为空，才会渲染同款样式的兜底卡片。）
feed.json 中每个日期是否有速览页，最终以 output/summary/$DATE.html 实际文件为准，
由 build.py 扫描写回 summaryHtml 字段供前端精确显隐。
"""
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
        return ""
    try:
        import markdown
        return markdown.markdown(md, extensions=["tables", "fenced_code", "sane_lists"])
    except Exception:
        esc = md.replace("`", "\\`").replace("${", "\\${")
        return (
            '<div class="md-raw" style="display:none">' + esc + "</div>"
            '<div class="md-out"></div>'
            '<script src="../../assets/marked.min.js"></script>'
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
    if title == "摘要":
        return "dot-ai"
    return "dot-gh"


def render_body(md):
    """把 summary Markdown 渲染为若干 section 块；无内容返回空串。"""
    if not md or not md.strip():
        return ""
    sections = split_summary_sections(md)
    body = ""
    for title, content in sections:
        if not content.strip():
            continue
        html = md_to_html(content)
        if not html.strip():
            continue
        body += f"""
    <section class="section">
      <div class="section-head">
        <span class="dot {dot_for(title)}"></span>
        <h2>{title}</h2>
      </div>
      <article class="content card">{html}</article>
    </section>
"""
    return body


def render_summary_html(date, md):
    body = render_body(md)
    if not body.strip():
        return render_fallback_html(date)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="doc-date" content="{date}" />
  <title>{SITE_TITLE} · 速览模式 · {fmt_date(date)}</title>
  <link rel="stylesheet" href="../../assets/style.css" />
</head>
<body data-date="{date}">
  <header class="site-header">
    <div class="header-inner">
      <div class="brand">
        <h1>{SITE_TITLE}</h1>
        <p class="subtitle">速览模式 · {fmt_date(date)}</p>
      </div>
      <div class="header-meta">
        <a class="summary-btn" href="../poster/{date}.png" target="_blank" style="text-decoration:none">🖼 今日海报</a>
        <a class="latest-btn" href="../archive/{date}.html" style="text-decoration:none">查看完整版</a>
        <a class="latest-btn" href="../../index.html" style="text-decoration:none">首页</a>
      </div>
    </div>
  </header>

  <main class="layout">
{body}
  </main>

  <section class="history">
    <div class="history-inner">
      <div class="history-head">
        <h3>想看更多细节？</h3>
      </div>
      <div class="history-bar">
        <a class="date-chip" style="text-decoration:none" href="../archive/{date}.html">查看 {fmt_date(date)} 完整版</a>
        <a class="date-chip" style="text-decoration:none" href="../../index.html">回到首页</a>
      </div>
    </div>
  </section>
</body>
</html>"""


def render_fallback_html(date):
    """内容为空 / AI 生成失败时的兜底页，样式与正常页一致。"""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="doc-date" content="{date}" />
  <title>{SITE_TITLE} · 速览模式 · {fmt_date(date)}</title>
  <link rel="stylesheet" href="../../assets/style.css" />
</head>
<body data-date="{date}">
  <header class="site-header">
    <div class="header-inner">
      <div class="brand">
        <h1>{SITE_TITLE}</h1>
        <p class="subtitle">速览模式 · {fmt_date(date)}</p>
      </div>
      <div class="header-meta">
        <a class="summary-btn" href="../poster/{date}.png" target="_blank" style="text-decoration:none">🖼 今日海报</a>
        <a class="latest-btn" href="../archive/{date}.html" style="text-decoration:none">查看完整版</a>
        <a class="latest-btn" href="../../index.html" style="text-decoration:none">首页</a>
      </div>
    </div>
  </header>

  <main class="layout">
    <section class="section">
      <div class="section-head">
        <span class="dot dot-ai"></span>
        <h2>今日速览</h2>
      </div>
      <article class="content card">
        <p class="loading">本日速览内容暂未生成（页面内容为空或 AI 总结未成功），请查看完整版了解当日全部 AI 新闻与 GitHub 榜单。</p>
      </article>
    </section>
  </main>

  <section class="history">
    <div class="history-inner">
      <div class="history-head">
        <h3>查看完整内容</h3>
      </div>
      <div class="history-bar">
        <a class="date-chip" style="text-decoration:none" href="../archive/{date}.html">查看 {fmt_date(date)} 完整版</a>
        <a class="date-chip" style="text-decoration:none" href="../../index.html">回到首页</a>
      </div>
    </div>
  </section>
</body>
</html>"""


def render_redirect_html(date):
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="refresh" content="0; url={date}.html" />
  <title>{SITE_TITLE} · 速览模式 · 最新</title>
</head>
<body>
  <p>正在跳转到最新速览模式… <a href="{date}.html">点击这里</a></p>
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
        if d not in entries:
            continue
        md = (entries[d].get("summary") or {}).get("markdown", "")
        # 仅当该日期确有真实 summary 内容时才生成页面。
        # 无 summary 的日期（如尚未生成速览的历史日）一律跳过，
        # 不生成兜底页 —— 否则会在 feed.json 中被误注册成速览入口，
        # 导致用户点开历史日期时看到空的「今日速览」。
        if not md or not md.strip():
            continue
        html = render_summary_html(d, md)
        with open(os.path.join(OUT, f"{d}.html"), "w", encoding="utf-8") as f:
            f.write(html)
        generated.append(d)

    if generated:
        latest = generated[0]
        with open(os.path.join(OUT, "latest.html"), "w", encoding="utf-8") as f:
            f.write(render_redirect_html(latest))
        print(f"已生成 {len(generated)} 个速览模式页 → output/summary/，最新：{latest}")
    else:
        print("未检测到任何含 summary 的日期，跳过生成（feed.json 中无 summary 段的日期不会生成速览页）")


if __name__ == "__main__":
    main()
