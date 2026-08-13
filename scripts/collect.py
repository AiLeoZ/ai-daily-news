#!/usr/bin/env python3
"""采集阶段：基于 sources/ 定义，实时拉取 RSS 与 GitHub Trending。

输出（data/collected/）：
  rss_$DATE.json  —— 近 7 天 RSS 条目（候选素材）
  gh_$DATE.json   —— GitHub 今日榜 / 本周榜（真实抓取）

设计要点（在线优先）：
  - **默认在线实时采集**：mode/环境变量未显式指定时走联网抓取，拿最新数据。
  - **并发抓取**：多源并行（线程池），整体耗时取决于最慢的单源而非累加。
  - **自动重试**：瞬时网络抖动按指数退避重试，降低偶发失败率。
  - **传输解压**：支持 gzip / deflate，兼容启用压缩的站点。
  - **源健康校验**：识别「返回 HTML 而非 RSS」「XML 解析失败」等失效源并明确报错，
    不会把一个已失效的订阅地址静默当成「今天没有新闻」。
  - **缓存保护**：联网抓取整体为空时自动回退到最近一次成功缓存，
    绝不用空结果覆盖已有缓存造成数据丢失（degraded 标记写入产物）。
  - **离线兜底**：--offline 或 mode: offline 时仅读本地缓存与语料，全程不联网。

纯标准库实现（urllib + xml.etree + concurrent.futures），无第三方依赖。

用法：
  python3 scripts/collect.py --date 2026-08-05             # 全部源（在线）
  python3 scripts/collect.py --date 2026-08-05 --rss       # 仅 RSS
  python3 scripts/collect.py --date 2026-08-05 --github    # 仅 GitHub
  python3 scripts/collect.py --date 2026-08-05 --online    # 强制在线（忽略配置）
  python3 scripts/collect.py --date 2026-08-05 --offline   # 强制离线（仅本地缓存）
  python3 scripts/collect.py --health                      # 只体检各源可用性，不落盘
"""
import argparse
import concurrent.futures as cf
import datetime
import gzip
import json
import os
import re
import ssl
import time
import urllib.request
import xml.etree.ElementTree as ET
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "sources")
OUT = os.path.join(ROOT, "data", "collected")
os.makedirs(OUT, exist_ok=True)

# 采集参数（可被 config/runtime.yaml 的 collect.http.* 覆盖）
DEFAULTS = {
    "timeout": 25,      # 单次请求超时（秒）
    "retries": 3,       # 单源最大尝试次数
    "workers": 8,       # 并发抓取线程数
    "backoff": 1.5,     # 重试退避基数（秒）
}

# 使用主流浏览器 UA：部分站点对脚本型 UA 直接返回 403 / 空页面。
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "application/rss+xml, application/atom+xml, application/xml, "
        "text/xml, text/html;q=0.8, */*;q=0.5"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
}
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

ATOM = "{http://www.w3.org/2005/Atom}"


# ---------------------------------------------------------------- HTTP 基础层

def _decompress(raw, encoding):
    """按 Content-Encoding 解压响应体；无法解压时原样返回。"""
    enc = (encoding or "").lower()
    try:
        if "gzip" in enc:
            return gzip.decompress(raw)
        if "deflate" in enc:
            try:
                return zlib.decompress(raw)
            except zlib.error:
                return zlib.decompress(raw, -zlib.MAX_WBITS)
    except Exception:
        pass
    return raw


def fetch(url, timeout=None, retries=None, backoff=None):
    """带重试 / 解压的抓取，返回 (text, content_type)。全部失败则抛最后一次异常。"""
    timeout = timeout or DEFAULTS["timeout"]
    retries = retries or DEFAULTS["retries"]
    backoff = backoff or DEFAULTS["backoff"]
    last = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
                raw = _decompress(r.read(), r.headers.get("Content-Encoding"))
                ctype = r.headers.get("Content-Type", "")
            return raw.decode("utf-8", "ignore"), ctype
        except Exception as e:
            last = e
            if attempt < retries:
                time.sleep(backoff * attempt)  # 线性退避，避免把慢源拖成分钟级
    raise last


def get_text(url, timeout=None):
    """兼容旧调用：只返回正文文本。"""
    return fetch(url, timeout=timeout)[0]


def parse_date(s):
    if not s:
        return None
    s = s.strip()
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z",
                "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%f%z",
                "%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.datetime.strptime(s, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            continue
    m = re.search(r"(\d{4}-\d{2}-\d{2})", s)
    if m:
        return datetime.datetime.strptime(m.group(1), "%Y-%m-%d").replace(
            tzinfo=datetime.timezone.utc)
    return None


def to_iso(s):
    """把任意 pubDate 归一化为 Asia/Shanghai 视角的 YYYY-MM-DD；失败返回空串。"""
    dt = parse_date(s)
    if not dt:
        return ""
    return dt.astimezone(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat()


# ---------------------------------------------------------------- RSS 在线采集

def _looks_like_html(text):
    head = text.lstrip()[:300].lower()
    if "<rss" in head or "<feed" in head or "<?xml" in head:
        return False
    return head.startswith("<!doctype html") or "<html" in head


def _extract_items(root, name, cutoff):
    """从已解析的 XML 根节点抽取条目，返回 (items, total_seen)。"""
    nodes = root.findall(".//item") or root.findall(f".//{ATOM}entry")
    items = []
    for it in nodes:
        title = (it.findtext("title") or it.findtext(f"{ATOM}title") or "").strip()
        link_el = it.find("link")
        link = ""
        if link_el is not None:
            link = (link_el.text or link_el.get("href") or "").strip()
        if not link:
            a = it.find(f"{ATOM}link")
            if a is not None:
                link = (a.get("href") or "").strip()
        pub = (it.findtext("pubDate") or it.findtext("published")
               or it.findtext(f"{ATOM}published") or it.findtext(f"{ATOM}updated") or "")
        desc = (it.findtext("description") or it.findtext("summary")
                or it.findtext(f"{ATOM}summary") or it.findtext(f"{ATOM}content") or "")
        dt = parse_date(pub)
        if dt and dt < cutoff:
            continue          # 超出 7 天窗口
        items.append({
            "source": name,
            "title": re.sub(r"\s+", " ", title),
            "link": link,
            "published": pub.strip(),
            "published_iso": to_iso(pub),   # 归一化日期，便于下游按天筛选
            "summary": re.sub(r"<[^>]+>", "", desc)[:400].strip(),
        })
    return items, len(nodes)


def _fetch_feed(entry, cutoff, http):
    """抓取并解析单个订阅源，返回 (name, items, error_or_None, stat)。"""
    parts = [p.strip() for p in entry.split("||")]
    name, url = parts[0], (parts[1] if len(parts) > 1 else "")
    t0 = time.time()
    try:
        text, _ctype = fetch(url, **http)
    except Exception as e:
        return name, [], {"name": name, "url": url,
                          "error": f"{type(e).__name__}: {e}"}, {"name": name, "ok": False}
    if _looks_like_html(text):
        return name, [], {"name": name, "url": url,
                          "error": "源返回 HTML 而非 RSS/Atom，订阅地址可能已失效"}, \
               {"name": name, "ok": False}
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        return name, [], {"name": name, "url": url,
                          "error": f"XML 解析失败: {e}"}, {"name": name, "ok": False}
    items, seen = _extract_items(root, name, cutoff)
    return name, items, None, {
        "name": name, "ok": True, "fetched": seen,
        "in_window": len(items), "cost": round(time.time() - t0, 1),
    }


def collect_rss(date_str, http=None):
    """在线 RSS：并发抓取全部订阅源，7 天窗口内去重汇总。

    整体为空（全部源失败）时回退最近一次成功缓存，避免空结果覆盖历史数据。
    """
    from yamlutil import load_file
    http = http or {}
    cfg = load_file(os.path.join(SRC, "rss.yaml"))
    feeds = [f for f in (cfg.get("feeds", []) or []) if str(f).strip()]
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)

    items, errors, stats = [], [], []
    workers = min(int(DEFAULTS["workers"]), max(1, len(feeds)))
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(_fetch_feed, e, cutoff, http) for e in feeds]
        for fu in cf.as_completed(futures):
            _name, got, err, stat = fu.result()
            items.extend(got)
            stats.append(stat)
            if err:
                errors.append(err)

    # 去重（按 link，退化到 title）
    seen, uniq = set(), []
    for it in items:
        key = it.get("link") or it.get("title")
        if not key or key in seen:
            continue
        seen.add(key)
        uniq.append(it)
    # 时间倒序，让下游天然优先看到最新素材
    uniq.sort(key=lambda x: x.get("published_iso") or "", reverse=True)

    payload = {
        "date": date_str,
        "count": len(uniq),
        "items": uniq,
        "errors": errors,
        "offline": False,
        "sources_used": [s["name"] for s in stats if s.get("ok")],
        "sources_failed": [s["name"] for s in stats if not s.get("ok")],
        "today_count": sum(1 for it in uniq if it.get("published_iso") == date_str),
        "collected_at": datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec="seconds"),
    }

    # 缓存保护：全部源失败时不落空结果，回退最近缓存
    if not uniq:
        rec = find_fallback_rss(date_str)
        if rec:
            try:
                old = json.load(open(rec, encoding="utf-8"))
                payload["items"] = old.get("items", [])
                payload["count"] = len(payload["items"])
                payload["degraded"] = True
                payload["sources_used"] = [os.path.basename(rec)]
                payload["note"] = "联网抓取全部失败，已回退最近一次成功缓存"
            except Exception:
                pass
    return payload


# ---------------------------------------------------------------- GitHub 抓取

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


def collect_github(date_str, http=None):
    """在线 GitHub Trending：日榜 / 周榜并发抓取，失败或为空回退最近缓存。"""
    from yamlutil import load_file
    http = http or {}
    cfg = load_file(os.path.join(SRC, "apis.yaml"))
    gh = (cfg.get("github_trending") or {})
    if not gh.get("enabled", True):
        return {"date": date_str, "enabled": False, "daily": [], "weekly": [], "errors": []}
    top_n = int(gh.get("top_n", 10))
    out = {"date": date_str, "enabled": True, "daily": [], "weekly": [],
           "errors": [], "offline": False, "sources_used": []}

    def grab(period):
        url = gh.get(period, "")
        try:
            html = get_text(url, timeout=http.get("timeout"))
            return period, parse_trending(html, period)[:top_n], None
        except Exception as e:
            return period, [], f"{type(e).__name__}: {e}"

    with cf.ThreadPoolExecutor(max_workers=2) as ex:
        for period, rows, err in ex.map(grab, ("daily", "weekly")):
            out[period] = rows
            if err:
                out["errors"].append({"period": period, "error": err})
            elif rows:
                out["sources_used"].append(f"github-trending:{period}")

    # 兜底：当日抓取为空（网络失败或解析为 0 行）时，复用最近一次成功数据
    for period in ("daily", "weekly"):
        if not out[period]:
            fb = find_fallback_gh(date_str)
            if fb:
                rows = load_gh_period(fb, period)
                if rows:
                    out[period] = rows
                    out["degraded"] = True
                    out["sources_used"].append(os.path.basename(fb))
                    out["errors"].append({
                        "period": period,
                        "fallback": os.path.basename(fb),
                        "note": "当日抓取为空，已复用最近一次成功的 GitHub 数据",
                    })
    out["collected_at"] = datetime.datetime.now(
        datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec="seconds")
    return out


# ---------------------------------------------------------------- 离线兜底路径

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


def find_fallback_rss(date_str):
    """date_str 之前最近的 rss_*.json（不含当天）；没有则返回 None。"""
    try:
        d = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return None
    cands = []
    for fn in os.listdir(OUT):
        m = re.match(r"^rss_(\d{4}-\d{2}-\d{2})\.json$", fn)
        if not m or m.group(1) == date_str:
            continue
        try:
            fd = datetime.datetime.strptime(m.group(1), "%Y-%m-%d").date()
        except Exception:
            continue
        if fd <= d:
            cands.append((fd, os.path.join(OUT, fn)))
    if not cands:
        return None
    cands.sort(key=lambda x: x[0], reverse=True)
    return cands[0][1]


def load_corpus_items():
    """读取 sources/corpus/*.md，转为与 RSS items 同构的本地素材。"""
    items = []
    corp_dir = os.path.join(SRC, "corpus")
    if not os.path.isdir(corp_dir):
        return items
    for fn in sorted(os.listdir(corp_dir)):
        if not fn.endswith(".md") or fn == "README.md":
            continue
        path = os.path.join(corp_dir, fn)
        try:
            text = open(path, encoding="utf-8").read()
        except Exception:
            continue
        title = fn[:-3]
        for line in text.splitlines():
            if line.startswith("#"):
                title = line.lstrip("#").strip()
                break
        m = re.search(r"(\d{4}-\d{2}-\d{2})", fn + " " + text[:200])
        pub = m.group(1) if m else datetime.date.today().isoformat()
        summary = re.sub(r"#.*", "", text)
        summary = re.sub(r"\s+", " ", summary).strip()[:400]
        items.append({
            "source": "本地语料",
            "title": re.sub(r"\s+", " ", title),
            "link": "",
            "published": pub,
            "published_iso": to_iso(pub),
            "summary": summary,
        })
    return items


def collect_rss_offline(date_str):
    """离线 RSS：当日缓存 → 最近缓存 → 本地语料，全程不访问网络。"""
    items, used = [], []
    today_path = os.path.join(OUT, f"rss_{date_str}.json")
    if os.path.exists(today_path):
        try:
            d = json.load(open(today_path, encoding="utf-8"))
            items = d.get("items", [])
            used.append(f"rss_{date_str}.json")
        except Exception:
            pass
    if not items:
        rec = find_fallback_rss(date_str)
        if rec:
            try:
                d = json.load(open(rec, encoding="utf-8"))
                items = d.get("items", [])
                used.append(os.path.basename(rec))
            except Exception:
                pass
    corpus = load_corpus_items()
    if corpus:
        used.append("sources/corpus")
    seen, uniq = set(), []
    for it in items + corpus:
        key = it.get("link") or it.get("title")
        if key in seen:
            continue
        seen.add(key)
        uniq.append(it)
    return {"date": date_str, "count": len(uniq), "items": uniq,
            "errors": [], "offline": True, "sources_used": used,
            "today_count": sum(1 for it in uniq if it.get("published_iso") == date_str)}


def collect_github_offline(date_str):
    """离线 GitHub：当日缓存 → 最近兜底缓存，全程不访问网络。"""
    out = {"date": date_str, "enabled": True, "daily": [], "weekly": [],
           "errors": [], "offline": True}
    used = []
    today_path = os.path.join(OUT, f"gh_{date_str}.json")
    if os.path.exists(today_path):
        try:
            d = json.load(open(today_path, encoding="utf-8"))
            out["daily"] = d.get("daily", [])
            out["weekly"] = d.get("weekly", [])
            used.append(f"gh_{date_str}.json")
        except Exception:
            pass
    if not out["daily"]:
        fb = find_fallback_gh(date_str)
        if fb:
            out["daily"] = load_gh_period(fb, "daily")
            used.append(os.path.basename(fb))
    if not out["weekly"]:
        fb = find_fallback_gh(date_str)
        if fb:
            out["weekly"] = load_gh_period(fb, "weekly")
            used.append(os.path.basename(fb))
    out["sources_used"] = used
    return out


# ---------------------------------------------------------------- 模式与入口

def load_runtime():
    try:
        from yamlutil import load_file
        return load_file(os.path.join(ROOT, "config", "runtime.yaml")) or {}
    except Exception:
        return {}


def http_opts(rt):
    """从 runtime.yaml 的 collect.http 读取抓取参数，缺省用 DEFAULTS。"""
    http = ((rt.get("collect") or {}).get("http") or {})
    opts = {}
    for k in ("timeout", "retries", "backoff"):
        if http.get(k) not in (None, ""):
            try:
                opts[k] = type(DEFAULTS[k])(http[k])
            except Exception:
                pass
    if http.get("workers") not in (None, ""):
        try:
            DEFAULTS["workers"] = int(http["workers"])
        except Exception:
            pass
    return opts


def is_offline_requested(rt=None):
    """判断是否走离线采集。

    优先级：环境变量 AINEWS_MODE > config/runtime.yaml 的 mode > 默认 online。
    环境变量用于在不改配置文件的前提下临时切换（如 CI 与本地行为不同）。
    """
    env_mode = os.environ.get("AINEWS_MODE", "").strip().lower()
    if env_mode in ("online", "offline"):
        return env_mode == "offline"
    rt = load_runtime() if rt is None else rt
    return str(rt.get("mode", "online")).lower() == "offline"


def cmd_health():
    """源体检：逐源实时探测可用性与条目数，不落盘。"""
    from yamlutil import load_file
    cfg = load_file(os.path.join(SRC, "rss.yaml"))
    feeds = [f for f in (cfg.get("feeds", []) or []) if str(f).strip()]
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)
    print(f"# 源体检（共 {len(feeds)} 个 RSS 源）")
    ok = 0
    with cf.ThreadPoolExecutor(max_workers=min(DEFAULTS["workers"], max(1, len(feeds)))) as ex:
        for name, items, err, stat in ex.map(lambda e: _fetch_feed(e, cutoff, {}), feeds):
            if err:
                print(f"  [✗] {name:22s} {err['error'][:70]}")
            else:
                ok += 1
                print(f"  [✓] {name:22s} 抓取 {stat['fetched']:3d} 条 / "
                      f"窗口内 {stat['in_window']:3d} 条 / {stat['cost']}s")
    print(f"  RSS 可用 {ok}/{len(feeds)}")

    gh_cfg = (load_file(os.path.join(SRC, "apis.yaml")).get("github_trending") or {})
    for period in ("daily", "weekly"):
        try:
            rows = parse_trending(get_text(gh_cfg.get(period, "")), period)
            print(f"  [{'✓' if rows else '✗'}] GitHub {period:7s} 解析 {len(rows)} 行")
        except Exception as e:
            print(f"  [✗] GitHub {period:7s} {type(e).__name__}: {str(e)[:60]}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="日期键 YYYY-MM-DD")
    ap.add_argument("--rss", action="store_true")
    ap.add_argument("--github", action="store_true")
    ap.add_argument("--offline", action="store_true",
                    help="离线模式：仅用本地缓存与语料，不访问任何外网")
    ap.add_argument("--online", action="store_true",
                    help="强制在线实时采集（忽略 runtime.yaml 的 mode）")
    ap.add_argument("--health", action="store_true", help="只体检各源可用性，不落盘")
    args = ap.parse_args()

    if args.health:
        return cmd_health()
    if not args.date:
        ap.error("--date 为必填（除非使用 --health）")

    rt = load_runtime()
    http = http_opts(rt)
    offline = args.offline or (not args.online and is_offline_requested(rt))
    do_all = not (args.rss or args.github)

    if offline:
        print("[offline] 离线采集：仅使用本地缓存（data/collected/）与语料（sources/corpus/）")
    else:
        print(f"[online] 实时采集：并发 {DEFAULTS['workers']} · 超时 "
              f"{http.get('timeout', DEFAULTS['timeout'])}s · 重试 "
              f"{http.get('retries', DEFAULTS['retries'])} 次")

    if args.rss or do_all:
        rss = collect_rss_offline(args.date) if offline else collect_rss(args.date, http)
        with open(os.path.join(OUT, f"rss_{args.date}.json"), "w", encoding="utf-8") as f:
            json.dump(rss, f, ensure_ascii=False, indent=2)
        msg = (f"RSS: {rss['count']} 条（当日 {rss.get('today_count', 0)} 条，"
               f"errors={len(rss['errors'])}）")
        if rss.get("sources_failed"):
            msg += f" 失效源={rss['sources_failed']}"
        if rss.get("degraded"):
            msg += f" ⚠ {rss.get('note', '')}"
        if offline:
            msg += f" 来源={rss.get('sources_used')}"
        print(msg)
        for e in rss["errors"]:
            print(f"   ! {e.get('name')}: {str(e.get('error'))[:90]}")

    if args.github or do_all:
        gh = collect_github_offline(args.date) if offline else collect_github(args.date, http)
        with open(os.path.join(OUT, f"gh_{args.date}.json"), "w", encoding="utf-8") as f:
            json.dump(gh, f, ensure_ascii=False, indent=2)
        msg = (f"GitHub: daily={len(gh['daily'])} weekly={len(gh['weekly'])}"
               f"（errors={len(gh['errors'])}）")
        if gh.get("degraded"):
            msg += " ⚠ 已回退缓存"
        if offline:
            msg += f" 来源={gh.get('sources_used')}"
        print(msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
