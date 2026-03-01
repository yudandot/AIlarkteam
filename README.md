# Awesome Lark Bots — 飞书 AI 机器人团队

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org)

**[English](#english)** | **中文**

一套在飞书（Lark）上运行的开源 AI 机器人，覆盖**创意脑暴、项目规划、日常助手、素材 Prompt 生成、舆情监控、新闻聚合、自媒体全流程编排**七大场景。

> **这是一个活跃探索中的项目。** 我们把它开源出来，是因为相信 AI + 飞书的自动化工作流有很大的想象空间，也希望有更多人一起来完善它。欢迎提 Issue、提 PR，或者单纯 star 一下表示支持。

### 为什么做这个？

我们相信 **不需要给 AI 完整的系统权限，也能让它帮你把大部分工作干了。**

思路很简单：

- **日常自动化**（脑暴、规划、舆情采集、内容创作、定时发布……）→ 部署在云端，用**飞书聊天**作为交互入口，随时随地发条消息就能触发，轻量、安全、低权限
- **深度任务**（复杂架构设计、大规模代码重构……）→ 需要时再用 Claude Code 等重型工具，按需授权

大多数工作场景不需要把钥匙全交给 AI。一个聊天窗口 + 几个专注的机器人，够了。

---

## 七个机器人一览

| 机器人 | 一句话介绍 | 在飞书上怎么用 | 启动命令 |
|--------|-----------|---------------|----------|
| **自媒体助手** ⚗️ | 自媒体全流程编排：输入主题 → 自动脑暴+规划+创作+存储+定时发布 | 发消息：`春天穿搭分享` 或 `深度：新品发布会` | `python3 -m conductor` |
| **脑暴机器人** | 5 个 AI 角色模拟真人团队讨论，四轮产出创意方案 | 发消息：`咖啡品牌 × 音乐节跨界联动` | `python3 -m brainstorm` |
| **规划机器人** | 六步结构化决策 + 自动生成飞书文档（Brief / 日历 / 时间线 / Spec 等 10 种） | 发消息：`规划：Q3 用户增长策略` | `python3 -m planner` |
| **助手机器人** | 备忘+线程、项目管理（飞书表格）、财务（记账/预算/目标）、联网研究、日/周/月报 | 发消息：`创建项目 Q2营销` / `记账 午餐 35` | `python3 -m assistant` |
| **创意 Prompt** | 生成 Seedance / Nano Banana 等 AI 工具可用的素材 prompt | 发消息：`春日樱花的抖音预告` | `python3 -m creative` |
| **舆情监控** | 从微博/抖音/小红书等 15 个平台采集社媒数据 | 发消息：`周报` / `采集 咖啡品牌 @微博 7天` | `python3 -m sentiment` |
| **早知天下事** | 多源新闻聚合 + AI 分析，每日推送新闻简报 | 发消息：`新闻` / `科技新闻` | `python3 -m newsbot` |

> ⚗️ **自媒体助手**目前处于探索阶段——基本框架已搭好，能跑通"选题→脑暴→规划→创作→存储"全流程，但在内容自动生成的质量把控和自媒体平台自动发布方面，还有很多需要探索和优化的空间。我们非常欢迎社区一起来完善这个模块。

七个机器人**共享底层模块**（LLM 调用、飞书 API），各自独立运行、互不干扰。
**自媒体助手是总编排者**——它会自动调用脑暴、规划、创意 Prompt 等模块完成完整的内容生产流程。

---

## 新手上路（3 步开始）

### 第 1 步：安装依赖

```bash
# 需要 Python 3.11+
pip3 install -r requirements.txt
```

### 第 2 步：配置环境变量

```bash
cp .env.example .env
```

然后用编辑器打开 `.env`，按需填入以下内容：

| 变量 | 必填？ | 说明 |
|------|--------|------|
| `FEISHU_APP_ID` | 必填 | 飞书应用的 App ID（所有机器人可共用） |
| `FEISHU_APP_SECRET` | 必填 | 飞书应用的 App Secret |
| `DEEPSEEK_API_KEY` | 必填 | DeepSeek 的 API Key（主力大模型） |
| `DOUBAO_API_KEY` | 脑暴必填 | 豆包的 API Key |
| `KIMI_API_KEY` | 脑暴必填 | Kimi 的 API Key |
| `FEISHU_WEBHOOK` | 推荐 | 飞书群 Webhook URL，用于实时推送讨论过程 |
| `JOA_TOKEN` | 舆情必填 | JustOneAPI 的 Token，用于社媒数据采集 |

> 完整变量说明见 `.env.example` 文件中的注释。

### 第 3 步：启动机器人

```bash
# 选一个启动（或同时运行多个）
python3 -m brainstorm    # 脑暴机器人
python3 -m planner       # 规划机器人
python3 -m assistant     # 助手机器人
python3 -m creative      # 创意 Prompt 机器人
python3 -m sentiment     # 舆情监控机器人
```

启动后，在飞书上给对应的机器人发消息就能用了。

---

## 飞书开放平台配置（首次需要）

每个机器人需要一个飞书应用（也可以多个机器人共用一个应用）：

1. 登录 [飞书开放平台](https://open.feishu.cn/app)，创建一个「自建应用」
2. 在应用详情页「凭证与基础信息」获取 **App ID** 和 **App Secret**，填入 `.env`
3. 「机器人」→ 启用机器人，勾选 **接收消息**、**发送消息**
4. 「事件订阅」→ 选择 **「长连接」** 模式（无需填 URL）
5. 添加事件：**「接收消息 v2.0」**（`im.message.receive_v1`）等
6. 发布应用，运行 `python3 -m xxx` 并保持程序运行

> 程序通过长连接(WebSocket)接收飞书消息，断线自动重连。

### 多机器人凭证配置

七个机器人可以**共用一套**飞书应用凭证，也可以各自使用独立应用。

> **关键规则：同时运行多个机器人时，不要让它们共用同一个 App ID。** 飞书按应用推事件——同一个 App ID 的所有长连接都会收到同一份消息，会导致多个机器人同时响应。

**最简配置（只跑 1-2 个）：** 只填 `FEISHU_APP_ID` + `FEISHU_APP_SECRET`，所有机器人共用。

**同时跑多个：** 为每个机器人创建独立的飞书应用，在 `.env` 中分别配置专用凭证：

| 机器人 | 专用凭证（优先） | 未配时回退到 |
|--------|------------------|-------------|
| **脑暴** | 直接使用主凭证 | `FEISHU_APP_ID` / `FEISHU_APP_SECRET` |
| **规划** | `PLANNER_FEISHU_APP_ID` / `SECRET` | 主凭证 |
| **助手** | `ASSISTANT_FEISHU_APP_ID` / `SECRET` | 主凭证 |
| **创意 Prompt** | `CREATIVE_FEISHU_APP_ID` / `SECRET` | 主凭证 |
| **舆情** | `SENTIMENT_FEISHU_APP_ID` / `SECRET` | 主凭证 |
| **自媒体助手** | `CONDUCTOR_FEISHU_APP_ID` / `SECRET` | 主凭证 |
| **早知天下事** | `NEWSBOT_FEISHU_APP_ID` / `SECRET` | 主凭证 |

> 详细说明见 [docs/FEISHU_APP_IDS.md](docs/FEISHU_APP_IDS.md)，自媒体助手的逐步接入说明见 [conductor/FEISHU_SETUP.md](conductor/FEISHU_SETUP.md)。

---

## 七个机器人详解

### 1. 脑暴机器人 (`brainstorm/`)

给机器人发消息即可触发 AI 多角色脑暴。

**坚果五仁团队**（5 个 AI 角色，各有分工）：

| 角色 | 定位 | 使用的大模型 | 职责 |
|------|------|-------------|------|
| 芝麻仁 | 现实架构师 | DeepSeek | 执行可行性、成本、约束 |
| 核桃仁 | 玩家化身 | 豆包 | 第一人称验证体验真实性 |
| 杏仁 | 体验导演 | Kimi | 设计具体瞬间、情绪峰值 |
| 瓜子仁 | 传播架构师 | Kimi | 设计可分享单元、传播路径 |
| 松子仁 | 体验总成 | DeepSeek | 收敛、裁决、产出最终交付物 |

**四轮讨论流程：**
1. **Idea Expansion（发散）** → 产出约 10 个体验方向
2. **Experience Embodiment（具象）** → 压缩为 6 个可执行候选
3. **Brutal Selection（淘汰）** → 三道筛子，只留 3 个方向
4. **Execution Conversion（交付）** → 讨论总结 + Claude Code prompt + 视觉 prompt

**也可 CLI 运行（不需要飞书）：**
```bash
python3 -m brainstorm.run --topic "咖啡品牌 × 音乐节跨界联动" --context "背景材料"
```

### 2. 规划机器人 (`planner/`)

给机器人发消息即可启动理性规划。支持两种交互模式：

- **直接聊** → 像朋友一样讨论，给判断、给方案、指出盲区
- **发「规划：话题」** → 启动六步结构化深度拆解，完成后可生成飞书文档

**五种规划模式：**
| 模式 | 包含步骤 | 适合场景 |
|------|---------|---------|
| 完整规划 | 问题定义→现状分析→方案生成→评估矩阵→执行计划→反馈机制 | 重大决策 |
| 快速模式 | 问题定义→方案生成→评估→执行计划 | 日常规划 |
| 分析模式 | 问题定义+现状分析 | 想先看看分析 |
| 方案模式 | 生成 3 个方案 | 只要选项 |
| 执行模式 | 执行计划 | 已有方向，要落地步骤 |

**文档交付：** 规划完成后自动弹出文档菜单，根据话题类型智能推荐：

| 话题类型 | 检测信号 | 可生成的文档 |
|---------|---------|------------|
| 营销/活动 | 营销、品牌、落地、二创、小红书… | 执行 Brief、内容日历、里程碑时间线、决策备忘 |
| 旅行 | 旅行、机票、酒店、行程… | 行程表、预算清单、打包清单、决策备忘 |
| 创意项目 | 项目、开发、做个、MVP、app… | 项目 Spec、功能优先级、行动清单、决策备忘 |
| 通用 | 默认 | 执行 Brief、行动清单、里程碑时间线、决策备忘 |

- 回复数字选择文档（`1` 单个 / `123` 多个合并 / `全部`）
- 自动创建飞书云文档（支持标题、加粗、列表等格式）并发送链接
- 文档标题由 LLM 自动凝练（如"五月日本十日游 — 执行 Brief"）

**切换模式：** 在消息前加模式名，如 `快速模式：下周产品发布计划`

**也可 CLI 运行：**
```bash
python3 -m planner.run --topic "Q3 用户增长策略" --mode "快速模式"
```

### 3. 助手机器人 (`assistant/`)

全能工作搭档：备忘+线程、项目管理、财务管理、联网研究、日/周/月报。

**备忘 + 工作线程：**
```
备忘 完成 deck #creator    → 记备忘并归入 #creator 线程
线程 / 周报 / 看板         → 查看线程 · 导出飞书表格
完成 3 / 完成 买牛奶       → 标记完成
```

**项目管理（飞书电子表格）：**
```
创建项目 Q2营销             → 新建飞书项目表（任务·来源·负责人·状态·优先级·截止·备注）
Q2营销 加任务 写推广方案    → 往项目表追加一行
发飞书妙记链接              → 自动归档到项目表
项目列表                    → 查看所有项目
Q2营销 总览                 → 任务 + 预算 + 目标全维度仪表盘
```

**财务管理：**
```
记账 午餐 35 #Q2营销        → 记一笔支出，带项目标签
直接丢费用清单              → AI 自动逐行识别并入账
创建预算 Q2营销             → 设定各项预算额度
Q2营销 预算                 → 查看预算 vs 实际执行率
Q2营销 设目标 新增用户 10000 人  → 设定 KPI 目标
更新目标 新增用户 7500      → 更新进度
本月花费                    → 按类别+项目的月度汇总
```

**联网研究：**
```
研究 Character.ai 增长机制        → 多来源搜索 + 交叉验证 + 结构化报告
fact check Threads 增长是 organic 吗  → 事实核查模式
```

**日程 & 简报：**
```
明天下午3点开会              → 自动加入飞书日历
今天 / 明天                 → 查看日程
月报 / 3月月报              → 线程+项目+财务全维度月度总结
```

**自动推送：**
- 08:00 晨报：日程 + 线程 + 项目状态 + 预算告警 + 到期提醒
- 18:00 收尾：今日回顾 + 项目/财务异常提醒
- 周一 09:00 周报：线程 + 预算执行 + 目标进度
- 月度报告：线程 + 项目 + 财务全维度总结（手动触发或定时）

### 4. 创意 Prompt 机器人 (`creative/`)

告诉它你想要什么素材，它生成可以直接复制到 AI 工具的 prompt。

**两种使用方式：**
```
直接生成：春日樱花主题的抖音预告               → 立即出 prompt
先聊后出：聊聊：我想做一个关于重逢的视频       → 多轮讨论
         生成                                  → 从讨论内容生成正式 prompt
```

**修改和品牌切换：**
```
改一下：更温暖一些         → 基于上次结果修改
品牌：mybrand              → 切换到指定品牌 profile
品牌                       → 查看可用品牌列表
```

**输出内容：**
- 中文结构化 Prompt（画面/场景/镜头/氛围/风格）
- Seedance 英文版（可直接复制粘贴到 AI 工具）
- 超 15 秒需求自动分镜 + 角色一致性建议
- 配套平台文案

### 5. 自媒体助手 (`conductor/`)

输入一个主题，自媒体助手自动完成：扫描热点 → 产出创意 → 生成内容 → 存储到内容仓库。

**两种模式：**

| 模式 | 说明 | 耗时 | 用法 |
|------|------|------|------|
| 快速模式 | LLM 直接产出创意 + 生成内容 | 1-3 分钟 | 直接发主题 |
| 深度模式 | 调用脑暴五人团队 + 规划引擎 + 生成内容 | 5-15 分钟 | `深度：主题` |

**内容管理：**
```
草稿                           → 查看所有内容
详情 abc123                    → 查看完整内容（文案+视觉Prompt）
发布 abc123                    → 审批通过
定时 abc123 10:00              → 设置定时发布
删除 abc123                    → 删除内容
品牌 mybrand                   → 切换品牌
平台 小红书 抖音                → 设置目标平台
```

**内容仓库状态机：** 草稿(draft) → 待发布(ready) → 已发布(published)，支持定时发布(scheduled)。

**也可 CLI 运行：**
```bash
python3 -m conductor.cli --topic "春天穿搭分享" --platforms "小红书 抖音"
python3 -m conductor.cli --topic "新品发布会" --deep --brand mybrand
python3 -m conductor.cli --list           # 查看内容仓库
python3 -m conductor.cli --detail abc123  # 查看内容详情
```

### 6. 舆情监控机器人 (`sentiment/`)

从社交媒体平台采集数据，生成结构化分析材料。

**快捷报告（一键使用）：**
```
周报                       → 默认品牌舆情周报（7天）
双周报 品牌名              → 指定品牌双周报（14天）
月报                       → 默认品牌月报（30天）
```

**自定义采集：**
```
采集 黄飞鸿 叶问 @微博 @B站 7天
采集 iPhone17 @全平台 3天 200条
咖啡品牌 @抖音 @小红书 14天 50条
```

**支持 15 个平台：**
- 国内社媒：微博、抖音、小红书、B站、快手、知乎、头条、微信
- 海外社媒：TikTok、YouTube、Twitter、Instagram、Facebook
- 电商平台：淘宝、拼多多

**可选 AI 分析：** 在指令末尾加 `+分析`，同时生成 AI 分析报告

### 7. 早知天下事 (`newsbot/`)

多源新闻采集 + AI 分析，自动生成结构化日报并推送到飞书群。

**使用方式：**
```
新闻                       → 手动触发今日新闻汇总
科技新闻                   → 按领域筛选
```

**新闻来源覆盖：**
- 华人圈 / 亚太 / 欧美 / 全球热点
- 自动去重、分段推送（绕开飞书单条消息字数限制）
- 支持定时自动推送

---

## 项目结构

```
awesome-lark-bots/
│
├── core/                     # 共享核心模块（所有机器人都用）
│   ├── llm.py                #   大模型调用封装（DeepSeek/豆包/Kimi）
│   ├── feishu_client.py      #   飞书 API（消息、日历、文档）
│   ├── feishu_webhook.py     #   飞书群 Webhook 推送
│   ├── skill_router.py       #   技能路由器（自动注入领域知识到 prompt）
│   └── utils.py              #   工具函数（截断、时间戳、文件保存）
│
├── brainstorm/               # 脑暴机器人
│   ├── bot.py                #   飞书长连接入口（接收消息 → 启动脑暴）
│   ├── run.py                #   主流程引擎（四轮讨论 + 交付物生成）
│   └── __main__.py           #   启动入口：python3 -m brainstorm
│
├── planner/                  # 规划机器人
│   ├── bot.py                #   飞书长连接入口（对话+规划+文档交付）
│   ├── run.py                #   主流程引擎（六步规划 + 文档生成）
│   ├── prompts.py            #   规划提示词 + 10 种文档模板
│   └── __main__.py           #   启动入口：python3 -m planner
│
├── assistant/                # 助手机器人
│   ├── bot.py                #   飞书长连接入口（备忘+日程+研究+对话）
│   └── __main__.py           #   启动入口：python3 -m assistant
│
├── research/                 # 联网研究模块（助手机器人调用）
│   ├── researcher.py         #   研究引擎：多来源搜索+交叉验证+报告生成
│   └── search.py             #   搜索抽象层（Tavily / DuckDuckGo）
│
├── creative/                 # 创意 Prompt 机器人
│   ├── bot.py                #   飞书长连接入口（生成+讨论+品牌切换）
│   ├── knowledge.py          #   品牌知识库和提示词构建
│   └── __main__.py           #   启动入口：python3 -m creative
│
├── conductor/                # 自媒体助手（全流程编排）
│   ├── bot.py                #   飞书长连接入口（消息路由+内容管理）
│   ├── cli.py                #   CLI 入口：python3 -m conductor.cli
│   ├── pipeline.py           #   Pipeline 编排引擎（串联六阶段）
│   ├── store.py              #   内容仓库（存储+检索+状态管理）
│   ├── scheduler.py          #   定时调度器（定时发布+自动扫描）
│   ├── config.py             #   配置（平台定义+安全阈值）
│   ├── models.py             #   数据模型
│   └── stages/               #   六个阶段实现
│       ├── trend_scanner.py  #     感知：扫描各平台热点
│       ├── idea_engine.py    #     构思：调用脑暴/规划产出创意
│       ├── content_factory.py#     创作：生成文案+视觉Prompt
│       ├── publisher.py      #     发布：存储+发布到平台
│       ├── engager.py        #     互动：监控评论+自动回复
│       └── reviewer.py       #     复盘：效果分析+改进建议
│
├── sentiment/                # 舆情监控机器人
│   ├── bot.py                #   飞书长连接入口（指令解析+引导对话）
│   ├── runner.py             #   采集流程编排（采集→统计→导出→上传）
│   ├── exporter.py           #   数据导出（JSON + Markdown）
│   ├── feishu_api.py         #   飞书 API（舆情机器人专用）
│   ├── github_client.py      #   GitHub 上传
│   └── __main__.py           #   启动入口：python3 -m sentiment
│
├── memo/                     # 备忘 + 项目 + 财务模块（助手机器人使用）
│   ├── store.py              #   备忘本地存储（线程安全，支持 #thread 标签、看板导出）
│   ├── intent.py             #   意图解析（30+ 指令：备忘/项目/财务/研究/日程）
│   ├── threads.py            #   线程自动识别（从 personal skill 信号词）
│   ├── projects.py           #   项目注册表（name → 飞书电子表格 token 映射）
│   └── finance.py            #   财务管理（记账/预算/目标/月度汇总）
│
├── cal/                      # 日程模块（助手机器人使用）
│   ├── aggregator.py         #   多源日程聚合（飞书 + Google + 备忘）
│   ├── google_calendar.py    #   Google 日历拉取
│   ├── daily_brief.py        #   每日简报生成与推送
│   └── push_target.py        #   推送接收人管理
│
├── prompts.json              # 脑暴「坚果五仁」角色配置
├── skills/                    # 共享技能库（9 个技能，自动路由注入 prompt）
│   ├── __init__.py            #   Skill 基类 + 注册表 + 自动发现
│   ├── __main__.py            #   CLI: python3 -m skills list / test / activate
│   ├── personal.py            #   个人合作风格（加载 profiles/ 下的用户 profile）
│   ├── decision_frameworks.py #   决策框架（第一性原理、pre-mortem、约束理论等）
│   ├── stakeholder.py         #   利益相关方对齐（利益地图、提案包装、阻力预判）
│   ├── cross_cultural.py      #   跨文化策略（高/低语境、本地化层级）
│   ├── brand.py               #   品牌知识（加载 creative/brands/*.yaml）
│   ├── marketing.py           #   营销方法论（加载 CN-MKT-Skills/）
│   ├── platforms.py           #   平台运营指南（加载 platform_guides/）
│   ├── copywriting.py         #   经典文案框架（AIDA、PAS、FAB 等）
│   └── calendar.py            #   营销日历（节日、大促、季节性主题）
│
├── CN-MKT-Skills/            # 营销技能知识库（规划机器人可参考）
├── briefs/                   # 脑暴主题 brief 文件
├── runs/                     # 运行记录输出（自动生成）
├── data/                     # 数据目录（备忘、推送目标等）
│
├── requirements.txt          # Python 依赖列表
├── .env.example              # 环境变量配置模板
├── docker-compose.yml        # Docker 部署配置
└── README.md                 # 本文件
```

---

## LLM 使用说明

项目通过 `core/llm.py` 统一调用大模型，**兼容所有 OpenAI API 协议的服务商**。你可以自由替换为自己偏好的模型，只需在 `.env` 中修改对应的 API Key、Base URL 和模型名即可。

目前默认配置使用三家国产大模型服务商，各有分工：

| 大模型 | 擅长 | 在哪用 |
|--------|------|--------|
| **DeepSeek** | 逻辑推理、结构化输出 | 规划机器人全程、助手机器人、脑暴中的策略角色、创意 Prompt |
| **豆包(Doubao)** | 创意发散 | 脑暴中的创意角色（核桃仁） |
| **Kimi** | 长文本理解 | 脑暴中的素材角色、最终交付物生成 |

> 这只是我们目前在尝试的组合。你完全可以换成 OpenAI、Claude、通义千问、智谱 GLM 或任何兼容 OpenAI 协议的模型——改 `.env` 里的三个变量（`*_API_KEY`、`*_BASE_URL`、`*_MODEL`）就行。

---

## 技能系统 (Skills)

所有机器人共享一套**可插拔的技能库**（`skills/`），通过 `core/skill_router.py` 自动路由——bot 只需一行代码即可获得领域知识增强：

```python
from core.skill_router import enrich_prompt

system = enrich_prompt("你是内容助手...", user_text=msg, bot_type="creative")
```

路由器会根据**用户消息关键词**和**bot 类型**自动判断需要加载哪些技能，将知识追加到 system prompt 中。

**内置技能：**

| 技能 | 说明 | 自动激活 |
|------|------|---------|
| `personal` | 个人工作风格与偏好（从 `skills/profiles/` 加载） | 所有核心 bot |
| `decision_frameworks` | 第一性原理、pre-mortem、Type 1/2 决策、约束理论、MECE | planner |
| `stakeholder` | 利益相关方对齐：利益地图、提案包装、阻力预判 | planner（多方信号时） |
| `cross_cultural` | 跨文化策略：高/低语境、本地化层级、平台生态差异 | planner（全球/海外信号时） |
| `brand` | 品牌视觉风格、调性、场景（从 `creative/brands/` 加载） | creative / conductor |
| `marketing` | 营销方法论与策略框架（从 `CN-MKT-Skills/` 加载） | planner / conductor |
| `platform` | 平台运营指南（从 `skills/platform_guides/` 加载） | conductor / planner |
| `copywriting` | 经典文案框架（AIDA、PAS、FAB 等）+ 内容格式模板 | conductor |
| `calendar` | 营销日历：节日节点、电商大促、季节性主题 | planner / conductor |

> 数据类技能（personal、brand、marketing、platform、calendar）的实际内容存放在本地，不上传 GitHub。代码仓库只包含加载器代码和模板文件。

**扩展新技能**：在 `skills/` 下新建 `.py` 文件，继承 `Skill` 基类并 `register()` 即可，详见 [`skills/README.md`](skills/README.md)。

```bash
python3 -m skills list                      # 列出所有技能
python3 -m skills activate "帮我做品牌推广"   # 查看哪些技能会被激活
python3 -m skills test personal              # 测试某个技能的输出
```

---

## Docker 部署

```bash
# 启动所有机器人
docker-compose up -d

# 启动指定机器人
docker-compose up -d brainstorm planner

# 查看日志
docker-compose logs -f brainstorm
```

---

## 常见问题

**Q: 程序启动后提示连接失败？**
检查：1) App ID / App Secret 是否正确  2) 应用是否已发布  3) 网络是否能访问 open.feishu.cn

**Q: 脑暴/规划结果在飞书群里看不到？**
确认 `FEISHU_WEBHOOK` 是否配置。结果通过 Webhook 推送到群，如果没配，只会保存到本地 `runs/` 目录。

**Q: 助手的日程管理提示「权限不足」？**
往个人日历加日程需要用户身份授权。请在 `.env` 中配置 `FEISHU_TOKEN_CALENDAR_CREATE`。

**Q: 可以只运行其中一个机器人吗？**
可以。每个机器人完全独立，按需启动即可。最低只需要 `FEISHU_APP_ID` + `FEISHU_APP_SECRET` + `DEEPSEEK_API_KEY`。

**Q: 运行记录保存在哪？**
所有运行结果保存在项目根目录的 `runs/` 文件夹，格式为 Markdown。

---

## Roadmap

以下是我们正在探索和希望社区一起推进的方向：

### 自媒体助手（conductor）— 核心探索方向
- [ ] **内容质量自动评估**：AI 生成的内容如何自动判断"够不够好"，避免发出低质量内容
- [ ] **自媒体平台自动发布**：更稳定的方式把内容发布到小红书、抖音、微博等平台
- [ ] **多平台内容适配**：同一个创意，自动适配不同平台的格式、风格和字数要求
- [ ] **数据驱动选题**：根据历史数据表现反馈，优化未来的内容选题方向
- [ ] **人机协作流程**：在关键节点（如选题确认、发布前审核）加入人工介入机制

### 各模块改进
- [ ] **脑暴**：支持自定义 AI 角色组合、更多大模型接入
- [ ] **舆情**：更多平台采集器、情感分析准确度提升
- [ ] **新闻聚合**：更多新闻源、可自定义的关注领域
- [ ] **创意 Prompt**：支持更多 AI 生成工具（MidJourney、Sora 等）的 prompt 格式

### 基础设施
- [ ] 单元测试覆盖核心模块
- [ ] 多语言支持（英文等）
- [ ] 更完善的错误处理和重试机制
- [ ] Web 管理面板（查看运行状态、管理内容）

欢迎在 [Issues](../../issues) 中讨论任何想法，或直接提 PR。

---

## 参与贡献

我们非常欢迎各种形式的贡献！详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

无论是修一个 typo、加一个采集器、改善一段 prompt，还是重构整个模块——每一份贡献都有价值。

---

## 许可证

[MIT License](LICENSE) — 你可以自由使用、修改和分发。

---

<a name="english"></a>

## English

### What is Awesome Lark Bots?

A collection of 7 open-source AI bots running on **Feishu (Lark)**, covering brainstorming, planning, daily assistance, creative prompt generation, social media monitoring, news aggregation, and end-to-end content creation workflows.

All bots are **compatible with any LLM that supports the OpenAI API protocol** — DeepSeek, OpenAI, Claude, Doubao, Kimi, Qwen, GLM, and more. Just change the API keys in `.env`.

### Why?

**You don't need to give AI full system access to get real work done.**

Our approach:

- **Routine automation** (brainstorming, planning, content creation, social monitoring, publishing…) → runs in the cloud, with **Feishu chat as the frontend**. Send a message, get things done. Lightweight, secure, minimal permissions.
- **Deep work** (complex architecture, large-scale refactoring…) → use heavy-duty tools like Claude Code when needed, with explicit access.

Most work scenarios don't require handing over all the keys. A chat window + a few focused bots is enough.

### The 7 Bots

| Bot | What it does | Command |
|-----|-------------|---------|
| **Content Assistant** ⚗️ | End-to-end content pipeline: topic → brainstorm → plan → create → store → publish | `python3 -m conductor` |
| **Brainstorm** | 5 AI personas simulate a real team discussion in 4 rounds | `python3 -m brainstorm` |
| **Planner** | 6-step structured decisions + auto-generate Feishu docs (Brief / Calendar / Spec, 10 types) | `python3 -m planner` |
| **Assistant** | Memos + threads, project management (Feishu Sheets), finance (expenses/budgets/goals), web research, daily/weekly/monthly reports | `python3 -m assistant` |
| **Creative Prompt** | Generate prompts for Seedance / MidJourney / Sora and other AI tools | `python3 -m creative` |
| **Sentiment Monitor** | Collect social media data from 15 platforms (Weibo, Douyin, Xiaohongshu, TikTok, etc.) | `python3 -m sentiment` |
| **News Digest** | Multi-source news aggregation + AI analysis, daily push | `python3 -m newsbot` |

> ⚗️ **Content Assistant** is in active exploration — the basic framework works end-to-end, but content quality control and automated publishing to social media platforms are still areas we're actively improving. Community contributions are very welcome!

### Quick Start

```bash
# 1. Install dependencies (Python 3.11+)
pip3 install -r requirements.txt

# 2. Configure environment variables
cp .env.example .env
# Edit .env — minimum: FEISHU_APP_ID + FEISHU_APP_SECRET + DEEPSEEK_API_KEY

# 3. Start any bot
python3 -m brainstorm    # Brainstorm bot
python3 -m planner       # Planner bot
python3 -m assistant     # Assistant bot
python3 -m creative      # Creative Prompt bot
python3 -m sentiment     # Sentiment Monitor
python3 -m newsbot       # News Digest
python3 -m conductor     # Content Assistant
```

### Feishu (Lark) Setup

1. Go to [Feishu Open Platform](https://open.feishu.cn/app) and create an app
2. Get the **App ID** and **App Secret**, put them in `.env`
3. Enable **Bot** capability, subscribe to **Receive Message v2.0** event
4. Choose **Long Connection (WebSocket)** mode — no public URL needed
5. Publish the app, run the bot, and send it a message on Feishu

**Running multiple bots:** Each bot can share one Feishu app, or use its own. When running multiple bots simultaneously, give each a separate App ID to avoid them all receiving the same messages. Each bot has its own `XXX_FEISHU_APP_ID` / `XXX_FEISHU_APP_SECRET` env vars (e.g. `PLANNER_FEISHU_APP_ID`), falling back to the main `FEISHU_APP_ID` if not set. See [docs/FEISHU_APP_IDS.md](docs/FEISHU_APP_IDS.md) for the full mapping.

### LLM Compatibility

The project calls LLMs through `core/llm.py` using the OpenAI-compatible API protocol. You can swap in **any provider** by changing three variables in `.env`:

- `*_API_KEY` — your API key
- `*_BASE_URL` — the provider's API endpoint
- `*_MODEL` — the model name

Currently configured with DeepSeek, Doubao, and Kimi as a starting point, but OpenAI, Claude, Qwen, GLM, and others all work.

### Skills System

All bots share a **plug-and-play skill library** (`skills/`), auto-routed via `core/skill_router.py` — one line of code gives any bot domain-knowledge augmentation:

```python
from core.skill_router import enrich_prompt
system = enrich_prompt("You are a content assistant...", user_text=msg, bot_type="creative")
```

The router checks **user message keywords** and **bot type** to decide which skills to load, appending domain knowledge to the system prompt.

| Skill | Description | Auto-activates for |
|-------|-------------|-------------------|
| `personal` | Personal working style & preferences | all core bots |
| `decision_frameworks` | First principles, pre-mortem, Type 1/2, constraint theory, MECE | planner |
| `stakeholder` | Stakeholder alignment: interest mapping, framing, resistance bypass | planner (multi-party) |
| `cross_cultural` | Cross-cultural strategy: high/low context, localization, platform diffs | planner (global) |
| `brand` | Brand visual style, tone, scenarios | creative / conductor |
| `marketing` | Marketing methodology & frameworks | planner / conductor |
| `platform` | Platform operation guides | conductor / planner |
| `copywriting` | Classic copywriting frameworks (AIDA, PAS, FAB, etc.) | conductor |
| `calendar` | Marketing calendar: holidays, promotions, seasonal themes | planner / conductor |

> Data-bearing skills keep their content local — only loader code and templates are in the repo.

Add custom skills by dropping a `.py` file in `skills/` — see [`skills/README.md`](skills/README.md).

```bash
python3 -m skills list                          # list all skills
python3 -m skills activate "brand promotion"    # see which skills activate
```

### Contributing

We welcome all contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### License

[MIT License](LICENSE)
