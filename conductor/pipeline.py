# -*- coding: utf-8 -*-
"""
Pipeline 编排引擎 — 串联六个阶段完成内容全流程。

两种运行模式：
  快速模式（默认）：LLM 直接产出创意 → 生成内容 → 存储
  深度模式：调用 brainstorm 脑暴 → content_factory 调用 creative prompt 机器人生成给火山的需求 → 生成内容 → 存储

Pipeline 支持：
  - 全流程一键执行
  - 单阶段执行（如只扫描热点、只生成内容）
  - 中途暂停等待人工审批后恢复
  - 定时发布调度
"""
from __future__ import annotations

import time
import traceback
from typing import Callable, Optional

from conductor.config import (
    TaskConfig, SafetyConfig, Stage, Platform,
    load_safety_config, log,
)
from conductor.models import PipelineRun, ContentDraft
from conductor.store import ContentItem, ContentStatus, store
from conductor.stages.trend_scanner import scan_trends
from conductor.stages.idea_engine import generate_ideas, generate_ideas_deep, select_best_idea
from conductor.stages.content_factory import create_content, review_quality
from conductor.stages.publisher import publish_draft
from conductor.stages.engager import check_and_reply
from conductor.stages.reviewer import generate_review


class Pipeline:
    """内容全流程编排器。"""

    def __init__(
        self,
        task: TaskConfig,
        safety: Optional[SafetyConfig] = None,
        on_stage_complete: Optional[Callable[[PipelineRun, Stage], None]] = None,
        on_approval_needed: Optional[Callable[[PipelineRun], None]] = None,
    ):
        self.task = task
        self.safety = safety or load_safety_config()
        self.on_stage_complete = on_stage_complete
        self.on_approval_needed = on_approval_needed
        self.run = PipelineRun()

    def execute(
        self,
        start_from: Stage = Stage.SCAN,
        stop_before: Optional[Stage] = None,
        deep_mode: bool = False,
    ) -> PipelineRun:
        """
        执行 Pipeline。

        Args:
            start_from: 从哪个阶段开始
            stop_before: 在哪个阶段前停下
            deep_mode: True=脑暴后由 creative prompt 生成火山需求
        """
        stages = [
            (Stage.SCAN, self._do_scan),
            (Stage.IDEATE, lambda: self._do_ideate(deep_mode)),
            (Stage.CREATE, self._do_create),
            (Stage.PUBLISH, self._do_publish),
            (Stage.ENGAGE, self._do_engage),
            (Stage.REVIEW, self._do_review),
        ]

        started = False
        for stage, handler in stages:
            if stage == start_from:
                started = True
            if not started:
                continue
            if stop_before and stage == stop_before:
                log.info("Pipeline 在 %s 前停止", stage.value)
                break

            self.run.current_stage = stage
            log.info("══════ 阶段: %s ══════", stage.value.upper())

            try:
                should_continue = handler()
                self.run.save()
                if self.on_stage_complete:
                    self.on_stage_complete(self.run, stage)
                if not should_continue:
                    log.info("Pipeline 在 %s 后暂停", stage.value)
                    self.run.status = "paused"
                    self.run.save()
                    return self.run
            except Exception as e:
                log.error("阶段 %s 失败: %s\n%s", stage.value, e, traceback.format_exc())
                self.run.error = f"[{stage.value}] {e}"
                self.run.status = "failed"
                self.run.finished_at = time.time()
                self.run.save()
                return self.run

        self.run.status = "completed"
        self.run.finished_at = time.time()
        self.run.save()
        log.info("Pipeline 完成 (%.1fs)", self.run.elapsed_sec())
        return self.run

    def _do_scan(self) -> bool:
        platforms = [p.value for p in self.task.target_platforms]
        self.run.trends = scan_trends(platforms, topic_hint=self.task.topic)
        log.info("扫描到 %d 条趋势", len(self.run.trends))
        return True

    def _do_ideate(self, deep_mode: bool = False) -> bool:
        if deep_mode:
            ideas, bs_path, plan_path = generate_ideas_deep(
                topic=self.task.topic,
                brand=self.task.brand,
                context="",
                persona=self.task.persona,
                target_audience=self.task.target_audience,
                content_goals=self.task.content_goals,
            )
            self.run.ideas = ideas
            log.info("深度模式完成: brainstorm=%s，火山需求由 content_factory 调用 creative prompt 生成", bs_path)
        else:
            self.run.ideas = generate_ideas(
                trends=self.run.trends,
                topic=self.task.topic,
                brand=self.task.brand,
                content_type=self.task.content_type,
                target_platforms=[p.value for p in self.task.target_platforms],
                persona=self.task.persona,
                target_audience=self.task.target_audience,
                content_goals=self.task.content_goals,
            )

        if not self.run.ideas:
            self.run.error = "未产出任何创意"
            return False

        self.run.selected_idea = select_best_idea(self.run.ideas)
        log.info("选中创意: %s (吸引力: %.2f)", self.run.selected_idea.title, self.run.selected_idea.estimated_appeal)
        return True

    def _do_create(self) -> bool:
        if not self.run.selected_idea:
            self.run.error = "没有选中的创意"
            return False

        self.run.draft = create_content(
            idea=self.run.selected_idea,
            brand=self.task.brand,
            target_platforms=[p.value for p in self.task.target_platforms],
            persona=self.task.persona,
            target_audience=self.task.target_audience,
            content_goals=self.task.content_goals,
        )
        self.run.draft = review_quality(self.run.draft)
        log.info("内容质量分: %.2f", self.run.draft.quality_score)

        if self.run.draft.quality_score < self.safety.min_quality_score:
            log.warning("质量分低于阈值: %.2f < %.2f", self.run.draft.quality_score, self.safety.min_quality_score)

        _save_draft_to_store(self.run)

        if self.safety.require_human_approval:
            log.info("需要人工审批，Pipeline 暂停")
            if self.on_approval_needed:
                self.on_approval_needed(self.run)
            return False

        return True

    def _do_publish(self) -> bool:
        if not self.run.draft:
            self.run.error = "没有可发布的内容"
            return False

        for platform in self.task.target_platforms:
            result = publish_draft(
                self.run.draft, platform,
                run_id=self.run.run_id,
                brainstorm_session=getattr(self.task, "brainstorm_session", ""),
            )
            self.run.publish_results.append(result)
            if result.success:
                log.info("存储成功: %s → %s", platform.value, result.post_id)
            else:
                log.warning("存储失败: %s → %s", platform.value, result.error)

        return any(r.success for r in self.run.publish_results)

    def _do_engage(self) -> bool:
        for result in self.run.publish_results:
            if not result.success:
                continue
            actions = check_and_reply(
                platform=result.platform,
                post_id=result.post_id,
                brand=self.task.brand,
                max_replies=self.task.max_comments_per_post,
            )
            self.run.engage_actions.extend(actions)
        return True

    def _do_review(self) -> bool:
        for result in self.run.publish_results:
            if not result.success:
                continue
            review = generate_review(
                platform=result.platform,
                post_id=result.post_id,
                brand=self.task.brand,
            )
            if review:
                self.run.review = review
        return True


def _save_draft_to_store(run: PipelineRun) -> str:
    """将 Pipeline 产出的草稿存入内容仓库。"""
    if not run.draft:
        return ""
    draft = run.draft
    item = ContentItem(
        title=draft.idea.title,
        topic=draft.idea.title,
        content_type=draft.idea.content_type,
        platform_copy=draft.platform_copy,
        hashtags=draft.hashtags,
        visual_prompt=draft.visual_prompt,
        visual_prompt_en=draft.visual_prompt_en,
        generated_assets=getattr(draft, "generated_assets", []),
        idea_title=draft.idea.title,
        idea_angle=draft.idea.angle,
        idea_hook=draft.idea.hook,
        quality_score=draft.quality_score,
        quality_feedback=draft.quality_feedback,
        status=ContentStatus.DRAFT,
        run_id=run.run_id,
    )
    return store.save(item)


# ── 便捷函数 ──────────────────────────────────────────────────

def run_pipeline(
    topic: str,
    brand: str = "",
    platforms: Optional[list[str]] = None,
    content_type: str = "short_video",
    deep_mode: bool = False,
    auto_publish: bool = False,
    persona: str = "",
    target_audience: str = "",
    content_goals: str = "",
    on_stage_complete: Optional[Callable] = None,
    on_approval_needed: Optional[Callable] = None,
) -> PipelineRun:
    """
    一键执行内容生产 Pipeline。

    Args:
        topic: 主题
        brand: 品牌（留空则不指定，由人设等决定）
        platforms: 目标平台列表（如 ["xiaohongshu", "douyin"]）
        content_type: 内容形式
        deep_mode: 是否走脑暴后由 creative prompt 生成火山需求的深度模式
        auto_publish: 是否自动发布（否则生成草稿等待审批）
        persona: 发帖人设（口吻、风格）
        target_audience: 目标受众描述
        content_goals: 内容目标（涨粉/种草/品牌等）
    """
    plat_list = []
    for p in (platforms or ["xiaohongshu"]):
        parsed = Platform.from_str(p)
        if parsed:
            plat_list.append(parsed)

    task = TaskConfig(
        topic=topic,
        brand=brand,
        target_platforms=plat_list or [Platform.XIAOHONGSHU],
        content_type=content_type,
        auto_publish=auto_publish,
        persona=persona,
        target_audience=target_audience,
        content_goals=content_goals,
    )

    stop_before = Stage.PUBLISH if not auto_publish else None

    pipeline = Pipeline(
        task=task,
        on_stage_complete=on_stage_complete,
        on_approval_needed=on_approval_needed,
    )
    return pipeline.execute(deep_mode=deep_mode, stop_before=stop_before)


def run_quick(topic: str, brand: str = "", platforms: Optional[list[str]] = None) -> PipelineRun:
    """快速模式：扫热点 → LLM 产创意 → 生成内容 → 存草稿。"""
    return run_pipeline(topic=topic, brand=brand, platforms=platforms, deep_mode=False)


def run_deep(topic: str, brand: str = "", platforms: Optional[list[str]] = None) -> PipelineRun:
    """深度模式：扫热点 → brainstorm 脑暴 → creative prompt 生成给火山的需求 → 生成内容 → 存草稿。"""
    return run_pipeline(topic=topic, brand=brand, platforms=platforms, deep_mode=True)
