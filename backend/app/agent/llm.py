"""LLM provider selection: Claude is primary, Ollama is the automatic
local-dev fallback (no API key, no cost) when ANTHROPIC_API_KEY isn't
configured.

Both `ChatAnthropic` and `ChatOllama` implement LangChain's standard
chat-model interface — including `.bind_tools()` for the agent's
function-calling tools — so the rest of the agent code (graph, tool
definitions, prompts) never needs to know which provider is active.
"""

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_ollama import ChatOllama, OllamaEmbeddings

from app.core.config import settings


def get_chat_model() -> BaseChatModel:
    if settings.anthropic_api_key:
        return ChatAnthropic(model=settings.anthropic_model, api_key=settings.anthropic_api_key)
    return ChatOllama(model=settings.ollama_model, base_url=settings.ollama_base_url)


def get_embeddings() -> OllamaEmbeddings:
    """Embeddings stay on Ollama even when Claude is the chat model —
    Anthropic doesn't offer an embeddings API, and keeping ingestion
    fully local avoids per-document API costs regardless of which chat
    provider is active."""
    return OllamaEmbeddings(model=settings.ollama_embedding_model, base_url=settings.ollama_base_url)


def using_claude() -> bool:
    return bool(settings.anthropic_api_key)
