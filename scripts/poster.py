#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
poster.py —— 由每日 feed.json 生成一张可直接发社交媒体的竖版海报。

版式（深色科技风）：
  · 顶部：品牌标题 + 日期；右上角二维码，标注「扫码查看详情」
  · 今日 AI 要闻（最多 10 条，主篇幅：完整标题，无下方注解）
  · GitHub 今日趋势 TOP 3（项目 + 今日新增 Star + 极简介绍）
  · 底部：引导扫码条

用法：
  python scripts/poster.py                 # 用 feed.json 里最新的日期
  python scripts/poster.py --date 2026-08-03
  python scripts/poster.py --date 2026-08-03 --out output/poster/2026-08-03.png

依赖：Pillow、qrcode（均已装在托管 venv 中）
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEED = os.path.join(ROOT, "data", "feed.json")
OUT_DIR = os.path.join(ROOT, "output", "poster")
SITE_URL = "https://3a2c7e71a31748508dbe8b75e7cdeca9.bj7.agentos-app.net"

# ---------------------------------------------------------------- 视觉规范
W = 1080                          # 画布宽（竖版社媒尺寸）
PAD = 60                          # 左右安全边距

BG_TOP = (10, 14, 28)             # 背景渐变（上）
BG_BOT = (17, 24, 43)             # 背景渐变（下）
CARD = (23, 31, 52)               # 卡片底
CARD_LINE = (38, 50, 78)          # 卡片描边
INK = (236, 241, 249)             # 主文字
SUB = (168, 181, 204)             # 次级文字
MUTED = (128, 143, 170)           # 弱化文字

AI_C = (96, 165, 250)             # AI 蓝
AI_DEEP = (37, 99, 235)
GH_C = (251, 176, 64)             # GitHub 橙
GH_DEEP = (217, 119, 6)

FONT_CANDIDATES = [
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", 0, 1),   # 常规, 粗体
    ("/System/Library/Fonts/STHeiti Light.ttc", 0, 0),
    ("/System/Library/Fonts/Supplemental/Songti.ttc", 0, 1),
]


def load_fonts():
    for path, ri, bi in FONT_CANDIDATES:
        if os.path.exists(path):
            return path, ri, path, bi
    raise RuntimeError("未找到可用的中文字体")


FR_PATH, FR_IDX, FB_PATH, FB_IDX = load_fonts()
_font_cache = {}


def f(size, bold=False):
    key = (size, bold)
    if key not in _font_cache:
        path, idx = (FB_PATH, FB_IDX) if bold else (FR_PATH, FR_IDX)
        try:
            _font_cache[key] = ImageFont.truetype(path, size, index=idx)
        except Exception:
            _font_cache[key] = ImageFont.truetype(path, size)
    return _font_cache[key]


# ---------------------------------------------------------------- 数据解析
def read_feed(date=None):
    with open(FEED, "r", encoding="utf-8") as fp:
        feed = json.load(fp)
    entries = feed.get("entries", {})
    if not entries:
        raise SystemExit("feed.json 里没有任何日期条目")
    if date is None:
        date = sorted(entries.keys())[-1]
    if date not in entries:
        raise SystemExit("feed.json 中不存在日期 %s（现有：%s）" % (date, ", ".join(sorted(entries))))
    return date, entries[date]


def clean(text):
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("**", "").replace("`", "")
    return re.sub(r"\s+", " ", text).strip()


def parse_ai_news(md, limit=5):
    """海报 AI 要闻：仅保留完整标题（含日期标签），不抽取下方注解/简介。"""
    items = []
    blocks = re.split(r"^###\s+", md, flags=re.M)[1:]
    for block in blocks:
        lines = [l.strip() for l in block.strip().split("\n")]
        if not lines:
            continue
        title = clean(lines[0])
        title = re.sub(r"^\d+[.、]\s*", "", title)
        date_tag = ""
        m = re.search(r"[（(]([^（()）]*月[^（()）]*日)[)）]\s*$", title)
        if m:
            date_tag = m.group(1).replace(" ", "")
            title = title[: m.start()].strip()
        items.append({"title": title, "date": date_tag})
        if len(items) >= limit:
            break
    return items


def parse_github(md, limit=5):
    part = md
    m = re.search(r"##\s*二、", md)
    if m:
        part = md[: m.start()]
    items = []
    row_re = re.compile(r"^\|\s*(\d+)\s*\|\s*(.+?)\s*\|\s*([^|]*?)\s*\|\s*(.+?)\s*\|\s*$", re.M)
    for m in row_re.finditer(part):
        rank, project_cell, star, note = m.groups()
        rm = re.search(r"\[([^\]]+)\]\(", project_cell)
        if not rm:
            continue
        repo = rm.group(1).strip()
        dm = re.search(r'repo-desc"[^>]*>(.*?)</span>', project_cell)
        desc = clean(dm.group(1)) if dm else ""
        if not desc:
            desc = re.split(r"[。！？]", clean(note))[0]
        items.append({"rank": int(rank), "repo": repo, "star": clean(star), "desc": desc})
        if len(items) >= limit:
            break
    return items


# ---------------------------------------------------------------- 绘图工具
_measure = ImageDraw.Draw(Image.new("RGB", (10, 10)))


def wrap(text, font, max_w, max_lines=2, draw=None, ellipsis=True):
    """按像素宽度折行（中英混排安全）；ellipsis=False 时超长直接截断、不加省略号。"""
    d = draw or _measure
    if not text:
        return []
    lines, cur = [], ""
    for ch in text:
        trial = cur + ch
        if d.textlength(trial, font=font) <= max_w:
            cur = trial
            continue
        if ch.isalnum() and cur and cur[-1].isalnum() and " " in cur.strip():
            cut = cur.rstrip().rfind(" ")
            if cut > len(cur) * 0.5:
                lines.append(cur[:cut])
                cur = cur[cut + 1:] + ch
                if len(lines) >= max_lines:
                    break
                continue
        lines.append(cur)
        cur = ch
        if len(lines) >= max_lines:
            break
    if len(lines) < max_lines and cur:
        lines.append(cur)
    if len(lines) == max_lines and ellipsis:
        # 英文折行会吃掉一个空格，故忽略空格再比较，避免误判为截断
        if "".join(lines).replace(" ", "") != text.replace(" ", ""):
            last = lines[-1]
            while last and d.textlength(last + "…", font=font) > max_w:
                last = last[:-1]
            lines[-1] = last + "…"
    return lines


def vgradient(size, c1, c2):
    h = size[1]
    strip = Image.new("RGB", (1, h))
    px = strip.load()
    for i in range(h):
        t = i / max(h - 1, 1)
        px[0, i] = tuple(int(c1[k] + (c2[k] - c1[k]) * t) for k in range(3))
    return strip.resize(size)


def add_glow(img, cx, cy, r, color, alpha=90):
    """在画布上叠一团柔光，营造科技感。"""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse([cx - r, cy - r, cx + r, cy + r],
                                  fill=color + (alpha,))
    layer = layer.filter(ImageFilter.GaussianBlur(r * 0.55))
    img.alpha_composite(layer)


def make_qr(url, size):
    import qrcode
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,
                       box_size=10, border=1)
    qr.add_data(url)
    qr.make(fit=True)
    im = qr.make_image(fill_color=(12, 18, 33), back_color="white").convert("RGB")
    return im.resize((size, size), Image.NEAREST)


WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

# ---------------------------------------------------------------- 版式常量
HEAD_H = 330
QR_SIZE = 168
SEC_H = 78            # 区块标题高度
CARD_GAP = 14
FOOT_H = 108


def measure_ai(items):
    """预先量出 AI 卡片高度，便于精确定高。标题完整保留、最多 3 行、不截断。"""
    tx_w = W - (PAD + 92) - PAD - 26
    out = []
    for it in items:
        t = wrap(it["title"], f(31, True), tx_w, 3, ellipsis=False)
        out.append((t, 28 + len(t) * 41 + 22))
    return out


def measure_gh(items):
    out = []
    for it in items:
        sw = _measure.textlength(it["star"], font=f(25, True)) + 30
        r = wrap(it["repo"], f(29, True), W - (PAD + 92) - PAD - sw - 44, 1)
        de = wrap(it["desc"], f(23), W - (PAD + 92) - PAD - 26, 2)
        out.append((r, de, sw, 26 + len(r) * 39 + (len(de) * 33 if de else 0) + 20))
    return out


def render(date, ai_items, gh_items, out_path):
    ai_m = measure_ai(ai_items)
    gh_m = measure_gh(gh_items)
    total = (HEAD_H + 34 + SEC_H + sum(m[1] + CARD_GAP for m in ai_m)
             + 30 + SEC_H + sum(m[3] + CARD_GAP for m in gh_m) + 24 + FOOT_H)

    img = vgradient((W, total), BG_TOP, BG_BOT).convert("RGBA")
    add_glow(img, 150, 90, 380, (37, 99, 235), 105)
    add_glow(img, W - 120, 300, 300, (124, 58, 237), 70)
    add_glow(img, W - 60, total - 160, 260, (245, 158, 11), 34)
    d = ImageDraw.Draw(img)

    # ================= 顶部品牌区
    d.text((PAD, 62), "AI 每日资讯", font=f(64, True), fill=(255, 255, 255))
    dt = datetime.strptime(date, "%Y-%m-%d")
    d.text((PAD, 154), "%d年%d月%d日 · %s" % (dt.year, dt.month, dt.day, WEEKDAYS[dt.weekday()]),
           font=f(29), fill=(191, 214, 255))
    # 细分隔线
    d.line([(PAD, 212), (PAD + 92, 212)], fill=AI_C, width=4)
    d.text((PAD, 232), "每日 AI 新闻 · GitHub 趋势  每日更新", font=f(24), fill=SUB)

    # 右上角二维码
    qx = W - PAD - QR_SIZE - 20
    qy = 56
    d.rounded_rectangle([qx - 20, qy - 20, qx + QR_SIZE + 20, qy + QR_SIZE + 74],
                        radius=22, fill=(255, 255, 255))
    img.paste(make_qr(SITE_URL, QR_SIZE), (qx, qy))
    tip = "扫码查看详情"
    tw = d.textlength(tip, font=f(23, True))
    d.text((qx + QR_SIZE / 2 - tw / 2, qy + QR_SIZE + 22), tip, font=f(23, True), fill=(23, 31, 52))

    y = HEAD_H + 34

    # ================= 区块标题
    def section(y, color, title, badge):
        d.rounded_rectangle([PAD, y + 8, PAD + 7, y + 42], radius=4, fill=color)
        d.text((PAD + 24, y), title, font=f(37, True), fill=INK)
        bw = d.textlength(badge, font=f(22, True))
        d.rounded_rectangle([W - PAD - bw - 30, y + 8, W - PAD, y + 46],
                            radius=19, fill=(255, 255, 255, 16), outline=color, width=1)
        d.text((W - PAD - bw - 15, y + 15), badge, font=f(22, True), fill=color)
        return y + SEC_H

    y = section(y, AI_C, "近期 AI 要闻", "%d 条" % len(ai_items))

    # ================= AI 新闻卡片（仅展示完整标题）
    for i, (it, (t_lines, ch)) in enumerate(zip(ai_items, ai_m), 1):
        d.rounded_rectangle([PAD, y, W - PAD, y + ch], radius=20,
                            fill=CARD, outline=CARD_LINE, width=1)
        d.rounded_rectangle([PAD, y + 18, PAD + 5, y + ch - 18], radius=3, fill=AI_DEEP)
        # 序号
        bx, by = PAD + 28, y + 24
        d.rounded_rectangle([bx, by, bx + 46, by + 46], radius=14, fill=AI_DEEP)
        nw = d.textlength(str(i), font=f(26, True))
        d.text((bx + 23 - nw / 2, by + 8), str(i), font=f(26, True), fill=(255, 255, 255))
        tx = PAD + 92
        ty = y + 24
        for line in t_lines:
            d.text((tx, ty), line, font=f(31, True), fill=INK)
            ty += 41
        if it["date"]:
            dw = d.textlength(it["date"], font=f(20))
            d.rounded_rectangle([W - PAD - dw - 34, y + 26, W - PAD - 16, y + 60],
                                radius=11, fill=(30, 58, 138))
            d.text((W - PAD - dw - 25, y + 32), it["date"], font=f(20), fill=(191, 219, 254))
        y += ch + CARD_GAP

    y += 30
    y = section(y, GH_C, "GitHub 今日趋势", "TOP %d" % len(gh_items))

    # ================= GitHub 卡片
    for it, (r_lines, de_lines, sw, ch) in zip(gh_items, gh_m):
        d.rounded_rectangle([PAD, y, W - PAD, y + ch], radius=20,
                            fill=CARD, outline=CARD_LINE, width=1)
        d.rounded_rectangle([PAD, y + 18, PAD + 5, y + ch - 18], radius=3, fill=GH_DEEP)
        bx, by = PAD + 28, y + 22
        d.rounded_rectangle([bx, by, bx + 46, by + 46], radius=14, fill=GH_DEEP)
        nw = d.textlength(str(it["rank"]), font=f(26, True))
        d.text((bx + 23 - nw / 2, by + 8), str(it["rank"]), font=f(26, True), fill=(255, 255, 255))
        tx = PAD + 92
        ty = y + 22
        for line in r_lines:
            d.text((tx, ty), line, font=f(29, True), fill=(255, 255, 255))
            ty += 39
        if it["star"]:
            d.rounded_rectangle([W - PAD - sw - 14, y + 22, W - PAD - 16, y + 64],
                                radius=13, fill=(66, 45, 14))
            d.text((W - PAD - sw, y + 30), it["star"], font=f(25, True), fill=GH_C)
        ty += 4
        for line in de_lines:
            d.text((tx, ty), line, font=f(23), fill=SUB)
            ty += 33

        y += ch + CARD_GAP

    # ================= 底部引导
    y += 20
    d.line([(PAD, y), (W - PAD, y)], fill=(45, 58, 88), width=1)
    tip = "更多 AI 资讯请扫描右上角二维码"
    tw = d.textlength(tip, font=f(26, True))
    d.text(((W - tw) / 2, y + 38), tip, font=f(26, True), fill=(255, 255, 255))

    img = img.convert("RGB")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path, "PNG", optimize=True)
    return out_path, img.size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="日期 YYYY-MM-DD，默认取 feed.json 最新")
    ap.add_argument("--out", default=None, help="输出路径，默认 output/poster/<date>.png")
    ap.add_argument("--ai-limit", type=int, default=10, help="AI 新闻最多显示条数（默认 10）")
    ap.add_argument("--gh-limit", type=int, default=3, help="GitHub 趋势显示条数（默认 3）")
    args = ap.parse_args()

    date, entry = read_feed(args.date)
    ai_md = (entry.get("aiNews") or {}).get("markdown", "")
    gh_md = (entry.get("github") or {}).get("markdown", "")
    ai_items = parse_ai_news(ai_md, args.ai_limit)
    gh_items = parse_github(gh_md, args.gh_limit)
    if len(ai_items) < 1 or len(gh_items) < 1:
        raise SystemExit("解析失败：AI %d 条 / GitHub %d 条" % (len(ai_items), len(gh_items)))

    out = args.out or os.path.join(OUT_DIR, "%s.png" % date)
    path, size = render(date, ai_items, gh_items, out)

    latest = os.path.join(OUT_DIR, "latest.png")
    Image.open(path).save(latest, "PNG", optimize=True)

    print("[poster] 日期 %s | AI %d 条 | GitHub %d 条" % (date, len(ai_items), len(gh_items)))
    for i, it in enumerate(ai_items, 1):
        print("   AI %d. %s" % (i, it["title"][:34]))
    for it in gh_items:
        print("   GH %d. %-42s %s" % (it["rank"], it["repo"], it["star"]))
    print("[poster] 输出 %s  (%dx%d)" % (path, size[0], size[1]))
    print("[poster] 同步 %s" % latest)


if __name__ == "__main__":
    sys.exit(main())
