# -*- coding: utf-8 -*-
"""
脑暴机器人 —— 飞书长连接入口。
==============================

这是什么？
  在飞书上给这个机器人发消息，就能启动一场 AI 多角色脑暴。
  5 个 AI 角色（坚果五仁团队）会像真人一样轮流发言讨论你的主题，
  讨论过程实时推送到飞书群，最终产出可落地的创意方案。

运行方式：
  python3 -m brainstorm

需要的环境变量：
  BRAINSTORM_FEISHU_APP_ID / BRAINSTORM_FEISHU_APP_SECRET（推荐，避免与指挥等共用 .env 时用错）
  或 FEISHU_APP_ID / FEISHU_APP_SECRET  飞书应用的 App ID / Secret
  DEEPSEEK_API_KEY   DeepSeek 的 API Key（必须）
  DOUBAO_API_KEY     豆包的 API Key（脑暴必须）
  KIMI_API_KEY       Kimi 的 API Key（脑暴必须）
  FEISHU_WEBHOOK     飞书群 Webhook URL（讨论过程推送到群）

消息格式：
  直接发消息内容即为脑暴主题，例如：
    咖啡品牌 × 音乐节跨界联动
  或带前缀：
    脑暴：给男人卖胸罩
  多行消息第一行为主题，其余为背景材料。
  发送「帮助」查看使用说明。

整体流程（小白版）：
  用户发消息 → 解析主题 → DeepSeek 优化主题 → 5个角色4轮讨论
  → 每轮实时推送飞书群 → Kimi 生成最终交付 → 通知用户完成
"""
import json
import os
import random
import sys
import threading
import time
import traceback
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import lark_oapi as lark
from lark_oapi import EventDispatcherHandler, LogLevel

from collections import OrderedDict

from core.feishu_client import reply_message, reply_card, send_message_to_user, send_card_to_user
from core.cards import welcome_card, progress_card, result_card, error_card, help_card
from core.llm import chat_completion
from brainstorm.run import run_brainstorm
from core.utils import load_context

_VERIFY_TOKEN = os.environ.get("FEISHU_VERIFICATION_TOKEN", "")
_ENCRYPT_KEY = os.environ.get("FEISHU_ENCRYPT_KEY", "")

# ── 日志 ─────────────────────────────────────────────────────

_log_lock = threading.Lock()
_bot_log_path: Optional[str] = None


def _log(msg: str) -> None:
    line = f"[BrainstormBot] {msg}"
    print(line, file=sys.stderr, flush=True)
    global _bot_log_path
    with _log_lock:
        if _bot_log_path is None:
            _bot_log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bot_brainstorm.log")
        try:
            with open(_bot_log_path, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
        except Exception:
            pass


# ── 消息解析 ─────────────────────────────────────────────────
# 用户发来的消息可能带有「脑暴：」等前缀，需要去掉前缀提取真正的主题。

_TOPIC_PREFIXES = ("脑暴 ", "脑暴：", "脑暴:", "brainstorm ", "brainstorm:", "brainstorm：")

_MODE_PREFIXES = {
    "营销：": "campaign", "营销:": "campaign", "活动：": "campaign", "活动:": "campaign",
    "项目：": "project", "项目:": "project", "产品：": "project", "产品:": "project",
    "策略：": "strategy", "策略:": "strategy", "探讨：": "strategy", "探讨:": "strategy",
    "探索：": "explore", "探索:": "explore", "生活：": "explore", "生活:": "explore",
}

# 不当作脑暴主题的废话/打招呼：命中则回欢迎卡片，不启动脑暴
_NOT_TOPIC_PHRASES = frozenset({
    "在吗", "在么", "你好", "嗨", "哈喽", "hi", "hello", "hey",
    "哈哈", "呵呵", "啊啊", "嗯", "哦", "好的", "好", "行", "1", "2", "测试", "试试",
    "？", "?", "？？", "。。", "啥", "怎么", "为什么", "啥意思",
    "开始", "start", "go", "来", "在", "喂", "呀", "呢", "吗",
})
_MIN_TOPIC_LEN = 3  # 主题至少几个字符才当作有效（过滤单字、双字废话）

def _welcome() -> dict:
    return welcome_card(
        "脑暴机器人",
        "什么话题都可以脑暴。直接发消息，系统自动识别类型。\n"
        "也可以用前缀指定模式：营销：/ 项目：/ 策略：/ 探索：\n\n"
        "**脑暴流程：** DeepSeek 优化主题 → 坚果五仁四轮讨论 → 最终交付",
        examples=[
            "帮哆啦A梦造势 它一定能赢过奥特曼",
            "策略：用户增长靠补贴还是靠产品本身？",
            "设计一个让猫主动帮你干活的智能家居",
        ],
        hints=["自动识别：营销/项目/策略探讨/生活", "可用前缀强制指定模式", "多行消息：第一行主题，其余背景", "发「帮助」查看说明"],
    )


def _help() -> dict:
    return help_card("脑暴机器人", [
        ("使用方式", "直接发消息，内容即为脑暴主题。\n可加「脑暴：」前缀，也可以不加。"),
        ("四种模式",
         "系统自动识别，也可以用前缀强制指定：\n\n"
         "**营销：** 品牌联动、线下活动、内容策略\n"
         "→ 侧重体验设计、传播节奏、视觉概念\n\n"
         "**项目：** 产品设计、游戏设计、side project\n"
         "→ 侧重用户体验、技术可行性、MVP 定义\n\n"
         "**策略：** 开放式战略问题、价值判断、方向选择\n"
         "→ 侧重观点碰撞、洞察深度、决策框架\n\n"
         "**探索：** 生活决策、职业规划、个人目标\n"
         "→ 侧重可执行性、个人契合度、行动方案"),
        ("指定模式示例",
         "> 策略：用户增长靠补贴还是靠产品本身？\n"
         "> 营销：帮哆啦A梦造势 它一定能赢过奥特曼\n"
         "> 项目：设计一个让猫主动帮你干活的智能家居\n\n"
         "不加前缀也可以，系统会自动判断"),
        ("脑暴后追问",
         "脑暴结束后可以继续追问，比如：\n"
         "> 方向1能展开讲讲吗？\n"
         "> 这几个方向哪个最容易落地？\n"
         "> 帮我想想执行计划\n\n"
         "发「**新主题**」开始新一轮脑暴\n"
         "发「**退出**」结束追问"),
        ("多行消息", "第一行 = 主题\n其余行 = 背景材料"),
    ], footer="脑暴过程约 3-5 分钟，完成后可继续追问深入")


def _extract_text(content: str) -> str:
    """从飞书消息体中提取纯文本。飞书传来的 content 是 JSON 字符串，如 '{"text":"你好"}'。"""
    if not content or not content.strip():
        return ""
    try:
        data = json.loads(content)
        if isinstance(data, dict) and "text" in data:
            return (data["text"] or "").strip()
        return content.strip()
    except (json.JSONDecodeError, TypeError):
        return content.strip()


def _parse_brainstorm_input(text: str) -> tuple[str, str, str]:
    """
    从用户消息中解析出 (主题, 背景材料, 模式)。

    规则：第一行为主题，后续行为背景材料。
    支持去掉「脑暴：」等前缀。
    支持模式前缀如「策略：」「营销：」等，返回对应 topic_type。
    废话/打招呼/过短内容不当作主题，返回 ("", "", "") 以触发欢迎卡片。
    """
    t = (text or "").strip()
    for prefix in _TOPIC_PREFIXES:
        if t.lower().startswith(prefix):
            t = t[len(prefix):].strip()
            break
    forced_mode = ""
    for prefix, mode in _MODE_PREFIXES.items():
        if t.startswith(prefix):
            forced_mode = mode
            t = t[len(prefix):].strip()
            break
    lines = t.split("\n", 1)
    topic = lines[0].strip()
    context = lines[1].strip() if len(lines) > 1 else ""
    if context.startswith("---"):
        context = context[3:].strip()
    if not topic or len(topic) < _MIN_TOPIC_LEN:
        return "", "", ""
    lower_topic = topic.lower().strip()
    if lower_topic in _NOT_TOPIC_PHRASES:
        return "", "", ""
    return topic, context, forced_mode


# ── 会话状态管理 ─────────────────────────────────────────────
# 每个用户维护独立会话：保存脑暴结果，支持 follow-up 追问。

_MAX_SESSIONS = 200
_sessions: OrderedDict[str, dict] = OrderedDict()
_sessions_lock = threading.Lock()


def _get_session(user_key: str) -> dict:
    with _sessions_lock:
        if user_key in _sessions:
            _sessions.move_to_end(user_key)
            return _sessions[user_key]
        session = {
            "mode": "idle",                 # idle | brainstorming | followup
            "topic": "",                    # 脑暴主题
            "topic_refined": "",            # 优化后的主题
            "round_summaries": [],          # 各轮摘要
            "final_output": "",             # 最终交付内容
            "session_path": "",             # session 文件路径
            "followup_history": [],         # follow-up 对话历史
        }
        _sessions[user_key] = session
        while len(_sessions) > _MAX_SESSIONS:
            _sessions.popitem(last=False)
        return session


def _update_session(user_key: str, **kwargs) -> None:
    with _sessions_lock:
        if user_key in _sessions:
            _sessions[user_key].update(kwargs)


# ── 运行中追踪 ───────────────────────────────────────────────

_running_sessions: dict[str, str] = {}
_running_lock = threading.Lock()


# ── Follow-up 追问 ───────────────────────────────────────────

_FOLLOWUP_SYSTEM = """你是脑暴追问助手。你刚和用户完成了一场多角色 AI 脑暴讨论，现在用户想就脑暴结果继续深入。

你的角色：
- 你熟悉整场脑暴的所有讨论内容和最终交付
- 用户可能想：深入某个方向、追问细节、请你帮忙展开某个创意、对比方向、思考落地方案等
- 像一个资深创意顾问回答追问，具体、有洞察、不废话
- 如果用户问到脑暴中没讨论到的东西，基于已有上下文合理延伸

沟通风格：
- 简洁专业，每次回复 3-8 句话
- 具体 > 模糊，给可操作的建议
- 可以主动提出"你可能还想知道…"引导深入
"""

_MAX_FOLLOWUP_HISTORY = 20

_NEW_TOPIC_TRIGGERS = frozenset({
    "新主题", "换个主题", "新脑暴", "再来一个", "重新开始",
    "new topic", "new brainstorm",
})

_EXIT_FOLLOWUP_TRIGGERS = frozenset({
    "退出", "结束", "退出追问", "结束追问", "不问了", "算了",
})


def _do_followup(user_key: str, user_input: str) -> str:
    """基于脑暴结果的 follow-up 对话。"""
    session = _get_session(user_key)

    history = list(session.get("followup_history", []))
    history.append({"role": "user", "content": user_input})
    if len(history) > _MAX_FOLLOWUP_HISTORY:
        history = history[-_MAX_FOLLOWUP_HISTORY:]

    brainstorm_context = _build_followup_context(session)
    system = _FOLLOWUP_SYSTEM + "\n\n" + brainstorm_context

    messages = [{"role": "system", "content": system}] + history

    result = chat_completion(
        provider="deepseek",
        messages=messages,
        temperature=0.7,
    )

    history.append({"role": "assistant", "content": result})
    _update_session(user_key, followup_history=history)
    return result


def _build_followup_context(session: dict) -> str:
    """从 session 中提取脑暴结果作为 follow-up 上下文。"""
    parts = []
    topic = session.get("topic_refined", "") or session.get("topic", "")
    if topic:
        parts.append(f"━━ 脑暴主题 ━━\n{topic[:500]}")

    summaries = session.get("round_summaries", [])
    if summaries:
        parts.append("━━ 各轮讨论摘要 ━━")
        for i, s in enumerate(summaries, 1):
            parts.append(f"第{i}轮：\n{s[:800]}")

    final = session.get("final_output", "")
    if final:
        parts.append(f"━━ 最终交付 ━━\n{final[:3000]}")

    return "\n\n".join(parts) if parts else "（暂无脑暴上下文）"


def _final_delivery_card(final_output: str) -> dict:
    """把最终交付内容作为卡片发到 1-on-1 聊天，用户可以直接看到结果。"""
    truncated = final_output[:4000]
    if len(final_output) > 4000:
        truncated += "\n\n…（内容过长已截断，完整版请查看飞书群）"
    elements = []
    elements.append({
        "tag": "markdown",
        "content": truncated,
    })
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": "脑暴最终交付", "tag": "plain_text"},
            "template": "green",
        },
        "elements": elements,
    }


def _done_card_with_followup(topic: str, path: str) -> dict:
    """脑暴完成卡片：引导用户进入 follow-up 追问 + 跨 Bot 联动。"""
    short_topic = topic[:60]
    return result_card(
        "脑暴完成",
        fields=[("主题", topic[:100]), ("会话文件", f"`{path}`")],
        next_actions=[
            "直接发消息追问脑暴结果",
            "「深入方向1」展开某个方向",
            "「新主题」开始新脑暴",
            "去飞书群看完整讨论",
            "━━ 用这个结果继续 ━━",
            f"去「自媒体助手」发「脑暴：{short_topic}」→ 生成内容",
            f"去「规划」发「{short_topic}」→ 细化成可执行计划",
            f"去「助理bot」发「备忘 跟进脑暴结论 #项目名」→ 记录待办",
        ],
    )


def _followup_card(content: str) -> dict:
    """follow-up 追问回复卡片。"""
    elements = []
    elements.append({
        "tag": "markdown",
        "content": content,
    })
    elements.append({"tag": "hr"})
    elements.append({
        "tag": "note",
        "elements": [{
            "tag": "plain_text",
            "content": "追问中  ·  继续提问  ·  发「新主题」开始新脑暴  ·  发「退出」结束追问",
        }],
    })
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": "脑暴追问", "tag": "plain_text"},
            "template": "turquoise",
        },
        "elements": elements,
    }


# ── 消息处理 ─────────────────────────────────────────────────

def _handle_message(data: lark.im.v1.P2ImMessageReceiveV1) -> None:
    _log("收到消息事件")
    try:
        if not data.event or not data.event.message:
            _log("事件或消息体为空，忽略")
            return
        msg = data.event.message
        message_id = msg.message_id
        user_text = _extract_text(msg.content or "{}")
        open_id = None
        if data.event.sender and data.event.sender.sender_id:
            open_id = getattr(data.event.sender.sender_id, "open_id", None)
        _log(f"message_id={message_id!r} open_id={open_id!r} 文本={user_text[:80]!r}")
        if not user_text:
            threading.Thread(
                target=lambda: reply_card(message_id, _welcome()),
                daemon=True,
            ).start()
            return
    except Exception as e:
        _log(f"解析消息异常: {e}\n{traceback.format_exc()}")
        return

    def _process(mid: str, text: str, uid: Optional[str]):
        try:
            lower = text.strip().lower().rstrip("!！~")
            user_key = uid or mid
            session = _get_session(user_key)
            current_mode = session.get("mode", "idle")

            if lower in ("帮助", "help", "?", "？"):
                reply_card(mid, _help())
                return

            # ── follow-up 模式：退出追问
            if current_mode == "followup" and lower in _EXIT_FOLLOWUP_TRIGGERS:
                _update_session(user_key, mode="idle", followup_history=[])
                reply_card(mid, progress_card(
                    "已退出追问",
                    "追问已结束。发新主题可以再来一轮脑暴。",
                    color="blue",
                ))
                return

            # ── follow-up 模式：开始新脑暴
            if current_mode == "followup" and lower in _NEW_TOPIC_TRIGGERS:
                _update_session(user_key, mode="idle", followup_history=[],
                    topic="", round_summaries=[], final_output="", session_path="")
                reply_card(mid, _welcome())
                return

            # ── follow-up 模式：追问对话
            if current_mode == "followup":
                # 如果用户发了一个新的有效脑暴主题（较长文本，非追问口吻），也当新脑暴处理
                # 但大部分情况下 follow-up 模式下的消息都是追问
                with _running_lock:
                    if _running_sessions.get(user_key):
                        reply_message(mid, "上一个请求还在处理中，请稍等...")
                        return
                    _running_sessions[user_key] = "followup"
                try:
                    _log(f"follow-up 追问: user={user_key[:20]} text={text[:60]!r}")
                    result = _do_followup(user_key, text)
                    card = _followup_card(result)
                    reply_card(mid, card)
                except Exception as e:
                    _log(f"follow-up 异常: {e}\n{traceback.format_exc()}")
                    reply_message(mid, "追问出错，请稍后重试")
                finally:
                    with _running_lock:
                        _running_sessions.pop(user_key, None)
                return

            # ── 正在脑暴中
            if current_mode == "brainstorming":
                with _running_lock:
                    if user_key in _running_sessions:
                        reply_card(mid, progress_card(
                            "脑暴进行中",
                            f"当前主题：**{_running_sessions[user_key][:40]}**\n\n请等脑暴结束后再操作。",
                            color="orange",
                        ))
                        return

            # ── idle 模式：解析主题
            topic, context, forced_mode = _parse_brainstorm_input(text)
            if not topic:
                reply_card(mid, _welcome())
                return

            with _running_lock:
                if user_key in _running_sessions:
                    reply_card(mid, progress_card(
                        "脑暴进行中",
                        f"当前主题：**{_running_sessions[user_key][:40]}**\n\n请等当前脑暴结束后再发起新的。",
                        color="orange",
                    ))
                    return
                _running_sessions[user_key] = topic

            _update_session(user_key, mode="brainstorming", topic=topic,
                round_summaries=[], final_output="", followup_history=[])

            reply_card(mid, progress_card(
                "正在启动脑暴",
                f"**主题：**{topic[:200]}\n\n讨论过程将实时推送到飞书群，完成后我会通知你。",
            ))
            _log(f"启动脑暴: topic={topic[:80]!r}")
            try:
                brainstorm_webhook = (
                    os.environ.get("BRAINSTORM_FEISHU_WEBHOOK") or os.environ.get("FEISHU_WEBHOOK") or ""
                ).strip() or None
                bs_result = run_brainstorm(topic=topic, context=context, webhook=brainstorm_webhook, topic_type=forced_mode)

                final_output = getattr(bs_result, "final_output", "")
                _update_session(user_key,
                    mode="followup",
                    topic_refined=getattr(bs_result, "topic_refined", ""),
                    round_summaries=getattr(bs_result, "round_summaries", []),
                    final_output=final_output,
                    session_path=str(bs_result),
                )

                # 把最终交付内容发到 1-on-1，用户直接在这里看结果、追问
                if final_output:
                    delivery_card = _final_delivery_card(final_output)
                    if uid:
                        send_card_to_user(uid, delivery_card)
                    else:
                        reply_card(mid, delivery_card)

                done_card = _done_card_with_followup(topic, str(bs_result))
                if uid:
                    send_card_to_user(uid, done_card)
                else:
                    reply_card(mid, done_card)
                try:
                    from core.events import emit as _emit_event
                    _emit_event("brainstorm", "session_completed",
                                f"脑暴完成: {topic[:50]}",
                                user_id=uid or "",
                                meta={"topic": topic[:100], "path": str(bs_result)})
                except Exception:
                    pass
                _log(f"脑暴完成: {bs_result}")
            except Exception as e:
                _log(f"脑暴异常: {e}\n{traceback.format_exc()}")
                _update_session(user_key, mode="idle")
                err = error_card("脑暴执行出错", "内部错误，请稍后重试", suggestions=["重新发送主题再试一次"])
                if uid:
                    send_card_to_user(uid, err)
                else:
                    reply_card(mid, err)
            finally:
                with _running_lock:
                    _running_sessions.pop(user_key, None)
        except Exception as e:
            _log(f"处理异常: {e}\n{traceback.format_exc()}")
            try:
                reply_card(mid, error_card("处理出错", "内部错误，请稍后重试", suggestions=["重新发送试试"]))
            except Exception:
                pass

    threading.Thread(target=_process, args=(message_id, user_text, open_id), daemon=True).start()


def _handle_bot_p2p_chat_entered(data) -> None:
    _log("用户打开了与机器人的单聊")
    try:
        open_id = None
        if hasattr(data, "event") and data.event:
            ev = data.event
            for attr in ("operator_id", "operator", "user_id"):
                obj = getattr(ev, attr, None)
                if obj:
                    open_id = getattr(obj, "open_id", None)
                    if open_id:
                        break
        if open_id:
            send_card_to_user(open_id, _welcome())
        else:
            _log("无法获取 open_id，跳过欢迎卡片")
    except Exception as e:
        _log(f"发送欢迎卡片异常: {e}\n{traceback.format_exc()}")


def _handle_message_read(_data) -> None:
    pass


# ── 长连接 ───────────────────────────────────────────────────
# 飞书长连接（WebSocket）会保持和飞书服务器的持久连接，实时接收消息。
# 如果连接断开（网络波动等），会自动重连，重连间隔从 5 秒开始指数增长，
# 最长 300 秒（5分钟）。加入随机抖动(jitter)避免多个实例同时重连。

RECONNECT_INITIAL_DELAY = 5       # 首次重连等待 5 秒
RECONNECT_MAX_DELAY = 300         # 最长等待 300 秒
RECONNECT_MULTIPLIER = 2          # 每次翻倍


def _run_client(app_id: str, app_secret: str) -> None:
    event_handler = (
        EventDispatcherHandler.builder(_VERIFY_TOKEN, _ENCRYPT_KEY)
        .register_p2_im_message_receive_v1(_handle_message)
        .register_p2_im_chat_access_event_bot_p2p_chat_entered_v1(_handle_bot_p2p_chat_entered)
        .register_p2_im_message_message_read_v1(_handle_message_read)
        .build()
    )
    cli = lark.ws.Client(app_id, app_secret, event_handler=event_handler, log_level=LogLevel.DEBUG, domain="https://open.feishu.cn")
    cli.start()


def main():
    # 优先用脑暴专用变量，避免与指挥/其他 bot 共用 FEISHU_APP_ID 时用错 token、发错欢迎卡片
    app_id = (
        os.environ.get("BRAINSTORM_FEISHU_APP_ID")
        or os.environ.get("FEISHU_APP_ID")
        or ""
    ).strip()
    app_secret = (
        os.environ.get("BRAINSTORM_FEISHU_APP_SECRET")
        or os.environ.get("FEISHU_APP_SECRET")
        or ""
    ).strip()
    if not app_id or not app_secret:
        raise SystemExit(
            "请设置环境变量 BRAINSTORM_FEISHU_APP_ID / BRAINSTORM_FEISHU_APP_SECRET（或 FEISHU_APP_ID / FEISHU_APP_SECRET）"
        )
    # 让 core.feishu_client 的 get_tenant_access_token 使用脑暴的凭证发消息/卡片
    os.environ["FEISHU_APP_ID"] = app_id
    os.environ["FEISHU_APP_SECRET"] = app_secret

    _log("脑暴机器人启动")
    print("=" * 60)
    print("AIlarkteams 脑暴机器人（长连接模式）")
    print()
    print("使用方式：在飞书上给机器人发消息，内容即为脑暴主题。")
    print()
    print("飞书开放平台配置：")
    print("  1. 先保持本程序运行")
    print("  2. 事件订阅 → 选择「长连接」")
    print("  3. 订阅「接收消息 v2.0」(im.message.receive_v1)")
    print("  4. 保存")
    print()
    print("断线后将自动重连，无需人工干预。")
    print("=" * 60)

    delay = RECONNECT_INITIAL_DELAY
    attempt = 0
    while True:
        attempt += 1
        _log(f"正在连接飞书… (第 {attempt} 次)")
        try:
            _run_client(app_id, app_secret)
            _log("飞书长连接已断开，将自动重连")
        except Exception as e:
            _log(f"连接失败: {e}\n{traceback.format_exc()}")
            if attempt == 1:
                print("\n若持续失败，请检查：", file=sys.stderr)
                print("  1. BRAINSTORM_FEISHU_APP_ID / BRAINSTORM_FEISHU_APP_SECRET（或 FEISHU_APP_ID / SECRET）是否正确", file=sys.stderr)
                print("  2. 应用是否已发布并启用", file=sys.stderr)
                print("  3. 网络是否可访问 open.feishu.cn", file=sys.stderr)
        wait = min(delay, RECONNECT_MAX_DELAY)
        jitter = random.uniform(0, min(5, wait * 0.2))
        wait += jitter
        _log(f"{wait:.1f} 秒后重连…")
        time.sleep(wait)
        delay = min(delay * RECONNECT_MULTIPLIER, RECONNECT_MAX_DELAY)


if __name__ == "__main__":
    main()
