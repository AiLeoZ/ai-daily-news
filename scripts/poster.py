#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
poster.py —— 由每日 feed.json 生成一张可直接发社交媒体的竖版海报。

版式（深色科技风）：
  · 顶部：品牌标题 + 日期；右上角二维码，标注「扫码查看详情」
  · 今日 AI 要闻（最多 10 条，主篇幅：完整标题，无下方注解）
  · GitHub 今日趋势 TOP 3（项目 + 今日新增 Star + 极简介绍）
  · 底部：引导扫码条

二维码跳转逻辑（qr_url_for）：
  · 站点根地址 SITE_URL 来自 config（runtime.poster.qr_url > site.site_url > 兜底）。
  · 当日（feed.json 中最新一天）海报二维码 → SITE_URL（站点主页）
  · 历史（非最新）海报二维码    → 该日期归档页 SITE_URL + /output/archive/<日期>.html
    这样扫描某天的海报会直接跳到那一天的完整内容页。
  · 后续所有新海报（当日=最新）默认即指向 SITE_URL，无需任何改动。

用法：
  python scripts/poster.py                 # 用 feed.json 里最新的日期
  python scripts/poster.py --date 2026-08-03
  python scripts/poster.py --date 2026-08-03 --out output/poster/2026-08-03.png
  python scripts/poster.py --qr-url https://example.com/xxx   # 手动覆盖二维码地址

依赖：Pillow、qrcode（均已装在托管 venv 中）
"""

import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEED = os.path.join(ROOT, "data", "feed.json")
OUT_DIR = os.path.join(ROOT, "output", "poster")

# 站内按日期归档页的目录（相对站点根）。历史海报二维码跳转到 <SITE_URL>/<ARCHIVE_PREFIX>/<日期>.html
ARCHIVE_PREFIX = "output/archive"

# 公开站点地址（海报二维码指向）：按优先级读取，避免硬编码外网。
#   1) config/runtime.yaml 的 poster.qr_url（离线场景可设为内网/本地地址）
#   2) config/site.yaml 的 site_url
#   3) 历史默认值（仅兜底）
try:
    from yamlutil import load_file
    _SITE_CFG = load_file(os.path.join(ROOT, "config", "site.yaml")) or {}
    _RT_CFG = load_file(os.path.join(ROOT, "config", "runtime.yaml")) or {}
except Exception:
    _SITE_CFG, _RT_CFG = {}, {}
_SITE_URL = (_RT_CFG.get("poster", {}) or {}).get("qr_url") \
    or _SITE_CFG.get("site_url") \
    or "https://aileoz.github.io/ai-daily-news/"
SITE_URL = _SITE_URL


def sorted_dates():
    """返回 feed.json 中所有日期（升序）。"""
    try:
        with open(FEED, "r", encoding="utf-8") as fp:
            feed = json.load(fp)
        return sorted(feed.get("entries", {}).keys())
    except Exception:
        return []


def latest_feed_date():
    """返回 feed.json 中最新（最大）日期；无则返回 None。"""
    ds = sorted_dates()
    return ds[-1] if ds else None


def qr_url_for(date, latest_date=None):
    """按日期返回海报二维码应指向的地址。

    · 当日（date == 最新一天）→ 站点根地址 SITE_URL（用户要求统一指向主站）
    · 历史（date != 最新一天）→ 该日期归档页 SITE_URL + /output/archive/<date>.html
    """
    base = SITE_URL.rstrip("/")
    if latest_date is None:
        latest_date = latest_feed_date() or date
    if date == latest_date:
        return base + "/"
    return "%s/%s/%s.html" % (base, ARCHIVE_PREFIX, date)

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

# 跨平台中文字体解析（macOS / Linux / 仓库内置，任一可用即停，不抛异常）
def _resolve_font():
    repo_fonts = sorted(glob.glob(os.path.join(ROOT, "assets", "fonts", "*.[to]tf")))
    repo_fonts += sorted(glob.glob(os.path.join(ROOT, "assets", "fonts", "*.ttc")))
    for path in repo_fonts:
        yield (path, 0, 0, True)

    if sys.platform == "darwin":
        for path in [
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
        ]:
            yield (path, 0, 1, False)
    else:
        for path in [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        ]:
            yield (path, 0, 0, False)
        for path in sorted(glob.glob("/usr/share/fonts/**/*.[to]tf", recursive=True)):
            yield (path, 0, 0, False)


def _pick_font():
    for path, ri, bi, _ in _resolve_font():
        if not os.path.exists(path):
            continue
        try:
            ImageFont.truetype(path, 20, index=ri)
            print(f"[poster] 使用字体: {path}", file=sys.stderr)
            return path, ri, path, bi
        except Exception:
            continue
    print("[poster] 未找到可用的中文字体，海报文字可能显示异常", file=sys.stderr)
    return None, 0, None, 0


FR_PATH, FR_IDX, FB_PATH, FB_IDX = _pick_font()
_font_cache = {}


def f(size, bold=False):
    key = (size, bold)
    if key not in _font_cache:
        path, idx = (FB_PATH, FB_IDX) if bold else (FR_PATH, FR_IDX)
        if path is None:
            _font_cache[key] = ImageFont.load_default()
        else:
            try:
                _font_cache[key] = ImageFont.truetype(path, size, index=idx)
            except Exception:
                try:
                    _font_cache[key] = ImageFont.truetype(path, size)
                except Exception:
                    _font_cache[key] = ImageFont.load_default()
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


def parse_summary(md, point_limit=6, para_limit=4):
    """解析速览模式摘要（summary.markdown）。

    返回 (paragraphs, points)：
      · paragraphs：摘要综述正文，按段落拆分，最多 para_limit 段
      · points：关键要点列表，最多 point_limit 条
    """
    paragraphs, points = [], []
    if not md:
        return paragraphs, points
    # 按「## 小节」切分：先找「## 摘要」正文、再找「## 关键要点」列表
    sec = re.split(r"^##\s+", md, flags=re.M)
    for block in sec[1:]:
        title = (block.split("\n", 1)[0] if "\n" in block else block).strip()
        body = block.split("\n", 1)[1] if "\n" in block else ""
        if "摘要" in title or "总结" in title:
            for para in re.split(r"\n\s*\n", body):
                t = clean(para)
                if t:
                    paragraphs.append(t)
                    if len(paragraphs) >= para_limit:
                        break
        elif "要点" in title or "亮点" in title or "速览" in title:
            for line in body.split("\n"):
                line = line.strip()
                m = re.match(r"^[-*]\s+(.+)", line)
                if not m:
                    continue
                t = clean(m.group(1))
                if t:
                    points.append(t)
                    if len(points) >= point_limit:
                        break
    return paragraphs, points


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
        # 统一提取日期并内联到标题末尾，格式：（M月D日）或（YYYY-MM-DD）
        date_tag = ""
        m = re.search(r"[（(]([^（()）]*?(?:\d{4}-\d{2}-\d{2}|\d{1,2}月\d{1,2}日))[)）]\s*$", title)
        if m:
            raw = m.group(1).replace(" ", "")
            # 统一转为「M月D日」短格式用于海报展示
            dm = re.match(r"(\d{4})-(\d{2})-(\d{2})", raw)
            if dm:
                date_tag = "%s月%s日" % (int(dm.group(2)), int(dm.group(3)))
            else:
                date_tag = raw
            title = title[: m.start()].strip()
        # 将日期拼回标题末尾，确保换行时日期跟随文字流动、不重叠
        if date_tag:
            title = title + "（" + date_tag + "）"
        items.append({"title": title})
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
    """按像素宽度贪心逐字折行：每行尽量填满到 max_w 才换行，保证所有条目对齐与折行规则一致、不出现单行未满即另起一行。

    ellipsis=False 时，超出 max_lines 的末尾内容直接截断（不追加省略号）。
    """
    d = draw or _measure
    if not text:
        return []
    lines, cur = [], ""
    for ch in text:
        trial = cur + ch
        if d.textlength(trial, font=font) <= max_w:
            cur = trial
            continue
        # 当前行已写到最宽，换行（cur 不含刚溢出的字符）
        lines.append(cur)
        cur = ch
        if len(lines) >= max_lines:
            break
    if cur:
        if len(lines) < max_lines:
            lines.append(cur)
        elif ellipsis:
            # 已达行数上限但仍有剩余：在最后一行追加省略号
            last = lines[-1]
            while last and d.textlength(last + "…", font=font) > max_w:
                last = last[:-1]
            lines[-1] = last.rstrip() + "…"
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


def measure_summary(paragraphs, points, para_fs=24, point_fs=22):
    """预先量出摘要区块内容高度（综述段落 + 关键要点）。

    返回的高度 = 顶部留白(24) + 内容行高总和 + 底部留白(22)，
    与 render() 中的绘制逻辑严格对齐，避免文字溢出卡片。
    """
    tx_w = W - PAD * 2 - 52
    content_h = 0
    for para in paragraphs:
        lines = wrap(para, f(para_fs), tx_w, 12, ellipsis=True)
        content_h += len(lines) * (para_fs + 12)
    if points:
        content_h += 22
        for pt in points:
            plines = wrap("· " + pt, f(point_fs), tx_w, 2, ellipsis=True)
            content_h += len(plines) * (point_fs + 9)
    return 24 + content_h + 22


def measure_gh(items):
    out = []
    for it in items:
        sw = _measure.textlength(it["star"], font=f(25, True)) + 30
        r = wrap(it["repo"], f(29, True), W - (PAD + 92) - PAD - sw - 44, 1)
        de = wrap(it["desc"], f(23), W - (PAD + 92) - PAD - 26, 2)
        out.append((r, de, sw, 26 + len(r) * 39 + (len(de) * 33 if de else 0) + 20))
    return out


def render(date, ai_items, gh_items, out_path, qr_url=None, summary=None):
    ai_m = measure_ai(ai_items)
    gh_m = measure_gh(gh_items)
    if summary:
        sum_paragraphs, sum_points = summary
        sum_h = measure_summary(sum_paragraphs, sum_points)
    else:
        sum_h = 0
    total = (HEAD_H + 34
             + (SEC_H + sum_h + CARD_GAP + 34 if summary else 0)
             + SEC_H + sum(m[1] + CARD_GAP for m in ai_m)
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
    img.paste(make_qr(qr_url or SITE_URL, QR_SIZE), (qx, qy))
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

    # ================= 今日摘要区块（速览模式的摘要，置于 AI 要闻之前）
    if summary:
        sum_paragraphs, sum_points = summary
        y = section(y, (167, 139, 250), "今日摘要", "速览")
        # 综述段落卡片
        sum_tx = PAD + 26
        sum_tw = W - PAD * 2 - 52
        card_h = measure_summary(sum_paragraphs, sum_points)
        d.rounded_rectangle([PAD, y, W - PAD, y + card_h], radius=20,
                            fill=CARD, outline=CARD_LINE, width=1)
        d.rounded_rectangle([PAD, y + 18, PAD + 5, y + card_h - 18], radius=3, fill=(167, 139, 250))
        ty = y + 24
        for para in sum_paragraphs:
            for line in wrap(para, f(24), sum_tw, 12, ellipsis=True):
                d.text((sum_tx, ty), line, font=f(24), fill=SUB)
                ty += 36
        if sum_points:
            ty += 22
            for pt in sum_points:
                for line in wrap("· " + pt, f(22), sum_tw, 2, ellipsis=True):
                    d.text((sum_tx, ty), line, font=f(22), fill=(196, 182, 240))
                    ty += 31
        y += card_h + CARD_GAP + 34

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


def generate_poster(date=None, out_path=None, qr_url=None, ai_limit=10,
                    gh_limit=3, copy_latest=True, with_summary=True):
    """生成单张海报（可复用，供 fix_poster_qr.py 批量调用）。

    date        : YYYY-MM-DD，默认取 feed.json 最新一天
    out_path    : 输出 PNG 路径，默认 output/poster/<date>.png
    qr_url      : 二维码跳转地址；为 None 时按 qr_url_for(date) 自动计算
    copy_latest : 是否同步写入 output/poster/latest.png（仅当日海报需要）
    with_summary: 是否在 AI 要闻之前插入「今日摘要」区块（速览模式摘要）
    返回 (path, size, qr_url)
    """
    date, entry = read_feed(date)
    ai_md = (entry.get("aiNews") or {}).get("markdown", "")
    gh_md = (entry.get("github") or {}).get("markdown", "")
    ai_items = parse_ai_news(ai_md, ai_limit)
    gh_items = parse_github(gh_md, gh_limit)
    if len(ai_items) < 1 or len(gh_items) < 1:
        raise SystemExit("解析失败：AI %d 条 / GitHub %d 条" % (len(ai_items), len(gh_items)))

    summary = None
    if with_summary:
        sum_md = (entry.get("summary") or {}).get("markdown", "")
        paras, _ = parse_summary(sum_md)
        if paras:
            summary = (paras, [])

    if qr_url is None:
        qr_url = qr_url_for(date)
    out = out_path or os.path.join(OUT_DIR, "%s.png" % date)
    path, size = render(date, ai_items, gh_items, out, qr_url=qr_url, summary=summary)

    if copy_latest:
        latest = os.path.join(OUT_DIR, "latest.png")
        Image.open(path).save(latest, "PNG", optimize=True)

    print("[poster] 日期 %s | AI %d 条 | GitHub %d 条 | 摘要 %s | 二维码 -> %s"
          % (date, len(ai_items), len(gh_items),
             ("含 %d 段 / %d 要点" % (len(summary[0]), len(summary[1])) if summary else "无"),
             qr_url))
    for i, it in enumerate(ai_items, 1):
        print("   AI %d. %s" % (i, it["title"][:34]))
    for it in gh_items:
        print("   GH %d. %-42s %s" % (it["rank"], it["repo"], it["star"]))
    print("[poster] 输出 %s  (%dx%d)" % (path, size[0], size[1]))
    if copy_latest:
        print("[poster] 同步 latest.png")
    return path, size, qr_url


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="日期 YYYY-MM-DD，默认取 feed.json 最新")
    ap.add_argument("--out", default=None, help="输出路径，默认 output/poster/<date>.png")
    ap.add_argument("--qr-url", default=None, help="手动指定二维码跳转地址（覆盖按日期自动计算）")
    ap.add_argument("--ai-limit", type=int, default=10, help="AI 新闻最多显示条数（默认 10）")
    ap.add_argument("--gh-limit", type=int, default=3, help="GitHub 趋势显示条数（默认 3）")
    ap.add_argument("--no-latest", action="store_true", help="不写 latest.png")
    args = ap.parse_args()

    qr_url = args.qr_url
    if qr_url is None and args.date is not None:
        qr_url = qr_url_for(args.date)
    path, size, qr_url = generate_poster(
        date=args.date, out_path=args.out, qr_url=qr_url,
        ai_limit=args.ai_limit, gh_limit=args.gh_limit,
        copy_latest=not args.no_latest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
