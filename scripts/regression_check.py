#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
跨模型一致性 / 回归校验器（模型无关，纯标准库，无第三方依赖）。

子命令：
  check   <file> --section aiNews|github|summary [--date YYYY-MM-DD]
          对单个模型的产出做断言校验，打印 SELF_CHECK 报告，退出码 0/1。
  compare --ref <ref.md> --cand <cand.md> --section S
          对参考模型(ref)与候选模型(cand)做结构等价比对，输出一致性报告。
  selftest
          运行内置最小 fixtures，自证逻辑正确（good 应通过、bad 应失败）。

断言来源：config/consistency-spec.json（数据驱动，随提示词模板版本演进）。

退出码：0 = 全部通过；1 = 任一检查失败；2 = 用法错误。
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SPEC = os.path.join(HERE, "..", "config", "consistency-spec.json")

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")


def load_spec(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def is_sep_row(cells):
    return len(cells) > 0 and all(re.match(r"^:?-+:?$", c.strip()) for c in cells)


def parse_md(text):
    """极简 Markdown 解析：抽取 h2/h3 标题与表格（含表头与数据行）。

    表格识别：以行首 '|' 判定；首个表格行作为表头，其后连续表格行中，
    仅「分隔行」（每格均为 --- / :--: 之类）被跳过，其余均为数据行。
    遇到非表格、非标题行则结束当前表格。
    """
    h2, h3, tables = [], [], []
    cur = None
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if cur is None:
                cur = {"header": cells, "rows": []}
                tables.append(cur)
                continue
            if is_sep_row(cells):
                continue
            cur["rows"].append(cells)
        else:
            m = HEADING_RE.match(ln)
            if m:
                level = len(m.group(1))
                title = m.group(2).strip()
                if level == 2:
                    h2.append(title)
                elif level == 3:
                    h3.append(title)
            cur = None
    return {"h2": h2, "h3": h3, "tables": tables}


def parse_title_date(s, spec, year):
    m = re.search(spec["date"]["title_date_regex"], s)
    if not m:
        return None
    d = m.group(1)
    if re.match(r"\d{4}-\d{2}-\d{2}", d):
        y, mo, da = map(int, d.split("-"))
        return (y, mo, da)
    mm = re.match(r"(\d+)月(\d+)日", d)
    if mm:
        return (year, int(mm.group(1)), int(mm.group(2)))
    return None


def run_section(section, text, spec, date=None):
    cfg = spec["sections"][section]
    parsed = parse_md(text)
    results = []
    year = int(date.split("-")[0]) if date else 2026

    # 1) required_h2（子串匹配，容忍标题后缀如日期范围）
    for i, need in enumerate(cfg.get("required_h2", [])):
        ok = any(need in h for h in parsed["h2"])
        results.append({
            "id": f"{section}-h2-{i+1}",
            "desc": f'含二级标题「{need}」',
            "pass": ok,
            "detail": "" if ok else "缺失",
        })

    if section == "aiNews":
        items = parsed["h3"]
        n = len(items)
        lo, hi = cfg["item_min"], cfg["item_max"]
        results.append({
            "id": f"{section}-count",
            "desc": f"条目数在 [{lo},{hi}]（实际 {n}）",
            "pass": lo <= n <= hi,
            "detail": "" if lo <= n <= hi else "超出容差",
        })
        for marker in cfg.get("required_body_markers", []):
            cnt = text.count(marker)
            results.append({
                "id": f"{section}-marker-{marker}",
                "desc": f'正文含「{marker}」（出现 {cnt} 次）',
                "pass": cnt >= 1,
                "detail": "" if cnt >= 1 else "未出现",
            })
        for ph in cfg.get("forbidden_phrases", []):
            bad = ph in text
            results.append({
                "id": f"{section}-forbid-{ph}",
                "desc": f'不含禁语「{ph}」',
                "pass": not bad,
                "detail": "命中" if bad else "",
            })
        dates = [parse_title_date(t, spec, year) for t in items]
        paired = [(t, d) for t, d in zip(items, dates) if d is not None]
        if paired:
            ok_order = all(paired[i][1] >= paired[i + 1][1] for i in range(len(paired) - 1))
            results.append({
                "id": f"{section}-order",
                "desc": "日期严格时间倒序（越近越靠前）",
                "pass": ok_order,
                "detail": "" if ok_order else "存在更晚日期插在前面",
            })
        else:
            results.append({
                "id": f"{section}-order",
                "desc": "日期严格时间倒序",
                "pass": True,
                "detail": "标题无解析到日期，跳过严格校验",
            })

    elif section == "github":
        for ph in cfg.get("forbidden_in_h2", []):
            bad = any(ph in h for h in parsed["h2"])
            results.append({
                "id": f"{section}-forbid-h2-{ph}",
                "desc": f'二级标题不含「{ph}」',
                "pass": not bad,
                "detail": "命中" if bad else "",
            })
        daily = next((t for t in parsed["tables"] if cfg["daily_marker"] in t["header"]), None)
        weekly = next((t for t in parsed["tables"] if cfg["weekly_marker"] in t["header"]), None)
        for name, tbl, cols in (("daily", daily, cfg["daily_columns"]), ("weekly", weekly, cfg["weekly_columns"])):
            if tbl is None:
                results.append({"id": f"github-{name}-table", "desc": f"含{name}榜表格", "pass": False, "detail": "未找到"})
                continue
            head_ok = tbl["header"][:len(cols)] == cols
            results.append({
                "id": f"github-{name}-cols",
                "desc": f"{name}榜表头列匹配 {cols}",
                "pass": head_ok,
                "detail": "" if head_ok else str(tbl["header"]),
            })
            rn = len(tbl["rows"])
            lo, hi = cfg["rows_min"], cfg["rows_max"]
            results.append({
                "id": f"github-{name}-rows",
                "desc": f"{name}榜行数在 [{lo},{hi}]（实际 {rn}）",
                "pass": lo <= rn <= hi,
                "detail": "" if lo <= rn <= hi else "超出容差",
            })
            proj_ok = all(len(r) > 1 and cfg["project_cell_must_contain"] in r[1] for r in tbl["rows"])
            results.append({
                "id": f"github-{name}-repodesc",
                "desc": f"{name}榜每行项目格含「{cfg['project_cell_must_contain']}」",
                "pass": proj_ok,
                "detail": "" if proj_ok else "存在缺失",
            })

    elif section == "summary":
        for ph in cfg.get("forbidden_phrases", []):
            bad = ph in text
            results.append({
                "id": f"{section}-forbid-{ph}",
                "desc": f'不含禁语「{ph}」',
                "pass": not bad,
                "detail": "命中" if bad else "",
            })

    return results


def metrics(section, text, spec):
    parsed = parse_md(text)
    if section == "aiNews":
        return {"h2": sorted(parsed["h2"]), "items": len(parsed["h3"])}
    if section == "github":
        g = spec["sections"]["github"]
        daily = next((t for t in parsed["tables"] if g["daily_marker"] in t["header"]), None)
        weekly = next((t for t in parsed["tables"] if g["weekly_marker"] in t["header"]), None)
        return {
            "h2": sorted(parsed["h2"]),
            "daily_rows": len(daily["rows"]) if daily else 0,
            "weekly_rows": len(weekly["rows"]) if weekly else 0,
        }
    if section == "summary":
        return {"h2": sorted(parsed["h2"])}
    return {}


def report(results, header=""):
    if header:
        print(header)
    passed = sum(1 for r in results if r["pass"])
    total = len(results)
    print("─" * 56)
    for r in results:
        mark = "✓" if r["pass"] else "✗"
        line = f"  [{mark}] {r['id']}: {r['desc']}"
        if r["detail"]:
            line += f"  ({r['detail']})"
        print(line)
    print("─" * 56)
    print(f"  通过 {passed}/{total}")
    print("SELF_CHECK: " + json.dumps({r["id"]: r["pass"] for r in results}, ensure_ascii=False))
    return passed == total


def cmd_check(args, spec):
    if not os.path.exists(args.file):
        print(f"ERROR: 文件不存在 {args.file}")
        return 1
    text = open(args.file, encoding="utf-8").read()
    results = run_section(args.section, text, spec, args.date)
    ok = report(results, header=f"# check {args.file}  section={args.section}")
    return 0 if ok else 1


def cmd_compare(args, spec):
    for p in (args.ref, args.cand):
        if not os.path.exists(p):
            print(f"ERROR: 文件不存在 {p}")
            return 1
    ref = open(args.ref, encoding="utf-8").read()
    cand = open(args.cand, encoding="utf-8").read()
    r1 = run_section(args.section, ref, spec, args.date)
    r2 = run_section(args.section, cand, spec, args.date)
    m1, m2 = metrics(args.section, ref, spec), metrics(args.section, cand, spec)
    consistent = all(r["pass"] for r in r1) and all(r["pass"] for r in r2) and m1 == m2
    print(f"# compare ref={args.ref} cand={args.cand}  section={args.section}")
    print(f"  ref 指标: {json.dumps(m1, ensure_ascii=False)}")
    print(f"  cand指标: {json.dumps(m2, ensure_ascii=False)}")
    print(f"  ref 全过: {all(r['pass'] for r in r1)} | cand 全过: {all(r['pass'] for r in r2)}")
    print(f"  结构指标一致: {m1 == m2}")
    print(f"  >>> 一致性判定: {'PASS ✅' if consistent else 'FAIL ❌'}")
    return 0 if consistent else 1


def _build_good_doc():
    items = []
    dates = ["2026-08-04", "8月3日", "8月2日", "8月1日", "7月31日", "7月30日", "7月29日", "7月28日"]
    for i, d in enumerate(dates, 1):
        items.append(
            f"### {i}. 标题{i}（{d}）\n事件说明段落。\n- **为什么关注**：行业意义{i}。\n- **注解**：大白话说明{i}。\n"
        )
    ai = "## 🔝 今日要闻\n\n" + items[0] + "\n## 近期其他要闻\n\n" + "\n".join(items[1:]) + "\n"

    daily_rows = "\n".join(
        f"| {i} | [o/r{i}](u{i})<br><span class=\"repo-desc\">简介{i}</span> | +{i*10} | 注{i} |"
        for i in range(1, 11)
    )
    weekly_rows = "\n".join(
        f"| {i} | [o/r{i}](u{i})<br><span class=\"repo-desc\">简介{i}</span> | {100+i} | +{i*10} | 注{i} |"
        for i in range(1, 11)
    )
    gh = (
        "## 一、今日榜（2026-08-04）\n\n"
        "| 排名 | 项目 | 今日新增 Star | 注解 |\n|:---:|------|:---:|---|\n"
        f"{daily_rows}\n\n"
        "## 二、本周榜（2026-07-28 ~ 2026-08-04）\n\n"
        "| 排名 | 项目 | 总 Star | 本周新增 | 注解 |\n|:---:|------|:---:|:---:|---|\n"
        f"{weekly_rows}\n\n"
    )
    su = "## 摘要\n一段连贯的概括。\n## 关键要点\n- 要点一。\n- 要点二。\n"
    return ai + gh + su


def _build_bad_doc():
    # 缺 🔝、缺 近期其他要闻、仅 1 条、含禁语、github 标题含 since= 且无 repo-desc
    ai = (
        "## 今日要闻\n\n"
        "### 1. 标题（2026-08-04）\n事件。这里用了通俗解释四个字来蒙混。\n\n"
    )
    gh = (
        "## 一、今日榜（since=daily）\n\n"
        "| 排名 | 项目 | 今日新增 Star |\n|:---:|------|:---:|\n"
        "| 1 | [o/r](u) | +10 |\n\n"
    )
    su = "## 摘要\n一段。\n"
    return ai + gh + su


def cmd_selftest(spec):
    print("# selftest")
    good, bad = _build_good_doc(), _build_bad_doc()
    ok_good = all(
        all(r["pass"] for r in run_section(s, good, spec, "2026-08-04"))
        for s in ("aiNews", "github", "summary")
    )
    ok_bad = any(
        any(not r["pass"] for r in run_section(s, bad, spec, "2026-08-04"))
        for s in ("aiNews", "github", "summary")
    )
    print(f"  good 全 section 应通过: {ok_good}")
    print(f"  bad  至少一项应失败:    {ok_bad}")
    print(f"  >>> selftest: {'PASS ✅' if (ok_good and ok_bad) else 'FAIL ❌'}")
    return 0 if (ok_good and ok_bad) else 1


def build_parser():
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--date", default="2026-08-04", help="日期 YYYY-MM-DD，用于解析中文日期")
    parent.add_argument("--spec", default=DEFAULT_SPEC, help="断言集 JSON 路径")

    ap = argparse.ArgumentParser(description="跨模型一致性/回归校验器")
    sub = ap.add_subparsers(dest="cmd")

    p_check = sub.add_parser("check", parents=[parent], help="校验单个模型产出")
    p_check.add_argument("file", help="待校验 Markdown 文件")
    p_check.add_argument("--section", required=True, choices=["aiNews", "github", "summary"])

    p_cmp = sub.add_parser("compare", parents=[parent], help="跨模型结构等价比对")
    p_cmp.add_argument("--ref", required=True, help="参考模型产出文件")
    p_cmp.add_argument("--cand", required=True, help="候选模型产出文件")
    p_cmp.add_argument("--section", required=True, choices=["aiNews", "github", "summary"])

    sub.add_parser("selftest", parents=[parent], help="运行内置 fixtures 自证")
    return ap


def main():
    ap = build_parser()
    args = ap.parse_args()
    spec = load_spec(args.spec)

    if args.cmd == "selftest":
        return cmd_selftest(spec)
    if args.cmd == "compare":
        return cmd_compare(args, spec)
    if args.cmd == "check":
        return cmd_check(args, spec)

    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
