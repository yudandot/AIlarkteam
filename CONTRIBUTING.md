# 贡献指南

感谢你对 Awesome Lark Bots 的关注！无论是修复 bug、完善文档还是提出新想法，我们都非常欢迎。

## 如何参与

### 提 Issue

- **Bug 反馈**：请描述复现步骤、期望行为和实际行为，附上相关日志
- **功能建议**：描述你想要的功能、使用场景，以及你觉得合适的实现方式
- **问题讨论**：任何关于架构、使用方式的问题都可以开 Issue 讨论

### 提 Pull Request

1. Fork 本仓库
2. 创建你的分支：`git checkout -b feat/your-feature`
3. 开发并测试你的改动
4. 提交：`git commit -m "feat: 添加xxx功能"`
5. 推送：`git push origin feat/your-feature`
6. 在 GitHub 上发起 Pull Request

### 分支命名建议

| 前缀 | 用途 | 示例 |
|------|------|------|
| `feat/` | 新功能 | `feat/weibo-collector` |
| `fix/` | Bug 修复 | `fix/webhook-timeout` |
| `docs/` | 文档改进 | `docs/conductor-guide` |
| `refactor/` | 重构 | `refactor/llm-client` |

### Commit 消息格式

采用简化的 [Conventional Commits](https://www.conventionalcommits.org/) 风格：

```
<type>: <description>

feat: 添加微博采集器
fix: 修复飞书 Webhook 超时问题
docs: 补充 conductor 部署说明
refactor: 提取 LLM 调用公共逻辑
```

## 开发环境搭建

```bash
# 克隆项目
git clone https://github.com/yudandot/awesome-lark-bots.git
cd awesome-lark-bots

# 安装依赖（推荐 Python 3.11+）
pip3 install -r requirements.txt

# 复制环境变量模板
cp .env.example .env
# 编辑 .env，填入你的飞书凭证和 LLM API Key

# 启动任意一个机器人试试
python3 -m brainstorm
```

最低配置只需要 3 个变量：`FEISHU_APP_ID` + `FEISHU_APP_SECRET` + `DEEPSEEK_API_KEY`。

## 项目结构快速了解

```
core/           → 共享模块（LLM、飞书 API），改这里会影响所有机器人
brainstorm/     → 脑暴机器人（独立）
planner/        → 规划机器人（独立）
assistant/      → 助手机器人（独立）
creative/       → 创意 Prompt 机器人（独立）
sentiment/      → 舆情监控机器人（独立）
newsbot/        → 早知天下事（独立）
conductor/      → 自媒体助手，编排以上模块（⚠️ 探索阶段）
```

每个机器人都可以独立运行和开发，互不干扰。如果你只关心某个模块，直接看对应目录即可。

## 特别欢迎的贡献方向

以下是我们目前特别需要帮助的方向（详见 README 的 Roadmap）：

- **conductor（自媒体助手）自动发布流程**：探索更稳定的自媒体平台自动发布方式
- **更多平台采集器**：为 `sentiment/` 和 `newsbot/` 添加新的数据源
- **内容质量评估**：自动评估 AI 生成内容的质量
- **多语言支持**：让机器人能处理英文等其他语言
- **测试覆盖**：为核心模块添加单元测试

## 行为准则

- 尊重每一位参与者
- 保持友善、建设性的讨论
- 遇到分歧时，以数据和用户价值为导向

## 许可证

参与贡献即表示你同意你的贡献将以 [MIT 许可证](LICENSE) 发布。
