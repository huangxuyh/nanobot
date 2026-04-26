"""CAE request guardrail."""

from __future__ import annotations

import json
import re
from typing import Any

from loguru import logger

from nanobot.agent.guardrails.models import CAEFilterDecision
from nanobot.agent.guardrails.prompts import build_cae_filter_messages
from nanobot.config.schema import CAEGuardrailConfig
from nanobot.providers.base import LLMProvider
from nanobot.workflow import WorkflowRecord

_ALLOW_KEYWORDS = (
    "cae",
    "cad",
    "mesh",
    "physics",
    "preprocess",
    "postprocess",
    "网格",
    "物理场",
    "前处理",
    "后处理",
    "边界条件",
    "载荷",
    "应力",
    "位移",
    "求解",
    "悬臂梁",
    "有限元",
    "fea",
    "ansys",
    "abaqus",
    "fluent",
    "step",
    "iges",
    "stl",
    "cae-master-flow-test",
    "cae-cad-stage-test",
    "cae-mesh-stage-test",
    "cae-physics-stage-test",
    "cae-preprocess-stage-test",
    "cae-postprocess-stage-test",
)

_DENY_KEYWORDS = (
    "政治",
    "共产党",
    "选举",
    "主席",
    "总统",
    "政府",
    "台独",
    "疆独",
    "法轮功",
    "六四",
    "民主运动",
    "terrorist",
    "terrorism",
    "terror",
    "bomb",
    "movie",
    "电影",
    "音乐",
    "股票",
    "币圈",
    "情书",
    "约会",
    "星座",
    "八卦",
    "porn",
    "sex",
    "成人视频",
    "色情",
    "自慰",
)

_ALLOW_SHORT_REPLY = re.compile(r"^[A-Za-z0-9_\-./ ]{1,64}$")
_NAME_VALUE_REPLY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\s*:\s*.+")


class CAERequestFilter:
    """Domain guardrail for CAE-only deployments."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        model: str,
        config: CAEGuardrailConfig,
    ) -> None:
        self.provider = provider
        self.model = model
        self.config = config

    async def evaluate(
        self,
        *,
        text: str,
        workflow: WorkflowRecord | None = None,
        is_command: bool = False,
        is_system: bool = False,
    ) -> CAEFilterDecision:
        if not self.config.enable:
            return CAEFilterDecision(
                action="allow",
                reason="guardrail disabled",
                classifier="disabled",
                category="disabled",
            )

        if is_system and self.config.allow_system_messages:
            return CAEFilterDecision(
                action="allow",
                reason="system message bypass",
                classifier="bypass",
                category="system",
            )

        if is_command and self.config.allow_commands:
            return CAEFilterDecision(
                action="allow",
                reason="command bypass",
                classifier="bypass",
                category="command",
            )

        normalized = (text or "").strip()
        if not normalized:
            return CAEFilterDecision(
                action="deny",
                reason="empty message outside CAE scope",
                classifier="fallback",
                category="empty",
            )

        deny_hits = self._keyword_hits(normalized, _DENY_KEYWORDS)
        if deny_hits and self.config.mode != "llm_only":
            return CAEFilterDecision(
                action="deny",
                reason="blocked keywords matched",
                classifier="rule",
                category="blocked_keyword",
                matched_terms=deny_hits,
            )

        if self._is_workflow_reply(normalized, workflow):
            return CAEFilterDecision(
                action="allow",
                reason="workflow reply pattern matched",
                classifier="rule",
                category="workflow_reply",
            )

        allow_hits = self._keyword_hits(normalized, _ALLOW_KEYWORDS)
        if allow_hits and self.config.mode != "llm_only":
            return CAEFilterDecision(
                action="allow",
                reason="CAE keywords matched",
                classifier="rule",
                category="cae_keyword",
                matched_terms=allow_hits,
            )

        if self.config.mode == "rule_only":
            return CAEFilterDecision(
                action="deny",
                reason="rule_only mode denied uncertain request",
                classifier="fallback",
                category="uncertain",
            )

        return await self._evaluate_with_llm(normalized, workflow)

    def _keyword_hits(self, text: str, keywords: tuple[str, ...]) -> list[str]:
        lowered = text.lower()
        hits: list[str] = []
        for kw in keywords:
            if kw.lower() in lowered:
                hits.append(kw)
        return hits

    def _is_workflow_reply(self, text: str, workflow: WorkflowRecord | None) -> bool:
        if workflow is None:
            return False

        state = str(getattr(workflow, "state", "") or "")
        if state not in {"awaiting_user_input", "awaiting_approval", "resuming", "running"}:
            return False

        awaiting = workflow.awaiting or {}
        fields = awaiting.get("fields") if isinstance(awaiting, dict) else None
        if isinstance(fields, list):
            field_names = [
                str(item.get("name"))
                for item in fields
                if isinstance(item, dict) and item.get("name")
            ]
            if field_names and any(name in text for name in field_names):
                return True

        if isinstance(awaiting, dict) and awaiting.get("kind") == "approval":
            if text.strip().lower() in {"yes", "no", "approve", "reject", "同意", "拒绝"}:
                return True

        if _NAME_VALUE_REPLY.search(text):
            return True

        if workflow.current_stage and _ALLOW_SHORT_REPLY.fullmatch(text):
            return True

        return False

    async def _evaluate_with_llm(
        self,
        text: str,
        workflow: WorkflowRecord | None,
    ) -> CAEFilterDecision:
        workflow_context = {
            "workflow_id": getattr(workflow, "workflow_id", None),
            "workflow_state": getattr(workflow, "state", None),
            "workflow_stage": getattr(workflow, "current_stage", None),
            "awaiting": workflow.awaiting if workflow else None,
        }
        messages = build_cae_filter_messages(text, workflow_context=workflow_context)
        try:
            response = await self.provider.chat_with_retry(
                messages=messages,
                tools=None,
                model=self.config.classifier_model or self.model,
                max_tokens=self.config.classifier_max_tokens,
                temperature=0,
                tool_choice=None,
            )
        except Exception as exc:
            logger.warning("CAE guardrail classifier failed: {}", exc)
            return CAEFilterDecision(
                action="deny",
                reason="classifier call failed",
                classifier="fallback",
                category="classifier_error",
            )

        payload = self._parse_classifier_json(response.content or "")
        if not isinstance(payload, dict):
            return CAEFilterDecision(
                action="deny",
                reason="classifier returned invalid payload",
                classifier="fallback",
                category="invalid_classifier_payload",
            )

        action = str(payload.get("action") or "").strip().lower()
        if action not in {"allow", "deny"}:
            return CAEFilterDecision(
                action="deny",
                reason="classifier returned unknown action",
                classifier="fallback",
                category="invalid_classifier_action",
            )

        confidence = payload.get("confidence")
        try:
            confidence_value = float(confidence) if confidence is not None else None
        except (TypeError, ValueError):
            confidence_value = None

        return CAEFilterDecision(
            action=action,
            reason=f"classifier returned {action}",
            classifier="llm",
            category=str(payload.get("category") or ""),
            confidence=confidence_value,
        )

    def _parse_classifier_json(self, content: str) -> dict[str, Any] | None:
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            pass

        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
