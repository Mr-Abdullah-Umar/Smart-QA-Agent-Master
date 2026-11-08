"""API-key provider used by the CLI: configuration, request shapes, and error handling."""

import asyncio
import io
import json
import urllib.error

import pytest

import qa_engine.llm.http_provider as http_provider
from qa_engine.llm.http_provider import HttpLLMProvider, LLMConfigError

MESSAGES = [
    {"role": "system", "content": "Be precise."},
    {"role": "user", "content": "Design tests."},
]


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch):
    real = http_provider.validate_destination_url
    monkeypatch.setattr(
        http_provider,
        "validate_destination_url",
        lambda url, domains, resolve_dns=False: real(url, domains, resolve_dns=False),
    )


def test_from_env_is_optional_and_validates():
    assert HttpLLMProvider.from_env({}) is None
    assert HttpLLMProvider.from_env({"QA_AI_PROVIDER": "none"}) is None
    with pytest.raises(LLMConfigError, match="QA_AI_API_KEY"):
        HttpLLMProvider.from_env({"QA_AI_PROVIDER": "openai", "QA_AI_MODEL": "m"})
    with pytest.raises(LLMConfigError, match="QA_AI_MODEL"):
        HttpLLMProvider.from_env({"QA_AI_PROVIDER": "openai", "QA_AI_API_KEY": "k"})
    with pytest.raises(LLMConfigError, match="Unknown AI provider"):
        HttpLLMProvider.from_env({"QA_AI_PROVIDER": "acme", "QA_AI_API_KEY": "k"})
    with pytest.raises(LLMConfigError, match="QA_AI_BASE_URL"):
        HttpLLMProvider("azure-openai", "k", "deploy")


def test_endpoints_must_be_https_and_public():
    with pytest.raises(LLMConfigError, match="https"):
        HttpLLMProvider("openai-compatible", "k", "m", base_url="http://llm.example/v1")
    with pytest.raises(LLMConfigError, match="network policy"):
        HttpLLMProvider("openai-compatible", "k", "m", base_url="https://127.0.0.1/v1")


def test_github_models_accepts_github_token():
    provider = HttpLLMProvider.from_env(
        {"QA_AI_PROVIDER": "github-models", "GITHUB_TOKEN": "ghs_x", "QA_AI_MODEL": "openai/gpt"}
    )
    url, headers, body = provider.build_request(MESSAGES, 0.2)
    assert url == "https://models.github.ai/inference/chat/completions"
    assert headers["Authorization"] == "Bearer ghs_x"
    assert body["model"] == "openai/gpt"


def test_request_shapes_per_provider():
    url, headers, body = HttpLLMProvider("openai", "sk", "gpt-x").build_request(MESSAGES, 0.1)
    assert url == "https://api.openai.com/v1/chat/completions"
    assert body == {"messages": MESSAGES, "temperature": 0.1, "model": "gpt-x"}

    azure = HttpLLMProvider(
        "azure-openai", "az", "my deploy", base_url="https://res.openai.azure.com/"
    )
    url, headers, body = azure.build_request(MESSAGES, None)
    assert url == (
        "https://res.openai.azure.com/openai/deployments/my%20deploy/chat/completions"
        "?api-version=2024-10-21"
    )
    assert headers["api-key"] == "az" and "Authorization" not in headers
    assert "model" not in body and "temperature" not in body

    url, headers, body = HttpLLMProvider("anthropic", "ak", "claude-x").build_request(MESSAGES, 0)
    assert url == "https://api.anthropic.com/v1/messages"
    assert headers["x-api-key"] == "ak"
    assert body["system"] == "Be precise."
    assert body["messages"] == [{"role": "user", "content": "Design tests."}]
    assert body["temperature"] == 0


def test_parse_content():
    assert HttpLLMProvider.parse_content("openai", {"choices": [{"message": {"content": "x"}}]})
    anthropic = {"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}
    assert HttpLLMProvider.parse_content("anthropic", anthropic) == "ab"
    with pytest.raises(RuntimeError, match="no message content"):
        HttpLLMProvider.parse_content("openai", {"choices": []})


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_chat_retries_without_rejected_temperature(monkeypatch):
    bodies = []

    def fake_urlopen(request, timeout):
        body = json.loads(request.data)
        bodies.append(body)
        if "temperature" in body:
            raise urllib.error.HTTPError(
                request.full_url,
                400,
                "bad",
                {},
                io.BytesIO(b'{"error": "Unsupported value: temperature"}'),
            )
        return _Response(json.dumps({"choices": [{"message": {"content": "done"}}]}).encode())

    monkeypatch.setattr(http_provider.urllib.request, "urlopen", fake_urlopen)
    provider = HttpLLMProvider("openai", "sk", "reasoner")
    result = asyncio.run(provider.chat(MESSAGES, temperature=0.3))
    assert result.content == "done"
    assert len(bodies) == 2 and "temperature" not in bodies[1]


def test_investigations_can_use_a_cheaper_model(monkeypatch):
    models = []

    def fake_urlopen(request, timeout):
        models.append(json.loads(request.data)["model"])
        return _Response(json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode())

    monkeypatch.setattr(http_provider.urllib.request, "urlopen", fake_urlopen)
    provider = HttpLLMProvider.from_env(
        {
            "QA_AI_PROVIDER": "openai",
            "QA_AI_API_KEY": "sk",
            "QA_AI_MODEL": "big-model",
            "QA_AI_INVESTIGATION_MODEL": "small-model",
        }
    )
    asyncio.run(provider.chat(MESSAGES))
    asyncio.run(provider.chat_with_purpose("design", MESSAGES))
    asyncio.run(provider.chat_with_purpose("investigation", MESSAGES))
    assert models == ["big-model", "big-model", "small-model"]
    plain = HttpLLMProvider("openai", "sk", "big-model")
    assert plain.model_for("investigation") == "big-model"


def test_http_errors_are_reported_without_the_key(monkeypatch):
    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 401, "no", {}, io.BytesIO(b'{"error": "invalid api key"}')
        )

    monkeypatch.setattr(http_provider.urllib.request, "urlopen", fake_urlopen)
    provider = HttpLLMProvider("openai", "sk-secret-value", "m")
    with pytest.raises(RuntimeError) as info:
        asyncio.run(provider.chat(MESSAGES))
    assert "HTTP 401" in str(info.value)
    assert "sk-secret-value" not in str(info.value)
