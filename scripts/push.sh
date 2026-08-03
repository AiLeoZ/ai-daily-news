#!/usr/bin/env bash
# scripts/push.sh —— 尽力而为的 Git 提交与推送
# 设计目标：任何失败都只告警、不返回致命错误，确保不中断上游流水线。
# 用法：bash scripts/push.sh   （自动定位工作目录，无需参数）
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIR="$(dirname "$SCRIPT_DIR")"   # scripts/ 的上级即工作目录
DATE="$(TZ=Asia/Shanghai date +%F)"

cd "$DIR" || { echo "[push] 无法进入工作目录 $DIR，跳过"; exit 0; }

git add -A
if git diff --cached --quiet; then
  echo "[push] 无变更，跳过 commit/push"
  exit 0
fi

git -c user.email="bot@workbuddy.local" -c user.name="WorkBuddy" \
  commit -m "chore: 每日更新 $DATE" || { echo "[push] commit 失败，跳过推送"; exit 0; }

if git push origin main 2>&1; then
  echo "[push] 推送成功 ($DATE)"
else
  echo "[push] 警告：push 失败（已忽略，不影响站点，下次运行会重试）"
fi
exit 0
