# AI 每日资讯 · AI Daily News

一个**完全云端运行、每日自动更新**的 AI 资讯站：每天定时抓取最新 AI 动态与 GitHub 趋势，由大模型自动成稿，编译为纯静态站点并发布到 GitHub Pages，同时生成可分享的社媒海报（带扫码跳转二维码）。

> 无需本地常驻电脑、无需人工干预。你只需要提供一个 LLM API Key，每天早上打开网站即可看到当日更新。

---

## ✨ 功能特性

- **全自动云端流水线**：采集 → 生成 → 构建 → 发布，全部在 GitHub Actions 上跑，本地零依赖。
- **每日定时更新**：默认北京时间每天 **06:00** 自动出刊（UTC `0 22 * * *`）。
- **三大内容板块**：
  - AI 新闻（今日要闻 + 近期其他要闻，每条带「为什么关注」+「注解」）
  - GitHub 趋势（日榜 / 周榜 TOP 10）
  - 每日速览（统一摘要 + 关键要点）
- **纯静态、零运行时 JS 依赖**：Markdown 在构建期预渲染为 HTML，浏览器端不会因脚本失败而白屏（归档页 / 速览页尤其稳）。
- **社媒海报**：每日自动生成竖版海报（含二维码），可直接发朋友圈 / 社群。
- **模型无关（Model-agnostic）**：内容生成走一套与底层模型解耦的任务契约 + 版本化提示词模板，换模型不重写逻辑。
- **优雅降级**：联网采集单源失败自动重试；整体失败回退最近缓存，绝不用空结果覆盖历史。

---

## 🌐 线上地址

| 内容 | 地址 |
|---|---|
| 网站主页 | https://aileoz.github.io/ai-daily-news/ |
| 当日速览 | `…/output/summary/latest.html` |
| 当日海报 | `…/output/poster/latest.png` |
| 历史某天归档页 | `…/output/archive/<YYYY-MM-DD>.html` |
| 历史某天海报 | `…/output/poster/<YYYY-MM-DD>.png` |

---

## 🏗️ 工作原理（流水线）

```text
┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│  采集 collect │ → │  生成 generate│ → │  聚合 filter │ → │  构建 build   │ → │  发布 deploy  │
│ (RSS+GitHub) │   │ (LLM 成稿)   │   │ (写 feed.json)│   │ (站点+海报)  │   │ (Pages+QR)  │
└──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘
        │                  │                  │                  │                  │
   data/collected    data/raw/$DATE_*   data/feed.json   output/{archive,    GitHub Pages
   sources/corpus                              │           summary,poster}/     + 校验
                                       regression_check    index.html
```

**步骤说明**

1. **采集** `scripts/collect.py`：联网抓取 RSS + GitHub Trending，写入 `data/collected/`（离线时复用最近缓存）。
2. **生成** `scripts/generate.py`：调用 DeepSeek 等 LLM，按契约写出 `data/raw/$DATE_{ai,github,summary}.md`。
3. **门禁校验** `scripts/regression_check.py`：对三块内容做结构 / 条数 / 禁语断言，不通过则中止发布。
4. **聚合** `scripts/filter.py`：把原始 Markdown 写入 `data/feed.json`（站点唯一数据源）。
5. **构建速览页** `scripts/build_summary.py`：生成 `output/summary/$DATE.html`。
6. **生成海报** `scripts/poster.py`：生成 `output/poster/$DATE.png` 并同步 `latest.png`。
7. **构建站点** `scripts/build.py`：生成归档页 / 首页 / 历史索引，并把海报与速览路径回写 feed 资产索引。
8. **日期一致性校验** `scripts/validate_dates.py`：确保 feed 键 == 文件名 == 内嵌日期严格 1:1。
9. **发布**：提交推送 → GitHub Pages 部署（`daily.yml` 的 `deploy` job）。

---

## 📁 目录结构

```text
.
├── index.html                 # 站点首页（SPA 壳，按日期加载 feed.json）
├── requirements.txt           # 云端运行时依赖（Pillow / qrcode / markdown）
├── .github/workflows/
│   └── daily.yml              # 云端全自动流水线（采集→生成→构建→发布→部署）
├── scripts/
│   ├── collect.py             # 采集 RSS + GitHub 趋势
│   ├── generate.py            # LLM 成稿（无人值守环境用）
│   ├── filter.py              # 聚合写入 feed.json
│   ├── build_summary.py       # 构建速览页
│   ├── poster.py              # 生成社媒海报（含二维码）
│   ├── build.py               # 构建归档/首页/历史索引
│   ├── regression_check.py    # 内容门禁（结构/条数/禁语断言）
│   ├── validate_dates.py       # 日期 1:1 一致性校验
│   ├── fix_poster_qr.py       # 批量修复历史海报二维码（按日期）
│   ├── run_daily.sh           # 本地/launchd 兜底编译脚本（不含 LLM）
│   └── yamlutil.py            # 配置读取工具
├── config/
│   ├── site.yaml              # 站点配置（标题/地址/板块/上限）—— 改站只动这里
│   ├── runtime.yaml           # 运行时开关（online/offline、LLM、git、deploy）
│   ├── consistency-spec.json  # 回归断言数据
│   └── prompts/               # 版本化提示词模板（模型无关）
├── sources/
│   ├── rss.yaml               # RSS 订阅源
│   ├── apis.yaml              # GitHub Trending 等接口定义
│   └── corpus/                # 离线语料
├── data/
│   ├── collected/             # 采集缓存
│   ├── raw/                   # 当日原始成稿（ai / github / summary）
│   ├── feed.json              # 聚合数据源（站点读取）
│   └── logs/                  # 运行日志
├── output/
│   ├── archive/               # 每日归档页 HTML
│   ├── summary/               # 每日速览页 HTML
│   └── poster/                # 每日海报 PNG（含 latest.png）
├── docs/                      # 系统设计 / 自动化规范 / 生成规则 / 云端部署指南
└── tests/regression/          # 回归测试 fixtures
```

---

## 🚀 部署（GitHub Pages + Actions）

仓库已配置好 `.github/workflows/daily.yml`，触发方式：

- `schedule`：每日北京时间 06:00 自动运行
- `push` 到 `main`：推送即触发一次重新发布（便于手动改配置后即时生效）
- `workflow_dispatch`：可在 GitHub 网页手动指定日期 / 强制重跑

**首次启用只需两步：**

1. 在仓库 **Settings → Secrets and variables → Actions** 添加：
   - `DEEPSEEK_API_KEY`：你的 DeepSeek API Key（用于内容生成）
2. 在仓库 **Settings → Pages → Build and deployment → Source** 选择 **GitHub Actions**。

之后每天自动出刊，无需任何操作。

> 站点基础地址集中在 `config/site.yaml::site_url`，换域名 / 换托管只改这一行，重新运行即生效，无需改代码。

---

## ⚙️ 配置说明

| 文件 | 作用 | 常见改动 |
|---|---|---|
| `config/site.yaml` | 站点信息、基础地址、板块、单日上限 | 改标题、改 `site_url`、调 `max_items_per_day` |
| `config/runtime.yaml` | 运行模式与端点：`mode: online/offline`、LLM 参数、git、deploy | 切联网/离线、换 LLM provider、调温度 |
| `sources/rss.yaml` | RSS 订阅源列表 | 增删资讯源 |
| `sources/apis.yaml` | GitHub Trending 等接口 | 扩展其他 API 源 |
| `config/prompts/` | 版本化提示词模板 | 换模型时派生新版本，不动结构契约 |

> 所有 API Key 只从环境变量 / 仓库 Secrets 读取，**绝不写入配置文件**。

---

## 🖼️ 海报二维码逻辑

二维码在生成时被「烧录」进 PNG 像素，无法就地改写，因此**修改 = 重新生成海报**。指向规则由 `scripts/poster.py::qr_url_for(date)` 按日期计算：

| 日期 | 二维码指向 | 说明 |
|---|---|---|
| 当日（feed.json 最新一天） | `site_url`（站点根地址） | 如 `https://aileoz.github.io/ai-daily-news/` |
| 历史（非最新） | `site_url/output/archive/<日期>.html` | 跳到该日期专属内容页 |

**批量修复历史海报**（例：迁移站点后统一换地址）：

```bash
# 重生成全部历史海报并解码校验指向是否正确
python scripts/fix_poster_qr.py --all

# 仅修复指定日期
python scripts/fix_poster_qr.py --date 2026-08-03

# 仅打印将写入的地址、不生成
python scripts/fix_poster_qr.py --all --dry-run
```

脚本生成后会自动用 OpenCV 解码回读二维码，确认指向无误（依赖缺失时跳过校验）。

---

## 🧪 本地运行（调试 / 手动出刊）

需要 Python 3 与 `requirements.txt` 依赖：

```bash
pip install -r requirements.txt

# 1) 采集（联网）
python scripts/collect.py --date 2026-08-05

# 2) 生成内容（需 DEEPSEEK_API_KEY 环境变量）
DEEPSEEK_API_KEY=sk-xxx python scripts/generate.py --date 2026-08-05

# 3) 门禁校验
python scripts/regression_check.py check data/raw/2026-08-05_ai.md --section aiNews
python scripts/regression_check.py check data/raw/2026-08-05_github.md --section github
python scripts/regression_check.py check data/raw/2026-08-05_summary.md --section summary

# 4) 聚合 + 构建 + 海报
python scripts/filter.py --date 2026-08-05 --section aiNews --file data/raw/2026-08-05_ai.md
python scripts/filter.py --date 2026-08-05 --section github --file data/raw/2026-08-05_github.md
python scripts/filter.py --date 2026-08-05 --section summary --file data/raw/2026-08-05_summary.md
python scripts/build_summary.py
python scripts/poster.py --date 2026-08-05
python scripts/build.py
python scripts/validate_dates.py

# 或用一键兜底脚本（不含 LLM 成稿，需当日 raw 已存在）
bash scripts/run_daily.sh --date 2026-08-05
```

---

## 🔧 模型无关设计（Model-agnostic）

本项目把「内容生成」与「底层模型」解耦，详见 `docs/`：

- `docs/automation-task-spec.md`：模型无关的任务契约、自检协议、评估标准、版本化提示词模板与回归机制。
- `docs/generation-guide.md`：内容生成规则（Markdown 结构 / 条数 / 文风，本身模型无关）。
- `docs/ai-news-system-design.md`：系统架构（采集 / 聚合 / 构建 / 部署流水线）。
- `docs/cloud-strategy.md` / `docs/cloud-setup.md`：云端部署方案与步骤。

**换模型操作**：仅改调用方传入的 `model.id` 与（必要时）`prompt_template_version`，复用同一提示词模板；换模后跑 `regression_check.py compare <ref> <cand>` 验证结构一致即可，不回退到模型专属特性。

---

## ❓ 常见问题

**Q：没联网 / 没开 VPN 能访问吗？**
能。站点发布在 GitHub Pages 上，是公开静态页，浏览器直接打开即可，无需代理。

**Q：每天几点更新？**
默认北京时间 06:00（GitHub Actions 定时 `0 22 * * *` UTC）。受 GitHub 调度队列影响可能有几分钟偏差。

**Q：改了配置 / 文案想立刻生效？**
在 GitHub 仓库 **Actions** 页手动 **Run workflow**（可选指定日期 / 强制重跑），或 push 一次到 `main` 即触发重新发布。

**Q：海报二维码扫出来是旧地址？**
二维码已「烧录」进 PNG，需重新生成。见上文「海报二维码逻辑」用 `fix_poster_qr.py` 批量修复，并推送发布。

**Q：内容来源可靠吗？**
AI 新闻来自 RSS 实时抓取 + GitHub Trending，生成阶段禁止编造未出现在素材中的事实；数字 / 项目名可追溯到 `data/collected/` 缓存。

---

## 📄 许可

仓库内容供个人学习与非商业分享使用。
