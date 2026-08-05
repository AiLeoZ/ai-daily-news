# AI 每日资讯 · 云端独立运行战略方案

> 评估日期：2026-08-05 ｜ 评估对象：`/Users/zhulei/WorkBuddy/2026-08-03-11-34-41`
> 目标：完全脱离本地电脑，云端每日定时自动运行，你只需提供 API key，每天访问一个网址查看结果。

---

## 一、结论先行

| 你的问题 | 结论 |
|---|---|
| 能否脱离电脑独立运行？ | **能。而且比预想的近——仓库已完成约 95% 的云端改造，只差一个能托管它的账户。** |
| 之前 GitHub 为什么没走通？ | **根因不是技术，是账户归属。** 仓库从未配置过 git remote，代码一次都没推上去。公司账户大概率是企业托管用户（EMU），受组织策略限制无法承载此类个人项目。 |
| 推荐怎么做？ | **首选：注册一个独立的个人 GitHub 账户 → Actions 定时 + Pages 托管。零代码改造、零平台费用、当天可上线。** |
| 有没有不依赖 GitHub 的路？ | 有，云服务器 + crontab（¥24–60/月，可控性最高、国内访问最快）。其余方案各有明显短板，见第四节。 |

**一句话战略判断**：你缺的不是方案，是一个「干净的账户」。别再在公司 GitHub 上折腾了，那条路在策略层面就是堵死的。

---

## 二、现状评估：距离「无人值守」还差多远

### 2.1 任务解剖：四个可分离的关注点

把「每天自动更新网站」拆开看，本质是四件事，它们可以由同一个平台包办，也可以拆到不同平台：

| 层 | 职责 | 本任务的具体需求 |
|---|---|---|
| **① 定时触发** | 每天固定时间唤醒任务 | 北京时间每日 06:00 |
| **② 计算执行** | 采集 → 生成 → 构建 → 出图 | Python 3 + Pillow/qrcode + 中文字体，单次约 5–8 分钟，需外网访问 RSS / GitHub / LLM API |
| **③ 状态持久化** | 历史内容必须累积，不能每天从零开始 | `data/feed.json` 持续增长、`output/archive/*.html` 逐日累积 |
| **④ 静态托管** | 对外提供可访问的网址 | 纯静态站点，无后端 |

**关键约束**：第 ③ 项决定了纯 Serverless 方案（函数计算、Workers）不好用——它们默认无状态，得额外接对象存储改造。而 **Git 仓库天然同时满足 ③ 和 ④**，这正是当前架构选择 GitHub 的原因，也是它依然是最优解的原因。

### 2.2 关键发现：云端能力其实已经内置

尽调中发现，这套系统早已按「模型无关 + 无人值守」设计过，而且已提交到 `main` 分支：

| 已就绪的资产 | 状态 | 作用 |
|---|---|---|
| `.github/workflows/daily.yml` | ✅ 完整（120 行） | 采集→生成→门禁→构建→发布→Pages 部署，全流程已编排 |
| `scripts/generate.py` | ✅ 542 行，**已实测干跑通过** | 唯一需要大模型的环节的无人值守实现，纯标准库、自带结构自检与失败重试 |
| `requirements.txt` | ✅ 锁定版本 | `Pillow==10.4.0`、`qrcode[pil]==7.4.2`，保障产物二进制一致 |
| `scripts/poster.py` 字体探测 | ✅ 跨平台 | 依次探测仓库内置字体 → macOS 系统字体 → Linux Noto/文泉驿 |
| `docs/cloud-setup.md` | ✅ 已写好 | Secrets 配置、Pages 启用、故障排查表 |
| `scripts/regression_check.py` | ✅ 19 项机器断言 | 内容门禁，不合格阻断发布 |
| **git remote** | ❌ **从未配置** | ← **这就是断点所在** |

我实测了无人值守生成链路（干跑，不消耗 API 额度），三个板块的提示词均正常构造：

```
aiNews : system 6,815 字 / user 31,538 字（103 条候选，已按产业/学术分层）
github : system 6,815 字 / user  5,579 字
summary: system 6,815 字 / user  9,427 字
```

脚本会自动把 `docs/generation-guide.md` 整篇作为 system prompt，把采集素材按「产业动态优先、学术预印本限额」分层喂给模型——**这套设计恰恰是为了防止 ArXiv 论文把产业新闻挤出选题**，说明前期已经踩过并解决了这个坑。

### 2.3 本地 WorkBuddy vs 云端无人值守：能力对照

| 环节 | 本地（现在） | 云端（目标） | 是否等价 |
|---|---|---|---|
| 采集 RSS / GitHub 趋势 | `collect.py` | `collect.py` | ✅ 完全一致 |
| 内容生成 | WorkBuddy 对话模型 | `generate.py` + DeepSeek API | ⚠️ 结构等价，**质量把关有差距**（见 2.4） |
| 结构门禁 | `regression_check.py` | 同一脚本，且为阻断式 | ✅ 云端更严格 |
| 日期一致性 | `validate_dates.py` | 同一脚本 | ✅ 一致 |
| 构建 / 海报 / 聚合 | `run_daily.sh` | 工作流逐步调用同名脚本 | ✅ 一致 |
| 发布 | CloudStudio（临时链接） | GitHub Pages（固定域名） | ✅ 云端更好 |
| **运行前提** | **你的电脑开机 + App 运行** | **无任何本地依赖** | ✅ 目标达成 |

### 2.4 唯一真实差距：内容质量的人工把关

这是必须坦诚说明的 trade-off，也是本方案唯一的实质性妥协。

机器能保证的（`regression_check.py` 19 项断言）：条数、序号连续性、必含二级标题、表格列名、`repo-desc` 存在性、禁语、日期倒序、日期 1:1 不串用。

**机器保证不了的**：`docs/automation-task-spec.md` §5 里的 A4（真实性抽样）、H1（文风是否 IT 小白友好）、H2（信息密度）。

**今天这次执行本身就是例证**：我在生成前核对素材时，发现上一版留有 2 条无法在当日采集缓存中溯源的新闻（DeepSeek 第二轮融资 500 亿元、Qwen-Image-3.0 定价 0.18 元/张），已将其剔除并替换为可溯源的 AMD 财报、SpaceX AI 营收、SaferAI 报告。**这类「这条到底有没有出处」的判断，无人值守脚本目前做不到**——它只会检查结构合不合规。

缓解措施（按性价比排序）：

1. **加一封每日邮件**（推荐）：工作流末尾发送当日速览摘要到你邮箱，你花 30 秒扫一眼标题就能发现离谱内容。比「记得每天去访问网站」可靠得多。
2. **保留每周一次人工复核**：周末花 5 分钟翻一遍本周归档，发现系统性偏差就调 `generation-guide.md`（改规范即改行为，不用改代码）。
3. **给 `generate.py` 增加溯源断言**（可选进阶）：强制要求每条新闻的标题关键词能在当日 `rss_$DATE.json` 中匹配到，匹配不上就重试。这能把 A4 从人工项转为自动项。

---

## 三、GitHub 方案失败根因排查

### 3.1 最可能的根因：企业托管用户（EMU）

GitHub 官方规则明确（已核实）：

- **GitHub Free 账户，Pages 仅在「公开仓库」可用**；私有仓库要开 Pages 需 GitHub Pro（$4/月）。
- **企业托管用户（Enterprise Managed Users, EMU）只能从「组织拥有的仓库」发布 Pages**，无法用个人仓库发布。

如果你公司的 GitHub 是 EMU 模式（用户名通常带企业后缀，如 `zhulei_tencent`），那么：个人仓库建不了、公开仓库通常被禁、Pages 走不通、还不能与企业外部仓库协作。**这不是配置问题，是账户类型的硬限制，怎么调都调不通。**

### 3.2 五分钟自查清单

| # | 检查项 | 怎么查 | 命中说明什么 |
|---|---|---|---|
| 1 | 账户是否 EMU | 头像 → Settings，页面是否显示 "Managed by \<企业名\>"；或用户名带企业后缀 | 命中 → **个人项目路线彻底不可行**，直接走方案 A（新账户）或方案 B |
| 2 | 能否建公开仓库 | New repository → Visibility 中 Public 是否置灰 | 置灰 → Free 版 Pages 不可用 |
| 3 | Actions 是否被禁 | 仓库 Settings → Actions → General | 显示被组织策略锁定 → 定时触发无法运行 |
| 4 | Pages 是否被禁 | 仓库 Settings 左栏是否存在 "Pages" 条目 | 不存在 → 企业级关闭了 Pages |
| 5 | SAML SSO 授权 | Settings → Developer settings → PAT，令牌旁是否要求 "Authorize" | 未授权 → push 报 403，这是最常见的「看起来配好了却推不上去」 |
| 6 | IP 白名单 | 组织 Settings → Security → IP allow list | 启用了 → 家庭网络会被直接拒绝 |

从仓库现状看（`git remote -v` 为空，`main` 分支上工作流与文档齐备但从未推送），你大概率卡在第 1、2 或 5 项。

### 3.3 一个容易被忽略的非技术风险

**用公司 GitHub 账户跑个人项目，本身可能违反公司 IT / 信息安全政策**——包括代码资产归属、Actions 算力占用、以及把个人 API key 存进公司账户的 Secrets。即便技术上能绕通，也不建议。**用独立个人账户是更干净的做法，这不只是技术选择，也是合规选择。**

---

## 四、方案全景对比

### 4.1 五个候选方案

| 方案 | 定时 | 计算 | 持久化 | 托管 | 月成本 | 改造量 |
|---|---|---|---|---|---|---|
| **A. 个人 GitHub 账户** | Actions cron | Actions runner | Git 仓库 | GitHub Pages | **¥0** | **0（已就绪）** |
| **B. 云服务器 + crontab** | 系统 crontab | 服务器本机 | 本地磁盘 + Git | Nginx | ¥24–60 | 低（1–2 小时） |
| **C. GitLab.com** | GitLab CI schedule | GitLab runner | Git 仓库 | GitLab Pages | ¥0（需绑卡验证） | 中（翻译 CI 文件，约 1 小时） |
| **D. Render Cron + 静态托管** | Render Cron Job | Render 容器 | 需外接 Git/对象存储 | Render Static Site | 约 $1–7 | 中高 |
| **E. 国内 Serverless（SCF/FC + COS）** | 云函数定时触发器 | 函数计算（≤15 min） | 对象存储 COS | COS 静态网站 | ≈¥0–10 | **高**（状态管理需重写） |

### 4.2 优劣详评

**方案 A · 个人 GitHub 账户** ⭐ 首选

- ✅ **零改造**：`daily.yml` 已写好，推上去就能跑
- ✅ **零成本**：公开仓库的 Actions 分钟数无限、Pages 免费
- ✅ 四层需求一个平台全包，无胶水代码
- ✅ 固定域名 `https://<用户名>.github.io/<仓库名>/`，可绑自定义域名
- ✅ 运行日志、失败通知、手动重跑（`workflow_dispatch`）开箱即用
- ⚠️ 仓库必须公开（内容本就是对外资讯站，可接受；介意则 GitHub Pro $4/月开私有 Pages）
- ⚠️ Actions 定时有 5–30 分钟延迟（整点排队，属正常，对每日资讯无影响）
- ⚠️ 国内访问 `github.io` 偶有波动（可套 Cloudflare 自定义域名改善）
- ⚠️ 需注册并长期维护一个独立个人账户，注意与公司账户在浏览器/Git 凭据上隔离

**方案 B · 云服务器 + crontab** ⭐ 备选 / 长期最稳

- ✅ **无任何平台策略风险**，不看别人脸色
- ✅ crontab 精确触发，无排队延迟
- ✅ 国内节点访问速度最快
- ✅ 计算时长无限制，未来扩展（加视频、加更多源）不受约束
- ⚠️ 需自己运维：环境安装、Nginx 配置、安全更新、备份
- ⚠️ ¥24–60/月（腾讯云轻量 2核2G 级别）
- ⚠️ 国内服务器绑定自定义域名需备案；用公网 IP 直接访问可免备案，或选香港/新加坡节点
- ⚠️ 服务器一旦被入侵，落盘的 API key 有泄露风险（用 `chmod 600` + 环境变量缓解）

**方案 C · GitLab.com**

- ✅ 免费额度 400 分钟/月，本任务约需 150–240 分钟/月，够用
- ✅ GitLab Pages 对**私有仓库**也免费开放（比 GitHub 宽松，适合不想公开代码的场景）
- ⚠️ 免费用户跑 CI 需绑定信用卡做身份验证（反滥用要求），这是主要摩擦点
- ⚠️ 需把 `daily.yml` 翻译成 `.gitlab-ci.yml`
- ⚠️ 额度紧张，失败重跑几次就可能触顶

**方案 D · Render 等海外 PaaS** ✗ 不推荐

- Cron Job 是一等公民、静态站点免费且不休眠，听起来很美
- ❌ 但 **Cron 容器与 Static Site 之间没有共享持久化存储**，产物还得推回某个 Git 仓库或对象存储——绕一大圈，最后还是要一个代码托管账户，白白多引入一个平台
- ❌ 免费层 Web Service 有冷启动，Cron 通常需付费（约 $1/月起）
- 结论：**复杂度增加，收益为负**

**方案 E · 国内 Serverless（腾讯云 SCF / 阿里云 FC + COS）**

- ✅ 国内访问最快，成本几乎在免费额度内
- ✅ 函数最长 15 分钟，本任务 5–8 分钟够用
- ❌ **改造量最大**：现有架构用 Git 仓库当状态存储，Serverless 要改成基于 COS 读写，`build.py`/`filter.py`/`validate_dates.py` 的路径逻辑都要动
- ❌ 装 Pillow 原生轮子 + 中文字体需自定义层或容器镜像部署
- ❌ COS 绑自定义域名需备案
- 结论：适合「未来要长期国内化运营」时的 v2 演进，不适合现在求快

### 4.3 已排除的方案

| 方案 | 排除原因 |
|---|---|
| Cloudflare Workers 定时 | Python Workers 基于 Pyodide，**装不了 Pillow 原生轮子**，海报生成直接不可行；CPU 时间也不够 |
| Vercel Cron | Hobby 层函数最长 60 秒，**跑不完 3 次 LLM 调用**（约 2–5 分钟） |
| Netlify Scheduled Functions | 同样有执行时长限制，且无持久化存储 |
| 本地 Mac 常开 + launchd | 违背「不依赖本地电脑」的核心目标（`run_daily.sh` 注释里提到的 launchd 兜底属于此类） |

> 注：Cloudflare Pages **做静态托管**仍是个好选择，可作为方案 A/B 的加速层（自定义域名 + 全球 CDN，改善国内访问）。被排除的只是用 Workers 跑计算。

---

## 五、推荐方案详解（方案 A）

### 5.1 架构

```
每日 UTC 22:00（北京时间 06:00）
        │
        ▼
GitHub Actions（ubuntu-latest 容器，用完即弃）
  1. checkout 仓库（含全部历史内容）
  2. apt 装中文字体 + pip 装 Pillow/qrcode
  3. collect.py   ── 联网抓 RSS + GitHub Trending
  4. generate.py  ── 调 DeepSeek API 写三份 Markdown ← 唯一用到你的 API key
  5. regression_check.py × 3 ── 内容门禁，不过则中止发布
  6. filter → build_summary → poster → build
  7. validate_dates.py ── 日期 1:1 校验
  8. 产物齐备性检查（8 个文件缺一不可）
  9. git commit + push（把当天内容写回仓库＝持久化）
 10. 部署到 GitHub Pages
        │
        ▼
https://<你的用户名>.github.io/<仓库名>/   ← 你每天访问这个
```

**为什么这个架构可靠**：第 5、7、8 步是三道阻断式门禁，任何一道不过就不会发布——**宁可今天不更新，也不会把残缺内容推上线**。而且因为产物 push 回仓库，即使某天失败，站点仍停留在上一次成功的状态，不会 404。

### 5.2 定时触发机制

```yaml
on:
  schedule:
    - cron: "0 22 * * *"      # UTC 22:00 = 北京时间次日 06:00
  workflow_dispatch:            # 支持网页端手动触发，可指定日期、强制重生成
```

- GitHub Actions 的 cron **统一使用 UTC**，不支持时区配置，所以写 22:00 对应北京时间 06:00。工作流内部再用 `TZ=Asia/Shanghai date +%F` 取正确日期，这点现有工作流已处理妥当。
- 整点是全球最拥挤的时段，**实际触发通常延迟 5–30 分钟**，属正常现象。若想更准时，可改成 `"7 22 * * *"` 这类错峰分钟数。
- 手动触发入口：仓库 → Actions → 选中工作流 → Run workflow，可传入指定日期补跑历史。

### 5.3 结果网站的生成与访问

**生成**：`build.py` 会扫描 `data/feed.json`，渲染出 `output/index.html`（首页）、`output/archive/<日期>.html`（每日归档）、`output/history.html`（历史列表），再由 `actions/deploy-pages` 整包发布。

**访问**：
- 主地址：`https://<用户名>.github.io/<仓库名>/`
- 当日速览：`.../output/summary/<日期>.html`，另有 `latest.html` 永久指向最新
- 当日海报：`.../output/poster/<日期>.png`，另有 `latest.png`

我已确认 `index.html` 内全部资源引用均为**相对路径**（`assets/style.css`、`output/summary/latest.html` 等），因此部署在 `/<仓库名>/` 子路径下样式不会丢失——这点常见的坑已经避开了。

**可选增强**：绑自定义域名（仓库根加 `CNAME` 文件 + 域名 DNS 加 CNAME 记录），或前置 Cloudflare 改善国内访问速度。

### 5.4 API key 安全提供方式

**推荐做法：GitHub Repository Secrets**

1. 仓库 → Settings → Secrets and variables → Actions → New repository secret
2. Name: `DEEPSEEK_API_KEY`，Value: 你的密钥
3. 工作流通过 `${{ secrets.DEEPSEEK_API_KEY }}` 注入为环境变量

**为什么这样是安全的**：

| 安全属性 | 保障机制 |
|---|---|
| 静态加密 | GitHub 侧加密存储，创建后**任何人（包括你）都无法再读出明文**，只能覆盖 |
| 传输隔离 | 仅在工作流运行时注入容器环境变量，运行结束容器销毁 |
| 日志脱敏 | 一旦密钥字符串出现在日志中会自动打码为 `***` |
| Fork 防护 | 来自 fork 的 PR **默认拿不到 Secrets**，这是公开仓库最关键的一道防线 |
| 不落盘 | 代码侧已做对：`config/runtime.yaml` 只存变量名 `api_key_env: DEEPSEEK_API_KEY`，注释明确写着「API key 永远只从环境变量读取，绝不写入本文件」；`generate.py` 只用 `os.environ.get()` 读取 |

我已对仓库做过密钥扫描：**74 个被 git 跟踪的文件中，无任何硬编码密钥、无个人隐私信息**，可以安全公开。

**额外的三条纪律**：

1. **为这个用途单独申请一个 DeepSeek key**，不要复用你其他项目的密钥——万一泄露，爆炸半径仅限于此
2. **在 DeepSeek 控制台设置消费限额**（本任务约 ¥0.2/天，设 ¥30/月上限足够，能防住意外死循环）
3. **每季度轮换一次**，在 Secrets 里覆盖即可，无需改任何代码

### 5.5 落地清单（约 30 分钟）

| # | 步骤 | 预计耗时 | 说明 |
|---|---|---|---|
| 1 | 注册独立个人 GitHub 账户 | 5 min | 用**个人邮箱**，与公司账户彻底隔离 |
| 2 | 新建公开仓库，如 `ai-daily-news` | 1 min | 不要勾选任何初始化文件 |
| 3 | 本地配置 remote 并推送 | 3 min | `git remote add origin <URL>` → `git push -u origin main` |
| 4 | 添加 Secret `DEEPSEEK_API_KEY` | 2 min | Settings → Secrets and variables → Actions |
| 5 | 启用 Pages | 1 min | Settings → Pages → Source 选 **GitHub Actions**（不是 Deploy from a branch） |
| 6 | 手动触发一次验证 | 10 min | Actions → Run workflow，全绿即成功 |
| 7 | 记下站点地址，加入浏览器书签 | 1 min | Settings → Pages 顶部显示 |
| 8 | 关闭本地 WorkBuddy 自动化 | 1 min | 避免本地与云端重复生成、互相覆盖 |

第 3 步的凭据建议用 **Personal Access Token**（Settings → Developer settings → Tokens，勾 `repo` + `workflow` 权限），比密码方式可靠。注意 Git 凭据管理器可能缓存了公司账户，推送前确认用的是新账户身份。

### 5.6 成本测算

| 项目 | 用量 | 费用 |
|---|---|---|
| GitHub Actions | 约 5–8 分钟/天 | **¥0**（公开仓库无限额） |
| GitHub Pages | 静态托管 | **¥0** |
| DeepSeek API | 输入约 6.7 万字/天、输出约 1 万 tokens/天 | **约 ¥0.2/天 ≈ ¥6/月**（含重试冗余按 ¥10/月估） |
| **合计** | | **约 ¥6–10/月，且唯一支出是你本来就要付的 API 费用** |

> API 单价随厂商调整，以 DeepSeek 官方最新定价为准；此处按输入 ¥2/百万 tokens、输出 ¥8/百万 tokens 估算。

---

## 六、备选方案详解（方案 B：云服务器）

若你对 GitHub 仍有顾虑（公司合规、国内访问速度、不愿内容公开），走这条路：

**配置建议**：腾讯云轻量应用服务器 2核2G / 阿里云同级，选**香港或新加坡节点可免域名备案**，国内节点则用公网 IP 直接访问。

**部署要点**：

```bash
# 1. 环境
apt update && apt install -y python3-pip nginx fonts-noto-cjk git
pip3 install -r requirements.txt

# 2. API key 写入环境文件（关键：权限收紧）
echo 'DEEPSEEK_API_KEY=sk-xxx' > /etc/ai-news.env
chmod 600 /etc/ai-news.env

# 3. crontab 每日 06:00
0 6 * * * cd /opt/ai-news && set -a && . /etc/ai-news.env && set +a && \
          python3 scripts/generate.py --date $(date +\%F) && \
          bash scripts/run_daily.sh >> /var/log/ai-news.log 2>&1

# 4. Nginx 指向仓库根目录即可（index.html 在根）
```

**注意**：服务器时区需设为 `Asia/Shanghai`（`timedatectl set-timezone Asia/Shanghai`），否则 crontab 的 06:00 不是你以为的 06:00——这是最常见的翻车点。

**优势**：完全自主、无策略风险、国内快、可扩展。**代价**：¥24–60/月 + 你要承担运维责任。

---

## 七、风险登记与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|---|---|---|---|
| 无人值守生成出现不可溯源内容 | **中** | 内容公信力受损 | 加每日邮件通知 + 每周人工抽查；进阶：给 `generate.py` 加溯源断言 |
| LLM 输出结构不合规 | 低 | 当天不更新 | 已有：`generate.py` 自检重试 + 三道阻断式门禁；站点保持上一版，不会 404 |
| RSS 源失效 | **中** | 素材减少 | 今日已出现（36氪源返回 HTML 而非 RSS）。`collect.py` 单源失败不影响整体；建议每季度巡检 `sources/rss.yaml` |
| API 余额耗尽 | 中 | 停止更新 | 设置余额告警 + 消费限额；工作流失败 GitHub 会自动邮件通知你 |
| GitHub Actions cron 延迟 | 高 | 更新时间漂移 | 影响可忽略；介意可错峰到非整点分钟 |
| 个人账户被误判滥用 | 低 | 服务中断 | 遵守 ToS，正常使用无虞；定期本地 `git pull` 留一份完整备份 |
| 国内访问 github.io 波动 | 中 | 打不开 | 绑自定义域名 + Cloudflare CDN |

---

## 八、建议执行路径

**第一阶段（今天，30 分钟）—— 先跑通**
按 5.5 清单执行方案 A，手动触发验证一次。跑通即达成核心目标：脱离本地电脑。

**第二阶段（本周，1 小时）—— 补上质量兜底**
1. 在工作流末尾加一步邮件通知，把当日速览摘要发到你邮箱
2. 连续观察 3–5 天云端自动生成的内容质量，与本地版本对比
3. 若发现选题或文风偏差，**改 `docs/generation-guide.md` 即可**——规范是唯一事实来源，改规范就改行为，不用碰代码

**第三阶段（本月，按需）—— 加固**
1. 绑定自定义域名 + Cloudflare，改善国内访问
2. 给 `generate.py` 增加溯源断言，把「真实性」从人工项转为自动项
3. 季度巡检 RSS 源有效性

**不建议做的事**：不要为了「更云原生」去改造成 Serverless。当前 Git-based 架构在状态持久化和版本可追溯上的优势，远大于 Serverless 带来的那点成本节约——你每月本来就只花几块钱。

---

## 附：核心判断依据速查

- 仓库已有 `.github/workflows/daily.yml`（完整 120 行）与 `scripts/generate.py`（542 行，干跑实测通过）
- `git remote -v` 为空 → 代码从未推送到任何远端，这是历史失败的直接原因
- GitHub 官方规则：Free 账户 Pages 仅限公开仓库；EMU 账户只能从组织仓库发布 Pages
- 仓库密钥扫描：74 个跟踪文件，零硬编码密钥、零隐私信息，可安全公开
- `index.html` 资源引用全部为相对路径，适配 Pages 子路径部署
- 提示词规模实测：三板块合计输入约 6.7 万字/天 → API 成本约 ¥0.2/天
