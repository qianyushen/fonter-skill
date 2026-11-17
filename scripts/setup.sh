#!/bin/bash
# 一条命令装好 fonter 的依赖，并自查。
#   bash scripts/setup.sh            # 装 + 自查
#   bash scripts/setup.sh --check    # 只自查
#   bash scripts/setup.sh --python /path/to/python3
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL="$(dirname "$HERE")"
PY="${PYTHON:-python3}"
CHECK_ONLY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --check) CHECK_ONLY=1; shift;;
    --python) PY="$2"; shift 2;;
    *) echo "未知参数: $1"; exit 1;;
  esac
done

echo "=== fonter 依赖安装 ==="
echo "skill: $SKILL"
echo "python: $(command -v "$PY" || echo "$PY") → $("$PY" -V 2>&1)"

if [ "$CHECK_ONLY" -eq 0 ]; then
  "$PY" -m pip install --disable-pip-version-check -r "$SKILL/requirements.txt" || {
    echo "✗ pip 安装失败。常见原因："
    echo "  1) 没网 / 需要代理：HTTPS_PROXY=http://127.0.0.1:7890 bash scripts/setup.sh"
    echo "  2) python3 被系统保护：改用 Homebrew/Framework 的 python3："
    echo "     bash scripts/setup.sh --python /Library/Frameworks/Python.framework/Versions/3.14/bin/python3"
    exit 1
  }
fi

echo
"$PY" "$HERE/check_env.py"
echo
echo "用这个解释器跑脚本即可，例："
echo "  $PY $HERE/build_family.py --sources 02_letters/* --family MYFONT --out-dir 04_font --charset A-Z,0-9"
