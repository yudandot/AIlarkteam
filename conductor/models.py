# -*- coding: utf-8 -*-
"""
数据模型 — Pipeline 各阶段的输入/输出结构。
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from conductor.config import Platform, Stage, DATA_DIR


@dataclass
class TrendItem:
    """一条热点/趋势。"""
    platform: str
    title: str
    heat: str = ""
    url: str = ""
    timestamp: float = 0.0


@dataclass
class ContentIdea:
    """一个内容创意。"""
    title: str
    angle: str                              # 切入角度
    hook: str = ""                          # 开头钩子
    target_platform: str = ""
    content_type: str = "short_video"
    estimated_appeal: float = 0.0           # AI 预估吸引力 0-1
    reasoning: str = ""
    idea_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


@dataclass
class ContentDraft:
    """一份内容草稿。"""
    idea: ContentIdea
    text_content: str = ""                  # 文案
    visual_prompt: str = ""                 # 视觉素材 prompt
    visual_prompt_en: str = ""              # Seedance 英文版
    hashtags: list[str] = field(default_factory=list)
    platform_copy: dict[str, str] = field(default_factory=dict)  # 各平台适配文案
    generated_assets: list[str] = field(default_factory=list)  # 生成的图片/视频 URL 或本地路径
    quality_score: float = 0.0             # AI 自评分数
    quality_feedback: str = ""


@dataclass
class PublishResult:
    """一次发布的结果。"""
    platform: Platform
    success: bool = False
    post_url: str = ""
    post_id: str = ""
    error: str = ""
    published_at: float = 0.0


@dataclass
class EngageAction:
    """一次互动动作。"""
    platform: Platform
    post_id: str
    comment_id: str = ""
    comment_text: str = ""                  # 原评论
    reply_text: str = ""                    # 回复
    action_type: str = "reply"              # reply / like
    success: bool = False
    timestamp: float = 0.0


@dataclass
class ReviewReport:
    """一次复盘报告。"""
    post_id: str
    platform: Platform
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    sentiment_positive: float = 0.0
    sentiment_negative: float = 0.0
    top_comments: list[str] = field(default_factory=list)
    ai_summary: str = ""
    improvement_suggestions: list[str] = field(default_factory=list)


# ── Pipeline Run（一次完整执行的记录）──────────────────────────

@dataclass
class PipelineRun:
    """一次完整 Pipeline 执行的记录。"""
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    current_stage: Stage = Stage.SCAN
    status: str = "running"                 # running / paused / completed / failed

    trends: list[TrendItem] = field(default_factory=list)
    ideas: list[ContentIdea] = field(default_factory=list)
    selected_idea: Optional[ContentIdea] = None
    draft: Optional[ContentDraft] = None
    publish_results: list[PublishResult] = field(default_factory=list)
    engage_actions: list[EngageAction] = field(default_factory=list)
    review: Optional[ReviewReport] = None

    error: str = ""
    human_feedback: str = ""                # 人工审批意见

    def elapsed_sec(self) -> float:
        end = self.finished_at or time.time()
        return end - self.started_at

    def save(self) -> Path:
        """保存到 JSON 文件。"""
        path = DATA_DIR / f"run_{self.run_id}.json"
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return path

    @classmethod
    def load(cls, run_id: str) -> Optional["PipelineRun"]:
        path = DATA_DIR / f"run_{run_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            run = cls(run_id=data.get("run_id", run_id))
            for k, v in data.items():
                if hasattr(run, k) and k != "run_id":
                    setattr(run, k, v)
            return run
        except Exception:
            return None
