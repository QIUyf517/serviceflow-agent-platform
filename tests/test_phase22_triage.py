import json

import pytest
from app.llm import ModelReply, ProviderError
from app.multi_agent.models import TriageResult
from app.multi_agent.triage import LLMTriage, MockTriage, TriageError


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


def test_llm_provider_error_is_sanitized():
    class BrokenProvider:
        def complete(self, messages, tools):
            raise ProviderError("private transport details")

    with pytest.raises(TriageError, match="provider_unavailable") as exc:
        LLMTriage(BrokenProvider()).classify("查询订单123")
    assert "private transport details" not in str(exc.value)
