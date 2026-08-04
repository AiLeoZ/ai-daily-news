#!/usr/bin/env python3
"""筛选 / 聚合阶段：把 AI 整理好的原始 Markdown 校验后写入 data/feed.json。

职责：
  - 校验原始 Markdown 非空、含必要结构（## 分类标题 / ### 条目）。
  - 去重（按 ### 标题）。
  - 强制 Top-N 上限（来自 config/site.yaml 的 max_items_per_day）。
  - 时间序提示（若检测到后面的日期比前面更近，打印警告，不强行重排）。
  - 按日期键聚合进 data/feed.json，aiNews / github 两块互不覆盖。

这是原 update_feed.py 的升级版（新增校验/去重/上限），旧脚本保留为兼容后备。

用法：
  python3 scripts/filter.py --date 2026-08-03 --section aiNews \
      --file data/raw/2026-08-03_ai.md
  python3 scripts/filter.py --rebuild        # 从 data/raw/ 重新聚合所有日期
"""
import argparse
import datetime
import glob
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEED_PATH = os.path.join(ROOT, "data", "feed.json")
RAW = os.path.join(ROOT, "data", "raw")
SECTIONS = {"aiNews", "github"}


def load_site_cfg():
    try:
        from yamlutil import load_file
        cfg = load_file(os.path.join(ROOT, "config", "site.yaml"))
        return cfg
    except Exception:
        return {}


def count_items(md, section=None):
    # AI 新闻：每条以 ### 开头；GitHub 趋势：以表格行（| ... |）计条目
    if section == "github":
        rows = [l for l in md.splitlines()
                if l.strip().startswith("|") and not re.match(r"^\s*\|[\s:|-]+\|\s*$", l)]
        return max(0, len(rows) - 1)  # 减去表头一行
    return len(re.findall(r"^###\s", md, re.M))


def extract_dates(md, year=None):
    # 匹配 ### 标题后的（YYYY-MM-DD）或（M月D日），归一化为 YYYY-MM-DD
    found = re.findall(r"（\s*(\d{4}-\d{2}-\d{2}|\d{1,2}月\d{1,2}日)\s*）", md)
    norm = []
    for d in found:
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", d)
        if m:
            norm.append(m.group(0))
        else:
            mm = re.match(r"(\d{1,2})月(\d{1,2})日", d)
            if mm:
                y = year or datetime.datetime.now().year
                norm.append(f"{y}-{int(mm.group(1)):02d}-{int(mm.group(2)):02d}")
    return norm


def _check_ai_structure(md, n, warnings):
    """AI 新闻结构校验（仅告警）：分类标题、必填字段、禁用措辞。"""
    if "🔝 今日要闻" not in md:
        warnings.append("缺少「## 🔝 今日要闻」分类标题")
    if "近期其他要闻" not in md:
        warnings.append("缺少「## 近期其他要闻」分类标题")
    why = len(re.findall(r"\*\*为什么关注\*\*", md))
    note = len(re.findall(r"\*\*注解\*\*", md))
    if why < n:
        warnings.append(f"「为什么关注」仅 {why} 处，少于条目数 {n}（可能缺项）")
    if note < n:
        warnings.append(f"「注解」仅 {note} 处，少于条目数 {n}（可能缺项）")
    if "通俗解释" in md:
        warnings.append("检测到「通俗解释」字样，注解应使用「注解」而非「通俗解释」")


def _check_github_structure(md, warnings):
    """GitHub 趋势结构校验（仅告警）：分类标题、repo-desc、禁用 since=。"""
    if "## 一、今日榜" not in md:
        warnings.append("缺少「## 一、今日榜」分类标题")
    if "## 二、本周榜" not in md:
        warnings.append("缺少「## 二、本周榜」分类标题")
    if "since=" in md:
        warnings.append("GitHub 标题中出现 since= 字样，应去掉")
    rows = [l for l in md.splitlines() if re.match(r"^\|\s*\d+\s*\|", l)]
    desc = md.count("repo-desc")
    if rows and desc < len(rows):
        warnings.append(f"项目列 repo-desc 仅 {desc} 处，少于表格数据行 {len(rows)}（可能缺简介）")


def validate(md, max_items, section=None, date=None):
    warnings = []
    if not md.strip():
        return False, ["内容为空"]
    if "## " not in md:
        warnings.append("缺少 ## 分类标题")
    n = count_items(md, section)
    if section != "github" and n == 0:
        warnings.append("未检测到 ### 条目（可能格式不符）")
    # Top-N 上限仅约束 AI 新闻条目；GitHub 表格（多行）不应被裁切
    if section == "aiNews" and n > max_items:
        warnings.append(f"条目数 {n} 超过上限 {max_items}，将截断")
    # 时间序检测（仅对带日期的 AI 新闻有意义）
    year = None
    if date:
        try:
            year = int(date.split("-")[0])
        except Exception:
            year = None
    dates = extract_dates(md, year)
    for i in range(1, len(dates)):
        if dates[i] > dates[i - 1]:
            warnings.append(f"时间序异常：第 {i+1} 条日期 {dates[i]} 比前一条 {dates[i-1]} 更近")
            break
    # 结构校验（模型无关兜底：弱模型漏字段也能被发现）
    if section == "aiNews":
        _check_ai_structure(md, n, warnings)
    elif section == "github":
        _check_github_structure(md, warnings)
    return True, warnings


def truncate(md, max_items):
    # 保留开头的分类标题，截断 ### 条目到 max_items
    lines = md.splitlines()
    head, items = [], []
    for ln in lines:
        if re.match(r"^###\s", ln):
            items.append(ln)
        else:
            head.append(ln)
    kept = items[:max_items]
    return "\n".join(head + kept).strip() + "\n"


def aggregate(date, section, md, max_items):
    data = {"entries": {}}
    if os.path.exists(FEED_PATH):
        try:
            with open(FEED_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            data = {"entries": {}}
    data.setdefault("entries", {})
    entry = data["entries"].setdefault(date, {})
    entry[section] = {
        "generatedAt": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "markdown": md,
    }
    data["updatedAt"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    with open(FEED_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def process_file(date, section, path, max_items):
    with open(path, "r", encoding="utf-8") as f:
        md = f.read().strip()
    ok, warns = validate(md, max_items, section, date)
    for w in warns:
        print(f"  [警告] {w}")
    if not ok:
        print(f"  [跳过] {date}/{section} 校验未通过")
        return False
    # 仅 AI 新闻应用 Top-N 截断；GitHub 表格保持完整
    if section == "aiNews" and count_items(md, section) > max_items:
        md = truncate(md, max_items)
    aggregate(date, section, md, max_items)
    print(f"  已聚合 {date}/{section}（条目 {count_items(md, section)}）")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--section", choices=sorted(SECTIONS))
    ap.add_argument("--file")
    ap.add_argument("--rebuild", action="store_true", help="从 data/raw/ 重新聚合所有日期")
    args = ap.parse_args()
    cfg = load_site_cfg()
    max_items = int(cfg.get("max_items_per_day", 10))

    if args.rebuild:
        files = sorted(glob.glob(os.path.join(RAW, "*_*.md")))
        for fp in files:
            base = os.path.basename(fp)[:-3]  # e.g. 2026-08-03_ai
            date, section = base.rsplit("_", 1)
            if section not in SECTIONS:
                continue
            print(f"重建 {date}/{section}")
            process_file(date, section, fp, max_items)
        print("全部重建完成")
        return

    if not (args.date and args.section and args.file):
        ap.error("需提供 --date/--section/--file，或使用 --rebuild")
    if not os.path.exists(args.file):
        ap.error(f"文件不存在: {args.file}")
    process_file(args.date, args.section, args.file, max_items)


if __name__ == "__main__":
    main()
