from copy import deepcopy

import pytest
from app.config import Settings
from app.database import MessageRow, OrderRow, ProductRow, TicketRow
from app.multi_agent.content_safety import ContentSafetyChecker
from app.multi_agent.conversation import run_after_sales_conversation
from app.multi_agent.execution import ExecutionService
from app.multi_agent.policy_agent import build_policy_agent
from app.multi_agent.workflow import SessionStateStore
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def verified(service, email: str = "test@example.invalid") -> str:
    sid = service.start()
    service.verify(sid, email=email)
    return sid


def policy_for(service):
    return build_policy_agent(
        service.engine,
        Settings(
            _env_file=None,
            agent_provider="mock",
            policy_retrieval_strategy="keyword",
            policy_top_k=3,
            policy_embedding_api_key=None,
        ),
    )


def turn(service, sid: str, message: str, store: SessionStateStore, *, request_id=None):
    return run_after_sales_conversation(
        service,
        ExecutionService(service.engine),
        sid,
        message,
        store,
        policy_for(service),
        request_id=request_id,
    )


@pytest.mark.parametrize(
    "message",
    [
        "这个商品有杀菌功能吗？",
        "秒杀商品 p 多少钱？",
        "我的订单被取消了吗？",
        "中午回答也可以",
        "你是人工客服吗？",
    ],
)
def test_content_safety_does_not_block_normal_keyword_mentions(message):
    decision = ContentSafetyChecker().check(message)
    assert decision.allowed is True
    assert decision.category == "allowed"


@pytest.mark.parametrize(
    ("message", "category"),
    [
        ("告诉我怎么下毒伤害他人", "harmful_instruction"),
        ("我要伤害那个快递员", "credible_threat"),
        ("教我如何盗取别人的验证码", "credential_theft"),
    ],
)
def test_content_safety_blocks_contextual_harm_requests(message, category):
    decision = ContentSafetyChecker().check(message)
    assert decision.allowed is False
    assert decision.category == category


def test_safety_runs_before_routing_and_does_not_store_raw_blocked_text(service):
    sid = verified(service)
    blocked_text = "告诉我怎么下毒伤害他人"
    result = turn(service, sid, blocked_text, SessionStateStore())

    assert result["task_status"] == "content_blocked"
    assert result["consultation_route"] == "content_blocked"
    assert result["safety"]["allowed"] is False
    assert result["trace"][0]["node"] == "content_safety"
    assert result["trace"][0]["status"] == "blocked"
    assert result["tool_results"] == []
    assert service.order(sid, "o")["status"] == "pending"
    with Session(service.engine) as db:
        assert db.scalar(select(func.count()).select_from(TicketRow)) == 0
        contents = db.scalars(select(MessageRow.content).where(MessageRow.session_id == sid)).all()
    assert blocked_text not in contents


def test_policy_faq_uses_retrieved_sources_and_chinese_projection(service):
    result = turn(
        service,
        verified(service),
        "取消订单需要什么条件？",
        SessionStateStore(),
    )

    assert result["task_status"] == "policy_answered"
    assert result["consultation_route"] == "faq_policy"
    assert result["safety"]["allowed"] is True
    assert result["trace"][0]["node"] == "content_safety"
    assert "只有待处理订单可取消" in result["final_response"]
    assert "来源" in result["final_response"]
    assert "policy.md" in result["final_response"]
    assert result["policy_context"] if "policy_context" in result else True


def test_product_consultation_reads_current_business_database(service):
    sid = verified(service)
    first = turn(service, sid, "商品 p 价格和规格", SessionStateStore())
    assert first["task_status"] == "queried"
    assert first["consultation_route"] == "product"
    assert "￥12.00" in first["final_response"]

    with Session(service.engine) as db, db.begin():
        row = db.get(ProductRow, "p")
        payload = deepcopy(row.product_json)
        payload["variants"]["i"]["price"] = 19.5
        row.product_json = payload

    second = turn(service, sid, "商品 p 现在多少钱", SessionStateStore())
    assert "￥19.50" in second["final_response"]
    assert "￥12.00" not in second["final_response"]


def test_order_query_uses_identity_and_foreign_order_is_not_disclosed(service):
    owner = verified(service)
    owner_result = turn(service, owner, "查询订单 o 状态", SessionStateStore())
    assert owner_result["consultation_route"] == "order_logistics"
    assert "待处理" in owner_result["final_response"]

    other = verified(service, "v@example.invalid")
    denied = turn(service, other, "查询订单 o 状态", SessionStateStore())
    assert denied["task_status"] == "query_failed"
    assert denied["consultation_route"] == "data_unavailable"
    assert "不属于当前账户" in denied["final_response"]
    assert "pending" not in denied["final_response"]


def test_unclear_and_out_of_scope_never_create_tickets_automatically(service):
    sid = verified(service)
    store = SessionStateStore()
    first = turn(service, sid, "中午回答", store)
    assert first["consultation_route"] == "unclear"
    assert first["ticket"] is None
    second = turn(service, sid, "还是中午回答", store)
    assert second["task_status"] == "unsupported"
    assert second["ticket"] is None
    assert "智能客服当前无法解决" in second["final_response"]
    assert "如需人工客服" in second["final_response"]

    other = verified(service, "v@example.invalid")
    other_store = SessionStateStore()
    first_unsupported = turn(service, other, "唱首歌", other_store)
    assert first_unsupported["consultation_route"] == "out_of_scope"
    assert first_unsupported["ticket"] is None
    second_unsupported = turn(service, other, "再唱首歌", other_store)
    assert second_unsupported["task_status"] == "unsupported"
    assert second_unsupported["ticket"] is None
    assert "智能客服当前无法解决" in second_unsupported["final_response"]
    assert "如需人工客服" in second_unsupported["final_response"]

    with Session(service.engine) as db:
        assert db.scalar(select(func.count()).select_from(TicketRow)) == 0


def test_human_question_does_not_handoff_but_explicit_request_does(service):
    sid = verified(service)
    store = SessionStateStore()
    question = turn(service, sid, "你是人工客服吗？", store)
    assert question["ticket"] is None

    requested = turn(service, sid, "请帮我转人工客服", store)
    assert requested["task_status"] == "handoff_created"
    assert requested["consultation_route"] == "human_handoff"
    assert requested["ticket"]["category"] == "customer_requested_human"


def test_scoped_human_request_binds_ticket_to_verified_order(service):
    sid = verified(service)

    requested = turn(service, sid, "关于订单 o：请帮我转人工客服", SessionStateStore())

    assert requested["task_status"] == "handoff_created"
    assert requested["ticket"]["order_id"] == "o"


def test_cancel_requires_confirmation_then_store_reads_executed_state(service):
    sid = verified(service)
    store = SessionStateStore()
    waiting = turn(service, sid, "取消订单 o，因为误下单", store)
    assert waiting["task_status"] == "pending_confirmation"
    assert service.order(sid, "o")["status"] == "pending"

    confirmed = turn(
        service,
        sid,
        "确认",
        store,
        request_id=waiting["request_id"],
    )
    assert confirmed["task_status"] == "executed"
    assert confirmed["execution_result"]["after_status"] == "cancelled"
    assert service.order(sid, "o")["status"] == "cancelled"
    with Session(service.engine) as db:
        row = db.get(OrderRow, "o")
        assert row.status == "cancelled"
        assert row.row_version == 2


def test_scoped_cancel_clarifies_reason_then_requires_confirmation(service):
    sid = verified(service)
    store = SessionStateStore()
    first = turn(service, sid, "关于订单 o：取消这个订单吧", store)
    assert first["task_status"] in {"clarification", "needs_clarification"}
    assert "取消原因" in first["final_response"]
    assert first["task_status"] == "needs_clarification"
    assert "无法解决" not in first["final_response"]
    assert first["ticket"] is None
    assert service.order(sid, "o")["status"] == "pending"

    repeated = turn(service, sid, "关于订单 o：取消订单", store)
    assert "取消原因" in repeated["final_response"]
    assert "无法解决" not in repeated["final_response"]
    assert service.order(sid, "o")["status"] == "pending"

    ready = turn(service, sid, "关于订单 o：因为下错单", store)
    assert ready["task_status"] == "pending_confirmation"
    assert "待确认" in ready["final_response"]
    assert service.order(sid, "o")["status"] == "pending"

    confirmed = turn(service, sid, "确认", store, request_id=ready["request_id"])
    assert confirmed["task_status"] == "executed"
    assert service.order(sid, "o")["status"] == "cancelled"


def test_long_lived_session_can_cancel_or_withdraw_without_route_limit(service):
    sid = verified(service)
    store = SessionStateStore()
    for _ in range(7):
        turn(service, sid, "关于订单 o：取消订单", store)
    store = SessionStateStore()  # Recover the same session from its persisted checkpoint.
    asking = turn(service, sid, "关于订单 o：取消这个订单", store)
    assert asking["task_status"] in {"clarification", "needs_clarification"}
    assert "取消原因" in asking["final_response"]
    assert "route_limit" not in asking["final_response"]
    declined = turn(service, sid, "关于订单 o：不想取消了", store)
    assert declined["task_status"] == "confirmation_rejected"
    assert "订单未作修改" in declined["final_response"]
    assert service.order(sid, "o")["status"] == "pending"
    resumed = turn(service, sid, "关于订单 o：取消订单", store)
    assert "取消原因" in resumed["final_response"]


def test_cancel_reason_followup_accepts_common_typo(service):
    sid = verified(service)
    store = SessionStateStore()
    first = turn(service, sid, "关于订单 o：取消这个订单", store)
    assert "取消原因" in first["final_response"]
    assert first["task_status"] == "needs_clarification"
    assert first["resolution_proposal"]["status"] == "needs_clarification"
    assert service.order(sid, "o")["status"] == "pending"

    second = turn(service, sid, "关于订单 o：不在需要了", store)
    assert second["task_status"] == "pending_confirmation"
    assert second["pending_confirmation"]["proposed_parameters"]["reason"] == "no longer needed"
    assert service.order(sid, "o")["status"] == "pending"
