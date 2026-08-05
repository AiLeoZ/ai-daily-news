#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_poster_qr.py —— 批量修复海报二维码跳转链接。

问题背景
--------
海报二维码在生成时被「烧录」进 PNG 像素，无法事后就地改写。
旧版海报统一指向已下线的 CloudStudio 临时地址；迁移到 GitHub Pages
（https://aileoz.github.io/ai-daily-news/）后，需要重新生成海报。

二维码指向规则（由 scripts/poster.py 的 qr_url_for 实现，本脚本复用）
---------------------------------------------------------------------
  · 当日（feed.json 中最新一天）  → 站点根地址 SITE_URL（主页）
  · 历史（非最新一天）            → 该日期归档页 SITE_URL/output/archive/<日期>.html

用法
----
  # 仅修复「今日」海报（默认），同步 latest.png
  python scripts/fix_poster_qr.py

  # 修复全部历史 + 今日（按 feed.json 所有日期批量处理）
  python scripts/fix_poster_qr.py --all

  # 修复单个指定日期
  python scripts/fix_poster_qr.py --date 2026-08-03

  # 修复一段日期区间（含端点，按自然日递增）
  python scripts/fix_poster_qr.py --range 2026-08-01 2026-08-05

  # 只打印将要写入的二维码地址，不重新生成
  python scripts/fix_poster_qr.py --all --dry-run

依赖：Pillow、qrcode（生成）；可选 opencv-python-headless / pyzbar（解码校验，缺失则跳过）
"""

import argparse
import os
import sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import poster  # noqa: E402


def decode_qr(png_path):
    """尽力解码 PNG 中的二维码，返回内容字符串；失败/无解码库返回 None。"""
    try:
        import cv2  # opencv-python-headless
        img = cv2.imread(png_path)
        if img is None:
            return None
        data, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
        return (data or "").strip() or None
    except Exception:
        pass
    try:
        from pyzbar.pyzbar import decode  # pyzbar（需系统 zbar）
        from PIL import Image
        res = decode(Image.open(png_path))
        if res:
            return res[0].data.decode("utf-8", "ignore").strip() or None
    except Exception:
        pass
    return None


def date_range(start, end):
    s = date.fromisoformat(start)
    e = date.fromisoformat(end)
    if s > e:
        s, e = e, s
    out = []
    while s <= e:
        out.append(s.isoformat())
        s += timedelta(days=1)
    return out


def main():
    ap = argparse.ArgumentParser(description="批量修复海报二维码跳转链接")
    ap.add_argument("--date", help="单个日期 YYYY-MM-DD")
    ap.add_argument("--all", action="store_true", help="修复 feed.json 中所有日期的海报")
    ap.add_argument("--range", nargs=2, metavar=("START", "END"),
                    help="日期区间（含端点，自然日递增）")
    ap.add_argument("--dry-run", action="store_true", help="只打印将要写入的二维码地址，不重新生成")
    ap.add_argument("--no-verify", action="store_true", help="跳过二维码解码校验")
    args = ap.parse_args()

    # ---- 决定要处理的日期列表
    if args.all:
        dates = poster.sorted_dates()
    elif args.range:
        dates = date_range(args.range[0], args.range[1])
    elif args.date:
        dates = [args.date]
    else:
        latest = poster.latest_feed_date()
        dates = [latest] if latest else []
    if not dates:
        raise SystemExit("没有可处理的日期（feed.json 为空或未指定 --date/--all/--range）")

    latest = poster.latest_feed_date()
    print("站点基础地址 SITE_URL = %s" % poster.SITE_URL)
    print("待处理日期（共 %d）：%s" % (len(dates), ", ".join(dates)))
    print("-" * 64)

    ok, bad = [], []
    for d in dates:
        url = poster.qr_url_for(d, latest_date=latest)
        tag = "（当日→主页）" if d == latest else "（历史→归档页）"
        print("%s %s -> %s" % (d, tag, url))
        if args.dry_run:
            ok.append((d, url, "dry-run"))
            continue

        png = os.path.join(poster.OUT_DIR, "%s.png" % d)
        poster.generate_poster(d, qr_url=url, copy_latest=(d == latest))
        # 校验：解码生成的 PNG 二维码，确认指向正确
        if not args.no_verify:
            decoded = decode_qr(png)
            if decoded == url:
                print("   ✓ 二维码校验通过：%s" % decoded)
                ok.append((d, url, "verified"))
            else:
                print("   ✗ 二维码校验不一致！解码得到：%r" % decoded)
                bad.append((d, url, decoded))
        else:
            ok.append((d, url, "unverified"))

    print("-" * 64)
    print("完成：成功 %d 张，异常 %d 张" % (len(ok), len(bad)))
    for d, url, st in bad:
        print("  异常 %s 期望 %s 实际 %r" % (d, url, st))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
