"""The agent itself: a standard LangGraph ReAct loop (model + tools),
built fresh per request rather than as a long-lived module-level object —
`get_chat_model()` already checks settings at call time (Claude vs Ollama
fallback), so building the graph per-request keeps that check live
instead of baking in whichever provider was active at import time.
"""

from langchain.agents import create_agent

from app.agent.llm import get_chat_model
from app.agent.tools import ALL_TOOLS

SYSTEM_PROMPT = (
    "You are the 3W network operations assistant. You can look up current "
    "and forecasted sector congestion status, and current CAPEX equipment "
    "pricing. Always cite the zoom_sector_id and year/week you looked up. "
    "If a lookup returns an error, say so plainly rather than guessing."
)


def build_agent():
    return create_agent(get_chat_model(), ALL_TOOLS, system_prompt=SYSTEM_PROMPT)


def run_agent(message: str) -> str:
    agent = build_agent()
    result = agent.invoke({"messages": [{"role": "user", "content": message}]})
    return result["messages"][-1].content
