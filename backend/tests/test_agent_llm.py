from langchain_anthropic import ChatAnthropic
from langchain_ollama import ChatOllama

from app.agent import llm


def test_falls_back_to_ollama_when_no_anthropic_key(monkeypatch) -> None:
    monkeypatch.setattr(llm.settings, "anthropic_api_key", None)
    assert llm.using_claude() is False
    assert isinstance(llm.get_chat_model(), ChatOllama)


def test_uses_claude_when_anthropic_key_present(monkeypatch) -> None:
    monkeypatch.setattr(llm.settings, "anthropic_api_key", "sk-ant-test-key")
    assert llm.using_claude() is True
    assert isinstance(llm.get_chat_model(), ChatAnthropic)
