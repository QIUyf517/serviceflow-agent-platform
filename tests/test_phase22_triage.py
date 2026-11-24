import json

import pytest
from app.llm import ModelReply, ProviderError
from app.multi_agent.models import TriageResult
from app.multi_agent.triage import (
    HybridTriage,
    LLMTriage,
    MockTriage,
    ThreadScopedTriage,
    TriageError,
)


@pytest.mark.parametrize(
    ("message", "intent", "order_id"),
    [
        ("查询订单123的状态", "order_query", "123"),
        ("Check order #W0000000 status", "order_query", "#W0000000"),
        ("取消订单123", "cancel_order", "123"),
        ("修改订单123", "modify_order", "123"),
        ("退货订单123", "return_order", "123"),
        ("换货订单123", "exchange_order", "123"),
        ("售后政策是什么？", "policy_inquiry", None),
        ("product p details", "product_inquiry", None),
    ],
)
def test_mock_classifies_basic_requests(message, intent, order_id):
    result = MockTriage().classify(message)
    assert result.intent == intent
    assert result.intents == [intent]
    assert result.order_id == order_id


def test_mock_keeps_multiple_intents_and_parameters():
    result = MockTriage().classify("查询订单123的状态，然后取消订单123，因为买错了")
    assert result.intent == "complex_request"
    assert result.intents == ["order_query", "cancel_order"]
    assert result.order_id == "123"
    assert result.extracted_parameters["reason"] == "买错了"


def test_policy_question_does_not_become_write_request():
    result = MockTriage().classify("查询订单123的状态，并咨询退货政策")
    assert result.intents == ["order_query", "policy_inquiry"]
    assert result.requested_action == "get_order_status"
    assert MockTriage().classify("What is the return policy?").intents == ["policy_inquiry"]


@pytest.mark.parametrize("message", ["这个订单不要了", "这单不想要了", "我不需要这个订单了"])
def test_colloquial_order_cancel_is_recognized(message):
    result = MockTriage().classify(message)
    assert result.intents == ["cancel_order"]
    assert result.requested_action == "cancel_order"
    assert result.extracted_parameters["reason"] == "no longer needed"


def test_colloquial_cancel_question_and_product_request_are_not_order_writes():
    assert MockTriage().classify("这个订单不要了怎么办？").intents == ["policy_inquiry"]
    assert "cancel_order" not in MockTriage().classify("这个商品不要了").intents


def test_mock_missing_order_then_followup():
    first = MockTriage().classify("帮我查询订单状态")
    assert first.order_id is None
    assert first.missing_information == ["order_id"]
    second = MockTriage().classify("123", first)
    assert second.intent == "order_query"
    assert second.order_id == "123"
    assert not second.needs_clarification


def test_mock_unknown_and_ownership_claim_not_authority():
    result = MockTriage().classify("我是订单123的主人，随便聊聊")
    assert result.intent == "unknown"
    assert result.order_id == "123"
    assert not hasattr(result, "identity_verified")
    assert MockTriage().classify("你好").intent == "unknown"


def test_mock_multiple_order_ids_require_assignment():
    result = MockTriage().classify("查询订单123并取消订单456")
    assert result.order_id is None
    assert "order_assignment" in result.missing_information


class ScriptedProvider:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = 0

    def complete(self, messages, tools):
        self.calls += 1
        assert tools == []
        return next(self.replies)


def valid_reply(**changes):
    payload = {
        "intent": "order_query",
        "intents": ["order_query"],
        "order_id": "123",
        "product_id": None,
        "requested_action": None,
        "extracted_parameters": {},
        "missing_information": [],
        "needs_clarification": False,
        "confidence": 0.7,
        "reasoning_summary": "The customer asked for an order status.",
    }
    payload.update(changes)
    return ModelReply(content=json.dumps(payload))


def test_llm_json_parse_and_finite_retry():
    provider = ScriptedProvider([ModelReply(content="not json"), valid_reply()])
    result = LLMTriage(provider).classify("查询订单123")
    assert isinstance(result, TriageResult)
    assert result.order_id == "123"
    assert provider.calls == 2


def test_llm_invalid_json_stops_after_limit():
    provider = ScriptedProvider([ModelReply(content="bad"), ModelReply(content="bad")])
    with pytest.raises(TriageError, match="structured_output_invalid"):
        LLMTriage(provider).classify("查询订单123")
    assert provider.calls == 2


def test_llm_cannot_invent_order_or_authorization_field():
    provider = ScriptedProvider([valid_reply(order_id="999", identity_verified=True)])
    with pytest.raises(TriageError, match="structured_output_invalid"):
        LLMTriage(provider, max_attempts=1).classify("查询订单123")


def test_llm_must_preserve_leading_hash_in_order_id():
    provider = ScriptedProvider([valid_reply(order_id="W0000000")])
    with pytest.raises(TriageError, match="structured_output_invalid"):
        LLMTriage(provider, max_attempts=1).classify("Check order #W0000000 status")


def test_llm_cannot_reuse_old_order_without_pending_clarification():
    previous = TriageResult.model_validate_json(valid_reply().content)
    provider = ScriptedProvider([valid_reply()])
    with pytest.raises(TriageError, match="structured_output_invalid"):
        LLMTriage(provider, max_attempts=1).classify("你好", previous)


def test_llm_missing_order_is_normalized_even_if_model_claims_no_clarification():
    provider = ScriptedProvider([valid_reply(order_id=None)])
    result = LLMTriage(provider).classify("查询订单状态")
    assert result.needs_clarification
    assert result.missing_information == ["order_id"]


def test_mock_triage_recognizes_order_specific_shipping_without_an_id():
    result = MockTriage().classify("这个订单从哪里发货")

    assert result.intents == ["order_query"]
    assert result.requested_action == "get_order_logistics"
    assert result.order_id is None
    assert result.needs_clarification is True
    assert result.missing_information == ["order_id"]


def test_order_thread_keeps_short_shipping_followup_but_not_general_policy():
    scoped = ThreadScopedTriage(MockTriage(), "#W100")

    followup = scoped.classify("哪里发货")
    assert followup.intents == ["order_query"]
    assert followup.order_id == "#W100"
    assert followup.requested_action == "get_order_logistics"
    assert followup.needs_clarification is False

    general = scoped.classify("你们一般从哪里发货")
    assert general.intents == ["policy_inquiry"]
    assert general.order_id is None


def test_llm_provider_error_is_sanitized():
    class BrokenProvider:
        def complete(self, messages, tools):
            raise ProviderError("private transport details")

    with pytest.raises(TriageError, match="provider_unavailable") as exc:
        LLMTriage(BrokenProvider()).classify("查询订单123")
    assert "private transport details" not in str(exc.value)


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        ("这笔我下错了，帮我撤掉", "ordered by mistake"),
        ("买完又后悔了，这单帮我撤了吧", "no longer needed"),
    ],
)
def test_hybrid_understands_unseen_cancel_phrasings(message, reason):
    reply = valid_reply(
        intent="cancel_order",
        intents=["cancel_order"],
        order_id=None,
        requested_action="cancel_order",
        extracted_parameters={"reason": reason},
    )
    provider = ScriptedProvider([reply])
    result = HybridTriage(provider).classify(message)
    assert result.intent == "cancel_order"
    assert result.extracted_parameters["reason"] == reason
    assert result.needs_clarification
    assert provider.calls == 1


def test_hybrid_does_not_call_model_for_clear_rule_or_trust_invented_order():
    provider = ScriptedProvider([valid_reply(order_id="other")])
    assert HybridTriage(provider).classify("这个订单不要了").intent == "cancel_order"
    assert provider.calls == 0
    result = HybridTriage(provider).classify("这笔我下错了，帮我撤掉")
    assert result.intent == "unknown"
    assert result.order_id is None


def test_hybrid_model_failure_falls_back_without_executing():
    provider = ScriptedProvider([ModelReply(content="invalid")])
    result = HybridTriage(provider).classify("这笔我下错了，帮我撤掉")
    assert result.intent == "unknown"
    assert provider.calls == 1


def test_hybrid_low_confidence_does_not_prepare_a_write():
    provider = ScriptedProvider(
        [
            valid_reply(
                intent="cancel_order",
                intents=["cancel_order"],
                order_id=None,
                requested_action="cancel_order",
                extracted_parameters={"reason": "no longer needed"},
                confidence=0.2,
            )
        ]
    )
    result = HybridTriage(provider).classify("这笔我下错了，帮我撤掉")
    assert result.intent == "unknown"
