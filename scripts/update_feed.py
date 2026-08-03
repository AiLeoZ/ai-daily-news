#!/usr/bin/env python3
"""更新网站数据文件 data/feed.json。

用法:
  python3 scripts/update_feed.py --date 2026-08-03 --section aiNews \
      --file data/raw/2026-08-03_ai.md

  section 取值: aiNews | github
数据按日期键聚合，两个板块各自独立写入，不会互相覆盖。
"""
import argparse
import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEED_PATH = os.path.join(ROOT, "data", "feed.json")
SECTIONS = {"aiNews", "github"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="日期键，格式 YYYY-MM-DD")
    ap.add_argument("--section", required=True, choices=sorted(SECTIONS))
    ap.add_argument("--file", required=True, help="包含 markdown 内容的文件路径")
    args = ap.parse_args()

    if not os.path.exists(args.file):
        sys.exit(f"内容文件不存在: {args.file}")

    with open(args.file, "r", encoding="utf-8") as f:
        markdown = f.read().strip()

    data = {"entries": {}}
    if os.path.exists(FEED_PATH):
        with open(FEED_PATH, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = {"entries": {}}
    data.setdefault("entries", {})

    entry = data["entries"].setdefault(args.date, {})
    entry[args.section] = {
        "generatedAt": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "markdown": markdown,
    }
    data["updatedAt"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")

    with open(FEED_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"已更新 {args.date} / {args.section}（共 {len(data['entries'])} 个日期）")


if __name__ == "__main__":
    main()
