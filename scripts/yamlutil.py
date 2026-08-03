#!/usr/bin/env python3
"""极简 YAML 子集解析器（零依赖，仅支持本项目用到的语法）。

支持：
  - 注释（# 及之后内容，行内 # 仅当不在引号内时生效）
  - 映射：key: value（value 可为空，随后是缩进子节点）
  - 嵌套映射：以 2 空格缩进表示层级
  - 标量列表：- item（item 为字符串/数字/布尔）
  - 标量类型：自动识别 true/false -> bool，纯整数 -> int，其余 -> str
  - 双引号 / 单引号字符串（引号内 # 不算注释）

不支持：锚点/别名、多行字符串、行内流格式（{} / []）、列表中的映射。
本项目所有 config/ 与 sources/ 文件均遵守上述约束。
"""
import re


def _strip_comment(line: str) -> str:
    # 找到不在引号内的第一个 #
    in_s = in_d = False
    for i, ch in enumerate(line):
        if ch == "'" and not in_d:
            in_s = not in_s
        elif ch == '"' and not in_s:
            in_d = not in_d
        elif ch == "#" and not in_s and not in_d:
            return line[:i]
    return line


def _scalar(val: str):
    v = val.strip()
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    if v == "true":
        return True
    if v == "false":
        return False
    if v == "":
        return ""
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    if v == "[]":
        return []
    if v == "{}":
        return {}
    return v


def _parse_block(lines, idx, indent):
    # 解析从 idx 开始、缩进 >= indent 的块，返回 (value, next_idx)
    # 先判断是映射还是列表
    # 看第一个有效行的形态
    container = None
    i = idx
    n = len(lines)
    while i < n:
        raw = lines[i]
        if raw.strip() == "":
            i += 1
            continue
        lead = len(raw) - len(raw.lstrip(" "))
        if lead < indent:
            break
        content = _strip_comment(raw).strip()
        if content == "":
            i += 1
            continue
        if content.startswith("- "):
            # 列表
            if container is None:
                container = []
            item = _scalar(content[2:])
            container.append(item)
            i += 1
        elif ":" in content:
            # 映射
            if container is None:
                container = {}
            key, _, rest = content.partition(":")
            key = key.strip()
            rest = rest.strip()
            if rest == "":
                # 子块
                child, i = _parse_block(lines, i + 1, lead + 2)
                container[key] = child
            else:
                container[key] = _scalar(rest)
                i += 1
        else:
            i += 1
    if container is None:
        container = {}
    return container, i


def load(text: str):
    lines = text.splitlines()
    value, _ = _parse_block(lines, 0, 0)
    return value


def load_file(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return load(f.read())


if __name__ == "__main__":
    import sys, json
    for p in sys.argv[1:]:
        print("==", p)
        print(json.dumps(load_file(p), ensure_ascii=False, indent=2))
