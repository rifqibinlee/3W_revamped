import pytest
from langchain_anthropic import ChatAnthropic

from app.agent import llm


def test_raises_when_no_anthropic_key(monkeypatch) -> None:
    monkeypatch.setattr(llm.settings, "anthropic_api_key", None)
    assert llm.using_claude() is False
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        llm.get_chat_model()


def test_uses_claude_when_anthropic_key_present(monkeypatch) -> None:
    monkeypatch.setattr(llm.settings, "anthropic_api_key", "sk-ant-test-key")
    assert llm.using_claude() is True
    assert isinstance(llm.get_chat_model(), ChatAnthropic)
