#!/usr/bin/env bash
# run_daily.sh —— 「AI 每日资讯」确定性流水线（不含 LLM 文本生成）。
#
# 设计目标：
#  - 完全可在无人工、无 App 常驻的情况下把"已生成的原始 Markdown"编译成全部静态产物；
#  - 联网相关步骤（git push / 部署）均为 best-effort，离线时优雅跳过，不阻塞主流程；
#  - 所有外网依赖由 config/runtime.yaml 的 mode 控制（默认 offline）。
#
# 调用方：
#  1) WorkBuddy 自动化（具备 LLM）：先由模型写出 data/raw/$DATE_*.md，再调用本脚本完成后续；
#  2) macOS launchd（系统级兜底）：每日 06:05 调用本脚本，若当日 raw 文件已存在则补齐构建/部署，
#     否则安全跳过（LLM 文本生成只能由自动化完成）。
#
# 用法：
#  bash scripts/run_daily.sh                 # 用 Asia/Shanghai 当天日期
#  bash scripts/run_daily.sh --date 2026-08-04
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

DATE="$(TZ=Asia/Shanghai date +%F)"
if [ "${1:-}" = "--date" ] && [ -n "${2:-}" ]; then DATE="$2"; fi

# 优先使用已安装 Pillow/qrcode 的托管 Python；缺失则回退 python3
MANAGED_PY="/Users/zhulei/.workbuddy/binaries/python/envs/default/bin/python"
if [ -x "$MANAGED_PY" ]; then PY="$MANAGED_PY"; else PY="python3"; fi

LOG_DIR="$ROOT/data/logs"; mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/run_$DATE.log"
exec > >(tee -a "$LOG") 2>&1

echo "================ run_daily.sh @ $DATE ($(TZ=Asia/Shanghai date '+%F %T')) ================"
echo "mode=$(grep -m1 '^mode:' config/runtime.yaml | awk '{print $2}')"

# 0) 健康前置：当日原始文件是否齐备（AI 新闻 / GitHub / 速览）
RAW_AI="data/raw/${DATE}_ai.md"
RAW_GH="data/raw/${DATE}_github.md"
RAW_SU="data/raw/${DATE}_summary.md"
if [ ! -f "$RAW_AI" ] || [ ! -f "$RAW_GH" ]; then
  echo "[WARN] 当日原始文件缺失（$RAW_AI / $RAW_GH），LLM 文本生成尚未完成，跳过编译。退出码 0。"
  exit 0
fi

# 1) 采集（离线：仅读本地缓存 + 语料，不碰外网）
echo "[1/7] collect (offline) ..."
$PY scripts/collect.py --date "$DATE" || echo "[WARN] collect 异常（不影响后续）"

# 2) 校验聚合：三块内容写入 feed.json
echo "[2/7] filter (aiNews / github / summary) ..."
$PY scripts/filter.py --date "$DATE" --section aiNews   --file "$RAW_AI"  || echo "[WARN] filter aiNews 失败"
$PY scripts/filter.py --date "$DATE" --section github    --file "$RAW_GH"  || echo "[WARN] filter github 失败"
$PY scripts/filter.py --date "$DATE" --section summary   --file "$RAW_SU"  || echo "[WARN] filter summary 失败"

# 顺序说明：build.py 会扫描 output/poster 与 output/summary，把 poster / summaryHtml 路径
# 写回 feed.json 资产索引，因此它必须排在「速览页」与「海报」之后；否则当日
# feed.poster / feed.summaryHtml 为空，validate_dates 会判为「未注册索引」错配。

# 3) 构建速览页
echo "[3/7] build_summary ..."
$PY scripts/build_summary.py || echo "[WARN] build_summary 失败"

# 4) 生成海报
echo "[4/7] poster ..."
$PY scripts/poster.py --date "$DATE" || echo "[WARN] poster 失败"

# 5) 构建静态归档 / 首页 / 历史页（并把 poster / summaryHtml 写回 feed 资产索引）
echo "[5/7] build ..."
$PY scripts/build.py || echo "[WARN] build 失败"

# 5.5) 历史记录过期清理（仅保留最近 7 天，分批静默删除）
echo "[5.5/7] prune_history ..."
$PY scripts/prune_history.py --keep 7 || echo "[WARN] prune_history 失败"

# 6) 一致性 / 日期校验（失败仅记录，不阻断发布）
echo "[6/7] regression_check + validate_dates ..."
$PY scripts/regression_check.py check "$RAW_AI"  --section aiNews  || echo "[FAIL] aiNews 一致性"
$PY scripts/regression_check.py check "$RAW_GH"  --section github   || echo "[FAIL] github 一致性"
$PY scripts/regression_check.py check "$RAW_SU"  --section summary  || echo "[FAIL] summary 一致性"
$PY scripts/validate_dates.py || echo "[FAIL] 日期 1:1 校验"

# 7) 发布（best-effort：离线/无权限时跳过）
echo "[7/7] publish (git push best-effort) ..."
if git -C "$ROOT" rev-parse >/dev/null 2>&1; then
  git -C "$ROOT" add -A
  if git -C "$ROOT" diff --cached --quiet; then
    echo "[INFO] 无变更，跳过 commit"
  else
    git -C "$ROOT" commit -m "chore: 每日更新 $DATE (自动化流水线)" >/dev/null 2>&1 \
      && git -C "$ROOT" push origin "$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)" >/dev/null 2>&1 \
      && echo "[OK] git push 成功" || echo "[WARN] git push 失败（离线或权限不足，已跳过，不阻塞）"
  fi
else
  echo "[WARN] 非 git 仓库，跳过 push"
fi

echo "================ 完成 @ $DATE ================"
echo "产物：data/feed.json · output/archive/$DATE.html · output/summary/$DATE.html · output/poster/$DATE.png"
echo "部署（CloudStudio）由自动化/手动执行 best-effort；日志见 $LOG"
