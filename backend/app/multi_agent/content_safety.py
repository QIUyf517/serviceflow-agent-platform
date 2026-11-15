"""Deterministic pre-routing safety checks for the customer support channel.

This is deliberately narrow: a word such as ``kill`` or ``杀`` is not itself a
violation.  A block requires a contextual phrase that asks for harmful conduct.
The checker does not decide business intent, identity, eligibility, or tool access.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

SafetyCategory = Literal[
    "allowed",
    "credible_threat",
    "harmful_instruction",
    "sexual_exploitation",
    "credential_theft",
    "self_harm_instruction",
]


class SafetyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    allowed: bool
    category: SafetyCategory
    reason_code: str | None = None


_RULES: tuple[tuple[SafetyCategory, re.Pattern[str]], ...] = (
    (
        "credible_threat",
        re.compile(
            r"(?:我要|我会|我准备|我现在就).{0,10}"
            r"(?:杀了|弄死|伤害|袭击|下毒)(?:他|她|他们|她们|客服|店员|快递员|那个人|人)?"
            r"|\b(?:i(?:'m| am) going to|i will)\s+(?:kill|poison|attack|hurt)\s+"
            r"(?:him|her|them|the agent|the courier|someone)\b",
            re.I,
        ),
    ),
    (
        "harmful_instruction",
        re.compile(
            r"(?:教我|告诉我|怎么|如何|帮我).{0,12}"
            r"(?:下毒|制作炸弹|伤害他人|杀死他人)"
            r"|\bhow (?:do i|to) (?:poison|build a bomb|hurt|kill)\b",
            re.I,
        ),
    ),
    (
        "sexual_exploitation",
        re.compile(
            r"(?:未成年|儿童|小孩).{0,10}(?:色情|裸照|性行为|性内容)"
            r"|(?:色情|裸照|性内容).{0,10}(?:未成年|儿童|小孩)"
            r"|\b(?:child|minor).{0,20}(?:sexual|nude|porn)\b",
            re.I,
        ),
    ),
    (
        "credential_theft",
        re.compile(
            r"(?:教我|帮我|怎么|如何).{0,12}"
            r"(?:盗取|偷取|套取).{0,8}(?:密码|验证码|银行卡|账号)"
            r"|\bhow (?:do i|to) (?:steal|phish).{0,20}(?:password|account|card)\b",
            re.I,
        ),
    ),
    (
        "self_harm_instruction",
        re.compile(
            r"(?:教我|告诉我|怎么|如何).{0,10}(?:自杀|自残|伤害自己)"
            r"|\bhow (?:do i|to) (?:kill|hurt) myself\b",
            re.I,
        ),
    ),
)


class ContentSafetyChecker:
    """Run before intent routing; never calls a model or external service."""

    def check(self, message: str) -> SafetyDecision:
        phrase = message.strip()
        for category, pattern in _RULES:
            if pattern.search(phrase):
                return SafetyDecision(
                    allowed=False,
                    category=category,
                    reason_code=f"content_{category}",
                )
        return SafetyDecision(allowed=True, category="allowed")


def blocked_message(category: SafetyCategory) -> str:
    if category == "self_harm_instruction":
        return (
            "这段内容涉及伤害自己的具体做法，我不能协助。"
            "如果你或他人正处于现实危险中，请立即联系当地紧急服务或可信赖的人。"
        )
    if category == "credible_threat":
        return (
            "这段内容包含对他人的现实伤害威胁，我不能继续处理。"
            "如果有人正处于危险中，请立即联系当地紧急服务。"
        )
    return (
        "这段内容涉及可能造成伤害或违法获取信息的具体请求，我不能协助。"
        "你可以继续咨询商品、订单或售后问题。"
    )
