"""Prompt helpers for CAE request filtering."""

from __future__ import annotations

import json
from typing import Any


CAE_FILTER_SYSTEM_PROMPT = """你是一个 CAE 领域请求分类器。

你的任务不是回答用户，而是判断这条消息是否允许进入 CAE agent 主流程。

允许的范围只有：
1. CAE 相关问答
2. CAE 相关脚本生成
3. CAE 相关流程执行
4. 当前 workflow 的 HITL 参数回复

必须拒绝的范围包括：
1. 政治
2. 敏感公共议题
3. 与 CAE 无关的通用问答
4. 与 CAE 无关的代码、工具、执行请求

你必须只输出 JSON，不要输出任何解释。

输出格式必须是：
{"action":"allow|deny","category":"...","confidence":0.0}
"""


def build_cae_filter_messages(
    text: str,
    *,
    workflow_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build classification messages for the CAE request guardrail."""

    payload = {
        "user_message": text,
        "workflow_context": workflow_context or {},
    }
    return [
        {"role": "system", "content": CAE_FILTER_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
