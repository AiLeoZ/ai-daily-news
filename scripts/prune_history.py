#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""历史记录过期清理：删除超过 KEEP_DAYS（默认 7）天的历史产物，仅保留最近窗口。

触发时机：每次「写入 / 构建」时调用（daily.yml 的 build 之后、validate_dates 之前；
本地由 run_daily.sh 同一位置调用），是写路径上的过期清理。读取路径上的前端兜底
见 assets/app.js 的 pruneExpiredDates()（静默、分批、不阻塞主线程）。

清理范围（保持 feed / 归档 / 速览 / 海报 严格 1:1，与 validate_dates 语义一致）：
  - data/feed.json            —— 移除过期日期条目（poster / summaryHtml 引用随条目一起消失）
  - output/archive/<date>.html—— 删除过期归档页
  - output/summary/<date>.html —— 删除过期速览页
  - output/poster/<date>.png   —— 删除过期海报
  - output/history.html        —— 按裁剪后的日期重新生成，避免残留死链

性能：文件删除按小批次（BATCH=50）执行并打印进度，避免一次性大量删除。

用法：
  python3 scripts/prune_history.py             # 默认保留最近 7 天
  python3 scripts/prune_history.py --keep 7
  python3 scripts/prune_history.py --dry-run   # 只打印将删除项，不实际删除
"""
import argparse
import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

FEED = os.path.join(ROOT, "data", "feed.json")
OUT = os.path.join(ROOT, "output")
BATCH = 50


def prune(keep_days=7, dry_run=False):
    if not os.path.exists(FEED):
        print("feed.json 不存在，跳过清理")
        return 0
    with open(FEED, encoding="utf-8") as f:
        data = json.load(f)
    entries = data.get("entries", {})
    if not entries:
        print("feed 为空，跳过清理")
        return 0

    dates = sorted(entries.keys(), reverse=True)
    latest = dates[0]
    cutoff = datetime.date.fromisoformat(latest) - datetime.timedelta(days=keep_days - 1)
    expired = [d for d in dates if datetime.date.fromisoformat(d) < cutoff]
    if not expired:
        print(f"无需清理：{len(dates)} 个日期均在最近 {keep_days} 天内（截止 {cutoff}）")
        return 0

    print(f"保留窗口：{cutoff} ~ {latest}（最近 {keep_days} 天），待清理 {len(expired)} 个日期")

    # 分批删除过期文件（每批 BATCH 个，打印进度）
    removed_files = 0
    total_targets = 0
    targets = []
    for d in expired:
        for rel in (
            os.path.join("archive", f"{d}.html"),
            os.path.join("summary", f"{d}.html"),
            os.path.join("poster", f"{d}.png"),
        ):
            p = os.path.join(OUT, rel)
            if os.path.exists(p):
                targets.append(p)
    total_targets = len(targets)
    for i in range(0, total_targets, BATCH):
        for p in targets[i:i + BATCH]:
            if not dry_run:
                os.remove(p)
            removed_files += 1
        print(f"  [分批] 已处理 {min(i + BATCH, total_targets)}/{total_targets} 个过期文件")

    if not dry_run:
        for d in expired:
            entries.pop(d, None)
        data["entries"] = entries
        with open(FEED, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"已从 feed.json 移除 {len(expired)} 个过期日期")

        # 重新生成历史索引，避免残留指向已删除归档页的死链
        try:
            import build as build_mod
            keep_dates = sorted(entries.keys(), reverse=True)
            with open(os.path.join(OUT, "history.html"), "w", encoding="utf-8") as f:
                f.write(build_mod.render_history_html(keep_dates))
            print(f"已重新生成 output/history.html（{len(keep_dates)} 个日期）")
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] 重新生成 history.html 失败：{e}（可重跑 build.py 恢复）")

    tag = "（dry-run，未实际删除）" if dry_run else ""
    print(f"清理完成：移除 {removed_files} 个过期文件、{len(expired)} 个过期日期{tag}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="历史记录过期清理（保留最近 N 天）")
    ap.add_argument("--keep", type=int, default=7, help="保留天数（默认 7）")
    ap.add_argument("--dry-run", action="store_true", help="仅预览，不实际删除")
    args = ap.parse_args()
    sys.exit(prune(args.keep, args.dry_run))


if __name__ == "__main__":
    main()
