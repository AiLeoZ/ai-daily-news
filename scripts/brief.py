#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
brief.py —— 由 feed.json 的 summary 段生成「今日速览图」。

定位：海报（poster.py）是完整要闻长图；速览图是 30 秒读完的浓缩版，篇幅约海报一半。

版式（深色科技风，与海报同一套视觉）：
  · 顶部：品牌标题 + 日期；右上角二维码，标注「扫码查看完整版」
  · ⚡ 一句话总览（高亮卡片）
  · 必须知道的 3 件事（编号卡片，标题 + 1–2 句）
  · 其余动态（一行一条）
  · GitHub 今日 TOP 3（点评 + 3 个项目各一行）

用法：
  python scripts/brief.py                  # 用 feed.json 里最新的日期
  python scripts/brief.py --date 2026-08-04
  python scripts/brief.py --date 2026-08-04 --out output/summary/2026-08-04.png

依赖：Pillow、qrcode（与 poster.py 共用，已装在托管 venv 中）
"""

import argparse
import os
import re
import sys
from datetime import datetime

from PIL import Image, ImageDraw

# 复用 poster.py 的视觉常量与绘图工具，保证两张图风格一致
from poster import (
    W, PAD, BG_TOP, BG_BOT, CARD, CARD_LINE, INK, SUB, MUTED,
    AI_C, AI_DEEP, GH_C, GH_DEEP, WEEKDAYS,
    f, clean, wrap, vgradient, add_glow, make_qr, read_feed, SITE_URL,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "output", "summary")

QR_SIZE = 150
HEAD_H = 300
SEC_H = 72
CARD_GAP = 13


# ---------------------------------------------------------------- 数据解析
def _section(md, name):
    """取出 `## <name>` 到下一个 `## ` 之间的正文。"""
    m = re.search(r"^##\s*[^\n]*" + re.escape(name) + r"[^\n]*$", md, re.M)
    if not m:
        return ""
    rest = md[m.end():]
    nxt = re.search(r"^##\s", rest, re.M)
    return (rest[: nxt.start()] if nxt else rest).strip()


def parse_summary(md):
    """把速览 Markdown 解析成渲染所需的结构化数据。"""
    overview = ""
    ov = _section(md, "一句话总览")
    for line in ov.split("\n"):
        line = clean(line)
        if line:
            overview = line
            break

    # 必须知道的 3 件事
    top = []
    top_md = _section(md, "必须知道的 3 件事")
    for block in re.split(r"^###\s+", top_md, flags=re.M)[1:]:
        lines = [l.strip() for l in block.strip().split("\n") if l.strip()]
        if not lines:
            continue
        title = clean(lines[0])
        title = re.sub(r"^\d+[.、]\s*", "", title)
        date_tag = ""
        dm = re.search(r"[（(]([^（()）]*(?:月[^（()）]*日|\d{4}-\d{2}-\d{2}))[)）]\s*$", title)
        if dm:
            date_tag = dm.group(1).replace(" ", "")
            # 2026-08-04 → 8月4日，图上更短更好读
            iso = re.match(r"(\d{4})-(\d{2})-(\d{2})$", date_tag)
            if iso:
                date_tag = "%d月%d日" % (int(iso.group(2)), int(iso.group(3)))
            title = title[: dm.start()].strip()
        desc = clean(" ".join(lines[1:]))
        top.append({"title": title, "date": date_tag, "desc": desc})

    # 其余动态：- **标题**（日期）：说明
    others = []
    for line in _section(md, "其余动态").split("\n"):
        line = line.strip()
        if not line.startswith(("-", "*")):
            continue
        body = clean(line.lstrip("-* ").strip())
        if not body:
            continue
        date_tag = ""
        dm = re.search(r"[（(]([^（()）]*(?:月[^（()）]*日|\d{4}-\d{2}-\d{2}))[)）]", body)
        if dm:
            date_tag = dm.group(1).replace(" ", "")
            iso = re.match(r"(\d{4})-(\d{2})-(\d{2})$", date_tag)
            if iso:
                date_tag = "%d月%d日" % (int(iso.group(2)), int(iso.group(3)))
            body = (body[: dm.start()] + body[dm.end():]).strip()
        body = body.lstrip("：: ").strip()
        others.append({"text": body, "date": date_tag})

    # GitHub TOP 3
    gh_md = _section(md, "GitHub 今日 TOP 3")
    gh_comment = ""
    gh_items = []
    for line in gh_md.split("\n"):
        line = line.strip()
        if line.startswith(">"):
            if not gh_comment:
                gh_comment = clean(line.lstrip("> ").strip())
            continue
        if not line.startswith(("-", "*")):
            continue
        raw = line.lstrip("-* ").strip()
        star = ""
        sm = re.search(r"`([^`]+)`", raw)
        if sm:
            star = sm.group(1).strip()
            raw = (raw[: sm.start()] + raw[sm.end():]).strip()
        raw = clean(raw)
        repo, _, desc = raw.partition("：")
        gh_items.append({"repo": repo.strip(), "star": star, "desc": desc.strip()})

    return {"overview": overview, "top": top, "others": others,
            "gh_comment": gh_comment, "gh": gh_items}


# ---------------------------------------------------------------- 版式测量
def measure(data):
    """预量各块高度，用于精确定高画布。"""
    m = {}
    # 总览卡片
    ov_w = W - PAD * 2 - 56
    m["ov_lines"] = wrap(data["overview"], f(33, True), ov_w, 3, ellipsis=False)
    m["ov_h"] = 30 + len(m["ov_lines"]) * 46 + 26

    # 3 件必知
    t_w = W - (PAD + 88) - PAD - 26
    m["top"] = []
    for it in data["top"]:
        tl = wrap(it["title"], f(30, True), t_w, 2, ellipsis=False)
        dl = wrap(it["desc"], f(23), t_w, 3, ellipsis=False)
        h = 24 + len(tl) * 40 + (6 + len(dl) * 33 if dl else 0) + 20
        m["top"].append((tl, dl, h))

    # 其余动态：一行一条（超长折 2 行）
    o_w = W - PAD * 2 - 40 - 24
    m["others"] = []
    for it in data["others"]:
        txt = it["text"]
        if it["date"]:
            txt = "%s · %s" % (it["date"], txt)
        ol = wrap(txt, f(24), o_w, 2, ellipsis=True)
        m["others"].append((ol, len(ol) * 34 + 14))

    # GitHub
    m["gh_comment_lines"] = wrap(data["gh_comment"], f(24), W - PAD * 2 - 52, 2) if data["gh_comment"] else []
    m["gh_comment_h"] = (len(m["gh_comment_lines"]) * 34 + 30) if m["gh_comment_lines"] else 0
    m["gh"] = []
    for it in data["gh"]:
        sw = (ImageDraw.Draw(Image.new("RGB", (10, 10))).textlength(it["star"], font=f(23, True)) + 26) if it["star"] else 0
        rl = wrap(it["repo"], f(27, True), W - (PAD + 82) - PAD - sw - 40, 1)
        dl = wrap(it["desc"], f(22), W - (PAD + 82) - PAD - 26, 2)
        h = 22 + len(rl) * 36 + (len(dl) * 31 if dl else 0) + 18
        m["gh"].append((rl, dl, sw, h))
    return m


# ---------------------------------------------------------------- 渲染
def render(date, data, out_path):
    m = measure(data)

    total = HEAD_H + 26 + m["ov_h"] + 34
    total += SEC_H + sum(x[2] + CARD_GAP for x in m["top"]) + 26
    if m["others"]:
        total += SEC_H + sum(x[1] for x in m["others"]) + 22
    total += SEC_H + m["gh_comment_h"] + sum(x[3] + CARD_GAP for x in m["gh"]) + 60

    img = vgradient((W, total), BG_TOP, BG_BOT).convert("RGBA")
    add_glow(img, 150, 90, 380, (37, 99, 235), 105)
    add_glow(img, W - 120, 300, 300, (124, 58, 237), 70)
    add_glow(img, W - 60, total - 160, 260, (245, 158, 11), 34)
    d = ImageDraw.Draw(img)

    # ================= 顶部品牌区
    d.text((PAD, 58), "AI 每日资讯", font=f(58, True), fill=(255, 255, 255))
    dt = datetime.strptime(date, "%Y-%m-%d")
    d.text((PAD, 140), "%d年%d月%d日 · %s" % (dt.year, dt.month, dt.day, WEEKDAYS[dt.weekday()]),
           font=f(27), fill=(191, 214, 255))
    d.line([(PAD, 194), (PAD + 92, 194)], fill=AI_C, width=4)
    # 速览标识
    d.text((PAD, 214), "⚡ 30 秒速览", font=f(34, True), fill=(253, 224, 71))
    d.text((PAD, 262), "完整版详情请扫描右上角二维码", font=f(22), fill=MUTED)

    # 右上角二维码 —— 标注「扫码查看完整版」
    qx = W - PAD - QR_SIZE - 18
    qy = 54
    d.rounded_rectangle([qx - 18, qy - 18, qx + QR_SIZE + 18, qy + QR_SIZE + 70],
                        radius=20, fill=(255, 255, 255))
    img.paste(make_qr(SITE_URL, QR_SIZE), (qx, qy))
    tip = "扫码查看完整版"
    tw = d.textlength(tip, font=f(22, True))
    d.text((qx + QR_SIZE / 2 - tw / 2, qy + QR_SIZE + 20), tip, font=f(22, True), fill=(23, 31, 52))

    y = HEAD_H + 26

    # ================= 一句话总览（高亮卡片）
    d.rounded_rectangle([PAD, y, W - PAD, y + m["ov_h"]], radius=20,
                        fill=(28, 40, 68), outline=AI_C, width=2)
    d.rounded_rectangle([PAD, y + 16, PAD + 6, y + m["ov_h"] - 16], radius=3, fill=(253, 224, 71))
    ty = y + 26
    for line in m["ov_lines"]:
        d.text((PAD + 30, ty), line, font=f(33, True), fill=(255, 255, 255))
        ty += 46
    y += m["ov_h"] + 34

    # ================= 区块标题
    def section(y, color, title, badge):
        d.rounded_rectangle([PAD, y + 6, PAD + 7, y + 40], radius=4, fill=color)
        d.text((PAD + 24, y), title, font=f(34, True), fill=INK)
        if badge:
            bw = d.textlength(badge, font=f(21, True))
            d.rounded_rectangle([W - PAD - bw - 28, y + 6, W - PAD, y + 42],
                                radius=18, fill=(255, 255, 255, 16), outline=color, width=1)
            d.text((W - PAD - bw - 14, y + 12), badge, font=f(21, True), fill=color)
        return y + SEC_H

    # ================= 必须知道的 3 件事
    y = section(y, AI_C, "必须知道的 3 件事", "重点")
    for i, (it, (tl, dl, ch)) in enumerate(zip(data["top"], m["top"]), 1):
        d.rounded_rectangle([PAD, y, W - PAD, y + ch], radius=20,
                            fill=CARD, outline=CARD_LINE, width=1)
        d.rounded_rectangle([PAD, y + 16, PAD + 5, y + ch - 16], radius=3, fill=AI_DEEP)
        bx, by = PAD + 26, y + 22
        d.rounded_rectangle([bx, by, bx + 42, by + 42], radius=13, fill=AI_DEEP)
        nw = d.textlength(str(i), font=f(24, True))
        d.text((bx + 21 - nw / 2, by + 7), str(i), font=f(24, True), fill=(255, 255, 255))
        tx, ty = PAD + 88, y + 22
        for line in tl:
            d.text((tx, ty), line, font=f(30, True), fill=INK)
            ty += 40
        if dl:
            ty += 6
            for line in dl:
                d.text((tx, ty), line, font=f(23), fill=SUB)
                ty += 33
        if it["date"]:
            dw = d.textlength(it["date"], font=f(19))
            d.rounded_rectangle([W - PAD - dw - 32, y + 22, W - PAD - 14, y + 54],
                                radius=10, fill=(30, 58, 138))
            d.text((W - PAD - dw - 23, y + 27), it["date"], font=f(19), fill=(191, 219, 254))
        y += ch + CARD_GAP
    y += 26

    # ================= 其余动态（一行一条）
    if m["others"]:
        y = section(y, (167, 139, 250), "其余动态", "%d 条" % len(data["others"]))
        for (ol, oh) in m["others"]:
            d.ellipse([PAD + 8, y + 12, PAD + 18, y + 22], fill=(167, 139, 250))
            ty = y + 4
            for line in ol:
                d.text((PAD + 40, ty), line, font=f(24), fill=SUB)
                ty += 34
            y += oh
        y += 22

    # ================= GitHub 今日 TOP 3
    y = section(y, GH_C, "GitHub 今日 TOP 3", "热门")
    if m["gh_comment_lines"]:
        ty = y + 2
        for line in m["gh_comment_lines"]:
            d.text((PAD + 26, ty), line, font=f(24), fill=(253, 230, 190))
            ty += 34
        d.rounded_rectangle([PAD, y, PAD + 5, ty - 8], radius=3, fill=GH_DEEP)
        y += m["gh_comment_h"]

    for it, (rl, dl, sw, ch) in zip(data["gh"], m["gh"]):
        d.rounded_rectangle([PAD, y, W - PAD, y + ch], radius=20,
                            fill=CARD, outline=CARD_LINE, width=1)
        d.rounded_rectangle([PAD, y + 16, PAD + 5, y + ch - 16], radius=3, fill=GH_DEEP)
        bx, by = PAD + 26, y + 20
        d.rounded_rectangle([bx, by, bx + 42, by + 42], radius=13, fill=GH_DEEP)
        rank = str(data["gh"].index(it) + 1)
        nw = d.textlength(rank, font=f(24, True))
        d.text((bx + 21 - nw / 2, by + 7), rank, font=f(24, True), fill=(255, 255, 255))
        tx, ty = PAD + 82, y + 20
        for line in rl:
            d.text((tx, ty), line, font=f(27, True), fill=(255, 255, 255))
            ty += 36
        if it["star"]:
            d.rounded_rectangle([W - PAD - sw - 12, y + 20, W - PAD - 14, y + 58],
                                radius=12, fill=(66, 45, 14))
            d.text((W - PAD - sw + 1, y + 27), it["star"], font=f(23, True), fill=GH_C)
        for line in dl:
            d.text((tx, ty), line, font=f(22), fill=SUB)
            ty += 31
        y += ch + CARD_GAP

    img = img.convert("RGB")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path, "PNG", optimize=True)
    return out_path, img.size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="日期 YYYY-MM-DD，默认取 feed.json 最新")
    ap.add_argument("--out", default=None, help="输出路径，默认 output/summary/<date>.png")
    args = ap.parse_args()

    date, entry = read_feed(args.date)
    md = (entry.get("summary") or {}).get("markdown", "")
    if not md.strip():
        raise SystemExit("[brief] %s 没有 summary 段，请先跑 filter.py --section summary" % date)

    data = parse_summary(md)
    if not data["overview"] or len(data["top"]) < 1:
        raise SystemExit("[brief] 速览解析失败：总览 %r / 必知 %d 条"
                         % (data["overview"][:20], len(data["top"])))

    out = args.out or os.path.join(OUT_DIR, "%s.png" % date)
    path, size = render(date, data, out)

    latest = os.path.join(OUT_DIR, "latest.png")
    Image.open(path).save(latest, "PNG", optimize=True)

    print("[brief] 日期 %s | 必知 %d 条 | 其余 %d 条 | GitHub %d 条"
          % (date, len(data["top"]), len(data["others"]), len(data["gh"])))
    print("   总览：%s" % data["overview"])
    for i, it in enumerate(data["top"], 1):
        print("   必知 %d. %s" % (i, it["title"][:32]))
    for it in data["gh"]:
        print("   GH  %-38s %s" % (it["repo"], it["star"]))
    print("[brief] 输出 %s  (%dx%d)" % (path, size[0], size[1]))
    print("[brief] 同步 %s" % latest)


if __name__ == "__main__":
    sys.exit(main())
