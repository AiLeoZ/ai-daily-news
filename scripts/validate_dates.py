#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日期 1:1 校验：确保每个日期的「速览文本 + 海报」严格按日期一一匹配，杜绝错配/串用。

校验项：
  1. feed.json 中每个日期键，若含 summary / poster，则其产物文件名日期必须与日期键一致；
  2. 每个速览页 HTML（output/summary/$DATE.html）必须内嵌
       <meta name="doc-date" content="$DATE"> 且 <body data-date="$DATE">，
     且内嵌日期 == 文件名日期 == feed 日期键（三者一致）；
  3. 每个海报 PNG（output/poster/$DATE.png）文件名日期必须与 feed 日期键一致；
  4. 若某日期在 feed 中有 summary 段却找不到对应 HTML 文件，或反之，判为错配。

任何不匹配都以非零退出码中止，防止把错误日期的内容发布/部署出去。

用法：
  python3 scripts/validate_dates.py
  python3 scripts/validate_dates.py --date 2026-08-03   # 仅校验单日
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEED_PATH = os.path.join(ROOT, "data", "feed.json")
SUMMARY_DIR = os.path.join(ROOT, "output", "summary")
POSTER_DIR = os.path.join(ROOT, "output", "poster")


def date_from_path(path, prefix, ext):
    """从 'output/summary/2026-08-03.html' 这类路径的文件名里提取 YYYY-MM-DD。"""
    base = os.path.basename(path)
    m = re.search(r"(\d{4}-\d{2}-\d{2})", base)
    return m.group(1) if m else None


def html_embedded_date(html_path):
    """读取速览 HTML，返回 (meta_doc_date, body_data_date)；文件不存在返回 (None, None)。"""
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()
    except FileNotFoundError:
        return (None, None)
    m = re.search(r'<meta\s+name="doc-date"\s+content="([^"]+)"', html)
    b = re.search(r"<body[^>]*\bdata-date=\"([^\"]+)\"", html)
    return (m.group(1) if m else None, b.group(1) if b else None)


def validate_date(date, entry, errors, checks):
    # ---- 1) summary 速览文本 ↔ 速览页 HTML ----
    summary_md = (entry.get("summary") or {}).get("markdown", "")
    has_summary = bool(summary_md and summary_md.strip())
    summary_html_field = entry.get("summaryHtml", "")
    html_path = os.path.join(SUMMARY_DIR, f"{date}.html")

    if has_summary:
        # 有内容就必须有 HTML 文件
        if not os.path.exists(html_path):
            errors.append(f"[{date}] 有 summary 内容但缺少速览页文件 {html_path}")
        else:
            meta_d, body_d = html_embedded_date(html_path)
            checks.append(f"[{date}] 速览页存在 ✓")
            if meta_d != date:
                errors.append(f"[{date}] 速览页 <meta doc-date>='{meta_d}' 与日期键 '{date}' 不一致")
            if body_d != date:
                errors.append(f"[{date}] 速览页 <body data-date>='{body_d}' 与日期键 '{date}' 不一致")
            if meta_d == date and body_d == date:
                checks.append(f"[{date}] 速览页内嵌日期与文件名、日期键一致 ✓")
        # feed.summaryHtml 路径也应指向该日期文件
        if summary_html_field:
            fd = date_from_path(summary_html_field, "output/summary/", ".html")
            if fd != date:
                errors.append(f"[{date}] feed.summaryHtml='{summary_html_field}' 文件名日期 '{fd}' ≠ 日期键")
    else:
        if os.path.exists(html_path):
            errors.append(f"[{date}] 无 summary 内容却存在速览页 {html_path}（疑似串用/残留）")
        if summary_html_field:
            errors.append(f"[{date}] feed.summaryHtml 指向 {summary_html_field} 但无 summary 内容")

    # ---- 2) poster 海报 ↔ 文件名日期 ----
    poster_field = entry.get("poster", "")
    poster_path = os.path.join(POSTER_DIR, f"{date}.png")
    if poster_field:
        pd = date_from_path(poster_field, "output/poster/", ".png")
        if pd != date:
            errors.append(f"[{date}] feed.poster='{poster_field}' 文件名日期 '{pd}' ≠ 日期键")
        if not os.path.exists(poster_path):
            errors.append(f"[{date}] feed.poster 指向 {poster_path} 但文件不存在")
        else:
            checks.append(f"[{date}] 海报存在且文件名日期匹配 ✓")
    else:
        if os.path.exists(poster_path):
            errors.append(f"[{date}] 存在海报 {poster_path} 但未在 feed.poster 注册（可能未刷新索引）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="仅校验单个日期")
    args = ap.parse_args()

    if not os.path.exists(FEED_PATH):
        print("✗ feed.json 不存在，无法校验")
        sys.exit(2)
    with open(FEED_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    entries = data.get("entries", {})

    errors, checks = [], []
    if args.date:
        if args.date not in entries:
            print(f"✗ feed.json 中不存在日期 {args.date}")
            sys.exit(2)
        validate_date(args.date, entries[args.date], errors, checks)
    else:
        for d in sorted(entries.keys(), reverse=True):
            validate_date(d, entries[d], errors, checks)

    print("\n".join(checks))
    if not errors:
        print(f"\n✓ 日期校验通过：{len(checks)} 项检查全部一致，无错配/串用。")
        sys.exit(0)
    else:
        print("\n".join(errors))
        print(f"\n✗ 日期校验失败：发现 {len(errors)} 处日期错配，已中止发布。")
        sys.exit(1)


if __name__ == "__main__":
    main()
