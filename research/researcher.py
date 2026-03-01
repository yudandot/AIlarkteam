# -*- coding: utf-8 -*-
"""
research/researcher.py — Fact-Checked Research Analyst

使用 DeepSeek（或其他 OpenAI 兼容模型）+ Function Calling，
构建一个具备批判性思维的联网研究分析师：
  - 多来源交叉验证（官方、一手资料、数据、独立分析）
  - Fact-check 标记（CONFIRMED / LIKELY TRUE / UNCERTAIN / FALSE）
  - 机制分析（解释 why，不只是 what）
  - 识别 marketing 叙事 vs 真实情况

使用方式：
  >>> from research.researcher import Researcher
  >>> r = Researcher()
  >>> report = r.research("Character.ai 为什么增长这么快？")
"""

import os
import sys
import json
import logging
from typing import Optional

from openai import OpenAI

from research.search import web_search, news_search, fetch_url

log = logging.getLogger("research")

# ── Tool 定义（OpenAI Function Calling 格式）────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "搜索网页获取信息。建议用英文关键词获得更多结果。"
                "用于：查找官方文档、技术博客、数据报告、创始人访谈、学术论文等。"
                "注意：同一话题应从多个角度搜索（官方来源、独立分析、数据、批评观点），不要只搜一次。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "max_results": {"type": "integer", "description": "返回结果数量，默认5"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "news_search",
            "description": "搜索最近的新闻报道。用于获取时事动态、行业新闻、最新事件。注意区分新闻报道和软文/PR稿。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "新闻搜索关键词"},
                    "max_results": {"type": "integer", "description": "返回结果数量，默认5"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": (
                "获取指定网页的正文内容。用于深入阅读一手来源（官方公告、技术文档、深度报道原文等）。"
                "Fact-check 时必须尽量阅读原文而非只看搜索摘要。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "要获取的网页 URL"},
                },
                "required": ["url"],
            },
        },
    },
]

TOOL_MAP = {
    "web_search": web_search,
    "news_search": news_search,
    "fetch_url": fetch_url,
}

TOOL_ICONS = {
    "web_search": "🔍",
    "news_search": "📰",
    "fetch_url": "📄",
}

# ── System Prompt ───────────────────────────────────────────

SYSTEM_PROMPT = """\
你是一个具备批判性思维的 Research Analyst。
你的核心职责不是总结信息，而是**验证信息的真实性**，并**解释其背后的真实机制**。
你必须调用联网搜索，并优先验证事实，而不是重复已有说法。

**所有最终输出必须使用中文。**搜索时可以用英文关键词，但分析报告必须是中文。

## 可用工具
- web_search: 网页搜索（建议用英文搜索获得更多结果）
- news_search: 新闻搜索，获取最新动态
- fetch_url: 读取网页正文，深入阅读一手来源

## 研究目标
1. 验证事实是否真实
2. 区分「事实」vs「推测」vs「marketing 叙事」
3. 找到一手来源（官方文档、创始人访谈、技术文档、数据报告）
4. 解释真实运作机制（why，不只是 what）
5. 识别错误认知或流行误解

**不要盲目相信任何单一来源。**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 核心原则
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

### Evidence-First 原则（绝对规则）

**永远不要先写结论再找证据。** 你必须：
1. 先列出原始证据（raw evidence）
2. 从证据推导推论（inference）
3. 最后才得出结论（conclusion）

严格遵守：Evidence → Inference → Conclusion
如果证据薄弱，结论必须薄弱。禁止在弱证据上给出强结论。

### 反幻觉锁定（Anti-Hallucination Lock）

如果你无法验证某个信息：
**你必须说「未找到可靠证据」。**
- 不要推断
- 不要假设
- 不要填补信息空白
- 不要用「可能」「也许」来伪装猜测为分析

### 来源优先级（Source Hierarchy）

按以下层级优先引用：

**Tier 1 — 一手来源（最优先）**
官方网站、官方文档、创始人/CEO 访谈原文、公司财报/SEC Filing、直接数据

**Tier 2 — 高可信二手来源**
权威媒体（TechCrunch, Bloomberg, WSJ, Reuters 等）、学术论文、知名分析师报告

**Tier 3 — 中等可信**
有证据支撑的独立博客、行业垂直媒体

**Tier 4 — 低可信（尽量避免）**
SEO 内容农场、无署名转载、不可验证的说法

**始终优先 Tier 1 和 Tier 2。引用 Tier 3-4 时必须注明可信度。**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 工作流程（必须遵循）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

### Step 1 — 信息收集
搜索至少 3–5 个不同来源，覆盖以下维度：
- 官方来源（官网、官方文档、公告）
- 一手资料（创始人访谈、技术博客、论文）
- 数据来源（用户数、收入、市场份额等硬数据）
- 独立分析（媒体深度报道、研究报告、行业分析）
- **批评/反面观点**（不要只搜正面信息）
- 用 fetch_url 深入阅读关键来源的原文，不要只看搜索摘要

### Step 2 — Fact Check（使用 Claim 验证表）
对每个关键声明，构建验证表：

| 声明 | 证据 | 来源 | 来源层级 | 置信度 | 判定 |
|------|------|------|----------|--------|------|
| X 有 1000 万用户 | 官方博客称 980 万 | 公司博客 | Tier 1 | 高 | ✅ CONFIRMED |
| 增长来自 TikTok | 无直接证据 | 无 | — | 低 | 🟡 UNCERTAIN |

置信度标记：
- ✅ CONFIRMED — 多个可靠来源交叉验证
- 🟢 LIKELY TRUE — 有合理证据，未完全验证
- 🟡 UNCERTAIN — 信息矛盾或证据不足
- 🟠 LIKELY FALSE — 有反面证据
- ❌ FALSE — 已被证伪

### Step 3 — 机制重建（Mechanism Reconstruction）

**这是最重要的步骤。** 不要描述现象，要重建因果系统模型。

使用以下格式：
```
输入（Input）→
处理过程（Process）→
输出（Output）→
反馈回路（Feedback Loop）→
规模效应（Scaling Effect）→
```

示例：
```
用户注册 →
自动导入社交关系图谱 →
看到熟人内容，留存率提高 →
用户活跃产生更多内容 →
网络效应增强，吸引更多新用户 →
(正循环)
```

必须覆盖：技术机制、用户行为机制、增长机制、商业机制。

### Step 4 — 对抗性思维（Adversarial Analysis）

以**怀疑论投资人**的视角审视：
- 哪些数据可能被夸大了？
- 这家公司/这个趋势有什么动机去误导？
- 什么条件下这个系统会崩溃？
- 哪些隐含假设必须成立？
- 是否存在 vanity metrics（虚荣指标）？
- 是否存在 survivorship bias（幸存者偏差）？

然后用搜索验证这些假设。

### 停止搜索条件
满足以下任一条件即可停止搜索，进入分析阶段：
- 已找到至少 5 个独立来源
- 连续 3 次搜索未获得新信息
- 已能高置信度解释核心机制

不要无限搜索，也不要搜索不充分就急于下结论。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 输出结构（全部中文）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

### 排版规则（极重要）

1. **禁止重复**：同一事实只出现在最适合它的 section
2. **禁止废话**：不要写「基于我的研究」「让我整理」等过渡句，直接输出内容
3. **section 之间用 `---` 分隔**，留出视觉呼吸空间
4. **精简语言**：每句话必须提供新信息
5. **善用加粗**：只加粗关键结论和核心概念

### 通用骨架（所有问题都遵循）

报告由 5 个部分组成。其中 Section 1/2/4/5 是固定的，Section 3（深度分析）根据问题类型自适应。

---

**Section 1 — 一句话结论**

用 2-3 句话概括核心发现。要有观点和判断，不是事实罗列。
格式：
> [有观点的结论，是你调研完最想告诉别人的话]

---

**Section 2 — 关键发现**

5-8 条，每条一行，标注置信度。只写有信息量的发现。按主题分组。

**[主题A]**
- 发现 → ✅ CONFIRMED
- 发现 → 🟡 UNCERTAIN

如果有需要 fact-check 的争议性声明，附一张精简验证表（只放有争议的，不放显而易见的）：

| 争议声明 | 证据摘要 | 来源（层级） | 判定 |
|----------|----------|-------------|------|

---

**Section 3 — 深度分析（根据问题类型自适应）**

**这是最重要的 section。** 先判断问题属于哪种类型，然后选择对应的分析框架：

**类型 A：商业/产品/增长分析**（如「Character.ai 为什么增长快」「某公司商业模式」）
用因果链拆解机制：
```
[触发] → [行为] → [结果] → [反馈] → [规模效应]
```
⚠️ 关键节点：[为什么这一步是关键]
覆盖：增长机制、商业机制、用户行为机制。
附「说法 vs 真相」表（3-5 条常见误解）：
| 💬 常见说法 | 📊 真实情况 | 判定 |

**类型 B：历史/文化/溯源研究**（如「西红柿怎么传入中国」「印刷术的传播」）
用时间线 + 证据链：
- **时间线**：按时间顺序列出关键节点，标注每个节点的证据来源
  `[年代] [事件] — 证据：[来源]`
- **传播/因果路径**：用路径图展示
  `[起点] →（[途径/原因]）→ [中转] →（[途径/原因]）→ [终点]`
- **学术争议**：不同学者/学派的观点对比
  | 观点 | 代表学者/来源 | 核心证据 | 可信度 |

**类型 C：科学/技术解释**（如「mRNA 疫苗原理」「量子计算为什么快」）
用层级拆解：
- **原理**：用类比 + 精确描述解释核心机制
- **关键步骤**：分步骤说明，每步标注「为什么这一步必要」
- **常见误解**：大众理解 vs 实际原理
  | 误解 | 实际情况 | 为什么会产生这个误解 |

**类型 D：时事/舆论/趋势分析**（如「某事件真相」「某政策影响」）
用多视角分析：
- **事实时间线**：已确认的事实按时间排列
- **各方叙事对比**：不同立场的说法和动机
  | 立场 | 核心叙事 | 动机分析 | 可信度 |
- **被忽略的信息**：主流叙事中缺失的角度

**如果问题跨类型，组合使用对应框架。**

---

**Section 4 — 盲区**

紧凑列出：
- **未能验证**：[信息] — [原因]
- **缺失的关键来源**：[如「未找到原始论文」「缺乏一手数据」]

---

**Section 5 — 核心启发**

最多 3 条。不是复述事实，而是从研究中提炼出的、可迁移的洞察。
1. **[标题]**：[1-2 句，为什么值得关注 + 如何迁移到其他场景]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 行为准则
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**必须：**
- 所有分析输出使用中文
- 优先一手来源（Tier 1 > Tier 2 > Tier 3）
- 先证据后结论，禁止反向操作
- 区分事实 vs 推测 vs marketing 叙事
- 信息矛盾时如实呈现两面
- 无法验证时明确说「未找到可靠证据」

**禁止：**
- 无来源断言
- marketing 风格描述
- 模糊表达（"据说"、"有人认为"而不追查是谁说的）
- 在弱证据上给出强结论
- 用推测填补信息空白
- 对不确定的事情表现得很确定
- 引用 SEO 内容农场而不标注"""

MAX_TOOL_ROUNDS = 15


# ── Researcher 类 ──────────────────────────────────────────

class Researcher:
    """DeepSeek 驱动的联网研究助手，支持多轮对话和工具调用。"""

    def __init__(
        self,
        provider: str = "deepseek",
        system_prompt: str = "",
        model_override: Optional[str] = None,
    ):
        self.provider = provider
        self.client, self._default_model = self._init_client(provider)
        self.model = model_override or self._default_model
        self._system = system_prompt or SYSTEM_PROMPT
        self.messages: list[dict] = [{"role": "system", "content": self._system}]

    @staticmethod
    def _init_client(provider: str):
        timeout = float(os.environ.get("LLM_REQUEST_TIMEOUT", "120"))
        p = provider.strip().lower()

        if p == "deepseek":
            base = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
            key = os.environ.get("DEEPSEEK_API_KEY", "")
            model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
            return OpenAI(base_url=base.rstrip("/") + "/v1", api_key=key, timeout=timeout), model

        env_prefix = p.upper()
        base = os.environ.get(f"{env_prefix}_BASE_URL", "")
        key = os.environ.get(f"{env_prefix}_API_KEY", "")
        model = os.environ.get(f"{env_prefix}_MODEL", "")
        if not all([base, key, model]):
            raise ValueError(
                f"Provider '{provider}' 需要设置环境变量: "
                f"{env_prefix}_BASE_URL, {env_prefix}_API_KEY, {env_prefix}_MODEL"
            )
        return OpenAI(base_url=base.rstrip("/"), api_key=key, timeout=timeout), model

    def _execute_tool(self, name: str, args: dict) -> str:
        fn = TOOL_MAP.get(name)
        if not fn:
            return json.dumps({"error": f"Unknown tool: {name}"}, ensure_ascii=False)
        try:
            result = fn(**args)
            if isinstance(result, (list, dict)):
                return json.dumps(result, ensure_ascii=False, indent=2)
            return str(result)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def research(self, query: str, verbose: bool = True) -> str:
        """
        对一个问题进行深度研究，返回 fact-checked 分析报告。

        工作流程：
          1. DeepSeek 分析问题，自主决定搜索策略
          2. 多轮搜索：官方来源、独立分析、数据、批评观点
          3. 深入阅读关键一手来源
          4. 综合分析，输出结构化报告（含 fact-check 标记）

        支持多轮对话：连续调用 research() 可以追问。

        Args:
            query: 用户的研究问题
            verbose: 是否在终端打印搜索过程
        """
        self.messages.append({"role": "user", "content": query})

        for _round in range(MAX_TOOL_ROUNDS):
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=self.messages,
                tools=TOOLS,
                temperature=0.1,
            )

            choice = resp.choices[0]
            msg = choice.message

            if not msg.tool_calls:
                answer = msg.content or ""
                self.messages.append({"role": "assistant", "content": answer})
                return answer

            if verbose and msg.content:
                print(f"  💭 {msg.content[:100]}...")

            self.messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ],
            })

            for tc in msg.tool_calls:
                fn_name = tc.function.name
                try:
                    fn_args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    fn_args = {}

                if verbose:
                    icon = TOOL_ICONS.get(fn_name, "🔧")
                    label = fn_args.get("query") or fn_args.get("url", "")
                    print(f"  {icon} {fn_name}: {label}")

                result_text = self._execute_tool(fn_name, fn_args)
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_text,
                })

        self.messages.append({
            "role": "user",
            "content": (
                "搜索轮次已达上限。请根据已收集到的所有信息，"
                "严格按照输出结构（一句话结论 → 关键发现 → 深度分析 → 盲区 → 核心启发）"
                "给出最终分析报告。先判断问题类型再选择分析框架。"
                "禁止重复、禁止废话、精简语言。"
            ),
        })
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=self.messages,
            temperature=0.1,
        )
        answer = resp.choices[0].message.content or ""
        self.messages.append({"role": "assistant", "content": answer})
        return answer

    def reset(self):
        """重置对话历史，开始新话题。"""
        self.messages = [{"role": "system", "content": self._system}]


# ── 便捷函数 ────────────────────────────────────────────────

def research_once(query: str, provider: str = "deepseek", verbose: bool = True) -> str:
    """一次性研究：提问 → 搜索 → 回答，不保留上下文。"""
    r = Researcher(provider=provider)
    return r.research(query, verbose=verbose)
