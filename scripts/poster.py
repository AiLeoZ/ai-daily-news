#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
poster.py —— 由每日 feed.json 生成一张可直接发社交媒体的竖版海报。

内容：
  · 顶部品牌头（标题 + 日期）
  · 今日 AI 要闻 TOP 5（标题 + 一句话摘要）
  · GitHub 今日趋势 TOP 5（项目 + 今日新增 Star + 极简介绍）
  · 底部二维码，扫码直达站点

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

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEED = os.path.join(ROOT, "data", "feed.json")
OUT_DIR = os.path.join(ROOT, "output", "poster")
SITE_URL = "https://3a2c7e71a31748508dbe8b75e7cdeca9.bj7.agentos-app.net"

# ---------------------------------------------------------------- 视觉规范
W = 1080                      # 画布宽（竖版社媒尺寸）
PAD = 56                      # 左右安全边距
BG = (245, 247, 251)          # --bg
CARD = (255, 255, 255)        # --card
INK = (31, 39, 51)            # --ink
MUTED = (107, 118, 134)       # --muted
LINE = (230, 234, 240)        # --line
ACCENT = (37, 99, 235)        # --accent 蓝：AI 新闻
ACCENT_DARK = (29, 78, 216)   # --accent-strong
GH = (217, 119, 6)            # --gh 橙：GitHub 趋势
GH_SOFT = (255, 247, 235)

FONT_CANDIDATES = [
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", 0, 1),   # 常规, 粗体
    ("/System/Library/Fonts/STHeiti Light.ttc", 0, 0),
    ("/System/Library/Fonts/Supplemental/Songti.ttc", 0, 1),
]


def load_fonts():
    """返回 (regular_path, regular_index, bold_path, bold_index)。"""
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
    """去掉 markdown / html 标记，压平成一行纯文本。"""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("**", "").replace("`", "")
    return re.sub(r"\s+", " ", text).strip()


def parse_ai_news(md, limit=5):
    """从 AI 新闻 markdown 里取前 N 条：标题 + 一句话摘要。"""
    items = []
    blocks = re.split(r"^###\s+", md, flags=re.M)[1:]
    for block in blocks:
        lines = [l.strip() for l in block.strip().split("\n")]
        if not lines:
            continue
        title = clean(lines[0])
        title = re.sub(r"^\d+[.、]\s*", "", title)           # 去掉序号
        date_tag = ""
        m = re.search(r"[（(]([^（()）]*月[^（()）]*日)[)）]\s*$", title)
        if m:
            date_tag = m.group(1).replace(" ", "")
            title = title[: m.start()].strip()
        summary = ""
        for l in lines[1:]:
            if not l or l.startswith(("-", "*", "#", ">", "|")):
                continue
            summary = clean(l)
            break
        if not summary:                                      # 兜底用「注解」
            m2 = re.search(r"\*\*注解\*\*[：:]\s*(.+)", block)
            if m2:
                summary = clean(m2.group(1))
        items.append({"title": title, "summary": summary, "date": date_tag})
        if len(items) >= limit:
            break
    return items


def parse_github(md, limit=5):
    """从 GitHub markdown 的第一张表（今日榜）取前 N 个项目。"""
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
        if not desc:                                         # 兜底：注解首句
            desc = re.split(r"[。！？]", clean(note))[0]
        items.append({"rank": int(rank), "repo": repo, "star": clean(star), "desc": desc})
        if len(items) >= limit:
            break
    return items


# ---------------------------------------------------------------- 绘图工具
def wrap(draw, text, font, max_w, max_lines=2):
    """按像素宽度折行（中英混排安全），超出行数用省略号收尾。"""
    if not text:
        return []
    lines, cur = [], ""
    for ch in text:
        trial = cur + ch
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
            continue
        # 英文单词尽量不拦腰截断
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
    if len(lines) == max_lines:
        rest_start = sum(len(l) for l in lines)
        if rest_start < len(text):
            last = lines[-1]
            while last and draw.textlength(last + "…", font=font) > max_w:
                last = last[:-1]
            lines[-1] = last + "…"
    return lines


def text_block(draw, x, y, text, font, fill, max_w, max_lines=2, leading=10):
    for line in wrap(draw, text, font, max_w, max_lines):
        draw.text((x, y), line, font=font, fill=fill)
        y += font.size + leading
    return y


def gradient_header(img, h, c1, c2):
    top = Image.new("RGB", (1, h))
    px = top.load()
    for i in range(h):
        t = i / max(h - 1, 1)
        px[0, i] = tuple(int(c1[k] + (c2[k] - c1[k]) * t) for k in range(3))
    img.paste(top.resize((W, h)), (0, 0))


def make_qr(url, size):
    import qrcode
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M,
                       box_size=10, border=1)
    qr.add_data(url)
    qr.make(fit=True)
    im = qr.make_image(fill_color=(15, 23, 42), back_color="white").convert("RGB")
    return im.resize((size, size), Image.NEAREST)


WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def render(date, ai_items, gh_items, out_path):
    img = Image.new("RGB", (W, 2600), BG)
    d = ImageDraw.Draw(img)

    # ---------- 头部
    HEAD_H = 268
    gradient_header(img, HEAD_H, (29, 78, 216), (59, 130, 246))
    d.text((PAD, 62), "AI 每日资讯", font=f(60, True), fill=(255, 255, 255))
    dt = datetime.strptime(date, "%Y-%m-%d")
    sub = "%d年%d月%d日 · %s" % (dt.year, dt.month, dt.day, WEEKDAYS[dt.weekday()])
    d.text((PAD, 146), sub, font=f(30), fill=(219, 234, 254))
    d.text((PAD, 196), "每日自动更新 · AI 新闻 + GitHub 趋势", font=f(24), fill=(191, 219, 254))
    tag = "DAILY BRIEF"
    tw = d.textlength(tag, font=f(22, True))
    d.rounded_rectangle([W - PAD - tw - 32, 66, W - PAD, 114], radius=24,
                        outline=(147, 197, 253), width=2)
    d.text((W - PAD - tw - 16, 79), tag, font=f(22, True), fill=(219, 234, 254))

    y = HEAD_H + 40

    # ---------- 区块标题
    def section(y, dot, title, count_text):
        d.rounded_rectangle([PAD, y + 6, PAD + 8, y + 40], radius=4, fill=dot)
        d.text((PAD + 24, y), title, font=f(38, True), fill=INK)
        cw = d.textlength(count_text, font=f(24, True))
        d.text((W - PAD - cw, y + 12), count_text, font=f(24, True), fill=MUTED)
        return y + 66

    y = section(y, ACCENT, "今日 AI 要闻", "TOP 5")

    # ---------- AI 新闻卡片
    for i, it in enumerate(ai_items, 1):
        tx = PAD + 88
        tw_max = W - tx - PAD - 24
        t_lines = wrap(d, it["title"], f(32, True), tw_max, 2)
        s_lines = wrap(d, it["summary"], f(24), tw_max, 3)
        card_h = 34 + len(t_lines) * 42 + (len(s_lines) * 34 if s_lines else 0) + 22
        d.rounded_rectangle([PAD, y, W - PAD, y + card_h], radius=18, fill=CARD, outline=LINE)
        # 序号徽章
        bx, by = PAD + 26, y + 28
        d.ellipse([bx, by, bx + 44, by + 44], fill=ACCENT)
        nw = d.textlength(str(i), font=f(26, True))
        d.text((bx + 22 - nw / 2, by + 7), str(i), font=f(26, True), fill=(255, 255, 255))
        # 标题
        ty = y + 26
        for line in t_lines:
            d.text((tx, ty), line, font=f(32, True), fill=INK)
            ty += 42
        if it["date"]:
            dw = d.textlength(it["date"], font=f(20))
            d.rounded_rectangle([W - PAD - dw - 28, y + 26, W - PAD - 12, y + 60],
                                radius=10, fill=(234, 241, 255))
            d.text((W - PAD - dw - 20, y + 32), it["date"], font=f(20), fill=ACCENT_DARK)
        ty += 4
        for line in s_lines:
            d.text((tx, ty), line, font=f(24), fill=MUTED)
            ty += 34
        y += card_h + 16

    y += 26
    y = section(y, GH, "GitHub 今日趋势", "TOP 5")

    # ---------- GitHub 卡片
    for it in gh_items:
        tx = PAD + 88
        star = it["star"]
        sw = d.textlength(star, font=f(26, True)) + 28
        tw_max = W - tx - PAD - sw - 40
        r_lines = wrap(d, it["repo"], f(30, True), tw_max, 1)
        de_lines = wrap(d, it["desc"], f(24), W - tx - PAD - 24, 3)
        card_h = 30 + len(r_lines) * 40 + (len(de_lines) * 34 if de_lines else 0) + 20
        d.rounded_rectangle([PAD, y, W - PAD, y + card_h], radius=18, fill=CARD, outline=LINE)
        bx, by = PAD + 26, y + 26
        d.ellipse([bx, by, bx + 44, by + 44], fill=GH)
        nw = d.textlength(str(it["rank"]), font=f(26, True))
        d.text((bx + 22 - nw / 2, by + 7), str(it["rank"]), font=f(26, True), fill=(255, 255, 255))
        ty = y + 24
        for line in r_lines:
            d.text((tx, ty), line, font=f(30, True), fill=(22, 32, 58))
            ty += 40
        # Star 徽标
        if star:
            d.rounded_rectangle([W - PAD - sw - 12, y + 24, W - PAD - 16, y + 66],
                                radius=12, fill=GH_SOFT)
            d.text((W - PAD - sw + 2, y + 32), star, font=f(26, True), fill=GH)
        ty += 4
        for line in de_lines:
            d.text((tx, ty), line, font=f(24), fill=MUTED)
            ty += 34
        y += card_h + 16

    # ---------- 底部二维码
    y += 30
    QR = 236
    foot_h = QR + 68
    d.rounded_rectangle([PAD, y, W - PAD, y + foot_h], radius=22, fill=(15, 23, 42))
    qr = make_qr(SITE_URL, QR)
    qx, qy = W - PAD - QR - 34, y + 34
    d.rounded_rectangle([qx - 12, qy - 12, qx + QR + 12, qy + QR + 12], radius=14, fill="white")
    img.paste(qr, (qx, qy))
    fx = PAD + 44
    d.text((fx, y + 52), "扫码看完整版", font=f(40, True), fill=(255, 255, 255))
    text_block(d, fx, y + 116, "近 7 天 AI 新闻全文 + GitHub 今日榜 / 本周榜，含通俗注解",
               f(23), (148, 163, 184), qx - fx - 40, 2, 9)
    d.text((fx, y + 204), "每天 24:00 自动更新", font=f(22, True), fill=(96, 165, 250))
    y += foot_h + 34

    img = img.crop((0, 0, W, y))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path, "PNG", optimize=True)
    return out_path, img.size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="日期 YYYY-MM-DD，默认取 feed.json 最新")
    ap.add_argument("--out", default=None, help="输出路径，默认 output/poster/<date>.png")
    args = ap.parse_args()

    date, entry = read_feed(args.date)
    ai_md = (entry.get("aiNews") or {}).get("markdown", "")
    gh_md = (entry.get("github") or {}).get("markdown", "")
    ai_items = parse_ai_news(ai_md, 5)
    gh_items = parse_github(gh_md, 5)
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
