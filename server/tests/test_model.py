import httpx
import pytest
from pydantic import BaseModel
import model


class Output(BaseModel):
    answer: str


@pytest.mark.asyncio
async def test_json_validation_retry_and_request_shape(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fixture-key")
    calls = []
    real_client = httpx.AsyncClient
    def handler(request):
        import json
        body = json.loads(request.content)
        calls.append(body)
        content = '{"answer":4}' if len(calls) == 1 else '{"answer":"4"}'
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": content}}]})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler)))
    result = await model.ask("输出 JSON", {"stem": "2+2"}, Output)
    assert result.answer == "4"
    assert len(calls) == 2
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert calls[0]["messages"][0]["role"] == "system"


@pytest.mark.asyncio
async def test_truncation_not_accepted(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fixture-key")
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={
            "choices": [{"finish_reason": "length", "message": {"content": '{"answer":"4"}'}}]}))))
    with pytest.raises(RuntimeError, match="上限"):
        await model.ask("输出 JSON", {}, Output)
