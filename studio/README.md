# AI 创意工作站

本地应用，四种模式帮团队高效获取灵感、做调研、出方案、交作业。

## 给同事的使用指南

### macOS 用户

1. 解压 `studio_app.zip`
2. 双击 `studio/启动工作站.command`
3. 首次会自动安装依赖（1-2 分钟），之后秒开
4. 浏览器自动打开，在主页填 API Key → 选模式使用

### 手动启动

```bash
# 安装依赖
pip install -r requirements.txt

# 启动
cd studio
streamlit run app.py
```

## 四种模式

- **💡 灵感** — 5 个 AI 角色四轮脑暴，产出创意全清单 + AI 深化 Prompt
- **📋 规划** — 六步理性规划，从问题定义到可执行方案
- **🎨 创作** — 选题 → 分镜 Prompt → 执行 Brief，一站式创作
- **🔍 调研** — Fact-Checked 深度研究，多来源交叉验证

每个模式都可以从下拉框选择 **CN MKT 营销知识库** 作为背景参考。

## 模型配置

支持所有 OpenAI 兼容 API，快速配置选一个服务商、填一个 Key 就行：

| 服务商 | 申请地址 |
|--------|----------|
| DeepSeek | https://platform.deepseek.com |
| Gemini | https://aistudio.google.com/apikey |
| GPT-4o | https://platform.openai.com |
| Kimi | https://platform.moonshot.cn |
| 通义千问 | https://dashscope.console.aliyun.com |

三个模型插槽（主力/创意/长文本）可以填同一个，也可以混搭。

## 系统要求

- Python 3.9+
- macOS / Linux / Windows（Windows 用手动启动方式）
