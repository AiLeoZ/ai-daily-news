#!/usr/bin/env python3
"""采集阶段：基于 sources/ 定义，自动拉取 RSS 与 GitHub Trending。

输出（data/collected/）：
  rss_$DATE.json  —— 近 7 天 RSS 条目（候选素材）
  gh_$DATE.json   —— GitHub 今日榜 / 本周榜（真实抓取）

纯标准库实现（urllib + xml.etree + re），无第三方依赖；任何 python3 均可运行。
网络不可达或解析失败时优雅降级（写出空列表 + error 字段），不影响后续流程。

用法：
  python3 scripts/collect.py --date 2026-08-03            # 全部源
  python3 scripts/collect.py --date 2026-08-03 --rss      # 仅 RSS
  python3 scripts/collect.py --date 2026-08-03 --github   # 仅 GitHub
"""
import argparse
import datetime
import json
import os
import re
import ssl
import urllib.request
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "sources")
OUT = os.path.join(ROOT, "data", "collected")
os.makedirs(OUT, exist_ok=True)

UA = {"User-Agent": "Mozilla/5.0 (compatible; AINewsBot/1.0)"}
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def get_text(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return r.read().decode("utf-8", "ignore")


def parse_date(s):
    if not s:
        return None
    s = s.strip()
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z",
               "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            return datetime.datetime.strptime(s, fmt).replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            continue
    m = re.search(r"(\d{4}-\d{2}-\d{2})", s)
    return datetime.datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc) if m else None


def collect_rss(date_str):
    from yamlutil import load_file
    cfg = load_file(os.path.join(SRC, "rss.yaml"))
    feeds = cfg.get("feeds", []) or []
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)
    items = []
    errors = []
    for entry in feeds:
        parts = [p.strip() for p in entry.split("||")]
        name, url = parts[0], parts[1]
        try:
            xml = get_text(url)
            root = ET.fromstring(xml)
            # RSS 2.0
            nodes = root.findall(".//item")
            if not nodes:
                # Atom
                nodes = root.findall(".//{http://www.w3.org/2005/Atom}entry")
            for it in nodes:
                title = (it.findtext("title") or it.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
                link_el = it.find("link")
                link = (link_el.text or link_el.get("href") or "") if link_el is not None else ""
                pub = (it.findtext("pubDate") or it.findtext("published") or
                       it.findtext("{http://www.w3.org/2005/Atom}published") or "")
                desc = (it.findtext("description") or it.findtext("summary") or
                        it.findtext("{http://www.w3.org/2005/Atom}summary") or "")
                dt = parse_date(pub)
                if dt and dt < cutoff:
                    continue
                items.append({
                    "source": name,
                    "title": re.sub(r"\s+", " ", title),
                    "link": link.strip(),
                    "published": pub,
                    "summary": re.sub(r"<[^>]+>", "", desc)[:400].strip(),
                })
        except Exception as e:
            errors.append({"source": name, "error": f"{type(e).__name__}: {e}"})
    # 去重（按 link 或 title）
    seen, uniq = set(), []
    for it in items:
        key = it["link"] or it["title"]
        if key in seen:
            continue
        seen.add(key)
        uniq.append(it)
    return {"date": date_str, "count": len(uniq), "items": uniq, "errors": errors}


def parse_trending(html, period):
    chunks = html.split('<article class="Box-row">')[1:]
    rows = []
    for c in chunks:
        m = re.search(r'<h2[^>]*>\s*<a[^>]*href="/([^"/]+)/([^"/]+)"', c)
        if not m:
            continue
        owner, repo = m.group(1), m.group(2)
        full = f"{owner}/{repo}"
        lang = re.search(r'itemprop="programmingLanguage">([^<]+)<', c)
        lang = lang.group(1).strip() if lang else ""
        desc = re.search(r'<p[^>]*>([^<]*)</p>', c)
        desc = re.sub(r"\s+", " ", desc.group(1)).strip() if desc else ""
        # 本期新增（"N stars today" / "N stars this week"）
        gained = re.search(r'([\d,]+)\s*stars\s+(?:today|this week)', c)
        gained = int(gained.group(1).replace(",", "")) if gained else 0
        # 总 Star：取 stargazers 链接内的数字（避免误抓"新增"数字）
        total = re.search(r'href="/[^"]+/stargazers"[^>]*>(.*?)</a>', c, re.S)
        if total:
            # 先剥掉 <svg>…</svg>，否则会误抓 path 坐标里的数字
            inner = re.sub(r"<svg.*?</svg>", " ", total.group(1), flags=re.S)
            inner = re.sub(r"<[^>]+>", " ", inner)
            num = re.search(r'([\d,]+(?:\.\d+)?k?)', inner.replace("\n", " ").strip(), re.I)
            if num:
                raw = num.group(1).replace(",", "")
                total = int(float(raw[:-1]) * 1000) if raw.lower().endswith("k") else int(raw)
            else:
                total = 0
        else:
            total = 0
        if total < gained:  # 兜底：总数不应小于新增
            total = gained
        rows.append({
            "rank": len(rows) + 1,
            "repo": full,
            "url": f"https://github.com/{full}",
            "language": lang,
            "description": desc,
            "total_stars": total,
            "gained": gained,
            "period": period,
        })
    return rows


def find_fallback_gh(date_str):
    """返回 date_str 之前最近的 gh_*.json 路径（不含当天）；没有则返回 None。"""
    try:
        d = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return None
    cands = []
    for fn in os.listdir(OUT):
        m = re.match(r"^gh_(\d{4}-\d{2}-\d{2})\.json$", fn)
        if not m or m.group(1) == date_str:
            continue
        try:
            fd = datetime.datetime.strptime(m.group(1), "%Y-%m-%d").date()
        except Exception:
            continue
        if fd < d:
            cands.append((fd, os.path.join(OUT, fn)))
    if not cands:
        return None
    cands.sort(key=lambda x: x[0], reverse=True)
    return cands[0][1]


def load_gh_period(fallback_path, period):
    """从兜底文件读取某周期的榜单并重新编号；失败返回 []。"""
    try:
        with open(fallback_path, encoding="utf-8") as f:
            data = json.load(f)
        rows = [r for r in (data.get(period) or []) if isinstance(r, dict)]
        for i, r in enumerate(rows):
            r["rank"] = i + 1
        return rows
    except Exception:
        return []


def collect_github(date_str):
    from yamlutil import load_file
    cfg = load_file(os.path.join(SRC, "apis.yaml"))
    gh = (cfg.get("github_trending") or {})
    if not gh.get("enabled", True):
        return {"date": date_str, "enabled": False, "daily": [], "weekly": [], "errors": []}
    top_n = int(gh.get("top_n", 10))
    out = {"date": date_str, "enabled": True, "daily": [], "weekly": [], "errors": []}
    for period in ("daily", "weekly"):
        url = gh.get(period, "")
        try:
            html = get_text(url)
            rows = parse_trending(html, period)[:top_n]
            out[period] = rows
        except Exception as e:
            out["errors"].append({"period": period, "error": f"{type(e).__name__}: {e}"})
        # 兜底：当日抓取为空（网络失败或解析为 0 行）时，复用最近一次成功数据
        if not out[period]:
            fb = find_fallback_gh(date_str)
            if fb:
                rows = load_gh_period(fb, period)
                if rows:
                    out[period] = rows
                    out["errors"].append({
                        "period": period,
                        "fallback": os.path.basename(fb),
                        "note": "当日抓取为空，已复用最近一次成功的 GitHub 数据",
                    })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="日期键 YYYY-MM-DD")
    ap.add_argument("--rss", action="store_true")
    ap.add_argument("--github", action="store_true")
    args = ap.parse_args()
    do_all = not (args.rss or args.github)

    if args.rss or do_all:
        rss = collect_rss(args.date)
        with open(os.path.join(OUT, f"rss_{args.date}.json"), "w", encoding="utf-8") as f:
            json.dump(rss, f, ensure_ascii=False, indent=2)
        print(f"RSS: {rss['count']} 条（errors={len(rss['errors'])}）")

    if args.github or do_all:
        gh = collect_github(args.date)
        with open(os.path.join(OUT, f"gh_{args.date}.json"), "w", encoding="utf-8") as f:
            json.dump(gh, f, ensure_ascii=False, indent=2)
        print(f"GitHub: daily={len(gh['daily'])} weekly={len(gh['weekly'])}（errors={len(gh['errors'])}）")


if __name__ == "__main__":
    main()
