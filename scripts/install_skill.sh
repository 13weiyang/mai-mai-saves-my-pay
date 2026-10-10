#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════
#  麦门搭子 · 把 Skill 装进你的项目
#
#  用法：
#    bash scripts/install_skill.sh              # 装到当前目录
#    bash scripts/install_skill.sh /path/to/proj
#
#  会同时放进三处（谁在跑就认谁）：
#    .cursor/skills/  ·  .workbuddy/skills/  ·  .claude/skills/
#
#  ⚠️ 只新增/覆盖同名文件，**不删除任何东西**。
# ══════════════════════════════════════════════════════════════
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$HERE/../skill/mai-mai-saves-my-pay"
TARGET="${1:-.}"

if [ ! -f "$SRC/SKILL.md" ]; then
  echo "✗ 找不到 $SRC/SKILL.md —— 请确认在仓库根目录下运行" >&2
  exit 1
fi

for base in .cursor .workbuddy .claude; do
  dest="$TARGET/$base/skills/mai-mai-saves-my-pay"
  mkdir -p "$dest"
  cp -R "$SRC"/. "$dest"/
  echo "✓ 已装入 $dest"
done

echo
echo "装好了。在对话里说一句「帮我用麦门搭子点一顿麦当劳」试试。"
echo "前置：需要 MCD_MCP_TOKEN（在 open.mcd.cn/mcp 申请）。"
