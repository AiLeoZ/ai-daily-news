# 云端自动化配置指南

## 前置条件

- 仓库必须有一个 `main` 分支，且 `.github/workflows/daily.yml` 已提交。
- GitHub Actions 已启用（仓库 Settings → Actions → General → Allow all actions）。

## 1. 添加 API 密钥

内容生成依赖 DeepSeek API，密钥必须存入 GitHub Secrets：

1. 打开仓库 → **Settings → Secrets and variables → Actions**
2. 点击 **New repository secret**
3. Name：`DEEPSEEK_API_KEY`
4. Value：你的 DeepSeek API 密钥（如 `sk-xxxxxxxx`）
5. 点击 Add secret

## 2. 启用 GitHub Pages

1. 打开仓库 → **Settings → Pages**
2. Source 选择 **GitHub Actions**（不是 "Deploy from a branch"）
3. 保存

启用后，第一次工作流成功运行时会自动创建 Pages 环境并部署。

## 3. 验证

### 手动触发测试

1. 打开仓库 → **Actions** 标签页
2. 左侧选择 **AI 每日资讯 · 云端全自动生成与发布**
3. 点击 **Run workflow** → **Run workflow**

### 检查运行结果

- 绿色 ✓ = 全部步骤成功（采集 → 生成 → 门禁 → 构建 → 发布）
- 红色 ✗ = 某步失败，点击查看日志定位原因

## 4. 定时运行

工作流每天 **北京时间 06:00**（UTC 22:00）自动触发。

注意：GitHub Actions 的 cron 在整点非常拥挤，实际触发时间可能延迟 5-30 分钟，属正常现象。

## 5. 站点地址

部署成功后，站点地址可在两个地方找到：

- 仓库 Settings → Pages → 顶部显示 "Your site is live at ..."
- Actions 运行日志 → deploy job → "站点地址" 输出

格式为 `https://<username>.github.io/<repo>/`

## 6. 常见故障排查

| 现象 | 可能原因 | 解决方式 |
|---|---|---|
| 生成步骤失败 "未配置 DEEPSEEK_API_KEY" | 未创建 Secret | 按第 1 步添加 |
| 海报步骤失败 "未找到可用的中文字体" | apt 字体包未安装 | 检查运行日志中 `fonts-noto-cjk` 安装是否成功 |
| 门禁校验失败 "缺少 repo-desc" 等 | LLM 输出格式不规范 | generate.py 已内置重试；若连续失败，检查 API 配额 |
| Pages 发布 404 | Pages 未启用或 Source 不对 | 确认第 2 步已执行 |
| 站点样式丢失 | 静态资源路径问题 | GitHub Pages 在子路径时（`/repo/`），assets 需用相对路径。当前网站已适配 |

## 7. 本地开发

若需在本地手动生成或调试，可运行：

```bash
# 本地联网采集 + 生成（需要 DEEPSEEK_API_KEY 环境变量）
export DEEPSEEK_API_KEY=sk-xxx
python3 scripts/generate.py --date 2026-08-05
bash scripts/run_daily.sh --date 2026-08-05
```

所有改动请通过 Git 提交至 `main` 分支，云端在下次定时运行时自动拉取。
