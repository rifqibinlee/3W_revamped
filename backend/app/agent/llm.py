"""LLM provider: Claude (Anthropic) only. Ollama removed — no local model
required. Set ANTHROPIC_API_KEY in the environment or .env file."""

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel

from app.core.config import settings


def get_chat_model() -> BaseChatModel:
    if not settings.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Add it to your .env file or EC2 environment."
        )
    return ChatAnthropic(model=settings.anthropic_model, api_key=settings.anthropic_api_key)


def using_claude() -> bool:
    return bool(settings.anthropic_api_key)
