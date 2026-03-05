#!/bin/bash
# ═══════════════════════════════════════════════════
#  AI 创意工作站 — 双击启动
# ═══════════════════════════════════════════════════
#
#  macOS 用户：双击此文件即可启动
#  首次运行会自动安装依赖（约 1-2 分钟）
#

cd "$(dirname "$0")/.."
PROJECT_DIR="$(pwd)"

echo ""
echo "  ⚡ AI 创意工作站"
echo "  ════════════════════════════════════"
echo ""

# ── 检查 Python ──
if ! command -v python3 &> /dev/null; then
    echo "  ❌ 未找到 python3"
    echo ""
    echo "  请先安装 Python 3.9+："
    echo "    https://www.python.org/downloads/"
    echo ""
    read -p "  按回车退出..."
    exit 1
fi

PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "  ✓ Python $PYVER"

# ── 安装依赖（首次运行或缺失时） ──
if ! python3 -c "import streamlit" 2>/dev/null; then
    echo "  ⏳ 首次运行，正在安装依赖..."
    echo ""
    python3 -m pip install -r "$PROJECT_DIR/requirements.txt" --quiet 2>&1 | tail -3
    echo ""
    echo "  ✓ 依赖安装完成"
fi

# ── 启动应用 ──
echo ""
echo "  🚀 正在启动..."
echo "  浏览器将自动打开 http://localhost:8501"
echo "  关闭此窗口即可停止应用"
echo ""

cd "$PROJECT_DIR/studio"
python3 -m streamlit run app.py \
    --server.port 8501 \
    --server.headless false \
    --browser.gatherUsageStats false
