import httpx
import pytest
from app.config import Settings
from app.llm import OpenAICompatibleProvider, ProviderError


def test_provider_requires_key():
    with pytest.raises(ProviderError, match="agent_api_key_missing"):
        OpenAICompatibleProvider(
            Settings(
                _env_file=None,
                agent_api_key=None,
                openai_api_key=None,
                llm_api_key=None,
            )
        )


def test_provider_tool_call_and_usage():
    def respond(request):
        assert request.url.path == "/v1/chat/completions"
        body = request.read().decode()
        assert '"parallel_tool_calls":false' in body
        assert '"max_tokens":1024' in body
        return httpx.Response(
            200,
            json={
                "model": "test-model",
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "get_order",
                                        "arguments": '{"order_id":"o"}',
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    settings = Settings(
        _env_file=None,
        agent_api_key="unit-test-only",
        agent_model="test-model",
        agent_base_url="https://example.invalid/v1",
    )
    result = OpenAICompatibleProvider(settings, httpx.MockTransport(respond)).complete(
        [{"role": "user", "content": "order?"}], []
    )
    assert result.tool_calls[0].arguments == {"order_id": "o"}
    assert result.usage["total_tokens"] == 15


def test_provider_sanitizes_http_failure():
    def fail(request):
        return httpx.Response(401, text="secret diagnostic")

    settings = Settings(
        _env_file=None, agent_api_key="unit-test-only", agent_base_url="https://example.invalid/v1"
    )
    with pytest.raises(ProviderError, match="model_request_failed") as error:
        OpenAICompatibleProvider(settings, httpx.MockTransport(fail)).complete([], [])
    assert "secret diagnostic" not in str(error.value)


def test_legacy_deepseek_settings_use_existing_env_names():
    def respond(request):
        body = request.read().decode()
        assert '"model":"deepseek-v4-flash"' in body
        assert '"thinking":{"type":"disabled"}' in body
        assert '"seed"' not in body
        assert '"parallel_tool_calls"' not in body
        return httpx.Response(
            200, json={"model": "deepseek-v4-flash", "choices": [{"message": {"content": "ok"}}]}
        )

    settings = Settings(
        _env_file=None,
        llm_api_key="unit-test-only",
        llm_model_id="deepseek-v4-flash",
        llm_base_url="https://api.deepseek.com",
    )
    result = OpenAICompatibleProvider(settings, httpx.MockTransport(respond)).complete(
        [{"role": "user", "content": "ping"}], []
    )
    assert result.content == "ok"
