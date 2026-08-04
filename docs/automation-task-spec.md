# 可移植自动化任务规范（模型无关）

> **目的**：定义一套「与底层大模型无关的」任务契约、上下文传递结构、自检协议、评估标准、版本化提示词模板与回归测试机制。
> 目标是在把底层模型从 A（如 Hy3）切换到 B（如 Claude / DeepSeek / 任意其他模型）时，**无需重写任务逻辑**，只需切换提示词模板版本并跑回归，即可保证产出的**结构、条数、文风一致、可复现**。
>
> **与本仓库分层关系**：
> - 本文件 = **编排层契约**（怎么把任务可靠地交给任意模型）。
> - `docs/generation-guide.md` = **内容生成规则**（具体的 Markdown 结构、条数、文风，仍适用，且本身已是模型无关）。
> - `docs/ai-news-system-design.md` = **系统架构**（采集/聚合/构建/部署流水线）。
> 三者分治：换模型只动本规范与提示词模板，不动生成规则与流水线代码。

---

## 0. 适用范围

- 任何「输入为数据/上下文、输出为确定性结构文档」的周期性自动化任务。
- 本仓库以「AI 每日资讯」为参考实现（AI 新闻 / GitHub 趋势 / 每日速览）。

---

## 1. 设计原则（核心）

| # | 原则 | 含义 |
|---|---|---|
| P1 | **模型无关** Model-agnostic | 只依赖「通用指令跟随 + 通用文本生成」这一最小公约数；不依赖任何模型专属能力（函数调用、特定思维链格式、特定温度行为、专属工具）。 |
| P2 | **中性表述** Neutral phrasing | 提示词用「你是一名训练有素的助手，请执行…」；**禁止出现模型名、厂商名、专属特性词**（如「用你的推理能力」「作为 Claude…」）。 |
| P3 | **确定性接口** Deterministic contract | 所有 I/O 用预定义 schema（JSON / 固定 Markdown 骨架），模型只填空、不决定结构。 |
| P4 | **规则替代发挥** Rules over vibes | 把主观判断（何为「重要」、如何排序）全部前置为确定性规则 + 范例；模型只做「按规则把真实信息填进来」。 |
| P5 | **可回归** Regressible | 每个版本有可机器校验的断言集；换模型即跑回归，输出一致性可得分。 |
| P6 | **优雅降级** Graceful degradation | 网络/工具失败不中断；缺数据则少列或标「暂无描述」，不编造。 |

---

## 2. 任务契约（Task Contract）

任一子任务都用如下字段描述（与 `config/prompts/registry.json` 中每个模板版本一致）：

| 字段 | 说明 |
|---|---|
| `objective` | 一句话任务目标 |
| `inputs` | 输入来源（文件/工具/上下文键）与格式 |
| `outputs` | 输出落盘路径与格式（强制骨架） |
| `constraints` | 硬约束（条数、结构、禁语、真实性） |
| `evaluation` | 评估标准与阈值（见 §5） |
| `self_check` | 发布前必须全过的自检项（见 §4） |

### 2.5 参考实现：把「AI 每日资讯」拆为 3 个子任务契约

| 子任务 | objective | outputs | 关键约束 |
|---|---|---|---|
| `aiNews` | 生成当日 AI 新闻（今日要闻 + 近期其他要闻） | `data/raw/$DATE_ai.md` | 10 条（8–10 容差）、今日要闻≤4、时间倒序、每条含「为什么关注 + 注解」、禁「通俗解释」 |
| `github` | 生成 GitHub 日榜/周榜 | `data/raw/$DATE_github.md` | 两块各 10 行、列固定、项目格含 `repo-desc`、标题无 `since=` |
| `summary` | 生成每日速览（统一总结） | `data/raw/$DATE_summary.md` | 仅 `## 摘要` + `## 关键要点` 两区、不引入新事实、数字可溯源 |

---

## 3. 标准化上下文传递结构（Context Schema）

定义跨轮次、跨模型一致传递的上下文对象。**只要传入此结构，无论底层模型如何替换，产出应结构一致。**

```json
{
  "schema_version": "1.0",
  "task": "ai-daily-news",
  "prompt_template_version": "v1",
  "date": "2026-08-04",
  "timezone": "Asia/Shanghai",
  "model": { "id": "hy3", "note": "可替换为任意模型标识，不影响任务契约" },
  "prior_summary": "<上一次执行的高层摘要，用于连续性>",
  "inputs": {
    "collected_rss": "data/collected/rss_2026-08-04.json",
    "collected_gh": "data/collected/gh_2026-08-04.json",
    "keywords": "sources/keywords.yaml"
  },
  "rules_ref": "docs/generation-guide.md",
  "self_check_results": [
    { "id": "aiNews-01", "pass": true, "detail": "条数=10 在 [8,10]" }
  ]
}
```

**传递规则**：
1. 每轮起始读取 `.workbuddy/automations/<id>/memory.md` 作为连续性上下文（高层级），**不要**把全量历史对话塞回 prompt（避免不同模型的上下文窗口/截断行为差异导致漂移）。
2. 真实素材（RSS/GitHub）以**文件路径引用**，而非内联全文，避免上下文膨胀与模型差异导致的截断行为不同。
3. `self_check_results` 必须回写，作为下一轮可观测状态。
4. **切换模型时：仅改 `model.id` 与（必要时）`prompt_template_version`，其余不变** → 输出应结构一致。

---

## 4. 自检协议（Self-Check Protocol）

- **结构化**：每个检查项有稳定 ID（如 `aiNews-01`）、描述、PASS/FAIL。
- **门控 Gating**：任一 FAIL 必须先修正再进入下一流水线步骤（调用 `filter.py` / `build.py`）。
- **机器优先**：能用脚本断言的（条数、禁语、结构、日期一致性）由 `scripts/regression_check.py` 自动跑；需人判的（文风是否「IT 小白友好」）保留人工项但给出判别锚点（标杆范例）。
- 检查项 ID 化清单（与 `generation-guide.md` 第 4 节对齐）：

| ID | 检查项 | 类型 |
|---|---|---|
| `aiNews-01` | 条数在 [8,10] 且序号连续 | 自动 |
| `aiNews-02` | 含 `## 🔝 今日要闻` 与 `## 近期其他要闻` | 自动 |
| `aiNews-03` | 今日要闻均为当天；其余严格时间倒序 | 自动（部分从软） |
| `aiNews-04` | 每条含「为什么关注」+「注解」；注解无「通俗解释」 | 自动+人工 |
| `github-01` | 两块各 10 行、列固定、项目格含 `repo-desc` | 自动 |
| `github-02` | 标题无 `since=` | 自动 |
| `summary-01` | 仅 `## 摘要` + `## 关键要点`；无新事实 | 自动+人工 |
| `date-01` | feed 键 == 文件名日期 == 内嵌日期（复用 `validate_dates.py`） | 自动 |

---

## 5. 评估标准（Evaluation Criteria）

分为**自动（A）**与**人工（H）**两类，给出阈值：

| 编号 | 标准 | 权重 | 阈值 |
|---|---|---|---|
| A1 | 结构保真：required_h2 / 表格列 / item 数在 [min,max] | 高 | 全过 |
| A2 | 约束合规：禁语命中=0、日期格式正确、无 `since=` | 一票否决 | 0 命中 |
| A3 | 日期一致性：feed 键==文件名==内嵌日期 | 高 | 全一致 |
| A4 | 真实性：数字/项目名可追溯到 collected/搜索（抽样） | 中 | 抽样 100% 可溯 |
| H1 | 文风一致：对照标杆范例，IT 小白友好度 | 中 |  reviewer 通过 |
| H2 | 信息密度：事件说明带关键数字、不堆形容词 | 中 | reviewer 通过 |

**一致性评分（换模型用）**：对参考模型 `ref` 与候选模型 `cand` 各跑 A1–A4，得到通过向量与关键结构指标（条数、h2 集合、表行数）。两者向量相同且指标相等即判「一致」。

---

## 6. 版本化提示词模板

- 目录：`config/prompts/`，语义化版本 `v1` / `v2` …
- 每个模板含：`objective / inputs / outputs / constraints / self_check / placeholders` 与**中性提示词正文**。
- 注册表 `config/prompts/registry.json` 记录 `active` 版本、各版本元信息、变更日志、迁移说明。
- **切换模型 ≠ 切换模板**；仅当新模型长期偏离结构时，才派生 `v2` 微调措辞，且不破坏既有结构契约。

---

## 7. 回归测试与一致性验证

- **工具**：`scripts/regression_check.py`（纯标准库，无第三方依赖）
  - `check <md> --section aiNews|github|summary --date D`：对单模型产出做断言校验 → 退出码 0/1，并打印 SELF_CHECK 报告。
  - `compare <ref.md> <cand.md> --section S`：结构等价性比对 → 输出一致性报告（PASS/FAIL + 指标差）。
  - `--selftest`：内置最小 fixtures 自证逻辑正确。
- **断言集来源**：`config/consistency-spec.json`（数据驱动，随模板版本演进）。
- **标准流程（换模型时）**：
  1. 用同一日期数据，以新模型生成 `cand` 产出。
  2. 跑 `check` 确认 `cand` 自身通过 A1–A4。
  3. 跑 `compare` 历史 `ref`（旧模型同日期产出）→ 结构等价则接纳。
  4. 不一致时优先定位为「模板措辞」偏差（非结构），必要时派生 `v2`，不回退到依赖模型特性。
- **测试资产**：`tests/regression/` 含用例说明与样例 fixtures。

---

## 8. 切换模型操作清单（Checklist）

- [ ] 仅改调用方传入的 `model.id`（与 `context.model.id`）。
- [ ] 复用同一 `prompt_template_version`（除非已派生 v2）。
- [ ] 同日期数据生成 `cand` 产出。
- [ ] `python3 scripts/regression_check.py check <cand> --section ...` 全过。
- [ ] `python3 scripts/regression_check.py compare <ref> <cand> --section ...` 判「一致」。
- [ ] `python3 scripts/validate_dates.py` 全过（日期 1:1 不串用）。
- [ ] 全过则接纳；否则按 §7 定位偏差，不回退到模型专属特性。
