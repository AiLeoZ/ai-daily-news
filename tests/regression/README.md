# 回归测试用例说明（跨模型一致性）

本目录配合 `scripts/regression_check.py` 与 `config/consistency-spec.json`，用于**验证不同底层模型产出的结构一致性**。

## 一、设计目标

换模型（如 Hy3 → Claude / DeepSeek）时，不要求文风字字相同，但要求**结构契约一致**：

- 相同的二级标题集合
- 相同的条目数容差（AI 新闻 8–10 条）
- 相同的表格列与行数（GitHub 日/周榜各 10 行、列固定）
- 相同的禁语约束（无「通俗解释」、无 `since=`）
- 相同的日期一致性（feed 键 == 文件名 == 内嵌日期，复用 `validate_dates.py`）

## 二、断言集（`config/consistency-spec.json`）

数据驱动，按 section 组织：

| section | 关键断言 |
|---|---|
| `aiNews` | 含 `## 🔝 今日要闻` + `## 近期其他要闻`；`###` 条目数 ∈ [8,10]；正文含「为什么关注」「注解」；禁「通俗解释」；标题日期时间倒序 |
| `github` | 含 `## 一、今日榜` + `## 二、本周榜`；标题禁 `since=`；日/周榜表头列固定；各 10 行；每行项目格含 `repo-desc` |
| `summary` | 含 `## 摘要` + `## 关键要点`；禁「通俗解释」 |

## 三、运行方式

```bash
# 1) 单模型产出校验（退出码 0/1）
python3 scripts/regression_check.py check data/raw/2026-08-04_ai.md --section aiNews
python3 scripts/regression_check.py check data/raw/2026-08-04_github.md --section github
python3 scripts/regression_check.py check data/raw/2026-08-04_summary.md --section summary

# 2) 跨模型结构等价比对（换模型必跑）
python3 scripts/regression_check.py --ref <ref模型产出.md> --cand <cand模型产出.md> --section aiNews

# 3) 内置 fixtures 自证逻辑正确
python3 scripts/regression_check.py selftest

# 4) 日期 1:1 一致性（防止速览/海报串用）
python3 scripts/validate_dates.py
```

## 四、回归用例矩阵

| 用例 | 输入 | 期望 |
|---|---|---|
| `selftest-good` | 内置合规样例 | `check` 全过 |
| `selftest-bad` | 内置违规样例（缺 h2、有 `since=`、无 repo-desc） | `check` 至少一项失败 |
| `real-8-04` | 仓库真实 `data/raw/2026-08-04_*.md` | 三 section 全过 |
| `cross-model` | ref=旧模型 / cand=新模型 同日期产出 | `compare` 判 PASS |

## 五、不一致时的处置

`compare` 判 FAIL 时，**优先定位为模板措辞偏差（非结构）**，必要时派生 `config/prompts/task-orchestration.v2.md` 并登记 `registry.json`，**不回退到依赖模型专属特性**。详见 `docs/automation-task-spec.md` §7–§8。
