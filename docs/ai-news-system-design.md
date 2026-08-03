# 云端自动化 AI 资讯网页系统 — 完整方案

> 目标：一套**无需本地参与**、由云端定时任务驱动、自动采集→筛选→构建→归档→部署的 AI 资讯站点系统。
> 本方案在现有「AI 每日资讯」站点实践基础上抽象成通用架构，可直接落地为生产级系统。

---

## 一、总体架构

系统由三层组成，全部运行在云端：

```
┌──────────────────────────────────────────────────────────────┐
│                      云端存储 + 版本管理                        │
│  （Git 仓库 / 对象存储，所有文件受版本控制，可回滚）            │
└──────────────────────────────────────────────────────────────┘
        │                      │                      │
  ┌─────▼─────┐        ┌──────▼──────┐        ┌──────▼──────┐
  │ 配置与源   │        │  生成引擎    │        │  产物与展示  │
  │ 定义层     │──驱动──▶│ (采集·筛选· │──产出──▶│ (静态站点)  │
  │ config/    │        │  构建)       │        │ output/     │
  │ sources/   │        │ scripts/     │        │ archive/    │
  │ templates/ │        └──────┬──────┘        │ index.html  │
  └────────────┘               │ 触发          │ history.html│
                               ▼               └──────┬──────┘
                        ┌──────────────┐               │
                        │ 定时调度器    │               │
                        │ 每日固定时刻  │───────────────┘ 用户访问
                        └──────────────┘
```

- **配置与源定义层**：声明"站点长什么样、从哪采、采什么"，与代码解耦。
- **生成引擎层**：读取配置与源，执行采集、筛选、构建，产出静态网页。
- **产物与展示层**：当日页面 + 历史归档 + 历史索引，对外提供访问。
- **定时调度器**：每天固定时刻拉起生成引擎，全程无本地参与。
- **版本管理**：包裹全部文件，每日构建自动提交，历史既可回溯（Git）也可浏览（archive）。

---

## 二、代码结构（云端文件）

推荐目录布局（与现有项目平滑兼容）：

```
/ (云端工作区根)
├── config/
│   └── site.yaml              # 站点配置：标题、更新频率、展示字段、主题
├── sources/                   # 资讯源定义（与代码解耦，可热更新）
│   ├── rss.yaml               # RSS 源列表
│   ├── apis.yaml              # API 接口 / 网页抓取源（如 GitHub Trending）
│   └── keywords.yaml          # 关键词 / 主题列表（用于联网搜索）
├── templates/                 # 网页模板（布局与展示逻辑）
│   ├── index.html             # 首页模板（落地 → 最新日；含历史跳转）
│   ├── page.html              # 单日页面模板（AI 新闻 + GitHub 趋势）
│   └── assets/
│       ├── app.js             # 渲染 / 历史切换 / 年-月-日选择逻辑
│       └── style.css
├── scripts/                   # 生成脚本模块
│   ├── collect.py             # 资讯采集：RSS / API / 关键词搜索
│   ├── filter.py              # 内容筛选：去重、相关度打分、时间排序、Top-N
│   ├── build.py               # 网页构建：渲染模板 → 当日页 + 索引
│   └── lib/                   # 公共库（HTTP、Markdown、渲染等）
├── data/
│   └── raw/                   # 每日原始采集结果（YYYY-MM-DD_*.md）
├── output/                    # 构建产物（最终部署的静态站点）
│   ├── index.html             # 首页：指向当日最新
│   ├── history.html           # 历史记录页：按日期倒序列出所有过往
│   └── archive/               # 历史归档目录（每日一页）
│       ├── 2026-08-03.html
│       └── 2026-08-04.html
└── .git/                      # 版本管理
```

### 2.1 数据配置文件 `config/site.yaml`

```yaml
site:
  title: "AI 每日资讯"
  subtitle: "每天追踪最新 AI 动态与 GitHub 趋势"
  timezone: "Asia/Shanghai"
  update_frequency: "daily"     # daily / hourly / custom
  update_time: "23:59"          # 本地时区的触发时刻
  theme: "light"

display:
  sections:
    - id: aiNews
      title: "AI 新闻"
      fields: [title, date, summary, why, note]   # 展示字段
      max_items: 10
      sort: "date_desc"            # 严格时间倒序
      headline_count: 5            # 今日要闻条数
    - id: github
      title: "GitHub 趋势"
      subsections: [daily, weekly]
      top_n: 10
      show_note: true             # 注解用大白话
```

**设计要点**：站点标题、更新频率、展示字段全部参数化，改配置即改站，无需动代码。

### 2.2 资讯源定义文件 `sources/`

**`sources/rss.yaml`**（结构化订阅源）
```yaml
- name: "OpenAI Blog"
  type: rss
  url: "https://openai.com/blog/rss.xml"
  section: aiNews
- name: "Google Research Blog"
  type: rss
  url: "https://research.google/blog/rss/"
  section: aiNews
```

**`sources/apis.yaml`**（接口 / 抓取源）
```yaml
- name: "GitHub Trending (日)"
  type: scrape
  url: "https://github.com/trending?since=daily"
  section: github
  sub: daily
- name: "GitHub Trending (周)"
  type: scrape
  url: "https://github.com/trending?since=weekly"
  section: github
  sub: weekly
- name: "NewsAPI-AI"
  type: rest
  url: "https://newsapi.org/v2/everything"
  params: { q: "AI OR LLM", language: "zh" }
  key_env: NEWS_API_KEY            # 密钥走环境变量，不入库
  section: aiNews
```

**`sources/keywords.yaml`**（关键词 / 主题检索）
```yaml
topics:
  - "大模型"
  - "LLM"
  - "AI Agent"
  - "多模态"
  - "开源模型"
search_provider: web_search        # 联网搜索
lookback_days: 7                    # 近 7 天窗口
section: aiNews
```

**设计要点**：三类来源（RSS / API·抓取 / 关键词）覆盖"被动订阅 + 主动检索"，新增源只改 YAML，生成引擎自动识别 `type` 分发处理。

---

## 三、生成脚本模块

| 脚本 | 职责 | 关键逻辑 |
|------|------|----------|
| `collect.py` | 资讯采集 | 遍历 `sources/*.yaml`，按 `type` 调对应采集器（RSS 解析 / HTTP 抓取 / 搜索 API），产出 `data/raw/YYYY-MM-DD_*.md` 原始内容 |
| `filter.py` | 内容筛选 | 去重（标题/链接相似度）、相关度打分（匹配 `keywords`）、按日期时间倒序、取 `max_items` / `top_n`；生成结构化中间数据 |
| `build.py` | 网页构建 | 读取 `config/site.yaml` + 中间数据，渲染 `templates/page.html` → `output/archive/YYYY-MM-DD.html`；重建 `output/index.html`（指向最新）与 `output/history.html`（倒序列出全部日期） |

**每日独立文件保证**：`build.py --date $DATE` 始终生成 `output/archive/$DATE.html`；同日期重跑为**幂等覆盖**（更新当日内容），跨日期互不影响。

**首页指向最新**：`output/index.html` 在每次构建后重写，内含当日页面链接 + 历史入口；也可做 302 重定向或前端自动跳转，确保"用户每日访问即见当天最新"。

---

## 四、任务调度机制

### 4.1 调度方式（云端、无需本地）

- **方案 A（推荐，本环境可用）**：使用云端自动化（Automation）配置 `FREQ=DAILY;BYHOUR=23;BYMINUTE=59`，触发一个"运行器"：
  ```bash
  DATE=$(TZ=Asia/Shanghai date +%F)
  python3 scripts/collect.py  --date $DATE
  python3 scripts/filter.py   --date $DATE
  python3 scripts/build.py    --date $DATE
  # 部署
  <cloud-deploy> output/        # 将 output/ 发布为静态站点
  git add -A && git commit -m "build: $DATE"
  ```
- **方案 B（通用云）**：云函数 + 云调度（如 Cron/EventBridge）或 CI 定时流水线，拉起同一套脚本。

### 4.2 调度保证

1. **每日独立命名**：产物强制以 `YYYY-MM-DD` 命名，天然隔离。
2. **自动更新首页**：构建末段重写 `index.html` 指向当日。
3. **零本地参与**：从采集到部署全程云端，用户仅访问 URL。
4. **失败可观测**：采集/筛选异常时，生成引擎保留上一日页面、仅记录告警，不破坏站点。

---

## 五、云端文件管理策略

### 5.1 统一云端存储 + 版本管理
- 全部文件（模板、配置、源定义、脚本、历史网页）存入**同一云端仓库 / 对象存储**。
- 启用 **Git 版本管理**：每次构建 `git commit`，完整历史可追溯、可回滚到任意一日。
- 密钥（API Key）只走**环境变量 / 密钥管理**，绝不入库。

### 5.2 历史归档与回溯
- 每日构建后，新页面自动落入 `output/archive/$DATE.html`。
- `output/history.html` 按**日期倒序**列出所有过往日期链接；首页提供"历史记录"入口与**年/月/日精确选择**控件（已在前序迭代实现）。
- 用户每日访问 `index.html` → 看当天最新；点击任意历史日期 → 看该日快照。

### 5.3 数据生命周期
- `data/raw/`：原始采集，可保留 30–90 天后归档冷存。
- `output/archive/`：长期保留，构成完整时间线。
- 重大改版时通过 Git tag 标记版本基线。

---

## 六、与现有项目的映射 / 迁移路径

| 现有 | 方案中的角色 |
|------|--------------|
| `index.html` + `assets/` | → `templates/` 模板层 |
| `data/feed.json` + `data/raw/` | → `data/raw/` + 新增 `output/archive/` 静态页 |
| `scripts/update_feed.py` | → 拆分为 `collect.py` / `filter.py` / `build.py` |
| 23:59 自动化 | → 第四节调度机制 |
| 年/月/日选择器 | → 历史页标准组件 |

**迁移建议**：先补 `config/site.yaml` 与 `sources/*.yaml` 抽离硬编码，再把 `update_feed.py` 拆为采集/筛选/构建三段，最后让 `build.py` 额外产出 `output/archive/$DATE.html` 与 `history.html`。现有 feed.json 渲染方式可保留作为"单文件轻量模式"的兼容路径。

---

## 七、风险与扩展

- **源失效**：某 RSS/API 下线 → 采集器降级跳过并告警，不影响当日产出。
- **重复/低质**：`filter.py` 的相关度阈值与去重可配置，避免灌水。
- **扩展多渠道**：新增平台只需在 `sources/` 加一条 YAML（支持 `type: plugin` 自定义采集器）。
- **多语言/多主题**：`config/site.yaml` 的 `theme`、语言字段可扩展；同类系统可复制仓库快速建站。
- **成本**：纯静态 + 定时构建，资源占用极低，适合常驻云端。
