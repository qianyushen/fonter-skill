#!/bin/bash
# 双击运行：装好 fonter 的依赖并自查（macOS 用，等价于 Windows 的 bat）
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null; then
  bash scripts/setup.sh
else
  echo "✗ 没找到 python3。先装 Python 3（https://www.python.org/downloads/）"
fi
read -r -p "按回车关闭窗口"
