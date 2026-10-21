import json

import httpx
import pytest

from app import agent


@pytest.fixture(autouse=True)
def isolated_diagnostics(tmp_path, monkeypatch):
    monkeypatch.setattr(agent.config, "RUNTIME", tmp_path)


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        {},
        {"choices": []},
        {"choices": [None]},
        {"choices": [{"message": None}]},
        {"choices": [{"message": {"content": []}}]},
        {"choices": [{"message": {"content": "{}"}}]},
        {"choices": [{"message": {"content": 42}}]},
    ],
)
def test_malformed_provider_response_fails_cleanly(monkeypatch, body):
    real_client = httpx.Client
    attempts = []

    def handler(request):
        attempts.append(request)
        return httpx.Response(200, json=body)

    monkeypatch.setenv("LLM_API_KEY", "synthetic-test-key")
    monkeypatch.setattr(
        agent.httpx,
        "Client",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    with pytest.raises(agent.ModelError, match="有效结构"):
        agent.call_model(agent.split_turns("客户：你好"))
    assert len(attempts) == 2


def test_provider_can_repair_its_first_invalid_response(monkeypatch):
    real_client = httpx.Client
    attempts = []

    def handler(request):
        attempts.append(request)
        payload = (
            "{}"
            if len(attempts) == 1
            else json.dumps(
                {"fields": {}, "signals": {}, "refusal": {}, "uncertainty": []}
            )
        )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": payload}}],
                "model": "test-model",
            },
        )

    monkeypatch.setenv("LLM_API_KEY", "synthetic-test-key")
    monkeypatch.setattr(
        agent.httpx,
        "Client",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    _, metadata = agent.call_model(agent.split_turns("客户：你好"))
    assert metadata["attempts"] == 2 and metadata["provider_model"] == "test-model"


def bind_provider(monkeypatch, handler):
    real_client = httpx.Client
    monkeypatch.setenv("LLM_API_KEY", "synthetic-secret-never-log")
    monkeypatch.setattr(agent.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        agent.httpx,
        "Client",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )


def valid_response(**choice_overrides):
    choice = {
        "message": {
            "content": json.dumps(
                {"fields": {}, "signals": {}, "refusal": {}, "uncertainty": []}
            )
        },
        "finish_reason": "stop",
    }
    choice.update(choice_overrides)
    return httpx.Response(200, json={"choices": [choice], "model": "test-model"})


def test_truncated_reasoning_output_is_regenerated_with_more_budget(
    monkeypatch, tmp_path
):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return valid_response(
                finish_reason="length",
                message={
                    "content": '{"fields":',
                    "reasoning_content": "private-reasoning",
                },
            )
        return valid_response()

    bind_provider(monkeypatch, handler)
    _, meta = agent.call_model(agent.split_turns("客户：private-transcript"))
    assert meta["attempts"] == 2
    assert calls[1]["max_tokens"] > calls[0]["max_tokens"]
    assert calls[1]["messages"] == calls[0]["messages"]
    log = (tmp_path / "diagnostics.jsonl").read_text(encoding="utf-8")
    assert "OUTPUT_TRUNCATED" in log
    assert all(
        value not in log
        for value in (
            "private-transcript",
            "private-reasoning",
            "synthetic-secret-never-log",
        )
    )


def test_endless_truncation_fails_without_creating_partial_extraction(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return valid_response(finish_reason="length")

    bind_provider(monkeypatch, handler)
    with pytest.raises(agent.ModelError) as err:
        agent.call_model(agent.split_turns("客户：测试"))
    assert err.value.code == "MODEL_TRUNCATED" and len(calls) == 2


def test_endpoint_fallback_still_allows_json_repair(monkeypatch):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(404)
        if len(calls) == 2:
            return valid_response(message={"content": "{}"})
        return valid_response()

    bind_provider(monkeypatch, handler)
    monkeypatch.setattr(agent.config, "BASE_URL", "https://synthetic.invalid")
    _, meta = agent.call_model(agent.split_turns("客户：测试"))
    assert meta["attempts"] == 3
    assert calls[0].endswith("/v1/chat/completions") and calls[-1].endswith(
        "/chat/completions"
    )


def test_json_mode_compatibility_keeps_strict_local_validation(monkeypatch):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return httpx.Response(400, json={"error": "response_format unsupported"})
        return valid_response()

    bind_provider(monkeypatch, handler)
    agent.call_model(agent.split_turns("客户：测试"))
    assert "response_format" in calls[0] and "response_format" not in calls[1]


@pytest.mark.parametrize("status", [429, 502, 503])
def test_temporary_provider_errors_are_retried(monkeypatch, status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status) if len(calls) < 3 else valid_response()

    bind_provider(monkeypatch, handler)
    _, meta = agent.call_model(agent.split_turns("客户：测试"))
    assert len(calls) == meta["attempts"] == 3


def test_auth_error_is_not_retried_or_exposed_verbatim(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401, text="upstream-private-details")

    bind_provider(monkeypatch, handler)
    with pytest.raises(agent.ModelError) as err:
        agent.call_model(agent.split_turns("客户：测试"))
    assert err.value.code == "MODEL_AUTH" and len(calls) == 1
    assert "upstream-private-details" not in str(err.value)


def test_timeout_is_bounded_and_distinguished_from_json_errors(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("synthetic timeout", request=request)

    bind_provider(monkeypatch, handler)
    with pytest.raises(agent.ModelError) as err:
        agent.call_model(agent.split_turns("客户：测试"))
    assert err.value.code == "MODEL_TIMEOUT" and len(calls) == 3


def test_null_unknowns_and_integer_strings_are_accepted_without_guessing():
    payload = {
        "fields": {
            "phone": {"value": None, "quote": None, "turn_id": None},
            "company_name": None,
        },
        "signals": {"pain": {"strength": "2", "quote": "出图慢", "turn_id": "T1"}},
        "refusal": None,
        "uncertainty": None,
    }
    ex = agent.normalize_extraction(payload)
    assert ex.fields["phone"].value == ex.fields["company_name"].value == ""
    assert ex.signals["pain"].strength == 2 and ex.uncertainty == []
    payload["signals"]["pain"]["strength"] = "high"
    with pytest.raises(ValueError):
        agent.normalize_extraction(payload)
