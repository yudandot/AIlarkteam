#!/bin/bash
# 启动 AI 创意工作站
cd "$(dirname "$0")"
streamlit run app.py --server.port 8501
