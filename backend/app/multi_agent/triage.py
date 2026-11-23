"""Intent extraction only; no business tools or authorization decisions."""

import re
from typing import Protocol

from pydantic import ValidationError

from app.llm import ModelProvider
from app.multi_agent.models import Intent, TriageResult

ORDER_ID = re.compile(
    r"(?:订单|order(?=\s|#|:|[0-9]))(?:编号|号|\s*id)?[\s:：]*([#]?[A-Za-z0-9_-]+)",
    re.I,
)
PRODUCT_ID = re.compile(
    r"(?:商品|产品|product)(?:编号|号|\s*id)?[\s:：]*([#]?[A-Za-z0-9_-]+)", re.I
)
BARE_ID = re.compile(r"#?[A-Za-z0-9_-]+")
ORDER_INTENTS = {"order_query", "cancel_order", "modify_order", "return_order", "exchange_order"}
NON_IDS = {"status", "cancel", "return", "exchange", "modify", "details", "information", "policy"}
ORDER_NOT_WANTED = re.compile(
    r"(?:订单|这单|那单).{0,8}(?:不要了|不想要了|不需要了|不再需要了?)"
    r"|(?:不要了|不想要了|不需要了|不再需要了?).{0,8}(?:订单|这单|那单)"
    r"|(?:不要|不想要|不需要)(?:这个|这笔|这张|那个)?订单了?"
)


class TriageError(Exception):
    """Sanitized classification failure."""


class TriageProvider(Protocol):
    def classify(self, message: str, previous: TriageResult | None = None) -> TriageResult: ...


def _mentioned(identifier: str, message: str) -> bool:
    return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(identifier)}(?![A-Za-z0-9])", message))


def _check_ids(result: TriageResult, message: str, previous: TriageResult | None) -> None:
    for field in ("order_id", "product_id"):
        value = getattr(result, field)
        if value is None:
            continue
        old = getattr(previous, field) if previous and previous.needs_clarification else None
        if not _mentioned(value, message) and value != old:
            raise ValueError("unmentioned_identifier")
        pattern = ORDER_ID if field == "order_id" else PRODUCT_ID
        explicit = _ids(pattern, message)
        if explicit and value not in explicit:
            raise ValueError("identifier_conflict")


def _ids(pattern: re.Pattern[str], message: str) -> list[str]:
    return list(
        dict.fromkeys(
            match.group(1)
            for match in pattern.finditer(message)
            if match.group(1).casefold() not in NON_IDS
        )
    )


def mentioned_order_ids(message: str) -> list[str]:
    """Return explicit order identifiers; never inferred from conversation history."""
    return _ids(ORDER_ID, message)


def _required_information(result: TriageResult) -> TriageResult:
    missing = [
        item
        for item in result.missing_information
        if not (item == "order_id" and result.requested_action == "list_orders")
    ]
    if (
        any(intent in ORDER_INTENTS for intent in result.intents)
        and not result.order_id
        and result.requested_action != "list_orders"
    ):
        if "order_id" not in missing:
            missing.append("order_id")
    if "product_inquiry" in result.intents and not result.product_id:
        if "product_id" not in missing:
            missing.append("product_id")
    return result.model_copy(
        update={"missing_information": missing, "needs_clarification": bool(missing)}
    )


def _action_mentioned(message: str, chinese: str, english: str) -> bool:
    return bool(
        re.search(rf"{re.escape(chinese)}(?!政策|规则)", message)
        or re.search(rf"\b{english}\b(?!\s+(?:policy|rules))", message, re.I)
    )


class MockTriage:
    """Deterministic, deliberately narrow parser for offline development."""

    def classify(self, message: str, previous: TriageResult | None = None) -> TriageResult:
        phrase = message.strip()
        lowered = phrase.casefold()
        order_ids = _ids(ORDER_ID, phrase)
        product_ids = _ids(PRODUCT_ID, phrase)
        order_id = order_ids[0] if len(order_ids) == 1 else None
        product_id = product_ids[0] if len(product_ids) == 1 else None
        if previous and previous.needs_clarification:
            order_id = order_id or previous.order_id
            product_id = product_id or previous.product_id
        if previous and previous.needs_clarification and BARE_ID.fullmatch(phrase):
            if "order_id" in previous.missing_information:
                order_id = phrase
            elif "product_id" in previous.missing_information:
                product_id = phrase

        merchant_knowledge_question = "订单" not in phrase and "order" not in lowered and any(
            word in lowered
            for word in (
                "发什么快递",
                "哪个快递",
                "快递公司",
                "从哪里发货",
                "哪里发货",
                "发货地点",
                "发货仓",
                "仓库发货",
                "shipping carrier",
                "ship from",
            )
        )
        policy_question = merchant_knowledge_question or any(
            word in lowered
            for word in (
                "政策",
                "规则",
                "条件",
                "要求",
                "能不能",
                "可不可以",
                "怎么规定",
                "怎么办",
                "怎么退",
                "怎么取消",
                "需要什么",
                "支持哪些支付",
                "支付方式",
                "退款多久",
                "售后流程",
                "policy",
                "rule",
                "eligible",
                "requirement",
            )
        )
        execution_request = any(
            word in lowered
            for word in (
                "申请取消",
                "帮我取消",
                "我要取消",
                "申请退货",
                "帮我退货",
                "我要退货",
                "申请换货",
                "帮我换货",
                "我要换货",
                "帮我修改",
                "我要修改",
                "please cancel",
                "please return",
                "please exchange",
                "i want to cancel",
                "i want to return",
                "i want to exchange",
            )
        )

        intents: list[Intent] = []
        if _action_mentioned(phrase, "退货", "return") and not (
            policy_question and not execution_request
        ):
            intents.append("return_order")
        if _action_mentioned(phrase, "换货", "exchange") and not (
            policy_question and not execution_request
        ):
            intents.append("exchange_order")
        colloquial_cancel = bool(ORDER_NOT_WANTED.search(phrase)) and not (
            policy_question or phrase.endswith(("吗", "？", "?"))
        )
        if colloquial_cancel or (
            _action_mentioned(phrase, "取消", "cancel")
            and not (policy_question and not execution_request)
        ):
            intents.append("cancel_order")
        if (
            any(word in lowered for word in ("修改", "更改", "change", "modify"))
            and ("订单" in phrase or "order" in lowered)
            and not (policy_question and not execution_request)
        ):
            intents.append("modify_order")
        if policy_question:
            intents.append("policy_inquiry")
        product_question = any(
            word in lowered
            for word in (
                "商品信息",
                "商品详情",
                "产品信息",
                "产品详情",
                "product",
            )
        ) or (
            bool(product_id)
            and any(
                word in lowered
                for word in ("价格", "多少钱", "库存", "有货", "规格", "可选", "参数")
            )
        )
        if product_question:
            intents.append("product_inquiry")
        if order_id or ("订单" in phrase or "order" in lowered):
            if any(
                word in lowered
                for word in (
                    "查询",
                    "查",
                    "看看",
                    "状态",
                    "详情",
                    "列表",
                    "所有订单",
                    "我的订单",
                    "订单中的商品",
                    "中的商品",
                    "物流",
                    "配送",
                    "tracking",
                    "items",
                    "list",
                    "my orders",
                    "status",
                    "where",
                    "show",
                    "check",
                )
            ):
                intents.insert(0, "order_query")
        if not intents and previous and previous.needs_clarification:
            intents = [intent for intent in previous.intents if intent != "unknown"]
        if not intents:
            intents = ["unknown"]
        intents = list(dict.fromkeys(intents))
        missing: list[str] = []
        list_orders = "order_query" in intents and any(
            word in lowered
            for word in ("订单列表", "所有订单", "我的订单", "list orders", "my orders")
        )
        if len(order_ids) > 1:
            missing.append("order_assignment")
        if len(product_ids) > 1:
            missing.append("product_assignment")
        if any(intent in ORDER_INTENTS for intent in intents) and not order_id and not list_orders:
            order_id = previous.order_id if previous and previous.needs_clarification else None
            if not order_id:
                missing.append("order_id")
        if "product_inquiry" in intents and not product_id:
            product_id = previous.product_id if previous else None
            if not product_id:
                missing.append("product_id")
        action = next(
            (intent for intent in intents if intent in ORDER_INTENTS - {"order_query"}), None
        )
        if action is None and "product_inquiry" in intents and "order_query" not in intents:
            action = "get_product_details"
        if action is None and "order_query" in intents:
            if list_orders:
                action = "list_orders"
            elif (
                previous
                and previous.needs_clarification
                and BARE_ID.fullmatch(phrase)
                and previous.requested_action
                in {
                    "get_order_details",
                    "get_order_status",
                    "get_order_items",
                    "get_order_logistics",
                }
            ):
                action = previous.requested_action
            elif any(word in lowered for word in ("物流", "配送", "tracking")):
                action = "get_order_logistics"
            elif any(word in lowered for word in ("订单中的商品", "中的商品", "items")):
                action = "get_order_items"
            elif any(word in lowered for word in ("状态", "status")):
                action = "get_order_status"
            else:
                action = "get_order_details"
        extracted = (
            dict(previous.extracted_parameters) if previous and previous.needs_clarification else {}
        )
        reason_match = re.search(r"(?:because|因为)\s*([^,，。]{1,80})", phrase, re.I)
        if reason_match:
            extracted["reason"] = reason_match.group(1).strip()
        elif any(word in lowered for word in ("ordered by mistake", "买错了", "下错单", "误下单")):
            extracted["reason"] = "ordered by mistake"
        elif colloquial_cancel or any(
            word in lowered
            for word in (
                "no longer needed",
                "不要了",
                "不用了",
                "不需要了",
                "不想要了",
                "不再需要",
                "不在需要",  # 常见输入错误；只在明确取消上下文中用作原因。
            )
        ):
            extracted["reason"] = "no longer needed"
        for key in ("item_ids", "new_item_ids", "payment_method_id"):
            match = re.search(rf"\b{key}\s*[:=]\s*([#A-Za-z0-9_,-]+)", phrase, re.I)
            if match:
                extracted[key] = match.group(1)
        quantities = re.search(
            r"\bitem_quantities\s*=\s*([#A-Za-z0-9_-]+:\d+(?:,[#A-Za-z0-9_-]+:\d+)*)",
            phrase,
            re.I,
        )
        if quantities:
            extracted["item_quantities"] = quantities.group(1)
        if any(word in lowered for word in ("地址", "address")):
            extracted["modification_type"] = "address"
        elif any(word in lowered for word in ("支付", "payment")):
            extracted["modification_type"] = "payment"
        elif (
            any(word in lowered for word in ("商品", "选项", "item", "variant"))
            and "modify_order" in intents
        ):
            extracted["modification_type"] = "items"
        for key in ("address1", "address2", "city", "state", "country", "zip"):
            match = re.search(rf"\b{key}\s*=\s*([^,，;；]+)", phrase, re.I)
            if match:
                extracted[key] = match.group(1).strip()
        result = TriageResult(
            intent="complex_request" if len(intents) > 1 else intents[0],
            intents=intents,
            order_id=order_id,
            product_id=product_id,
            requested_action=action,
            extracted_parameters=extracted,
            missing_information=missing,
            needs_clarification=bool(missing),
            confidence=0.8 if intents != ["unknown"] else 0.0,
            reasoning_summary="Matched explicit request terms; no business eligibility checked.",
        )
        _check_ids(result, phrase, previous)
        return result


class LLMTriage:
    """Reuse the existing Chat Completions Provider with validated JSON output."""

    def __init__(self, provider: ModelProvider, *, max_attempts: int = 2) -> None:
        if max_attempts < 1 or max_attempts > 3:
            raise ValueError("invalid_attempt_limit")
        self.provider = provider
        self.max_attempts = max_attempts

    def classify(self, message: str, previous: TriageResult | None = None) -> TriageResult:
        system = (
            "Classify the customer's latest request. Return one JSON object matching these keys: "
            "intent, intents, order_id, product_id, requested_action, extracted_parameters, "
            "missing_information, needs_clarification, confidence, reasoning_summary. "
            "Allowed intents: product_inquiry, order_query, cancel_order, modify_order, "
            "return_order, exchange_order, policy_inquiry, complex_request, unknown. "
            "For multiple requests set intent=complex_request and list each actual intent "
            "in intents. "
            "For an order list request set requested_action=list_orders and order_id=null. "
            "Do not invent identifiers. Preserve a leading # in any order ID exactly. "
            "Understand colloquial Chinese, including 撤单、下错单、后悔买了、不要这单了 "
            "as possible cancel requests. "
            "A question about how cancellation or returns work is policy_inquiry, "
            "not a request to execute. "
            "For cancel_order set requested_action=cancel_order. "
            "When the customer clearly gives a reason, "
            "map a mistaken purchase to reason='ordered by mistake' and no longer wanting it to "
            "reason='no longer needed'. Otherwise omit reason; never invent one. "
            "Confidence is an uncalibrated reference. "
            "Give a short classification reason, not private reasoning. "
            "Do not claim any task executed."
        )
        context = (
            f"Previous intent={previous.intent}; previous order_id={previous.order_id}; "
            f"missing={previous.missing_information}"
            if previous and previous.needs_clarification
            else "No pending clarification."
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "system", "content": context},
            {"role": "user", "content": message},
        ]
        last_error = "structured_output_invalid"
        for attempt in range(self.max_attempts):
            if attempt:
                messages.append(
                    {"role": "system", "content": "Previous output invalid. Return valid JSON."}
                )
            try:
                reply = self.provider.complete(messages, [])
            except Exception as exc:
                last_error = "provider_unavailable"
                if attempt + 1 == self.max_attempts:
                    raise TriageError(last_error) from exc
                continue
            try:
                if reply.tool_calls or not reply.content:
                    raise ValueError("invalid_model_reply")
                result = TriageResult.model_validate_json(reply.content)
                _check_ids(result, message, previous)
                return _required_information(result)
            except (ValidationError, ValueError):
                last_error = "structured_output_invalid"
        raise TriageError(last_error)


class HybridTriage:
    """Use the model for unclear language; keep the offline parser as a safe fallback."""

    def __init__(self, provider: ModelProvider) -> None:
        self.rules = MockTriage()
        self.model = LLMTriage(provider, max_attempts=1)

    def classify(self, message: str, previous: TriageResult | None = None) -> TriageResult:
        rule = self.rules.classify(message, previous)
        if rule.intents != ["unknown"] and not (
            rule.intents == ["cancel_order"]
            and "reason" not in rule.extracted_parameters
        ):
            return rule
        try:
            model = self.model.classify(message, previous)
        except TriageError:
            return rule
        if model.intents == ["unknown"] or model.confidence < 0.6:
            return rule
        if rule.intents != ["unknown"] and model.intents != rule.intents:
            return rule
        if model.intents == ["cancel_order"]:
            reason = model.extracted_parameters.get("reason")
            if reason not in {"ordered by mistake", "no longer needed"}:
                model.extracted_parameters.pop("reason", None)
            model = model.model_copy(update={"requested_action": "cancel_order"})
        return model


class ThreadScopedTriage:
    """Bind a server-resolved order thread without trusting message text."""

    def __init__(self, provider: TriageProvider, order_id: str) -> None:
        if not order_id.strip():
            raise ValueError("thread_order_id_invalid")
        self.provider = provider
        self.order_id = order_id

    def classify(self, message: str, previous: TriageResult | None = None) -> TriageResult:
        result = self.provider.classify(message, previous)
        if result.order_id is None and result.requested_action != "list_orders":
            missing = [
                item for item in result.missing_information if item != "order_id"
            ]
            result = result.model_copy(
                update={
                    "order_id": self.order_id,
                    "missing_information": missing,
                    "needs_clarification": bool(missing),
                }
            )
        return result
